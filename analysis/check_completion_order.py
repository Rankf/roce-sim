#!/usr/bin/env python3
import re
from pathlib import Path

cases = [
    (Path("results/write-completion-order/simulation.log"), "write"),
    (Path("results/read-completion-order/simulation.log"), "read"),
]
for path, operation in cases:
    log = path.read_text(errors="replace")
    completed = re.search(r"DMA write completed: key 0x4, vaddr 0x[0-9a-f]+, length 64", log)
    assert completed, f"{path}: payload write completion missing"
    following = log[completed.end():]
    if operation == "write":
        dependent = re.search(r"sauProcessing, type: 17|PACER_TX qpn 1 opcode 0x11", following)
        assert dependent, f"{path}: ACK did not follow payload write"
    else:
        dependent = re.search(r"RGRRU.postTxCpl! qpn 1", following)
        assert dependent, f"{path}: CQE did not follow local payload write"
    assert "FIXED_SUMMARY submitted=1 success=1 failure=0 outstanding=0" in log
    print(f"PASS {path}: payload write precedes {operation} completion")
