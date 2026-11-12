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
  - [9.1 Case: no exemptions apply to this ASIC](#91-case-no-exemptions-apply-to-this-asic)
  - [9.2 Case: a wrong (unknown) field name in the conf](#92-case-a-wrong-unknown-field-name-in-the-conf)
  - [9.3 Summary tables](#93-summary-tables)
- [10. Testing](#10-testing)
- [11. Limitations & Future Work](#11-limitations--future-work)

## Revision

| Rev | Date       | Author | Change Description           |
|-----|------------|--------|------------------------------|
| 0.1 | 2026-06-20 | Nexthop | Initial version (per-HWSKU keying) |
| 0.2 | 2026-06-24 | Nexthop | Switch keying from HWSKU to ASIC (reuse `get_asic_name`) |
| 0.3 | 2026-07-10 | Nexthop | Move the table registry from code into the conf file |
| 0.4 | 2026-07-13 | Nexthop | Fail hard on a missing/invalid conf instead of a silent conservative fallback; drop the in-code `_DEFAULT_PORT_BINDING_TABLES` copy |
| 0.5 | 2026-07-27 | Nexthop | Clarify "fail hard" vs "conservative fallback": expand §9 with worked cases for an unresolved ASIC and a mistyped field name, incl. a console example |
| 0.6 | 2026-07-27 | Nexthop | Warn (instead of staying silent) when no exemptions apply, distinguishing an unresolved ASIC from an ASIC absent from the conf |
| 0.7 | 2026-07-27 | Nexthop | Emit that warning only when the patch actually changes a port binding, so it never appears on unrelated patches |
| 0.8 | 2026-07-28 | Nexthop | Record why the port-binding registry stays in conf while `CreateOnlyFilter` moves to YANG (NOS-12728), and why their failure modes differ |
| 0.9 | 2026-07-28 | Nexthop | Cache the parsed conf per process (one parse per `apply-patch` instead of ~8, and one snapshot behind the registry/exemption intersection); clarify that this is not an in-code copy of the registry |
| 1.0 | 2026-07-28 | Nexthop | Rename the registry key to `port_binding_tables` (the file already has an unrelated top-level `tables`); compare each requiring path at most once per patch when deciding whether to emit the bounce warning |
| 1.1 | 2026-07-28 | Nexthop | Validate registry element types: `key_pattern`/`fields` must hold non-empty strings, so a bad edit fails at load time instead of as an `AttributeError` downstream (or, for an empty string, matching nothing at all) |
| 1.2 | 2026-07-28 | Nexthop | Scope requirement 7 to the port-binding readers: the two pre-existing readers of this conf file raise only on a missing file and let malformed JSON escape (§9.3) |
| 1.3 | 2026-07-28 | Nexthop | Correct §9.2/§9.3: an unknown table name under `no_admin_down_fields` forfeits only its own entry — the ASIC's valid entries still match at field level — and add the test that pins it |
| 1.4 | 2026-09-28 | Nexthop | §11: a third registry, `create_only_replacement.in_place_fields`, lists per ASIC the create-only fields whose value can be changed in place; update the registries note accordingly |
| 1.5 | 2026-10-08 | Nexthop | §11: state what listing an ASIC under `in_place_fields` asserts (the intermediate states orchagent's per-field SAI sets pass through) |
| 1.6 | 2026-10-12 | Nexthop | §7.1, §11: add `q4d` (NH-5210) to `no_admin_down_fields` and `in_place_fields`, with the same lists as `q3d` |
| 1.7 | 2026-11-10 | Nexthop | §6, §7.1: add `pfcwd_sw_enable` to `no_admin_down_fields` on `th5`, `th6`, `q3d` and `q4d` (NOS-22689); state that an exemption also asserts the re-set of the entry's other fields on a live port |
| 1.8 | 2026-11-11 | Nexthop | §3: the admin down for added bindings now comes from `BulkRequiredValueMoveGenerator` (and `BulkKeyLevelMoveGenerator` for ports the patch creates), in one change at the start of the plan; state the longer down window on a live `apply-patch` |

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
| The conf file | [`generic_config_updater/gcu_field_operation_validators.conf.json`](../generic_config_updater/gcu_field_operation_validators.conf.json) — ships with the `sonic-utilities` package and holds both the table registry and the per-ASIC exemptions. Referred to throughout as "the conf file" |
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

The sorter then uses these collaborators:
- `BulkRequiredValueMoveGenerator` — for every binding the patch *adds*, offers one
  change that takes every affected port admin down. It runs before the generators that
  add bindings, so the downs land in the first change of the plan.
- `BulkKeyLevelMoveGenerator` — when the patch creates a port admin up together with its
  bindings (e.g. a breakout change), adds the port admin down in its one group instead.
- `RequiredValueMoveExtender` — generates the `admin_status=down` move before a
  requiring change the generators above did not cover (a binding that is replaced or
  removed), one port per step.
- `RequiredValueMoveValidator` — enforces the ordering (rejects changing the binding
  while the port is up, and rejects bringing the port up while requiring changes
  remain).

All of them read the same `RequiredValueIdentifier` rules. The admin up is grouped by
`BulkKeyGroupLowLevelMoveGenerator` once no requiring change remains.

On a live `config apply-patch` that adds bindings to admin-up ports, this means the
ports go down at the start of the plan, not just before their bindings, and stay down
through any unrelated changes the plan applies before the bindings. The trade-off is
deliberate: when the plan has other changes between the downs and the bindings, as a
full-config replace does, orchagent has taken the ports down by the time their bindings
are applied, so `ChangeApplier` needs no wait for it. This is not a guarantee. orchagent
takes ports down one at a time (about 6 s for 64 ports on an NH-5010-F), and the applier
moves on 1 s after a change. A patch that adds nothing but bindings plans the downs and
the bindings back to back, and on many ports the bindings can then reach orchagent while
some ports are still up: bufferorch logs `PG profile ... applied after port ... is up` and
still programs the profile. Replacing or removing an existing binding still takes each
port down just before its own change.

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
7. **Fail hard on a broken conf** — the port-binding readers (`_load_conf()`,
   `_load_port_binding_tables()`, `_get_no_admin_down_fields()`) raise
   `GenericConfigUpdaterError` rather than silently degrading admin-down protection, and
   they agree with each other on what counts as broken.

   This is a property of the readers this design adds, not of every reader of this file.
   The two pre-existing ones — `get_asic_name()` in `field_operation_validators.py` and the
   validator lookup in `gu_common.py` — raise `GenericConfigUpdaterError` only for a
   *missing* file and let `json.JSONDecodeError` escape on malformed JSON. §9.3 covers why
   that is not a hole on the path described here: `__init__` resolves the ASIC and then
   immediately calls `_load_port_binding_tables()`, so a malformed file aborts
   `apply-patch` either way.

   "Broken" means exactly one of three things, all of which leave the code with **no
   usable table registry at all**:
   1. the conf file is **missing** or cannot be opened;
   2. it is present but is **not valid JSON**;
   3. it is valid JSON, but its `port_binding_tables` registry is **not the expected structure** —
      the section is absent, is not a list, is an empty list, or an entry in it is not a
      `{"key_pattern": [...], "fields": [...]}` object whose two lists are non-empty lists of
      non-empty strings.

   All three can only come from a broken install or a bad hand-edit, since the file ships
   with the package.

   Note what is **not** in this list: a *wrong name* — an ASIC, table, or field under
   `no_admin_down_fields` that the code does not recognize. That conf is readable and its
   registry is intact; it just names something unknown. It is dropped and falls back to
   the conservative bounce (§9), not a hard failure. The structural check above applies to
   the `port_binding_tables` registry — the list of what the tables *are* — not to
   `no_admin_down_fields`, the list of what is exempt.

## 5. High-Level Design

### 5.1 Design Principles

- **Data over code.** The set of exempt (ASIC, table, field) tuples lives in a JSON
  config file, not in Python. Day-to-day changes are config-only.
- **ASIC as the key.** In-place rebind support is a hardware/SAI capability, so the
  decision is keyed on the ASIC family rather than the HWSKU. One entry covers every
  HWSKU on that ASIC.
- **Table described once, in config.** Each port-binding table is described a single
  time in a registry (its key pattern + its bindable fields) that lives in the conf
  file. The bounce-decision logic is generic over this registry, and adding a table is
  a config change. There is no in-code copy of the registry — no second, independently
  maintained list in Python that could drift from the file. (The parsed file *is* cached
  in memory for the life of the process; that is a read of the one source, not a copy of
  it — see §5.5.)
- **Fail hard on a broken conf; be conservative when the conf is silent.** Two different
  things are deliberately not treated the same way:
  - *The rulebook is unusable* — the file is missing, is not valid JSON, or its
    `port_binding_tables`
    registry is absent/not a non-empty list of `{key_pattern, fields}` entries → raise
    `GenericConfigUpdaterError` and abort `apply-patch`. There is no registry to decide
    with, and this can only be a broken install or a bad edit.
  - *The rulebook is fine but says nothing about this case* (ASIC undetermined or not
    listed, section absent, table/field name not in the registry) → drop the unusable part,
    log a warning where one applies, and fall back to the **conservative whole-entry
    bounce** — the original pre-feature behavior. This fallback can only ever *add* an
    admin bounce, never remove one, so it is always the safe direction.

### 5.2 Architecture

```
 config apply-patch
        │
        ▼
 ┌─────────────────────────┐
 │   GCU patch_sorter      │
 │                         │
 │  RequiredValueIdentifier│────► resolve ASIC  (get_asic_name)
 │   • table registry      │         asic_type + HWSKU + *_asics maps
 │   • _build_requiring_   │────► read port_binding_tables + exempt
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

At construction, `RequiredValueIdentifier` reads everything from one file,
`gcu_field_operation_validators.conf.json`:
1. Resolves the ASIC (injectable for tests; otherwise `get_asic_name()`).
2. Loads and validates the table registry from
   `port_binding_replacement.port_binding_tables`
   (hard-fails if the file is missing, is not valid JSON, or has no usable registry).
3. Loads the per-ASIC exemptions from `port_binding_replacement.no_admin_down_fields`.
4. Builds `requiring_patterns` from the table registry, dropping/expanding patterns
   based on the exemptions.

### 5.3 ASIC Resolution

The ASIC shorthand is resolved by `get_asic_name()` in
[`generic_config_updater/field_operation_validators.py`](../generic_config_updater/field_operation_validators.py),
the same function used by `rdma_config_update_validator`. It derives the ASIC from
`DEVICE_METADATA.localhost.asic_type` plus the HWSKU, using the ASIC→HWSKU lists under
`helper_data.rdma_config_update_validator.{mellanox_asics, broadcom_asics}` in the
same conf file (e.g. `th5`, `q3d`, `spc4`, `td3`, `cisco-8000`, `marvell-teralynx`).

`RequiredValueIdentifier` imports it lazily (function-scope) to avoid any import
cycle. A return of `"unknown"` — or any non-conf exception (e.g. a `device_info` or
subprocess hiccup) — is treated as "no exemptions" (conservative). A
`GenericConfigUpdaterError` (raised by `get_asic_name()` when the conf file is missing)
is **not** swallowed: it propagates, so a broken conf fails hard here too.

`get_asic_name()` returns `"unknown"` whenever the ASIC genuinely cannot be determined,
which happens in two ordinary situations:

- **`asic_type` is unspecified** — `device_info.get_sonic_version_info()` has no
  `asic_type` key (or returns nothing at all).
- **The HWSKU is not in the maps** — `asic_type` is known but the HWSKU is absent from
  the `helper_data.rdma_config_update_validator.{mellanox_asics, broadcom_asics}` lists,
  e.g. a brand-new platform that has not been added yet.

Either way the ASIC is *undetermined*, not *wrong*, so `_get_no_admin_down_fields()`
returns `{}` immediately — it does not even open the conf file — and every port-binding
table keeps its conservative whole-entry pattern. See §9.1 for why this is a fallback
and not a hard failure.

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
- The optional `"default"` key applies to every **resolved** ASIC not listed explicitly.
  It does **not** apply when the ASIC could not be resolved at all (`"unknown"`) — see §9.1.
- ASIC, table, and field matching are all **case-insensitive**.

### 5.5 Table Registry

The registry that describes each supported table once lives in
[`generic_config_updater/gcu_field_operation_validators.conf.json`](../generic_config_updater/gcu_field_operation_validators.conf.json)
— the same conf file as the exemptions in §5.4 — under
`helper_data.port_binding_replacement.port_binding_tables`. It is loaded at construction by
`RequiredValueIdentifier._load_port_binding_tables()` into `self.port_binding_tables`:

```json
"port_binding_tables": [
    { "key_pattern": ["BUFFER_PG", "@|*"], "fields": ["profile"] },
    { "key_pattern": ["BUFFER_PORT_EGRESS_PROFILE_LIST", "@"], "fields": ["profile_list"] },
    { "key_pattern": ["BUFFER_PORT_INGRESS_PROFILE_LIST", "@"], "fields": ["profile_list"] },
    { "key_pattern": ["BUFFER_QUEUE", "@|*"], "fields": ["profile"] },
    { "key_pattern": ["PORT_QOS_MAP", "@"], "fields": [ ...11 maps... ] },
    { "key_pattern": ["QUEUE", "@|*"], "fields": ["scheduler", "wred_profile"] }
]
```

The registry lives **only** in `gcu_field_operation_validators.conf.json`;
`patch_sorter.py` keeps no in-code copy.
`_load_port_binding_tables()` reads it via `_load_conf()` and checks its structure up
front: `port_binding_tables` must be a non-empty list, and every entry must be an object
whose `key_pattern` and `fields` are non-empty lists of non-empty strings. Anything else
raises `GenericConfigUpdaterError` at load time — the point of checking here is that the
same defect would otherwise surface much later as an unhelpful
`KeyError`/`IndexError`/`AttributeError` thrown out of `__init__`.

Element types are part of the structure, not a detail. Every token and field name is used
as a string downstream — `.lower()` in `_build_requiring_patterns()`,
`.replace()`/`.startswith()` inside `JsonPointerFilter` — so a `{"key_pattern": [123]}`
that passed this check would resurface as `'int' object has no attribute 'lower'`, which is
the very error the check exists to replace. Empty strings are rejected for a different
reason: one would satisfy every type check and then match nothing, quietly dropping that
table's admin-down protection instead of failing.

`_load_conf()` caches the parsed file per process (keyed by path). Each
`RequiredValueIdentifier` reads the conf twice — once for this registry and once for the
per-ASIC exemptions of §5.4 — and the class is constructed several times per
`apply-patch` (validator, extender, strict and non-strict sorters), so without the cache
the same file would be re-read and re-parsed roughly eight times per patch. The stronger
reason is consistency: those two halves are intersected against each other in
`_build_requiring_patterns()` (§5.6), and separate reads could observe two different
states of the file. One parse means one snapshot of the conf decides a whole patch.
Only successful parses are cached, so a transient read failure is retried rather than
remembered, and `_load_port_binding_tables()` returns a deep copy so the cached parse
cannot be mutated through an identifier's `self.port_binding_tables`.

Caching a parse is **not** an in-code copy of the registry in the sense used above: the
conf file remains the only source, the cache holds nothing that was not read from it, and
it lives no longer than the `apply-patch` process. What §5.1 rules out is a second,
independently maintained copy of the registry in Python that could drift from the file.

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
    for table in self.port_binding_tables:
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
"th5": { "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map", "pfcwd_sw_enable" ] }
```

| Patch changes | Bounce? | Why |
|---------------|---------|-----|
| `PORT_QOS_MAP/EthX/dscp_to_tc_map` | **No** | exempt field |
| `PORT_QOS_MAP/EthX/tc_to_queue_map` | **No** | exempt field |
| `dscp_to_tc_map` + `tc_to_queue_map` | **No** | both exempt |
| `PORT_QOS_MAP/EthX/pfcwd_sw_enable` | **No** | exempt field |
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
["PORT_QOS_MAP", "@", "tc_to_pg_map"]             #   (dscp_to_tc_map,
["PORT_QOS_MAP", "@", "pfc_enable"]               #    tc_to_queue_map and
                                                  #    pfcwd_sw_enable omitted)
["PORT_QOS_MAP", "@", "pfc_to_queue_map"]
["PORT_QOS_MAP", "@", "pfc_to_pg_map"]
["PORT_QOS_MAP", "@", "tc_to_dscp_map"]
["PORT_QOS_MAP", "@", "tc_to_dot1p_map"]
["PORT_QOS_MAP", "@", "scheduler"]
["QUEUE", "@|*"]                                  # conservative
```

With the shipped `th5` list (§7.1), the patterns for `tc_to_pg_map`, `pfc_enable`,
`pfc_to_queue_map`, `tc_to_dscp_map` and `scheduler` drop out as well.

## 7. Configuration Examples

### 7.1 Exempt fields on one ASIC (as currently shipped)
```json
"no_admin_down_fields": {
    "th5": {
        "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_queue_map", "tc_to_pg_map",
                          "pfc_to_queue_map", "tc_to_dscp_map", "pfc_enable",
                          "pfcwd_sw_enable", "scheduler" ],
        "QUEUE":        [ "scheduler" ],
        "BUFFER_QUEUE": [ "profile" ],
        "BUFFER_PG":    [ "profile" ]
    },
    "q3d": {
        "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_pg_map", "tc_to_queue_map",
                          "pfc_enable", "pfcwd_sw_enable", "scheduler" ],
        "QUEUE":        [ "scheduler" ],
        "BUFFER_QUEUE": [ "profile" ],
        "BUFFER_PG":    [ "profile" ]
    },
    "q4d": {
        "PORT_QOS_MAP": [ "dscp_to_tc_map", "tc_to_pg_map", "tc_to_queue_map",
                          "pfc_enable", "pfcwd_sw_enable", "scheduler" ],
        "QUEUE":        [ "scheduler" ],
        "BUFFER_QUEUE": [ "profile" ],
        "BUFFER_PG":    [ "profile" ]
    }
}
```
`th5` covers every Tomahawk5 HWSKU (e.g. all NH-4010 variants); `q3d` covers the
Qumran3D HWSKUs (e.g. NH-5010-F-O64); `q4d` covers the Qumran4D HWSKUs (e.g. NH-5210),
with the same list as `q3d`. All three exempt the single field of `BUFFER_QUEUE` and
`BUFFER_PG`, so those two tables drop out of the requiring patterns entirely (outcome 3 in
§5.6). The illustrative three-field `th5` config used in §6 is a simplification of this.

An exemption covers the changed field, not the update orchagent makes. On any
`PORT_QOS_MAP` update, orchagent re-sets every map field in the entry on the live port and
re-applies `pfc_enable`, whichever field changed. So listing a field asserts that this
ASIC's SAI accepts those re-sets of unchanged values on a live port, including for fields
not listed. On `q3d` and `q4d`, the NH QoS templates put `pfc_to_queue_map` on every
port, and every listed field relies on its re-set. `pfcwd_sw_enable` itself sets no SAI
attribute (orchagent only stores the bitmask for the PFC watchdog). A changed
`pfcwd_sw_enable` is not applied to a PFC watchdog (hardware or software) already running
on the port; the watchdog reads it at its next start or stop.

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

### 7.5 Add a brand-new binding table
When SONiC introduces a new port-binding table, add one entry to the `port_binding_tables`
registry in
`gcu_field_operation_validators.conf.json` (its `key_pattern` and `fields`):
```json
"port_binding_tables": [
    ...,
    { "key_pattern": ["NEW_TABLE", "@"], "fields": ["some_binding"] }
]
```
Then reference it from `no_admin_down_fields` as in the examples above. This is a
config-only change; there is no in-code copy of the registry to keep in sync.

## 8. Backward Compatibility

- With an empty `no_admin_down_fields` (or the section absent entirely), every table
  falls back to the whole-entry pattern — **identical** to the original behavior.
- The patch format, CLI, and output messages are unchanged (other than fewer
  synthesized changes when a bounce is skipped).
- This revision changes the schema key semantics from HWSKU names to ASIC shorthands;
  this is an internal config file owned by sonic-utilities and is migrated in the same
  change.

## 9. Failure Handling & Safety

The feature asks two questions, in order, and only the **first** one can abort the patch:

1. **Can I read the rulebook at all?** — the conf file must exist, parse as JSON, and
   contain a usable `port_binding_tables` registry (§4.7). If not, the code cannot tell which
   tables are
   port-binding tables or which fields they have, so it raises
   `GenericConfigUpdaterError` and `config apply-patch` aborts. This is a **broken conf**:
   the file ships with the package, so it can only be broken by a bad install or a
   hand-edit. There is no sane decision to make without a registry, and quietly proceeding
   would change bounce behavior without anyone noticing.

2. **Does the rulebook say anything about *this* ASIC / table / field?** — if the answer is
   "no" or "not in a way I recognize", nothing is broken. The conf read fine; it simply
   grants no exemption here. The unusable part is dropped (with a warning where one
   applies) and that table falls back to the **conservative whole-entry pattern**: any
   change to the table bounces the port, exactly as GCU behaved before this feature
   existed.

The asymmetry is deliberate. Question 1 failing means *the ruleset is unknowable*.
Question 2 failing means *the ruleset is known and it does not exempt you* — which is a
normal, expected state (a new HWSKU, an ASIC that was never configured, a table nobody
listed). Falling back there can only **add** an admin bounce, never remove one, so it can
never turn a disruptive change into an undetected one. Aborting `apply-patch` for it
would instead break perfectly ordinary patches on perfectly healthy devices.

### 9.1 Case: no exemptions apply to this ASIC

**What happens:** conservative — every port-binding table bounces the port — and, **if the
patch actually changes a port binding**, a warning is printed saying so. There are two
distinct causes, and the warning names which one it is, because the fix is different for
each.

**Cause A — the ASIC could not be resolved.** See §5.3 for the two ways `get_asic_name()`
ends up at `"unknown"` (no `asic_type`, or a HWSKU missing from the `*_asics` maps):

1. `_get_asic()` → `get_asic_name()` → `"unknown"`.
2. `_get_no_admin_down_fields("unknown")` short-circuits and returns `{}` **without
   reading the conf** — there is no ASIC key to look up, and `"default"` is deliberately
   *not* applied to an undetermined ASIC (a `default` exemption is a statement about
   known hardware, not about hardware we failed to identify).
3. `_build_requiring_patterns()` sees no exemptions, so every table contributes its
   whole-entry `key_pattern`, and it **stages** this warning:

```
Patch Sorter: port_binding_replacement: could not determine the switch ASIC; no in-place rebind support applies, so this port binding change will admin-down/up the port.
```

*Fix:* add the HWSKU to the `*_asics` maps under
`helper_data.rdma_config_update_validator`.

**Cause B — the ASIC resolved, but the conf has no entry for it** (and no `"default"`).
This is the `th6` case below: `get_asic_name()` returns `th6` correctly, there is simply no
`th6` key under `no_admin_down_fields`:

```
Patch Sorter: port_binding_replacement: no in-place rebind support configured for asic 'th6'; this port binding change will admin-down/up the port.
```

*Fix:* if that ASIC does support in-place rebind, add a `"th6": { ... }` entry under
`no_admin_down_fields` (§7).

Either way a `PORT_QOS_MAP` change expands into 3 changes (down → change → up) — the §2
"before" behavior:

```
Patch Applier: localhost: sorting patch updates.
Patch Sorter: port_binding_replacement: no in-place rebind support configured for asic 'th6'; this port binding change will admin-down/up the port.
Patch Applier: The localhost patch was converted into 3 changes:
Patch Applier: localhost: applying 3 changes in order:
Patch Applier:   * [{"op": "replace", "path": "/PORT/Ethernet192/admin_status", "value": "down"}]
Patch Applier:   * [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet192/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
Patch Applier:   * [{"op": "replace", "path": "/PORT/Ethernet192/admin_status", "value": "up"}]
```

**Why warn at all, if this is the safe path?** Because from the operator's side a
conservative fallback and a misconfiguration look identical: ports bounce and nothing says
why. Without the warning, a typo'd ASIC key or a HWSKU missing from the maps presents as
"the feature just doesn't work", with no thread to pull. The warning is emitted once per
process (`_log_config_warning` de-duplicates), so a single `apply-patch` prints one line
even though `RequiredValueIdentifier` is constructed several times.

**Why this is not a hard failure:** an undetermined or unconfigured ASIC is a legitimate
runtime state, not a corrupt file. Virtual switches, lab images, and platforms not yet
added to the HWSKU maps all land here, as does every platform that has simply never
configured an exemption. Aborting would make `apply-patch` unusable on those devices for
*every* patch, including ones that touch no port binding at all — a far worse outcome
than an extra admin bounce.

**When the warning is emitted.** The message claims a port binding change is bouncing the
port, so it must not appear on a patch where that is untrue. It is therefore **staged**, not
printed, when the patterns are built, and released only once a port binding is known to be
changing:

1. `_build_requiring_patterns()` stages the message on
   `self._no_rebind_support_warning` (nothing is printed).
2. `RequiredValueMoveExtender.extend()` and `RequiredValueMoveValidator.validate()` each
   call `warn_if_bounce_unavoidable(data, current_config, target_config)` right after
   building the requiring data.
3. That method scans the requiring paths for one where the **patch as a whole** changes the
   binding (`is_config_different(path, current_config, target_config)`). Only then does it
   print, and it clears the staged message so later moves skip the scan.

Comparing *current vs target* rather than the per-move simulated config matters: the
warning then appears once at the start of the patch, rather than only when the binding's
own move happens to come up.

It also bounds the cost. Step 2 runs on **every candidate move** the sorter validates, and
in the quiet case — a patch that changes no port binding, which is exactly the case step 3
exists to keep silent — the staged message is never cleared, so the scan would otherwise
repeat in full for every move, at two JSON-pointer resolutions per requiring path. Because
both sides of the comparison are the patch's endpoints, each path's verdict is fixed for
the whole patch, so paths found unchanged are remembered in `_unchanged_binding_paths` and
never resolved twice. The requiring data is rebuilt per move (from the simulated config as
well) and can gain paths, so the memo skips answered paths rather than skipping the scan:
a binding that first appears in a later move still warns.

Consequently a patch that touches no port binding stays silent even on an ASIC with no
exemptions:

```
admin@seag166:~$ sudo config apply-patch /home/admin/new_dscp_to_tc.json
...
Patch Applier: localhost: sorting patch updates.
Patch Applier: The localhost patch was converted into 1 change:
Patch Applier:   * [{"op": "add", "path": "/DSCP_TO_TC_MAP/NEW_AZURE_DSCP_MAP", "value": {...}}]
```

`DSCP_TO_TC_MAP` is the map *definition*, not a port binding — nothing is admin-downed, so
nothing is warned about. The warning appears only once a `PORT_QOS_MAP` (or other
port-binding) entry is rebound to it.

### 9.2 Case: a wrong (unknown) field name in the conf

**What happens:** the misspelled name is dropped and logged; the decision is then made as
if it had never been written. Concretely, `_build_requiring_patterns()` computes
`exempt = requested & known_fields` — it **intersects before deciding**, so:

| Exempt list for the table | Result |
|---------------------------|--------|
| `["dscp_to_tc_map", "dscp__to_pg_map"]` (one valid, one typo) | typo dropped + logged; behaves exactly like `["dscp_to_tc_map"]` → field-level patterns, `dscp_to_tc_map` still exempt (no bounce) |
| `["dscp__to_pg_map"]` (typo only) | dropped + logged; `exempt` is empty → table falls back to the conservative whole-entry pattern (bounce) |
| A whole table name that is not in the registry | that exempt entry is ignored + logged; it forfeits only itself — the ASIC's other, valid entries still produce field-level patterns |

An unrecognized *table* name is scoped the same way, and scoped narrowly.
`_build_requiring_patterns()` looks up `exemptions.get(table_name, set())` once per registry
table, so a name that matches no registry table is simply never consulted: it forfeits its
own exemptions and nothing else. With `th5` as shipped, adding a `BOGUS_TABLE` entry logs
the warning and leaves `PORT_QOS_MAP`, `BUFFER_QUEUE` and `BUFFER_PG` matching at field
level exactly as before. Registry tables that end up conservative in that scenario are the
ones with no valid exemption of their own — true with or without the bad name.

The intersect-before-decide order is the safety property: a typo can never flip a table
from conservative whole-entry matching into field-level matching, which is the only way a
typo could have *silently removed* a bounce that was supposed to happen. Every dropped
name is logged via `log_warning(..., also_print_to_console=True)`, so it appears on the
console and in syslog; `_log_config_warning()` de-duplicates it to one line per distinct
message per process (`RequiredValueIdentifier` is constructed several times per
`apply-patch`).

**Why this is not a hard failure:** the conf is structurally valid — someone just named a
field the registry does not know. That can be a typo, or a field from a newer/older YANG
than this image ships. Dropping it is fail-safe (it can only re-add a bounce) and loud,
whereas aborting would block an operator's unrelated patch over one bad string.

#### Example — typo alongside a valid field

Conf for this device (ASIC `th6`), with `dscp_to_pg_map` mistyped as `dscp__to_pg_map`:

```json
"th6": { "PORT_QOS_MAP": [ "dscp_to_tc_map", "dscp__to_pg_map" ] }
```

Applying a patch that changes only `dscp_to_tc_map`:

```
admin@seag166:~$ sudo config apply-patch /home/admin/bind_dscp_to_tc.json
Patch Applier: localhost: Patch application starting.
Patch Applier: localhost: Patch: [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet192/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
Patch Applier: localhost getting current config db.
Patch Applier: localhost: simulating the target full config after applying the patch.
Patch Applier: localhost: validating all JsonPatch operations are permitted on the specified fields
Patch Applier: localhost: validating target config does not have empty tables,
                            since they do not show up in ConfigDb.
Patch Applier: localhost: sorting patch updates.
Patch Sorter: port_binding_replacement: ignoring unknown field(s) ['dscp__to_pg_map'] for table 'PORT_QOS_MAP' on asic 'th6'. Valid fields: ['dot1p_to_tc_map', 'dscp_to_tc_map', 'pfc_enable', 'pfc_to_pg_map', 'pfc_to_queue_map', 'pfcwd_sw_enable', 'scheduler', 'tc_to_dot1p_map', 'tc_to_dscp_map', 'tc_to_pg_map', 'tc_to_queue_map']
Patch Applier: The localhost patch was converted into 1 change:
Patch Applier: localhost: applying 1 change in order:
Patch Applier:   * [{"op": "replace", "path": "/PORT_QOS_MAP/Ethernet192/dscp_to_tc_map", "value": "NEW_AZURE_DSCP_MAP"}]
Patch Applier: localhost: verifying patch updates are reflected on ConfigDB.
Patch Applier: localhost patch application completed.
Patch applied successfully.
```

Reading the output:

- The `Patch Sorter:` line names the bad field, the table, the ASIC, and the full list of
  valid field names for that table — enough to fix the conf without consulting this
  document.
- The patch is **not** rejected. It converts into **1 change** — no admin bounce — because
  the surviving valid entry `dscp_to_tc_map` still exempts the field actually being
  changed.
- Had the exempt list contained *only* `dscp__to_pg_map`, the same warning would print but
  the count would read `converted into 3 changes` (down → change → up): with nothing valid
  left, `PORT_QOS_MAP` reverts to the conservative whole-entry pattern.
- `dscp_to_pg_map` itself remains non-exempt until the typo is corrected, so any patch
  touching that field keeps bouncing the port.

### 9.3 Summary tables

**Broken conf → hard failure (`GenericConfigUpdaterError`), `apply-patch` aborts:**

| Condition | Behavior |
|-----------|----------|
| The conf file is missing, unreadable, or not valid JSON | `GenericConfigUpdaterError` from `_load_conf()` |
| `port_binding_replacement.port_binding_tables` is absent, empty, or not a list | `GenericConfigUpdaterError` from `_load_port_binding_tables()` |
| A `port_binding_tables` entry is not an object, or its `key_pattern`/`fields` is not a non-empty list of non-empty strings | `GenericConfigUpdaterError` from `_load_port_binding_tables()` |
| The conf file is missing when `get_asic_name()` reads it during ASIC resolution | `GenericConfigUpdaterError` from `get_asic_name()`, propagated by `_get_asic()` instead of being swallowed into `"unknown"` |

The last row is listed separately because ASIC resolution reads the same file through its
own path (`get_asic_name()` in `field_operation_validators.py`, which needs the
`*_asics` HWSKU maps). `_get_asic()` deliberately catches *other* exceptions from it and
falls back to `"unknown"` (conservative), so without that carve-out a missing conf would be
downgraded to a silent fallback instead of the hard failure the first three rows give.

It says *missing* rather than *missing or invalid JSON* because `get_asic_name()` only
raises `GenericConfigUpdaterError` for a missing file; malformed JSON raises
`json.JSONDecodeError` there, which `_get_asic()` swallows into `"unknown"`. That is not a
hole: `__init__` calls `_load_port_binding_tables()` immediately afterwards, and row 1
catches the malformed file a moment later. Either way `apply-patch` aborts.

**Conf readable but silent on this case → conservative bounce, patch still applies:**

| Condition | Behavior | Warning? |
|-----------|----------|----------|
| The ASIC cannot be determined — no `asic_type`, or the HWSKU is absent from the `*_asics` maps | `get_asic_name()` → `"unknown"` → no exemptions → conservative (§9.1) | "could not determine the switch ASIC" — only if the patch changes a port binding |
| `device_info` or the HWSKU subprocess fails during ASIC resolution | caught by `_get_asic()` → `"unknown"` → conservative | same as above |
| The conf has no `no_admin_down_fields` section | `{}` → conservative | "no in-place rebind support configured for asic '\<x\>'" — only if the patch changes a port binding |
| The ASIC is resolved but has no entry, and there is no `default` | `{}` → conservative | same as above |
| Table listed but unknown to the registry | that entry ignored → only it is forfeited; the ASIC's valid entries are unaffected | yes, at load time |
| Unknown field listed alongside valid field(s) | unknown field dropped; behaves as if never listed (§9.2) | yes, at load time |
| Table's exempt list contains **only** unknown fields | all dropped → table falls back to conservative whole-entry | yes, at load time |

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
6. **Unknown table name** — a `BOGUS_TABLE` entry alongside a valid `PORT_QOS_MAP` one is
   dropped and logged, and forfeits only itself: `PORT_QOS_MAP` still matches at field level
   with `dscp_to_tc_map` exempt. This pins the scope of the drop — an unknown name must not
   pull the ASIC's valid entries back to conservative.
7. **"No in-place rebind support" warning** — a patch that changes no port binding (adding
   a `DSCP_TO_TC_MAP` entry) stays silent on an unconfigured ASIC, while the same ASIC
   warns once a `PORT_QOS_MAP` rebind is in the patch; an unresolved ASIC warns about the
   ASIC and stays conservative; a correctly configured ASIC warns not at all; and four
   identifiers driven three times each produce exactly one console line. Two more cases
   pin the scan cost: five calls over a quiet patch resolve each requiring path exactly
   once (not once per call), and a binding that only enters the requiring data on a later
   move still warns — the memo skips answered paths, not the scan.

Cases 1–7 inject the ASIC via `RequiredValueIdentifier(path_addressing, asic=...)` and
mock the exemption lookup, so they are deterministic and independent of the
device/config DB.

The conf loader is also covered directly (so a future refactor that mocks the loaders
cannot silently remove this coverage):

8. **Loader reads the shipped conf** — `_load_port_binding_tables()` reads the conf and
   returns the full six-table registry.
9. **Fail-hard on a broken conf** — a missing file, malformed JSON, a missing/empty
   `port_binding_tables` section, and malformed entries (non-object entry; `key_pattern` or
   `fields` missing, empty, not a list, or holding a non-string / empty-string element) each
   raise `GenericConfigUpdaterError`.
10. **Verified-only exemptions** — the exempt lists the shipped conf grants `th5`, `q3d` and `q4d`
   (§7.1) are asserted exactly, so any expansion of the in-place-rebind exemptions has to
   be made deliberately and reviewed as a hardware claim. An unknown ASIC returns `{}`
   without reading the file, and a resolved ASIC with a missing conf raises
   `GenericConfigUpdaterError`.
11. **Parse cached once per process** (§5.5) — two identifiers open the conf file once in
    total; the cache-clearing hook the tests rely on really does force a re-read; a failed
    parse is not cached; and the registry handed to each identifier is isolated from the
    cached parse (mutating one identifier's `port_binding_tables` affects neither another
    identifier nor the cache).

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
- **Table registry maintained in config.** Supported tables/fields live in the conf
  file's `port_binding_tables` registry (there is no in-code copy; the parsed file is cached
  in memory
  per process — §5.5) and must be kept in sync with the corresponding YANG models. Adding
  a table or field is a config change.
- **Registries in `patch_sorter.py`, sourced two different ways — on purpose.**
  Once NOS-12728 lands, `CreateOnlyFilter` discovers its patterns from the compiled YANG
  models via the `ext:create-only` extension, while the port-binding registry described
  here stays in `gcu_field_operation_validators.conf.json`. The split follows what the
  data *is*:
  - *Schema properties* → YANG. Whether a field is create-only is a property of the
    field itself, identical on every platform. YANG is its natural home.
  - *Platform capability assertions* → conf. Whether an ASIC can rebind a field in place
    without bouncing the port is a property of that ASIC's SAI, not of the schema, and
    has no YANG representation. It already lives beside the `*_asics` HWSKU maps in this
    conf file.

  The same split applies to the in-place create-only fields in
  `helper_data.create_only_replacement.in_place_fields`. That a field is create-only stays a
  schema property in YANG. Whether an ASIC can still change such a field's value in place,
  instead of re-creating the entry and first removing everything that references it, is a
  capability of that ASIC's SAI, so it is listed per ASIC in the conf beside the rebind
  exemptions. An ASIC with no entry keeps re-creating (the conservative default). Only a value
  change or an added field is applied in place: orchagent cannot clear a removed field, so
  removing one still re-creates the entry. An entry that carries any create-only field not listed
  for the ASIC is re-created for every change, because orchagent re-sets all of an entry's fields
  on each update.

  What listing an ASIC asserts: orchagent applies an entry's fields as one SAI set per field, in
  the order CONFIG_DB holds them, so an in-place update passes through intermediate states that
  the re-create path never produced, and the ASIC's SAI must accept them. For SCHEDULER: a
  minimum rate above the old maximum (`cir` set before `pir`), and a `meter_type` that changes
  before its rates. The packets→bytes direction is the one that matters: between the two sets a
  rate of 1,000,000 packets/s is applied as 1,000,000 bytes/s, an 8 Mb/s shaper on a live port.
  Sub-millisecond on a quiet box, but under load it is a burst of drops that the re-create path
  did not have (that path left the object unshaped for its gap instead). `q3d` was verified on
  queue-bound schedulers (NOS-17934), and `q4d` is listed with the same fields; a new ASIC needs the same check before it is listed.

  The `port_binding_tables` registry follows the exemptions into the conf because the two are
  intersected against each other (`requested & known_fields` in
  `_build_requiring_patterns()`). Splitting them across YANG and JSON would spread one
  intersection over two sources and require the field-name spellings to agree across
  both, with a typo on either side silently changing behavior.

  The two also differ in what happens when the source is unusable, and that difference
  is a consequence of the same split rather than an inconsistency: `CreateOnlyFilter`
  falls back to its in-code pattern list when `sonic_yang`/`confDbYangMap` is
  unavailable, which is safe because the fallback list preserves the previous
  protection. The port-binding registry deliberately keeps **no** in-code copy (rev
  0.4), so it has no conservative fallback available — a silent one would mean losing
  admin-down protection — and therefore fails hard with `GenericConfigUpdaterError`
  instead. See §9.
- **Correctness is operator-asserted.** Listing an (ASIC, table, field) asserts the
  ASIC's SAI rebinds it in place without disruption; this is not auto-verified by GCU.
