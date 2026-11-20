#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()

for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    config = (result / "gem5" / "config.ini").read_text()
    operation = re.search(r"^operation=(write|read)$", run, re.MULTILINE).group(1)
    expected = {
        "write": "RDMA Write data is Hello World!  Hello RDMA Write!",
        "read": "RDMA Read data is Hello World!  Hello RDMA Read !",
    }[operation]
    failures = ["segmentation fault", "Program aborted", "panic:"]
    assert "cpu=TimingSimpleCPU" in run, f"{result}: not TimingSimpleCPU"
    assert config.count("mem_mode=timing") == 2, f"{result}: both systems must use timing"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(item in log for item in failures), f"{result}: simulator failure"
    match = re.search(r"send cnt: (\d+)", log)
    fixed = re.search(r"FIXED_SUMMARY submitted=(\d+) success=(\d+) failure=(\d+) outstanding=(\d+)", log)
    assert fixed or expected in log, f"{result}: expected payload missing; fixed runs use check_fixed_rc.py for memory digests"
    if fixed:
        submitted, success, failure, outstanding = map(int, fixed.groups())
        assert submitted == success and success > 0 and failure == 0 and outstanding == 0, f"{result}: bad fixed completion counts"
        completed = success
    else:
        assert match and int(match.group(1)) > 0, f"{result}: no completed operations"
        completed = int(match.group(1))
    print(f"PASS {result} operation={operation} completed={completed}")
