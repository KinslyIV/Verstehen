#!/bin/bash
set -euo pipefail
groupadd -g "$BUILD_GID" builder
useradd -m -u "$BUILD_UID" -g "$BUILD_GID" builder
mkdir -p /build /cache/npm /cache/uv
chown -R "$BUILD_UID:$BUILD_GID" /build /cache /output
tar -C /source --exclude=.git --exclude=node_modules --exclude=.venv --exclude='./dist' --exclude='./backend/dist' --exclude=build --exclude=.svelte-kit --exclude=verify-output -cf - . | tar -C /build -xf -
chown -R "$BUILD_UID:$BUILD_GID" /build
exec runuser -u builder -- bash /build/packaging/compile.sh
