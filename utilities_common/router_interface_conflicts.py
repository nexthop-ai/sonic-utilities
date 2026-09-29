ROUTER_INTERFACE_TABLES = ('INTERFACE', 'PORTCHANNEL_INTERFACE')


def key_parts(key):
    """Split a ConfigDB key given either as a tuple or as a '|'-joined string."""
    return list(key) if isinstance(key, tuple) else key.split('|')


def find_router_interface_vlan_conflicts(tables):
    """
    Pick the entries to drop so that no port or PortChannel is both a VLAN
    member and a router interface.

    tables maps a table name to its entries, keyed by tuple or by '|'-joined
    string. A router interface with an address, or with IPv6 link-local-only
    enabled, is kept and its VLAN memberships are dropped. Any other router
    interface row carries nothing that works on a VLAN member, so it is
    dropped and the memberships are kept.

    Returns {table: [key, ...]}, empty when there is no conflict.
    """
    memberships = {}
    for key in tables.get('VLAN_MEMBER') or {}:
        memberships.setdefault(key_parts(key)[-1], []).append(key)

    drop = {}
    for table in ROUTER_INTERFACE_TABLES:
        rows_by_name = {}
        for key, entry in (tables.get(table) or {}).items():
            rows_by_name.setdefault(key_parts(key)[0], []).append((key, entry))

        for name, rows in rows_by_name.items():
            if name not in memberships:
                continue
            routed = any(len(key_parts(key)) > 1 for key, _ in rows) or any(
                isinstance(entry, dict) and entry.get('ipv6_use_link_local_only') == 'enable'
                for _, entry in rows)
            if routed:
                drop.setdefault('VLAN_MEMBER', []).extend(memberships[name])
            else:
                drop.setdefault(table, []).extend(key for key, _ in rows)
    return drop
