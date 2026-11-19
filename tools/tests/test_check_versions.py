import json
from pathlib import Path

from tools.check_versions import check_versions


def test_package_versions_must_match_backend(tmp_path: Path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "app/src-tauri").mkdir(parents=True)
    (tmp_path / "backend/pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    (tmp_path / "app/src-tauri/Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
    config = tmp_path / "app/src-tauri/tauri.conf.json"
    config.write_text(json.dumps({"version": "0.1.0"}))
    assert check_versions(tmp_path) == []
    config.write_text(json.dumps({"version": "0.2.0"}))
    assert check_versions(tmp_path) == [
        "Set Cargo.toml and tauri.conf.json versions to backend/pyproject.toml's version."
    ]
