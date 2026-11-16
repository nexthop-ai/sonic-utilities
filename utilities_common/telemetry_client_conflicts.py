# Copyright 2026 Nexthop Systems Inc. All rights reserved.
# This software is proprietary and confidential. Unauthorized use, distribution, or modification is strictly prohibited.
from utilities_common.router_interface_conflicts import key_parts

TABLE = 'TELEMETRY_CLIENT'
GROUP_PREFIX = 'DestinationGroup'
SUBSCRIPTION_PREFIX = 'Subscription'


def split_telemetry_client_dst_group_conflicts(config):
    """
    Split out each TELEMETRY_CLIENT Subscription whose dst_group names no
    DestinationGroup. The model's must on dst_group used to be contains() over
    the list names, which XPath reduces to the first name only, so a substring
    of that name or a Subscription's name was accepted and older images could
    save it. The model now requires an existing DestinationGroup with exactly
    that name. Such a Subscription had no collector to dial, so dropping it
    does not change what the dial-out client sends. A Subscription without a
    dst_group is outside the constraint and stays.

    config is one scope of a config file with '|'-joined keys, or CONFIG_DB
    tables with tuple keys; removed keeps each key as it was given. Returns
    (kept, removed, reasons). kept and removed are ConfigDB shaped, removed
    holding each dropped Subscription in full so it stays recoverable.
    """
    entries = config.get(TABLE) or {}
    groups = set()
    subscriptions = []
    for key, value in entries.items():
        parts = key_parts(key)
        if len(parts) != 2:
            continue
        if parts[0] == GROUP_PREFIX:
            groups.add(parts[1])
        elif parts[0] == SUBSCRIPTION_PREFIX and isinstance(value, dict) and 'dst_group' in value:
            subscriptions.append((key, parts[1], value))

    dangling = [(key, name, value) for key, name, value in subscriptions
                if value['dst_group'] not in groups]
    if not dangling:
        return config, {}, []

    dropped_keys = {key for key, _, _ in dangling}
    kept = dict(config)
    kept[TABLE] = {key: value for key, value in entries.items() if key not in dropped_keys}
    removed = {TABLE: {key: dict(value) for key, _, value in dangling}}
    reasons = ["{}|{}|{} dropped: dst_group '{}' names no DestinationGroup, so it had no "
               "collector to dial".format(TABLE, SUBSCRIPTION_PREFIX, name, value['dst_group'])
               for _, name, value in sorted(dangling, key=lambda d: d[1])]
    return kept, removed, reasons
