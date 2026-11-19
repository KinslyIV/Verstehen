import json
import tomllib
from pathlib import Path


def check_versions(root: Path) -> list[str]:
    version = tomllib.loads((root / "backend/pyproject.toml").read_text())["project"][
        "version"
    ]
    cargo = tomllib.loads((root / "app/src-tauri/Cargo.toml").read_text())["package"][
        "version"
    ]
    tauri = json.loads((root / "app/src-tauri/tauri.conf.json").read_text())["version"]
    if version == cargo == tauri:
        return []
    return [
        "Set Cargo.toml and tauri.conf.json versions to backend/pyproject.toml's version."
    ]


if __name__ == "__main__":
    errors = check_versions(Path(__file__).resolve().parents[1])
    for error in errors:
        print(error)
    raise SystemExit(bool(errors))
