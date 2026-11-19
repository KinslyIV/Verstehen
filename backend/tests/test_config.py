from pathlib import Path

import pytest

from verstehen.config import load_settings


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in ("DESKTOP", "TOKEN", "PORT", "ALLOWED_HOSTS", "FAKE_MODEL"):
        monkeypatch.delenv(f"VERSTEHEN_{name}", raising=False)
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path / "data"))


def test_desktop_flag_without_token_refuses_to_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_DESKTOP", "1")
    with pytest.raises(ValueError, match="at least 64"):
        load_settings()


def test_short_token_refuses_to_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_DESKTOP", "1")
    monkeypatch.setenv("VERSTEHEN_TOKEN", "x" * 63)
    with pytest.raises(ValueError, match="at least 64"):
        load_settings()


def test_token_without_desktop_flag_refuses_to_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_TOKEN", "x" * 64)
    with pytest.raises(ValueError, match="requires VERSTEHEN_DESKTOP=1"):
        load_settings()


def test_settings_read_environment_once(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_ALLOWED_HOSTS", " MY.EXAMPLE, other.example ,")
    monkeypatch.setenv("VERSTEHEN_PORT", "12345")
    settings = load_settings()
    monkeypatch.setenv("VERSTEHEN_PORT", "54321")
    assert settings.port == 12345
    assert settings.allowed_hosts == ("my.example", "other.example")
    assert settings.data_dir.is_dir()


def test_missing_fake_model_script_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("VERSTEHEN_FAKE_MODEL", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="Invalid fake-model script.*missing.json"):
        load_settings()
