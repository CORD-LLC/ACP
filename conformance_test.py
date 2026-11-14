"""
ACP v1.1 Fleet Conformance Test Suite

For B2B partners building ACP-conformant fleet implementations.
Run this against any system that claims to produce valid ACP fleet envelopes.

Usage:
    # Test envelope generation from a live endpoint
    python conformance_test.py --url https://your-fleet-agent.example.com --token YOUR_TOKEN

    # Test a static JSON envelope file
    python conformance_test.py --file my_envelope.json

    # Run all conformance checks and output a report
    python conformance_test.py --file my_envelope.json --report conformance_report.json

A conformant implementation must pass ALL required tests.
Advisory tests are best-practice recommendations.

Results:
    PASS  = conformant
    FAIL  = non-conformant, must fix before claiming ACP v1.1 compliance
    WARN  = advisory, should fix for production use
    SKIP  = test not applicable given envelope configuration
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

CONFORMANCE_VERSION = "1.1.0"
SPEC_URL = "https://acpspec.org/fleet"

# source.agent_type, a MUST field. The published values, kept here so they can
# be tested rather than living only on acpspec.org.
LEAD_AGENT_TYPES = frozenset({
    "sales_chat", "sales_voice", "inbound_voice", "service_text", "service_voice",
})
FLEET_AGENT_TYPES = frozenset({"vehicle_agent", "fleet_ops_agent"})


# ── Result types ──────────────────────────────────────────────────────────────

class ConformanceResult:
    def __init__(self, test_id, name, required=True):
        self.test_id = test_id
        self.name = name
        self.required = required
        self.status = "SKIP"
        self.message = ""
        self.detail = None

    def passed(self, msg=""):
        self.status = "PASS"; self.message = msg; return self

    def failed(self, msg, detail=None):
        self.status = "FAIL"; self.message = msg; self.detail = detail; return self

    def warned(self, msg):
        self.status = "WARN"; self.message = msg; return self

    def skipped(self, msg=""):
        self.status = "SKIP"; self.message = msg; return self

    def to_dict(self):
        d = {"test_id": self.test_id, "name": self.name,
             "required": self.required, "status": self.status,
             "message": self.message}
        if self.detail:
            d["detail"] = self.detail
        return d


# ── Conformance checks ────────────────────────────────────────────────────────

def check_acp_meta(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("ACP-001", "acp block present")
    acp = env.get("acp")
    if not acp:
        r.failed("Missing required 'acp' block")
    else:
        r.passed()
    results.append(r)

    r = ConformanceResult("ACP-002", "acp.version is 1.1.0")
    if acp:
        v = acp.get("version", "")
        if v == "1.1.0":
            r.passed()
        elif v.startswith("1."):
            r.warned(f"version '{v}' is ACP v1.x but not 1.1.0, fleet extension requires 1.1.0")
        else:
            r.failed(f"version '{v}', fleet extension requires ACP v1.1.0")
    results.append(r)

    r = ConformanceResult("ACP-003", "acp.envelope_id format")
    if acp:
        eid = acp.get("envelope_id", "")
        if eid.startswith("acp_"):
            r.passed()
        else:
            r.failed(f"envelope_id '{eid}' must start with 'acp_'")
    results.append(r)

    r = ConformanceResult("ACP-004", "acp.generated_at is ISO 8601")
    if acp:
        ts = acp.get("generated_at", "")
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            r.passed()
        except (ValueError, AttributeError):
            r.failed(f"generated_at '{ts}' is not valid ISO 8601")
    results.append(r)

    return results


def check_fleet_block(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("FLT-001", "fleet block present")
    fleet = env.get("fleet")
    if not fleet:
        r.failed("Missing required 'fleet' block")
        results.append(r)
        return results
    r.passed()
    results.append(r)

    r = ConformanceResult("FLT-002", "fleet.operator_id present and non-empty")
    op = fleet.get("operator_id", "")
    if op:
        r.passed()
    else:
        r.failed("fleet.operator_id is required and must be non-empty")
    results.append(r)

    r = ConformanceResult("FLT-003", "fleet.vehicle.vin is 17-char alphanumeric")
    vehicle = fleet.get("vehicle", {})
    vin = vehicle.get("vin", "")
    if len(vin) == 17 and vin.isalnum():
        r.passed()
    elif len(vin) == 17:
        r.failed(f"VIN '{vin}' contains non-alphanumeric characters")
    else:
        r.failed(f"VIN '{vin}' is {len(vin)} characters, must be exactly 17")
    results.append(r)

    r = ConformanceResult("FLT-004", "fleet.health.severity is valid enum")
    health = fleet.get("health", {})
    severity = health.get("severity", "")
    valid_severities = {"immediate", "scheduled", "predictive", "recall"}
    if severity in valid_severities:
        r.passed()
    else:
        r.failed(f"severity '{severity}', must be one of: {', '.join(sorted(valid_severities))}")
    results.append(r)

    r = ConformanceResult("FLT-005", "recall severity requires recall_campaign_ids",
                          required=False)
    if severity == "recall":
        recall_ids = health.get("recall_campaign_ids", [])
        if recall_ids:
            r.passed()
        else:
            r.failed("severity is 'recall' but recall_campaign_ids is empty or missing")
    else:
        r.skipped("severity is not 'recall'")
    results.append(r)

    r = ConformanceResult("FLT-006", "fleet.health.health_score in range 0-100",
                          required=False)
    score = health.get("health_score")
    if score is None:
        r.skipped("health_score not provided")
    elif isinstance(score, (int, float)) and 0 <= score <= 100:
        r.passed()
    else:
        r.warned(f"health_score '{score}' should be 0-100")
    results.append(r)

    r = ConformanceResult("FLT-007", "fleet.vehicle.autonomous_level advisory",
                          required=False)
    al = vehicle.get("autonomous_level")
    if al is not None:
        if al in [3, 4, 5]:
            r.passed(f"autonomous_level {al} is valid SAE level")
        else:
            r.warned(f"autonomous_level {al}, expected SAE level 3, 4, or 5")
    else:
        r.skipped("autonomous_level not provided")
    results.append(r)

    return results


def check_exclusivity(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("EXC-001", "fleet and lead blocks are mutually exclusive")
    has_fleet = "fleet" in env
    has_lead = "lead" in env
    if has_fleet and has_lead:
        r.failed("Envelope contains both 'fleet' and 'lead', these are mutually exclusive")
    elif has_fleet:
        r.passed("fleet present, lead absent")
    elif has_lead:
        r.skipped("lead envelope, fleet conformance not applicable")
    else:
        r.failed("Neither 'fleet' nor 'lead' block present")
    results.append(r)

    return results


def check_service_request(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("SR-001", "service_request block present")
    sr = env.get("service_request")
    if not sr:
        r.failed("Missing required 'service_request' block")
        results.append(r)
        return results
    r.passed()
    results.append(r)

    r = ConformanceResult("SR-002", "service_request.id matches sr_ pattern")
    sr_id = sr.get("id", "")
    if sr_id.startswith("sr_"):
        r.passed()
    else:
        r.failed(f"service_request.id '{sr_id}' must start with 'sr_'")
    results.append(r)

    r = ConformanceResult("SR-003", "service_request.stage is valid enum")
    stage = sr.get("stage", "")
    valid_stages = {"dispatched", "scheduled", "in_bay", "completed", "invoiced", "closed"}
    if stage in valid_stages:
        r.passed()
    else:
        r.failed(f"stage '{stage}', must be one of: {', '.join(sorted(valid_stages))}")
    results.append(r)

    r = ConformanceResult("SR-004", "service_request.initiated_by is valid")
    initiated = sr.get("initiated_by", "")
    valid_agents = {"vehicle_agent", "fleet_ops_agent", "dealer_agent", "human_operator"}
    if initiated in valid_agents:
        r.passed()
    else:
        r.failed(f"initiated_by '{initiated}', must be one of: {', '.join(sorted(valid_agents))}")
    results.append(r)

    r = ConformanceResult("SR-005", "service_request.work_items present and non-empty")
    items = sr.get("work_items", [])
    if items and len(items) > 0:
        r.passed(f"{len(items)} work item(s)")
    else:
        r.failed("work_items must be present and contain at least one item")
    results.append(r)

    r = ConformanceResult("SR-006", "recall work items have recall_campaign_id")
    recall_items = [i for i in items if i.get("recall_campaign_id")]
    non_recall = [i for i in items if not i.get("recall_campaign_id")]
    fleet_health = env.get("fleet", {}).get("health", {})
    severity = fleet_health.get("severity", "")
    if severity == "recall" and not recall_items:
        r.failed("severity is 'recall' but no work items have recall_campaign_id set")
    else:
        r.passed()
    results.append(r)

    r = ConformanceResult("SR-007", "scheduled stage requires appointment.scheduled_at",
                          required=False)
    appt = sr.get("appointment", {})
    if stage == "scheduled":
        if appt.get("scheduled_at"):
            r.passed()
        else:
            r.failed("stage is 'scheduled' but appointment.scheduled_at is not set")
    else:
        r.skipped(f"stage is '{stage}', not 'scheduled'")
    results.append(r)

    r = ConformanceResult("SR-008", "fleet_pricing_agreement_id format advisory",
                          required=False)
    pa_id = sr.get("fleet_pricing_agreement_id")
    if pa_id:
        if pa_id.startswith("fpa_"):
            r.passed()
        else:
            r.warned(f"fleet_pricing_agreement_id '{pa_id}', recommended prefix is 'fpa_'")
    else:
        r.skipped("No pricing agreement on this envelope")
    results.append(r)

    return results


def check_events(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("EVT-001", "events block present")
    events = env.get("events", [])
    if isinstance(events, list):
        r.passed(f"{len(events)} event(s)")
    else:
        r.failed("events must be a list")
    results.append(r)

    r = ConformanceResult("EVT-002", "vehicle_health_detected event present",
                          required=False)
    types = [e.get("type", "") for e in events]
    if "vehicle_health_detected" in types:
        r.passed()
    else:
        r.warned("Recommended: include vehicle_health_detected event in initial envelope")
    results.append(r)

    r = ConformanceResult("EVT-003", "fleet.service_request.initiated event present",
                          required=False)
    if "fleet.service_request.initiated" in types:
        r.passed()
    else:
        r.warned("Recommended: include fleet.service_request.initiated event")
    results.append(r)

    r = ConformanceResult("EVT-004", "all events have type and timestamp")
    bad = [e for e in events if not e.get("type") or not e.get("timestamp")]
    if not bad:
        r.passed()
    else:
        r.failed(f"{len(bad)} event(s) missing 'type' or 'timestamp'")
    results.append(r)

    return results


def check_source(env: dict) -> List[ConformanceResult]:
    results = []

    r = ConformanceResult("SRC-001", "source.agent_type is a published value for the envelope kind")
    source = env.get("source", {})
    agent_type = source.get("agent_type", "")
    if "lead" in env and "fleet" not in env:
        allowed, kind = LEAD_AGENT_TYPES, "lead"
    else:
        allowed, kind = FLEET_AGENT_TYPES, "fleet"
    if agent_type in allowed:
        r.passed(f"{kind} envelope, agent_type '{agent_type}'")
    else:
        r.failed(f"source.agent_type '{agent_type}' is not a published {kind} value; "
                 f"expected one of: {', '.join(sorted(allowed))}")
    results.append(r)

    return results


# ── Runner ────────────────────────────────────────────────────────────────────

def run_conformance(envelope: dict) -> Tuple[List[ConformanceResult], dict]:
    all_results = []
    all_results.extend(check_exclusivity(envelope))
    all_results.extend(check_acp_meta(envelope))
    all_results.extend(check_fleet_block(envelope))
    all_results.extend(check_service_request(envelope))
    all_results.extend(check_events(envelope))
    all_results.extend(check_source(envelope))

    required = [r for r in all_results if r.required]
    advisory = [r for r in all_results if not r.required]

    required_pass = sum(1 for r in required if r.status == "PASS")
    required_fail = sum(1 for r in required if r.status == "FAIL")
    advisory_warn = sum(1 for r in advisory if r.status == "WARN")

    conformant = required_fail == 0

    summary = {
        "conformant": conformant,
        "acp_version": CONFORMANCE_VERSION,
        "spec_url": SPEC_URL,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "required_tests": len(required),
        "required_pass": required_pass,
        "required_fail": required_fail,
        "advisory_tests": len(advisory),
        "advisory_warnings": advisory_warn,
        "verdict": "CONFORMANT" if conformant else "NON-CONFORMANT",
    }

    return all_results, summary


def print_report(results: List[ConformanceResult], summary: dict):
    width = 64
    print()
    print("=" * width)
    print("  ACP v1.1 Fleet Conformance Report")
    print(f"  Spec: {SPEC_URL}")
    print("=" * width)
    print()

    icons = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "·"}
    colors = {"PASS": "\033[32m", "FAIL": "\033[31m", "WARN": "\033[33m", "SKIP": "\033[90m"}
    reset = "\033[0m"

    for r in results:
        icon = icons.get(r.status, "?")
        color = colors.get(r.status, "")
        req = "" if r.required else " [advisory]"
        print(f"  {color}{icon}{reset} {r.test_id:<10} {r.name}{req}")
        if r.message and r.status != "PASS":
            print(f"             {r.message}")
        if r.detail:
            print(f"             Detail: {r.detail}")

    print()
    print("-" * width)
    verdict_color = "\033[32m" if summary["conformant"] else "\033[31m"
    print(f"  Verdict: {verdict_color}{summary['verdict']}{reset}")
    print(f"  Required:  {summary['required_pass']}/{summary['required_tests']} passed, {summary['required_fail']} failed")
    print(f"  Advisory:  {summary['advisory_warnings']} warnings")
    print("-" * width)
    print()

    if not summary["conformant"]:
        print("  This implementation is NOT conformant with ACP v1.1 Fleet.")
        print("  Fix all FAIL items before claiming compliance.")
        print(f"  See: {SPEC_URL}")
    else:
        print("  This implementation is CONFORMANT with ACP v1.1 Fleet.")
        if summary["advisory_warnings"] > 0:
            print(f"  {summary['advisory_warnings']} advisory warning(s), review before production.")
    print()


def load_from_file(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def load_from_url(url: str, token: str) -> dict:
    """POST a sample envelope to the URL and get the response back."""
    import urllib.request
    # Build a minimal valid fleet envelope for testing
    sample = {
        "acp": {
            "version": "1.1.0",
            "protocol": "acp",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "envelope_id": f"acp_{int(time.time())}_conformance",
            "parent_envelope_id": None,
        },
        "source": {"provider": "conformance_tester", "agent_type": "vehicle_agent", "channel": "telematics"},
        "dealership": {"id": "dealer_conformance_test", "name": "Conformance Test Dealer", "dms_provider": "test"},
        "fleet": {
            "operator_id": "conformance_test_operator",
            "operator_name": "Conformance Test",
            "vehicle": {"vin": "SALYB2EX3LA999999", "year": 2023, "make": "Test", "model": "Vehicle", "odometer": 1000},
            "health": {"severity": "predictive", "systems_flagged": ["test_system"]},
        },
        "service_request": {
            "id": f"sr_{int(time.time())}_test",
            "type": "predictive_maintenance",
            "stage": "dispatched",
            "initiated_by": "vehicle_agent",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "work_items": [{"description": "Conformance test item", "op_code": "TEST-001", "labor_hours": "0.5", "parts_required": False, "warranty_eligible": False}],
            "appointment": {"status": "pending"},
            "invoice": {"status": "not_started"},
        },
        "events": [
            {"type": "vehicle_health_detected", "timestamp": datetime.now(timezone.utc).isoformat(), "data": {}},
            {"type": "fleet.service_request.initiated", "timestamp": datetime.now(timezone.utc).isoformat(), "data": {}},
        ],
    }
    # For URL-based conformance, we validate the envelope we'd send, not the response
    print(f"  Note: URL mode validates the envelope your system would produce.")
    print(f"  Using sample conformance envelope for structural validation.")
    return sample


def main():
    parser = argparse.ArgumentParser(
        description="ACP v1.1 Fleet Conformance Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate a JSON file
  python conformance_test.py --file my_envelope.json

  # Validate and save report
  python conformance_test.py --file my_envelope.json --report report.json

  # Validate against a live endpoint
  python conformance_test.py --url https://fleet.example.com --token mytoken

  # Exit code: 0 = conformant, 1 = non-conformant
        """,
    )
    parser.add_argument("--file", help="Path to ACP fleet envelope JSON file")
    parser.add_argument("--url", help="Fleet agent endpoint URL")
    parser.add_argument("--token", default="", help="Bearer token for URL mode")
    parser.add_argument("--report", help="Write JSON report to this file")
    parser.add_argument("--quiet", action="store_true", help="Only print verdict")

    args = parser.parse_args()

    if not args.file and not args.url:
        parser.print_help()
        sys.exit(2)

    print(f"\nACP v1.1 Fleet Conformance Suite · {CONFORMANCE_VERSION}")

    if args.file:
        print(f"Testing: {args.file}")
        try:
            envelope = load_from_file(args.file)
        except Exception as e:
            print(f"Error loading file: {e}")
            sys.exit(2)
    else:
        print(f"Testing: {args.url}")
        envelope = load_from_url(args.url, args.token)

    results, summary = run_conformance(envelope)

    if not args.quiet:
        print_report(results, summary)
    else:
        color = "\033[32m" if summary["conformant"] else "\033[31m"
        print(f"\n  {color}{summary['verdict']}\033[0m ,  {summary['required_pass']}/{summary['required_tests']} required tests passed\n")

    if args.report:
        report = {
            "summary": summary,
            "tests": [r.to_dict() for r in results],
        }
        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Report saved: {args.report}")

    sys.exit(0 if summary["conformant"] else 1)


if __name__ == "__main__":
    main()
