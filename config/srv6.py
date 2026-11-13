import click
import ipaddress
import jsonpatch
import utilities_common.cli as clicommon
from .validated_config_db_connector import ValidatedConfigDBConnector
from generic_config_updater.generic_updater import GenericUpdater, ConfigFormat

ADHOC_VALIDATION = True

# ConfigDB table names
CONFIG_DB_SRV6_MY_LOCATORS_TABLE = 'SRV6_MY_LOCATORS'
CONFIG_DB_SRV6_MY_SIDS_TABLE = 'SRV6_MY_SIDS'
CONFIG_DB_SRV6_GLOBAL_TABLE = 'SRV6_GLOBAL'

# Valid device_encap_mode values
VALID_ENCAP_MODES = ['regular', 'reduced', 'all']

# Valid SRv6 action types
VALID_ACTIONS = ['uN', 'uA', 'uDT4', 'uDT6', 'uDT46', 'End', 'End.PSP', 'End.USD',
                 'End.PSP.USD', 'End.X', 'End.X.PSP', 'End.X.PSP.USD']

# Actions that require vrf parameter
VRF_REQUIRED_ACTIONS = ['uDT4', 'uDT6', 'uDT46']

# Actions that require interface parameter
INTERFACE_REQUIRED_ACTIONS = ['uA', 'End.X', 'End.X.PSP', 'End.X.PSP.USD']

# uSID actions (micro-segment)
USID_ACTIONS = ['uN', 'uA', 'uDT4', 'uDT6', 'uDT46']

# frrcfgd and zebra drop func_len above this (bgpd SID transposition).
MAX_FUNC_LEN = 20


def is_valid_ipv6_prefix(prefix):
    """Validate IPv6 prefix format"""
    try:
        ipaddress.IPv6Network(prefix, strict=False)
        return True
    except (ipaddress.AddressValueError, ValueError):
        return False


def is_valid_ipv6_address(address):
    """Validate IPv6 address format"""
    try:
        ipaddress.IPv6Address(address)
        return True
    except (ipaddress.AddressValueError, ValueError):
        return False


def interface_exists(config_db, interface_name):
    """Check if interface exists in PORT, PORTCHANNEL, or VLAN table"""
    if interface_name.startswith("Ethernet"):
        interfaces = config_db.get_table('PORT')
    elif interface_name.startswith("PortChannel"):
        interfaces = config_db.get_table('PORTCHANNEL')
    elif interface_name.startswith("Vlan"):
        interfaces = config_db.get_table('VLAN')
    else:
        return False

    return interface_name in interfaces


def vrf_exists(config_db, vrf_name):
    """Check if VRF exists"""
    if vrf_name == 'default':
        return True

    vrfs = config_db.get_table('VRF')
    return vrf_name in vrfs


#
# 'srv6' group ('config srv6 ...')
#
@click.group(cls=clicommon.AliasedGroup, name='srv6')
def srv6():
    """SRv6-related configuration tasks"""
    pass


#
# 'locator' group ('config srv6 locator ...')
#
@srv6.group(cls=clicommon.AliasedGroup, name='locator')
def locator():
    """SRv6 locator configuration"""
    pass


@locator.command('add')
@click.argument('name', metavar='<locator_name>', required=True)
@click.argument('prefix', metavar='<ipv6_prefix>', required=True)
@click.option('--block-len', type=click.IntRange(1, 128), help='Block length (1-128)')
@click.option('--node-len', type=click.IntRange(0, 128), help='Node length (0-128)')
@click.option('--function-len', type=click.IntRange(0, 128), help='Function length (0-128)')
@click.option('--argument-len', type=click.IntRange(0, 128), help='Argument length (0-128)')
@click.option('--vrf', metavar='<vrf_name>', help='VRF name')
@click.option('--full-sid', is_flag=True,
              help='Configure as a full-SID locator (default: uSID)')
@clicommon.pass_db
def add_locator(db, name, prefix, block_len, node_len, function_len, argument_len, vrf, full_sid):
    """Add SRv6 locator"""
    ctx = click.get_current_context()
    config_db = ValidatedConfigDBConnector(db.cfgdb)

    # Validate IPv6 prefix format first to get prefix_len for default calculation
    try:
        prefix_network = ipaddress.IPv6Network(prefix, strict=False)
        prefix_len = prefix_network.prefixlen
    except (ipaddress.AddressValueError, ValueError):
        ctx.fail(f"Invalid IPv6 prefix: {prefix}")

    if block_len is None:
        ctx.fail("Block length must be specified")

    # Apply default values
    # node_len defaults to remaining bits to satisfy: block_len + node_len = prefix_len
    node_len = node_len if node_len is not None else (prefix_len - block_len)
    function_len = function_len if function_len is not None else 16
    argument_len = argument_len if argument_len is not None else 0

    if ADHOC_VALIDATION:
        # Validate block_len + node_len == prefix_length
        if block_len + node_len != prefix_len:
            ctx.fail(f"Sum of block_len ({block_len}) + node_len ({node_len}) must equal prefix length ({prefix_len})")

        # Validate node_len is non-negative
        if node_len < 0:
            ctx.fail(f"Node length cannot be negative (block_len {block_len} exceeds prefix length {prefix_len})")

        # Validate VRF if specified
        if vrf and not vrf_exists(db.cfgdb, vrf):
            ctx.fail(f"VRF {vrf} does not exist")

        if function_len > MAX_FUNC_LEN:
            ctx.fail(
                f"func_len ({function_len}) exceeds the supported maximum of {MAX_FUNC_LEN}"
            )

        # Validate length sum constraint (block + node + function + argument <= 128)
        total_len = block_len + node_len + function_len + argument_len
        if total_len > 128:
            ctx.fail(f"Sum of block_len + node_len + function_len + argument_len ({total_len}) exceeds 128")

    # Check if locator already exists
    locator_existed = False
    existing_locators = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_LOCATORS_TABLE)
    if name in existing_locators:
        locator_existed = True

    # Build the entry dict
    entry = {
        'prefix': prefix,
        'block_len': str(block_len),
        'node_len': str(node_len),
        'func_len': str(function_len),
        'arg_len': str(argument_len)
    }

    if vrf:
        entry['vrf'] = vrf
    if full_sid:
        entry['full_sid'] = 'true'

    try:
        config_db.set_entry(CONFIG_DB_SRV6_MY_LOCATORS_TABLE, name, entry)
        if locator_existed:
            click.echo(f"Locator {name} configuration updated successfully")
        else:
            click.echo(f"Locator {name} added successfully")
    except ValueError as e:
        ctx.fail(f"Failed to add Locator {name}. Error: {e}")


@locator.command('del')
@click.argument('name', metavar='<locator_name>', required=True)
@clicommon.pass_db
def del_locator(db, name):
    """Delete SRv6 locator"""
    ctx = click.get_current_context()
    config_db = ValidatedConfigDBConnector(db.cfgdb)

    if ADHOC_VALIDATION:
        # Check if locator exists
        existing_locators = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_LOCATORS_TABLE)
        if name not in existing_locators:
            ctx.fail(f"Locator {name} does not exist")

        # Check if any SIDs are using this locator
        existing_sids = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_SIDS_TABLE)
        for sid_key in existing_sids.keys():
            if isinstance(sid_key, tuple) and len(sid_key) >= 2:
                if sid_key[0] == name:
                    ctx.fail(f"Cannot delete locator {name}: SID {sid_key[1]} is using it")

    try:
        config_db.set_entry(CONFIG_DB_SRV6_MY_LOCATORS_TABLE, name, None)
        click.echo(f"Locator {name} deleted successfully")
    except ValueError as e:
        ctx.fail(f"Failed to delete Locator {name}. Error: {e}")


#
# 'static-sid' group ('config srv6 static-sid ...')
#
@srv6.group(cls=clicommon.AliasedGroup, name='static-sid')
def static_sid():
    """SRv6 static SID configuration"""
    pass


@static_sid.command('add')
@click.argument('sid', metavar='<ipv6_prefix>', required=True)
@click.argument('locator', metavar='<locator_name>', required=True)
@click.argument('action', metavar='<action>', required=True, type=click.Choice(VALID_ACTIONS))
@click.option('--vrf', metavar='<vrf_name>', help='VRF name')
@click.option('--interface', metavar='<interface_name>', help='Interface for End.X or uA actions')
@click.option('--adjacency', metavar='<ipv6_address>', help='IPv6 adjacency address')
@clicommon.pass_db
def add_static_sid(db, sid, locator, action, vrf, interface, adjacency):
    """Add SRv6 static SID"""
    ctx = click.get_current_context()
    config_db = ValidatedConfigDBConnector(db.cfgdb)

    if ADHOC_VALIDATION:
        # Validate IPv6 prefix format
        if not is_valid_ipv6_prefix(sid):
            ctx.fail(f"Invalid IPv6 prefix: {sid}")

        # Check if locator exists
        existing_locators = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_LOCATORS_TABLE)
        if locator not in existing_locators:
            ctx.fail(f"Locator {locator} does not exist")

        # Validate that vrf is provided for actions that require it
        if action in VRF_REQUIRED_ACTIONS:
            if not vrf:
                ctx.fail(f"VRF is mandatory for action {action}")

        # Validate that interface is provided for actions that require it
        if action in INTERFACE_REQUIRED_ACTIONS:
            if not interface:
                ctx.fail(f"Interface is mandatory for action {action}")

        # Validate interface exists if specified
        if interface and not interface_exists(db.cfgdb, interface):
            ctx.fail(f"Interface {interface} does not exist")

        # Validate VRF if specified
        if vrf and not vrf_exists(db.cfgdb, vrf):
            ctx.fail(f"VRF {vrf} does not exist")

        # Validate adjacency IPv6 address if specified
        if adjacency and not is_valid_ipv6_address(adjacency):
            ctx.fail(f"Invalid IPv6 adjacency address: {adjacency}")

        # Validate prefix length for non-uSID actions
        try:
            sid_network = ipaddress.IPv6Network(sid, strict=False)
            if action not in USID_ACTIONS and sid_network.prefixlen != 128:
                ctx.fail(f"Prefix length must be /128 for action {action}, got /{sid_network.prefixlen}")
        except ValueError:
            ctx.fail(f"Invalid IPv6 prefix: {sid}")

        # Validate uSID consistency with locator. uSID (micro-segment) is the
        # default; a locator is full-SID only when it sets 'full_sid' to 'true'
        locator_data = existing_locators[locator]
        is_usid_locator = locator_data.get('full_sid', 'false').lower() != 'true'
        is_usid_action = action in USID_ACTIONS

        if is_usid_action != is_usid_locator:
            if is_usid_action:
                ctx.fail(f"Cannot configure uSID action {action} with non-uSID locator {locator}")
            else:
                ctx.fail(f"Cannot configure non-uSID action {action} with uSID locator {locator}")

        # Validate supernet relationship between locator and SID
        locator_prefix = locator_data['prefix']
        locator_network = ipaddress.IPv6Network(locator_prefix, strict=False)

        if action in USID_ACTIONS:
            # For uSID: validate using locator's block_len only
            block_len = int(locator_data.get('block_len', 0))
            if block_len == 0:
                ctx.fail(f"Locator {locator} does not have block_len configured")

            # uN is the node SID itself and carries no function bits: its prefix
            # length must equal block_len + node_len so the programmed my_sid has
            # function_len == 0.
            if action == 'uN':
                node_len = int(locator_data.get('node_len', 16))
                expected_len = block_len + node_len
                if sid_network.prefixlen != expected_len:
                    ctx.fail(
                        f"uN SID prefix length must equal block_len + node_len "
                        f"({block_len} + {node_len} = {expected_len}), got "
                        f"/{sid_network.prefixlen} (function_len must be 0)")

            # Create network with locator's base address and block_len as prefix length
            effective_locator_network = ipaddress.IPv6Network(
                f"{locator_network.network_address}/{block_len}",
                strict=False
            )

            if not (sid_network.subnet_of(effective_locator_network) or
                    sid_network.network_address in effective_locator_network):
                ctx.fail(f"SID {sid} is not within uSID locator block {effective_locator_network}")
        else:
            # For non-uSID: validate locator prefix is supernet of SID prefix
            if not (sid_network.subnet_of(locator_network) or
                    sid_network.network_address in locator_network):
                ctx.fail(f"SID {sid} is not within locator prefix {locator_network}")

    # Check if SID already exists
    sid_existed = False
    existing_sids = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_SIDS_TABLE)
    if (locator, sid) in existing_sids:
        sid_existed = True

    # Build the entry dict
    entry = {'action': action}

    if vrf:
        entry['decap_vrf'] = vrf
    if interface:
        entry['interface'] = interface
    if adjacency:
        entry['adj'] = adjacency

    try:
        config_db.set_entry(CONFIG_DB_SRV6_MY_SIDS_TABLE, (locator, sid), entry)
        if sid_existed:
            click.echo(f"Static SID {sid} configuration updated successfully")
        else:
            click.echo(f"Static SID {sid} added successfully")
    except ValueError as e:
        ctx.fail(f"Failed to add static SID {sid}. Error: {e}")


@static_sid.command('del')
@click.argument('sid', metavar='<ipv6_prefix>', required=True)
@click.argument('locator', metavar='<locator_name>', required=True)
@clicommon.pass_db
def del_static_sid(db, sid, locator):
    """Delete SRv6 static SID"""
    ctx = click.get_current_context()
    config_db = ValidatedConfigDBConnector(db.cfgdb)

    if ADHOC_VALIDATION:
        # Check if SID exists
        existing_sids = db.cfgdb.get_table(CONFIG_DB_SRV6_MY_SIDS_TABLE)
        sid_key = (locator, sid)
        if sid_key not in existing_sids:
            ctx.fail(f"SID {sid} with locator {locator} does not exist")

    try:
        config_db.set_entry(CONFIG_DB_SRV6_MY_SIDS_TABLE, (locator, sid), None)
        click.echo(f"Static SID {sid} deleted successfully")
    except ValueError as e:
        ctx.fail(f"Failed to delete static SID {sid}. Error: {e}")


#
# 'global' group ('config srv6 global ...')
#
@srv6.group(cls=clicommon.AliasedGroup, name='global')
def srv6_global():
    """SRv6 global configuration"""
    pass


@srv6_global.command('device_encap_mode')
@click.argument('mode', type=click.Choice(VALID_ENCAP_MODES))
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt')
@clicommon.pass_db
def device_encap_mode(db, mode, yes):
    """Set SRv6 device encapsulation mode (regular/reduced/all).

    The orchagent reads this value once at init to program the SAI
    SID-list type attribute, so applying a new mode restarts the swss
    container (brief data-plane interruption). GCU's SRV6_GLOBAL restart
    rule restarts swss once the patch is applied.
    """
    ctx = click.get_current_context()

    # Check current value — skip if unchanged (no restart needed)
    current = db.cfgdb.get_entry(CONFIG_DB_SRV6_GLOBAL_TABLE, 'default')
    old_mode = current.get('device_encap_mode', '')
    if old_mode == mode:
        click.echo(f"device_encap_mode is already set to '{mode}'")
        return

    # Build JSON patch. Four cases:
    # 1. 'default' entry has device_encap_mode → replace just that field
    #    (preserves other fields within the entry)
    # 2. 'default' entry exists without the field (YANG default, e.g. after
    #    deploy-mg) → add just the field; RFC 6902 'replace' fails on a
    #    missing member
    # 3. Table exists but 'default' doesn't → add just the entry (avoids
    #    overwriting sibling entries; per RFC 6902, op=add on an existing
    #    member replaces it)
    # 4. Table doesn't exist at all → create the table with the default entry
    if current and 'device_encap_mode' in current:
        patch_ops = [{"op": "replace",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/device_encap_mode",
                      "value": mode}]
    elif current:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/device_encap_mode",
                      "value": mode}]
    elif db.cfgdb.get_table(CONFIG_DB_SRV6_GLOBAL_TABLE):
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default",
                      "value": {'device_encap_mode': mode}}]
    else:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}",
                      "value": {"default": {'device_encap_mode': mode}}}]

    gcu_patch = jsonpatch.JsonPatch(patch_ops)

    # YANG validation (preflight) — delegate to
    # generic_config_updater/main.py:validate_patch() which is the same
    # preflight used by `config apply-patch`. It loads platform YANG
    # deviations from /usr/local/platform-yang-models and rejects values
    # that violate the per-platform enum (e.g. 'all' on DNX). Run this
    # BEFORE the confirm prompt so the user isn't asked to confirm a
    # change that will be rejected anyway.
    # Lazy import to avoid circular dependency at module load time.
    from generic_config_updater.main import validate_patch, get_all_running_config
    try:
        all_running_config = get_all_running_config()
        validate_patch(patch_ops, all_running_config)
    except Exception as e:
        ctx.fail(f"Failed to validate device_encap_mode='{mode}'. Error: {e}")

    # Confirm the disruptive change
    if not yes:
        click.echo("Changing device_encap_mode will restart the swss container.")
        click.echo("This will cause a brief data-plane interruption.")
        click.confirm("Continue?", abort=True)

    # Apply via GCU — its SRV6_GLOBAL restart rule restarts swss.
    try:
        GenericUpdater().apply_patch(patch=gcu_patch,
                                     config_format=ConfigFormat.CONFIGDB,
                                     verbose=False,
                                     dry_run=False,
                                     ignore_non_yang_tables=False,
                                     ignore_paths=None,
                                     sort=False)
    except Exception as e:
        ctx.fail(f"Failed to set device_encap_mode to '{mode}'. Error: {e}")

    click.echo(f"device_encap_mode set to '{mode}'")


@srv6_global.command('device_srv6_enabled')
@click.argument('value', type=click.Choice(['true', 'false']))
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompt')
@clicommon.pass_db
def device_srv6_enabled(db, value, yes):
    """Enable or disable SRv6. Restarts swss to apply."""
    ctx = click.get_current_context()

    current = db.cfgdb.get_entry(CONFIG_DB_SRV6_GLOBAL_TABLE, 'default')
    if current.get('device_srv6_enabled', '') == value:
        click.echo(f"device_srv6_enabled is already set to '{value}'")
        return

    # SONiC stores YANG booleans as the lowercase strings 'true'/'false'
    # A Python bool serializes as 'True'/'False' and
    # is rejected by libyang in validate_patch().
    if current and 'device_srv6_enabled' in current:
        patch_ops = [{"op": "replace",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/device_srv6_enabled",
                      "value": value}]
    elif current:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/device_srv6_enabled",
                      "value": value}]
    elif db.cfgdb.get_table(CONFIG_DB_SRV6_GLOBAL_TABLE):
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default",
                      "value": {'device_srv6_enabled': value}}]
    else:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}",
                      "value": {"default": {'device_srv6_enabled': value}}}]

    gcu_patch = jsonpatch.JsonPatch(patch_ops)

    from generic_config_updater.main import validate_patch, get_all_running_config
    try:
        validate_patch(patch_ops, get_all_running_config())
    except Exception as e:
        ctx.fail(f"Failed to validate device_srv6_enabled='{value}'. Error: {e}")

    if value == 'true':
        click.echo("Note: enabling SRv6 also turns off IP-in-IP decapsulation.")

    if not yes:
        click.confirm(
            "Changing device_srv6_enabled restarts swss to regenerate the BCM "
            "config and causes a brief data-plane interruption. Continue?",
            abort=True,
        )

    try:
        GenericUpdater().apply_patch(patch=gcu_patch,
                                     config_format=ConfigFormat.CONFIGDB,
                                     verbose=False,
                                     dry_run=False,
                                     ignore_non_yang_tables=False,
                                     ignore_paths=None,
                                     sort=False)
    except Exception as e:
        ctx.fail(f"Failed to set device_srv6_enabled to '{value}'. Error: {e}")

    click.echo(f"device_srv6_enabled set to '{value}'")


@srv6_global.command('encap_source_address')
@click.argument('address', metavar='<ipv6_address>')
@clicommon.pass_db
def encap_source_address(db, address):
    """Set SRv6 global encapsulation source address.

    Applied live by bgpcfgd via vtysh ("segment-routing srv6 encapsulation
    source-address ..."); unlike device_encap_mode, this does NOT restart
    swss — the GCU SRV6_GLOBAL restart rule does not cover this field.
    """
    ctx = click.get_current_context()

    if not is_valid_ipv6_address(address):
        ctx.fail(f"Invalid IPv6 address: {address}")

    current = db.cfgdb.get_entry(CONFIG_DB_SRV6_GLOBAL_TABLE, 'default')
    if current.get('encap_source_address', '') == address:
        click.echo(f"encap_source_address is already set to '{address}'")
        return

    # Same 3-case patch shape as device_encap_mode.
    if current and 'encap_source_address' in current:
        patch_ops = [{"op": "replace",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/encap_source_address",
                      "value": address}]
    elif current:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/encap_source_address",
                      "value": address}]
    elif db.cfgdb.get_table(CONFIG_DB_SRV6_GLOBAL_TABLE):
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default",
                      "value": {'encap_source_address': address}}]
    else:
        patch_ops = [{"op": "add",
                      "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}",
                      "value": {"default": {'encap_source_address': address}}}]

    gcu_patch = jsonpatch.JsonPatch(patch_ops)

    from generic_config_updater.main import validate_patch, get_all_running_config
    try:
        validate_patch(patch_ops, get_all_running_config())
    except Exception as e:
        ctx.fail(f"Failed to validate encap_source_address='{address}'. Error: {e}")

    try:
        GenericUpdater().apply_patch(patch=gcu_patch,
                                     config_format=ConfigFormat.CONFIGDB,
                                     verbose=False,
                                     dry_run=False,
                                     ignore_non_yang_tables=False,
                                     ignore_paths=None,
                                     sort=False)
    except Exception as e:
        ctx.fail(f"Failed to set encap_source_address to '{address}'. Error: {e}")

    click.echo(f"encap_source_address set to '{address}'")


#
# 'del' group ('config srv6 global del ...') — for clearing optional
# scalar fields whose absence has a defined meaning (e.g.
# encap_source_address). Set-only fields with YANG defaults (e.g.
# device_encap_mode) intentionally have no del path.
#
@srv6_global.group(cls=clicommon.AliasedGroup, name='del')
def srv6_global_del():
    """Delete SRv6 global configuration fields"""
    pass


@srv6_global_del.command('encap_source_address')
@clicommon.pass_db
def del_encap_source_address(db):
    """Clear SRv6 global encapsulation source address.

    Removes encap_source_address from SRV6_GLOBAL|default; bgpcfgd emits
    'no source-address' to FRR via vtysh — no swss restart.
    """
    ctx = click.get_current_context()

    current = db.cfgdb.get_entry(CONFIG_DB_SRV6_GLOBAL_TABLE, 'default')
    if 'encap_source_address' not in current:
        click.echo("encap_source_address is not configured")
        return

    patch_ops = [{"op": "remove",
                  "path": f"/{CONFIG_DB_SRV6_GLOBAL_TABLE}/default/encap_source_address"}]
    gcu_patch = jsonpatch.JsonPatch(patch_ops)

    from generic_config_updater.main import validate_patch, get_all_running_config
    try:
        validate_patch(patch_ops, get_all_running_config())
    except Exception as e:
        ctx.fail(f"Failed to validate removal of encap_source_address. Error: {e}")

    try:
        GenericUpdater().apply_patch(patch=gcu_patch,
                                     config_format=ConfigFormat.CONFIGDB,
                                     verbose=False,
                                     dry_run=False,
                                     ignore_non_yang_tables=False,
                                     ignore_paths=None,
                                     sort=False)
    except Exception as e:
        ctx.fail(f"Failed to clear encap_source_address. Error: {e}")

    click.echo("encap_source_address cleared")
