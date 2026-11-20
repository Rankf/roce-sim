#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_DIR="$ROOT/model/csrna"
UPSTREAM_URL=${CSRNA_UPSTREAM_URL:-https://github.com/ncsg-group/csRNA.git}
UPSTREAM_COMMIT=5270d51c584055fb21f05602d624c2bcfb4184c7
MAIN_PATCH="$ROOT/patches/csrna-rocev2-protection.patch"
COMPAT_PATCH="$ROOT/patches/csrna-build-compat.patch"

if [[ -d "$MODEL_DIR/.git" ]]; then
    actual=$(git -C "$MODEL_DIR" rev-parse HEAD)
    if [[ "$actual" != "$UPSTREAM_COMMIT" ]]; then
        echo "Unsupported csRNA commit in $MODEL_DIR: $actual" >&2
        echo "Expected $UPSTREAM_COMMIT; the existing directory is left unchanged." >&2
        exit 2
    fi
    if git -C "$MODEL_DIR" apply --check --reverse "$MAIN_PATCH" && \
            git -C "$MODEL_DIR" apply --check --reverse "$COMPAT_PATCH"; then
        echo "csRNA is already configured in $MODEL_DIR"
        exit 0
    fi
    echo "Existing csRNA does not match the delivery patch; left unchanged." >&2
    exit 2
fi
if [[ -e "$MODEL_DIR" ]]; then
    echo "$MODEL_DIR exists but is not a csRNA git checkout; left unchanged." >&2
    exit 2
fi

mkdir -p "$ROOT/model"
git clone "$UPSTREAM_URL" "$MODEL_DIR"
git -C "$MODEL_DIR" checkout --detach "$UPSTREAM_COMMIT"
git -C "$MODEL_DIR" apply "$MAIN_PATCH"
git -C "$MODEL_DIR" apply "$COMPAT_PATCH"
chmod +x "$MODEL_DIR/util/cpt_upgrader.py"
echo "Configured csRNA $UPSTREAM_COMMIT in $MODEL_DIR"
