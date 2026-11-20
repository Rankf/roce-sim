#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
CASES=(fixed-write fixed-read send send-multipacket send-imm write-imm
    rnr-recovery atomic-basic atomic-replay multipacket-write multipacket-read
    bad-rkey duplicate-write-request drop-read-response psn-wrap-write
    mw-bind mw-send-inv)
if [[ "$CASE_NAME" == all ]]; then
    for name in "${CASES[@]}"; do
        "$ROOT/scripts/run_ipv6.sh" "$name"
    done
    exit 0
fi
export ROCE_IP_VERSION=6
export MAX_TICKS=${MAX_TICKS:-200000000000}
RUN_ID=ipv6-$CASE_NAME
export RUN_ID
case "$CASE_NAME" in
    fixed-write|fixed-read)
        FIXED_WR_NUM=16 "$ROOT/scripts/run_rc.sh" "${CASE_NAME#fixed-}" ;;
    send|send-multipacket|send-imm|write-imm|rnr-recovery|atomic-basic|atomic-replay)
        "$ROOT/scripts/run_qp.sh" "$CASE_NAME" ;;
    multipacket-write|multipacket-read|bad-rkey)
        "$ROOT/scripts/run_protection.sh" "$CASE_NAME" ;;
    duplicate-write-request|drop-read-response)
        "$ROOT/scripts/run_fault.sh" "$CASE_NAME" ;;
    psn-wrap-write)
        "$ROOT/scripts/run_rc_state.sh" "$CASE_NAME" ;;
    mw-bind|mw-send-inv)
        "$ROOT/scripts/run_mw.sh" "${CASE_NAME#mw-}" ;;
    *) echo "Usage: $0 [all|case-name]" >&2; exit 2 ;;
esac
