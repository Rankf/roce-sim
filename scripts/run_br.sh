#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local tag=$1 version=$2 name=$3
    shift 3
    env OUTDIR="$ROOT/results/br-$tag-ipv$version" ROCE_IP_VERSION="$version" \
        "$@" "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/br-$tag-ipv$version.log" 2>&1
}

algorithm_test() {
    g++ -std=c++11 -Wall -Wextra -pedantic tests/dcqcn_format_test.cc -o results/br-format-test
    ./results/br-format-test | tee results/br-format.log
}

common=(ENABLE_ECN=1 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=50us
    DCQCN_ALPHA_INTERVAL=5us DCQCN_DECREASE_INTERVAL=4us
    DCQCN_RECOVERY_INTERVAL=20us RETRANS_TIMEOUT=1000us)
dual=(ENABLE_DCQCN=1 DCQCN_DUAL_TRIGGER=1 DCQCN_BYTE_RECOVERY_BYTES=128B)

run_br01() {
    run_case 01-default 4 e05 "${common[@]}" ENABLE_DCQCN=1
    python3 analysis/check_br.py br01
}

run_br02() {
    run_case 02-send 4 s08 "${common[@]}" "${dual[@]}" RNIC_TX_BUSY_RETRIES=20 \
        MAX_TICKS=50000000000000
    python3 analysis/check_br.py br02
}

run_br03() {
    algorithm_test
    python3 analysis/check_br.py br03
}

run_br04() {
    algorithm_test
    python3 analysis/check_br.py br04
}

run_br05() {
    algorithm_test
    python3 analysis/check_br.py br05
}

run_br06() {
    run_case 06-lifecycle 4 e07 "${common[@]}" "${dual[@]}" CNP_MERGE_INTERVAL=1s \
        DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 DROP_COUNT=1 \
        DUPLICATE_SERVER_OPCODE=10 DUPLICATE_CLIENT_OPCODE=10 DUPLICATE_COUNT=1
    python3 analysis/check_br.py br06
}

run_br07() {
    run_case 07-pfc 4 d08 "${common[@]}" "${dual[@]}" ENABLE_PFC=1 \
        SWITCH_BUFFER_SIZE=16kB PFC_XOFF=512B PFC_XON=128B PFC_HEADROOM=8kB \
        PFC_PAUSE_QUANTA=1000 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=4kB \
        RX_PFC_XOFF=512B RX_PFC_XON=128B RX_PFC_PAUSE_QUANTA=1000 \
        RX_PFC_REFRESH_INTERVAL=50us DMA_DELAY=100us DMA_DELAY_NODE=3 \
        DROP_SERVER_OPCODE=10 DROP_COUNT=1 RNIC_TX_BUSY_RETRIES=20 \
        DCQCN_D08_WR_NUM=50 MAX_TICKS=50000000000000
    python3 analysis/check_br.py br07
}

run_br08() {
    run_case 08-dual 6 d08 "${common[@]}" "${dual[@]}" DCQCN_D08_WR_NUM=50
    ./scripts/run_ecn.sh all
    python3 analysis/check_dcqcn.py
    python3 analysis/check_pfc.py
    python3 analysis/check_rx.py
    python3 analysis/check_mspfc.py
    python3 analysis/check_br.py br08
}

case "$CASE_NAME" in
    all)
        algorithm_test
        run_br01; run_br02; run_br03; run_br04; run_br05; run_br06; run_br07; run_br08
        ;;
    br01|br02|br03|br04|br05|br06|br07|br08) "run_$CASE_NAME" ;;
    *) echo "Usage: $0 [all|br01|br02|br03|br04|br05|br06|br07|br08]" >&2; exit 2 ;;
esac
