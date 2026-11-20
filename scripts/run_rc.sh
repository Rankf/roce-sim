#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
MODEL=csrna
MODEL_DIR="$ROOT/model/csrna"
OP=${1:-write}
case "$OP" in
    write) OP_MODE=0 ;;
    read) OP_MODE=1 ;;
    *) echo "Usage: $0 [write|read]" >&2; exit 2 ;;
esac
RUN_ID=${RUN_ID:-rc-$OP-$(date -u +%Y%m%dT%H%M%SZ)}
OUTDIR=${OUTDIR:-$ROOT/results/$RUN_ID}
mkdir -p "$OUTDIR/gem5"

cd "$MODEL_DIR"
CPU_TYPE=${CPU_TYPE:-TimingSimpleCPU}
COMMAND=(build/X86/gem5.opt
    --outdir="$OUTDIR/gem5")
if [[ -n ${DEBUG_FLAGS:-} ]]; then
    COMMAND+=(--debug-flags="$DEBUG_FLAGS")
fi
COMMAND+=(configs/example/rdma/hangu_rnic_se.py
    --cpu-type "$CPU_TYPE"
    --cpu-clock 2GHz
    --num-cpus 1
    --node-num 2
    --ethernet-linkspeed 100Gbps
    --pci-linkspeed 128Gbps
    --qpc-cache-cap 300
    --reorder-cap 64
    --mem-size 1024MB
    -c 'tests/test-progs/hangu-rnic/bin/server;tests/test-progs/hangu-rnic/bin/client'
    -o "-s 10 -t 1 -m $OP_MODE -e ${PROTECT_MODE:-0} -n ${FIXED_WR_NUM:-0};-s 10 -l 11 -t 1 -m $OP_MODE -e ${PROTECT_MODE:-0} -n ${FIXED_WR_NUM:-0}")
if [[ -n ${DRAM_TCL:-} ]]; then
    COMMAND+=(--param "cltsys.mem_ctrls[0].dram.tCL='$DRAM_TCL'"
        --param "svrsys.mem_ctrls[0].dram.tCL='$DRAM_TCL'")
fi
if [[ -n ${DRAM_TRCD:-} ]]; then
    COMMAND+=(--param "cltsys.mem_ctrls[0].dram.tRCD='$DRAM_TRCD'"
        --param "svrsys.mem_ctrls[0].dram.tRCD='$DRAM_TRCD'")
fi
if [[ -n ${DMA_RETRY_COUNT:-} ]]; then
    COMMAND+=(--dma-retry-count "$DMA_RETRY_COUNT")
fi
if [[ -n ${DMA_DELAY:-} ]]; then
    COMMAND+=(--dma-delay "$DMA_DELAY")
fi
if [[ ${ENABLE_PFC:-0} == 1 ]]; then
    COMMAND+=(--switch-enable-pfc --rnic-enable-pfc
        --switch-pfc-xoff "${PFC_XOFF:-4kB}" --switch-pfc-xon "${PFC_XON:-2kB}"
        --switch-pfc-headroom "${PFC_HEADROOM:-16kB}"
        --switch-pfc-pause-quanta "${PFC_PAUSE_QUANTA:-1000}"
        --switch-pfc-trace-prefix "$OUTDIR/pfc-switch")
fi
if [[ ${ENABLE_RX_BUFFER:-0} == 1 ]]; then
    COMMAND+=(--rnic-enable-rx-buffer --rnic-rx-buffer-size "${RX_BUFFER_SIZE:-1MB}"
        --rnic-rx-pfc-xoff "${RX_PFC_XOFF:-512kB}" --rnic-rx-pfc-xon "${RX_PFC_XON:-256kB}"
        --rnic-rx-pfc-pause-quanta "${RX_PFC_PAUSE_QUANTA:-1000}"
        --rnic-rx-pfc-refresh-interval "${RX_PFC_REFRESH_INTERVAL:-100us}"
        --rnic-rx-pfc-priority "${RX_PFC_PRIORITY:-3}")
fi
if [[ -n ${RETRANS_TIMEOUT:-} ]]; then
    COMMAND+=(--retrans-timeout "$RETRANS_TIMEOUT")
fi
if [[ -n ${ATOMIC_RESPONSE_DELAY:-} ]]; then
    COMMAND+=(--atomic-response-delay "$ATOMIC_RESPONSE_DELAY")
fi
if [[ -n ${ROCE_IP_VERSION:-} ]]; then
    COMMAND+=(--roce-ip-version "$ROCE_IP_VERSION")
fi
if [[ -n ${RETRANS_LIMIT:-} ]]; then
    COMMAND+=(--retrans-limit "$RETRANS_LIMIT")
fi
if [[ -n ${RNR_RETRY_LIMIT:-} ]]; then
    COMMAND+=(--rnr-retry-limit "$RNR_RETRY_LIMIT")
fi
if [[ -n ${CQ_CAPACITY:-} ]]; then
    COMMAND+=(--cq-capacity "$CQ_CAPACITY")
fi
if [[ -n ${INITIAL_PSN:-} ]]; then
    COMMAND+=(--initial-psn "$INITIAL_PSN")
fi
if [[ -n ${DROP_SERVER_OPCODE:-} || -n ${DROP_CLIENT_OPCODE:-} ]]; then
    COMMAND+=(--drop-server-opcode "${DROP_SERVER_OPCODE:-0}"
        --drop-client-opcode "${DROP_CLIENT_OPCODE:-0}"
        --drop-count "${DROP_COUNT:-1}")
fi
if [[ -n ${DUPLICATE_SERVER_OPCODE:-} || -n ${DUPLICATE_CLIENT_OPCODE:-} ]]; then
    COMMAND+=(--duplicate-server-opcode "${DUPLICATE_SERVER_OPCODE:-0}"
        --duplicate-client-opcode "${DUPLICATE_CLIENT_OPCODE:-0}"
        --duplicate-count "${DUPLICATE_COUNT:-1}")
fi
if [[ ${PACKET_TRACE:-1} == 1 ]]; then
    COMMAND+=(--packet-trace-prefix "$OUTDIR/rocev2")
fi
if [[ -n ${MAX_TICKS:-} ]]; then
    COMMAND+=(--abs-max-tick "$MAX_TICKS")
fi
printf '%q ' "${COMMAND[@]}" > "$OUTDIR/command.txt"
printf '\n' >> "$OUTDIR/command.txt"
printf 'model=%s\ncommit=%s\noperation=%s\ncpu=%s\nprotect_mode=%s\nfixed_wr_num=%s\ninitial_psn=%s\nretrans_timeout=%s\natomic_response_delay=%s\nroce_ip_version=%s\nretrans_limit=%s\nrnr_retry_limit=%s\ncq_capacity=%s\ndrop_server_opcode=%s\ndrop_client_opcode=%s\ndrop_count=%s\nduplicate_server_opcode=%s\nduplicate_client_opcode=%s\npacket_trace=%s\nmemory=1024MB\nendpoints=2\n' \
    "$MODEL" "$(git rev-parse HEAD)" "$OP" "$CPU_TYPE" "${PROTECT_MODE:-0}" \
    "${FIXED_WR_NUM:-0}" "${INITIAL_PSN:-0}" "${RETRANS_TIMEOUT:-100us}" \
    "${ATOMIC_RESPONSE_DELAY:-0t}" "${ROCE_IP_VERSION:-4}" "${RETRANS_LIMIT:-7}" "${RNR_RETRY_LIMIT:-7}" "${CQ_CAPACITY:-128}" "${DROP_SERVER_OPCODE:-0}" "${DROP_CLIENT_OPCODE:-0}" \
    "${DROP_COUNT:-0}" "${DUPLICATE_SERVER_OPCODE:-0}" \
    "${DUPLICATE_CLIENT_OPCODE:-0}" "${PACKET_TRACE:-1}" > "$OUTDIR/run.yaml"
git status --short > "$OUTDIR/source-status.txt"
git diff > "$OUTDIR/local-changes.patch"
set -o pipefail
"${COMMAND[@]}" 2>&1 | tee "$OUTDIR/simulation.log"
