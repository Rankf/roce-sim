#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-cq-overrun")
log = (result / "simulation.log").read_text(errors="replace")
run = (result / "run.yaml").read_text()
assert re.search(r"^cq_capacity=2$", run, re.MULTILINE), "CQ capacity mismatch"
assert len(re.findall(r"IBV_EVENT_CQ_ERR cqn 1: CQ overrun, CQ disabled", log)) == 2, \
    "expected independent requester and receiver CQ errors"
assert "CQ_OVERRUN_TEST submitted=4" in log
assert "CQ_OVERRUN_CLIENT posted=4" in log
requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x04]
responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
assert [p["psn"] for p in requests] == [0, 1, 2, 3], "missing wire SEND"
assert [p["psn"] for p in responses] == [0, 1, 2, 3], "missing successful ACK"
evidence = re.search(r"PROTECT_TARGET digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
assert evidence and int(evidence.group(1), 16) == 0x1720BC0FC349392B
assert int(evidence.group(2), 16) == 0x875BA9063DBF9103
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS requester/receiver CQ overrun events, disabled CQ and correct wire data")
