#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-sqd-read")
log = (result / "simulation.log").read_text(errors="replace")

def ordered(*markers):
    position = 0
    for marker in markers:
        position = log.find(marker, position)
        assert position >= 0, f"missing or out-of-order marker: {marker}"
        position += len(marker)
    return position

ordered("RoCEv2 opcode 0xc", "QP_STATE qpn 1 state 4")
sqd = log.index("QP_STATE qpn 1 state 4")
hold = log.index("SQD_HOLD")
drained = log.index("SQD_DRAINED")
reported = log.index("SQD_DRAIN_REPORTED drained=1")
resume = log.find("QP_STATE qpn 1 state 3", reported)
assert hold >= sqd and drained >= sqd, "SQD hold/drain markers missing"
assert drained <= reported <= resume, "drain was reported before actual completion or after RTS"
send = log.find("RoCEv2 opcode 0x4", resume)
assert send >= 0, "paused SEND did not resume"
assert log.index("RC_RETRANSMIT") < sqd, "SQD was not exercised during retransmission"
tx = re.findall(r"TX_CQE mode=52 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
assert tx == [("0", "12288", "5458000000000000"), ("0", "64", "5458000000000001")], tx
assert "SQD_SUMMARY completed=2 outstanding=0" in log
assert len(re.findall(r"RX_CQE mode=52 status=0 byte_cnt=64", log)) == 1
requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] in {0x04, 0x0C}]
assert [p["opcode"] for p in requests].count(0x0C) >= 2, "read retransmission missing"
assert [p["opcode"] for p in requests].count(0x04) == 1, "paused SEND missing or duplicated"
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS SQD during retransmission, true drain notification, paused WR resume")
