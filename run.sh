#!/usr/bin/env bash
# Build and run Letter Quest with podman or docker.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p data

if command -v podman >/dev/null 2>&1; then
  ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
  ENGINE=docker
else
  echo "Need podman or docker installed." >&2
  exit 1
fi

echo "Building with $ENGINE..."
$ENGINE build -t letter-quest:latest .

$ENGINE rm -f letter-quest >/dev/null 2>&1 || true

# :Z is a no-op on non-SELinux hosts and required on Fedora.
echo "Starting on http://localhost:8080 ..."
$ENGINE run -d --name letter-quest \
  -p 8080:8080 \
  -e PORT=8080 \
  -e DATA_DIR=/data \
  -v "$PWD/data:/data:Z" \
  letter-quest:latest

echo
echo "  Letter Quest is up:  http://localhost:8080"
echo "  Health check:        http://localhost:8080/api/health"
echo "  Stop:                $ENGINE stop letter-quest"
echo "  Logs:                $ENGINE logs -f letter-quest"
echo
echo "On another device on your Wi-Fi, use this machine's IP instead of localhost."
