#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local tag=$1 version=$2 name=$3
    shift 3
    env OUTDIR="$ROOT/results/mspfc-$tag-ipv$version" ROCE_IP_VERSION="$version" \
        SWITCH_NUM=2 "$@" "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/mspfc-$tag-ipv$version.log" 2>&1
}

common=(ENABLE_PFC=1 SWITCH_FABRIC_SPEED=100Gbps SWITCH_BUFFER_SIZE=16kB
    PFC_XOFF=512B PFC_XON=128B PFC_HEADROOM=8kB PFC_PAUSE_QUANTA=1000
    RETRANS_TIMEOUT=1000us MAX_TICKS=50000000000000)
rx_common=("${common[@]}" PFC_XOFF=256B ENABLE_PACING=1 PACING_RATE=5Gbps
    ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=16kB RX_PFC_XOFF=1280B RX_PFC_XON=512B
    PFC_PAUSE_QUANTA=10000 RX_PFC_PAUSE_QUANTA=10000 RX_PFC_REFRESH_INTERVAL=50us
    DMA_DELAY=500us DMA_DELAY_NODE=3 RETRANS_TIMEOUT=100ms)
pair_endpoints=(RNIC_COMMANDS='tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/client;tests/test-progs/hangu-rnic/bin/client')
pair_ring=("${pair_endpoints[@]}"
    RNIC_OPTIONS='-s 10 -t 1 -m 57 -e 57 -n 80;-s 11 -t 1 -m 57 -e 57 -n 80;-s 11 -l 12 -t 1 -m 57 -e 57 -n 80;-s 10 -l 13 -t 1 -m 57 -e 57 -n 80')
pair_bidirectional=("${pair_endpoints[@]}"
    RNIC_OPTIONS='-s 10 -t 1 -m 0 -e 90 -n 16;-s 11 -t 1 -m 0 -e 90 -n 16;-s 11 -l 12 -t 1 -m 0 -e 90 -n 16;-s 10 -l 13 -t 1 -m 0 -e 90 -n 16')
pair_send=("${pair_endpoints[@]}"
    RNIC_OPTIONS='-s 10 -t 1 -m 0 -e 46 -n 0;-s 11 -t 1 -m 0 -e 46 -n 0;-s 11 -l 12 -t 1 -m 0 -e 46 -n 0;-s 10 -l 13 -t 1 -m 0 -e 46 -n 0')
pair_reset=("${pair_endpoints[@]}"
    RNIC_OPTIONS='-s 10 -t 1 -m 0 -e 47 -n 0;-s 11 -t 1 -m 0 -e 47 -n 0;-s 11 -l 12 -t 1 -m 0 -e 47 -n 0;-s 10 -l 13 -t 1 -m 0 -e 47 -n 0')
joint=(ENABLE_ECN=1 ECN_THRESHOLD=0B CNP_MERGE_INTERVAL=50us ENABLE_DCQCN=1
    DCQCN_ALPHA_INTERVAL=5us DCQCN_DECREASE_INTERVAL=4us DCQCN_RECOVERY_INTERVAL=20us)

run_ms01() {
    run_case 01-basic 4 s01 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=64kB
    run_case 01-basic 4 d08 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=64kB \
        DCQCN_D08_WR_NUM=8 RETRANS_TIMEOUT=1000us
    run_case 01-basic 6 d08 ENABLE_RX_BUFFER=1 RX_BUFFER_SIZE=64kB \
        DCQCN_D08_WR_NUM=8 RETRANS_TIMEOUT=1000us
    python3 analysis/check_mspfc.py ms01
}

run_ms02() {
    python3 analysis/check_mspfc.py ms02
}

run_ms03() {
    run_case 03-link 4 d08 "${common[@]}" SWITCH_LINK_SPEED=10Mbps \
        DCQCN_D08_WR_NUM=50
    python3 analysis/check_mspfc.py ms03
}

run_ms04() {
    run_case 04-control 4 d08 "${rx_common[@]}" DMA_DELAY=0t PACING_RATE=1Gbps \
        SWITCH1_PFC_XOFF=138B DCQCN_PROTECT_MODE=57 DCQCN_D08_WR_NUM=0
    run_case 04-rx 4 d08 "${rx_common[@]}" PACING_RATE=1Gbps \
        SWITCH1_PFC_XOFF=138B DCQCN_PROTECT_MODE=57 DCQCN_D08_WR_NUM=0
    python3 analysis/check_mspfc.py ms04
}

run_ms05() {
    run_case 05-recovery 4 d08 "${rx_common[@]}" PFC_DROP_XON_COUNT=1 \
        PFC_PAUSE_QUANTA=10000 RX_PFC_PAUSE_QUANTA=10000 DCQCN_D08_WR_NUM=50
    python3 analysis/check_mspfc.py ms05
}

run_ms06() {
    run_case 06-insufficient 4 d08 "${rx_common[@]}" SWITCH2_BUFFER_SIZE=512B \
        SWITCH2_PFC_HEADROOM=1B DCQCN_D08_WR_NUM=50
    python3 analysis/check_mspfc.py ms06
}

run_ms07() {
    run_case 07-same 4 ms07 "${rx_common[@]}" RX_PFC_XOFF=256B RX_PFC_XON=0B \
        DCQCN_D08_WR_NUM=80 "${pair_ring[@]}"
    run_case 07-isolated 4 ms07 "${rx_common[@]}" RX_PFC_XOFF=256B RX_PFC_XON=0B \
        DCQCN_D08_WR_NUM=80 PFC_MULTI_PRIORITY=1 DMA_DELAY_NODE=-1 "${pair_ring[@]}"
    python3 analysis/check_mspfc.py ms07
}

run_ms08() {
    run_case 08-bidirectional 4 s03 "${rx_common[@]}" "${pair_bidirectional[@]}"
    run_case 08-read 4 p08read "${rx_common[@]}" DCQCN_D08_WR_NUM=20
    run_case 08-send 4 ms08send "${rx_common[@]}" "${pair_send[@]}"
    run_case 08-reset 4 ms08reset "${rx_common[@]}" "${pair_reset[@]}" CNP_MERGE_INTERVAL=1s \
        DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 DROP_COUNT=1 \
        DUPLICATE_SERVER_OPCODE=10 DUPLICATE_CLIENT_OPCODE=10 DUPLICATE_COUNT=1
    python3 analysis/check_mspfc.py ms08
}

run_ms09() {
    run_case 09-joint 4 d08 "${rx_common[@]}" "${joint[@]}" DCQCN_D08_WR_NUM=50
    python3 analysis/check_mspfc.py ms09
}

run_ms10() {
    run_case 10-rx 6 d08 "${rx_common[@]}" DCQCN_D08_WR_NUM=50
    run_case 10-joint 6 d08 "${rx_common[@]}" "${joint[@]}" DCQCN_D08_WR_NUM=50
    ./scripts/run_ecn.sh all
    python3 analysis/check_dcqcn.py
    python3 analysis/check_pfc.py
    python3 analysis/check_rx.py
    python3 analysis/check_mspfc.py ms10
}

case "$CASE_NAME" in
    all)
        run_ms01; run_ms02; run_ms03; run_ms04; run_ms05
        run_ms06; run_ms07; run_ms08; run_ms09; run_ms10
        ;;
    ms01|ms02|ms03|ms04|ms05|ms06|ms07|ms08|ms09|ms10) "run_$CASE_NAME" ;;
    *) echo "Usage: $0 [all|ms01|ms02|ms03|ms04|ms05|ms06|ms07|ms08|ms09|ms10]" >&2; exit 2 ;;
esac
