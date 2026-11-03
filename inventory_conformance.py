"""
ACP Inventory Integrity conformance suite (draft 0.1, ACP v1.2.0).

Usage:
    python inventory_conformance.py --file envelope.json
    python inventory_conformance.py --file envelope.json --report report.json
    python inventory_conformance.py --file envelope.json --print-hash

Spec: extensions/inventory-integrity.md
Exit code 0 = conformant, 1 = non-conformant, 2 = bad input.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

from conformance_test import ConformanceResult as R

SUITE_VERSION = "0.1.0"
ACP_VERSION = "1.2.0"
SPEC = "extensions/inventory-integrity.md"

STATUSES = {"in_transit", "in_stock", "pending_sale", "sold", "wholesale", "removed"}
LIVE = {"in_stock", "in_transit", "pending_sale"}
CONDITIONS = {"new", "used", "cpo"}
DRIVETRAINS = {"fwd", "rwd", "awd", "4wd"}
SOURCE_SYSTEMS = {"dms", "inventory_tool", "oem_build", "oem_incentives",
                  "dealer_website", "marketplace", "manual"}
SURFACES = {"dealer_website", "marketplace", "meta_catalog", "google_vehicle_ads",
            "oem_locator", "ai_agent"}
CHECK_IDS = {"INT-VIN-VALID", "INT-BUILD-MATCH", "INT-PRICE-CONSISTENT",
             "INT-STATUS-CONSISTENT", "INT-PRICE-FRESH", "INT-MEDIA-PRESENT",
             "INT-INCENTIVE-VALID"}
EVENT_TYPES = {"inventory.unit.created", "inventory.unit.updated",
               "inventory.unit.price_changed", "inventory.unit.status_changed",
               "inventory.unit.sold", "inventory.integrity.verified",
               "inventory.integrity.conflict_detected",
               "inventory.surface.drift_detected", "inventory.surface.reconciled"}

# tokens that mean drivetrain, doors or body got packed into trim
PACKED = re.compile(r"\b(AWD|4WD|FWD|RWD|2WD|4X4|4X2|[2-5]DR|[2-5]D|SEDAN|COUPE|HATCHBACK|WAGON|CREW ?CAB)\b", re.I)
DECIMAL = re.compile(r"^\d+(\.\d{1,2})?$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")

VIN_VALUES = {**{str(d): d for d in range(10)},
              "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
              "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
              "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9}
VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def record_hash(unit):
    raw = json.dumps(unit, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def vin_check_digit(vin):
    total = sum(VIN_VALUES[c] * w for c, w in zip(vin, VIN_WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def ts(v):
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def check_envelope(env):
    out = []
    kinds = [k for k in ("inventory", "lead", "fleet") if k in env]

    r = R("INV-001", "inventory block present and exclusive of lead and fleet")
    if kinds == ["inventory"]:
        r.passed()
    elif "inventory" not in kinds:
        r.failed("No 'inventory' block")
    else:
        r.failed(f"Envelope carries {', '.join(kinds)}; only one is allowed")
    out.append(r)

    acp = env.get("acp") or {}
    r = R("INV-002", f"acp.version is {ACP_VERSION}")
    v = acp.get("version")
    r.passed() if v == ACP_VERSION else r.failed(f"version '{v}', inventory requires {ACP_VERSION}")
    out.append(r)

    r = R("INV-003", "acp.envelope_id starts with acp_")
    eid = acp.get("envelope_id") or ""
    r.passed() if eid.startswith("acp_") else r.failed(f"envelope_id '{eid}'")
    out.append(r)

    r = R("INV-004", "acp.generated_at is ISO 8601 with offset")
    r.passed() if ts(acp.get("generated_at")) else r.failed(f"generated_at '{acp.get('generated_at')}'")
    out.append(r)

    r = R("INV-005", "acp.mode is snapshot or delta; delta has parent_envelope_id")
    mode = acp.get("mode")
    if mode == "snapshot":
        r.passed()
    elif mode == "delta":
        r.passed() if acp.get("parent_envelope_id") else r.failed("delta without parent_envelope_id")
    else:
        r.failed(f"mode '{mode}'")
    out.append(r)

    r = R("INV-006", "source.agent_type advisory", required=False)
    at = (env.get("source") or {}).get("agent_type")
    if at in {"inventory_agent", "dms", "inventory_tool", "dealer_agent"}:
        r.passed()
    else:
        r.warned(f"agent_type '{at}', expected inventory_agent, dms, inventory_tool or dealer_agent")
    out.append(r)
    return out


def check_unit(env):
    out = []
    unit = (env.get("inventory") or {}).get("unit")
    r = R("UNIT-001", "inventory.unit present")
    if not isinstance(unit, dict):
        out.append(r.failed("Missing inventory.unit"))
        return out
    out.append(r.passed())

    r = R("UNIT-002", "required unit fields present")
    need = ["vin", "stock_number", "status", "condition", "year", "make", "model", "price", "updated_at"]
    missing = [f for f in need if unit.get(f) in (None, "")]
    r.failed("Missing: " + ", ".join(missing)) if missing else r.passed()
    out.append(r)

    vin = str(unit.get("vin") or "").upper()
    r = R("UNIT-003", "VIN is 17 characters without I, O or Q")
    if len(vin) == 17 and all(c in VIN_VALUES for c in vin):
        r.passed()
    else:
        r.failed(f"VIN '{vin}'")
    out.append(r)

    r = R("UNIT-004", "VIN check digit (North American VINs)", required=False)
    if len(vin) != 17 or not all(c in VIN_VALUES for c in vin):
        r.skipped("VIN malformed")
    elif vin[0] not in "12345":
        r.skipped("Not a North American VIN")
    elif vin[8] == vin_check_digit(vin):
        r.passed()
    else:
        r.warned(f"Position 9 is '{vin[8]}', computed '{vin_check_digit(vin)}'")
    out.append(r)

    status = unit.get("status")
    r = R("UNIT-005", "status is a valid enum")
    r.passed() if status in STATUSES else r.failed(f"status '{status}'")
    out.append(r)

    cond = unit.get("condition")
    r = R("UNIT-006", "condition is new, used or cpo")
    r.passed() if cond in CONDITIONS else r.failed(f"condition '{cond}'")
    out.append(r)

    r = R("UNIT-007", "odometer present for used and cpo units")
    if cond in ("used", "cpo"):
        odo = unit.get("odometer")
        r.passed() if isinstance(odo, int) and odo >= 0 else r.failed(f"odometer '{odo}'")
    else:
        r.skipped("new unit")
    out.append(r)

    r = R("UNIT-008", "trim does not pack drivetrain, doors or body style")
    trim = unit.get("trim")
    hit = PACKED.findall(trim or "")
    r.failed(f"trim '{trim}' contains {', '.join(hit)}; use separate fields") if hit else r.passed()
    out.append(r)

    r = R("UNIT-009", "drivetrain is a valid enum when present")
    dt = unit.get("drivetrain")
    if dt is None:
        r.skipped()
    else:
        r.passed() if dt in DRIVETRAINS else r.failed(f"drivetrain '{dt}'")
    out.append(r)

    price = unit.get("price") or {}
    r = R("UNIT-010", "price has currency, advertised and effective_at")
    errs = []
    if not re.fullmatch(r"[A-Z]{3}", str(price.get("currency") or "")):
        errs.append("currency must be ISO 4217")
    if not DECIMAL.match(str(price.get("advertised") or "")):
        errs.append("advertised must be a decimal string")
    if not ts(price.get("effective_at")):
        errs.append("effective_at must be ISO 8601 with offset")
    r.failed("; ".join(errs)) if errs else r.passed()
    out.append(r)

    r = R("UNIT-011", "msrp present for new units")
    if cond == "new":
        r.passed() if DECIMAL.match(str(price.get("msrp") or "")) else r.failed("new unit without a decimal msrp")
    else:
        r.skipped("not new")
    out.append(r)

    r = R("UNIT-012", "updated_at is ISO 8601 with offset")
    r.passed() if ts(unit.get("updated_at")) else r.failed(f"updated_at '{unit.get('updated_at')}'")
    out.append(r)

    r = R("UNIT-013", "live units have photos", required=False)
    if status in LIVE:
        n = (unit.get("media") or {}).get("photo_count") or 0
        r.passed(f"{n} photos") if n > 0 else r.warned("live unit with no photos")
    else:
        r.skipped("unit not live")
    out.append(r)
    return out


def check_integrity(env):
    out = []
    integ = env.get("integrity")
    unit = (env.get("inventory") or {}).get("unit")
    r = R("ATT-001", "integrity block present")
    if not isinstance(integ, dict):
        out.append(r.failed("Missing integrity block"))
        return out
    out.append(r.passed())

    sources = integ.get("sources") or []
    r = R("ATT-002", "sources listed with valid system and observed_at")
    bad = [s for s in sources if s.get("system") not in SOURCE_SYSTEMS or not ts(s.get("observed_at"))]
    if not sources:
        r.failed("No sources")
    elif bad:
        r.failed(f"{len(bad)} source(s) with unknown system or bad observed_at")
    else:
        r.passed(f"{len(sources)} source(s)")
    out.append(r)

    r = R("ATT-003", "at least two sources, oem_build for new units", required=False)
    systems = {s.get("system") for s in sources}
    if len(sources) < 2:
        r.warned("Only one source; nothing to compare against")
    elif isinstance(unit, dict) and unit.get("condition") == "new" and "oem_build" not in systems:
        r.warned("New unit not compared against oem_build")
    else:
        r.passed()
    out.append(r)

    checks = integ.get("checks") or []
    r = R("ATT-004", "checks use registry or X- ids and a valid status")
    bad = [c.get("id") for c in checks
           if not (c.get("id") in CHECK_IDS or str(c.get("id", "")).startswith("X-"))
           or c.get("status") not in ("pass", "fail", "warn")]
    if not checks:
        r.failed("No checks")
    elif bad:
        r.failed(f"Invalid checks: {bad}")
    else:
        r.passed(f"{len(checks)} check(s)")
    out.append(r)

    r = R("ATT-005", "failed and warned checks carry field, expected and observed")
    thin = [c.get("id") for c in checks if c.get("status") != "pass"
            and not (c.get("field") and "expected" in c and isinstance(c.get("observed"), dict))]
    r.failed(f"Missing detail on: {thin}") if thin else r.passed()
    out.append(r)

    att = integ.get("attestation") or {}
    r = R("ATT-006", "attestation has status, record_hash, issued_at, expires_at, issuer")
    errs = []
    if att.get("status") not in ("verified", "conflicted", "unverified"):
        errs.append(f"status '{att.get('status')}'")
    if not HASH.match(str(att.get("record_hash") or "")):
        errs.append("record_hash must be sha256:<64 hex>")
    issued, expires = ts(att.get("issued_at")), ts(att.get("expires_at"))
    if not issued:
        errs.append("issued_at")
    if not expires:
        errs.append("expires_at")
    if issued and expires and expires <= issued:
        errs.append("expires_at must be after issued_at")
    if not att.get("issuer"):
        errs.append("issuer")
    r.failed("; ".join(errs)) if errs else r.passed()
    out.append(r)

    r = R("ATT-007", "record_hash matches canonical hash of inventory.unit")
    if not isinstance(unit, dict):
        r.skipped("no unit")
    else:
        want = record_hash(unit)
        if att.get("record_hash") == want:
            r.passed()
        else:
            r.failed("Hash mismatch; consumers must treat this record as unverified",
                     detail={"attested": att.get("record_hash"), "computed": want})
    out.append(r)

    r = R("ATT-008", "attestation status agrees with check results")
    fails = [c.get("id") for c in checks if c.get("status") == "fail"]
    st = att.get("status")
    if fails and st != "conflicted":
        r.failed(f"Checks failed ({', '.join(fails)}) but status is '{st}'")
    elif st == "conflicted" and not fails:
        r.failed("status is 'conflicted' but no check failed")
    else:
        r.passed()
    out.append(r)

    r = R("ATT-009", "live attestations expire within one hour", required=False)
    if issued and expires and isinstance(unit, dict) and unit.get("status") in LIVE:
        mins = (expires - issued).total_seconds() / 60
        r.passed() if mins <= 60 else r.warned(f"attestation lives {mins:.0f} minutes")
    else:
        r.skipped()
    out.append(r)
    return out


def check_surfaces(env):
    out = []
    surfaces = env.get("surfaces")
    r = R("SURF-001", "surfaces is a list when present")
    if surfaces is None:
        out.append(r.skipped("no surface reports"))
        return out
    if not isinstance(surfaces, list):
        out.append(r.failed("surfaces must be a list"))
        return out
    out.append(r.passed(f"{len(surfaces)} surface(s)"))

    r = R("SURF-002", "each surface has a known type and observed_at")
    bad = [s.get("surface") for s in surfaces
           if not (s.get("surface") in SURFACES or str(s.get("surface", "")).startswith("X-"))
           or not ts(s.get("observed_at"))]
    r.failed(f"Invalid surfaces: {bad}") if bad else r.passed()
    out.append(r)

    r = R("SURF-003", "matches is false exactly when drift is non-empty")
    bad = [s.get("surface") for s in surfaces
           if not isinstance(s.get("matches"), bool) or s.get("matches") == bool(s.get("drift"))]
    r.failed(f"Inconsistent: {bad}") if bad else r.passed()
    out.append(r)

    r = R("SURF-004", "surface drift is reflected in attestation", required=False)
    drifted = [s.get("surface") for s in surfaces if s.get("matches") is False]
    st = ((env.get("integrity") or {}).get("attestation") or {}).get("status")
    if drifted and st == "verified":
        r.warned(f"{', '.join(drifted)} drifted but record is attested verified")
    else:
        r.passed()
    out.append(r)
    return out


def check_events(env):
    out = []
    events = env.get("events")
    r = R("EVT-001", "events is a list of typed, timestamped events")
    if not isinstance(events, list):
        out.append(r.failed("events must be a list"))
        return out
    bad = [e for e in events if not e.get("type") or not ts(e.get("timestamp"))]
    r.failed(f"{len(bad)} event(s) missing type or valid timestamp") if bad else r.passed(f"{len(events)} event(s)")
    out.append(r)

    r = R("EVT-002", "inventory event types are registered or X-")
    bad = [e.get("type") for e in events
           if not (e.get("type") in EVENT_TYPES or str(e.get("type", "")).startswith("X-"))]
    r.failed(f"Unknown types: {bad}") if bad else r.passed()
    out.append(r)

    r = R("EVT-003", "conflicted records carry inventory.integrity.conflict_detected", required=False)
    st = ((env.get("integrity") or {}).get("attestation") or {}).get("status")
    types = {e.get("type") for e in events}
    if st == "conflicted":
        r.passed() if "inventory.integrity.conflict_detected" in types else r.warned("missing conflict_detected event")
    else:
        r.skipped()
    out.append(r)

    r = R("EVT-004", "delta envelopes carry the event that caused them", required=False)
    if (env.get("acp") or {}).get("mode") == "delta":
        r.passed() if events else r.warned("delta with no events")
    else:
        r.skipped()
    out.append(r)
    return out


def run(env):
    results = []
    for fn in (check_envelope, check_unit, check_integrity, check_surfaces, check_events):
        results += fn(env)
    req = [r for r in results if r.required]
    fails = sum(r.status == "FAIL" for r in req)
    summary = {
        "conformant": fails == 0,
        "verdict": "CONFORMANT" if fails == 0 else "NON-CONFORMANT",
        "suite": "acp-inventory-integrity",
        "suite_version": SUITE_VERSION,
        "acp_version": ACP_VERSION,
        "spec": SPEC,
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "required_tests": len(req),
        "required_pass": sum(r.status == "PASS" for r in req),
        "required_fail": fails,
        "required_skipped": sum(r.status == "SKIP" for r in req),
        "advisory_warnings": sum(r.status == "WARN" for r in results if not r.required),
        "attestation_status": ((env.get("integrity") or {}).get("attestation") or {}).get("status"),
    }
    return results, summary


def report(results, s):
    icons = {"PASS": "\033[32m✓", "FAIL": "\033[31m✗", "WARN": "\033[33m⚠", "SKIP": "\033[90m·"}
    print(f"\nACP Inventory Integrity Conformance · draft {SUITE_VERSION} · ACP {ACP_VERSION}\n")
    for r in results:
        tag = "" if r.required else " [advisory]"
        print(f"  {icons[r.status]}\033[0m {r.test_id:<9} {r.name}{tag}")
        if r.message and r.status != "PASS":
            print(f"            {r.message}")
        if r.detail:
            print(f"            {json.dumps(r.detail)}")
    color = "\033[32m" if s["conformant"] else "\033[31m"
    print(f"\n  Verdict: {color}{s['verdict']}\033[0m")
    print(f"  Required: {s['required_pass']}/{s['required_tests']} passed, {s['required_fail']} failed, {s['required_skipped']} not applicable")
    print(f"  Advisory: {s['advisory_warnings']} warning(s)")
    print(f"  Record attestation: {s['attestation_status']}\n")


def main():
    p = argparse.ArgumentParser(description="ACP Inventory Integrity conformance suite")
    p.add_argument("--file", required=True, help="inventory envelope JSON")
    p.add_argument("--report", help="write a JSON report here")
    p.add_argument("--print-hash", action="store_true", help="print the canonical record_hash of inventory.unit and exit")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()

    try:
        with open(a.file, encoding="utf-8") as f:
            env = json.load(f)
    except (OSError, ValueError) as e:
        print(f"Could not load {a.file}: {e}")
        sys.exit(2)

    if a.print_hash:
        unit = (env.get("inventory") or {}).get("unit")
        if not isinstance(unit, dict):
            print("No inventory.unit in file")
            sys.exit(2)
        print(record_hash(unit))
        sys.exit(0)

    results, s = run(env)
    if a.quiet:
        print(s["verdict"])
    else:
        report(results, s)
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump({"summary": s, "tests": [r.to_dict() for r in results]}, f, indent=2)
    sys.exit(0 if s["conformant"] else 1)


if __name__ == "__main__":
    main()
