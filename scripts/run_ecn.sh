#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local name=$1
    local version=$2
    local tag=$3
    shift 3
    local output=$ROOT/results/ecn-$tag-ipv$version
    env OUTDIR="$output" ROCE_IP_VERSION="$version" ENABLE_ECN=1 \
        SWITCH_BUFFER_SIZE=1MB "$@" \
        "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/ecn-$tag-ipv$version.log" 2>&1
}

run_e01() {
    for version in 4 6; do
        run_case e01 "$version" e01-disabled ENABLE_ECN=0 ECN_THRESHOLD=512B
        run_case e01 "$version" e01-low ECN_THRESHOLD=1MB
    done
}

run_e02() {
    g++ -std=c++11 -Wall -Wextra -pedantic tests/ecn_format_test.cc -o results/ecn-format-test
    ./results/ecn-format-test | tee results/ecn-e02-format.log
}

run_e04() {
    for version in 4 6; do
        run_case e04 "$version" e04 ECN_THRESHOLD=512B RETRANS_TIMEOUT=5us
    done
}

run_e05() {
    for version in 4 6; do
        run_case e05 "$version" e05 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=50us
    done
}

run_e06() {
    for version in 4 6; do
        run_case e06 "$version" e06 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=50us
    done
}

run_e07() {
    for version in 4 6; do
        run_case e07 "$version" e07 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=1s \
            DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 DROP_COUNT=1 RETRANS_TIMEOUT=1000us \
            DUPLICATE_SERVER_OPCODE=10 DUPLICATE_CLIENT_OPCODE=10 DUPLICATE_COUNT=1
    done
}

run_e08() {
    for version in 4 6; do
        run_case e08 "$version" e08 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=50us
    done
}

run_e09() {
    for version in 4 6; do
        run_case e09 "$version" e09 ECN_THRESHOLD=512B RETRANS_TIMEOUT=5us \
            DROP_CLIENT_OPCODE=129 DROP_COUNT=1
    done
}

run_e10() {
    FIXED_WR_NUM=16 RUN_ID=fixed-write-completion ./scripts/run_rc.sh write > results/ecn-e10-fixed-write.log 2>&1
    FIXED_WR_NUM=16 RUN_ID=fixed-read-completion ./scripts/run_rc.sh read > results/ecn-e10-fixed-read.log 2>&1
    FIXED_WR_NUM=1 RUN_ID=write-completion-order DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic \
        ./scripts/run_rc.sh write > results/ecn-e10-write-order.log 2>&1
    FIXED_WR_NUM=1 RUN_ID=read-completion-order DEBUG_FLAGS=MrResc,RdmaEngine,HanGuRnic \
        ./scripts/run_rc.sh read > results/ecn-e10-read-order.log 2>&1
    RUN_ID=timing-normal-valid ./scripts/run_rc.sh write > results/ecn-e10-timing-normal.log 2>&1
    RUN_ID=timing-high-latency-valid DRAM_TCL=27500ps DRAM_TRCD=27500ps \
        ./scripts/run_rc.sh write > results/ecn-e10-timing-high.log 2>&1
    RUN_ID=retry-cross-line-fixed PROTECT_MODE=12 DMA_RETRY_COUNT=4 DMA_DELAY=1000ps \
        DEBUG_FLAGS=DMA,DmaEngine,RdmaEngine ./scripts/run_rc.sh write > results/ecn-e10-retry.log 2>&1
    ./scripts/run_protection.sh all > results/ecn-e10-protection.log 2>&1
    ./scripts/run_fault.sh all > results/ecn-e10-fault.log 2>&1
    ./scripts/run_rc_state.sh all > results/ecn-e10-rc-state.log 2>&1
    ./scripts/run_qp.sh all > results/ecn-e10-qp.log 2>&1
    ./scripts/run_mw.sh all > results/ecn-e10-mw.log 2>&1
    ./scripts/run_ipv6.sh all > results/ecn-e10-ipv6.log 2>&1
    ./scripts/run_switch.sh all > results/ecn-e10-switch.log 2>&1
    python3 analysis/check_fixed_rc.py results/fixed-write-completion results/fixed-read-completion
    python3 analysis/check_protection.py results/protect-*
    python3 analysis/check_timing_rc.py results/timing-normal-valid results/timing-high-latency-valid
    python3 analysis/check_fault.py results/fault-*
    python3 analysis/check_retry.py
    python3 analysis/check_completion_order.py
    python3 analysis/check_rc_state.py \
        results/rc-state-psn-wrap-write results/rc-state-psn-wrap-read \
        results/rc-state-outstanding-write results/rc-state-outstanding-read \
        results/rc-state-out-of-order-write results/rc-state-out-of-order-read \
        results/rc-state-consecutive-ack-loss results/rc-state-retry-exhausted \
        results/rc-state-consecutive-request-loss \
        results/rc-state-multipacket-out-of-order results/rc-state-multipacket-read-middle
    python3 analysis/check_operations.py results/qp-send results/qp-send-multipacket \
        results/qp-send-imm results/qp-write-imm results/qp-duplicate-send-multipacket
    python3 analysis/check_qp.py
    python3 analysis/check_rnr.py results/qp-rnr-recovery results/qp-rnr-exhausted
    python3 analysis/check_queue.py
    python3 analysis/check_cq_overrun.py
    python3 analysis/check_sqd.py
    python3 analysis/check_read_credit.py
    python3 analysis/check_sge.py
    python3 analysis/check_fence.py
    python3 analysis/check_ring.py
    python3 analysis/check_atomic.py
    python3 analysis/check_atomic_ext.py
    python3 analysis/check_qp_completion.py results/qp-send-batch results/qp-reset-inflight
    python3 analysis/check_mw.py
    python3 analysis/check_ipv6.py
    python3 analysis/check_switch.py
    python3 analysis/check_rocev2_pcap.py results/protect-* results/fault-* results/fixed-*-completion
}

case "$CASE_NAME" in
    all)
        run_e01
        run_e02
        run_e04
        run_e05
        run_e06
        run_e07
        run_e08
        run_e09
        python3 analysis/check_ecn.py e01 e02 e03 e04 e05 e06 e07 e08 e09
        run_e10
        python3 analysis/check_ecn.py e10
        ;;
    e01) run_e01; python3 analysis/check_ecn.py e01 ;;
    e02|e03) run_e02; python3 analysis/check_ecn.py "$CASE_NAME" ;;
    e04|e05|e06|e07|e08|e09)
        "run_$CASE_NAME"
        python3 analysis/check_ecn.py "$CASE_NAME"
        ;;
    e10) run_e10; python3 analysis/check_ecn.py e10 ;;
    *) echo "Usage: $0 [all|e01|e02|e03|e04|e05|e06|e07|e08|e09|e10]" >&2; exit 2 ;;
esac
