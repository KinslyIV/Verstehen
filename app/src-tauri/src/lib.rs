use std::{
    path::PathBuf,
    sync::Mutex,
    time::{Duration, Instant},
};
use tauri::{Manager, State};
use tauri_plugin_shell::{
    ShellExt,
    process::{CommandChild, CommandEvent},
};
use tokio::sync::{oneshot, watch};

#[derive(Clone, serde::Serialize)]
struct Connection {
    port: u16,
    token: String,
}

#[derive(Clone)]
enum Startup {
    Starting,
    Ready(Connection),
    Failed(String),
}

struct Sidecar {
    startup: watch::Sender<Startup>,
    child: Mutex<Option<CommandChild>>,
    began: Instant,
}

impl Sidecar {
    fn log_timing(&self, milestone: &str) {
        eprintln!(
            "startup {milestone}: {} ms",
            self.began.elapsed().as_millis()
        );
    }
}

#[tauri::command]
async fn sidecar_connection(state: State<'_, Sidecar>) -> Result<Connection, String> {
    let mut startup = state.startup.subscribe();
    let settled = startup
        .wait_for(|startup| !matches!(startup, Startup::Starting))
        .await
        .map_err(|_| "Sidecar connection closed".to_string())?;
    match settled.clone() {
        Startup::Ready(connection) => Ok(connection),
        Startup::Failed(reason) => Err(reason),
        Startup::Starting => Err("Sidecar is not ready".into()),
    }
}

#[tauri::command]
fn startup_mark(state: State<'_, Sidecar>, name: String) {
    if name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        state.log_timing(&format!("ui {name}"));
    }
}

fn stop(app: &tauri::AppHandle) {
    if let Ok(mut child) = app.state::<Sidecar>().child.lock()
        && let Some(child) = child.take()
    {
        let _ = child.kill();
    }
}

fn log_path() -> PathBuf {
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default();
    let directory = std::env::var("VERSTEHEN_DATA_DIR")
        .map(|value| {
            if value == "~" {
                home.clone()
            } else if let Some(rest) = value.strip_prefix("~/") {
                home.join(rest)
            } else {
                PathBuf::from(value)
            }
        })
        .unwrap_or_else(|_| home.join(".local/share/verstehen"));
    directory.join("logs/verstehen.log")
}

async fn start(app: &tauri::AppHandle) -> Result<Connection, String> {
    let mut random = [0u8; 32];
    getrandom::fill(&mut random).map_err(|e| e.to_string())?;
    let token: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
    let (mut events, child) = app
        .shell()
        .sidecar("verstehen-sidecar")
        .map_err(|e| e.to_string())?
        .env("VERSTEHEN_DESKTOP", "1")
        .env("VERSTEHEN_TOKEN", &token)
        .env("VERSTEHEN_PORT", "0")
        .spawn()
        .map_err(|e| e.to_string())?;
    let state = app.state::<Sidecar>();
    *state.child.lock().map_err(|e| e.to_string())? = Some(child);
    state.log_timing("sidecar_spawned");
    let (sender, receiver) = oneshot::channel();
    let (exit_sender, mut exited) = oneshot::channel();
    tauri::async_runtime::spawn(async move {
        let mut sender = Some(sender);
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    if let Some(sender) = sender.take() {
                        let port = serde_json::from_slice::<serde_json::Value>(&line)
                            .ok()
                            .and_then(|v| v["port"].as_u64())
                            .and_then(|p| u16::try_from(p).ok())
                            .filter(|p| *p != 0);
                        let _ = sender.send(port.ok_or("Invalid sidecar port line"));
                    }
                }
                CommandEvent::Stderr(line) => eprintln!("{}", String::from_utf8_lossy(&line)),
                CommandEvent::Error(error) => eprintln!("Sidecar: {error}"),
                CommandEvent::Terminated(_) => break,
                _ => {}
            }
        }
        let _ = exit_sender.send(());
    });
    let port = receiver
        .await
        .map_err(|_| "Sidecar exited before announcing its port")??;
    state.log_timing("sidecar_port");
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(1))
        .build()
        .map_err(|e| e.to_string())?;
    loop {
        if let Ok(response) = client
            .get(format!("http://127.0.0.1:{port}/api/health"))
            .header("x-verstehen-token", &token)
            .send()
            .await
            && response.status() == reqwest::StatusCode::OK
        {
            break;
        }
        tokio::select! {
            _ = &mut exited => return Err("Sidecar exited before becoming healthy".into()),
            _ = tokio::time::sleep(Duration::from_millis(100)) => {}
        }
    }
    state.log_timing("sidecar_healthy");
    Ok(Connection { port, token })
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(Sidecar {
            startup: watch::channel(Startup::Starting).0,
            child: Mutex::new(None),
            began: Instant::now(),
        })
        .invoke_handler(tauri::generate_handler![sidecar_connection, startup_mark])
        .setup(|app| {
            let handle = app.handle().clone();
            handle.state::<Sidecar>().log_timing("window_created");
            tauri::async_runtime::spawn(async move {
                let result = tokio::time::timeout(Duration::from_secs(30), start(&handle)).await;
                let startup = match result {
                    Ok(Ok(connection)) => Startup::Ready(connection),
                    failure => {
                        stop(&handle);
                        let reason = match failure {
                            Ok(Err(reason)) => reason,
                            _ => "it took longer than 30 seconds".to_string(),
                        };
                        Startup::Failed(format!(
                            "The sidecar didn't start: {reason}. See {}",
                            log_path().display()
                        ))
                    }
                };
                handle.state::<Sidecar>().startup.send_replace(startup);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Failed to build Verstehen");
    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            stop(app);
        }
    });
}
