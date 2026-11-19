#!/bin/bash
set -euo pipefail
groupadd -g "$BUILD_GID" builder
useradd -m -u "$BUILD_UID" -g "$BUILD_GID" builder
mkdir -p /build /cache/cargo /cache/target /cache/npm /cache/uv
chown -R "$BUILD_UID:$BUILD_GID" /build /cache /output
tar -C /source --exclude=.git --exclude=node_modules --exclude=.venv --exclude=dist --exclude=build --exclude=target --exclude=.svelte-kit --exclude=verify-output --exclude=binaries -cf - . | tar -C /build -xf -
chown -R "$BUILD_UID:$BUILD_GID" /build
exec runuser -u builder -- bash /build/packaging/compile.sh
