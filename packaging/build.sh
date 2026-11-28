#!/bin/bash
set -euo pipefail
mkdir -p dist
docker build --quiet --tag verstehen-build - < packaging/Dockerfile
docker run --rm \
  -e BUILD_UID="$(id -u)" -e BUILD_GID="$(id -g)" \
  -v "$PWD:/source:ro" -v "$PWD/dist:/output" \
  -v verstehen-npm:/cache/npm -v verstehen-uv:/cache/uv \
  verstehen-build bash /source/packaging/container.sh
printf 'Build duration: %s seconds\n' "$SECONDS"
