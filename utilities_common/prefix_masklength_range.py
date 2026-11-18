# Copyright 2026 Nexthop Systems Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import re

from utilities_common.router_interface_conflicts import key_parts

PREFIX_TABLE = 'PREFIX'

_BOUND = r'([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])'
_RANGE = re.compile(r'exact|' + _BOUND + r'\.\.' + _BOUND)


def models_refuse_malformed_masklength_range(sy):
    """
    Whether the loaded models (a SonicYang) give the PREFIX masklength_range a
    pattern, and with it the musts masklength_range_refusal mirrors. Older
    models type it as a plain string and accept any value.
    """
    model = sy.confDbYangMap.get(PREFIX_TABLE)
    if model is None:
        return False
    return any(leaf.keyword() == 'leaf' and leaf.name() == 'masklength_range' and any(leaf.type().patterns())
               for entry in model['container'].children() for leaf in entry.children())


def masklength_range_refusal(ip_prefix, masklength_range):
    """
    Why a model that refuses malformed ranges refuses masklength_range on
    ip_prefix, or None when it accepts it: 'exact', or <low>..<high> with each
    bound 0 to 128, low <= high, high at least the prefix length, and high at
    most 32 for an IPv4 prefix.
    """
    if not _RANGE.fullmatch(masklength_range):
        return "is not 'exact' or <low>..<high> with bounds 0 to 128"
    if masklength_range == 'exact':
        return None
    low, high = (int(bound) for bound in masklength_range.split('..'))
    if low > high:
        return "has a low bound above its high bound"
    length = ip_prefix.partition('/')[2]
    if length.isdigit() and high < int(length):
        return "has a high bound below the prefix length"
    if ':' not in ip_prefix and high > 32:
        return "has a high bound above 32 for an IPv4 prefix"
    return None


def prefix_row_refusal(key):
    """
    masklength_range_refusal for a PREFIX row's key, which ends in its
    ip_prefix and masklength_range with or without a sequence number before
    them; None for a key of any other shape.
    """
    if not isinstance(key, tuple) or len(key) < 3:
        return None
    return masklength_range_refusal(key[-2], key[-1])


def split_malformed_prefix_rows(config):
    """
    Split out each PREFIX row whose masklength_range prefix_row_refusal
    refuses, for models that pass models_refuse_malformed_masklength_range.

    config is one scope of a config file with '|'-joined keys, or CONFIG_DB
    tables with tuple keys; removed keeps each key as it was given. Returns
    (kept, removed, reasons). removed holds each dropped row in full, so it
    stays recoverable.
    """
    entries = config.get(PREFIX_TABLE)
    if not isinstance(entries, dict):
        return config, {}, []
    refused = [(key, reason) for key in sorted(entries)
               for reason in [prefix_row_refusal(tuple(key_parts(key)))] if reason]
    if not refused:
        return config, {}, []
    dropped = {key for key, _ in refused}
    kept = dict(config)
    kept[PREFIX_TABLE] = {key: value for key, value in entries.items() if key not in dropped}
    removed = {PREFIX_TABLE: {key: entries[key] for key, _ in refused}}
    reasons = ["{}|{} dropped: its masklength_range {}".format(PREFIX_TABLE, '|'.join(key_parts(key)), reason)
               for key, reason in refused]
    return kept, removed, reasons
