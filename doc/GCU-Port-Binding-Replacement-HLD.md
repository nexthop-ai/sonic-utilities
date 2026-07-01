# GCU Port-Binding Replacement without Admin Down/Up — High Level Design

## Table of Contents
- [Revision](#revision)
- [Scope](#scope)
- [Definitions / Abbreviations](#definitions--abbreviations)
- [1. Overview](#1-overview)
- [2. Problem Statement](#2-problem-statement)
- [3. Background: How GCU Decides the Admin Down/Up](#3-background-how-gcu-decides-the-admin-downup)
- [4. Requirements](#4-requirements)
- [5. High-Level Design](#5-high-level-design)
  - [5.1 Design Principles](#51-design-principles)
  - [5.2 Architecture](#52-architecture)
  - [5.3 ASIC Resolution](#53-asic-resolution)
  - [5.4 Configuration Schema](#54-configuration-schema)
  - [5.5 Table Registry](#55-table-registry)
  - [5.6 Pattern-Building Algorithm](#56-pattern-building-algorithm)
- [6. Detailed Behavior & Examples](#6-detailed-behavior--examples)
- [7. Configuration Examples](#7-configuration-examples)
- [8. Backward Compatibility](#8-backward-compatibility)
- [9. Failure Handling & Safety](#9-failure-handling--safety)
- [10. Testing](#10-testing)
- [11. Limitations & Future Work](#11-limitations--future-work)

## Revision

| Rev | Date       | Author | Change Description           |
|-----|------------|--------|------------------------------|
| 0.1 | 2026-06-20 | Nexthop | Initial version (per-HWSKU keying) |
| 0.2 | 2026-06-24 | Nexthop | Switch keying from HWSKU to ASIC (reuse `get_asic_name`) |

## Scope

This document describes the design of a per-ASIC, per-table mechanism in the
**Generic Config Updater (GCU)** that allows selected **port-binding** fields to be
changed *in place* during `config apply-patch` **without** automatically bouncing the
port (admin down → change → admin up).

The change is confined to the GCU `patch_sorter` and its configuration file in
`sonic-utilities`. It does not change the GCU public CLI, the patch format, or any
other SONiC component.

## Definitions / Abbreviations

| Term | Meaning |
|------|---------|
| GCU | Generic Config Updater — applies a JSON Patch to ConfigDB safely |
| HLD | High Level Design |
| ASIC shorthand | Short ASIC family identifier resolved by `get_asic_name()` (e.g. `th5`, `q3d`, `spc4`, `td3`, `cisco-8000`) |
| HWSKU | Hardware SKU (`DEVICE_METADATA.localhost.hwsku`) — used only as an input to ASIC resolution |
| Port binding | A config object that binds a port (or port\|index) to a referenced object — e.g. a QoS map, a buffer profile, a scheduler |
| Admin bounce | The sequence: set `PORT/<port>/admin_status=down` → apply change → restore `admin_status=up` |
| Requiring config | Config whose change requires another field to hold a specific value |
| Required config | The field that must hold a specific value (here `PORT/<port>/admin_status=down`) |

## 1. Overview

When `config apply-patch` modifies certain port-related QoS/buffer bindings, GCU
automatically inserts moves to take the port **admin down** before the change and
**admin up** afterwards. This guarantees minimum disruption on platforms where the
underlying SAI cannot reprogram those bindings while the port is carrying traffic.

On some ASICs, specific bindings (e.g. `dscp_to_tc_map`) *can* be rebound in place
with no disruption, so the forced admin bounce is unnecessary and itself causes an
avoidable traffic hit.

This design makes the admin-bounce requirement **data-driven and per-ASIC**: an
operator can declare, per ASIC and per table, exactly which binding fields are safe to
change in place. Everything not declared keeps the existing conservative behavior.
ASIC is the natural key because in-place rebind capability is a property of the
ASIC/SAI, not of the HWSKU (which mostly encodes port breakout).

## 2. Problem Statement

Consider a patch that only changes one QoS binding:

```json
[{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet0/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
```

GCU expands this into **three** changes and bounces the port:

```
Patch Applier: The localhost patch was converted into 3 changes:
  * [{"op": "replace", "path": "/PORT/Ethernet0/admin_status", "value": "down"}]
  * [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet0/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
  * [{"op": "replace", "path": "/PORT/Ethernet0/admin_status", "value": "up"}]
```

On an ASIC where `dscp_to_tc_map` rebind is hitless, the down/up is pure, avoidable
disruption. The previous behavior was hard-coded for **all** ports and **all**
platforms, with no way to opt out for a specific binding on a specific ASIC.

## 3. Background: How GCU Decides the Admin Down/Up

The admin bounce is **not** part of the user's patch. It is synthesized by the GCU
patch sorter, driven by the `RequiredValueIdentifier` class in
[`generic_config_updater/patch_sorter.py`](../generic_config_updater/patch_sorter.py).

`RequiredValueIdentifier` declares a rule:

> Any change under a *requiring* table for a port requires the *required* field
> `PORT/<port>/admin_status` to equal `down`.

The "requiring" tables historically were (hard-coded):
`BUFFER_PG`, `BUFFER_PORT_INGRESS_PROFILE_LIST`, `BUFFER_PORT_EGRESS_PROFILE_LIST`,
`BUFFER_QUEUE`, `PORT_QOS_MAP`, `QUEUE`.

The sorter then uses two collaborators:
- `RequiredValueMoveExtender` — generates the `admin_status=down` move before the
  requiring change and keeps the port down until all requiring changes are applied
  (then restores `up`).
- `RequiredValueMoveValidator` — enforces the ordering (rejects changing the binding
  while the port is up, and rejects bringing the port up while requiring changes
  remain).

Matching is done via `JsonPointerFilter`, which supports patterns of arbitrary depth:
- `["PORT_QOS_MAP", "@"]` matches the **whole entry** `/PORT_QOS_MAP/Ethernet0`
  (any field change triggers the bounce). `@` is the common key (the port).
- `["PORT_QOS_MAP", "@", "dscp_to_tc_map"]` matches a **single field**
  `/PORT_QOS_MAP/Ethernet0/dscp_to_tc_map`.

This depth flexibility is the key enabler: by matching at field granularity and
*omitting* the safe fields, the bounce can be skipped for just those fields.

## 4. Requirements

1. **Per-ASIC control** — different ASICs can make different decisions, since the
   capability is an ASIC/SAI property.
2. **Per-table, per-field control** — exempt an arbitrary subset of fields within any
   port-binding table, not just one hard-coded table/field.
3. **Generic / extensible** — supporting a new table or field should not require
   re-architecting; ideally it is a pure configuration change.
4. **Reuse existing ASIC detection** — use the same `get_asic_name()` resolver and
   ASIC→HWSKU maps already used by `rdma_config_update_validator`.
5. **Safe by default** — anything not explicitly declared safe must keep the existing
   conservative admin-bounce behavior.
6. **No regression** — with no configuration entries, behavior is byte-for-byte
   identical to the original.
7. **Robust** — failure to determine the ASIC or read the config must fall back to the
   conservative behavior, never crash a patch apply.

## 5. High-Level Design

### 5.1 Design Principles

- **Data over code.** The set of exempt (ASIC, table, field) tuples lives in a JSON
  config file, not in Python. Day-to-day changes are config-only.
- **ASIC as the key.** In-place rebind support is a hardware/SAI capability, so the
  decision is keyed on the ASIC family rather than the HWSKU. One entry covers every
  HWSKU on that ASIC.
- **Table described once.** Each port-binding table is described a single time in a
  registry (its key pattern + its bindable fields). The bounce-decision logic is
  generic over this registry.
- **Conservative fallback at every layer.** Unknown/unresolved ASIC, missing file,
  missing section, unmatched ASIC, or unlisted table/field → conservative whole-entry
  bounce.

### 5.2 Architecture

```
 config apply-patch
        │
        ▼
 ┌─────────────────────────┐
 │   GCU patch_sorter      │
 │                         │
 │  RequiredValueIdentifier│────► resolve ASIC  (get_asic_name)
 │   • PORT_BINDING_TABLES │         asic_type + HWSKU + *_asics maps
 │   • _build_requiring_   │────► read exemptions
 │       patterns(asic)    │         gcu_field_operation_validators.conf.json
 │            │            │         helper_data.port_binding_replacement
 │            ▼            │
 │     requiring_patterns  │
 │            │            │
 │   ┌────────┴─────────┐  │
 │   ▼                  ▼  │
 │ MoveExtender   MoveValidator
 │ (insert down/up) (enforce order)
 └─────────────────────────┘
        │
        ▼
   sorted changes (with or without admin bounce, per config)
```

At construction, `RequiredValueIdentifier`:
1. Resolves the ASIC (injectable for tests; otherwise `get_asic_name()`).
2. Loads the per-ASIC exemptions from the config file.
3. Builds `requiring_patterns` from the table registry, dropping/expanding patterns
   based on the exemptions.

### 5.3 ASIC Resolution

The ASIC shorthand is resolved by `get_asic_name()` in
[`generic_config_updater/field_operation_validators.py`](../generic_config_updater/field_operation_validators.py),
the same function used by `rdma_config_update_validator`. It derives the ASIC from
`DEVICE_METADATA.localhost.asic_type` plus the HWSKU, using the ASIC→HWSKU lists under
`helper_data.rdma_config_update_validator.{mellanox_asics, broadcom_asics}` in the
same conf file (e.g. `th5`, `q3d`, `spc4`, `td3`, `cisco-8000`, `marvell-teralynx`).

`RequiredValueIdentifier` imports it lazily (function-scope) to avoid any import
cycle, and treats a return of `"unknown"` — or any exception — as "no exemptions"
(conservative).

### 5.4 Configuration Schema

Location:
[`generic_config_updater/gcu_field_operation_validators.conf.json`](../generic_config_updater/gcu_field_operation_validators.conf.json)
under `helper_data.port_binding_replacement.no_admin_down_fields`.

```json
"port_binding_replacement": {
    "no_admin_down_fields": {
        "<ASIC>": {
            "<TABLE>": [ "<field>", "<field>", ... ],
            ...
        },
        "default": {
            "<TABLE>": [ "<field>", ... ]
        }
    }
}
```

Semantics:
- Maps **ASIC shorthand → { table → [exempt fields] }**.
- The ASIC shorthand is exactly the value `get_asic_name()` returns (the same keys
  used under `rdma_config_update_validator`).
- A field listed for an (ASIC, table) is changed **in place** (no bounce).
- Any field **not** listed for that (ASIC, table) still bounces the port.
- A table **not listed** at all bounces the port for any change (conservative).
- The optional `"default"` key applies to every ASIC not listed explicitly.
- ASIC, table, and field matching are all **case-insensitive**.

### 5.5 Table Registry

In `patch_sorter.py`, `RequiredValueIdentifier.PORT_BINDING_TABLES` describes each
supported table once:

```python
PORT_BINDING_TABLES = [
    {"key_pattern": ["BUFFER_PG", "@|*"], "fields": ["profile"]},
    {"key_pattern": ["BUFFER_PORT_EGRESS_PROFILE_LIST", "@"], "fields": ["profile_list"]},
    {"key_pattern": ["BUFFER_PORT_INGRESS_PROFILE_LIST", "@"], "fields": ["profile_list"]},
    {"key_pattern": ["BUFFER_QUEUE", "@|*"], "fields": ["profile"]},
    {"key_pattern": ["PORT_QOS_MAP", "@"], "fields": [ ...11 maps... ]},
    {"key_pattern": ["QUEUE", "@|*"], "fields": ["scheduler", "wred_profile"]},
]
```

| Table | Key pattern | Bindable fields (per YANG) |
|-------|-------------|----------------------------|
| `PORT_QOS_MAP` | `["PORT_QOS_MAP", "@"]` | `dscp_to_tc_map, dot1p_to_tc_map, tc_to_queue_map, tc_to_pg_map, pfc_enable, pfcwd_sw_enable, pfc_to_queue_map, pfc_to_pg_map, tc_to_dscp_map, tc_to_dot1p_map, scheduler` |
| `BUFFER_PG` | `["BUFFER_PG", "@\|*"]` | `profile` |
| `BUFFER_QUEUE` | `["BUFFER_QUEUE", "@\|*"]` | `profile` |
| `QUEUE` | `["QUEUE", "@\|*"]` | `scheduler, wred_profile` |
| `BUFFER_PORT_INGRESS_PROFILE_LIST` | `["...", "@"]` | `profile_list` |
| `BUFFER_PORT_EGRESS_PROFILE_LIST` | `["...", "@"]` | `profile_list` |

> Note: `@` = the common key (the port). `@|*` matches keys of the form
> `<port>|<index>` (e.g. `Ethernet0|3-4`).

### 5.6 Pattern-Building Algorithm

```python
def _build_requiring_patterns(self, asic):
    exemptions = self._get_no_admin_down_fields(asic)        # {table: [fields]}
    exemptions = {t.lower(): {f.lower() for f in fs}         # normalize for case-insensitive
                  for t, fs in exemptions.items()}
    patterns = []
    for table in self.PORT_BINDING_TABLES:
        name   = table["key_pattern"][0]
        exempt = exemptions.get(name.lower(), set())
        if not exempt:
            patterns.append(table["key_pattern"])             # whole-entry: conservative
        else:
            patterns += [table["key_pattern"] + [field]       # field-level: exempt fields omitted
                         for field in table["fields"]
                         if field.lower() not in exempt]
    return patterns
```

Three outcomes per table:
1. **No exemptions** → match the whole entry (any change bounces the port). Identical
   to the original behavior.
2. **Some fields exempt** → match only the non-exempt fields at field granularity.
   Changing only exempt fields produces no requiring pattern → no bounce.
3. **All fields exempt** → no patterns for that table at all → no change to it ever
   bounces the port.

## 6. Detailed Behavior & Examples

Assume ASIC `th5` (Tomahawk5, e.g. NH-4010) with this configuration:

```json
"th5": { "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map" ] }
```

| Patch changes | Bounce? | Why |
|---------------|---------|-----|
| `PORT_QOS_MAP/EthX/dscp_to_tc_map` | **No** | exempt field |
| `PORT_QOS_MAP/EthX/tc_to_queue_map` | **No** | exempt field |
| `dscp_to_tc_map` + `tc_to_queue_map` | **No** | both exempt |
| `PORT_QOS_MAP/EthX/pfc_to_queue_map` | Yes | not exempt |
| `dscp_to_tc_map` + `pfc_to_queue_map` | Yes | the non-exempt field forces it |
| `BUFFER_PG/EthX\|3-4/profile` | Yes | `BUFFER_PG` not listed → conservative |
| `QUEUE/EthX\|3/scheduler` | Yes | `QUEUE` not listed → conservative |

**Before (any ASIC, original behavior) — bounce:**
```
Patch Applier: The localhost patch was converted into 3 changes:
  * [{"op": "replace", "path": "/PORT/Ethernet0/admin_status", "value": "down"}]
  * [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet0/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
  * [{"op": "replace", "path": "/PORT/Ethernet0/admin_status", "value": "up"}]
```

**After (th5 exempts dscp_to_tc_map) — no bounce:**
```
Patch Applier: The localhost patch was converted into 1 change:
  * [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet0/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
```

### Internal `requiring_patterns` produced for `th5`

```
["BUFFER_PG", "@|*"]                              # conservative (whole entry)
["BUFFER_PORT_EGRESS_PROFILE_LIST", "@"]          # conservative
["BUFFER_PORT_INGRESS_PROFILE_LIST", "@"]         # conservative
["BUFFER_QUEUE", "@|*"]                           # conservative
["PORT_QOS_MAP", "@", "dot1p_to_tc_map"]          # field-level, non-exempt
["PORT_QOS_MAP", "@", "tc_to_pg_map"]             #   (dscp_to_tc_map and
["PORT_QOS_MAP", "@", "pfc_enable"]               #    tc_to_queue_map omitted)
["PORT_QOS_MAP", "@", "pfcwd_sw_enable"]
["PORT_QOS_MAP", "@", "pfc_to_queue_map"]
["PORT_QOS_MAP", "@", "pfc_to_pg_map"]
["PORT_QOS_MAP", "@", "tc_to_dscp_map"]
["PORT_QOS_MAP", "@", "tc_to_dot1p_map"]
["PORT_QOS_MAP", "@", "scheduler"]
["QUEUE", "@|*"]                                  # conservative
```

## 7. Configuration Examples

### 7.1 Exempt fields on one ASIC (current)
```json
"no_admin_down_fields": {
    "th5": { "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map" ] },
    "q3d": { "PORT_QOS_MAP": [ "dscp_to_tc_map" ] }
}
```
`th5` covers every Tomahawk5 HWSKU (e.g. all NH-4010 variants); `q3d` covers the
Qumran3D HWSKUs (e.g. NH-5010-F-O64) and here exempts only `dscp_to_tc_map`.

### 7.2 Extend to buffer bindings on the same ASIC (future "tomorrow" case)
Pure config change — no code change:
```json
"th5": {
    "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map" ],
    "BUFFER_PG":    [ "profile" ],
    "BUFFER_QUEUE": [ "profile" ]
}
```

### 7.3 Apply a policy to all ASICs via `default`
```json
"no_admin_down_fields": {
    "default": { "PORT_QOS_MAP": [ "dscp_to_tc_map" ] },
    "th5":     { "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map" ] }
}
```
(`th5` overrides `default`; all other ASICs use `default`.)

### 7.4 Make an entire table hitless on an ASIC
List all of the table's fields (e.g. `QUEUE`):
```json
"th5": { "QUEUE": [ "scheduler", "wred_profile" ] }
```

### 7.5 Add a brand-new binding table (rare — requires code)
Only when SONiC introduces a new port-binding table:
1. Add one entry to `PORT_BINDING_TABLES` in `patch_sorter.py`
   (its `key_pattern` and `fields`).
2. Reference it from the config file as in the examples above.

## 8. Backward Compatibility

- With an empty `no_admin_down_fields` (or the section absent entirely), every table
  falls back to the whole-entry pattern — **identical** to the original behavior.
- The patch format, CLI, and output messages are unchanged (other than fewer
  synthesized changes when a bounce is skipped).
- This revision changes the schema key semantics from HWSKU names to ASIC shorthands;
  this is an internal config file owned by sonic-utilities and is migrated in the same
  change.

## 9. Failure Handling & Safety

| Condition | Behavior |
|-----------|----------|
| ASIC cannot be resolved (`get_asic_name()` returns `"unknown"`) | no exemptions → conservative |
| `get_asic_name()` raises | caught → `"unknown"` → conservative |
| Config file missing / unreadable / invalid JSON | exception caught → `{}` → conservative |
| `port_binding_replacement` section absent | `{}` → conservative |
| ASIC not listed and no `default` | `{}` → conservative |
| Table listed but unknown to the registry | ignored; logged as a warning |
| Unknown field listed alongside valid field(s) | unknown field dropped (logged); behaves as if it were not listed |
| Table's exempt list contains **only** unknown fields | dropped (logged) → table falls back to conservative whole-entry |

Unknown table/field names are validated against the registry: they are intersected
with the known fields before the matching decision, so a typo can never silently
switch a table from conservative whole-entry matching to field-level matching. Every
dropped name is logged via `log_warning(..., also_print_to_console=True)` so it is
visible to the operator.

The ASIC lookup and file read are each wrapped so that **no failure path can break a
patch apply** — the worst case is the safe, original admin-bounce behavior.

## 10. Testing

Unit tests in
[`tests/generic_config_updater/patch_sorter_test.py`](../tests/generic_config_updater/patch_sorter_test.py)
(`TestRequiredValueIdentifier`):

1. **Conservative / default** — unlisted ASIC yields whole-entry patterns for every
   table (including `PORT_QOS_MAP`), i.e. the original behavior.
2. **Single-table exemption** — an ASIC exempting `dscp_to_tc_map` + `tc_to_queue_map`
   yields field-level `PORT_QOS_MAP` patterns excluding those two, with all other
   tables conservative.
3. **Multi-table exemption** — an ASIC exempting `PORT_QOS_MAP.dscp_to_tc_map`,
   all of `BUFFER_PG`, and all of `QUEUE` drops `BUFFER_PG`/`QUEUE` entirely while
   keeping the remaining `PORT_QOS_MAP` fields and untouched tables conservative.
4. **Unknown field mixed with valid** — an exempt list of
   `["dscp_to_tc_map", "bogus_field"]` behaves exactly like `["dscp_to_tc_map"]`.
5. **Unknown field only** — an exempt list of `["bogus_field"]` falls back to the
   conservative whole-entry pattern.

The ASIC is injected into `RequiredValueIdentifier(path_addressing, asic=...)` and
the exemption lookup is mocked, so the tests are deterministic and independent of the
device/config DB.

## 11. Limitations & Future Work

- **ASIC granularity.** Decisions are per-ASIC, so an exemption applies to **all**
  HWSKUs on that ASIC (e.g. `th5` covers every Tomahawk5 platform, not just one).
  This matches the fact that the capability is an ASIC/SAI property, but if a single
  HWSKU on a shared ASIC needs to differ, an additional HWSKU-level override layer
  would be required (possible future enhancement: ASIC default + HWSKU override).
- **ASIC resolution depends on maintained maps.** `get_asic_name()` resolves the ASIC
  from the `*_asics` HWSKU lists under `rdma_config_update_validator`; a HWSKU absent
  from those lists resolves to `"unknown"` and falls back to conservative.
- **Capability may depend on SAI/build version.** `rdma_config_update_validator`
  already gates per ASIC with a minimum `branch_version`. If in-place rebind support
  is tied to a SAI release, a similar ASIC + min-version gate could be added here.
- **Hard-coded table registry.** Supported tables/fields live in `PORT_BINDING_TABLES`
  and must be kept in sync with the corresponding YANG models. Adding a new *table*
  needs a (small) code change; adding *fields* of existing tables is config-only.
  A future enhancement could derive both from the YANG models directly (the existing
  `# TODO: move to YANG models`).
- **Correctness is operator-asserted.** Listing an (ASIC, table, field) asserts the
  ASIC's SAI rebinds it in place without disruption; this is not auto-verified by GCU.
