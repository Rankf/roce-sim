#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-atomic-basic")
log = (result / "simulation.log").read_text(errors="replace")
expected = [
    (0x13, 20, 10, 10),
    (0x13, 30, 10, 20),
    (0x14, 5, 0, 20),
    (0x13, 0xFFFFFFFFFFFFFFFF, 25, 25),
    (0x14, 1, 0, 0xFFFFFFFFFFFFFFFF),
]
cqe = re.findall(
    r"ATOMIC_CQE type=(\d+) status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+) old=0x([0-9a-f]+)", log)
assert len(cqe) == 5 and "ATOMIC_BASIC_SUMMARY completed=5" in log
for index, (_, status, byte_cnt, wr_id, old) in enumerate(cqe):
    opcode, swap, compare, expected_old = expected[index]
    assert status == "0" and byte_cnt == "8" and int(wr_id, 16) == 0x4154000000000000 | index
    assert int(old, 16) == expected_old, f"wrong returned old value at {index}"
assert len(re.findall(r"ATOMIC_EXECUTED", log)) == 5
assert len(re.findall(r"Received response SwapResp", log)) == 5, \
    "operations did not complete as gem5 SwapReq/SwapResp transactions"
assert len(re.findall(r"rejects .* retries remain", log)) >= 4, \
    "atomic DMA backpressure was not exercised"
assert "ATOMIC_TARGET index=0 value=0x0" in log, "64-bit wrap/target value mismatch"
requests = [p for p in read_pcap(result / "rocev2.server.pcap")
            if p["opcode"] in {0x13, 0x14}]
responses = [p for p in read_pcap(result / "rocev2.client1.pcap")
             if p["opcode"] == 0x12]
assert len(requests) == len(responses) == 5
for index, (request, response) in enumerate(zip(requests, responses)):
    opcode, swap, compare, old = expected[index]
    assert request["opcode"] == opcode and not request["payload"]
    assert request["atomic"][2] == swap and request["atomic"][3] == compare
    assert request["atomic"][0] & 7 == 0
    assert response["original"] == old and not response["payload"]
    assert response["psn"] == request["psn"] == index
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS CAS hit/miss, FAA, 64-bit wrap, SwapReq responses and DMA backpressure")
