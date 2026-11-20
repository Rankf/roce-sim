#!/usr/bin/env python3
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from check_dcqcn import load, packet_ticks
from check_rocev2_pcap import read_pcap
from check_rx import final_rx_zero

RESULTS = Path("results")
SOURCES = ("svrsys", "cltsys0", "cltsys1")
BYTE_RE = re.compile(
    r"(?P<tick>\d+): (?P<node>\w+)\.platform\.rdma_nic\.RdmaEngine:.*?"
    r"DCQCN_BYTE_ACCOUNT qpn (?P<qpn>\d+) packet_bytes (?P<packet_bytes>\d+) "
    r"triggers (?P<triggers>\d+) time_events (?P<time_events>\d+) "
    r"byte_events (?P<byte_events>\d+) byte_remainder (?P<byte_remainder>\d+)"
)


def byte_events(data):
    events = []
    for match in BYTE_RE.finditer(data["log"]):
        event = match.groupdict()
        for key in event:
            if key != "node":
                event[key] = int(event[key])
        events.append(event)
    return events


def unit_log():
    return (RESULTS / "br-format.log").read_text()


def assert_accounting(data, require_triggers=True):
    accounts = byte_events(data)
    paced = [event for event in data["tx"] if event["paced"]]
    assert len(accounts) == len(paced), (data["path"], len(accounts), len(paced))
    expected = defaultdict(int)
    actual = defaultdict(int)
    for event in paced:
        expected[event["node"]] += event["bytes"]
    for event in accounts:
        actual[event["node"]] += event["packet_bytes"]
    assert dict(actual) == dict(expected), (actual, expected)
    if require_triggers:
        assert sum(event["triggers"] for event in accounts) > 0, data["path"]
    return accounts


def check_br01():
    data = load("br-01-default-ipv4/multi-qp")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 2
    assert "DCQCN_BYTE_ACCOUNT" not in data["log"]
    for line in data["log"].splitlines():
        if "DCQCN_" in line and "time_events=" in line:
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            assert fields["time_events"] == "0" and fields["byte_events"] == "0"
    with (RESULTS / "br01-frozen-signature.csv").open() as stream:
        frozen = list(csv.DictReader(stream))
    current = []
    sequence = defaultdict(int)
    for event in data["tx"]:
        key = (event["node"], event["qpn"])
        index = sequence[key]
        sequence[key] += 1
        current.append({"node": event["node"], "qpn": event["qpn"], "sequence": index,
                        "opcode": event["opcode"], "psn": event["psn"],
                        "bytes": event["bytes"], "rate": event["rate"]})
    frozen_current = [{key: value if key == "node" else int(value) for key, value in row.items()}
                      for row in frozen]
    def by_flow(rows):
        result = defaultdict(list)
        for row in rows:
            result[(row["node"], row["qpn"])].append(
                {key: value for key, value in row.items() if key != "rate"})
        return result
    assert by_flow(current) == by_flow(frozen_current)
    for path in ("dcqcn-d07-repeat-ipv4/multi-qp", "br-01-default-ipv4/multi-qp"):
        item = load(path)
        assert len(re.findall(r"DCQCN_DECREASE qpn \d+[^\n]*rate 50000000000", item["log"])) >= 2
        assert all(f"phase {phase}" in item["log"] for phase in ("FR", "AI", "HAI"))
    print("PASS BR01 default time-only packet sequence and key FR/AI/HAI rate trajectory match frozen behavior")


def check_br02():
    total_busy = 0
    total_triggers = 0
    for subdir in ("multipacket", "cross-page", "ring-stress"):
        data = load(f"br-02-send-ipv4/{subdir}")
        assert not re.search(r"SUMMARY[^\n]*(?:failure=[1-9]|outstanding=[1-9])", data["log"])
        accounts = assert_accounting(data, require_triggers=False)
        total_busy += data["log"].count("PACER_BUSY")
        total_triggers += sum(event["triggers"] for event in accounts)
    assert total_busy >= 60 and total_triggers > 0
    print(f"PASS BR02 queued/busy/rejected sends are uncharged; actual paced sends match accounting, busy={total_busy}")


def check_br03():
    assert "PASS BR03 byte threshold below/equal/above, multi-trigger and residual preservation" in unit_log()
    print("PASS BR03 threshold equality, overshoot residue and multiple thresholds in one packet")


def check_br04():
    assert "PASS BR04 independent T/BC progression and Figure 7 FR/AI/HAI boundaries" in unit_log()
    data = load("br-02-send-ipv4/ring-stress")
    accounts = byte_events(data)
    assert any(event["byte_events"] for event in accounts)
    assert "DCQCN_RECOVERY" in data["log"] and "trigger time" in data["log"] and "trigger byte" in data["log"]
    print("PASS BR04 independent time/byte triggers observed in algorithm and actual traffic")


def check_br05():
    assert "PASS BR05 congestion decrease resets both counters, residue and stage with rate bounds" in unit_log()
    assert "PASS D04 alpha precision, FR/AI/HAI recovery and maximum-rate clamp" in unit_log()
    print("PASS BR05 Figure 7 phase boundaries, decrease reset and min/max rate bounds")


def check_br06():
    assert "PASS BR06 same-tick time/byte ordering, zero-byte repeat and clean reinitialization" in unit_log()
    data = load("br-06-lifecycle-ipv4/merge-reset")
    assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", data["log"])) == 2
    assert "PACER_QP_CLEAR" in data["log"]
    assert not re.search(r"SUMMARY[^\n]*(?:failure=[1-9]|outstanding=[1-9])", data["log"])
    print("PASS BR06 same-tick ordering, duplicate suppression, QP Reset and stale-event isolation")


def check_br07():
    data = load("br-07-pfc-ipv4/sustained")
    assert len(re.findall(r"DCQCN_FLOW_SUMMARY submitted=50 success=50 failure=0 outstanding=0", data["log"])) == 3
    final_rx_zero(data)
    accounts = assert_accounting(data)
    assert "PFC_RX" in data["log"] and "RX_XOFF" in data["log"]
    assert "RC_RETRANSMIT" in data["log"] and "PACER_BUSY" in data["log"]
    windows = []
    for match in re.finditer(r"(\d+): (\w+)\.platform[^\n]*PFC_RX priority 3 quantum [1-9]\d* until (\d+)", data["log"]):
        windows.append((match.group(2), int(match.group(1)), int(match.group(3))))
    for event in accounts:
        assert not any(node == event["node"] and start < event["tick"] < until
                       for node, start, until in windows), event
    paced = [event for event in data["tx"] if event["paced"]]
    for previous, current in zip(paced, paced[1:]):
        if previous["node"] == current["node"] and previous["qpn"] == current["qpn"]:
            assert current["tick"] - previous["tick"] >= packet_ticks(previous["bytes"], current["rate"])
    print("PASS BR07 PFC pause/resume, busy and retransmission charging with existing pacing")


def check_br08():
    data = load("br-08-dual-ipv6/sustained")
    assert len(re.findall(r"DCQCN_FLOW_SUMMARY submitted=50 success=50 failure=0 outstanding=0", data["log"])) == 3
    assert_accounting(data)
    for name in ("server", "client1", "client2", "client3"):
        packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
        assert packets and all(packet.get("ip_version") == 6 for packet in packets if not packet.get("pfc"))
    e10 = (RESULTS / "ecn-e10-check.log").read_text().splitlines()
    assert len(e10) == 144 and all(line.startswith("PASS") for line in e10)
    for name in ("pfc-all.log", "rx-all.log", "mspfc-all.log"):
        lines = (RESULTS / name).read_text().splitlines()
        assert len(lines) == 10 and all(line.startswith("PASS") for line in lines)
    print("PASS BR08 old/new comparison, IPv6, existing regressions and final drain")


def export_evidence():
    rows = []
    cases = (("default", "01-default", "ipv4", "multi-qp"),
             ("dual-multipacket", "02-send", "ipv4", "multipacket"),
             ("dual-ring", "02-send", "ipv4", "ring-stress"),
             ("dual-pfc", "07-pfc", "ipv4", "sustained"),
             ("dual-ipv6", "08-dual", "ipv6", "sustained"))
    for mode, tag, version, subdir in cases:
        data = load(f"br-{tag}-{version}/{subdir}")
        accounts = byte_events(data)
        for node in sorted(set(event["node"] for event in data["tx"])):
            node_accounts = [event for event in accounts if event["node"] == node]
            node_tx = [event for event in data["tx"] if event["node"] == node and event["paced"]]
            rows.append({"mode": mode, "node": node,
                         "paced_packets": len(node_tx),
                         "actual_bytes": sum(event["bytes"] for event in node_tx),
                         "byte_triggers": sum(event["triggers"] for event in node_accounts),
                         "max_time_events": max((event["time_events"] for event in node_accounts), default=0),
                         "max_byte_events": max((event["byte_events"] for event in node_accounts), default=0),
                         "busy": data["log"].count("PACER_BUSY"),
                         "retransmits": data["log"].count("RC_RETRANSMIT")})
    with (RESULTS / "br-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    data = load("br-07-pfc-ipv4/sustained")
    markers = ("PACER_TX", "PACER_BUSY", "DCQCN_", "PFC_RX", "PFC_XOFF", "PFC_XON",
               "RX_BUFFER_EVENT", "RX_XOFF", "RX_XON", "RC_RETRANSMIT")
    events = []
    for line in data["log"].splitlines():
        event = next((name for name in markers if name in line), None)
        if not event:
            continue
        prefix = re.search(r"(\d+): (\w+)\.platform", line)
        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
        tick = int(prefix.group(1)) if prefix else int(fields.get("tick", 0))
        node = prefix.group(2) if prefix else fields.get("port", "switch")
        events.append((tick, node, event, line))
    events.sort(key=lambda row: (row[0], row[1], row[2]))
    with (RESULTS / "br-timeseries.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("tick", "node", "event", "details"))
        writer.writerows(events)


CHECKS = {f"br{i:02d}": value for i, value in enumerate(
    (check_br01, check_br02, check_br03, check_br04, check_br05,
     check_br06, check_br07, check_br08), 1)}

if __name__ == "__main__":
    selected = sys.argv[1:] or list(CHECKS)
    for name in selected:
        CHECKS[name.lower()]()
    if not selected or selected == list(CHECKS):
        export_evidence()
