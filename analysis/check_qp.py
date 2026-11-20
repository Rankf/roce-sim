#!/usr/bin/env python3
import re
from pathlib import Path

path = Path("results/qp-lifecycle/simulation.log")
log = path.read_text(errors="replace")
summary = re.search(r"QP_LIFECYCLE_SUMMARY passed=(\d+) failed=(\d+) state=(\d+)", log)
assert summary and summary.groups() == ("12", "0", "3"), "QP lifecycle summary mismatch"
assert len(re.findall(r"QP_CHECK case=", log)) == 12, "QP lifecycle cases missing"
assert re.search(r"QP_STATE qpn 1 state 6", log), "device did not enter ERR"
assert re.search(r"QP_STATE qpn 1 state 0", log), "device did not reset"
assert re.search(r"QP_STATE qpn 1 state 4", log), "device did not enter SQD"
assert "Exiting @ tick" in log
assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"])
print("PASS QP transitions, attribute rejection, ERR/RESET and SQD resume")
