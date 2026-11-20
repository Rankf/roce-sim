#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-read-credit")
log = (result / "simulation.log").read_text(errors="replace")
request_values = [int(x) for x in re.findall(r"READ_CREDIT_ACQUIRE qpn \d+ outstanding (\d+)", log)]
dest_values = [int(x) for x in re.findall(r"DEST_READ_CREDIT_ACQUIRE qpn \d+ outstanding (\d+)", log)]
assert request_values and max(request_values) <= 2, request_values
assert dest_values and max(dest_values) <= 1, dest_values
assert "READ_CREDIT_WAIT" in log, "requester did not block above its credit limit"
assert "DEST_READ_CREDIT_WAIT" in log, "responder did not block above its credit limit"
assert len(re.findall(r"READ_CREDIT_RELEASE qpn \d+ outstanding 0", log)) >= 1
assert len(re.findall(r"DEST_READ_CREDIT_RELEASE qpn \d+ outstanding 0", log)) >= 1
expected = [(0, 12288, 0x5458000000000000), (0, 64, 0x5458000000000001),
            (0, 64, 0x5458000000000002), (0, 64, 0x5458000000000003)]
tx = re.findall(r"TX_CQE mode=53 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
assert len(tx) == 4
for index, (status, byte_cnt, wr_id) in enumerate(tx):
    assert (int(status), int(byte_cnt), int(wr_id, 16)) == expected[index], tx
assert "READ_CREDIT_SUMMARY completed=4 outstanding=0" in log
requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x0C]
responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
assert len(requests) >= 4, "read requests missing"
assert any(p["syndrome"] == 0x20 for p in responses), "responder RNR NAK missing"
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS requester/responder Read credit limits, RNR recovery and resource release")
