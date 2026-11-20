#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from check_rocev2_pcap import WRITE_PAYLOAD, read_pcap

GUARD = 0x875BA9063DBF9103
PAYLOAD_DIGEST = 0x1720BC0FC349392B
TX_RE = re.compile(
    r"TX_CQE mode=46 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)")
RX_RE = re.compile(
    r"RX_CQE mode=46 status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+) "
    r"imm=0x([0-9a-f]+) flags=0x([0-9a-f]+) rq_offset=(\d+) notify_probe=0x([0-9a-f]+)")


def check_common(result, log):
    for endpoint in ("LOCAL", "TARGET"):
        evidence = re.search(
            rf"PROTECT_{endpoint} digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
        assert evidence, f"{result}: {endpoint} memory evidence missing"
        assert int(evidence.group(1), 16) == PAYLOAD_DIGEST, f"{result}: bad {endpoint} payload"
        assert int(evidence.group(2), 16) == GUARD, f"{result}: {endpoint} guard changed"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:")), \
        f"{result}: simulator failure"


def check_send_batch(result, log):
    tx = TX_RE.findall(log)
    rx = RX_RE.findall(log)
    assert len(tx) == len(rx) == 4, f"{result}: expected four unique TX/RX completions"
    for index, completion in enumerate(tx):
        status, byte_cnt, wr_id = completion
        assert (int(status), int(byte_cnt), int(wr_id, 16)) == (
            0, 64, 0x5458000000000000 | index), f"{result}: bad TX completion {index}"
    for index, completion in enumerate(rx):
        status, byte_cnt, wr_id, imm, flags, rq_offset, notify = completion
        assert (int(status), int(byte_cnt), int(wr_id, 16)) == (
            0, 64, 0x5258000000000000 | index), f"{result}: bad RX completion {index}"
        assert (int(imm, 16), int(flags, 16), int(rq_offset), int(notify, 16)) == (0, 0, 96, 0), \
            f"{result}: bad RX metadata {index}"
    assert "SEND_BATCH_SUMMARY submitted=4 completed=4" in log, f"{result}: bad batch summary"
    requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x04]
    responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
    assert [p["psn"] for p in requests] == list(range(4)), f"{result}: bad SEND PSNs"
    assert [p["psn"] for p in responses] == list(range(4)), f"{result}: bad ACK PSNs"
    assert all(p["payload"] == WRITE_PAYLOAD for p in requests), f"{result}: bad SEND payload"
    print(f"PASS {result} four outstanding SENDs, unique TX/RX wr_id, four RQ WQEs and ACKs")


def check_reset(result, log):
    flushed = re.findall(r"QP_RESET_FLUSH status=(\d+)", log)
    success = re.findall(r"QP_RESET_SUCCESS status=(\d+)", log)
    assert flushed == ["5"] and success == ["0"], f"{result}: expected one flush and one success"
    assert "QP_RESET_SUMMARY flushed=1 success=1" in log, f"{result}: bad reset summary"
    assert len(re.findall(r"RC_FAULT drop opcode 0xa", log)) == 1, f"{result}: request loss missing"
    states = [int(s) for s in re.findall(r"svrsys\.platform\.rdma_nic.*QP_STATE qpn 1 state (\d+)", log)]
    assert states[-5:] == [6, 0, 1, 2, 3], f"{result}: bad ERR/RESET/recovery states {states}"
    assert log.index("QP_RESET_FLUSH") < log.index("QP_RESET_SUCCESS"), f"{result}: bad completion order"
    requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x0A]
    responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
    assert len(requests) == len(responses) == 1, f"{result}: duplicate post-reset wire request/response"
    assert requests[0]["payload"] == WRITE_PAYLOAD, f"{result}: bad post-reset payload"
    print(f"PASS {result} in-flight WR flush, ERR→RESET→RTS recovery and one post-reset Write/ACK")


parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()
for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    mode = int(re.search(r"^protect_mode=(\d+)$", run, re.MULTILINE).group(1))
    check_common(result, log)
    if mode == 46:
        check_send_batch(result, log)
    elif mode == 47:
        check_reset(result, log)
    else:
        raise AssertionError(f"{result}: unsupported QP completion mode {mode}")
