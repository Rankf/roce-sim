#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local tag=$1 version=$2 name=$3
    shift 3
    env OUTDIR="$ROOT/results/rx-$tag-ipv$version" ROCE_IP_VERSION="$version" \
        "$@" "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/rx-$tag-ipv$version.log" 2>&1
}

common=(ENABLE_PFC=1 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=4kB RX_PFC_XOFF=512B
    RX_PFC_XON=128B RX_PFC_PAUSE_QUANTA=1000 RX_PFC_REFRESH_INTERVAL=50us
    SWITCH_BUFFER_SIZE=16kB PFC_XOFF=512B PFC_XON=128B PFC_HEADROOM=8kB
    DMA_DELAY=100us RETRANS_TIMEOUT=1000us MAX_TICKS=50000000000000)

run_rx01() {
    run_case 01-account 4 d08 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=64kB \
        RX_PFC_XOFF=32kB RX_PFC_XON=16kB DCQCN_D08_WR_NUM=8 RETRANS_TIMEOUT=1000us
    RUN_ID=rx01-write FIXED_WR_NUM=1 ./scripts/run_rc.sh write > results/rx01-write.log 2>&1
    RUN_ID=rx01-read FIXED_WR_NUM=1 ./scripts/run_rc.sh read > results/rx01-read.log 2>&1
    python3 analysis/check_fixed_rc.py results/rx01-write results/rx01-read
    python3 analysis/check_rx.py rx01
}

run_rx02() {
    run_case 02-overflow 4 d08 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=512B \
        RX_PFC_XOFF=256B RX_PFC_XON=128B DMA_DELAY=100us DCQCN_D08_WR_NUM=8 \
        RETRANS_TIMEOUT=1000us MAX_TICKS=50000000000000
    python3 analysis/check_rx.py rx02
}

run_rx03() {
    run_case 03-auto 4 d08 "${common[@]}" PFC_XOFF=2kB PFC_XON=512B DCQCN_D08_WR_NUM=50
    python3 analysis/check_rx.py rx03
}

run_rx04() {
    run_case 04-propagation 4 d08 "${common[@]}" DCQCN_D08_WR_NUM=50
    python3 analysis/check_rx.py rx04
}

run_rx05() {
    run_case 05-insufficient 4 d08 "${common[@]}" RX_BUFFER_SIZE=1kB DCQCN_D08_WR_NUM=50
    python3 analysis/check_rx.py rx05
}

run_rx06() {
    run_case 06-read 4 p08read "${common[@]}" DCQCN_D08_WR_NUM=50
    run_case 06-operations 4 e08 "${common[@]}" RX_BUFFER_SIZE=16kB RX_PFC_XOFF=4kB RX_PFC_XON=1kB
    run_case 06-multipacket 4 s08 "${common[@]}" RX_BUFFER_SIZE=16kB RX_PFC_XOFF=4kB RX_PFC_XON=1kB
    python3 analysis/check_rx.py rx06
}

run_rx07() {
    run_case 07-multiqp 4 e05 "${common[@]}"
    python3 analysis/check_rx.py rx07
}

run_rx08() {
    run_case 08-reset 4 e07 "${common[@]}" SWITCH_BUFFER_SIZE=32kB \
        CNP_MERGE_INTERVAL=1s DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 DROP_COUNT=1 \
        DUPLICATE_SERVER_OPCODE=10 DUPLICATE_CLIENT_OPCODE=10 DUPLICATE_COUNT=1
    python3 analysis/check_rx.py rx08
}

run_rx09() {
    RUN_ID=rx09-rnr ENABLE_PFC=1 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=64kB \
        RX_PFC_XOFF=32kB RX_PFC_XON=16kB ./scripts/run_qp.sh rnr-recovery \
        > results/rx09-rnr.log 2>&1
    python3 analysis/check_rnr.py results/rx09-rnr
    python3 analysis/check_rx.py rx09
}

run_rx10() {
    run_case 10-auto 6 d08 "${common[@]}" DCQCN_D08_WR_NUM=50
    ./scripts/run_ecn.sh all
    python3 analysis/check_rx.py rx10
}

case "$CASE_NAME" in
    all)
        run_rx01; run_rx02; run_rx03; run_rx04; run_rx05
        run_rx06; run_rx07; run_rx08; run_rx09; run_rx10
        ;;
    rx01|rx02|rx03|rx04|rx05|rx06|rx07|rx08|rx09|rx10) "run_$CASE_NAME" ;;
    *) echo "Usage: $0 [all|rx01|rx02|rx03|rx04|rx05|rx06|rx07|rx08|rx09|rx10]" >&2; exit 2 ;;
esac
