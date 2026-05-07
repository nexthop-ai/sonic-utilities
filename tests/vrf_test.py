import os
import sys
from click.testing import CliRunner
from swsscommon.swsscommon import SonicV2Connector
from utilities_common.db import Db
<<<<<<< HEAD

=======
import pytest
from natsort import natsorted
>>>>>>> 11a3089b (NOS-7313: implement "show vrf all" sub-command (#454))
import config.main as config
import show.main as show
import threading

DEFAULT_NAMESPACE = ''
test_path = os.path.dirname(os.path.abspath(__file__))
mock_db_path = os.path.join(test_path, "vrf_input")
mock_db_path_vnet = os.path.join(test_path, "vnet_input")

class TestShowVrf(object):
    @classmethod
    def setup_class(cls):
        print("SETUP")
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    def update_statedb(self, db, db_name, key):
        import time
        time.sleep(0.5)
        db.delete(db_name, key)

    def test_vrf_show(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        db = Db()
        expected_output = """\
VRF     Interfaces
------  ---------------
Vrf1
Vrf101  Ethernet0.10
Vrf102  Eth36.10
        PortChannel0002
        Vlan40
Vrf103  Ethernet4
        Loopback0
        Po0002.101
"""

        result = runner.invoke(show.cli.commands['vrf'], [], obj=db)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert result.output == expected_output

<<<<<<< HEAD
=======
    def test_vrf_show_unconfigured_vrf(self):
        """Test show VRF command failing where the user specifies the wrong VRF"""
        runner = CliRunner()
        db = Db()

        vrf_name = "Vrf-null"
        result = runner.invoke(show.cli.commands['vrf'], [vrf_name], obj=db)

        assert result.exit_code != 0
        assert f"Error: VRF {vrf_name} is not configured." in result.output

    def test_vrf_show_specified_interface(self):
        """Test show VRF command returns specified interface if found"""
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        vrf_name = "Vrf1"

        result = runner.invoke(show.cli.commands['vrf'], [vrf_name])
        print(result.output)
        assert result.exit_code == 0

        assert vrf_name in result.output
        assert "Vrf101" not in result.output
        assert "Vrf102" not in result.output
        assert "Vrf103" not in result.output

    def test_vrf_show_summary_default_only(self, default_vrf_only):
        runner = CliRunner()
        result = runner.invoke(show.cli.commands['vrf'], ['summary'])
        assert result.exit_code == 0
        assert "All interfaces are in default VRF.\n" == result.output

    def test_vrf_show_summary(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        db = Db()
        result = runner.invoke(show.cli.commands['vrf'], ['summary'], obj=db)
        assert result.exit_code == 0

        # check table columns
        assert "VRF" in result.output
        assert "Description" in result.output
        assert "Interfaces" not in result.output

        # check description presence
        assert "Development VRF with a long description" in result.output
        assert "Default VRF" in result.output

        # check correct description formatting
        vrf_table = db.cfgdb.get_table('VRF')
        self.assert_correct_multiline_desc(result.output, vrf_table, "Vrf102")

        # check VRF ordering
        vrfs_in_order = ["Vrf1", "Vrf101", "Vrf102", "Vrf103", "Default"]
        for i in range(1, len(vrfs_in_order)):
            first_vrf_index = result.output.index(vrfs_in_order[i - 1])
            second_vrf_index = result.output.index(vrfs_in_order[i])
            assert first_vrf_index < second_vrf_index

    def test_vrf_show_default(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        db = Db()
        result = runner.invoke(show.cli.commands['vrf'], ['default'], obj=db)
        assert result.exit_code == 0

        # check table columns
        assert "VRF" in result.output
        assert "Description" in result.output
        assert "Interfaces" in result.output

        # check interface ordering
        assert result.output.index("Ethernet123") < result.output.index("PortChannel1234")

        # check non-default VRFs not in output
        assert "Vrf1" not in result.output
        assert "Vrf101" not in result.output
        assert "Vrf102" not in result.output
        assert "Vrf103" not in result.output

        # check interfaces in non-default VRFs do not show up
        table_names = ['INTERFACE', 'LOOPBACK_INTERFACE', 'VLAN_INTERFACE',
                       'PORTCHANNEL_INTERFACE', 'VLAN_SUB_INTERFACE']
        for table_name in table_names:
            table = db.cfgdb.get_table(table_name)
            for intf, attr in table.items():
                if 'vrf_name' in attr:
                    assert intf not in result.output

    def test_vrf_show_all(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        db = Db()
        result = runner.invoke(show.cli.commands['vrf'], ['all'], obj=db)
        assert result.exit_code == 0

        # check table columns
        assert "VRF" in result.output
        assert "Description" in result.output
        assert "Interfaces" in result.output

        def assert_existence_and_sorted_order(collection):
            for i in range(len(collection)):
                assert collection[i] in result.output
                if i < len(collection) - 1:
                    assert result.output.index(collection[i]) < result.output.index(collection[i + 1])

        # check VRFs exist in table & are ordered properly
        ordered_vrfs = natsorted(db.cfgdb.get_table('VRF')) + ["Default"]
        assert_existence_and_sorted_order(ordered_vrfs)

        def get_vrf_interfaces(vrf='default'):
            table_names = ['INTERFACE', 'LOOPBACK_INTERFACE', 'VLAN_INTERFACE',
                           'PORTCHANNEL_INTERFACE', 'VLAN_SUB_INTERFACE']
            interfaces = []
            for table_name in table_names:
                table = db.cfgdb.get_table(table_name)
                for intf, attr in table.items():
                    if vrf == 'default' and 'vrf_name' not in attr:
                        interfaces.append(intf)
                    elif 'vrf_name' in attr and attr['vrf_name'] == vrf:
                        interfaces.append(intf)
            return interfaces

        # check all interfaces are enumerated and in the expected order
        interfaces = []
        for vrf in ordered_vrfs:
            interfaces += sorted(get_vrf_interfaces(vrf=vrf))
        interfaces += sorted(get_vrf_interfaces(vrf='default'))
        assert_existence_and_sorted_order(interfaces)

>>>>>>> 11a3089b (NOS-7313: implement "show vrf all" sub-command (#454))
    def test_vrf_bind_unbind(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()
        db = Db()
        expected_output = """\
VRF     Interfaces
------  ---------------
Vrf1
Vrf101  Ethernet0.10
Vrf102  Eth36.10
        PortChannel0002
        Vlan40
Vrf103  Ethernet4
        Loopback0
        Po0002.101
"""

        result = runner.invoke(show.cli.commands['vrf'], [], obj=db)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert result.output == expected_output


        vrf_obj = {'config_db':db.cfgdb, 'namespace':db.db.namespace}

        expected_output_unbind = "Interface Ethernet4 IP disabled and address(es) removed due to unbinding VRF.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Ethernet4"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert 'Ethernet4' not in db.cfgdb.get_table('INTERFACE')
        assert result.output == expected_output_unbind

        expected_output_unbind = "Interface Loopback0 IP disabled and address(es) removed due to unbinding VRF.\n"

        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Loopback0"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert 'Loopback0' not in db.cfgdb.get_table('LOOPBACK_INTERFACE')
        assert result.output == expected_output_unbind

        expected_output_unbind = "Interface Vlan40 IP disabled and address(es) removed due to unbinding VRF.\n"

        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Vlan40"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert 'Vlan40' not in db.cfgdb.get_table('VLAN_INTERFACE')
        assert result.output == expected_output_unbind

        expected_output_unbind = "Interface PortChannel0002 IP disabled and address(es) removed due to unbinding VRF.\n"

        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["PortChannel0002"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert 'PortChannel002' not in db.cfgdb.get_table('PORTCHANNEL_INTERFACE')
        assert result.output == expected_output_unbind

        vrf_obj = {'config_db':db.cfgdb, 'namespace':DEFAULT_NAMESPACE}
        state_db = SonicV2Connector(use_unix_socket_path=True, namespace='')
        state_db.connect(state_db.STATE_DB, False)
        _hash = "INTERFACE_TABLE|Eth36.10"
        state_db.set(db.db.STATE_DB, _hash, "state", "ok")
        vrf_obj['state_db'] = state_db

        expected_output_unbind = "Interface Eth36.10 IP disabled and address(es) removed due to unbinding VRF.\n"
        T1 = threading.Thread( target = self.update_statedb, args = (state_db, db.db.STATE_DB, _hash))  
        T1.start()
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Eth36.10"], obj=vrf_obj)
        T1.join()
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert ('vrf_name', 'Vrf102') not in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Eth36.10']
        assert result.output == expected_output_unbind

        vrf_obj = {'config_db':db.cfgdb, 'namespace':DEFAULT_NAMESPACE}

        expected_output_unbind = "Interface Ethernet0.10 IP disabled and address(es) removed due to unbinding VRF.\n"

        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Ethernet0.10"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert ('vrf_name', 'Vrf101') not in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Ethernet0.10']
        assert result.output == expected_output_unbind

        expected_output_unbind = "Interface Po0002.101 IP disabled and address(es) removed due to unbinding VRF.\n"

        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["unbind"], ["Po0002.101"], obj=vrf_obj)

        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert ('vrf_name', 'Vrf103') not in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Po0002.101']
        assert result.output == expected_output_unbind

        expected_output_bind = "Interface Ethernet0 IP disabled and address(es) removed due to binding VRF Vrf1.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Ethernet0", "Vrf1"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf1') in db.cfgdb.get_table('INTERFACE')['Ethernet0']['vrf_name']

        expected_output_bind = "Interface Loopback0 IP disabled and address(es) removed due to binding VRF Vrf101.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Loopback0", "Vrf101"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf101') in db.cfgdb.get_table('LOOPBACK_INTERFACE')['Loopback0']['vrf_name']

        expected_output_bind = "Interface Vlan40 IP disabled and address(es) removed due to binding VRF Vrf101.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Vlan40", "Vrf101"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf101') in db.cfgdb.get_table('VLAN_INTERFACE')['Vlan40']['vrf_name']

        expected_output_bind = "Interface PortChannel0002 IP disabled and address(es) removed due to binding VRF Vrf101.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["PortChannel0002", "Vrf101"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf101') in db.cfgdb.get_table('PORTCHANNEL_INTERFACE')['PortChannel0002']['vrf_name']

        expected_output_bind = "Interface Eth36.10 IP disabled and address(es) removed due to binding VRF Vrf102.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Eth36.10", "Vrf102"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf102') in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Eth36.10']['vrf_name']

        expected_output_bind = "Interface Ethernet0.10 IP disabled and address(es) removed due to binding VRF Vrf103.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Ethernet0.10", "Vrf103"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf103') in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Ethernet0.10']['vrf_name']

        expected_output_bind = "Interface Po0002.101 IP disabled and address(es) removed due to binding VRF Vrf1.\n"
        result = runner.invoke(config.config.commands["interface"].commands["vrf"].commands["bind"], ["Po0002.101", "Vrf1"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_bind
        assert ('Vrf1') in db.cfgdb.get_table('VLAN_SUB_INTERFACE')['Po0002.101']['vrf_name']

        jsonfile_config = os.path.join(mock_db_path, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config

        expected_output = """\
VRF     Interfaces
------  ---------------
Vrf1
Vrf101  Ethernet0.10
Vrf102  Eth36.10
        PortChannel0002
        Vlan40
Vrf103  Ethernet4
        Loopback0
        Po0002.101
"""

        result = runner.invoke(show.cli.commands['vrf'], [], obj=db)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert result.output == expected_output

    def test_vrf_add_del(self):
        runner = CliRunner()
        db = Db()
        vrf_obj = {'config_db':db.cfgdb, 'namespace':db.db.namespace}

        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["Vrf100"], obj=vrf_obj)
        assert ('Vrf100') in db.cfgdb.get_table('VRF')
        assert result.exit_code == 0

        # Add dummy VLAN and DHCP relay config using the VRF
        vlan = "Vlan100"
        server_ip = "192.0.2.1"
        db.cfgdb.mod_entry("VLAN", vlan, {})

        # Enable has_sonic_dhcpv4_relay flag
        db.cfgdb.set_entry("DEVICE_METADATA", "localhost", {"has_sonic_dhcpv4_relay": "True"})

        db.cfgdb.set_entry("DHCPV4_RELAY", vlan, {
            "dhcpv4_servers": [server_ip],
            "server_vrf": "Vrf100",
            "link_selection": "enable",
            "vrf_selection": "enable",
            "server_id_override": "enable"
        })

        assert result.exit_code == 0

        # Attempt to delete the VRF in use by DHCPv4_RELAY ὀ~T should failfa
        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["Vrf100"], obj=vrf_obj)
        assert result.exit_code != 0
        assert "VRF 'Vrf100' is in use for dhcp_relay configurations for Vlan100" in result.output

        # Clean up the DHCP config to allow VRF deletion
        db.cfgdb.set_entry("DHCPV4_RELAY", vlan, None)
        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["Vrf100"], obj=vrf_obj)
        assert result.exit_code == 0
        assert "Vrf100" not in db.cfgdb.get_table("VRF")

        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["Vrf1"], obj=vrf_obj)
        assert "VRF Vrf1 already exists!" in result.output
        assert ('Vrf1') in db.cfgdb.get_table('VRF')
        assert result.exit_code != 0

        expected_output_del = "VRF Vrf1 deleted and all associated IP addresses removed.\n"
        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["Vrf1"], obj=vrf_obj)
        assert result.exit_code == 0
        assert result.output == expected_output_del
        assert ('Vrf1') not in db.cfgdb.get_table('VRF')

        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["Vrf200"], obj=vrf_obj)
        assert result.exit_code != 0
        assert ('Vrf200') not in db.cfgdb.get_table('VRF')
        assert "VRF Vrf200 does not exist!" in result.output

    def test_invalid_vrf_name(self):
        db = Db()
        runner = CliRunner()
        obj = {'config_db':db.cfgdb}
        expected_output = """\
Error: 'vrf_name' must begin with 'Vrf' or named 'mgmt'/'management' in case of ManagementVRF.
"""
        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["vrf-blue"], obj=obj)
        assert result.exit_code != 0
        assert ('vrf-blue') not in db.cfgdb.get_table('VRF')
        assert expected_output in result.output

        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["VRF2"], obj=obj)
        assert result.exit_code != 0
        assert ('VRF2') not in db.cfgdb.get_table('VRF')
        assert expected_output in result.output

        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["VrF10"], obj=obj)
        assert result.exit_code != 0
        assert ('VrF10') not in db.cfgdb.get_table('VRF')
        assert expected_output in result.output

        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["vrf-blue"], obj=obj)
        assert result.exit_code != 0
        assert expected_output in result.output

        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["VRF2"], obj=obj)
        assert result.exit_code != 0
        assert expected_output in result.output

        result = runner.invoke(config.config.commands["vrf"].commands["del"], ["VrF10"], obj=obj)
        assert result.exit_code != 0
        assert expected_output in result.output

        expected_output = """\
Error: 'vrf_name' length should not exceed 15 characters
"""
        result = runner.invoke(config.config.commands["vrf"].commands["add"], ["VrfNameTooLong!!!"], obj=obj)
        assert result.exit_code != 0
        assert ('VrfNameTooLong!!!') not in db.cfgdb.get_table('VRF')
        assert expected_output in result.output


class TestVnet(object):
    @classmethod
    def setup_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "1"
        print("SETUP")

    def test_show_vnet_brief(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path_vnet, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()

        result = runner.invoke(show.cli.commands["vnet"].commands["brief"], [])
        print(result.output)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert "Vnet_2000" in result.output
        assert "1234-56-7890-1234" in result.output
        assert "tunnel1" in result.output

    def test_show_vnet_name(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path_vnet, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()

        result = runner.invoke(show.cli.commands["vnet"].commands["name"], ["Vnet_2000"])
        print(result.output)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert "Vnet_2000" in result.output
        assert "1234-56-7890-1234" in result.output
        assert "Ethernet4" in result.output
        assert "Ethernet0.100" in result.output
        assert "Vlan40" in result.output
        assert "PortChannel0002" in result.output
        assert "Loopback0" in result.output

    def test_show_vnet_guid(self):
        from .mock_tables import dbconnector
        jsonfile_config = os.path.join(mock_db_path_vnet, "config_db")
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile_config
        runner = CliRunner()

        result = runner.invoke(show.cli.commands["vnet"].commands["guid"], ["1234-56-7890-1234"])
        print(result.output)
        dbconnector.dedicated_dbs = {}
        assert result.exit_code == 0
        assert "Vnet_2000" in result.output
        assert "1234-56-7890-1234" in result.output
        assert "tunnel1" in result.output
        assert "Ethernet4" in result.output
        assert "Ethernet0.100" in result.output
        assert "Vlan40" in result.output
        assert "PortChannel0002" in result.output
        assert "Loopback0" in result.output

    @classmethod
    def teardown_class(cls):
        print("TEARDOWN")
