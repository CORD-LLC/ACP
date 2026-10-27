#!/usr/bin/env python3
"""
ACP v1.1 Fleet Commerce Extension — Vehicle Agent Demo

Simulates the complete machine-to-machine commerce loop:

  Vehicle detects brake wear
       ↓
  ACP fleet envelope generated
       ↓
  Protocol enforcement layer validates
       ↓
  Dealer service system acknowledges
       ↓
  Appointment confirmed → RO opened
       ↓
  Confirmation delta returned to vehicle agent
       ↓
  Invoice closed
       ↓
  Vehicle returned to fleet rotation

Run against a live server:
    python demo_vehicle_agent.py --url http://localhost:8000 --token YOUR_TOKEN

Run in dry-run mode (validates envelope only, no HTTP):
    python demo_vehicle_agent.py --dry-run

This is the demo you show Waymo, STAR, and JP Morgan.
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── Try to use httpx if available, fall back to urllib ────────────────────────
try:
    import httpx
    _USE_HTTPX = True
except ImportError:
    import urllib.request
    import urllib.error
    _USE_HTTPX = False

# ── Add parent to path for imports ───────────────────────────────────────────
sys.path.insert(0, ".")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _now().isoformat()


def _envelope_id() -> str:
    ts = int(_now().timestamp())
    rand = uuid.uuid4().hex[:6]
    return f"acp_{ts}_{rand}"


def _sr_id() -> str:
    ts = int(_now().timestamp())
    rand = uuid.uuid4().hex[:4]
    return f"sr_{ts}_{rand}"


# ── Build the fleet envelope ──────────────────────────────────────────────────

def build_fleet_envelope(
    vin: str = "SALYB2EX3LA123456",
    operator_id: str = "waymo_fleet_west_001",
    dealer_id: str = "dealer_costa_mesa_001",
    pricing_agreement_id: str = None,
    severity: str = "predictive",
) -> dict:
    """
    Builds a valid ACP v1.1 fleet snapshot envelope.
    This is what a Waymo vehicle agent generates automatically.
    """
    sr_id = _sr_id()
    window_start = (_now() + timedelta(days=3)).isoformat()
    window_end = (_now() + timedelta(days=5)).isoformat()

    envelope = {
        "acp": {
            "version": "1.1.0",
            "protocol": "acp",
            "generated_at": _ts(),
            "envelope_id": _envelope_id(),
            "parent_envelope_id": None,
        },
        "source": {
            "provider": "AutomotiveAI",
            "agent_type": "vehicle_agent",
            "channel": "telematics",
            "session_id": f"vtl_{operator_id}_{vin[-6:]}_{_now().strftime('%Y%m%d')}",
        },
        "dealership": {
            "id": dealer_id,
            "name": "Pacific Jaguar Land Rover",
            "dms_provider": "dealer_center",
            "timezone": "America/Los_Angeles",
        },
        "fleet": {
            "operator_id": operator_id,
            "operator_name": "Waymo LLC",
            "contract_tier": "enterprise",
            "dispatch_priority": "normal",
            "vehicle": {
                "vin": vin,
                "year": 2023,
                "make": "Jaguar",
                "model": "I-PACE",
                "odometer": 48247,
                "telematics_source": "waymo_os_v4.2",
                "autonomous_level": 4,
                "fleet_unit_id": "WM-LA-0047",
            },
            "health": {
                "severity": severity,
                "health_score": 71,
                "dtc_codes": [],
                "systems_flagged": ["brake_pads_rear", "cabin_air_filter"],
                "predicted_failure_window_days": 12,
                "last_service_date": "2025-10-14",
            },
        },
        "service_request": {
            "id": sr_id,
            "type": "predictive_maintenance",
            "stage": "dispatched",
            "initiated_by": "vehicle_agent",
            "last_updated": _ts(),
            "loaner_required": False,
            "estimated_downtime_hours": 3.5,
            "work_items": [
                {
                    "op_code": "BRK-PAD-REAR-IPACE",
                    "description": "Rear brake pad replacement",
                    "labor_hours": "1.5",
                    "parts_required": True,
                    "warranty_eligible": False,
                },
                {
                    "op_code": "FILTER-CABIN-IPACE",
                    "description": "Cabin air filter replacement",
                    "labor_hours": "0.5",
                    "parts_required": True,
                    "warranty_eligible": False,
                },
            ],
            "appointment": {
                "status": "pending",
                "requested_window_start": window_start,
                "requested_window_end": window_end,
                "scheduled_at": None,
                "bay_assigned": None,
                "drop_off_method": "self_driving",
            },
            "invoice": {
                "status": "not_started",
                "fleet_adjusted_total": None,
                "closed_at": None,
            },
        },
        "events": [
            {
                "type": "fleet.health.detected",
                "timestamp": _ts(),
                "data": {
                    "systems": ["brake_pads_rear", "cabin_air_filter"],
                    "severity": severity,
                    "health_score_at_detection": 71,
                },
            },
            {
                "type": "fleet.service_request.initiated",
                "timestamp": _ts(),
                "data": {
                    "service_request_id": sr_id,
                    "initiated_by": "vehicle_agent",
                    "operator_id": operator_id,
                },
            },
        ],
    }

    if pricing_agreement_id:
        envelope["service_request"]["fleet_pricing_agreement_id"] = pricing_agreement_id

    return envelope


# ── Validate locally (dry run) ────────────────────────────────────────────────

def dry_run(envelope: dict, verbose: bool = False):
    """Validate the envelope against the published ACP spec using the open
    conformance suite (conformance_test.py), without hitting any server.

    This keeps the reference producer fully standalone: it depends only on the
    public ACP conformance tooling, never on a private enforcement engine.
    """
    import subprocess
    import tempfile

    here = os.path.dirname(os.path.abspath(__file__))
    suite = os.path.join(here, "conformance_test.py")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(envelope, fh, default=str)
        envelope_path = fh.name

    print("\n" + "=" * 60)
    print("  ACP v1.1 FLEET ENVELOPE — CONFORMANCE CHECK")
    print("=" * 60)
    print(f"  Envelope ID  : {envelope.get('acp', {}).get('envelope_id')}")
    print(f"  VIN          : {envelope.get('fleet', {}).get('vehicle', {}).get('vin')}")
    print(f"  SR ID        : {envelope.get('service_request', {}).get('id')}")
    print()

    proc = subprocess.run(
        [sys.executable, suite, "--file", envelope_path],
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr)

    if verbose:
        print("\nFull envelope JSON:")
        print(json.dumps(envelope, indent=2, default=str))

    print("=" * 60)
    return proc.returncode == 0


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _post(url: str, data: dict, token: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = json.dumps(data, default=str).encode()

    if _USE_HTTPX:
        resp = httpx.post(url, content=body, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    else:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())


# ── Full live demo ────────────────────────────────────────────────────────────

def run_live_demo(
    base_url: str,
    token: str,
    vin: str,
    operator_id: str,
    dealer_id: str,
    pricing_agreement_id: str,
    verbose: bool,
):
    print("\n" + "="*60)
    print("  ACP v1.1 FLEET COMMERCE — LIVE DEMO")
    print("  Machine-initiated service loop")
    print("="*60)

    # ── Step 1: Vehicle fires service request ─────────────────────────────────
    print("\n[1/5] Vehicle agent generating fleet envelope...")
    envelope = build_fleet_envelope(
        vin=vin,
        operator_id=operator_id,
        dealer_id=dealer_id,
        pricing_agreement_id=pricing_agreement_id,
    )
    parent_envelope_id = envelope["acp"]["envelope_id"]
    sr_id = envelope["service_request"]["id"]

    print(f"      Envelope ID : {parent_envelope_id}")
    print(f"      VIN         : {vin}")
    print(f"      SR ID       : {sr_id}")
    print(f"      Work items  : {len(envelope['service_request']['work_items'])}")

    print("\n[2/5] Transmitting to dealer protocol enforcement layer...")
    try:
        ack = _post(f"{base_url}/api/v1/fleet/service-request", envelope, token)
        print(f"      ✓ Acknowledged: {ack.get('acknowledged')}")
        print(f"      Stage         : {ack.get('stage')}")
        print(f"      Severity      : {ack.get('severity')}")
        if ack.get("pricing"):
            p = ack["pricing"]
            print(f"      Fleet pricing applied:")
            print(f"        Labor  : ${p.get('labor_total')}")
            print(f"        Parts  : ${p.get('parts_total')}")
            print(f"        Total  : ${p.get('fleet_adjusted_total')}")
        if ack.get("warnings"):
            for w in ack["warnings"]:
                print(f"      ⚠ {w}")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        return False

    # ── Step 2: Dealer confirms appointment ───────────────────────────────────
    print("\n[3/5] Dealer confirming appointment and opening RO...")
    scheduled_at = (_now() + timedelta(days=4)).replace(hour=9, minute=0, second=0)
    ro_number = f"RO-{_now().strftime('%Y')}-{uuid.uuid4().hex[:5].upper()}"

    confirm_payload = {
        "service_request_id": sr_id,
        "parent_envelope_id": parent_envelope_id,
        "scheduled_at": scheduled_at.isoformat(),
        "bay_assigned": "BAY-4",
        "ro_number": ro_number,
        "vin": vin,
        "operator_id": operator_id,
        "dms_provider": "dealer_center",
    }

    try:
        delta = _post(f"{base_url}/api/v1/fleet/confirm-appointment", confirm_payload, token)
        delta_id = delta.get("acp", {}).get("envelope_id", "unknown")
        print(f"      ✓ Confirmation delta   : {delta_id}")
        print(f"        Parent envelope      : {parent_envelope_id}")
        print(f"        Scheduled at         : {scheduled_at.strftime('%Y-%m-%d %H:%M %Z')}")
        print(f"        Bay                  : BAY-4")
        print(f"        RO Number            : {ro_number}")
        print(f"        Events in delta      : {len(delta.get('events', []))}")
        if verbose:
            print(f"\n      Confirmation delta:")
            print(json.dumps(delta, indent=6, default=str))
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        return False

    # ── Step 3: Invoice closed ────────────────────────────────────────────────
    print("\n[4/5] Closing invoice...")
    invoice_payload = {
        "service_request_id": sr_id,
        "parent_envelope_id": delta_id,
        "vin": vin,
        "operator_id": operator_id,
        "ro_number": ro_number,
        "fleet_adjusted_total": "220.50",
        "warranty_covered": "0.00",
    }

    try:
        inv_delta = _post(f"{base_url}/api/v1/fleet/close-invoice", invoice_payload, token)
        print(f"      ✓ Invoice delta : {inv_delta.get('acp', {}).get('envelope_id')}")
        print(f"        Total         : $220.50")
        print(f"        Status        : invoiced")
    except Exception as e:
        print(f"      ✗ Failed: {e}")
        return False

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n[5/5] Loop complete.")
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │  MACHINE-TO-MACHINE COMMERCE LOOP COMPLETED     │")
    print("  │                                                  │")
    print(f"  │  VIN       : {vin:<36}│")
    print(f"  │  Operator  : {operator_id:<36}│")
    print(f"  │  RO        : {ro_number:<36}│")
    print(f"  │  Total     : $220.50{'':<34}│")
    print("  │                                                  │")
    print("  │  Zero human touchpoints.                         │")
    print("  └─────────────────────────────────────────────────┘")
    print()
    print("="*60)
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ACP v1.1 Fleet Vehicle Agent Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — validate envelope locally, no server needed
  python demo_vehicle_agent.py --dry-run

  # Live demo against local server
  python demo_vehicle_agent.py --url http://localhost:8000 --token mytoken

  # Custom VIN and operator
  python demo_vehicle_agent.py --dry-run --vin SALYB2EX3LA999999 --operator waymo_sf_001

  # With fleet pricing agreement
  python demo_vehicle_agent.py --url http://localhost:8000 --token mytoken \\
      --pricing-agreement fpa_waymo_socal_2026
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate envelope locally, no HTTP")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of the server")
    parser.add_argument("--token", default="dev_token", help="Bearer token")
    parser.add_argument("--vin", default="SALYB2EX3LA123456", help="Vehicle VIN")
    parser.add_argument("--operator", default="waymo_fleet_west_001", help="Fleet operator ID")
    parser.add_argument("--dealer", default="dealer_costa_mesa_001", help="Dealer ID")
    parser.add_argument("--pricing-agreement", default=None, help="Fleet pricing agreement ID")
    parser.add_argument("--severity", default="predictive",
                        choices=["immediate", "scheduled", "predictive", "recall"],
                        help="Health severity level")
    parser.add_argument("--verbose", action="store_true", help="Print full envelope JSON")
    parser.add_argument("--print-envelope", action="store_true", help="Print envelope and exit")

    args = parser.parse_args()

    if args.print_envelope:
        envelope = build_fleet_envelope(
            vin=args.vin,
            operator_id=args.operator,
            dealer_id=args.dealer,
            pricing_agreement_id=args.pricing_agreement,
            severity=args.severity,
        )
        print(json.dumps(envelope, indent=2, default=str))
        sys.exit(0)

    if args.dry_run:
        envelope = build_fleet_envelope(
            vin=args.vin,
            operator_id=args.operator,
            dealer_id=args.dealer,
            pricing_agreement_id=args.pricing_agreement,
            severity=args.severity,
        )
        ok = dry_run(envelope, verbose=args.verbose)
        sys.exit(0 if ok else 1)

    ok = run_live_demo(
        base_url=args.url,
        token=args.token,
        vin=args.vin,
        operator_id=args.operator,
        dealer_id=args.dealer,
        pricing_agreement_id=args.pricing_agreement or "",
        verbose=args.verbose,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
