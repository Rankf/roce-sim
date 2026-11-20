#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-}
if [[ "$CASE_NAME" == all ]]; then
    for name in drop-write-request drop-write-ack duplicate-write-request drop-read-request drop-read-response duplicate-read-request duplicate-read-response; do
        "$ROOT/scripts/run_fault.sh" "$name"
    done
    exit 0
fi

DROP_SERVER_OPCODE=0
DROP_CLIENT_OPCODE=0
DUPLICATE_SERVER_OPCODE=0
DUPLICATE_CLIENT_OPCODE=0
case "$CASE_NAME" in
    drop-write-request) MODE=22; OP=write; DROP_SERVER_OPCODE=10 ;;
    drop-write-ack) MODE=23; OP=write; DROP_CLIENT_OPCODE=17 ;;
    duplicate-write-request) MODE=24; OP=write; DUPLICATE_SERVER_OPCODE=10 ;;
    drop-read-request) MODE=25; OP=read; DROP_SERVER_OPCODE=12 ;;
    drop-read-response) MODE=26; OP=read; DROP_CLIENT_OPCODE=16 ;;
    duplicate-read-request) MODE=27; OP=read; DUPLICATE_SERVER_OPCODE=12 ;;
    duplicate-read-response) MODE=28; OP=read; DUPLICATE_CLIENT_OPCODE=16 ;;
    *) echo "Usage: $0 [all|case-name]" >&2; exit 2 ;;
esac

RUN_ID=${RUN_ID:-fault-$CASE_NAME} PROTECT_MODE=$MODE \
    RETRANS_TIMEOUT=${RETRANS_TIMEOUT:-5us} \
    DROP_SERVER_OPCODE=$DROP_SERVER_OPCODE DROP_CLIENT_OPCODE=$DROP_CLIENT_OPCODE \
    DUPLICATE_SERVER_OPCODE=$DUPLICATE_SERVER_OPCODE \
    DUPLICATE_CLIENT_OPCODE=$DUPLICATE_CLIENT_OPCODE \
    DEBUG_FLAGS=${DEBUG_FLAGS:-MrResc,RdmaEngine,HanGuRnic} \
    "$ROOT/scripts/run_rc.sh" "$OP"
