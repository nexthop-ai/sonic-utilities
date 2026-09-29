import os
import pytest
import sys
import argparse
from unittest import mock
from deepdiff import DeepDiff
import json

from swsscommon.swsscommon import SonicV2Connector, SonicDBConfig
from sonic_py_common import device_info

from .mock_tables import dbconnector

import config.main as config
from utilities_common.db import Db

test_path = os.path.dirname(os.path.abspath(__file__))
mock_db_path = os.path.join(test_path, "db_migrator_input")
modules_path = os.path.dirname(test_path)
scripts_path = os.path.join(modules_path, "scripts")
sys.path.insert(0, test_path)
sys.path.insert(0, modules_path)
sys.path.insert(0, scripts_path)



def get_sonic_version_info_mlnx():
    return {'asic_type': 'mellanox'}

def version_greater_than(v1, v2):
    # Return True when v1 is later than v2. Otherwise return False.
    if 'master' in v1:
        if 'master' in v2:
            # both are master versions, directly compare.
            return v1 > v2

        # v1 is master verson and v2 is not, v1 is higher
        return True

    if 'master' in v2:
        # v2 is master version and v1 is not.
        return False

    s1 = v1.split('_')
    s2 = v2.split('_')
    if len(s1) == 3:
        # new format version_<barnch>_<ver>
        if len(s2) == 3:
            # Both are new format version string
            return v1 > v2
        return True

    if len(s2) == 3:
        # v2 is new format and v1 is old format.
        return False

    # Both are old format version_a_b_c
    return v1 > v2


def advance_version_for_expected_database(migrated_db, expected_db, last_interested_version):
    # In case there are new db versions greater than the latest one that mellanox buffer migrator is interested,
    # we just advance the database version in the expected database to make the test pass
    expected_dbversion = expected_db.get_entry('VERSIONS', 'DATABASE')
    dbmgtr_dbversion = migrated_db.get_entry('VERSIONS', 'DATABASE')
    if expected_dbversion and dbmgtr_dbversion:
        if expected_dbversion['VERSION'] == last_interested_version and version_greater_than(dbmgtr_dbversion['VERSION'], expected_dbversion['VERSION']):
            expected_dbversion['VERSION'] = dbmgtr_dbversion['VERSION']
            expected_db.set_entry('VERSIONS', 'DATABASE', expected_dbversion)


class TestVersionComparison(object):
    @classmethod
    def setup_class(cls):
        cls.version_comp_list = [
                                  # Old format v.s old format
                                  {'v1': 'version_1_0_1', 'v2': 'version_1_0_2', 'result': False},
                                  {'v1': 'version_1_0_2', 'v2': 'version_1_0_1', 'result': True},
                                  {'v1': 'version_1_0_1', 'v2': 'version_2_0_1', 'result': False},
                                  {'v1': 'version_2_0_1', 'v2': 'version_1_0_1', 'result': True},
                                  # New format v.s old format
                                  {'v1': 'version_1_0_1', 'v2': 'version_202311_01', 'result': False},
                                  {'v1': 'version_202311_01', 'v2': 'version_1_0_1', 'result': True},
                                  {'v1': 'version_1_0_1', 'v2': 'version_master_01', 'result': False},
                                  {'v1': 'version_master_01', 'v2': 'version_1_0_1', 'result': True},
                                  # New format v.s new format
                                  {'v1': 'version_202311_01', 'v2': 'version_202311_02', 'result': False},
                                  {'v1': 'version_202311_02', 'v2': 'version_202311_01', 'result': True},
                                  {'v1': 'version_202305_01', 'v2': 'version_202311_01', 'result': False},
                                  {'v1': 'version_202311_01', 'v2': 'version_202305_01', 'result': True},
                                  {'v1': 'version_202405_01', 'v2': 'version_202411_02', 'result': False},
                                  {'v1': 'version_202411_02', 'v2': 'version_202405_01', 'result': True},
                                  {'v1': 'version_202411_02', 'v2': 'version_202505_01', 'result': False},
                                  {'v1': 'version_202505_01', 'v2': 'version_202411_02', 'result': True},
                                  {'v1': 'version_202505_01', 'v2': 'version_202511_01', 'result': False},
                                  {'v1': 'version_202511_01', 'v2': 'version_202505_01', 'result': True},
                                  {'v1': 'version_202511_01', 'v2': 'version_master_01', 'result': False},
                                  {'v1': 'version_202411_02', 'v2': 'version_master_01', 'result': False},
                                  {'v1': 'version_202311_01', 'v2': 'version_master_01', 'result': False},
                                  {'v1': 'version_master_01', 'v2': 'version_202311_01', 'result': True},
                                  {'v1': 'version_master_01', 'v2': 'version_master_02', 'result': False},
                                  {'v1': 'version_master_02', 'v2': 'version_master_01', 'result': True},
                                ]

    def test_version_comparison(self):
        for rec in self.version_comp_list:
            assert version_greater_than(rec['v1'], rec['v2']) == rec['result'], 'test failed: {}'.format(rec)


class TestMellanoxBufferMigrator(object):
    @classmethod
    def setup_class(cls):
        cls.config_db_tables_to_verify = ['BUFFER_POOL', 'BUFFER_PROFILE', 'BUFFER_PG', 'DEFAULT_LOSSLESS_BUFFER_PARAMETER', 'LOSSLESS_TRAFFIC_PATTERN', 'VERSIONS', 'DEVICE_METADATA']
        cls.appl_db_tables_to_verify = ['BUFFER_POOL_TABLE:*', 'BUFFER_PROFILE_TABLE:*', 'BUFFER_PG_TABLE:*', 'BUFFER_QUEUE:*', 'BUFFER_PORT_INGRESS_PROFILE_LIST:*', 'BUFFER_PORT_EGRESS_PROFILE_LIST:*']
        cls.warm_reboot_from_version = 'version_1_0_6'
        cls.warm_reboot_to_version = 'version_3_0_3'

        cls.version_list = ['version_1_0_1', 'version_1_0_2', 'version_1_0_3', 'version_1_0_4', 'version_1_0_5', 'version_1_0_6', 'version_3_0_0', 'version_3_0_3']


    def make_db_name_by_sku_topo_version(self, sku, topo, version):
        return sku + '-' + topo + '-' + version

    def mock_dedicated_config_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'config_db', filename)
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile
        db = Db()
        return db

    def mock_dedicated_state_db(self):
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db')

    def mock_dedicated_appl_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'appl_db', filename)
        dbconnector.dedicated_dbs['APPL_DB'] = jsonfile
        appl_db = SonicV2Connector(host='127.0.0.1')
        appl_db.connect(appl_db.APPL_DB)
        return appl_db

    def clear_dedicated_mock_dbs(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = None
        dbconnector.dedicated_dbs['STATE_DB'] = None
        dbconnector.dedicated_dbs['APPL_DB'] = None

    def check_config_db(self, result, expected, tables_to_verify=None):
        if not tables_to_verify:
            tables_to_verify = self.config_db_tables_to_verify
        for table in tables_to_verify:
            assert result.get_table(table) == expected.get_table(table)

    def check_appl_db(self, result, expected):
        for table in self.appl_db_tables_to_verify:
            keys = expected.keys(expected.APPL_DB, table)
            assert keys == result.keys(result.APPL_DB, table)
            if keys is None:
                continue
            for key in keys:
                assert expected.get_all(expected.APPL_DB, key) == result.get_all(result.APPL_DB, key)

    @pytest.mark.parametrize('scenario',
                             ['empty-config',
                              'empty-config-with-device-info-generic',
                              'empty-config-with-device-info-traditional',
                              'empty-config-with-device-info-nvidia',
                              'non-default-config',
                              'non-default-xoff',
                              'non-default-lossless-profile-in-pg',
                              'non-default-lossy-profile-in-pg',
                              'non-default-pg',
                              # An explicit buffer_model=dynamic must survive migration on any SKU for which
                              # dynamic is not the default-traditional model, ie. non "Mellanox-" prefixed SKUs
                              # and the SKUs listed in mellanox_buffer_migrator.dynamic_model_skus.
                              'non-default-config-dynamic-acs',
                              'non-default-config-dynamic-nvidia',
                              # A "Mellanox-" prefixed SKU outside that list is still forced to traditional
                              'non-default-config-dynamic-mellanox',
                              'non-default-config-traditional-acs'
                             ])
    def test_mellanox_buffer_migrator_negative_cold_reboot(self, scenario):
        db_before_migrate = scenario + '-input'
        db_after_migrate = scenario + '-expected'
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        db = self.mock_dedicated_config_db(db_before_migrate)
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        expected_db = self.mock_dedicated_config_db(db_after_migrate)
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, self.version_list[-1])
        self.check_config_db(dbmgtr.configDB, expected_db.cfgdb)
        assert not dbmgtr.mellanox_buffer_migrator.is_buffer_config_default

    @pytest.mark.parametrize('sku_version',
                             [('ACS-MSN2700', 'version_1_0_1'),
                              ('Mellanox-SN2700', 'version_1_0_1'),
                              ('Mellanox-SN2700-Single-Pool', 'version_1_0_4'),
                              ('Mellanox-SN2700-C28D8', 'version_1_0_1'),
                              ('Mellanox-SN2700-C28D8-Single-Pool', 'version_1_0_4'),
                              ('Mellanox-SN2700-D48C8', 'version_1_0_1'),
                              ('Mellanox-SN2700-D48C8-Single-Pool', 'version_1_0_4'),
                              ('Mellanox-SN2700-D40C8S8', 'version_1_0_5'),
                              ('ACS-MSN3700', 'version_1_0_2'),
                              ('ACS-MSN3800', 'version_1_0_5'),
                              ('Mellanox-SN3800-C64', 'version_1_0_5'),
                              ('Mellanox-SN3800-D112C8', 'version_1_0_5'),
                              ('Mellanox-SN3800-D24C52', 'version_1_0_5'),
                              ('Mellanox-SN3800-D28C50', 'version_1_0_5'),
                              ('ACS-MSN4700', 'version_1_0_4')
                             ])
    @pytest.mark.parametrize('topo', ['t0', 't1'])
    def test_mellanox_buffer_migrator_for_cold_reboot(self, sku_version, topo):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        sku, start_version = sku_version
        version = start_version
        start_index = self.version_list.index(start_version)

        # start_version represents the database version from which the SKU is supported
        # For each SKU,
        # migration from any version between start_version and the current version (inclusive) to the current version will be verified
        for version in self.version_list[start_index:]:
            _ = self.mock_dedicated_config_db(self.make_db_name_by_sku_topo_version(sku, topo, version))
            import db_migrator
            dbmgtr = db_migrator.DBMigrator(None)
            dbmgtr.migrate()

            # Eventually, the config db should be migrated to the latest version
            expected_db = self.mock_dedicated_config_db(self.make_db_name_by_sku_topo_version(sku, topo, self.version_list[-1]))
            advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, self.version_list[-1])
            self.check_config_db(dbmgtr.configDB, expected_db.cfgdb)
            assert dbmgtr.mellanox_buffer_migrator.is_buffer_config_default

        self.clear_dedicated_mock_dbs()

    def mellanox_buffer_migrator_warm_reboot_runner(self, input_config_db, input_appl_db, expected_config_db, expected_appl_db, is_buffer_config_default_expected):
        expected_config_db = self.mock_dedicated_config_db(expected_config_db)
        expected_appl_db = self.mock_dedicated_appl_db(expected_appl_db)
        self.mock_dedicated_state_db()
        _ = self.mock_dedicated_config_db(input_config_db)
        _ = self.mock_dedicated_appl_db(input_appl_db)

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        advance_version_for_expected_database(dbmgtr.configDB, expected_config_db.cfgdb, self.version_list[-1])
        assert dbmgtr.mellanox_buffer_migrator.is_buffer_config_default == is_buffer_config_default_expected
        self.check_config_db(dbmgtr.configDB, expected_config_db.cfgdb)
        self.check_appl_db(dbmgtr.appDB, expected_appl_db)

        self.clear_dedicated_mock_dbs()

    @pytest.mark.parametrize('sku',
                             ['ACS-MSN2700',
                              'Mellanox-SN2700', 'Mellanox-SN2700-Single-Pool', 'Mellanox-SN2700-C28D8', 'Mellanox-SN2700-C28D8-Single-Pool',
                              'Mellanox-SN2700-D48C8', 'Mellanox-SN2700-D48C8-Single-Pool',
                              'Mellanox-SN2700-D40C8S8',
                              'ACS-MSN3700',
                              'ACS-MSN3800',
                              'Mellanox-SN3800-C64',
                              'Mellanox-SN3800-D112C8',
                              'Mellanox-SN3800-D24C52',
                              'Mellanox-SN3800-D28C50',
                              'ACS-MSN4700'
                             ])
    @pytest.mark.parametrize('topo', ['t0', 't1'])
    def test_mellanox_buffer_migrator_for_warm_reboot(self, sku, topo):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        # Eventually, the config db should be migrated to the latest version
        expected_db_name = self.make_db_name_by_sku_topo_version(sku, topo, self.warm_reboot_to_version)
        input_db_name = self.make_db_name_by_sku_topo_version(sku, topo, self.warm_reboot_from_version)
        self.mellanox_buffer_migrator_warm_reboot_runner(input_db_name, input_db_name, expected_db_name, expected_db_name, True)

    def test_mellanox_buffer_migrator_negative_nondefault_for_warm_reboot(self):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        expected_config_db = 'non-default-config-expected'
        expected_appl_db = 'non-default-expected'
        input_config_db = 'non-default-config-input'
        input_appl_db = 'non-default-input'
        self.mellanox_buffer_migrator_warm_reboot_runner(input_config_db, input_appl_db, expected_config_db, expected_appl_db, False)

    def test_mellanox_buffer_migrator_dynamic_preserved_for_warm_reboot(self):
        """
        mlnx_flush_new_buffer_configuration is reached from the warm reboot path as well,
        verify the explicit buffer_model=dynamic is preserved there too
        """
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        expected_config_db = 'non-default-config-dynamic-acs-expected'
        expected_appl_db = 'non-default-expected'
        input_config_db = 'non-default-config-dynamic-acs-input'
        input_appl_db = 'non-default-input'
        self.mellanox_buffer_migrator_warm_reboot_runner(input_config_db,
                                                         input_appl_db,
                                                         expected_config_db,
                                                         expected_appl_db,
                                                         is_buffer_config_default_expected=False)

    @pytest.mark.parametrize('buffer_model', ['traditional', 'dynamic'])
    @pytest.mark.parametrize('ingress_pools', ['double-pools', 'single-pool'])
    def test_mellanox_buffer_reclaiming(self, buffer_model, ingress_pools):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        db_before_migrate = 'reclaiming-buffer-' + buffer_model + '-' + ingress_pools + '-input'
        db_after_migrate = 'reclaiming-buffer-' + buffer_model + '-' + ingress_pools + '-expected'

        db = self.mock_dedicated_config_db(db_before_migrate)
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        expected_db = self.mock_dedicated_config_db(db_after_migrate)
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_3_0_3')
        tables_to_verify = self.config_db_tables_to_verify
        tables_to_verify.extend(['BUFFER_QUEUE', 'BUFFER_PORT_INGRESS_PROFILE_LIST', 'BUFFER_PORT_EGRESS_PROFILE_LIST'])
        self.check_config_db(dbmgtr.configDB, expected_db.cfgdb, tables_to_verify)

    def test_mellanox_buffer_reclaiming_warm_reboot(self):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        input_db_name = 'reclaiming-buffer-warmreboot-input'
        expected_db_name = 'reclaiming-buffer-warmreboot-expected'
        self.mellanox_buffer_migrator_warm_reboot_runner(input_db_name, input_db_name, expected_db_name,expected_db_name, True)


class TestAutoNegMigrator(object):


    def test_port_autoneg_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'port-an-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()

        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'port-an-expected')
        expected_db = Db()
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_3_0_1')

        assert dbmgtr.configDB.get_table('PORT') == expected_db.cfgdb.get_table('PORT')
        assert dbmgtr.configDB.get_table('VERSIONS') == expected_db.cfgdb.get_table('VERSIONS')

class TestInitConfigMigrator(object):


    def test_init_config_feature_migration(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'feature-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'feature-expected')
        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('FEATURE')
        expected_table = expected_db.cfgdb.get_table('FEATURE')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

        assert not expected_db.cfgdb.get_table('CONTAINER_FEATURE')

class TestLacpKeyMigrator(object):


    def test_lacp_key_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'portchannel-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'portchannel-expected')
        expected_db = Db()
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_3_0_2')

        assert dbmgtr.configDB.get_table('PORTCHANNEL') == expected_db.cfgdb.get_table('PORTCHANNEL')
        assert dbmgtr.configDB.get_table('VERSIONS') == expected_db.cfgdb.get_table('VERSIONS')

class TestDnsNameserverMigrator(object):


    def test_dns_nameserver_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns-nameserver-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        # Set config_src_data to DNS_NAMESERVERS
        dbmgtr.config_src_data = {
            'DNS_NAMESERVER': {
                '1.1.1.1': {},
                '2001:1001:110:1001::1': {}
            }
        }
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns-nameserver-expected')
        expected_db = Db()
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_202411_02')
        resulting_keys = dbmgtr.configDB.keys(dbmgtr.configDB.CONFIG_DB, 'DNS_NAMESERVER*')
        expected_keys = expected_db.cfgdb.keys(expected_db.cfgdb.CONFIG_DB, 'DNS_NAMESERVER*')

        diff = DeepDiff(resulting_keys, expected_keys, ignore_order=True)
        assert not diff

class TestQosDBFieldValueReferenceRemoveMigrator(object):
    @classmethod
    def setup_class(cls):
        cls.config_db_tables_to_verify = ['QUEUE', 'PORT_QOS_MAP', 'BUFFER_PROFILE', 'BUFFER_PG', 'BUFFER_PORT_INGRESS_PROFILE_LIST', 'BUFFER_PORT_EGRESS_PROFILE_LIST', 'VERSIONS']
        cls.appl_db_tables_to_verify = ['BUFFER_PROFILE_TABLE:*', 'BUFFER_PG_TABLE:*', 'BUFFER_QUEUE_TABLE:*', 'BUFFER_PORT_INGRESS_PROFILE_LIST_TABLE:*', 'BUFFER_PORT_EGRESS_PROFILE_LIST_TABLE:*']


    def mock_dedicated_config_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'config_db', filename)
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile
        db = Db()
        return db

    def mock_dedicated_appl_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'appl_db', filename)
        dbconnector.dedicated_dbs['APPL_DB'] = jsonfile
        appl_db = SonicV2Connector(host='127.0.0.1')
        appl_db.connect(appl_db.APPL_DB)
        return appl_db

    def clear_dedicated_mock_dbs(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = None
        dbconnector.dedicated_dbs['APPL_DB'] = None

    def check_config_db(self, result, expected):
        for table in self.config_db_tables_to_verify:
            assert result.get_table(table) == expected.get_table(table)

    def check_appl_db(self, result, expected):
        for table in self.appl_db_tables_to_verify:
            keys = expected.keys(expected.APPL_DB, table)
            if keys is None:
                continue
            for key in keys:
                assert expected.get_all(expected.APPL_DB, key) == result.get_all(result.APPL_DB, key)

    def test_qos_buffer_migrator_for_cold_reboot(self):
        db_before_migrate = 'qos_tables_db_field_value_reference_format_3_0_1'
        db_after_migrate = 'qos_tables_db_field_value_reference_format_3_0_3'
        db = self.mock_dedicated_config_db(db_before_migrate)
        _ = self.mock_dedicated_appl_db(db_before_migrate)
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        expected_db = self.mock_dedicated_config_db(db_after_migrate)
        expected_appl_db = self.mock_dedicated_appl_db(db_after_migrate)
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_3_0_3')

        self.check_config_db(dbmgtr.configDB, expected_db.cfgdb)
        self.check_appl_db(dbmgtr.appDB, expected_appl_db)
        self.clear_dedicated_mock_dbs()


class TestPfcEnableMigrator(object):


    def test_pfc_enable_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'qos_map_table_input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'qos_map_table_expected')
        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('PORT_QOS_MAP')
        expected_table = expected_db.cfgdb.get_table('PORT_QOS_MAP')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

class TestGlobalDscpToTcMapMigrator(object):


    def test_global_dscp_to_tc_map_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'qos_map_table_global_input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.asic_type = "broadcom"
        dbmgtr.hwsku = "vs"
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'qos_map_table_global_expected')
        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('PORT_QOS_MAP')
        expected_table = expected_db.cfgdb.get_table('PORT_QOS_MAP')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

        # Check port_qos_map|global is not generated on mellanox asic
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'qos_map_table_global_input')
        dbmgtr_mlnx = db_migrator.DBMigrator(None)
        dbmgtr_mlnx.asic_type = "mellanox"
        dbmgtr_mlnx.hwsku = "vs"
        dbmgtr_mlnx.migrate()
        resulting_table = dbmgtr_mlnx.configDB.get_table('PORT_QOS_MAP')
        assert resulting_table == {}

class TestMoveLoggerTablesInWarmUpgrade(object):


    def mock_dedicated_loglevel_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'loglevel_db', filename)
        dbconnector.dedicated_dbs['LOGLEVEL_DB'] = jsonfile
        loglevel_db = SonicV2Connector(host='127.0.0.1')
        loglevel_db.connect(loglevel_db.LOGLEVEL_DB)
        return loglevel_db

    def test_move_logger_tables_in_warm_upgrade(self):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx

        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'logger_tables_input')
        dbconnector.dedicated_dbs['LOGLEVEL_DB'] = os.path.join(mock_db_path, 'loglevel_db', 'logger_tables_input')
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db')

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()

        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'logger_tables_expected')
        dbconnector.dedicated_dbs['LOGLEVEL_DB'] = os.path.join(mock_db_path, 'loglevel_db', 'logger_tables_expected')

        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('LOGGER')
        expected_table = expected_db.cfgdb.get_table('LOGGER')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

class TestFastRebootTableModification(object):


    def mock_dedicated_state_db(self):
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db')

    def test_rename_fast_reboot_table_check_enable(self):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'fast_reboot_input')
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'empty-config-input')

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()

        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'fast_reboot_expected')
        expected_db = SonicV2Connector(host='127.0.0.1')
        expected_db.connect(expected_db.STATE_DB)

        resulting_table = dbmgtr.stateDB.get_all(dbmgtr.stateDB.STATE_DB, 'FAST_RESTART_ENABLE_TABLE|system')
        expected_table = expected_db.get_all(expected_db.STATE_DB, 'FAST_RESTART_ENABLE_TABLE|system')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

    def test_ignore_rename_fast_reboot_table(self):
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'fast_reboot_upgrade_from_202205')
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'empty-config-input')

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()

        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'fast_reboot_upgrade_from_202205')
        expected_db = SonicV2Connector(host='127.0.0.1')
        expected_db.connect(expected_db.STATE_DB)

        resulting_table = dbmgtr.stateDB.get_all(dbmgtr.stateDB.STATE_DB, 'FAST_RESTART_ENABLE_TABLE|system')
        expected_table = expected_db.get_all(expected_db.STATE_DB, 'FAST_RESTART_ENABLE_TABLE|system')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

class TestWarmUpgrade_to_2_0_2(object):


    def test_warm_upgrade_to_2_0_2(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'cross_branch_upgrade_to_version_2_0_2_input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'cross_branch_upgrade_to_version_2_0_2_expected')
        expected_db = Db()

        new_tables = ["RESTAPI", "TELEMETRY", "CONSOLE_SWITCH"]
        for table in new_tables:
            resulting_table = dbmgtr.configDB.get_table(table)
            expected_table = expected_db.cfgdb.get_table(table)
            if table == "RESTAPI":
                # for RESTAPI - just make sure if the new fields are added, and ignore values match
                # values are ignored as minigraph parser is expected to generate different
                # results for cert names based on the project specific config.
                diff = set(resulting_table.get("certs").keys()) != set(expected_table.get("certs").keys())
            else:
                diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
            assert not diff

        target_routing_mode_result = dbmgtr.configDB.get_table("DEVICE_METADATA")['localhost']['docker_routing_config_mode']
        target_routing_mode_expected = expected_db.cfgdb.get_table("DEVICE_METADATA")['localhost']['docker_routing_config_mode']
        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert target_routing_mode_result == target_routing_mode_expected,\
            "After migration: {}. Expected after migration: {}".format(
                target_routing_mode_result, target_routing_mode_expected)

    def test_warm_upgrade__without_mg_to_2_0_2(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'cross_branch_upgrade_to_version_2_0_2_input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        # set config_src_data to None to mimic the missing minigraph.xml scenario
        dbmgtr.config_src_data = None
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'cross_branch_upgrade_without_mg_2_0_2_expected.json')
        expected_db = Db()

        new_tables = ["RESTAPI", "TELEMETRY", "CONSOLE_SWITCH"]
        for table in new_tables:
            resulting_table = dbmgtr.configDB.get_table(table)
            expected_table = expected_db.cfgdb.get_table(table)
            print(resulting_table)
            diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
            assert not diff

class Test_Migrate_Loopback(object):


    def test_migrate_loopback_int(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'loopback_interface_migrate_from_1_0_1_input')
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'loopback_interface_migrate_from_1_0_1_input')

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'loopback_interface_migrate_from_1_0_1_expected')
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'loopback_interface_migrate_from_1_0_1_expected')
        expected_db = Db()

        # verify migrated configDB
        resulting_table = dbmgtr.configDB.get_table("LOOPBACK_INTERFACE")
        expected_table = expected_db.cfgdb.get_table("LOOPBACK_INTERFACE")
        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

        # verify migrated appDB
        expected_appl_db = SonicV2Connector(host='127.0.0.1')
        expected_appl_db.connect(expected_appl_db.APPL_DB)
        expected_keys = expected_appl_db.keys(expected_appl_db.APPL_DB, "INTF_TABLE:*")
        expected_keys.sort()
        resulting_keys = dbmgtr.appDB.keys(dbmgtr.appDB.APPL_DB, "INTF_TABLE:*")
        resulting_keys.sort()
        assert expected_keys == resulting_keys
        for key in expected_keys:
            resulting_keys = dbmgtr.appDB.get_all(dbmgtr.appDB.APPL_DB, key)
            expected_keys = expected_appl_db.get_all(expected_appl_db.APPL_DB, key)
            diff = DeepDiff(resulting_keys, expected_keys, ignore_order=True)
            assert not diff

class TestWarmUpgrade_T0_EdgeZoneAggregator(object):


    def test_warm_upgrade_t0_edgezone_aggregator_diff_cable_length(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sample-t0-edgezoneagg-config-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sample-t0-edgezoneagg-config-output')
        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('CABLE_LENGTH')
        expected_table = expected_db.cfgdb.get_table('CABLE_LENGTH')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

    def test_warm_upgrade_t0_edgezone_aggregator_same_cable_length(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sample-t0-edgezoneagg-config-same-cable-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sample-t0-edgezoneagg-config-same-cable-output')
        expected_db = Db()

        resulting_table = dbmgtr.configDB.get_table('CABLE_LENGTH')
        expected_table = expected_db.cfgdb.get_table('CABLE_LENGTH')

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff


class TestFastUpgrade_to_4_0_3(object):
    @classmethod
    def setup_class(cls):
        cls.config_db_tables_to_verify = ['FLEX_COUNTER_TABLE']
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'fast_reboot_upgrade')


    def mock_dedicated_config_db(self, filename):
        jsonfile = os.path.join(mock_db_path, 'config_db', filename)
        dbconnector.dedicated_dbs['CONFIG_DB'] = jsonfile
        db = Db()
        return db

    def check_config_db(self, result, expected):
        for table in self.config_db_tables_to_verify:
            assert result.get_table(table) == expected.get_table(table)

    def test_fast_reboot_upgrade_to_4_0_3(self):
        db_before_migrate = 'cross_branch_upgrade_to_4_0_3_input'
        db_after_migrate = 'cross_branch_upgrade_to_4_0_3_expected'
        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        db = self.mock_dedicated_config_db(db_before_migrate)
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        expected_db = self.mock_dedicated_config_db(db_after_migrate)
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_4_0_3')
        assert not self.check_config_db(dbmgtr.configDB, expected_db.cfgdb)
        assert dbmgtr.CURRENT_VERSION == expected_db.cfgdb.get_entry('VERSIONS', 'DATABASE')['VERSION'], '{} {}'.format(dbmgtr.CURRENT_VERSION, dbmgtr.get_version())


class TestSflowSampleDirectionMigrator(object):


    def test_sflow_migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sflow_table_input')
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'sflow_table_input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'sflow_table_expected')
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'sflow_table_expected')
        expected_db = Db()

        # verify migrated config DB
        resulting_table = dbmgtr.configDB.get_table('SFLOW')
        expected_table = expected_db.cfgdb.get_table('SFLOW')
        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

        resulting_table = dbmgtr.configDB.get_table('SFLOW_SESSION')
        expected_table = expected_db.cfgdb.get_table('SFLOW_SESSION')
        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

        # verify migrated appDB
        expected_appl_db = SonicV2Connector(host='127.0.0.1')
        expected_appl_db.connect(expected_appl_db.APPL_DB)


        expected_keys = expected_appl_db.keys(expected_appl_db.APPL_DB, "SFLOW_TABLE:global")
        expected_keys.sort()
        resulting_keys = dbmgtr.appDB.keys(dbmgtr.appDB.APPL_DB, "SFLOW_TABLE:global")
        resulting_keys.sort()
        for key in expected_keys:
            resulting_keys = dbmgtr.appDB.get_all(dbmgtr.appDB.APPL_DB, key)
            expected_keys = expected_appl_db.get_all(expected_appl_db.APPL_DB, key)
            diff = DeepDiff(resulting_keys, expected_keys, ignore_order=True)
            assert not diff

        expected_keys = expected_appl_db.keys(expected_appl_db.APPL_DB, "SFLOW_SESSION_TABLE:*")
        expected_keys.sort()
        resulting_keys = dbmgtr.appDB.keys(dbmgtr.appDB.APPL_DB, "SFLOW_SESSION_TABLE:*")
        resulting_keys.sort()
        assert expected_keys == resulting_keys
        for key in expected_keys:
            resulting_keys = dbmgtr.appDB.get_all(dbmgtr.appDB.APPL_DB, key)
            expected_keys = expected_appl_db.get_all(expected_appl_db.APPL_DB, key)
            diff = DeepDiff(resulting_keys, expected_keys, ignore_order=True)
            assert not diff

class TestGoldenConfig(object):
    @classmethod
    def setup_class(cls):
        os.system("cp %s %s" % (mock_db_path + '/golden_config_db.json.test', mock_db_path + '/golden_config_db.json'))


    def test_golden_config_hostname(self):
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        config = dbmgtr.config_src_data
        device_metadata = config.get('DEVICE_METADATA', {})
        assert device_metadata != {}
        host = device_metadata.get('localhost', {})
        assert host != {}
        hostname = host.get('hostname', '')
        # hostname is from golden_config_db.json
        assert hostname == 'SONiC-Golden-Config'

    def test_golden_config_ns(self):
        # golden_config_db.json.test has no namespace
        import db_migrator
        dbmgtr = db_migrator.DBMigrator("asic0")
        result = json.dumps(dbmgtr.config_src_data)
        assert 'SONiC-Golden-Config' not in result

    @classmethod
    def teardown_class(cls):
        os.system("rm %s" % (mock_db_path + '/golden_config_db.json'))

class TestGoldenConfigInvalid(object):
    @classmethod
    def setup_class(cls):
        os.system("cp %s %s" % (mock_db_path + '/golden_config_db.json.invalid', mock_db_path + '/golden_config_db.json'))


    def test_golden_config_hostname(self):
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        config = dbmgtr.config_src_data
        device_metadata = config.get('DEVICE_METADATA', {})
        assert device_metadata != {}
        host = device_metadata.get('localhost', {})
        assert host != {}
        hostname = host.get('hostname', '')
        # hostname is from minigraph.xml
        assert hostname == 'SONiC-Dummy'


    @classmethod
    def teardown_class(cls):
        os.system("rm %s" % (mock_db_path + '/golden_config_db.json'))


class TestMain(object):

    @mock.patch('argparse.ArgumentParser.parse_args')
    def test_init(self, mock_args):
        mock_args.return_value=argparse.Namespace(namespace=None, operation='get_version', socket=None)
        import db_migrator
        db_migrator.main()

    @mock.patch('argparse.ArgumentParser.parse_args')
    @mock.patch('swsscommon.swsscommon.SonicDBConfig.isInit', mock.MagicMock(return_value=False))
    @mock.patch('swsscommon.swsscommon.SonicDBConfig.initialize', mock.MagicMock())
    def test_init_no_namespace(self, mock_args):
        mock_args.return_value = argparse.Namespace(namespace=None, operation='version_202411_02', socket=None)
        import db_migrator
        db_migrator.main()

    @mock.patch('argparse.ArgumentParser.parse_args')
    @mock.patch('swsscommon.swsscommon.SonicDBConfig.isGlobalInit', mock.MagicMock(return_value=False))
    @mock.patch('swsscommon.swsscommon.SonicDBConfig.initializeGlobalConfig', mock.MagicMock())
    def test_init_namespace(self, mock_args):
        mock_args.return_value = argparse.Namespace(namespace="asic0", operation='version_202411_02', socket=None)
        import db_migrator
        db_migrator.main()


class TestGNMIMigrator(object):


    def test_dns_nameserver_migrator_minigraph(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'gnmi-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        # Set config_src_data
        dbmgtr.config_src_data = {
            'GNMI': {
                'gnmi': {
                    "client_auth": "true", 
                    "log_level": "2", 
                    "port": "50052"
                }, 
                'certs': {
                    "server_key": "/etc/sonic/telemetry/streamingtelemetryserver.key", 
                    "ca_crt": "/etc/sonic/telemetry/dsmsroot.cer", 
                    "server_crt": "/etc/sonic/telemetry/streamingtelemetryserver.cer"
                }
            }
        }
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'gnmi-minigraph-expected')
        expected_db = Db()
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_202411_02')
        resulting_table = dbmgtr.configDB.get_table("GNMI")
        expected_table = expected_db.cfgdb.get_table("GNMI")

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

    def test_dns_nameserver_migrator_configdb(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'gnmi-input')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        # Set config_src_data
        dbmgtr.config_src_data = {}
        dbmgtr.migrate()
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'gnmi-configdb-expected')
        expected_db = Db()
        advance_version_for_expected_database(dbmgtr.configDB, expected_db.cfgdb, 'version_202411_02')
        resulting_table = dbmgtr.configDB.get_table("GNMI")
        expected_table = expected_db.cfgdb.get_table("GNMI")

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff

class TestAAAMigrator(object):


    def load_golden_config(self, dbmgtr, test_json):
        dbmgtr.config_src_data = {}

        json_path = os.path.join(mock_db_path, 'config_db', test_json + ".json")
        if os.path.exists(json_path):
            with open(json_path) as f:
                dbmgtr.config_src_data = json.load(f)
                print("test_per_command_aaa load golden config success, config_src_data: {}".format(dbmgtr.config_src_data))
        else:
            print("test_per_command_aaa load golden config failed, file {} does not exist.".format(test_json))


    @pytest.mark.parametrize('test_json', ['per_command_aaa_enable',
                                           'per_command_aaa_no_passkey',
                                           'per_command_aaa_disable',
                                           'per_command_aaa_no_change',
                                           'per_command_aaa_no_tacplus',
                                           'per_command_aaa_no_authentication'])
    def test_per_command_aaa(self, test_json):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', test_json)
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        self.load_golden_config(dbmgtr, test_json + '_golden')
        dbmgtr.migrate_tacplus()
        dbmgtr.migrate_aaa()
        resulting_table = dbmgtr.configDB.get_table("AAA")

        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', test_json + '_expected')
        expected_db = Db()
        expected_table = expected_db.cfgdb.get_table("AAA")

        print("test_per_command_aaa: {}".format(test_json))
        print("test_per_command_aaa, resulting_table: {}".format(resulting_table))
        print("test_per_command_aaa, expected_table: {}".format(expected_table))

        diff = DeepDiff(resulting_table, expected_table, ignore_order=True)
        assert not diff


class TestIPinIPTunnelMigrator(object):


    def test_tunnel_migrator(self):
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'tunnel_table_input')
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'tunnel_table_input')

        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate()

        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'tunnel_table_expected')
        expected_appl_db = SonicV2Connector(host='127.0.0.1')
        expected_appl_db.connect(expected_appl_db.APPL_DB)
        expected_keys = expected_appl_db.keys(expected_appl_db.APPL_DB, "*")
        resulting_keys = dbmgtr.appDB.keys(dbmgtr.appDB.APPL_DB, "*")
        expected_keys.sort()
        resulting_keys.sort()
        assert expected_keys == resulting_keys
        for key in expected_keys:
            resulting_keys = dbmgtr.appDB.get_all(dbmgtr.appDB.APPL_DB, key)
            expected_keys = expected_appl_db.get_all(expected_appl_db.APPL_DB, key)
            diff = DeepDiff(resulting_keys, expected_keys, ignore_order=True)
            assert not diff


class TestDhcpv4RelayMigrator(object):


    def test_check_has_sonic_dhcpv4_relay_flag_true(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Set the flag to True
        dbmgtr.configDB.set_entry("DEVICE_METADATA", "localhost", {
            "has_sonic_dhcpv4_relay": "True"
        })

        assert dbmgtr.check_has_sonic_dhcpv4_relay_flag() is True

    def test_check_has_sonic_dhcpv4_relay_flag_false(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Set the flag to False
        dbmgtr.configDB.set_entry("DEVICE_METADATA", "localhost", {
            "has_sonic_dhcpv4_relay": "False"
        })

        assert dbmgtr.check_has_sonic_dhcpv4_relay_flag() is False

    def test_check_has_sonic_dhcpv4_relay_flag_not_set(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Ensure flag is not set
        dbmgtr.configDB.set_entry("DEVICE_METADATA", "localhost", {})

        assert dbmgtr.check_has_sonic_dhcpv4_relay_flag() is False

    def test_migrate_dhcp_servers_to_dhcpv4_relay_success(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Setup initial VLAN with dhcp_servers
        dbmgtr.configDB.set_entry("VLAN", "Vlan100", {
            "vlanid": "100",
            "dhcp_servers": ["192.0.2.1", "192.0.2.2"]
        })

        # Run migration
        dbmgtr.migrate_dhcp_servers_to_dhcpv4_relay()

        # Verify DHCPV4_RELAY entry created
        relay_entry = dbmgtr.configDB.get_entry("DHCPV4_RELAY", "Vlan100")
        assert relay_entry.get("dhcpv4_servers") == ["192.0.2.1", "192.0.2.2"]

        # Verify dhcp_servers removed from VLAN
        vlan_entry = dbmgtr.configDB.get_entry("VLAN", "Vlan100")
        assert "dhcp_servers" not in vlan_entry
        assert vlan_entry.get("vlanid") == "100"

    def test_migrate_dhcp_servers_skip_if_no_dhcp_servers(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Setup VLAN without dhcp_servers
        dbmgtr.configDB.set_entry("VLAN", "Vlan200", {"vlanid": "200"})

        # Run migration
        dbmgtr.migrate_dhcp_servers_to_dhcpv4_relay()

        # Verify no DHCPV4_RELAY entry created
        relay_entry = dbmgtr.configDB.get_entry("DHCPV4_RELAY", "Vlan200")
        assert not relay_entry or "dhcpv4_servers" not in relay_entry

    def test_migrate_dhcp_servers_skip_if_already_migrated(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Setup VLAN with dhcp_servers
        dbmgtr.configDB.set_entry("VLAN", "Vlan300", {
            "vlanid": "300",
            "dhcp_servers": ["192.0.2.1"]
        })

        # Setup existing DHCPV4_RELAY entry
        dbmgtr.configDB.set_entry("DHCPV4_RELAY", "Vlan300", {
            "dhcpv4_servers": ["10.0.0.1"]
        })

        # Run migration
        dbmgtr.migrate_dhcp_servers_to_dhcpv4_relay()

        # Verify existing entry not overwritten
        relay_entry = dbmgtr.configDB.get_entry("DHCPV4_RELAY", "Vlan300")
        assert relay_entry.get("dhcpv4_servers") == ["10.0.0.1"]

        vlan_entry = dbmgtr.configDB.get_entry("VLAN", "Vlan300")
        assert "dhcp_servers" not in vlan_entry

    def test_migrate_dhcp_servers_multiple_vlans(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Setup multiple VLANs with dhcp_servers
        dbmgtr.configDB.set_entry("VLAN", "Vlan400", {
            "vlanid": "400",
            "dhcp_servers": ["192.0.2.10"]
        })
        dbmgtr.configDB.set_entry("VLAN", "Vlan500", {
            "vlanid": "500",
            "dhcp_servers": ["192.0.2.20"]
        })

        # Run migration
        dbmgtr.migrate_dhcp_servers_to_dhcpv4_relay()

        # Verify both VLANs migrated
        relay_entry_400 = dbmgtr.configDB.get_entry("DHCPV4_RELAY", "Vlan400")
        assert relay_entry_400.get("dhcpv4_servers") == ["192.0.2.10"]

        relay_entry_500 = dbmgtr.configDB.get_entry("DHCPV4_RELAY", "Vlan500")
        assert relay_entry_500.get("dhcpv4_servers") == ["192.0.2.20"]

        # Verify dhcp_servers removed from both VLANs
        vlan_entry_400 = dbmgtr.configDB.get_entry("VLAN", "Vlan400")
        assert "dhcp_servers" not in vlan_entry_400

        vlan_entry_500 = dbmgtr.configDB.get_entry("VLAN", "Vlan500")
        assert "dhcp_servers" not in vlan_entry_500

    @pytest.mark.parametrize("version_method,vlan_id,dhcp_server", [
        ("version_202305_01", "100", "192.0.2.1"),
        ("version_202311_01", "200", "192.0.2.2"),
        ("version_202311_02", "300", "192.0.2.3"),
        ("version_202311_03", "400", "192.0.2.4"),
        ("version_202405_01", "500", "192.0.2.5"),
        ("version_202405_02", "600", "192.0.2.6"),
        ("version_202411_01", "700", "192.0.2.7"),
        ("version_202411_02", "800", "192.0.2.8"),
        ("version_202505_01", "900", "192.0.2.9"),
    ])
    def test_version_methods_with_dhcp_migration(self, version_method, vlan_id, dhcp_server):
        """Test all version methods call dhcp migration when flag is True"""
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)

        # Set flag to True and setup VLAN with dhcp_servers
        dbmgtr.configDB.set_entry("DEVICE_METADATA", "localhost", {"has_sonic_dhcpv4_relay": "True"})
        vlan_name = f"Vlan{vlan_id}"
        dbmgtr.configDB.set_entry("VLAN", vlan_name, {"vlanid": vlan_id, "dhcp_servers": [dhcp_server]})

        # Call the version method dynamically
        getattr(dbmgtr, version_method)()

        # Verify migration was executed
        relay_entry = dbmgtr.configDB.get_entry("DHCPV4_RELAY", vlan_name)
        assert relay_entry.get("dhcpv4_servers") == [dhcp_server]


class TestIPinIPTunnelEcnModeMigrator(object):


    def compare_keys(self, expected_db, resulting_db, db_name):
        expected_values = sorted(expected_db.keys(db_name, "*"))
        resulting_values = sorted(resulting_db.keys(db_name, "*"))
        assert expected_values == resulting_values
        for key in expected_values:
            expected_values = expected_db.get_all(db_name, key)
            resulting_values = resulting_db.get_all(db_name, key)
            diff = DeepDiff(resulting_values, expected_values, ignore_order=True)
            assert not diff

    def test_ipinip_tunnel_ecn_mode_migrator(self):
        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'tunnel_table_ecn_mode_input')
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'tunnel_table_ecn_mode_input')

        device_info.get_sonic_version_info = get_sonic_version_info_mlnx
        import db_migrator
        dbmgtr = db_migrator.DBMigrator(None)
        dbmgtr.migrate_ipinip_tunnel_ecn_mode_mellanox()

        dbconnector.dedicated_dbs['APPL_DB'] = os.path.join(mock_db_path, 'appl_db', 'tunnel_table_ecn_mode_expected')
        dbconnector.dedicated_dbs['STATE_DB'] = os.path.join(mock_db_path, 'state_db', 'tunnel_table_ecn_mode_expected')

        expected_appl_db = SonicV2Connector(host='127.0.0.1')
        expected_appl_db.connect(expected_appl_db.APPL_DB)
        self.compare_keys(expected_appl_db, dbmgtr.appDB, 'APPL_DB')

        expected_state_db = SonicV2Connector(host='127.0.0.1')
        expected_state_db.connect(expected_state_db.STATE_DB)
        self.compare_keys(expected_state_db, dbmgtr.stateDB, 'STATE_DB')
<<<<<<< HEAD
=======


class TestRoutePerformanceKnobsMigrator(object):
    """
    The four DEVICE_METADATA route performance knobs were removed in the
    sonic-device_metadata 2026-06-02 revision and replaced by the
    SYSTEM_DEFAULTS entries swss_zmq and async_rec.
    """

    @classmethod
    def setup_class(cls):
        cls.saved_version_info = device_info.get_sonic_version_info
        device_info.get_sonic_version_info = get_sonic_version_info_broadcom

    @classmethod
    def teardown_class(cls):
        device_info.get_sonic_version_info = cls.saved_version_info
        dbconnector.dedicated_dbs.clear()

    def setup_method(self):
        self.patchers = []

    def teardown_method(self):
        # Stop only the patches this test started, rather than every patch
        # active in the process.
        while self.patchers:
            self.patchers.pop().stop()

    def compare_tables(self, dbmgtr, expected_fixture):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', expected_fixture)
        expected_db = Db()
        for table in ('DEVICE_METADATA', 'SYSTEM_DEFAULTS'):
            diff = DeepDiff(dbmgtr.configDB.get_table(table),
                            expected_db.cfgdb.get_table(table),
                            ignore_order=True)
            assert not diff, "{} mismatch: {}".format(table, diff)

    def patch(self, target, attribute, value):
        patcher = mock.patch.object(target, attribute, value)
        patcher.start()
        self.patchers.append(patcher)

    def migrator(self, input_fixture, quarantine=None, tmp_path=None,
                 saved_config=None):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', input_fixture)
        import db_migrator
        if quarantine is not None or saved_config is not None:
            config_db_file = os.path.join(str(tmp_path), 'config_db.json')
            if saved_config is not None:
                with open(config_db_file, 'w') as f:
                    json.dump(saved_config, f)
            if quarantine is not None:
                with open(config_db_file + db_migrator.CONFIG_DB_QUARANTINE_SUFFIX, 'w') as f:
                    json.dump(quarantine, f)
            self.patch(db_migrator, 'CONFIG_DB_FILE', config_db_file)
        return db_migrator.DBMigrator(None)

    def test_knobs_enabled_move_to_system_defaults(self):
        dbmgtr = self.migrator('route_perf_knobs_input')
        dbmgtr.migrate_route_performance_knobs()
        self.compare_tables(dbmgtr, 'route_perf_knobs_expected')

    def test_disabled_knob_collapses_to_disabled(self):
        dbmgtr = self.migrator('route_perf_knobs_disabled_input')
        dbmgtr.migrate_route_performance_knobs()
        self.compare_tables(dbmgtr, 'route_perf_knobs_disabled_expected')

    def test_entry_in_the_saved_config_wins(self, tmp_path):
        saved = {'SYSTEM_DEFAULTS': {'swss_zmq': {'status': 'enabled'}}}
        dbmgtr = self.migrator('route_perf_knobs_operator_set_input',
                               saved_config=saved, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        self.compare_tables(dbmgtr, 'route_perf_knobs_operator_set_expected')

    def test_value_read_from_quarantine_file(self, tmp_path):
        # Cold upgrade boot: 'config reload' already stripped the field from
        # CONFIG_DB, so the old value only exists in the quarantine file.
        quarantine = {
            'DEVICE_METADATA': {
                'localhost': {'orch_northbond_route_zmq_enabled': 'false'}
            }
        }
        dbmgtr = self.migrator('route_perf_knobs_quarantine_input',
                               quarantine=quarantine, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        self.compare_tables(dbmgtr, 'route_perf_knobs_quarantine_expected')

    def test_image_default_in_configdb_does_not_block_the_migration(self, tmp_path):
        # config reload loads init_cfg before the config file, so an entry is
        # always in CONFIG_DB by the time this runs. Absent from the saved
        # config, it is only the image default and must not win.
        dbmgtr = self.migrator('route_perf_knobs_operator_set_input',
                               saved_config={}, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == \
            {'status': 'disabled'}
        assert 'orch_northbond_route_zmq_enabled' not in \
            dbmgtr.configDB.get_entry('DEVICE_METADATA', 'localhost')

    def test_saved_value_equal_to_the_image_default_still_wins(self, tmp_path):
        # The case that decides this cannot be judged from CONFIG_DB: somebody
        # chose the value the image also defaults to. Saved, so it stands, and
        # the every-boot re-run must not keep reverting it.
        saved = {'SYSTEM_DEFAULTS': {'swss_zmq': {'status': 'enabled'}}}
        quarantine = {
            'DEVICE_METADATA': {
                'localhost': {'orch_northbond_route_zmq_enabled': 'false'}
            }
        }
        # CONFIG_DB carries the saved value, as it would after a reload.
        dbmgtr = self.migrator('route_perf_knobs_operator_set_input',
                               quarantine=quarantine, saved_config=saved,
                               tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == \
            {'status': 'enabled'}

    def test_northbound_only_source_migrates_on_its_own(self, tmp_path):
        # 202511 has no southbound ZMQ at all, so a config carried from there
        # has only the northbound knob and its value stands alone.
        quarantine = {
            'DEVICE_METADATA': {
                'localhost': {'orch_northbond_route_zmq_enabled': 'true'}
            }
        }
        dbmgtr = self.migrator('route_perf_knobs_quarantine_input',
                               quarantine=quarantine, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == \
            {'status': 'enabled'}
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'async_rec') == {}

    def test_async_rec_read_from_quarantine_file(self, tmp_path):
        # The async fields take the same quarantine path as the ZMQ ones, and
        # carry an enabled/disabled enum rather than a boolean.
        quarantine = {
            'DEVICE_METADATA': {
                'localhost': {'async_swss_rec': 'enabled',
                              'route_state_async_publish': 'enabled'}
            }
        }
        dbmgtr = self.migrator('route_perf_knobs_quarantine_input',
                               quarantine=quarantine, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'async_rec') == \
            {'status': 'enabled'}
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == {}

    def test_route_state_async_publish_does_not_feed_async_rec(self, tmp_path):
        # Nothing ever read route_state_async_publish out of CONFIG_DB, so it
        # must not be able to switch off a recorder somebody had on.
        quarantine = {
            'DEVICE_METADATA': {
                'localhost': {'async_swss_rec': 'enabled',
                              'route_state_async_publish': 'disabled'}
            }
        }
        dbmgtr = self.migrator('route_perf_knobs_quarantine_input',
                               quarantine=quarantine, tmp_path=tmp_path)
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'async_rec') == \
            {'status': 'enabled'}

    def test_no_knobs_present_is_a_noop(self):
        dbmgtr = self.migrator('route_perf_knobs_quarantine_input')
        dbmgtr.migrate_route_performance_knobs()
        assert dbmgtr.configDB.get_table('SYSTEM_DEFAULTS') == {}

    def test_version_202605_01_runs_the_migration(self):
        # A DUT upgrading from 202605 enters the chain already stamped
        # version_202605_01, so the migration has to hang off that handler
        # rather than an earlier one. The stamp does not advance.
        dbmgtr = self.migrator('route_perf_knobs_input')
        assert dbmgtr.get_version() == 'version_202605_01'
        with mock.patch.object(type(dbmgtr), 'common_migration_ops'):
            dbmgtr.migrate()
        assert dbmgtr.get_version() == 'version_202605_01'
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == {'status': 'enabled'}
        assert 'orch_northbond_route_zmq_enabled' not in \
            dbmgtr.configDB.get_entry('DEVICE_METADATA', 'localhost')

    def test_version_202511_01_walks_into_the_migration(self):
        # A DUT upgrading from 202511 enters the chain earlier and reaches the
        # same handler, so one hook covers both populations.
        dbmgtr = self.migrator('route_perf_knobs_input')
        dbmgtr.set_version('version_202511_01')
        with mock.patch.object(type(dbmgtr), 'common_migration_ops'):
            dbmgtr.migrate()
        assert dbmgtr.get_version() == 'version_202605_01'
        assert dbmgtr.configDB.get_entry('SYSTEM_DEFAULTS', 'swss_zmq') == {'status': 'enabled'}

    def test_migration_is_idempotent_across_boots(self):
        # version_202605_01 is terminal, so db_migrator re-runs it on every
        # boot. A second pass must not change what the first produced.
        dbmgtr = self.migrator('route_perf_knobs_input')
        with mock.patch.object(type(dbmgtr), 'common_migration_ops'):
            dbmgtr.migrate()
            dbmgtr.migrate()
        assert dbmgtr.get_version() == 'version_202605_01'
        self.compare_tables(dbmgtr, 'route_perf_knobs_expected')


class TestBgpNeighborPeerTypeAsnConflictMigrator(object):
    """
    asn and peer_type became mutually exclusive on BGP_NEIGHBOR and
    BGP_PEER_GROUP rows. A row carrying both, left over from before that
    constraint existed, has peer_type dropped so it validates going forward.
    """

    @classmethod
    def setup_class(cls):
        cls.saved_version_info = device_info.get_sonic_version_info
        device_info.get_sonic_version_info = get_sonic_version_info_broadcom

    @classmethod
    def teardown_class(cls):
        device_info.get_sonic_version_info = cls.saved_version_info
        dbconnector.dedicated_dbs.clear()

    def setup_method(self):
        self.patchers = []

    def teardown_method(self):
        while self.patchers:
            self.patchers.pop().stop()

    def compare_tables(self, dbmgtr, expected_fixture):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', expected_fixture)
        expected_db = Db()
        for table in ('BGP_NEIGHBOR', 'BGP_PEER_GROUP'):
            diff = DeepDiff(dbmgtr.configDB.get_table(table),
                            expected_db.cfgdb.get_table(table),
                            ignore_order=True)
            assert not diff, "{} mismatch: {}".format(table, diff)

    def patch(self, target, attribute, value):
        patcher = mock.patch.object(target, attribute, value)
        patcher.start()
        self.patchers.append(patcher)

    def migrator(self, input_fixture, tmp_path=None, saved_config=None):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', input_fixture)
        import db_migrator
        if saved_config is not None:
            config_db_file = os.path.join(str(tmp_path), 'config_db.json')
            with open(config_db_file, 'w') as f:
                json.dump(saved_config, f)
            self.patch(db_migrator, 'CONFIG_DB_FILE', config_db_file)
        return db_migrator.DBMigrator(None)

    def test_both_set_drops_peer_type_on_neighbor_and_peer_group(self):
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        self.compare_tables(dbmgtr, 'bgp_neighbor_peer_type_asn_conflict_expected')

    def test_asn_only_is_a_noop(self):
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        assert dbmgtr.configDB.get_entry('BGP_NEIGHBOR', ('default', '192.0.2.2')) == \
            {'asn': '65002'}

    def test_peer_type_only_is_a_noop(self):
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        assert dbmgtr.configDB.get_entry('BGP_NEIGHBOR', ('default', '192.0.2.3')) == \
            {'peer_type': 'internal'}

    def test_single_key_template_row_is_skipped(self):
        # BGP_NEIGHBOR_TEMPLATE_LIST rows are keyed on neighbor alone (a
        # single-part key) and never carry peer_type in the first place;
        # the tuple-length check must not touch them regardless.
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        assert dbmgtr.configDB.get_entry('BGP_NEIGHBOR', '10.0.0.1') == {'asn': '65200'}

    def test_migration_is_idempotent(self):
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        self.compare_tables(dbmgtr, 'bgp_neighbor_peer_type_asn_conflict_expected')

    def test_saved_config_file_is_also_repaired(self, tmp_path):
        # A plain 'config reload' YANG-validates the saved config_db.json
        # before db_migrator ever runs, so a both-set row left there aborts
        # every such reload unless the file itself is fixed too.
        saved = {
            'BGP_NEIGHBOR': {
                'default|192.0.2.1': {'asn': '65001', 'peer_type': 'external'}
            }
        }
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input',
                               saved_config=saved, tmp_path=tmp_path)
        dbmgtr.migrate_bgp_neighbor_peer_type_asn_conflict()
        import db_migrator
        with open(db_migrator.CONFIG_DB_FILE) as f:
            file_cfg = json.load(f)
        assert file_cfg['BGP_NEIGHBOR']['default|192.0.2.1'] == {'asn': '65001'}

    def test_version_202605_01_runs_the_migration(self):
        dbmgtr = self.migrator('bgp_neighbor_peer_type_asn_conflict_input')
        assert dbmgtr.get_version() == 'version_202605_01'
        with mock.patch.object(type(dbmgtr), 'common_migration_ops'):
            dbmgtr.migrate()
        assert dbmgtr.get_version() == 'version_202605_01'
        self.compare_tables(dbmgtr, 'bgp_neighbor_peer_type_asn_conflict_expected')


class TestRouterInterfaceVlanConflictMigrator(object):
    """
    A port left both a VLAN member and a router interface loses one side.
    """

    @classmethod
    def setup_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "2"

    @classmethod
    def teardown_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "0"
        dbconnector.dedicated_dbs['CONFIG_DB'] = None

    def migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        return db_migrator.DBMigrator(None)

    def test_membership_of_an_addressed_router_interface_is_removed(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORTCHANNEL_INTERFACE", ("PortChannel0001", "10.0.0.1/31"), {"NULL": "NULL"})
        dbmgtr.configDB.set_entry("VLAN_MEMBER", ("Vlan1000", "PortChannel0001"), {"tagging_mode": "tagged"})

        dbmgtr.migrate_router_interface_vlan_conflicts()

        assert dbmgtr.configDB.get_entry("VLAN_MEMBER", ("Vlan1000", "PortChannel0001")) == {}
        assert ("PortChannel0001", "10.0.0.1/31") in dbmgtr.configDB.get_keys("PORTCHANNEL_INTERFACE")

    def test_bare_router_interface_row_of_a_vlan_member_is_removed(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("INTERFACE", "Ethernet4", {"mpls": "enable"})
        dbmgtr.configDB.set_entry("VLAN_MEMBER", ("Vlan1000", "Ethernet4"), {"tagging_mode": "untagged"})

        dbmgtr.migrate_router_interface_vlan_conflicts()

        assert dbmgtr.configDB.get_entry("INTERFACE", "Ethernet4") == {}
        assert dbmgtr.configDB.get_entry("VLAN_MEMBER", ("Vlan1000", "Ethernet4")) == {"tagging_mode": "untagged"}

    def test_config_without_a_conflict_is_left_alone(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("INTERFACE", "Ethernet0", {"mpls": "enable"})
        dbmgtr.configDB.set_entry("VLAN_MEMBER", ("Vlan1000", "Ethernet4"), {"tagging_mode": "untagged"})
        before = {table: dbmgtr.configDB.get_table(table)
                  for table in ("INTERFACE", "PORTCHANNEL_INTERFACE", "VLAN_MEMBER")}

        dbmgtr.migrate_router_interface_vlan_conflicts()

        assert {table: dbmgtr.configDB.get_table(table) for table in before} == before

    def test_wired_into_version_202605_01(self):
        dbmgtr = self.migrator()
        import db_migrator

        with mock.patch.object(db_migrator.DBMigrator, 'migrate_router_interface_vlan_conflicts') as mock_migrate:
            assert dbmgtr.version_202511_01() == 'version_202605_01'
            mock_migrate.assert_not_called()
            with mock.patch.object(db_migrator.DBMigrator, 'migrate_route_performance_knobs'), \
                    mock.patch.object(db_migrator.DBMigrator, 'migrate_bgp_neighbor_peer_type_asn_conflict'), \
                    mock.patch.object(db_migrator.DBMigrator, 'migrate_remove_switchport_mode'):
                dbmgtr.version_202605_01()
            mock_migrate.assert_called_once()


class TestRemoveSwitchportModeMigrator(object):
    """
    PORT and PORTCHANNEL rows carrying the mode field have it dropped.
    """

    @classmethod
    def setup_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "2"

    @classmethod
    def teardown_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "0"
        dbconnector.dedicated_dbs['CONFIG_DB'] = None

    def migrator(self):
        dbconnector.dedicated_dbs['CONFIG_DB'] = os.path.join(
            mock_db_path, 'config_db', 'dns_nameserver_expected')
        import db_migrator
        return db_migrator.DBMigrator(None)

    def test_mode_is_removed_and_other_fields_survive(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORT", "Ethernet0", {"lanes": "0", "mode": "access"})
        dbmgtr.configDB.set_entry("PORTCHANNEL", "PortChannel0001", {"mtu": "9100", "mode": "trunk"})

        dbmgtr.migrate_remove_switchport_mode()

        port_entry = dbmgtr.configDB.get_entry("PORT", "Ethernet0")
        assert "mode" not in port_entry
        assert port_entry.get("lanes") == "0"

        po_entry = dbmgtr.configDB.get_entry("PORTCHANNEL", "PortChannel0001")
        assert "mode" not in po_entry
        assert po_entry.get("mtu") == "9100"

    def test_rows_without_mode_are_left_alone(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORT", "Ethernet4", {"lanes": "4"})

        dbmgtr.migrate_remove_switchport_mode()

        assert dbmgtr.configDB.get_entry("PORT", "Ethernet4") == {"lanes": "4"}

    def test_is_idempotent(self):
        # The migration may run more than once.
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORT", "Ethernet8", {"lanes": "8", "mode": "trunk"})

        dbmgtr.migrate_remove_switchport_mode()
        first = dbmgtr.configDB.get_entry("PORT", "Ethernet8")
        dbmgtr.migrate_remove_switchport_mode()

        assert dbmgtr.configDB.get_entry("PORT", "Ethernet8") == first
        assert "mode" not in first

    def test_wired_into_version_202605_01(self):
        dbmgtr = self.migrator()
        import db_migrator

        with mock.patch.object(db_migrator.DBMigrator, 'migrate_route_performance_knobs'), \
                mock.patch.object(db_migrator.DBMigrator, 'migrate_bgp_neighbor_peer_type_asn_conflict'), \
                mock.patch.object(db_migrator.DBMigrator,
                                  'migrate_remove_switchport_mode') as mock_migrate:
            dbmgtr.version_202605_01()

        mock_migrate.assert_called_once()

    def test_unreadable_table_does_not_stop_the_other(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORTCHANNEL", "PortChannel0001", {"mtu": "9100", "mode": "trunk"})
        get_table = dbmgtr.configDB.get_table

        def failing_get_table(table):
            if table == "PORT":
                raise RuntimeError("read failed")
            return get_table(table)

        with mock.patch.object(dbmgtr.configDB, 'get_table', side_effect=failing_get_table):
            dbmgtr.migrate_remove_switchport_mode()

        assert dbmgtr.configDB.get_entry("PORTCHANNEL", "PortChannel0001") == {"mtu": "9100"}

    def test_unwritable_row_does_not_stop_the_others(self):
        dbmgtr = self.migrator()
        dbmgtr.configDB.set_entry("PORT", "Ethernet0", {"lanes": "0", "mode": "access"})
        dbmgtr.configDB.set_entry("PORT", "Ethernet4", {"lanes": "4", "mode": "trunk"})
        set_entry = dbmgtr.configDB.set_entry

        def failing_set_entry(table, key, data):
            if key == "Ethernet0":
                raise RuntimeError("write failed")
            return set_entry(table, key, data)

        with mock.patch.object(dbmgtr.configDB, 'set_entry', side_effect=failing_set_entry):
            dbmgtr.migrate_remove_switchport_mode()

        assert dbmgtr.configDB.get_entry("PORT", "Ethernet0")["mode"] == "access"
        assert dbmgtr.configDB.get_entry("PORT", "Ethernet4") == {"lanes": "4"}
>>>>>>> 917270d3 (NOS-16717: derive the switchport mode instead of storing it (#1083))
