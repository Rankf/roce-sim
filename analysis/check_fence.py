#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import READ_PAYLOAD, read_pcap

result = Path("results/qp-fence")
log = (result / "simulation.log").read_text(errors="replace")
tx = re.findall(r"TX_CQE mode=56 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
assert tx == [("0", "64", "5458000000000000"),
              ("0", "64", "5458000000000001")], f"Fence completion mismatch: {tx}"
assert "FENCE_WAIT" in log, "fenced WR was not held behind the outstanding Read"
release = re.search(r"READ_CREDIT_RELEASE qpn \d+ outstanding 0", log)
assert release, "Read credit/local completion was not released"
write_generation = re.search(r"RoCEv2 opcode 0xa,", log)
assert write_generation and release.end() < write_generation.start(), \
    "fenced Write was generated before Read completion"
target = bytearray(4096)
target[:64] = READ_PAYLOAD
target[128:192] = READ_PAYLOAD
expected_digests = {"LOCAL": 0x9599CA298EA25C83}
hash_value = 1469598103934665603
for byte in target:
    hash_value = (hash_value ^ byte) * 1099511628211 & 0xffffffffffffffff
expected_digests["TARGET"] = hash_value
for endpoint in ("LOCAL", "TARGET"):
    evidence = re.search(
        rf"PROTECT_{endpoint} digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
    assert evidence, f"{endpoint} memory evidence missing"
    assert int(evidence.group(1), 16) == expected_digests[endpoint], \
        f"{endpoint} did not contain the expected Read/Write payloads"
    assert int(evidence.group(2), 16) == 0x875BA9063DBF9103, \
        f"{endpoint} guard changed"
requests = [p for p in read_pcap(result / "rocev2.server.pcap")
            if p["opcode"] in {0x0A, 0x0C}]
assert requests[-1]["opcode"] == 0x0A and requests[-1]["payload"] == READ_PAYLOAD, \
    "fenced Write did not carry the data returned by Read"
assert any(p["opcode"] == 0x0C for p in requests), "Read request missing"
responses = [p for p in read_pcap(result / "rocev2.client1.pcap")
             if p["opcode"] == 0x10]
assert responses and all(p["payload"] == READ_PAYLOAD for p in responses), \
    "Read response payload mismatch"
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS fenced Write waits for Read DMA completion and carries returned data")
