#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

EXPECTED = {
    29: (4, 4, 0), 30: (4, 4, 0), 31: (8, 8, 0), 32: (8, 8, 0),
    33: (4, 4, 0), 34: (4, 4, 0), 35: (4, 4, 0), 36: (2, 0, 2),
    37: (4, 4, 0), 38: (1, 1, 0), 39: (1, 1, 0),
}

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()

for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    summary = re.search(r"RC_STATE_SUMMARY mode=(\d+) submitted=(\d+) success=(\d+) failure=(\d+) outstanding=(\d+)", log)
    assert summary, f"{result}: RC state summary missing"
    mode, submitted, success, failure, outstanding = map(int, summary.groups())
    assert (submitted, success, failure) == EXPECTED[mode] and outstanding == 0, f"{result}: bad completion counts"
    assert len(re.findall(r"RC_STATE_CQE mode=", log)) == submitted, f"{result}: missing or duplicate CQEs"
    guard = re.search(r"PROTECT_TARGET digest=0x[0-9a-f]+ guard=0x([0-9a-f]+)", log)
    assert guard and int(guard.group(1), 16) == 0x875BA9063DBF9103, f"{result}: guard changed"
    if mode in {29, 30}:
        request_opcode = 0x0A if mode == 29 else 0x0C
        packets = read_pcap(result / "rocev2.server.pcap")
        psns = [p["psn"] for p in packets if p["opcode"] == request_opcode]
        assert psns == [0xFFFFFE, 0xFFFFFF, 0, 1], f"{result}: bad wrap sequence {psns}"
    if mode in {31, 32}:
        request_opcode = 0x0A if mode == 31 else 0x0C
        packets = read_pcap(result / "rocev2.server.pcap")
        assert len({p["psn"] for p in packets if p["opcode"] == request_opcode}) == 8, f"{result}: not eight outstanding PSNs"
    if mode in {33, 34, 37, 38}:
        assert "RC_DROP out-of-sequence" in log and "RC_NAK_SEQUENCE" in log, f"{result}: sequence NAK missing"
        assert "RC_RETRANSMIT" in log, f"{result}: recovery retransmission missing"
    if mode == 37:
        assert len(re.findall(r"RC_FAULT drop opcode 0xa", log)) == 2, f"{result}: consecutive request loss missing"
    if mode == 38:
        assert re.search(r"RC_RETRANSMIT qpn 1 PSN 0x0 opcode 0x6", log), f"{result}: first segment not retransmitted"
        assert re.search(r"RC_RETRANSMIT qpn 1 PSN 0x1 opcode 0x8", log), f"{result}: last segment not retransmitted"
    if mode == 39:
        responses = read_pcap(result / "rocev2.client1.pcap")
        segments = [p for p in responses if p["opcode"] in {0x0D, 0x0E, 0x0F}]
        assert segments and len(segments) % 3 == 0, f"{result}: incomplete response sequence"
        for offset in range(0, len(segments), 3):
            group = segments[offset:offset + 3]
            assert [p["opcode"] for p in group] == [0x0D, 0x0E, 0x0F], \
                f"{result}: bad response sequence at packet {offset}"
            assert [p["psn"] for p in group] == [0, 1, 2], f"{result}: bad response PSNs"
            assert "syndrome" not in group[1], f"{result}: middle response contains AETH"
    if mode == 35:
        assert len(re.findall(r"RC_FAULT drop opcode 0x11", log)) == 3, f"{result}: consecutive ACK loss missing"
        responses = read_pcap(result / "rocev2.client1.pcap")
        assert any(p["opcode"] == 0x11 and p["psn"] == 3 for p in responses), f"{result}: cumulative ACK missing"
        assert "RC_RETRANSMIT" not in log, f"{result}: cumulative ACK should avoid retransmission"
    if mode == 36:
        statuses = [int(value) for value in re.findall(r"RC_STATE_CQE mode=36 status=(\d+)", log)]
        assert statuses == [12, 5], f"{result}: expected retry-exceeded then flush, got {statuses}"
        assert len(re.findall(r"RC_RETRY_EXCEEDED qpn 1", log)) == 1, f"{result}: retry exhaustion missing"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"]), f"{result}: simulator failure"
    print(f"PASS {result} mode={mode} submitted={submitted} success={success} failure={failure}")
