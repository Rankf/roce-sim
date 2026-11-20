#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_DIR="$ROOT/model/csrna"
JOBS=${JOBS:-16}

if [[ ! -d "$MODEL_DIR" ]]; then
    echo "Missing csRNA model: $MODEL_DIR" >&2
    exit 2
fi
if [[ ! -x "$ROOT/env/python38-packages/bin/scons" ]]; then
    "$ROOT/scripts/bootstrap.sh"
fi

mkdir -p "$MODEL_DIR/tests/test-progs/hangu-rnic/bin" "$ROOT/env/bin"
ln -sf /usr/bin/python3 "$ROOT/env/bin/python"
chmod +x "$MODEL_DIR/util/cpt_upgrader.py"
if [[ ! -e "$MODEL_DIR/README" && -e "$MODEL_DIR/README.md" ]]; then
    ln -s README.md "$MODEL_DIR/README"
fi
make -C "$MODEL_DIR/tests/test-progs/hangu-rnic/src" -j"$JOBS"

export PATH="$ROOT/env/bin":/usr/local/sbin:/usr/local/bin:/usr/bin:/sbin:/bin
export SCONS_LIB_DIR="$ROOT/env/python38-packages/scons"
export PYTHONPATH="$ROOT/env/python38-packages/scons:$ROOT/env/python38-packages"
cd "$MODEL_DIR"
/usr/bin/python3 "$ROOT/env/python38-packages/bin/scons" build/X86/gem5.opt PYTHON_CONFIG=/usr/bin/python3-config -j"$JOBS"
