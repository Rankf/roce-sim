#!/usr/bin/env python3
import re
from collections import Counter, defaultdict
from pathlib import Path

from check_rocev2_pcap import read_pcap

result = Path("results/qp-ring-stress")
log = (result / "simulation.log").read_text(errors="replace")
assert "RING_PARTIAL accepted=4 rejected=1 bad_index=4" in log, \
    "initial partial submission did not stop at the fifth WR"
summary = re.search(
    r"RING_SUMMARY submitted=(\d+) completions=(\d+) outstanding=(\d+)", log)
assert summary and summary.groups() == ("320", "81", "0"), \
    f"ring completion/resource summary mismatch: {summary.groups() if summary else None}"
wraps = re.findall(r"RING_WRAP qpn=(\d+) posts=(\d+)", log)
assert len(wraps) == 4 and Counter(qpn for qpn, _ in wraps) == {"1": 2, "2": 2}, \
    f"SQ wrap coverage mismatch: {wraps}"
cqe = re.findall(
    r"RING_CQE qpn=(\d+) status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
assert len(cqe) == 81 and Counter(qpn for qpn, *_ in cqe) == {"1": 41, "2": 40}
assert all(status == "0" and byte_cnt == "64" for _, status, byte_cnt, _ in cqe)
assert len(re.findall(r"rejects .* retries remain", log)) >= 8, \
    "DMA backpressure injection was not exercised"

def payload(offset):
    return bytes((offset + i) * 37 + 11 & 0xff for i in range(64))

packets = [p for p in read_pcap(result / "rocev2.server.pcap")
           if p["opcode"] == 0x0A]
assert len(packets) == 320, f"unexpected Write count: {len(packets)}"
by_qp = defaultdict(list)
base = packets[0]["reth"][0]
for packet in packets:
    addr, _, length = packet["reth"]
    offset = addr - base
    assert 0 <= offset < 8192 and offset % 64 == 0 and length == 64
    assert packet["payload"] == payload(offset), \
        f"payload mismatch at qpn={packet['qpn']} psn={packet['psn']} offset={offset}"
    by_qp[packet["qpn"]].append(packet["psn"])
assert set(by_qp) == {1, 2}
expected_counts = {1: 162, 2: 158}
for qpn, psns in by_qp.items():
    assert psns == list(range(expected_counts[qpn])), f"QP {qpn} PSN/order mismatch"
expected = b"".join(payload(offset) for offset in range(0, 8192, 64))
hash_value = 1469598103934665603
for byte in expected:
    hash_value = (hash_value ^ byte) * 1099511628211 & 0xffffffffffffffff
for endpoint in ("LOCAL", "TARGET"):
    evidence = re.search(
        rf"PROTECT_{endpoint} digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
    assert evidence and int(evidence.group(1), 16) == hash_value, \
        f"{endpoint} final memory mismatch"
    assert int(evidence.group(2), 16) == 0x875BA9063DBF9103, \
        f"{endpoint} guard changed"
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS two-QP ring wrap, partial post, selective completion, DMA retry and all payloads")
