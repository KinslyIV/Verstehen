import html
from pathlib import Path

PAGE_STYLE = (
    "body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
    "background:#09090b;color:#fafafa;font:16px system-ui,sans-serif;text-align:center}"
    "p{color:#a1a1aa;font-size:14px;line-height:1.5;max-width:28rem}h1{font-size:18px}"
)


def starting_page() -> str:
    return f"<style>{PAGE_STYLE}</style><p role='status'>Starting Verstehen…</p>"


def failure_page(reason: str, log_path: Path) -> str:
    message = html.escape(f"The server didn't start: {reason}. See {log_path}")
    return (
        f"<style>{PAGE_STYLE}</style><div role='alert'><h1>Verstehen couldn't start</h1>"
        f"<p>{message}</p><p>Close this window and open Verstehen again.</p></div>"
    )
