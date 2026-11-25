from pathlib import Path

import pytest

from verstehen.config import load_settings


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in (
        "SERVER",
        "HOST",
        "TOKEN",
        "PORT",
        "ALLOWED_HOSTS",
        "FAKE_MODEL_SCRIPT",
    ):
        monkeypatch.delenv(f"VERSTEHEN_{name}", raising=False)
    monkeypatch.setenv("VERSTEHEN_DATA_DIR", str(tmp_path / "data"))


def test_desktop_token_must_have_at_least_64_characters():
    with pytest.raises(ValueError, match="at least 64"):
        load_settings(desktop_token="x" * 63)
    settings = load_settings(desktop_token="x" * 64)
    assert settings.desktop is True
    assert settings.token == "x" * 64


def test_desktop_environment_variables_no_longer_exist(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_DESKTOP", "1")
    monkeypatch.setenv("VERSTEHEN_TOKEN", "x" * 64)
    settings = load_settings()
    assert settings.desktop is False
    assert settings.token is None


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
    monkeypatch.setenv("VERSTEHEN_FAKE_MODEL_SCRIPT", str(tmp_path / "missing.json"))
    with pytest.raises(ValueError, match="Invalid fake-model script.*missing.json"):
        load_settings()


@pytest.mark.parametrize("value,enabled", [(None, False), ("0", False), ("1", True)])
def test_provider_event_logging_requires_explicit_one(monkeypatch, value, enabled):
    monkeypatch.delenv("VERSTEHEN_PROVIDER_EVENTS", raising=False)
    if value is not None:
        monkeypatch.setenv("VERSTEHEN_PROVIDER_EVENTS", value)
    assert load_settings().provider_events is enabled


def test_server_mode_defaults_to_loopback_8420(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_SERVER", "1")
    settings = load_settings()
    assert settings.server is True
    assert settings.desktop is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8420


def test_server_mode_accepts_cli_and_env_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERSTEHEN_HOST", "100.64.0.10")
    monkeypatch.setenv("VERSTEHEN_PORT", "9000")
    settings = load_settings(server=True)
    assert settings.server is True
    assert settings.host == "100.64.0.10"
    assert settings.port == 9000

    overridden = load_settings(server=True, host="100.64.0.20", port=0)
    assert overridden.host == "100.64.0.20"
    assert overridden.port == 0


def test_server_mode_refuses_the_desktop_window():
    with pytest.raises(ValueError, match="cannot be combined with server mode"):
        load_settings(server=True, desktop_token="x" * 64)


def test_non_loopback_host_refused_outside_server_mode(
    monkeypatch: pytest.MonkeyPatch,
):
    with pytest.raises(ValueError, match="requires server mode"):
        load_settings(host="0.0.0.0")
    monkeypatch.setenv("VERSTEHEN_HOST", "100.64.0.1")
    with pytest.raises(ValueError, match="requires server mode"):
        load_settings()
