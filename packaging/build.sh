#!/bin/bash
set -euo pipefail
mkdir -p dist
docker run --rm \
  -e BUILD_UID="$(id -u)" -e BUILD_GID="$(id -g)" \
  -v "$PWD:/source:ro" -v "$PWD/dist:/output" \
  -v verstehen-cargo:/cache/cargo -v verstehen-target:/cache/target \
  -v verstehen-npm:/cache/npm -v verstehen-uv:/cache/uv \
  -v verstehen-pacman:/var/cache/pacman/pkg \
  archlinux:latest bash /source/packaging/container.sh
printf 'Build duration: %s seconds\n' "$SECONDS"
