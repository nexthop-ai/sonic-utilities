import os
from unittest import mock

import pytest
from click.testing import CliRunner

import show.main as show
from show import isis


def rvtysh(vtysh_cmd):
    return ['sudo', 'rvtysh', '-c', vtysh_cmd]


class TestShowIsis:

    @classmethod
    def setup_class(cls):
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    @classmethod
    def teardown_class(cls):
        os.environ["UTILITIES_UNIT_TESTING"] = "0"

    def invoke(self, cmd_path, args=()):
        command = show.cli.commands["isis"]
        for name in cmd_path:
            command = command.commands[name]
        with mock.patch('show.isis.clicommon.run_command') as mock_run:
            result = CliRunner().invoke(command, list(args))
        print(result.output)
        assert result.exit_code == 0, result.output
        return mock_run

    @pytest.mark.parametrize("cmd_path, args, vtysh_cmd", [
        (["summary"], [], "show isis summary"),
        (["summary"], ["json"], "show isis summary json"),
        (["interface"], [], "show isis interface"),
        (["interface"], ["detail"], "show isis interface detail"),
        (["interface"], ["Ethernet0", "json"], "show isis interface Ethernet0 json"),
        (["neighbor"], [], "show isis neighbor"),
        (["neighbor"], ["detail", "json"], "show isis neighbor detail json"),
        (["neighbor"], ["0000.0000.0002"], "show isis neighbor 0000.0000.0002"),
        (["hostname"], [], "show isis hostname"),
        (["database"], [], "show isis database"),
        (["database"], ["detail", "r1.00-00"], "show isis database detail r1.00-00"),
        (["topology"], ["level-2"], "show isis topology level-2"),
        (["route"], ["level-1", "backup", "json"], "show isis route level-1 backup json"),
        (["spf-delay-ietf"], [], "show isis spf-delay-ietf"),
        (["fast-reroute", "summary"], [], "show isis fast-reroute summary"),
        (["fast-reroute", "summary"], ["level-2"], "show isis fast-reroute summary level-2"),
    ])
    def test_show_isis_passthrough(self, cmd_path, args, vtysh_cmd):
        mock_run = self.invoke(cmd_path, args)
        mock_run.assert_called_once_with(rvtysh(vtysh_cmd), display_cmd=False)

    @pytest.mark.parametrize("vrf", ["Vrf1", "all"])
    def test_show_isis_vrf_precedes_subcommand(self, vrf):
        mock_run = self.invoke(["neighbor"], ["--vrf", vrf, "detail"])
        mock_run.assert_called_once_with(rvtysh("show isis vrf {} neighbor detail".format(vrf)), display_cmd=False)

    def test_show_isis_options_after_args(self):
        mock_run = self.invoke(["summary"], ["json", "--vrf", "all"])
        mock_run.assert_called_once_with(rvtysh("show isis vrf all summary json"), display_cmd=False)

    def test_show_isis_fast_reroute_vrf(self):
        mock_run = self.invoke(["fast-reroute", "summary"], ["--vrf", "Vrf1", "level-1"])
        mock_run.assert_called_once_with(rvtysh("show isis vrf Vrf1 fast-reroute summary level-1"),
                                         display_cmd=False)

    def test_show_isis_verbose(self):
        mock_run = self.invoke(["summary"], ["--verbose"])
        mock_run.assert_called_once_with(rvtysh("show isis summary"), display_cmd=True)

    def test_show_isis_interface_alias_mode(self):
        with mock.patch('show.isis.clicommon.get_interface_naming_mode', return_value="alias"), \
                mock.patch('show.isis.clicommon.InterfaceAliasConverter') as mock_converter:
            mock_converter.return_value.alias_to_name.return_value = "Ethernet0"
            mock_run = self.invoke(["interface"], ["etp1", "json"])
        mock_converter.return_value.alias_to_name.assert_called_once_with("etp1")
        mock_run.assert_called_once_with(rvtysh("show isis interface Ethernet0 json"), display_cmd=False)

    def test_show_isis_interface_alias_mode_keyword_untouched(self):
        with mock.patch('show.isis.clicommon.get_interface_naming_mode', return_value="alias"), \
                mock.patch('show.isis.clicommon.InterfaceAliasConverter') as mock_converter:
            mock_run = self.invoke(["interface"], ["detail"])
        mock_converter.return_value.alias_to_name.assert_not_called()
        mock_run.assert_called_once_with(rvtysh("show isis interface detail"), display_cmd=False)

    def test_run_isis_show_namespace(self):
        with mock.patch('show.isis.multi_asic.get_asic_id_from_name', return_value=1), \
                mock.patch('show.isis.clicommon.run_command') as mock_run:
            isis.run_isis_show("summary", namespace="asic1")
        mock_run.assert_called_once_with(['sudo', 'rvtysh', '-n', '1', '-c', 'show isis summary'],
                                         display_cmd=False)

    def test_run_isis_show_default_namespace(self):
        with mock.patch('show.isis.clicommon.run_command') as mock_run:
            isis.run_isis_show("summary", namespace="")
        mock_run.assert_called_once_with(rvtysh("show isis summary"), display_cmd=False)

    def test_show_isis_help_lists_subcommands(self):
        result = CliRunner().invoke(show.cli.commands["isis"], ["--help"])
        assert result.exit_code == 0
        for name in ["summary", "interface", "neighbor", "hostname", "database",
                     "topology", "route", "spf-delay-ietf", "fast-reroute"]:
            assert name in result.output
