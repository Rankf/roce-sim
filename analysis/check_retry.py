#!/usr/bin/env python3
import re
from pathlib import Path

path = Path("results/retry-cross-line-fixed/simulation.log")
log = path.read_text(errors="replace")
assert len(re.findall(r" rejects (?:ReadReq|WriteReq)", log)) == 8
assert "-- Failed, waiting for retry" in log
assert "Received response" in log
responses = re.findall(r"Received response \S+ for addr: 0x[0-9a-f]+ size: (\d+) nb: (\d+), tot: (\d+)", log)
assert any(tot == "96" and nb == "0" for size, nb, tot in responses)
assert any(tot == "96" and nb == "64" for size, nb, tot in responses)
assert len(re.findall(r"PROTECT_CQE mode=12 status=0 byte_cnt=64", log)) == 1
assert "PROTECT_TARGET digest=0xe45368c93b1e652b guard=0x875ba9063dbf9103" in log
assert "Exiting @ tick" in log
assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"])
print("PASS retry notifications, 64+32 byte subtransaction responses, one completion")
