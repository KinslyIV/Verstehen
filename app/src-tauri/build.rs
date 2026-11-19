fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["sidecar_connection"])),
    )
    .expect("Failed to prepare Tauri build");
}
