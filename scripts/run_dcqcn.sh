#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CASE_NAME=${1:-all}
cd "$ROOT"
mkdir -p results

run_case() {
    local tag=$1
    local version=$2
    local name=$3
    shift 3
    env OUTDIR="$ROOT/results/dcqcn-$tag-ipv$version" ROCE_IP_VERSION="$version" \
        "$@" "$ROOT/scripts/run_switch.sh" "$name" \
        > "$ROOT/results/dcqcn-$tag-ipv$version.log" 2>&1
}

algorithm_test() {
    g++ -std=c++11 -Wall -Wextra -pedantic tests/dcqcn_format_test.cc -o results/dcqcn-format-test
    ./results/dcqcn-format-test | tee results/dcqcn-format.log
}

common_feedback=(ENABLE_ECN=1 ECN_THRESHOLD=0B RETRANS_TIMEOUT=1000us
    CNP_MERGE_INTERVAL=50us DCQCN_ALPHA_INTERVAL=5us
    DCQCN_DECREASE_INTERVAL=4us DCQCN_RECOVERY_INTERVAL=20us)

run_d01() {
    run_case d01-disabled 4 e04 "${common_feedback[@]}"
    run_case d01-10g 4 e04 ENABLE_PACING=1 PACING_RATE=10Gbps RETRANS_TIMEOUT=1000us
    run_case d01-20g 4 e04 ENABLE_PACING=1 PACING_RATE=20Gbps RETRANS_TIMEOUT=1000us
    python3 analysis/check_dcqcn.py d01
}

run_d02() {
    run_case d02-sustained 4 d08 "${common_feedback[@]}" ENABLE_DCQCN=1 DCQCN_D08_WR_NUM=50
    python3 analysis/check_dcqcn.py d02
}

run_d03() {
    algorithm_test
    python3 analysis/check_dcqcn.py d03
}

run_d04() {
    algorithm_test
    python3 analysis/check_dcqcn.py d04
}

run_d05() {
    run_case d05 4 s08 ENABLE_PACING=1 PACING_RATE=20Gbps \
        RNIC_TX_BUSY_RETRIES=20 RETRANS_TIMEOUT=1000us
    python3 analysis/check_dcqcn.py d05
}

run_d06() {
    run_case d06 4 e06 "${common_feedback[@]}" ENABLE_DCQCN=1
    python3 analysis/check_dcqcn.py d06
}

run_d07() {
    run_case d07 4 e05 "${common_feedback[@]}" ENABLE_DCQCN=1
    run_case d07-repeat 4 e05 "${common_feedback[@]}" ENABLE_DCQCN=1
    python3 analysis/check_dcqcn.py d07
}

run_d08() {
    local common=(ENABLE_ECN=1 SWITCH_FABRIC_SPEED=10Gbps SWITCH_BUFFER_SIZE=1MB
        ECN_THRESHOLD=512B RETRANS_TIMEOUT=1000us CNP_MERGE_INTERVAL=50us
        DCQCN_ALPHA_INTERVAL=5us DCQCN_DECREASE_INTERVAL=4us
        DCQCN_RECOVERY_INTERVAL=20us DCQCN_D08_WR_NUM=100 MAX_TICKS=50000000000000)
    run_case d08-baseline 4 d08 "${common[@]}"
    run_case d08-dcqcn 4 d08 "${common[@]}" ENABLE_DCQCN=1
    python3 analysis/check_dcqcn.py d08
}

run_d09() {
    run_case d09-loss 4 e09 "${common_feedback[@]}" ENABLE_DCQCN=1 \
        DROP_CLIENT_OPCODE=129 DROP_SERVER_OPCODE=10 DROP_COUNT=1 RETRANS_TIMEOUT=5us
    run_case d09-retrans 4 s05 "${common_feedback[@]}" ENABLE_DCQCN=1 \
        SWITCH_BUFFER_SIZE=512B RETRANS_TIMEOUT=5us MAX_TICKS=50000000000000
    run_case d09-lifecycle 4 e07 "${common_feedback[@]}" ENABLE_DCQCN=1 \
        CNP_MERGE_INTERVAL=1s DROP_SERVER_OPCODE=10 DROP_CLIENT_OPCODE=10 \
        DROP_COUNT=1 RETRANS_TIMEOUT=1000us DUPLICATE_SERVER_OPCODE=10 \
        DUPLICATE_CLIENT_OPCODE=10 DUPLICATE_COUNT=1
    python3 analysis/check_dcqcn.py d09
}

run_d10() {
    run_case d02-sustained 6 d08 "${common_feedback[@]}" ENABLE_DCQCN=1 DCQCN_D08_WR_NUM=50
    run_case d06 6 e06 "${common_feedback[@]}" ENABLE_DCQCN=1
    ./scripts/run_ecn.sh all
    python3 analysis/check_dcqcn.py d10
}

case "$CASE_NAME" in
    all)
        algorithm_test
        run_d01
        run_d02
        run_d03
        run_d04
        run_d05
        run_d06
        run_d07
        run_d08
        run_d09
        run_d10
        ;;
    d01|d02|d03|d04|d05|d06|d07|d08|d09|d10) "run_$CASE_NAME" ;;
    *) echo "Usage: $0 [all|d01|d02|d03|d04|d05|d06|d07|d08|d09|d10]" >&2; exit 2 ;;
esac
