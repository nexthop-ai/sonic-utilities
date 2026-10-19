import click
from sonic_py_common import multi_asic

import utilities_common.cli as clicommon
import utilities_common.constants as constants
import utilities_common.multi_asic as multi_asic_util
from .vtysh_helper import vtysh_command


def run_isis_show(subcommand, args=(), vrf=None, namespace=None, verbose=False):
    """Run 'show isis [vrf VRF] SUBCOMMAND [ARGS]' against the FRR instance of the namespace."""
    vtysh_cmd = "show isis"
    if vrf:
        # FRR expects the vrf keyword before the subcommand, not after it.
        vtysh_cmd += " vrf {}".format(vrf)
    vtysh_cmd = " ".join([vtysh_cmd, subcommand] + list(args))

    cmd = ['sudo', constants.RVTYSH_COMMAND]
    if namespace and namespace != multi_asic.DEFAULT_NAMESPACE:
        cmd += ['-n', str(multi_asic.get_asic_id_from_name(namespace))]
    cmd += ['-c', vtysh_cmd]
    clicommon.run_command(cmd, display_cmd=verbose)


def isis_show_options(func):
    """Options shared by every 'show isis' subcommand; extra args are passed through to FRR."""
    func = click.option('--verbose', is_flag=True, help="Enable verbose output")(func)
    # Built by hand rather than with multi_asic_click_option_namespace(required=...), which release
    # branches such as 202511 do not have.
    func = click.option('--namespace', '-n', 'namespace', default=None, show_default=False,
                        required=multi_asic.is_multi_asic(),
                        type=multi_asic_util.LazyChoice(multi_asic_util.multi_asic_ns_choices),
                        help='Namespace name')(func)
    func = click.option('--vrf', default=None, help="VRF name, or 'all'")(func)
    return click.argument('args', nargs=-1, required=False)(func)


#
# 'isis' group ('show isis ...')
#
@click.group(cls=clicommon.AliasedGroup)
def isis():
    """Show IS-IS operational state from FRR"""
    pass


@isis.command(cls=vtysh_command("show isis summary"))
@isis_show_options
def summary(args, vrf, namespace, verbose):
    """Show IS-IS instance summary"""
    run_isis_show("summary", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis interface"))
@isis_show_options
def interface(args, vrf, namespace, verbose):
    """Show IS-IS interfaces [detail|INTERFACE] [json]"""
    if args and args[0] not in ("detail", "json") and clicommon.get_interface_naming_mode() == "alias":
        args = (clicommon.InterfaceAliasConverter().alias_to_name(args[0]),) + tuple(args[1:])
    run_isis_show("interface", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis neighbor"))
@isis_show_options
def neighbor(args, vrf, namespace, verbose):
    """Show IS-IS neighbor adjacencies [detail|SYSTEM-ID] [json]"""
    run_isis_show("neighbor", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis hostname"))
@isis_show_options
def hostname(args, vrf, namespace, verbose):
    """Show IS-IS dynamic hostname mapping"""
    run_isis_show("hostname", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis database"))
@isis_show_options
def database(args, vrf, namespace, verbose):
    """Show IS-IS link state database [detail] [LSP-ID] [json]"""
    run_isis_show("database", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis topology"))
@isis_show_options
def topology(args, vrf, namespace, verbose):
    """Show IS-IS SPF topology [level-1|level-2] [json]"""
    run_isis_show("topology", args, vrf, namespace, verbose)


@isis.command(cls=vtysh_command("show isis route"))
@isis_show_options
def route(args, vrf, namespace, verbose):
    """Show IS-IS routing table [level-1|level-2] [backup] [json]"""
    run_isis_show("route", args, vrf, namespace, verbose)


@isis.command('spf-delay-ietf', cls=vtysh_command("show isis spf-delay-ietf"))
@isis_show_options
def spf_delay_ietf(args, vrf, namespace, verbose):
    """Show IS-IS SPF delay (RFC 8405) state"""
    run_isis_show("spf-delay-ietf", args, vrf, namespace, verbose)


#
# 'fast-reroute' subgroup ('show isis fast-reroute ...')
#
@isis.group('fast-reroute', cls=clicommon.AliasedGroup)
def fast_reroute():
    """Show IS-IS fast reroute information"""
    pass


@fast_reroute.command('summary', cls=vtysh_command("show isis fast-reroute summary"))
@isis_show_options
def fast_reroute_summary(args, vrf, namespace, verbose):
    """Show IS-IS fast reroute summary [level-1|level-2]"""
    run_isis_show("fast-reroute summary", args, vrf, namespace, verbose)
