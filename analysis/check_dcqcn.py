#!/usr/bin/env python3
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

from check_rocev2_pcap import read_pcap

RESULTS = Path("results")
SOURCES = ("svrsys", "cltsys0", "cltsys1")
MAX_RATE = 100000000000

PACER_RE = re.compile(
    r"(?P<tick>\d+): (?P<node>\w+)\.platform\.rdma_nic\.RdmaEngine:.*?"
    r"PACER_TX qpn (?P<qpn>\d+) opcode 0x(?P<opcode>[0-9a-f]+) PSN 0x(?P<psn>[0-9a-f]+) "
    r"bytes (?P<bytes>\d+) rate (?P<rate>\d+) paced (?P<paced>\d+) generation (?P<generation>\d+)"
)
STATE_RE = re.compile(
    r"(?P<tick>\d+): (?P<node>\w+)\.platform\.rdma_nic\.RdmaEngine:.*?"
    r"(?P<event>DCQCN_CNP|DCQCN_ALPHA|DCQCN_DECREASE|DCQCN_STATE) qpn (?P<qpn>\d+) "
    r"alpha (?P<alpha>[0-9.e+-]+) rate (?P<rate>\d+) target (?P<target>\d+) "
    r"stage (?P<stage>\d+)"
)


def packet_ticks(size, rate):
    numerator = size * 8 * 1000000000000
    return max(1, numerator // rate + bool(numerator % rate))


def load(relative):
    path = RESULTS / relative / "simulation.log"
    log = path.read_text(errors="replace")
    assert "Exiting @ tick" in log and "simulate() limit reached" not in log, path
    assert not any(item in log for item in ("segmentation fault", "Program aborted", "panic:")), path
    ports = {}
    for line in log.splitlines():
        if line.startswith("SWITCH_PORT_STAT "):
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            ports[fields["port"]] = {k: int(v) for k, v in fields.items() if k != "port"}
    metadata = {}
    run_yaml = path.parent / "run.yaml"
    if run_yaml.exists():
        metadata = dict(line.split("=", 1) for line in run_yaml.read_text().splitlines())
    switch_num = int(metadata.get("switch_num", 1))
    expected_ports = 4 + 2 * (switch_num - 1)
    assert len(ports) == expected_ports or (switch_num == 2 and len(ports) == 4), path
    for port, stat in ports.items():
        assert stat["enq_packets"] == stat["sent_packets"] + stat["drop_packets"] + stat["queued_packets"], port
        assert stat["enq_bytes"] == stat["sent_bytes"] + stat["drop_bytes"] + stat["queued_bytes"], port
        assert stat["queued_packets"] == 0 and stat["queued_bytes"] == 0, port
    return {"path": path, "log": log, "ports": ports, "tx": pacer_events(log)}


def pacer_events(log):
    events = []
    for match in PACER_RE.finditer(log):
        item = match.groupdict()
        for key in ("tick", "qpn", "bytes", "rate", "paced", "generation"):
            item[key] = int(item[key])
        item["opcode"] = int(item["opcode"], 16)
        item["psn"] = int(item["psn"], 16)
        events.append(item)
    return events


def state_events(log, event=None):
    result = []
    for match in STATE_RE.finditer(log):
        if event and match.group("event") != event:
            continue
        item = match.groupdict()
        for key in ("tick", "qpn", "rate", "target", "stage"):
            item[key] = int(item[key])
        item["alpha"] = float(item["alpha"])
        result.append(item)
    return result


def writes(data, node):
    return [e for e in data["tx"] if e["node"] == node and e["qpn"] == 1 and
            e["opcode"] in (0x06, 0x07, 0x08, 0x0a, 0x0b)]


def check_fixed_fanin(data, count=8, mode=31):
    pattern = (rf"DCQCN_FLOW_SUMMARY submitted={count} success={count} failure=0 outstanding=0"
               if mode == 91 else
               rf"RC_STATE_SUMMARY mode={mode} submitted={count} success={count} failure=0 outstanding=0"
               if mode else rf"FIXED_SUMMARY submitted={count} success={count} failure=0 outstanding=0")
    assert len(re.findall(pattern, data["log"])) == 3, data["path"]


def check_d01():
    disabled = load("dcqcn-d01-disabled-ipv4/feedback")
    check_fixed_fanin(disabled)
    assert not any(e["paced"] for e in disabled["tx"])
    assert "DCQCN_" not in disabled["log"]
    rates = {}
    for rate in (10000000000, 20000000000):
        data = load(f"dcqcn-d01-{rate // 1000000000}g-ipv4/feedback")
        check_fixed_fanin(data)
        intervals = []
        for node in SOURCES:
            packets = writes(data, node)
            assert len(packets) == 8 and all(e["paced"] and e["rate"] == rate for e in packets)
            for previous, current in zip(packets, packets[1:]):
                expected = packet_ticks(previous["bytes"], rate)
                assert current["tick"] - previous["tick"] == expected, (node, previous, current)
                intervals.append(current["tick"] - previous["tick"])
        assert intervals
        rates[rate] = intervals[0]
        print(f"PASS D01 IPv4 fixed rate={rate} packet_bytes=138 interval_ps={intervals[0]}")
    assert rates[10000000000] == 2 * rates[20000000000]
    print("PASS D01 controller-disabled behavior preserves unpaced transmission")


def check_d02():
    data = load("dcqcn-d02-sustained-ipv4/sustained")
    check_fixed_fanin(data, 50, 91)
    for node in SOURCES:
        decreases = [e for e in state_events(data["log"], "DCQCN_DECREASE") if e["node"] == node]
        assert decreases and decreases[0]["rate"] == MAX_RATE // 2
        packets = writes(data, node)
        assert any(e["paced"] and e["rate"] < MAX_RATE and e["tick"] > decreases[0]["tick"] for e in packets)
    assert "PASS D02 first CNP state, timers and monitored rate decrease" in (RESULTS / "dcqcn-format.log").read_text()
    print("PASS D02 first CNP changes both controller state and later wire transmission")


def check_d03():
    log = (RESULTS / "dcqcn-format.log").read_text()
    assert "PASS D03 same-tick and cross-period CNP coalescing" in log
    data = load("dcqcn-d02-sustained-ipv4/sustained")
    for node in SOURCES:
        cnp = len([e for e in state_events(data["log"], "DCQCN_CNP") if e["node"] == node])
        decreases = len([e for e in state_events(data["log"], "DCQCN_DECREASE") if e["node"] == node])
        assert cnp >= decreases > 0
    print("PASS D03 periodic monitoring coalesces multiple CNP events into one decrease")


def check_d04():
    assert "PASS D04 alpha precision, FR/AI/HAI recovery and maximum-rate clamp" in (RESULTS / "dcqcn-format.log").read_text()
    data = load("dcqcn-d02-sustained-ipv4/sustained")
    assert "DCQCN_RECOVERY qpn 1 phase FR" in data["log"]
    assert all(e["rate"] <= MAX_RATE and e["target"] <= MAX_RATE for e in state_events(data["log"]))
    print("PASS D04 alpha decay and time-driven FR/AI/HAI state machine with rate bounds")


def check_d05():
    lengths = set()
    busy = 0
    for subdir in ("multipacket", "cross-page", "ring-stress"):
        data = load(f"dcqcn-d05-ipv4/{subdir}")
        busy += data["log"].count("PACER_BUSY")
        lengths.update(e["bytes"] for e in data["tx"] if e["paced"])
        assert not re.search(r"SUMMARY[^\n]*(?:failure=[1-9]|outstanding=[1-9])", data["log"])
        for node in SOURCES:
            previous = None
            for event in data["tx"]:
                if event["node"] != node or not event["paced"]:
                    continue
                if previous and event["rate"] == previous["rate"]:
                    elapsed = event["tick"] - previous["tick"]
                    assert elapsed >= packet_ticks(previous["bytes"], event["rate"])
                previous = event
    assert busy >= 80 and max(lengths) > 4096 and min(lengths) < 200
    print(f"PASS D05 variable-length charging, busy retry without budget consumption; busy={busy}")


def check_d06():
    data = load("dcqcn-d06-ipv4/read-response")
    assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", data["log"])) == 2
    for node in ("cltsys0", "cltsys2"):
        decreases = [e for e in state_events(data["log"], "DCQCN_DECREASE") if e["node"] == node]
        assert decreases
        responses = [e for e in data["tx"] if e["node"] == node and e["qpn"] == 1 and
                     e["opcode"] in (0x0d, 0x0e, 0x0f, 0x10)]
        assert any(e["rate"] < MAX_RATE and e["tick"] > decreases[0]["tick"] for e in responses)
    controls = [e for e in data["tx"] if e["opcode"] in (0x11, 0x81)]
    assert controls and all(not e["paced"] for e in controls)
    print("PASS D06 responder-side Read Response pacing and unpaced ACK/CNP progress")


def check_d07():
    data = load("dcqcn-d07-ipv4/multi-qp")
    repeat = load("dcqcn-d07-repeat-ipv4/multi-qp")
    assert len(re.findall(r"RING_SUMMARY submitted=320 completions=81 outstanding=0", data["log"])) == 2
    for node in ("svrsys", "cltsys1"):
        for qpn in (1, 2):
            decreases = [e for e in state_events(data["log"], "DCQCN_DECREASE")
                         if e["node"] == node and e["qpn"] == qpn]
            assert decreases
    def flow_signature(item):
        flows = defaultdict(list)
        for event in item["tx"]:
            flows[(event["node"], event["qpn"])].append(
                (event["opcode"], event["psn"], event["bytes"], event["rate"]))
        return dict(flows)
    assert flow_signature(data) == flow_signature(repeat)
    assert "PASS D07 same-tick control priority, round-robin wrap and repeatability" in (RESULTS / "dcqcn-format.log").read_text()
    sent = defaultdict(list)
    for line in data["log"].splitlines():
        if line.startswith("SWITCH_QUEUE_EVENT ") and "action=sent" in line:
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            sent[fields["port"]].append((int(fields["tick"]), int(fields["bytes"])))
    for port, packets in sent.items():
        assert all(b[0] > a[0] for a, b in zip(packets, packets[1:])), port
        span = packets[-1][0] - packets[0][0] + packet_ticks(packets[-1][1], MAX_RATE)
        assert sum(item[1] for item in packets) * 8 * 1000000000000 <= span * MAX_RATE, port
    print("PASS D07 independent QP state, shared-port capacity and deterministic repeat")


def export_timeseries(data, relative):
    rows = []
    for event in data["tx"]:
        rows.append({"tick": event["tick"], "node": event["node"], "event": "PACER_TX",
                     "qpn": event["qpn"], "opcode": event["opcode"], "psn": event["psn"],
                     "bytes": event["bytes"], "rate": event["rate"]})
    for event in state_events(data["log"]):
        rows.append(event)
    for line in data["log"].splitlines():
        if line.startswith("SWITCH_QUEUE_EVENT ") or line.startswith("SWITCH_ECN_EVENT "):
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            rows.append({"tick": int(fields["tick"]), "node": fields["port"],
                         "event": "SWITCH_QUEUE" if "QUEUE" in line else "SWITCH_ECN",
                         "action": fields.get("action"), "bytes": fields.get("bytes"),
                         "queued_bytes": fields.get("queued_bytes", fields.get("queue_bytes")),
                         "queue_delay": fields.get("queue_delay")})
        elif "DCQCN_RECOVERY" in line:
            match = re.search(r"(\d+): (\w+)\.platform.*DCQCN_RECOVERY qpn (\d+) phase (\w+)", line)
            if match:
                rows.append({"tick": int(match.group(1)), "node": match.group(2),
                             "event": "DCQCN_RECOVERY", "qpn": int(match.group(3)),
                             "phase": match.group(4)})
        elif "CNP_RX" in line:
            match = re.search(r"(\d+): (\w+)\.platform.*CNP_RX qpn (\d+)", line)
            if match:
                rows.append({"tick": int(match.group(1)), "node": match.group(2),
                             "event": "CNP_RX", "qpn": int(match.group(3))})
    rows.sort(key=lambda row: (row["tick"], row["node"], row["event"], row.get("qpn") or 0))
    fields = ["tick", "node", "event", "qpn", "opcode", "psn", "bytes", "rate",
              "target", "alpha", "stage", "phase", "action", "queued_bytes", "queue_delay"]
    path = RESULTS / relative / "timeseries.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def check_d08():
    baseline = load("dcqcn-d08-baseline-ipv4/sustained")
    dcqcn = load("dcqcn-d08-dcqcn-ipv4/sustained")
    for data in (baseline, dcqcn):
        check_fixed_fanin(data, 100, 91)
    assert not any(e["paced"] for e in baseline["tx"])
    rows = []
    for scenario, data in (("feedback", baseline), ("dcqcn", dcqcn)):
        directory = "baseline" if scenario == "feedback" else "dcqcn"
        export_timeseries(data, f"dcqcn-d08-{directory}-ipv4/sustained")
        for node in SOURCES:
            packets = writes(data, node)
            unique = {}
            for event in packets:
                unique.setdefault(event["psn"], event)
            assert len(unique) == 100
            first = min(e["tick"] for e in unique.values())
            last = max(e["tick"] for e in unique.values())
            span = max(1, last - first)
            actual_bytes = sum(e["bytes"] for e in packets)
            rows.append({"scenario": scenario, "node": node, "unique_writes": len(unique),
                         "actual_packets": len(packets), "actual_bytes": actual_bytes,
                         "span_ps": span, "actual_rate_bps": actual_bytes * 8 * 1000000000000 // span,
                         "goodput_bps": len(unique) * 64 * 8 * 1000000000000 // span,
                         "cnp": len(re.findall(rf"\d+: {node}\.platform[^\n]*CNP_RX", data["log"])), 
                         "decreases": len([e for e in state_events(data["log"], "DCQCN_DECREASE") if e["node"] == node])})
        marked = sum(port["ecn_marked"] for port in data["ports"].values())
        dropped = sum(port["drop_packets"] for port in data["ports"].values())
        print(f"PASS D08 {scenario} marked={marked} dropped={dropped} queues_drained=1")
    for row in rows:
        if row["scenario"] == "dcqcn":
            assert row["cnp"] and row["decreases"]
    assert "DCQCN_RECOVERY" in dcqcn["log"]
    with (RESULTS / "dcqcn-d08-summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("PASS D08 sustained three-to-one time series, actual rate and deduplicated goodput exported")


def check_d09():
    loss = load("dcqcn-d09-loss-ipv4/drop-cnp")
    check_fixed_fanin(loss)
    assert "RC_FAULT drop opcode 0x81" in loss["log"] and "CNP_RX" in loss["log"]
    retrans = load("dcqcn-d09-retrans-ipv4/overflow")
    assert "RC_RETRANSMIT" in retrans["log"]
    repeated = defaultdict(int)
    for event in retrans["tx"]:
        if event["node"] in SOURCES and event["qpn"] == 1 and event["opcode"] == 0x0a:
            repeated[(event["node"], event["psn"])] += 1
    assert any(count > 1 for count in repeated.values())
    lifecycle = load("dcqcn-d09-lifecycle-ipv4/merge-reset")
    assert len(re.findall(r"QP_RESET_SUMMARY flushed=1 success=1", lifecycle["log"])) == 2
    assert lifecycle["log"].count("PACER_QP_CLEAR") >= 4
    assert "DCQCN_CNP" in lifecycle["log"]
    print("PASS D09 CNP loss, wire-loss retransmission charging, ERR/RESET cleanup and QP rebuild")


def check_d10():
    sustained = load("dcqcn-d02-sustained-ipv6/sustained")
    read = load("dcqcn-d06-ipv6/read-response")
    check_fixed_fanin(sustained, 50, 91)
    assert len(re.findall(r"FIXED_SUMMARY submitted=16 success=16 failure=0 outstanding=0", read["log"])) == 2
    assert any(e["paced"] and e["rate"] < MAX_RATE for e in sustained["tx"])
    assert any(e["paced"] and e["rate"] < MAX_RATE and e["opcode"] == 0x10 for e in read["tx"])
    for data in (sustained, read):
        for name in ("server", "client1", "client2", "client3"):
            packets = read_pcap(data["path"].parent / f"rocev2.{name}.pcap")
            assert packets and all(packet["ip_version"] == 6 for packet in packets)
    e01 = (RESULTS / "ecn-e01-e09-check.log").read_text()
    e10 = (RESULTS / "ecn-e10-check.log").read_text()
    assert "FAIL" not in e01 and "FAIL" not in e10
    assert "PASS E10 existing full regression" in e10
    print("PASS D10 IPv6 CNP/rate/pacing representatives and existing dual-stack full regression")


CHECKS = {"d01": check_d01, "d02": check_d02, "d03": check_d03, "d04": check_d04,
          "d05": check_d05, "d06": check_d06, "d07": check_d07, "d08": check_d08,
          "d09": check_d09, "d10": check_d10}

if __name__ == "__main__":
    selected = sys.argv[1:] or list(CHECKS)
    for name in selected:
        CHECKS[name.lower()]()
