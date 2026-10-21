import utilities_common.dhcp_relay_util as dhcp_relay_util


def router_interface_refusal(config_db, table, port, action, namespace=None):
    """Refusal for using a router interface for an L2 role, naming what makes it routed.

    action completes "run ... before <action>", e.g. "adding it to a VLAN".
    """
    entry = config_db.get_entry(table, port)
    interface_cmd = "config interface -n {}".format(namespace) if namespace else "config interface"
    reasons = []
    commands = []
    if entry.get('vrf_name') or entry.get('vnet_name'):
        # Unbinding also removes the addresses and link-local mode.
        if entry.get('vrf_name'):
            reasons.append("bound to VRF {}".format(entry['vrf_name']))
        else:
            reasons.append("bound to VNET {}".format(entry['vnet_name']))
        commands.append("'{} vrf unbind {}'".format(interface_cmd, port))
    else:
        addresses = sorted(key[1] for key in config_db.get_keys(table)
                           if isinstance(key, tuple) and key[0] == port)
        if addresses:
            reasons.append("IP address{} {}".format("es" if len(addresses) > 1 else "", ", ".join(addresses)))
            commands += ["'{} ip remove {} {}'".format(interface_cmd, port, address) for address in addresses]
        if entry.get('ipv6_use_link_local_only') == 'enable':
            reasons.append("IPv6 link-local-only enabled")
            commands.append("'{} ipv6 disable use-link-local-only {}'".format(interface_cmd, port))
    # The commands above keep DHCP relay servers on the entry, so they are removed last.
    # Relay servers can be configured on Ethernet ports only.
    servers = []
    for field in dhcp_relay_util.DHCP_RELAY_INTF_FIELDS:
        servers += entry.get(field, [])
    if servers and table == 'INTERFACE':
        reasons.append("DHCP relay server{} {}".format("s" if len(servers) > 1 else "", ", ".join(servers)))
        commands.append("'{} dhcp_relay del {} {}'".format(interface_cmd, port, " ".join(servers)))
    if not reasons:
        if not entry:
            return "{} is a router interface ({} has an empty entry for it)".format(port, table)
        fields = ", ".join("{}={}".format(field, ",".join(value) if isinstance(value, list) else value)
                           for field, value in sorted(entry.items()))
        return "{} is a router interface ({} has an entry for it with {})".format(port, table, fields)
    return "{} is a router interface ({}); run {} before {}".format(
        port, "; ".join(reasons), ", then ".join(commands), action)
