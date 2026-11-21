from pathlib import Path

from fastapi.testclient import TestClient

from verstehen.app import create_app
from verstehen.config import Settings
from verstehen.providers.claude_code import binary


def test_status_and_catalog_use_safe_metadata(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(binary, "resolve_binary", lambda: None)
    with TestClient(
        create_app(Settings(tmp_path)), base_url="http://localhost"
    ) as client:
        status = client.get("/api/accounts/claude-code").json()
        assert status["state"] == "not_installed"
        assert status["minimum_version"] == binary.MINIMUM_VERSION
        assert status["tested_version"] == binary.TESTED_VERSION
        catalog = client.get("/api/models").json()
        assert catalog["accounts"][0]["account"]["state"] == "not_installed"
        assert catalog["accounts"][0]["models"] == []
