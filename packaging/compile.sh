#!/bin/bash
set -euo pipefail
cd /build
export npm_config_cache=/cache/npm UV_CACHE_DIR=/cache/uv
uv sync --project backend --locked
npm ci --prefix app
npm run build --prefix app
cd backend
uv run pyinstaller --noconfirm packaging/verstehen.spec
cd ..
test ! -e backend/dist/verstehen/_internal/claude_agent_sdk/_bundled/claude || { echo "The frozen app must not bundle the Claude Code CLI; filter it in verstehen.spec"; exit 1; }
uv run --project backend python packaging/smoke.py backend/dist/verstehen/verstehen
rm -rf backend/dist/server-bundle
mkdir -p backend/dist/server-bundle
uv build --wheel --out-dir backend/dist/server-bundle backend
uv export --project backend --frozen --no-dev --no-emit-project --extra server --format requirements-txt -o backend/dist/server-bundle/requirements.txt
if grep -qiE '^(pyside6|shiboken6)' backend/dist/server-bundle/requirements.txt; then
  echo "The server bundle must not require PySide6; keep it in the desktop extra"
  exit 1
fi
cd packaging
PKGDEST=/output makepkg --force --nodeps
pacman -Qp /output/verstehen-*.pkg.tar.zst
pacman -Qlp /output/verstehen-*.pkg.tar.zst > /output/package-contents.txt
du -sh ../backend/dist/verstehen
