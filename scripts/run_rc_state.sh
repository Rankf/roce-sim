#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-}
if [[ "$CASE_NAME" == all ]]; then
    for name in psn-wrap-write psn-wrap-read outstanding-write outstanding-read out-of-order-write out-of-order-read consecutive-ack-loss retry-exhausted consecutive-request-loss multipacket-out-of-order multipacket-read-middle; do
        "$ROOT/scripts/run_rc_state.sh" "$name"
    done
    exit 0
fi

INITIAL_PSN=0
DROP_SERVER_OPCODE=0
DROP_CLIENT_OPCODE=0
DROP_COUNT=0
RETRANS_LIMIT=7
case "$CASE_NAME" in
    psn-wrap-write) MODE=29; OP=write; INITIAL_PSN=16777214 ;;
    psn-wrap-read) MODE=30; OP=read; INITIAL_PSN=16777214 ;;
    outstanding-write) MODE=31; OP=write ;;
    outstanding-read) MODE=32; OP=read ;;
    out-of-order-write) MODE=33; OP=write; DROP_SERVER_OPCODE=10; DROP_COUNT=1 ;;
    out-of-order-read) MODE=34; OP=read; DROP_SERVER_OPCODE=12; DROP_COUNT=1 ;;
    consecutive-ack-loss) MODE=35; OP=write; DROP_CLIENT_OPCODE=17; DROP_COUNT=3 ;;
    retry-exhausted) MODE=36; OP=write; DROP_SERVER_OPCODE=10; DROP_COUNT=20; RETRANS_LIMIT=2 ;;
    consecutive-request-loss) MODE=37; OP=write; DROP_SERVER_OPCODE=10; DROP_COUNT=2 ;;
    multipacket-out-of-order) MODE=38; OP=write; DROP_SERVER_OPCODE=6; DROP_COUNT=1 ;;
    multipacket-read-middle) MODE=39; OP=read ;;
    *) echo "Usage: $0 [all|case-name]" >&2; exit 2 ;;
esac

RUN_ID=${RUN_ID:-rc-state-$CASE_NAME} PROTECT_MODE=$MODE \
    INITIAL_PSN=$INITIAL_PSN RETRANS_TIMEOUT=${RETRANS_TIMEOUT:-5us} \
    RETRANS_LIMIT=$RETRANS_LIMIT \
    DROP_SERVER_OPCODE=$DROP_SERVER_OPCODE DROP_CLIENT_OPCODE=$DROP_CLIENT_OPCODE \
    DROP_COUNT=$DROP_COUNT DEBUG_FLAGS=${DEBUG_FLAGS:-MrResc,RdmaEngine,HanGuRnic} \
    "$ROOT/scripts/run_rc.sh" "$OP"
