#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-}
if [[ "$CASE_NAME" == all ]]; then
    for name in bad-rkey remote-pd remote-write-permission remote-read-permission mr-start mr-end mr-wrap local-lkey local-pd local-read-write legal-end cross-line invalid-mr local-read-default isolation-g0 isolation-g1 isolation-g0-cross isolation-g1-cross cross-page multipacket-write multipacket-read; do
        "$ROOT/scripts/run_protection.sh" "$name"
    done
    exit 0
fi

case "$CASE_NAME" in
    bad-rkey) MODE=1; OP=write ;;
    remote-pd) MODE=2; OP=write ;;
    remote-write-permission) MODE=3; OP=write ;;
    remote-read-permission) MODE=4; OP=read ;;
    mr-start) MODE=5; OP=write ;;
    mr-end) MODE=6; OP=write ;;
    mr-wrap) MODE=7; OP=write ;;
    local-lkey) MODE=8; OP=write ;;
    local-pd) MODE=9; OP=write ;;
    local-read-write) MODE=10; OP=read ;;
    legal-end) MODE=11; OP=write ;;
    cross-line) MODE=12; OP=write ;;
    invalid-mr) MODE=13; OP=write ;;
    local-read-default) MODE=14; OP=write ;;
    isolation-g0) MODE=15; OP=write ;;
    isolation-g1) MODE=16; OP=write ;;
    isolation-g0-cross) MODE=17; OP=write ;;
    isolation-g1-cross) MODE=18; OP=write ;;
    cross-page) MODE=19; OP=write ;;
    multipacket-write) MODE=20; OP=write ;;
    multipacket-read) MODE=21; OP=read ;;
    *) echo "Usage: $0 [all|case-name]" >&2; exit 2 ;;
esac

RUN_ID=${RUN_ID:-protect-$CASE_NAME} PROTECT_MODE=$MODE DEBUG_FLAGS=${DEBUG_FLAGS:-MrResc,RdmaEngine,HanGuRnic} "$ROOT/scripts/run_rc.sh" "$OP"
