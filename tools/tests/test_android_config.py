import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "app/android/app/src/main"
NAMESPACE = "{http://schemas.android.com/apk/res/android}"
APP_JAVA = ANDROID / "java/local/verstehen/app"


def test_manifest_wires_network_and_backup_rules():
    application = ElementTree.parse(ANDROID / "AndroidManifest.xml").find("application")
    assert application is not None
    assert (
        application.get(f"{NAMESPACE}networkSecurityConfig")
        == "@xml/network_security_config"
    )
    assert (
        application.get(f"{NAMESPACE}dataExtractionRules")
        == "@xml/data_extraction_rules"
    )
    assert application.get(f"{NAMESPACE}fullBackupContent") == "@xml/backup_rules"


def test_connection_file_is_excluded_from_backups():
    for name in ("backup_rules", "data_extraction_rules"):
        text = (ANDROID / f"res/xml/{name}.xml").read_text()
        assert 'domain="sharedpref" path="CapacitorStorage.xml"' in text


def test_cleartext_is_allowed_for_the_guard_to_restrict():
    config = ElementTree.parse(
        ANDROID / "res/xml/network_security_config.xml"
    ).getroot()
    base = config.find("base-config")
    assert base is not None and base.get("cleartextTrafficPermitted") == "true"
    assert config.find("domain-config") is None


def test_guard_allows_only_the_page_tailscale_and_the_debug_emulator_host():
    source = (APP_JAVA / "CleartextGuard.java").read_text()
    address_literals = set(re.findall(r'"(\d+\.\d+\.\d+\.\d+)"', source))
    assert address_literals == {"10.0.2.2"}
    assert 'host.equals("localhost")' in source
    assert "octets[0] == 100 && octets[1] >= 64 && octets[1] <= 127" in source
    assert "(debug && host.equals(EMULATOR_HOST))" in source


def test_webview_uses_the_guard_with_the_build_type():
    assert (
        "GuardedWebViewClient(bridge)" in (APP_JAVA / "MainActivity.java").read_text()
    )
    client = (APP_JAVA / "GuardedWebViewClient.java").read_text()
    assert (
        "CleartextGuard.allows(url.getScheme(), url.getHost(), BuildConfig.DEBUG)"
        in client
    )
    assert "return super.shouldInterceptRequest(view, request);" in client


def test_capacitor_loads_the_page_from_http_localhost_with_native_http_disabled():
    config = (ROOT / "app/capacitor.config.ts").read_text()
    assert "appId: 'local.verstehen.app'" in config
    assert "androidScheme: 'http'" in config
    assert "webDir: 'build-android'" in config
    assert "plugins: { CapacitorHttp: { enabled: false } }" in config


def android_release_steps() -> list[str]:
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    job = workflow.split("\n  android:\n")[1]
    return ["      - " + step for step in job.split("\n      - ")[1:]]


def test_unconfigured_android_release_is_skipped_with_a_notice_before_any_setup():
    first, *rest = android_release_steps()
    assert "id: signing" in first and "::notice::" in first and "::error::" not in first
    assert "exit 1" not in first
    assert all("steps.signing.outputs.configured == 'true'" in step for step in rest)
    assert any("android-actions/setup-android@v4" in step for step in rest)


def test_signing_secrets_reach_only_the_check_and_build_steps():
    steps_with_secrets = [
        step.splitlines()[0]
        for step in android_release_steps()
        if "secrets.ANDROID_" in step
    ]
    assert steps_with_secrets == [
        "      - name: Check the Android signing secrets",
        "      - name: Build the signed .apk",
    ]


def android_debug_job() -> str:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    return workflow.split("\n  android-debug:\n")[1]


def test_ci_builds_the_debug_apk_only_for_pull_requests_without_secrets():
    job = android_debug_job()
    assert "if: github.event_name == 'pull_request'" in job
    assert "secrets." not in job
    assert "distribution: temurin" in job and "java-version: '21'" in job
    assert "android-actions/setup-android@v4" in job
    assert "run: make android-debug" in job
    assert "path: dist/verstehen-*-debug.apk" in job


def test_ci_keeps_its_triggers_and_original_job():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert (
        "on:\n  pull_request:\n    branches: [main]\n  push:\n    branches: [main]\n"
        in workflow
    )
    assert "\n  ci:\n" in workflow and "      - run: make verify\n" in workflow
