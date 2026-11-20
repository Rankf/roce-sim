#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
if [[ "$CASE_NAME" == all ]]; then
    for version in 4 6; do
        for name in s01 s02 s03 s04 s05 s06 s07 s08; do
            ROCE_IP_VERSION=$version "$ROOT/scripts/run_switch.sh" "$name"
        done
    done
    exit 0
fi
VERSION=${ROCE_IP_VERSION:-4}
RUN_ID=switch-$CASE_NAME-ipv$VERSION
OUTDIR=${OUTDIR:-$ROOT/results/$RUN_ID}
mkdir -p "$OUTDIR"
cd "$ROOT/model/csrna"
FABRIC_SPEED=${SWITCH_FABRIC_SPEED:-100Gbps}
BUFFER_SIZE=${SWITCH_BUFFER_SIZE:-1MB}
SWITCH_NUM=${SWITCH_NUM:-1}
SWITCH_LINK_SPEED=${SWITCH_LINK_SPEED:-$FABRIC_SPEED}
SWITCH_LINK_DELAY=${SWITCH_LINK_DELAY:-10us}
SWITCH1_PFC_XOFF=${SWITCH1_PFC_XOFF:-}
SWITCH2_BUFFER_SIZE=${SWITCH2_BUFFER_SIZE:-}
SWITCH2_PFC_HEADROOM=${SWITCH2_PFC_HEADROOM:-}
DMA_DELAY_NODE=${DMA_DELAY_NODE:--1}
case "$CASE_NAME" in
    s05) RETRANS_TIMEOUT=${RETRANS_TIMEOUT:-5us} ;;
    s06|s08) RETRANS_TIMEOUT=${RETRANS_TIMEOUT:-1000us} ;;
    *) RETRANS_TIMEOUT=${RETRANS_TIMEOUT:-100us} ;;
esac
case "$CASE_NAME" in
    s05) BUFFER_SIZE=${SWITCH_BUFFER_SIZE:-512B} ;;
    s06) FABRIC_SPEED=${SWITCH_FABRIC_SPEED:-10Mbps}; MAX_TICKS=${MAX_TICKS:-5000000000000} ;;
    s08) MAX_TICKS=${MAX_TICKS:-800000000000} ;;
esac
MAX_TICKS=${MAX_TICKS:-200000000000}
run_pair() {
    local operation=$1
    local protect_mode=$2
    local wr_num=$3
    local tag=${4:-$operation-$protect_mode}
    local result_dir=$OUTDIR/$tag
    mkdir -p "$result_dir/gem5"
    local command=(build/X86/gem5.opt --outdir="$result_dir/gem5"
        --debug-flags=MrResc,RdmaEngine,HanGuRnic
        configs/example/rdma/hangu_rnic_se.py
        --cpu-type TimingSimpleCPU --cpu-clock 2GHz --num-cpus 1 --node-num 4
        --ethernet-linkspeed 100Gbps --ethernet-linkdelay 10us
        --pci-linkspeed 128Gbps --qpc-cache-cap 300 --reorder-cap 64
        --mem-size 1024MB
        -c "${RNIC_COMMANDS:-tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/client;tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/client}"
        -o "${RNIC_OPTIONS:--s 10 -t 1 -m $operation -e $protect_mode -n $wr_num;-s 10 -l 11 -t 1 -m $operation -e $protect_mode -n $wr_num;-s 12 -t 1 -m $operation -e $protect_mode -n $wr_num;-s 12 -l 13 -t 1 -m $operation -e $protect_mode -n $wr_num}"
        --roce-ip-version "$VERSION"
        --rnic-link-delay 10us
        --retrans-timeout "$RETRANS_TIMEOUT"
        --switch-num "$SWITCH_NUM"
        --switch-fabric-speed "$FABRIC_SPEED"
        --switch-link-speed "$SWITCH_LINK_SPEED"
        --switch-link-delay "$SWITCH_LINK_DELAY"
        --switch-output-buffer-size "$BUFFER_SIZE"
        --switch1-pfc-xoff "$SWITCH1_PFC_XOFF"
        --switch2-output-buffer-size "$SWITCH2_BUFFER_SIZE"
        --switch2-pfc-headroom "$SWITCH2_PFC_HEADROOM"
        --switch-stats
        --packet-trace-prefix "$result_dir/rocev2"
        --abs-max-tick "$MAX_TICKS")
    if [[ ${ENABLE_ECN:-0} == 1 ]]; then
        command+=(--switch-enable-ecn --rnic-enable-cnp)
    fi
    if [[ -n ${ECN_THRESHOLD:-} ]]; then
        command+=(--switch-ecn-threshold "$ECN_THRESHOLD")
    fi
    if [[ -n ${CNP_MERGE_INTERVAL:-} ]]; then
        command+=(--rnic-cnp-merge-interval "$CNP_MERGE_INTERVAL")
    fi
    if [[ ${ENABLE_PACING:-0} == 1 ]]; then
        command+=(--rnic-enable-pacing --rnic-pacing-rate "${PACING_RATE:-100Gbps}")
    fi
    if [[ ${ENABLE_DCQCN:-0} == 1 ]]; then
        command+=(--rnic-enable-dcqcn)
    fi
    for parameter in DCQCN_MAX_RATE DCQCN_MIN_RATE DCQCN_RATE_AI DCQCN_RATE_HAI; do
        if [[ -n ${!parameter:-} ]]; then
            option=${parameter,,}
            command+=("--${option//_/-}" "${!parameter}")
        fi
    done
    for parameter in DCQCN_ALPHA_INTERVAL DCQCN_DECREASE_INTERVAL DCQCN_RECOVERY_INTERVAL; do
        if [[ -n ${!parameter:-} ]]; then
            option=${parameter,,}
            command+=("--${option//_/-}" "${!parameter}")
        fi
    done
    if [[ -n ${DCQCN_FAST_RECOVERY_TIMES:-} ]]; then
        command+=(--dcqcn-fast-recovery-times "$DCQCN_FAST_RECOVERY_TIMES")
    fi
    if [[ ${DCQCN_DUAL_TRIGGER:-0} == 1 ]]; then
        command+=(--dcqcn-dual-trigger)
    fi
    if [[ -n ${DCQCN_BYTE_RECOVERY_BYTES:-} ]]; then
        command+=(--dcqcn-byte-recovery-bytes "$DCQCN_BYTE_RECOVERY_BYTES")
    fi
    if [[ -n ${RNIC_TX_BUSY_RETRIES:-} ]]; then
        command+=(--rnic-tx-busy-retries "$RNIC_TX_BUSY_RETRIES")
    fi
    if [[ ${ENABLE_PFC:-0} == 1 ]]; then
        command+=(--switch-enable-pfc --rnic-enable-pfc
            --switch-pfc-xoff "${PFC_XOFF:-4kB}" --switch-pfc-xon "${PFC_XON:-2kB}"
            --switch-pfc-headroom "${PFC_HEADROOM:-16kB}"
            --switch-pfc-priority "${PFC_PRIORITY:-3}"
            --switch-pfc-pause-quanta "${PFC_PAUSE_QUANTA:-1000}"
            --switch-pfc-drop-xon-count "${PFC_DROP_XON_COUNT:-0}"
            --switch-pfc-trace-prefix "$result_dir/pfc-switch")
    fi
    if [[ ${ENABLE_RX_BUFFER:-0} == 1 ]]; then
        command+=(--rnic-enable-rx-buffer --rnic-rx-buffer-size "${RX_BUFFER_SIZE:-1MB}"
            --rnic-rx-pfc-xoff "${RX_PFC_XOFF:-512kB}" --rnic-rx-pfc-xon "${RX_PFC_XON:-256kB}"
            --rnic-rx-pfc-pause-quanta "${RX_PFC_PAUSE_QUANTA:-1000}"
            --rnic-rx-pfc-refresh-interval "${RX_PFC_REFRESH_INTERVAL:-100us}"
            --rnic-rx-pfc-priority "${RX_PFC_PRIORITY:-3}")
    fi
    if [[ -n ${DMA_RETRY_COUNT:-} ]]; then
        command+=(--dma-retry-count "$DMA_RETRY_COUNT")
    fi
    if [[ -n ${DMA_DELAY:-} ]]; then
        command+=(--dma-delay "$DMA_DELAY" --dma-delay-node "$DMA_DELAY_NODE")
    fi
    if [[ ${PFC_MULTI_PRIORITY:-0} == 1 ]]; then
        command+=(--rnic-pfc-multi-priority)
    fi
    if [[ -n ${RNIC_PFC_TEST_MASK:-} ]]; then
        command+=(--rnic-pfc-test-mask "$RNIC_PFC_TEST_MASK"
            --rnic-pfc-test-quanta "${RNIC_PFC_TEST_QUANTA:-1000}"
            --rnic-pfc-test-time "${RNIC_PFC_TEST_TIME:-40us}"
            --rnic-pfc-port-reset-time "${RNIC_PFC_PORT_RESET_TIME:-0t}")
    fi
    if [[ -z ${RNIC_PFC_TEST_MASK:-} && -n ${RNIC_PFC_PORT_RESET_TIME:-} ]]; then
        command+=(--rnic-pfc-port-reset-time "$RNIC_PFC_PORT_RESET_TIME")
    fi
    if [[ -n ${DROP_SERVER_OPCODE:-} ]]; then
        command+=(--drop-server-opcode "$DROP_SERVER_OPCODE" --drop-count "${DROP_COUNT:-1}")
    fi
    if [[ -n ${DROP_CLIENT_OPCODE:-} ]]; then
        command+=(--drop-client-opcode "$DROP_CLIENT_OPCODE" --drop-count "${DROP_COUNT:-1}")
    fi
    if [[ -n ${DUPLICATE_SERVER_OPCODE:-} ]]; then
        command+=(--duplicate-server-opcode "$DUPLICATE_SERVER_OPCODE" --duplicate-count "${DUPLICATE_COUNT:-1}")
    fi
    if [[ -n ${DUPLICATE_CLIENT_OPCODE:-} ]]; then
        command+=(--duplicate-client-opcode "$DUPLICATE_CLIENT_OPCODE" --duplicate-count "${DUPLICATE_COUNT:-1}")
    fi
    printf '%q ' "${command[@]}" > "$result_dir/command.txt"
    printf '\n' >> "$result_dir/command.txt"
    printf 'case=%s\nip_version=%s\noperation=%s\nprotect_mode=%s\nfixed_wr_num=%s\nswitch_num=%s\nfabric_speed=%s\nswitch_link_speed=%s\nswitch_link_delay=%s\noutput_buffer_size=%s\n' \
        "$CASE_NAME" "$VERSION" "$operation" "$protect_mode" "$wr_num" \
        "$SWITCH_NUM" "$FABRIC_SPEED" "$SWITCH_LINK_SPEED" "$SWITCH_LINK_DELAY" \
        "$BUFFER_SIZE" > "$result_dir/run.yaml"
    git status --short > "$result_dir/source-status.txt"
    git diff > "$result_dir/local-changes.patch"
    "${command[@]}" 2>&1 | tee "$result_dir/simulation.log"
}
run_fanin() {
    local tag=$1
    local protect_mode=${2:-0}
    local wr_num=${3:-16}
    local op_mode=${4:-0}
    local result_dir=$OUTDIR/$tag
    mkdir -p "$result_dir/gem5"
    local command=(build/X86/gem5.opt --outdir="$result_dir/gem5"
        --debug-flags=MrResc,RdmaEngine,HanGuRnic
        configs/example/rdma/hangu_rnic_se.py
        --cpu-type TimingSimpleCPU --cpu-clock 2GHz --num-cpus 1 --node-num 4
        --ethernet-linkspeed 100Gbps --ethernet-linkdelay 10us
        --pci-linkspeed 128Gbps --qpc-cache-cap 300 --reorder-cap 64
        --mem-size 1024MB
        -c "${RNIC_COMMANDS:-tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/client}"
        -o "${RNIC_OPTIONS:--s 10 -t 1 -m $op_mode -e $protect_mode -n $wr_num;-s 11 -t 1 -m $op_mode -e $protect_mode -n $wr_num;-s 12 -t 1 -m $op_mode -e $protect_mode -n $wr_num;-s 10 -l 13 -t 3 -m $op_mode -e $protect_mode -n $wr_num}"
        --roce-ip-version "$VERSION"
        --rnic-link-delay 10us
        --retrans-timeout "$RETRANS_TIMEOUT"
        --switch-num "$SWITCH_NUM"
        --switch-fabric-speed "$FABRIC_SPEED"
        --switch-link-speed "$SWITCH_LINK_SPEED"
        --switch-link-delay "$SWITCH_LINK_DELAY"
        --switch-output-buffer-size "$BUFFER_SIZE"
        --switch1-pfc-xoff "$SWITCH1_PFC_XOFF"
        --switch2-output-buffer-size "$SWITCH2_BUFFER_SIZE"
        --switch2-pfc-headroom "$SWITCH2_PFC_HEADROOM"
        --switch-stats
        --packet-trace-prefix "$result_dir/rocev2"
        --abs-max-tick "$MAX_TICKS")
    if [[ ${ENABLE_ECN:-0} == 1 ]]; then
        command+=(--switch-enable-ecn --rnic-enable-cnp)
    fi
    if [[ -n ${ECN_THRESHOLD:-} ]]; then
        command+=(--switch-ecn-threshold "$ECN_THRESHOLD")
    fi
    if [[ -n ${CNP_MERGE_INTERVAL:-} ]]; then
        command+=(--rnic-cnp-merge-interval "$CNP_MERGE_INTERVAL")
    fi
    if [[ ${ENABLE_PACING:-0} == 1 ]]; then
        command+=(--rnic-enable-pacing --rnic-pacing-rate "${PACING_RATE:-100Gbps}")
    fi
    if [[ ${ENABLE_DCQCN:-0} == 1 ]]; then
        command+=(--rnic-enable-dcqcn)
    fi
    for parameter in DCQCN_MAX_RATE DCQCN_MIN_RATE DCQCN_RATE_AI DCQCN_RATE_HAI; do
        if [[ -n ${!parameter:-} ]]; then
            option=${parameter,,}
            command+=("--${option//_/-}" "${!parameter}")
        fi
    done
    for parameter in DCQCN_ALPHA_INTERVAL DCQCN_DECREASE_INTERVAL DCQCN_RECOVERY_INTERVAL; do
        if [[ -n ${!parameter:-} ]]; then
            option=${parameter,,}
            command+=("--${option//_/-}" "${!parameter}")
        fi
    done
    if [[ -n ${DCQCN_FAST_RECOVERY_TIMES:-} ]]; then
        command+=(--dcqcn-fast-recovery-times "$DCQCN_FAST_RECOVERY_TIMES")
    fi
    if [[ ${DCQCN_DUAL_TRIGGER:-0} == 1 ]]; then
        command+=(--dcqcn-dual-trigger)
    fi
    if [[ -n ${DCQCN_BYTE_RECOVERY_BYTES:-} ]]; then
        command+=(--dcqcn-byte-recovery-bytes "$DCQCN_BYTE_RECOVERY_BYTES")
    fi
    if [[ -n ${RNIC_TX_BUSY_RETRIES:-} ]]; then
        command+=(--rnic-tx-busy-retries "$RNIC_TX_BUSY_RETRIES")
    fi
    if [[ ${ENABLE_PFC:-0} == 1 ]]; then
        command+=(--switch-enable-pfc --rnic-enable-pfc
            --switch-pfc-xoff "${PFC_XOFF:-4kB}" --switch-pfc-xon "${PFC_XON:-2kB}"
            --switch-pfc-headroom "${PFC_HEADROOM:-16kB}"
            --switch-pfc-priority "${PFC_PRIORITY:-3}"
            --switch-pfc-pause-quanta "${PFC_PAUSE_QUANTA:-1000}"
            --switch-pfc-drop-xon-count "${PFC_DROP_XON_COUNT:-0}"
            --switch-pfc-trace-prefix "$result_dir/pfc-switch")
    fi
    if [[ ${ENABLE_RX_BUFFER:-0} == 1 ]]; then
        command+=(--rnic-enable-rx-buffer --rnic-rx-buffer-size "${RX_BUFFER_SIZE:-1MB}"
            --rnic-rx-pfc-xoff "${RX_PFC_XOFF:-512kB}" --rnic-rx-pfc-xon "${RX_PFC_XON:-256kB}"
            --rnic-rx-pfc-pause-quanta "${RX_PFC_PAUSE_QUANTA:-1000}"
            --rnic-rx-pfc-refresh-interval "${RX_PFC_REFRESH_INTERVAL:-100us}"
            --rnic-rx-pfc-priority "${RX_PFC_PRIORITY:-3}")
    fi
    if [[ -n ${DMA_RETRY_COUNT:-} ]]; then
        command+=(--dma-retry-count "$DMA_RETRY_COUNT")
    fi
    if [[ -n ${DMA_DELAY:-} ]]; then
        command+=(--dma-delay "$DMA_DELAY" --dma-delay-node "$DMA_DELAY_NODE")
    fi
    if [[ ${PFC_MULTI_PRIORITY:-0} == 1 ]]; then
        command+=(--rnic-pfc-multi-priority)
    fi
    if [[ -n ${RNIC_PFC_TEST_MASK:-} ]]; then
        command+=(--rnic-pfc-test-mask "$RNIC_PFC_TEST_MASK"
            --rnic-pfc-test-quanta "${RNIC_PFC_TEST_QUANTA:-1000}"
            --rnic-pfc-test-time "${RNIC_PFC_TEST_TIME:-40us}"
            --rnic-pfc-port-reset-time "${RNIC_PFC_PORT_RESET_TIME:-0t}")
    fi
    if [[ -z ${RNIC_PFC_TEST_MASK:-} && -n ${RNIC_PFC_PORT_RESET_TIME:-} ]]; then
        command+=(--rnic-pfc-port-reset-time "$RNIC_PFC_PORT_RESET_TIME")
    fi
    if [[ -n ${DROP_SERVER_OPCODE:-} ]]; then
        command+=(--drop-server-opcode "$DROP_SERVER_OPCODE" --drop-count "${DROP_COUNT:-1}")
    fi
    if [[ -n ${DROP_CLIENT_OPCODE:-} ]]; then
        command+=(--drop-client-opcode "$DROP_CLIENT_OPCODE" --drop-count "${DROP_COUNT:-1}")
    fi
    if [[ -n ${DUPLICATE_SERVER_OPCODE:-} ]]; then
        command+=(--duplicate-server-opcode "$DUPLICATE_SERVER_OPCODE" --duplicate-count "${DUPLICATE_COUNT:-1}")
    fi
    if [[ -n ${DUPLICATE_CLIENT_OPCODE:-} ]]; then
        command+=(--duplicate-client-opcode "$DUPLICATE_CLIENT_OPCODE" --duplicate-count "${DUPLICATE_COUNT:-1}")
    fi
    printf '%q ' "${command[@]}" > "$result_dir/command.txt"
    printf '\n' >> "$result_dir/command.txt"
    printf 'case=%s\nip_version=%s\noperation=%s\nprotect_mode=%s\nfixed_wr_num=%s\nswitch_num=%s\nfabric_speed=%s\nswitch_link_speed=%s\nswitch_link_delay=%s\noutput_buffer_size=%s\n' \
        "$CASE_NAME" "$VERSION" "$op_mode" "$protect_mode" "$wr_num" \
        "$SWITCH_NUM" "$FABRIC_SPEED" "$SWITCH_LINK_SPEED" "$SWITCH_LINK_DELAY" \
        "$BUFFER_SIZE" > "$result_dir/run.yaml"
    git status --short > "$result_dir/source-status.txt"
    git diff > "$result_dir/local-changes.patch"
    "${command[@]}" 2>&1 | tee "$result_dir/simulation.log"
}
case "$CASE_NAME" in
    s01)
        run_pair 0 0 16 write
        run_pair 1 0 16 read
        run_pair 0 41 0 send
        ;;
    s02) run_pair 0 0 16 parallel ;;
    s03) run_pair 0 90 16 bidirectional ;;
    s04) run_fanin fanin ;;
    s05) run_fanin overflow 31 0 ;;
    s06) run_fanin busy 31 0 ;;
    s07) run_pair 0 0 16 timing ;;
    s08)
        run_pair 0 38 0 multipacket
        run_pair 0 19 0 cross-page
        run_pair 0 57 0 ring-stress
        ;;
    e01) run_fanin control 31 0 ;;
    e04) run_fanin feedback 31 0 ;;
    e05) run_pair 0 57 0 multi-qp ;;
    e06) run_pair 1 0 16 read-response ;;
    e07) run_pair 0 47 0 merge-reset ;;
    e08)
        run_pair 0 53 0 read-credit
        run_pair 0 46 0 send-recv
        ;;
    e09) run_fanin drop-cnp 31 0 ;;
    d08) run_fanin sustained "${DCQCN_PROTECT_MODE:-91}" "${DCQCN_D08_WR_NUM:-100}" ;;
    p08read) run_fanin read-response 91 "${DCQCN_D08_WR_NUM:-50}" 1 ;;
    ms07) run_fanin priority 57 "${DCQCN_D08_WR_NUM:-0}" 57 ;;
    ms08send) run_pair 0 46 0 send-recv ;;
    ms08reset) run_pair 0 47 0 merge-reset ;;
    *) echo "Usage: $0 [all|s01|s02|s03|s04|s05|s06|s07|s08|e01|e04|e05|e06|e07|e08|e09|d08|ms07|ms08send|ms08reset]" >&2; exit 2 ;;
esac
