#!/usr/bin/env python3
import re
from pathlib import Path

from check_rocev2_pcap import READ_PAYLOAD, WRITE_PAYLOAD, read_pcap

WRITE_DIGEST = 0x5494DA080543F92B
READ_DIGEST = 0xDCAA036B56F31C83
GUARD = 0x875BA9063DBF9103


def check_payloads(result, send_mode):
    requests = read_pcap(result / "rocev2.server.pcap")
    responses = read_pcap(result / "rocev2.client1.pcap")
    for packet in requests + responses:
        if packet["opcode"] in {0x00, 0x06, 0x0A, 0x0D, 0x10}:
            initial = WRITE_PAYLOAD if send_mode else READ_PAYLOAD
            expected = initial + bytes(len(packet["payload"]) - len(initial))
            assert len(packet["payload"]) >= len(initial) and packet["payload"] == expected, \
                f"{result}: first SGE payload mismatch"
        elif packet["opcode"] in {0x01, 0x02, 0x07, 0x08, 0x0E, 0x0F}:
            assert not any(packet["payload"]), f"{result}: unexpected nonzero later-segment data"


def check_digest(log, endpoint, result, expected_digest):
    evidence = re.search(
        rf"PROTECT_{endpoint} digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
    assert evidence, f"{result}: {endpoint} digest missing"
    assert int(evidence.group(1), 16) == expected_digest, f"{result}: bad {endpoint} digest"
    assert int(evidence.group(2), 16) == GUARD, f"{result}: {endpoint} guard changed"


send_result = Path("results/qp-sge-send")
log = (send_result / "simulation.log").read_text(errors="replace")
assert len(re.findall(r"TX_CQE mode=54 status=0 byte_cnt=8192", log)) == 1
assert len(re.findall(r"RX_CQE mode=54 status=0 byte_cnt=8192", log)) == 1
assert "rq_offset=24" in log, "multi-SGE message did not consume one Receive WQE"
check_digest(log, "TARGET", send_result, WRITE_DIGEST)
check_payloads(send_result, True)
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS three-source/two-destination SGE SEND with one RQ completion")

read_result = Path("results/qp-sge-read")
log = (read_result / "simulation.log").read_text(errors="replace")
assert len(re.findall(r"TX_CQE mode=55 status=0 byte_cnt=8192", log)) == 2
check_digest(log, "LOCAL", read_result, READ_DIGEST)
check_digest(log, "TARGET", read_result, READ_DIGEST)
check_payloads(read_result, False)
assert "Exiting @ tick" in log
assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:"))
print("PASS two-destination Read scatter and three-source Write gather")
