#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
if [[ "$CASE_NAME" == all ]]; then
    for name in bind reject rebind send-inv rnr timing lifecycle reuse; do
        "$ROOT/scripts/run_mw.sh" "$name"
    done
    exit 0
fi
case "$CASE_NAME" in
    bind) MODE=80 ;;
    reject) MODE=81 ;;
    rebind) MODE=82 ;;
    send-inv) MODE=83 ;;
    rnr) MODE=84; DROP_CLIENT_OPCODE=17; DROP_COUNT=1; RETRANS_TIMEOUT=5us; DUPLICATE_SERVER_OPCODE=23; export DUPLICATE_SERVER_OPCODE DUPLICATE_COUNT=1 ;;
    timing) MODE=85; DMA_RETRY_COUNT=4; DMA_DELAY=30us; ATOMIC_RESPONSE_DELAY=300us; DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic,DMA; export DMA_RETRY_COUNT DMA_DELAY ATOMIC_RESPONSE_DELAY ;;
    lifecycle) MODE=86 ;;
    reuse) MODE=87 ;;
    *) echo "Usage: $0 [all|bind|reject|rebind|send-inv|rnr|timing|lifecycle|reuse]" >&2; exit 2 ;;
esac
if [[ "$CASE_NAME" == rnr ]]; then
    export DROP_CLIENT_OPCODE DROP_COUNT RETRANS_TIMEOUT
fi
RUN_ID=${RUN_ID:-mw-$CASE_NAME} PROTECT_MODE=$MODE \
    DEBUG_FLAGS=${DEBUG_FLAGS:-MrResc,RdmaEngine,HanGuRnic} \
    "$ROOT/scripts/run_rc.sh" write
