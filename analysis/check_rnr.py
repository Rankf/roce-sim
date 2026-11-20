#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

from check_rocev2_pcap import read_pcap

GUARD = 0x875BA9063DBF9103
PAYLOAD = 0x1720BC0FC349392B
ZERO_4K = 0xB43A063055ADC383

parser = argparse.ArgumentParser()
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()
for result in args.results:
    log = (result / "simulation.log").read_text(errors="replace")
    run = (result / "run.yaml").read_text()
    mode = int(re.search(r"^protect_mode=(\d+)$", run, re.MULTILINE).group(1))
    requests = [p for p in read_pcap(result / "rocev2.server.pcap") if p["opcode"] == 0x04]
    responses = [p for p in read_pcap(result / "rocev2.client1.pcap") if p["opcode"] == 0x11]
    rnr_naks = [p for p in responses if p["syndrome"] == 0x20]
    successful_acks = [p for p in responses if p["syndrome"] == 0]
    assert all(p["credit"] == 0x1F for p in rnr_naks), f"{result}: bad RNR wait code"
    assert len(rnr_naks) == len(re.findall(r"RC_RNR_NAK qpn", log)) // 2, \
        f"{result}: wire/log RNR count mismatch"
    assert "Exiting @ tick" in log, f"{result}: no normal exit"
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:")), \
        f"{result}: simulator failure"
    guard = re.search(r"PROTECT_TARGET digest=0x([0-9a-f]+) guard=0x([0-9a-f]+)", log)
    assert guard and int(guard.group(2), 16) == GUARD, f"{result}: guard changed"

    if mode == 48:
        assert len(re.findall(r"TX_CQE mode=48 status=0 byte_cnt=64", log)) == 1, \
            f"{result}: missing or duplicate success TX CQE"
        assert len(re.findall(r"RX_CQE mode=48 status=0 byte_cnt=64", log)) == 1, \
            f"{result}: missing or duplicate success RX CQE"
        assert "rq_offset=24" in log, f"{result}: expected one Receive WQE"
        assert "RNR_RECV_POSTED" in log, f"{result}: delayed RECV was not posted"
        assert len(re.findall(r"RC_RNR_RETRY qpn", log)) >= 1, f"{result}: no RNR retry"
        assert len(requests) == len(rnr_naks) + 1 and len(rnr_naks) >= 1, \
            f"{result}: unexpected recovery request/NAK counts"
        assert len(successful_acks) == 1, f"{result}: expected one successful ACK"
        assert int(guard.group(1), 16) == PAYLOAD, f"{result}: payload not written after recovery"
        print(f"PASS {result} RNR wait, delayed RECV recovery, one TX/RX completion and one payload")
    elif mode == 49:
        assert re.search(r"^rnr_retry_limit=2$", run, re.MULTILINE), f"{result}: wrong retry limit"
        assert len(re.findall(r"TX_CQE mode=49 status=13 byte_cnt=0", log)) == 1, \
            f"{result}: missing RNR exhaustion CQE"
        assert "RX_CQE mode=49" not in log, f"{result}: unexpected receive completion"
        assert len(re.findall(r"RC_RNR_RETRY qpn", log)) == 2, f"{result}: expected two RNR retries"
        assert len(re.findall(r"RC_RNR_RETRY_EXCEEDED qpn", log)) == 1, \
            f"{result}: RNR exhaustion missing"
        assert len(requests) == len(rnr_naks) == 3, f"{result}: expected initial request plus two retries"
        assert not successful_acks, f"{result}: unexpected successful ACK"
        assert int(guard.group(1), 16) == ZERO_4K, f"{result}: target changed after RNR exhaustion"
        print(f"PASS {result} two RNR retries, WC status 13, no success ACK and no memory side effect")
    else:
        raise AssertionError(f"{result}: unsupported RNR mode {mode}")
