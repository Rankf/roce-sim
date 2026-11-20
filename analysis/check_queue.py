#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-queue-resource")
log = (result / "simulation.log").read_text(errors="replace")
assert "QUEUE_TX_SUBMIT accepted=2 rejected=1 bad_index=2" in log, "SQ partial submission mismatch"
assert "QUEUE_RX_SUBMIT accepted=2 rejected=1 bad_index=2" in log, "RQ partial submission mismatch"
assert "QUEUE_TX_SUMMARY completed=1 outstanding=0" in log, "SQ completion/resource recycling mismatch"
assert "QUEUE_RX_SUMMARY completed=2 outstanding=0" in log, "RQ completion/resource recycling mismatch"
tx = re.findall(r"TX_CQE mode=50 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
rx = re.findall(r"RX_CQE mode=50 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
assert tx == [("0", "64", "5458000000000001")], f"selective TX completion mismatch: {tx}"
assert rx == [("0", "64", "5258000000000000"), ("0", "64", "5258000000000001")], \
    f"RX completion mismatch: {rx}"
requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x04]
responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
assert [p["psn"] for p in requests] == [0, 1], "unexpected SQ wire requests"
assert [p["psn"] for p in responses] == [0, 1], "unexpected ACKs"
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS SQ/RQ partial submission, selective completion and full resource recycling")
