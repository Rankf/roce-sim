#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-lifecycle}
if [[ "$CASE_NAME" == all ]]; then
    for name in lifecycle send send-multipacket send-imm write-imm duplicate-send-multipacket rnr-recovery rnr-exhausted queue-resource cq-overrun sqd-read read-credit sge-send sge-read fence ring-stress atomic-basic atomic-protect atomic-contend atomic-duplicate atomic-replay atomic-credit-fence atomic-retry atomic-reset send-batch reset-inflight; do
        "$ROOT/scripts/run_qp.sh" "$name"
    done
    exit 0
fi
DUPLICATE_SERVER_OPCODE=
case "$CASE_NAME" in
    lifecycle) MODE=40 ;;
    send) MODE=41 ;;
    send-batch) MODE=46 ;;
    reset-inflight) MODE=47; DROP_SERVER_OPCODE=10; DROP_COUNT=1 ;;
    send-multipacket) MODE=42 ;;
    send-imm) MODE=43 ;;
    write-imm) MODE=44 ;;
    duplicate-send-multipacket) MODE=45; DUPLICATE_SERVER_OPCODE=0 ;;
    rnr-recovery) MODE=48 ;;
    rnr-exhausted) MODE=49; RNR_RETRY_LIMIT=2 ;;
    queue-resource) MODE=50 ;;
    cq-overrun) MODE=51; CQ_CAPACITY=2 ;;
    sqd-read) MODE=52; DROP_CLIENT_OPCODE=13; DROP_COUNT=1; RETRANS_TIMEOUT=5us ;;
    read-credit) MODE=53; DROP_CLIENT_OPCODE=13; DROP_COUNT=1; RETRANS_TIMEOUT=1000us ;;
    sge-send) MODE=54 ;;
    sge-read) MODE=55 ;;
    fence) MODE=56; DROP_CLIENT_OPCODE=16; DROP_COUNT=1; RETRANS_TIMEOUT=5us ;;
    ring-stress) MODE=57; DMA_RETRY_COUNT=8; DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic,DMA; export DMA_RETRY_COUNT ;;
    atomic-basic) MODE=58; DMA_RETRY_COUNT=4; DMA_DELAY=1000ps; DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic,DMA; export DMA_RETRY_COUNT DMA_DELAY ;;
    atomic-protect) MODE=59 ;;
    atomic-contend) MODE=60 ;;
    atomic-duplicate) MODE=61; DUPLICATE_SERVER_OPCODE=20; DMA_DELAY=1000ps; DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic,DMA; export DMA_DELAY ;;
    atomic-replay) MODE=62; DROP_CLIENT_OPCODE=18; DROP_COUNT=1; RETRANS_TIMEOUT=5us ;;
    atomic-credit-fence) MODE=63 ;;
    atomic-retry) MODE=64; DROP_CLIENT_OPCODE=18; DROP_COUNT=20; RETRANS_LIMIT=2; RETRANS_TIMEOUT=5us ;;
    atomic-reset) MODE=65; DROP_CLIENT_OPCODE=18; DROP_COUNT=1; RETRANS_TIMEOUT=1000us ;;
    *) echo "Usage: $0 [all|case-name]" >&2; exit 2 ;;
esac
if [[ -n "$DUPLICATE_SERVER_OPCODE" ]]; then
    export DUPLICATE_SERVER_OPCODE DUPLICATE_COUNT=1
fi
if [[ -n "${DROP_SERVER_OPCODE:-}" ]]; then
    export DROP_SERVER_OPCODE DROP_COUNT=1
fi
if [[ "$CASE_NAME" == reset-inflight ]]; then
    export RETRANS_TIMEOUT=1000us
fi
if [[ "$CASE_NAME" == rnr-exhausted ]]; then
    export RNR_RETRY_LIMIT
fi
if [[ "$CASE_NAME" == atomic-retry ]]; then
    export RETRANS_LIMIT
fi
if [[ "$CASE_NAME" == cq-overrun ]]; then
    export CQ_CAPACITY
fi
if [[ "$CASE_NAME" == sqd-read || "$CASE_NAME" == read-credit || "$CASE_NAME" == fence ||
        "$CASE_NAME" == atomic-replay || "$CASE_NAME" == atomic-retry ||
        "$CASE_NAME" == atomic-reset ]]; then
    export DROP_CLIENT_OPCODE DROP_COUNT RETRANS_TIMEOUT
fi
OPERATION=write
if [[ "$CASE_NAME" == sge-read || "$CASE_NAME" == fence || "$CASE_NAME" == atomic-credit-fence ]]; then
    OPERATION=read
fi
RUN_ID=${RUN_ID:-qp-$CASE_NAME} PROTECT_MODE=$MODE \
    DEBUG_FLAGS=${DEBUG_FLAGS:-MrResc,RdmaEngine,HanGuRnic} \
    "$ROOT/scripts/run_rc.sh" "$OPERATION"
