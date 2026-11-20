#!/usr/bin/env python3
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from check_rocev2_pcap import read_pcap

RESULTS = Path("results")


def statistics(log):
    ports = {}
    for line in log.splitlines():
        if not line.startswith("SWITCH_PORT_STAT "):
            continue
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        ports[fields["port"]] = {
            key: int(value) for key, value in fields.items() if key != "port"
        }
    assert len(ports) == 4
    for port, stat in ports.items():
        assert stat["enq_packets"] == stat["sent_packets"] + stat["drop_packets"] + stat["queued_packets"], port
        assert stat["enq_bytes"] == stat["sent_bytes"] + stat["drop_bytes"] + stat["queued_bytes"], port
        assert stat["queued_packets"] == 0 and stat["queued_bytes"] == 0, port
    return ports


def events(log, name):
    pattern = re.compile(
        r"(?P<tick>\d+): (?P<node>\w+)\.platform\.rdma_nic\.RdmaEngine:.*?"
        + re.escape(name) + r"(?: qpn (?P<qpn>\d+))?(?: dest_qpn (?P<dest>\d+))?"
    )
    return [match.groupdict() for match in pattern.finditer(log)]


def load(tag, version, subdir):
    result = RESULTS / f"ecn-{tag}-ipv{version}" / subdir
    log = (result / "simulation.log").read_text(errors="replace")
    assert "Exiting @ tick" in log and "simulate() limit reached" not in log, result
    assert not any(x in log for x in ("segmentation fault", "Program aborted", "panic:")), result
    ports = statistics(log)
    captures = {}
    for name in ("server", "client1", "client2", "client3"):
        packets = read_pcap(result / f"rocev2.{name}.pcap")
        assert all(packet["ip_version"] == version for packet in packets)
        captures[name] = packets
    data = {
        "result": result,
        "log": log,
        "ports": ports,
        "captures": captures,
        "ce": events(log, "CE_RX"),
        "tx": events(log, "CNP_TX"),
        "rx": events(log, "CNP_RX"),
        "merge": events(log, "CNP_MERGE"),
        "reset": events(log, "CNP_RESET"),
    }
    return data


def nodes(items):
    return Counter(item["node"] for item in items)


def qpns(items, node):
    return {int(item["qpn"]) for item in items if item["node"] == node}


def summary(case, version, data):
    marked = sum(stat["ecn_marked"] for stat in data["ports"].values())
    already = sum(stat["ecn_already"] for stat in data["ports"].values())
    dropped = len(re.findall(r"RC_FAULT drop opcode 0x81", data["log"]))
    print(
        f"PASS {case} IPv{version} marked={marked} already_ce={already} "
        f"ce_rx={len(data['ce'])} cnp_tx={len(data['tx'])} cnp_rx={len(data['rx'])} "
        f"merged={len(data['merge'])} cnp_dropped={dropped}"
    )


def check_e01():
    for version in (4, 6):
        for tag in ("e01-disabled", "e01-low"):
            data = load(tag, version, "control")
            assert not data["ce"] and not data["tx"] and not data["rx"]
            assert "action=2" not in data["log"]
            assert len(re.findall(
                r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0",
                data["log"],
            )) == 3
            summary("E01", version, data)


def check_e02():
    log = (RESULTS / "ecn-e02-format.log").read_text()
    assert "PASS ECN codepoints, threshold, CNP format, DSCP/Flow Label preservation and ICRC invariance" in log
    print("PASS E02 ECT(0)/ECT(1)/Not-ECT/CE, threshold equality, DSCP and Flow Label preservation")


def check_e03():
    check_e02()
    for version in (4, 6):
        data = load("e04", version, "feedback")
        for packets in data["captures"].values():
            for packet in packets:
                if packet["opcode"] == 0x81:
                    assert packet["psn"] == 0 and not packet["ack_request"]
                    assert not packet["payload"]
        print(f"PASS E03 IPv{version} IPv4-checksum/UDP/ICRC, CNP format and corruption rejection")


def check_e04():
    for version in (4, 6):
        data = load("e04", version, "feedback")
        assert data["ce"] and data["tx"] and data["rx"]
        assert qpns(data["ce"], "cltsys2") == {1}
        assert qpns(data["tx"], "cltsys2") == {1}
        assert not qpns(data["rx"], "cltsys2")
        assert set(nodes(data["rx"])).issubset({"svrsys", "cltsys0", "cltsys1"})
        assert sum(stat["ecn_marked"] for stat in data["ports"].values()) > 0
        cnp = [p for packets in data["captures"].values() for p in packets if p["opcode"] == 0x81]
        assert cnp and all(p["psn"] == 0 and not p["payload"] for p in cnp)
        assert len(re.findall(
            r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0",
            data["log"],
        )) == 3
        summary("E04", version, data)


def check_e05():
    for version in (4, 6):
        data = load("e05", version, "multi-qp")
        assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 2
        for receiver in ("cltsys0", "cltsys2"):
            assert qpns(data["ce"], receiver) == {1, 2}, (receiver, nodes(data["ce"]))
        for source in ("svrsys", "cltsys1"):
            assert qpns(data["rx"], source) == {1, 2}, (source, nodes(data["rx"]))
        assert data["merge"]
        summary("E05", version, data)


def check_e06():
    for version in (4, 6):
        data = load("e06", version, "read-response")
        assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", data["log"])) == 2
        for requester in ("svrsys", "cltsys1"):
            assert data["ce"] and qpns(data["ce"], requester) == {1}
            assert qpns(data["tx"], requester) == {1}
            assert not qpns(data["rx"], requester)
        for responder in ("cltsys0", "cltsys2"):
            assert qpns(data["rx"], responder) == {1}
        for requester_capture in ("server", "client2"):
            assert any(p["opcode"] == 0x81 for p in data["captures"][requester_capture])
        for responder_capture in ("client1", "client3"):
            assert not any(p["opcode"] == 0x81 for p in data["captures"][responder_capture])
        summary("E06", version, data)


def check_e07():
    for version in (4, 6):
        data = load("e07", version, "merge-reset")
        assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", data["log"])) == 2
        assert len(re.findall(r"QP_RESET_TARGET state=0", data["log"])) == 2
        assert data["merge"]
        for receiver in ("cltsys0", "cltsys2"):
            resets = [int(item["tick"]) for item in data["reset"] if item["node"] == receiver]
            transmissions = [int(item["tick"]) for item in data["tx"] if item["node"] == receiver]
            assert resets and transmissions
            assert max(transmissions) < max(resets), (receiver, transmissions, resets)
            assert qpns(data["ce"], receiver) == {1}
        summary("E07", version, data)


def check_e08():
    for version in (4, 6):
        read = load("e08", version, "read-credit")
        assert len(re.findall(r"READ_CREDIT_SUMMARY completed=4 outstanding=0", read["log"])) == 2
        assert "READ_CREDIT_WAIT" in read["log"]
        assert read["rx"]
        summary("E08-read-credit", version, read)
        send = load("e08", version, "send-recv")
        assert len(re.findall(r"SEND_BATCH_SUMMARY submitted=4 completed=4", send["log"])) == 2
        assert len(re.findall(r"RX_CQE mode=46 status=0", send["log"])) == 8
        assert send["rx"]
        summary("E08-send-recv", version, send)


def check_e09():
    for version in (4, 6):
        data = load("e09", version, "drop-cnp")
        drops = list(re.finditer(r"RC_FAULT drop opcode 0x81", data["log"]))
        assert drops and data["rx"]
        first_drop = drops[0].start()
        assert data["log"].find("CNP_RX", first_drop) >= 0
        assert len(re.findall(
            r"RC_STATE_SUMMARY mode=31 submitted=8 success=8 failure=0 outstanding=0",
            data["log"],
        )) == 3
        summary("E09", version, data)


def check_e10():
    logs = list(RESULTS.glob("ecn-*-ipv*/*/simulation.log"))
    assert logs
    for path in logs:
        statistics(path.read_text(errors="replace"))
    print(f"PASS E10 existing full regression and final queue drain across {len(logs)} ECN runs")


CHECKS = {
    "e01": check_e01,
    "e02": check_e02,
    "e03": check_e03,
    "e04": check_e04,
    "e05": check_e05,
    "e06": check_e06,
    "e07": check_e07,
    "e08": check_e08,
    "e09": check_e09,
    "e10": check_e10,
}

selected = sys.argv[1:] or list(CHECKS)
for name in selected:
    CHECKS[name.lower()]()
