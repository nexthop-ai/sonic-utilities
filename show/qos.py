import click
from natsort import natsorted
from tabulate import tabulate

import utilities_common.cli as clicommon

maptype_to_table = {
        "tc-to-pg": {
            "name": "TC_TO_PRIORITY_GROUP_MAP",
            "header": ['tc', 'pg']
        },
        "pfc-to-pg": {
            "name": "PFC_PRIORITY_TO_PRIORITY_GROUP_MAP",
            "header": ['pfc', 'pg']
        },
        "pfc-to-queue": {
            "name": "MAP_PFC_PRIORITY_TO_QUEUE",
            "header": ['pfc', 'queue']
        },
        "dot1p-to-tc": {
            "name": "DOT1P_TO_TC_MAP",
            "header": ['dot1p', 'tc']
        },
        "dscp-to-tc": {
            "name": "DSCP_TO_TC_MAP",
            "header": ['dscp', 'tc']
        },
        "tc-to-queue": {
            "name": "TC_TO_QUEUE_MAP",
            "header": ['tc', 'queue']
        },
        "tc-to-dscp": {
            "name": "TC_TO_DSCP_MAP",
            "header": ['tc', 'dscp']
        },
        "tc-to-dot1p": {
            "name": "TC_TO_DOT1P_MAP",
            "header": ['tc', 'dot1p']
        }
    }

@click.group(cls=clicommon.AliasedGroup)
def qos():
    """Show QOS information"""
    pass


@qos.command()
@click.argument('maptype', type=click.Choice(maptype_to_table.keys(), case_sensitive=True))
@clicommon.pass_db
def map(db, maptype):
    tablename = maptype_to_table[maptype]["name"]
    data = db.cfgdb.get_table(tablename)
    keys = list(data.keys())

    def tablelize(data, header):
        table = []

        for d in natsorted(list(data.keys())):
            r = [d, data[d]]
            table.append(r)

        return table

    for key in keys:
        click.echo('"{0}": {1}'.format(tablename, key))
        header = maptype_to_table[maptype]["header"]
        click.echo('-' * (len(tablename)+len(key)+5))
        click.echo(tabulate(tablelize(data[key], header), header))


@qos.command()
@clicommon.pass_db
def scheduler_policy(db):
    data = db.cfgdb.get_table('SCHEDULER')
    schedulers = list(data.keys())

    for s in schedulers:
        click.echo('Scheduler Policy: {}'.format(s))

        for key, val in data[s].items():
            click.echo('{0}: {1}'.format(key, val))
        click.echo('')


def _resolve_interface_name(ethernet_arg, intfid):
    """Support both 'Ethernet64' and legacy 'Ethernet 64' forms."""
    if intfid is not None:
        if ethernet_arg != 'Ethernet':
            raise click.UsageError("Expected 'Ethernet' followed by a port-id or 'all'.")
        if intfid.lower() == 'all':
            return 'all'
        try:
            int(intfid)
        except ValueError:
            raise click.UsageError("Port id must be an integer or 'all'.")
        return 'Ethernet' + intfid
    if ethernet_arg.lower() == 'all':
        return 'all'
    if not ethernet_arg.startswith('Ethernet'):
        raise click.UsageError("Must be 'all' or a port name like 'Ethernet64'.")
    suffix = ethernet_arg[len('Ethernet'):]
    try:
        int(suffix)
    except ValueError:
        raise click.UsageError("Must be 'all' or a port name like 'Ethernet64'.")
    return ethernet_arg

@qos.command()
@click.argument('ethernet_arg', metavar='<EthernetN|all>', required=True)
@click.argument('intfid', metavar='[port-id]', required=False, default=None)
@clicommon.pass_db
def interface(db, ethernet_arg, intfid):
    interface_name = _resolve_interface_name(ethernet_arg, intfid)
    data = db.cfgdb.get_table('PORT_QOS_MAP')
    portinfos = list(data.keys())

    for p in portinfos:
        if interface_name != 'all' and interface_name != p:
            continue

        click.echo('Interface: {}'.format(p))

        for key, val in data[p].items():
            click.echo('{0}: {1}'.format(key, val))
        click.echo('')


