#!/usr/bin/env bash
set -euo pipefail

MISE_VERSION="${MISE_VERSION:-v2026.6.13}"
INSTALL_DIR="${INSTALL_DIR:-/home/coder/.local/bin}"
MISE_INSTALL_PATH="${MISE_INSTALL_PATH:-${INSTALL_DIR}/mise}"

mkdir -p "${INSTALL_DIR}"

if command -v mise >/dev/null 2>&1; then
  mise --version
  exit 0
fi

curl -fsSL https://mise.run | MISE_VERSION="${MISE_VERSION}" MISE_INSTALL_PATH="${MISE_INSTALL_PATH}" sh

if ! command -v mise >/dev/null 2>&1; then
  echo "mise install completed but mise was not found on PATH" >&2
  exit 1
fi

mise --version
