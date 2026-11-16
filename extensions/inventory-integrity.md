# ACP Inventory Integrity Extension

Status: Draft 0.1, proposed for ACP v1.2.0
License: Apache 2.0

## Why this exists

A vehicle record passes through the DMS, the inventory tool, the dealer website, listing sites, ad catalogs, OEM programs and AI agents. Every handoff can drop a field, truncate a trim or serve yesterday's price. The result is one truck with three prices.

Fixing that inside a private middle layer moves the problem instead of solving it. The checks, the canonical record and the proof that a record was checked should be part of the open protocol, so any producer can emit them and any consumer can verify them without trusting a single vendor.

This extension adds three things to ACP:

1. An `inventory` envelope that carries one vehicle as a canonical record.
2. An `integrity` block that says which sources were compared, which checks ran, and an attestation bound to the exact record by hash.
3. A `surfaces` block that reports what is actually live on each downstream surface and whether it matches.

It also adds one rule for agents: no agent binds an offer to a record that is conflicted, stale or unattested. See [Agent quoting rule](#agent-quoting-rule).

## Keywords

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **NOT RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted as described in BCP 14 [RFC2119] [RFC8174] when, and only when, they appear in all capitals, as shown here.

**References**

- [RFC2119] Bradner, S., "Key words for use in RFCs to Indicate Requirement Levels", BCP 14, RFC 2119, March 1997.
- [RFC8174] Leiba, B., "Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words", BCP 14, RFC 8174, May 2017.

## Envelope shape

An inventory envelope is an ACP envelope with `acp.version` of `1.2.0` and an `inventory` block. The `inventory` block is mutually exclusive with `lead` and `fleet`. An envelope MUST NOT carry more than one of the three.

```json
{
  "acp": { "version": "1.2.0", "protocol": "acp", "generated_at": "...", "envelope_id": "acp_...", "parent_envelope_id": null, "mode": "snapshot" },
  "source": { "provider": "...", "agent_type": "inventory_agent", "channel": "inventory_feed" },
  "dealership": { "id": "...", "name": "...", "dms_provider": "..." },
  "inventory": { "unit": { }, "cord": { } },
  "integrity": { "sources": [ ], "checks": [ ], "attestation": { } },
  "surfaces": [ ],
  "events": [ ]
}
```

`acp.mode` is `snapshot` or `delta`. A delta is a change notification: it sets `parent_envelope_id` to the envelope it supersedes and carries the event that caused the change. Both modes carry the complete `unit`, so every envelope can be verified on its own. A unit record is small; a partial record that cannot be checked is not worth the bytes saved.

`source.agent_type` SHOULD be `inventory_agent`, `dms`, `inventory_tool` or `dealer_agent`.

## The unit

`inventory.unit` is the canonical record for one vehicle at one rooftop.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `vin` | string | yes | 17 characters, no I, O or Q |
| `stock_number` | string | yes | The dealer's stock number |
| `status` | enum | yes | `in_transit`, `in_stock`, `pending_sale`, `sold`, `wholesale`, `removed` |
| `condition` | enum | yes | `new`, `used`, `cpo` |
| `year`, `make`, `model` | int, string, string | yes | |
| `trim` | string | no | Trim only. Drivetrain, body and doors go in their own fields |
| `drivetrain` | enum | no | `fwd`, `rwd`, `awd`, `4wd` |
| `body_style` | string | no | |
| `doors` | int | no | |
| `exterior_color`, `interior_color` | string | no | |
| `odometer` | int | no | Miles. Required when `condition` is `used` or `cpo` |
| `price` | object | yes | See below |
| `media` | object | no | `photo_count`, `photo_urls[]`, `video_url` |
| `updated_at` | ISO 8601 | yes | When this record last changed at the source of truth |

`price` holds the numbers a shopper or an agent may act on. All amounts are decimal strings in the stated currency.

| Field | Required | Notes |
| --- | --- | --- |
| `currency` | yes | ISO 4217, for example `USD` |
| `advertised` | yes | The price shown to shoppers. Every surface MUST show this number |
| `msrp` | no | Required when `condition` is `new` |
| `effective_at` | yes | When `advertised` took effect |
| `incentives` | no | List of `{ program_id, amount, expires_at }` that make up the gap between MSRP and advertised |

Splitting packed strings is a requirement, not a nicety. A producer MUST NOT put drivetrain, doors or body style inside `trim` (for example `AWD 4DR LTD`). Consumers that need a packed string can build it; consumers that need fields cannot reliably unpack one.

## CORD binding

`inventory.cord` links the unit to its CORD canonical object.

```json
"cord": { "object_type": "vehicle", "object_id": "cord_veh_...", "version": 7 }
```

When ACP is translated into a legacy feed, CORD measures what was lost. The integrity block below measures whether what was kept is still true.

## Integrity

### Sources

`integrity.sources` lists every system the producer compared for this VIN.

```json
{ "system": "dms", "provider": "dealer_center", "observed_at": "...", "record_hash": "sha256:..." }
```

`system` is one of `dms`, `inventory_tool`, `oem_build`, `oem_incentives`, `dealer_website`, `marketplace`, `manual`. A producer SHOULD include at least two sources, one of them `oem_build` for new units.

### Checks

`integrity.checks` lists the checks that ran. Each check has an `id` from the registry below, a `status` of `pass`, `fail` or `warn`, and, when it did not pass, the `field`, the `expected` value and the `observed` values by source.

```json
{ "id": "INT-PRICE-CONSISTENT", "status": "fail", "field": "price.advertised",
  "expected": "48995.00", "observed": { "dms": "48995.00", "marketplace": "49995.00" } }
```

### Check registry

| ID | What it checks | Fails when |
| --- | --- | --- |
| `INT-VIN-VALID` | VIN format and, for North American VINs, the position 9 check digit | Length, characters or check digit are wrong |
| `INT-BUILD-MATCH` | Year, make, model, trim and drivetrain against OEM build data | Any field disagrees with the build |
| `INT-PRICE-CONSISTENT` | `price.advertised` across every source that carries a price | Two sources disagree |
| `INT-STATUS-CONSISTENT` | Status across sources | A unit is `sold` or `removed` in one source and live in another |
| `INT-PRICE-FRESH` | Age of the price relative to the source of truth | A downstream copy predates `price.effective_at` |
| `INT-MEDIA-PRESENT` | Photos on live units | A live unit has zero photos |
| `INT-INCENTIVE-VALID` | Every listed incentive against OEM incentive data | An incentive is expired or unknown |

Implementations MAY add checks. Custom check IDs MUST start with `X-` followed by the producer's name, for example `X-ACME-CARFAX-MATCH`.

### Attestation

The attestation is the part a consumer can verify without trusting the producer's word.

```json
"attestation": {
  "status": "verified",
  "record_hash": "sha256:9f2c...",
  "issued_at": "2026-11-03T17:00:00Z",
  "expires_at": "2026-11-03T18:00:00Z",
  "issuer": "dealer_costa_mesa_001",
  "signature": null
}
```

- `status` is `verified` (every required check passed), `conflicted` (at least one check failed) or `unverified` (checks were not run or could not complete).
- `record_hash` is `sha256:` followed by the lowercase hex SHA-256 of `inventory.unit` serialized as canonical JSON: keys sorted, no insignificant whitespace, UTF-8. A consumer MUST recompute it and MUST treat the attestation as `unverified` if it does not match.
- `expires_at` MUST be set. An attestation is a claim about a moment. A producer SHOULD keep attestations short lived (one hour or less for units in `in_stock`).
- `status` MUST be `conflicted` if any check in `checks` has status `fail`.
- `signature` MAY carry a detached JWS over `record_hash` and `issued_at` by the issuer. Signature format is reserved for a later draft and is `null` in 0.1.

## Surfaces

`surfaces` reports what is live where, observed separately from any feed.

```json
{ "surface": "dealer_website", "url": "https://...", "observed_at": "...",
  "observed": { "status": "in_stock", "advertised": "49995.00" },
  "matches": false, "drift": ["price.advertised"] }
```

`surface` is one of `dealer_website`, `marketplace`, `meta_catalog`, `google_vehicle_ads`, `oem_locator`, `ai_agent`, or an `X-` custom value. `matches` MUST be `false` whenever `drift` is non-empty, and `true` only when `drift` is empty.

Google's vehicle ads policy expects the landing page price to match the feed. Surface reports give a dealer proof of that per unit instead of a guess.

## Events

Inventory envelopes use these event types. Deltas SHOULD carry the event that caused them.

| Type | When |
| --- | --- |
| `inventory.unit.created` | A new unit enters inventory |
| `inventory.unit.updated` | Any field changed. `data.fields` lists them |
| `inventory.unit.price_changed` | `price.advertised` changed. `data.from`, `data.to` |
| `inventory.unit.status_changed` | `status` changed. `data.from`, `data.to` |
| `inventory.unit.sold` | Status moved to `sold` |
| `inventory.integrity.verified` | An attestation was issued with status `verified` |
| `inventory.integrity.conflict_detected` | A check failed. `data.check_ids` |
| `inventory.surface.drift_detected` | A surface no longer matches. `data.surface`, `data.drift` |
| `inventory.surface.reconciled` | A surface was corrected and now matches |

Price and status changes SHOULD be pushed as delta envelopes when they happen, not held for the next batch file. A unit that sells at 10 a.m. should not be advertised at noon.

## Agent quoting rule

This is the part a feed tool cannot give you, and the reason the checks belong in the protocol.

When an agent quotes a price, presents a unit as available or binds an offer in an ACP `transaction` or `conversation`, it MUST reference the attestation it relied on:

```json
"vehicle_ref": { "vin": "...", "envelope_id": "acp_...", "record_hash": "sha256:..." }
```

The agent MUST NOT bind an offer (a firm price, a deposit, a signed term) against a record whose attestation is `conflicted`, `unverified`, expired, or whose `record_hash` does not match the unit. It MAY still talk about the unit, and it SHOULD tell the shopper or the counterparty agent that the number is being confirmed.

A counterparty agent that receives a `vehicle_ref` MAY fetch the inventory envelope and verify the hash itself. Two agents from two companies can then agree on what car and what number they are negotiating over without either one trusting the other's database.

## Conformance

`inventory_conformance.py` in this repository checks an inventory envelope against this draft. A producer claiming support MUST pass every required check. Run:

```bash
python inventory_conformance.py --file examples/sample_inventory_verified.json
```

## Open questions for 0.2

- Signature format for attestations (JWS with dealer or vendor keys, and how keys are published).
- Whether `surfaces` should allow third-party observers to publish reports about a dealer they do not represent.
- Mapping to the STAR vehicle inventory BOD, so STAR members can carry the same attestation.
