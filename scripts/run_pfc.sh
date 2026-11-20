#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local tag=$1 version=$2 name=$3
    shift 3
    env OUTDIR="$ROOT/results/pfc-$tag-ipv$version" ROCE_IP_VERSION="$version" \
        "$@" "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/pfc-$tag-ipv$version.log" 2>&1
}

algorithm_test() {
    g++ -std=c++11 -Wall -Wextra -pedantic tests/pfc_format_test.cc -o results/pfc-format-test
    ./results/pfc-format-test | tee results/pfc-format.log
}

common=(ENABLE_PFC=1 SWITCH_FABRIC_SPEED=10Mbps SWITCH_BUFFER_SIZE=16kB
    PFC_XOFF=512B PFC_XON=128B PFC_HEADROOM=8kB PFC_PAUSE_QUANTA=1000
    RETRANS_TIMEOUT=1000us MAX_TICKS=50000000000000)

run_p01() {
    algorithm_test
    run_case p01-disabled 4 e04 ENABLE_ECN=1 ECN_THRESHOLD=512B RETRANS_TIMEOUT=5us
    python3 analysis/check_pfc.py p01
}

run_p02() {
    run_case p02-directed 4 e06 ENABLE_PFC=1 SWITCH_BUFFER_SIZE=32kB PFC_HEADROOM=8kB \
        RNIC_PFC_TEST_MASK=8 RNIC_PFC_TEST_QUANTA=2000 RNIC_PFC_TEST_TIME=40us RETRANS_TIMEOUT=1000us
    python3 analysis/check_pfc.py p02
}

run_p03() {
    run_case p03-same 4 e05 "${common[@]}"
    python3 analysis/check_pfc.py p03
}

run_p04() {
    run_case p04-isolation 4 e05 "${common[@]}" PFC_MULTI_PRIORITY=1
    run_case p04-directed 4 e05 "${common[@]}" PFC_MULTI_PRIORITY=1 \
        RNIC_PFC_TEST_MASK=8 RNIC_PFC_TEST_QUANTA=2000 RNIC_PFC_TEST_TIME=40us
    python3 analysis/check_pfc.py p04
}

run_p05() {
    algorithm_test
    python3 analysis/check_pfc.py p05
}

run_p06() {
    run_case p06-auto 4 d08 "${common[@]}" DCQCN_D08_WR_NUM=50
    python3 analysis/check_pfc.py p06
}

run_p07() {
    run_case p07-insufficient 4 d08 "${common[@]}" SWITCH_BUFFER_SIZE=2kB \
        PFC_HEADROOM=1B DCQCN_D08_WR_NUM=50
    python3 analysis/check_pfc.py p07
}

run_p08() {
    local base=(ENABLE_ECN=1 ECN_THRESHOLD=512B CNP_MERGE_INTERVAL=50us
        SWITCH_FABRIC_SPEED=10Mbps SWITCH_BUFFER_SIZE=16kB RETRANS_TIMEOUT=1000us
        DCQCN_ALPHA_INTERVAL=5us DCQCN_DECREASE_INTERVAL=4us
        DCQCN_RECOVERY_INTERVAL=20us DCQCN_D08_WR_NUM=50 MAX_TICKS=50000000000000)
    run_case p08-off-off 4 d08 "${base[@]}"
    run_case p08-dcqcn-off 4 d08 "${base[@]}" ENABLE_DCQCN=1
    run_case p08-off-pfc 4 d08 "${base[@]}" "${common[@]}"
    run_case p08-dcqcn-pfc 4 d08 "${base[@]}" ENABLE_DCQCN=1 "${common[@]}"
    run_case p08-read 4 p08read "${base[@]}" ENABLE_DCQCN=1 "${common[@]}" ECN_THRESHOLD=0B
    python3 analysis/check_pfc.py p08
}

run_p09() {
    run_case p09-xon-loss 4 d08 "${common[@]}" PFC_DROP_XON_COUNT=1 DCQCN_D08_WR_NUM=50
    run_case p09-lifecycle 4 e07 ENABLE_ECN=1 ECN_THRESHOLD=0B ENABLE_PFC=1 \
        SWITCH_BUFFER_SIZE=32kB PFC_XOFF=512B PFC_XON=128B PFC_HEADROOM=8kB \
        CNP_MERGE_INTERVAL=1s DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 DROP_COUNT=1 \
        RETRANS_TIMEOUT=1000us DUPLICATE_SERVER_OPCODE=10 DUPLICATE_CLIENT_OPCODE=10 \
        DUPLICATE_COUNT=1 RNIC_PFC_PORT_RESET_TIME=60us
    python3 analysis/check_pfc.py p09
}

run_p10() {
    run_case p10-auto 6 d08 "${common[@]}" DCQCN_D08_WR_NUM=50
    ./scripts/run_ecn.sh all
    python3 analysis/check_pfc.py p10
}

case "$CASE_NAME" in
    all)
        algorithm_test
        run_p01; run_p02; run_p03; run_p04; run_p05; run_p06; run_p07; run_p08; run_p09; run_p10
        ;;
    p01|p02|p03|p04|p05|p06|p07|p08|p09|p10) "run_$CASE_NAME" ;;
    *) echo "Usage: $0 [all|p01|p02|p03|p04|p05|p06|p07|p08|p09|p10]" >&2; exit 2 ;;
esac
