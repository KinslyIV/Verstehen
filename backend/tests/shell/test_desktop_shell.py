import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from verstehen.desktop.links import navigation_for
from verstehen.desktop.pages import failure_page, starting_page
from verstehen.desktop.server import DesktopServer, ServerStartupError

ORIGIN = "http://127.0.0.1:28420"
PROBE = Path(__file__).with_name("desktop_probe.py")
LAZY_PROBE = Path(__file__).with_name("lazy_imports_probe.py")


@pytest.mark.parametrize(
    "url",
    [
        "https://auth.openai.com/oauth/authorize?client_id=x&state=y",
        "https://code.claude.com/docs/en/setup",
    ],
)
def test_the_two_allowed_links_open_outside_the_window(url: str):
    assert navigation_for(url, ORIGIN, is_main_frame=True) == "open-externally"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://auth.openai.com.evil.example/x",
        "http://auth.openai.com/x",
        "https://code.claude.com/docs/en/setup?x=1",
        "https://code.claude.com/docs/en/other",
        "file:///etc/passwd",
        "http://127.0.0.1:9999/",
        "http://127.0.0.1:28420.evil.example/",
        "javascript:alert(1)",
    ],
)
def test_every_other_navigation_leaves_nothing_loaded(url: str):
    assert navigation_for(url, ORIGIN, is_main_frame=True) == "block"


def test_the_window_stays_on_its_own_origin_and_frames_load_freely():
    assert navigation_for(ORIGIN + "/", ORIGIN, is_main_frame=True) == "load"
    assert navigation_for(ORIGIN + "/session/1", ORIGIN, is_main_frame=True) == "load"
    assert navigation_for("about:blank", None, is_main_frame=True) == "load"
    assert navigation_for("https://example.com/", ORIGIN, is_main_frame=False) == "load"
    assert navigation_for(ORIGIN + "/", None, is_main_frame=True) == "block"


def test_the_starting_and_failure_pages_say_what_happened():
    assert "Starting Verstehen…" in starting_page()
    failure = failure_page("<boom>", Path("/data/logs/verstehen.log"))
    assert "Verstehen couldn't start" in failure
    assert "&lt;boom&gt;" in failure
    assert "/data/logs/verstehen.log" in failure


def test_a_server_that_cannot_start_reports_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERSTEHEN_SPA_DIR", str(tmp_path / "missing"))
    server = DesktopServer(on_exit=lambda: None)
    with pytest.raises(ServerStartupError, match="missing"):
        server.start()
    server.stop()


def test_a_server_that_is_not_healthy_in_time_reports_the_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERSTEHEN_SPA_DIR", str(tmp_path))
    server = DesktopServer(on_exit=lambda: None)
    server.start()
    try:
        with pytest.raises(ServerStartupError, match="took longer than 0 seconds"):
            server.wait_until_healthy(timeout=0)
        server.wait_until_healthy()
    finally:
        server.stop()


def run_probe(
    script: Path, tmp_path: Path, spa_dir: Path, *args: str, **extra_env: str
) -> dict:
    (tmp_path / "saved").mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PROBE_SAVE_DIR": str(tmp_path / "saved"),
        **extra_env,
        "VERSTEHEN_DATA_DIR": str(tmp_path / "data"),
        "VERSTEHEN_SPA_DIR": str(spa_dir),
        "QT_QPA_PLATFORM": "offscreen",
        "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --no-sandbox",
    }
    done = subprocess.run(
        [sys.executable, str(script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.splitlines()[-1])


@pytest.mark.slow
def test_the_window_loads_the_app_with_the_token_cookie(tmp_path: Path):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text(
        "<body><p id=p>loading</p><script>"
        "fetch('/api/health').then(r => r.status).then(s => "
        "document.body.innerText = 'health ' + s);"
        "window.open('https://code.claude.com/docs/en/setup', '_blank', 'noopener,noreferrer');"
        "window.open('https://example.com/', '_blank');"
        "function save(name, content) {"
        "  const url = URL.createObjectURL(new Blob([content], { type: 'text/html' }));"
        "  const link = document.createElement('a');"
        "  link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);"
        "}"
        "save('first-demo.html', '<p>first</p>');"
        "setTimeout(() => save('second-demo.html', '<p>second</p>'), 500);"
        "setTimeout(() => { location.href = 'https://example.com/' }, 500);"
        "</script></body>"
    )
    result = run_probe(PROBE, tmp_path, spa, "6")
    assert result["origin"].startswith("http://127.0.0.1:")
    assert result["text"] == "health 200"
    assert result["has_icon"] is True
    assert result["opened"] == ["https://code.claude.com/docs/en/setup"]
    assert result["url"] == result["origin"] + "/"
    assert result["asked"] == ["first-demo.html", "second-demo.html"]
    assert result["saved"] == {"first-demo.html": "<p>first</p>"}
    assert "devtools_url" not in result


@pytest.mark.slow
def test_f12_opens_devtools_only_when_enabled_and_they_close_with_the_window(
    tmp_path: Path,
):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text("<body>app</body>")
    result = run_probe(PROBE, tmp_path, spa, "6", VERSTEHEN_DEVTOOLS="1")
    assert result["devtools_shown"] is True
    assert result["devtools_url"].startswith("devtools://")
    assert result["devtools_closed_with_window"] is True


@pytest.mark.slow
def test_the_window_shows_why_the_server_did_not_start(tmp_path: Path):
    result = run_probe(PROBE, tmp_path, tmp_path / "missing", "4")
    assert "Verstehen couldn't start" in result["text"]
    assert "verstehen.log" in result["text"]


@pytest.mark.slow
def test_lazy_names_resolve_in_the_desktop_process_after_qt_loads(tmp_path: Path):
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text("<body></body>")
    assert run_probe(LAZY_PROBE, tmp_path, spa) == {
        "qt_loaded": True,
        "claude_code_model_is_a_class": True,
        "worker_module_is_a_module": True,
    }
