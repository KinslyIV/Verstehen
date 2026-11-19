use std::{path::PathBuf, sync::Mutex, time::Duration};
use tauri::{Manager, State};
use tauri_plugin_dialog::{DialogExt, MessageDialogKind};
use tauri_plugin_shell::{
    ShellExt,
    process::{CommandChild, CommandEvent},
};
use tokio::sync::oneshot;

#[derive(Clone, serde::Serialize)]
struct Connection {
    port: u16,
    token: String,
}

#[derive(Default)]
struct Sidecar {
    connection: Mutex<Option<Connection>>,
    child: Mutex<Option<CommandChild>>,
}

#[tauri::command]
fn sidecar_connection(state: State<'_, Sidecar>) -> Result<Connection, String> {
    state
        .connection
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or_else(|| "Sidecar is not ready".into())
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

async fn start(app: &tauri::AppHandle) -> Result<(), String> {
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
    *app.state::<Sidecar>()
        .child
        .lock()
        .map_err(|e| e.to_string())? = Some(child);
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
    *app.state::<Sidecar>()
        .connection
        .lock()
        .map_err(|e| e.to_string())? = Some(Connection { port, token });
    app.get_webview_window("main")
        .ok_or("Main window missing")?
        .show()
        .map_err(|e| e.to_string())
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar::default())
        .invoke_handler(tauri::generate_handler![sidecar_connection])
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let result = tokio::time::timeout(Duration::from_secs(30), start(&handle)).await;
                if !matches!(result, Ok(Ok(()))) {
                    stop(&handle);
                    handle
                        .dialog()
                        .message(format!(
                            "The sidecar didn't start. See {}",
                            log_path().display()
                        ))
                        .title("Verstehen")
                        .kind(MessageDialogKind::Error)
                        .blocking_show();
                    handle.exit(1);
                }
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
