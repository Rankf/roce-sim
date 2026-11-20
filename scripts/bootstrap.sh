#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
python3 -m pip install --disable-pip-version-check --target "$ROOT/env/python38-packages" -r "$ROOT/env/requirements.txt"
SCONS_LIB_DIR="$ROOT/env/python38-packages/scons" PYTHONPATH="$ROOT/env/python38-packages/scons:$ROOT/env/python38-packages" /usr/bin/python3 "$ROOT/env/python38-packages/bin/scons" --version
