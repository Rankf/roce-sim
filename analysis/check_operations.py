#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from check_rocev2_pcap import WRITE_PAYLOAD, read_pcap

EXPECTED_OPS = {41: [0x04], 42: [0x00, 0x02], 43: [0x05], 44: [0x0B], 45: [0x00, 0x02, 0x00]}
NORMAL_DIGEST = 0x1720BC0FC349392B
MULTI_DIGEST = 0x5494DA080543F92B

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()
for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    mode = int(re.search(r"protect_mode=(\d+)", run).group(1))
    length = 8192 if mode in {42, 45} else 64
    tx = re.search(r"TX_CQE mode=(\d+) status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+)", log)
    rx = re.search(r"RX_CQE mode=(\d+) status=(\d+) byte_cnt=(\d+) wr_id=0x([0-9a-f]+) imm=0x([0-9a-f]+) flags=0x([0-9a-f]+) rq_offset=(\d+) notify_probe=0x([0-9a-f]+)", log)
    assert tx and rx, f"{result}: TX/RX CQE missing"
    assert int(mode) == int(tx.group(1)) == int(rx.group(1))
    assert tx.group(2) == rx.group(2) == "0", f"{result}: completion failed"
    assert int(tx.group(3)) == int(rx.group(3)) == length, f"{result}: bad byte count"
    assert int(tx.group(4), 16) == 0x5458000000000000 | mode, f"{result}: TX wr_id mismatch"
    assert int(rx.group(4), 16) == 0x5258000000000000 | mode, f"{result}: RX wr_id mismatch"
    expected_imm = 0x11223344 if mode in {43, 44} else 0
    expected_flags = 1 if mode in {43, 44} else 0
    assert int(rx.group(5), 16) == expected_imm and int(rx.group(6), 16) == expected_flags, f"{result}: immediate metadata mismatch"
    assert int(rx.group(7)) == 24, f"{result}: message must consume exactly one Receive WQE"
    if mode == 44:
        assert int(rx.group(8), 16) == 0, f"{result}: notification SGE was used as payload destination"
        completed = re.search(r"DMA write completed: key 0x4, vaddr 0x[0-9a-f]+, length 64", log)
        ack = re.search(r"sauProcessing, type: 17|PACER_TX qpn 1 opcode 0x11", log[completed.end():] if completed else "")
        assert completed and ack, f"{result}: WriteImm ACK precedes remote DMA completion"
    digest = re.search(r"PROTECT_TARGET digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
    assert digest and int(digest.group(1), 16) == (MULTI_DIGEST if mode in {42, 45} else NORMAL_DIGEST), f"{result}: payload digest mismatch"
    assert int(digest.group(2), 16) == 0x875BA9063DBF9103, f"{result}: guard changed"
    assert len(re.findall(r"RX_CQE mode=", log)) == 1 and len(re.findall(r"TX_CQE mode=", log)) == 1, f"{result}: duplicate completion"
    payload_dmas = list(re.finditer(
        r"cltsys\.platform\.rdma_nic.*DMA write completed: key 0x4, "
        r"vaddr 0x[0-9a-f]+, length (\d+)", log))
    expected_dma_lengths = [4096, 4096] if mode in {42, 45} else [64]
    assert [int(match.group(1)) for match in payload_dmas] == expected_dma_lengths, \
        f"{result}: payload DMA completions missing or duplicated"
    rx_position = log.index("RX_CQE mode=")
    assert all(match.end() < rx_position for match in payload_dmas), \
        f"{result}: RX CQE precedes a payload DMA completion"
    packets = read_pcap(result / "rocev2.server.pcap")
    operations = [p for p in packets if p["opcode"] in {0x00, 0x02, 0x04, 0x05, 0x0B}]
    assert [p["opcode"] for p in operations] == EXPECTED_OPS[mode], f"{result}: wrong wire operations"
    for index, packet in enumerate(operations):
        if mode in {42, 45}:
            expected = WRITE_PAYLOAD + bytes(4096 - len(WRITE_PAYLOAD)) if packet["opcode"] == 0x00 else bytes(4096)
        else:
            expected = WRITE_PAYLOAD
        assert packet["payload"] == expected, f"{result}: payload differs from reference"
        if mode in {43, 44}:
            assert packet["immediate"] == 0x11223344, f"{result}: wire immediate mismatch"
    if mode == 45:
        assert "RC_DUPLICATE request" in log, f"{result}: duplicate first segment not detected"
        assert "RC_DUPLICATE response" in log, f"{result}: duplicate ACK not discarded"
    assert "Exiting @ tick" in log
    assert not any(x in log for x in ["segmentation fault", "Program aborted", "panic:"])
    print(f"PASS {result} mode={mode} one RQ WQE, TX/RX wr_id, payload and Timing completion")
