#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

GUARD = 0x875ba9063dbf9103
PAYLOAD = {"write": 0x1720bc0fc349392b, "read": 0x9599ca298ea25c83}

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()

for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    operation = re.search(r"^operation=(write|read)$", run, re.MULTILINE).group(1)
    expected_requests = int(re.search(r"^fixed_wr_num=(\d+)$", run, re.MULTILINE).group(1))
    summary = re.search(r"FIXED_SUMMARY submitted=(\d+) success=(\d+) failure=(\d+) outstanding=(\d+)", log)
    assert summary, f"{result}: summary missing"
    assert tuple(map(int, summary.groups())) == (expected_requests, expected_requests, 0, 0), f"{result}: bad counts"
    for endpoint in ["TARGET", "LOCAL"]:
        match = re.search(rf"FIXED_{endpoint} digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
        assert match, f"{result}: {endpoint} memory evidence missing"
        assert int(match.group(1), 16) == PAYLOAD[operation], f"{result}: unexpected {endpoint} payload"
        assert int(match.group(2), 16) == GUARD, f"{result}: {endpoint} guard changed"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"]), f"{result}: simulator failure"
    print(f"PASS {result} requests={expected_requests} success={expected_requests} guards=unchanged")
