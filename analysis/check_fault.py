#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

CASES = {
    "22": (10, "write"),
    "23": (17, "write"),
    "25": (12, "read"),
    "26": (16, "read"),
}

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()

for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    cqe = re.search(r"PROTECT_CQE mode=(\d+) status=0 byte_cnt=64", log)
    assert cqe, f"{result}: successful fixed completion missing"
    mode = cqe.group(1)
    assert len(re.findall(r"PROTECT_CQE mode=", log)) == 1, f"{result}: duplicate CQE"
    if mode in CASES:
        opcode, operation = CASES[mode]
        assert re.search(rf"RC_FAULT drop opcode 0x{opcode:x}", log), f"{result}: drop not injected"
        request_opcode = 10 if operation == "write" else 12
        assert len(re.findall(rf"RC_RETRANSMIT qpn \d+ PSN 0x0 opcode 0x{request_opcode:x}", log)) == 1, f"{result}: request not retransmitted once"
    if mode in {"23", "24", "26", "27"}:
        assert "RC_DUPLICATE request" in log, f"{result}: duplicate request not detected"
    if mode in {"24", "27", "28"}:
        opcode = {"24": 10, "27": 12, "28": 16}[mode]
        assert re.search(rf"RC_FAULT duplicate opcode 0x{opcode:x}", log), f"{result}: duplicate not injected"
    if mode == "28":
        assert "RC_DUPLICATE response" in log, f"{result}: duplicate response not discarded"
    if mode in {"23", "24"}:
        assert len(re.findall(r"RDMA Write segment opcode 0xa", log)) == 1, f"{result}: target write side effect repeated"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"]), f"{result}: simulator failure"
    print(f"PASS {result} mode={mode} one completion and correct duplicate/loss handling")
