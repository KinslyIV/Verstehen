#!/bin/bash
set -euo pipefail
cd /build
export CARGO_HOME=/cache/cargo CARGO_TARGET_DIR=/cache/target npm_config_cache=/cache/npm UV_CACHE_DIR=/cache/uv
uv sync --project backend --locked
npm ci --prefix app
uv run --project backend python tools/check_versions.py
cd backend
uv run pyinstaller --noconfirm packaging/verstehen-sidecar.spec
cd ..
test ! -e backend/dist/verstehen-sidecar/_internal/claude_agent_sdk/_bundled/claude || { echo "The frozen sidecar must not bundle the Claude Code CLI; filter it in verstehen-sidecar.spec"; exit 1; }
uv run --project backend python packaging/smoke.py backend/dist/verstehen-sidecar/verstehen-sidecar
mkdir -p app/src-tauri/binaries
cp backend/dist/verstehen-sidecar/verstehen-sidecar app/src-tauri/binaries/verstehen-sidecar-x86_64-unknown-linux-gnu
cd app
cargo fmt --manifest-path src-tauri/Cargo.toml --check
npm run build
cargo clippy --locked --manifest-path src-tauri/Cargo.toml -- -D warnings
npx tauri build --no-bundle -- --locked
cd ../packaging
PKGDEST=/output makepkg --force --nodeps
pacman -Qp /output/verstehen-*.pkg.tar.zst
pacman -Qlp /output/verstehen-*.pkg.tar.zst > /output/package-contents.txt
rustc --version
npm list --prefix ../app @tauri-apps/cli
du -sh ../backend/dist/verstehen-sidecar
