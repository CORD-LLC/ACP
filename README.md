# ACP — Automotive Commerce Protocol

The open, JSON-native protocol for AI-powered automotive commerce. The successor to ADF-XML, built to model the full transaction lifecycle from first conversation through negotiation, financing, delivery, and post-sale events.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![ACP Version](https://img.shields.io/badge/ACP-v1.1-green.svg)](https://acpspec.org)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)]()

This repository holds the open protocol tooling: the conformance suite any partner can run, and a reference producer that emits a conformant envelope. The full specification, JSON Schema, migration guide, and governance live at [acpspec.org](https://acpspec.org).

## What ACP is

ACP defines the shape of an automotive commerce interaction. Every envelope is a self-contained, versioned document with eight top-level objects: `acp`, `source`, `dealership`, `lead`, `transaction`, `conversation`, `events`, and an optional `ai_analysis`. Envelopes are full snapshots by default, with delta envelopes supported for real-time streaming. ACP v1.1 adds a fleet extension for machine-to-machine service commerce between autonomous vehicle operators and dealer networks.

ACP is vendor-neutral and community-governed. The specification, schema, and the tooling in this repository are Apache 2.0 licensed and free to implement.

## What is in this repository

`conformance_test.py` is the conformance suite. Run it against any system that claims to produce valid ACP envelopes. A conformant implementation must pass every required check.

```bash
# Validate a static envelope file
python conformance_test.py --file my_envelope.json

# Validate output from a live endpoint
python conformance_test.py --url https://your-fleet-agent.example.com --token YOUR_TOKEN

# Emit a machine-readable report
python conformance_test.py --file my_envelope.json --report report.json
```

`demo_vehicle_agent.py` is a reference producer. It builds a conformant ACP v1.1 fleet envelope and, in dry-run mode, validates it through the conformance suite without contacting any server.

```bash
# Print a sample envelope and exit
python demo_vehicle_agent.py --print-envelope

# Build an envelope and check it against the spec, no network
python demo_vehicle_agent.py --dry-run --verbose
```

Both files run on the Python 3.11+ standard library. The demo will use `httpx` for live transmission if it is installed, and falls back to `urllib` otherwise.

## Inventory Integrity extension (draft, ACP v1.2)

A vehicle record changes as it moves from the DMS to the website, the ad catalogs, the marketplaces and the AI agents that now answer shoppers. The Inventory Integrity extension puts the checks in the open protocol instead of inside a vendor. An inventory envelope carries one canonical vehicle record, the sources it was compared against, the checks that ran, and an attestation bound to the exact record by SHA-256 hash. Surface reports say what is actually live on each downstream site and whether it matches.

It also sets one rule for agents: no agent binds an offer to a record that is conflicted, expired or unattested. Two agents from two companies can verify the same hash and know they are negotiating over the same car at the same number.

Spec: [extensions/inventory-integrity.md](extensions/inventory-integrity.md)

```bash
# Check an inventory envelope against the draft
python inventory_conformance.py --file examples/sample_inventory_verified.json

# A price conflict, reported honestly, is still conformant
python inventory_conformance.py --file examples/sample_inventory_conflicted.json

# Print the canonical record_hash of a unit, for producers building attestations
python inventory_conformance.py --file my_envelope.json --print-hash
```

## What is not in this repository

This repository contains the protocol and its conformance tooling only. It does not contain an enforcement or orchestration engine. How a receiving system resolves identity, enforces consent, scores leads, routes to a CRM, or prices fleet work is an implementation concern, outside the scope of the open protocol. Producing a conformant envelope is all ACP asks of an implementation.

## Adoption

ACP is designed for incremental adoption alongside existing ADF-XML workflows. The recommended path is dual output first, then ACP primary with ADF-XML as fallback, then ACP only with a deterministic converter retained for backward compatibility. See the migration guide at [acpspec.org/migration](https://acpspec.org/migration).

## Built on CORD

ACP uses the [CORD protocol](https://cordspec.org) as its translation and loss-quantification layer. When ACP envelopes are transmitted to legacy CRM and DMS systems, CORD measures what information is lost in the conversion.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Maintained by

AutomotiveAI, a division of The Carman Auto Group. Specification and governance at [acpspec.org](https://acpspec.org).
