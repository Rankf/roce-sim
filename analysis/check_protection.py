#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

ZERO_4K = 0xb43a063055adc383
READ_4K = 0x9599ca298ea25c83
LEGAL_WRITE = {"11": 0xee4ac94af5f2e12b, "12": 0xe45368c93b1e652b,
               "14": 0x1720bc0fc349392b, "15": 0x1720bc0fc349392b,
               "16": ZERO_4K, "19": 0x052089f28aac912b,
               "20": 0x5494da080543f92b, "21": 0xdcaa036b56f31c83,
               "22": 0x1720bc0fc349392b, "23": 0x1720bc0fc349392b,
               "24": 0x1720bc0fc349392b, "25": READ_4K,
               "26": READ_4K, "27": READ_4K, "28": READ_4K}

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()

for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    operation = re.search(r"^operation=(write|read)$", run, re.MULTILINE).group(1)
    cqe = re.search(r"PROTECT_CQE mode=(\d+) status=(\d+) byte_cnt=(\d+)", log)
    target = re.search(r"PROTECT_TARGET digest=0x([0-9a-f]+)", log)
    assert cqe and target, f"{result}: completion or target evidence missing"
    mode = cqe.group(1)
    legal = mode in LEGAL_WRITE
    expected_status = "0" if legal else ("4" if mode in {"8", "9", "10"} else "10")
    expected_bytes = "8192" if mode in {"20", "21"} else ("64" if legal else "0")
    assert cqe.group(2) == expected_status and cqe.group(3) == expected_bytes, f"{result}: bad CQE"
    expected = LEGAL_WRITE[mode] if legal else (ZERO_4K if operation == "write" else READ_4K)
    assert int(target.group(1), 16) == expected, f"{result}: unexpected target memory"
    if mode in {"15", "16", "17", "18"}:
        target2 = re.search(r"PROTECT_TARGET2 digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
        assert target2, f"{result}: second MR evidence missing"
        expected2 = 0x1720bc0fc349392b if mode == "16" else ZERO_4K
        assert int(target2.group(1), 16) == expected2, f"{result}: unexpected second MR"
        assert int(target2.group(2), 16) == 0x875ba9063dbf9103, f"{result}: second guard changed"
    if mode == "10":
        local = re.search(r"PROTECT_LOCAL digest=0x([0-9a-f]+)", log)
        assert local and int(local.group(1), 16) == ZERO_4K, f"{result}: local destination changed"
    assert legal or "PROTECT deny" in log, f"{result}: no protection denial"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"]), f"{result}: simulator failure"
    print(f"PASS {result} mode={mode} status={expected_status} target_digest=0x{expected:x}")
