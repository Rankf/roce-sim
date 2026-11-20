#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREFIX=${RUN_ID_PREFIX:-rc-smoke-$(date -u +%Y%m%dT%H%M%SZ)}
RUN_ID="$PREFIX-write" "$ROOT/scripts/run_rc.sh" write
RUN_ID="$PREFIX-read" "$ROOT/scripts/run_rc.sh" read
