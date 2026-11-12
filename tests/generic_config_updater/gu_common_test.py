import copy
import json
import jsonpatch
import sonic_yang
import unittest
import mock

from unittest.mock import MagicMock, Mock
from mock import patch
from .gutest_helpers import create_side_effect_dict, Files
import generic_config_updater.gu_common as gu_common

class TestDryRunConfigWrapper(unittest.TestCase):
    @patch('generic_config_updater.gu_common.subprocess.Popen')
    def test_get_config_db_as_json(self, mock_popen):
        config_wrapper = gu_common.DryRunConfigWrapper()
        mock_proc = MagicMock()
        mock_proc.communicate = MagicMock(
            return_value=('{"PORT": {}, "bgpraw": ""}', None))
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        actual = config_wrapper.get_config_db_as_json()
        expected = {"PORT": {}}
        self.assertDictEqual(actual, expected)

    def test_get_config_db_as_json__returns_imitated_config_db(self):
        # Arrange
        config_wrapper = gu_common.DryRunConfigWrapper(Files.CONFIG_DB_AS_JSON)
        expected = Files.CONFIG_DB_AS_JSON

        # Act
        actual = config_wrapper.get_config_db_as_json()

        # Assert
        self.assertDictEqual(expected, actual)

    def test_get_sonic_yang_as_json__returns_imitated_config_db_as_yang(self):
        # Arrange
        config_wrapper = gu_common.DryRunConfigWrapper(Files.CONFIG_DB_AS_JSON)
        expected = Files.SONIC_YANG_AS_JSON

        # Act
        actual = config_wrapper.get_sonic_yang_as_json()

        # Assert
        self.assertDictEqual(expected, actual)

    def test_apply_change_to_config_db__multiple_calls__changes_imitated_config_db(self):
        # Arrange
        imitated_config_db = Files.CONFIG_DB_AS_JSON
        config_wrapper = gu_common.DryRunConfigWrapper(imitated_config_db)

        changes = [gu_common.JsonChange(jsonpatch.JsonPatch([{'op':'remove', 'path':'/VLAN'}])),
                   gu_common.JsonChange(jsonpatch.JsonPatch([{'op':'remove', 'path':'/ACL_TABLE'}])),
                   gu_common.JsonChange(jsonpatch.JsonPatch([{'op':'remove', 'path':'/PORT'}]))
                  ]

        expected = imitated_config_db
        actual = config_wrapper.get_config_db_as_json()
        for change in changes:
            # Act
            actual = config_wrapper.apply_change_to_config_db(actual, change)
            expected = change.apply(expected)

            # Assert
            self.assertDictEqual(expected, actual)

class TestConfigWrapper(unittest.TestCase):
    def setUp(self):
        self.config_wrapper_mock = gu_common.ConfigWrapper()
        self.config_wrapper_mock.get_config_db_as_json=MagicMock(return_value=Files.CONFIG_DB_AS_JSON)

    def test_ctor__default_values_set(self):
        config_wrapper = gu_common.ConfigWrapper()

        self.assertEqual("/usr/local/yang-models", gu_common.YANG_DIR)

    @patch('generic_config_updater.gu_common.subprocess.Popen')
    def test_get_config_db_as_text(self, mock_popen):
        config_wrapper = gu_common.ConfigWrapper()
        mock_proc = MagicMock()
        mock_proc.communicate = MagicMock(
            return_value=("[]", None))
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        actual = config_wrapper._get_config_db_as_text()
        expected = "[]"
        self.assertEqual(actual, expected)

        config_wrapper = gu_common.ConfigWrapper(scope="asic0")
        mock_proc = MagicMock()
        mock_proc.communicate = MagicMock(
            return_value=("[]", None))
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        actual = config_wrapper._get_config_db_as_text()
        expected = "[]"
        self.assertEqual(actual, expected)

    def test_get_sonic_yang_as_json__returns_sonic_yang_as_json(self):
        # Arrange
        config_wrapper = self.config_wrapper_mock
        expected = Files.SONIC_YANG_AS_JSON

        # Act
        actual = config_wrapper.get_sonic_yang_as_json()

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_config_db_to_sonic_yang__empty_config_db__returns_empty_sonic_yang(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = {}

        # Act
        actual = config_wrapper.convert_config_db_to_sonic_yang({})

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_config_db_to_sonic_yang__non_empty_config_db__returns_sonic_yang_as_json(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = Files.SONIC_YANG_AS_JSON

        # Act
        actual = config_wrapper.convert_config_db_to_sonic_yang(Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_sonic_yang_to_config_db__empty_sonic_yang__returns_empty_config_db(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = {}

        # Act
        actual = config_wrapper.convert_sonic_yang_to_config_db({})

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_sonic_yang_to_config_db__non_empty_sonic_yang__returns_config_db_as_json(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = Files.CROPPED_CONFIG_DB_AS_JSON

        # Act
        actual = config_wrapper.convert_sonic_yang_to_config_db(Files.SONIC_YANG_AS_JSON)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_sonic_yang_to_config_db__table_name_without_colons__returns_config_db_as_json(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = Files.CROPPED_CONFIG_DB_AS_JSON

        # Act
        actual = config_wrapper.convert_sonic_yang_to_config_db(Files.SONIC_YANG_AS_JSON_WITHOUT_COLONS)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_convert_sonic_yang_to_config_db__table_name_with_unexpected_colons__returns_config_db_as_json(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = Files.CROPPED_CONFIG_DB_AS_JSON

        # Act and assert
        self.assertRaises(ValueError,
                          config_wrapper.convert_sonic_yang_to_config_db,
                          Files.SONIC_YANG_AS_JSON_WITH_UNEXPECTED_COLONS)

    def test_validate_sonic_yang_config__valid_config__returns_true(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = True

        # Act
        actual, error = config_wrapper.validate_sonic_yang_config(Files.SONIC_YANG_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)
        self.assertIsNone(error)

    def test_validate_sonic_yang_config__invvalid_config__returns_false(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = False

        # Act
        actual, error = config_wrapper.validate_sonic_yang_config(Files.SONIC_YANG_AS_JSON_INVALID)

        # Assert
        self.assertEqual(expected, actual)
        self.assertIsNotNone(error)

    def test_validate_config_db_config__valid_config__returns_true(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = True

        # Act
        actual, error = config_wrapper.validate_config_db_config(Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)
        self.assertIsNone(error)

    def test_validate_config_db_config__invalid_config__returns_false(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = False

        # Act
        actual, error = config_wrapper.validate_config_db_config(Files.CONFIG_DB_AS_JSON_INVALID)

        # Assert
        self.assertEqual(expected, actual)
        self.assertIsNotNone(error)

    def test_validate_config_db_config__same_config_called_twice__loadData_called_once(self):
        """Cache hit: second call with same config must not call loadData again."""
        config_wrapper = gu_common.ConfigWrapper()
        mock_sy = MagicMock()
        mock_sy.loadData = MagicMock()
        mock_sy.loadYangModel = MagicMock()
        config_wrapper.sonic_yang_with_loaded_models = mock_sy

        config = {"ACL_TABLE": {}}

        config_wrapper.validate_config_db_config(config)
        config_wrapper.validate_config_db_config(config)

        # loadData should only be called once — second call hits the result cache
        mock_sy.loadData.assert_called_once()

    def test_validate_config_db_config__different_configs__loadData_called_each_time(self):
        """Cache miss: different configs must each call loadData."""
        config_wrapper = gu_common.ConfigWrapper()
        mock_sy = MagicMock()
        mock_sy.loadData = MagicMock()
        config_wrapper.sonic_yang_with_loaded_models = mock_sy

        config_a = {"ACL_TABLE": {"rule1": {}}}
        config_b = {"ACL_TABLE": {"rule2": {}}}

        config_wrapper.validate_config_db_config(config_a)
        config_wrapper.validate_config_db_config(config_b)

        self.assertEqual(2, mock_sy.loadData.call_count)

    def test_find_ref_paths__after_validate_same_config__loadData_skipped(self):
        """
        Core optimization: if validate_config_db_config already loaded config into sy,
        find_ref_paths with the same config must skip loadData entirely.
        """
        config_wrapper = gu_common.ConfigWrapper()
        mock_sy = MagicMock()
        mock_sy.loadData = MagicMock()
        mock_sy.root = MagicMock()
        mock_sy.root.find_path = MagicMock(return_value=MagicMock(data=MagicMock(return_value=[])))
        config_wrapper.sonic_yang_with_loaded_models = mock_sy

        path_addressing = gu_common.PathAddressing(config_wrapper)
        config = {"ACL_TABLE": {}}

        # First: validate loads the config into sy and sets _currently_loaded_hash
        config_wrapper.validate_config_db_config(config)
        self.assertIsNotNone(config_wrapper._currently_loaded_hash,
                             "validate_config_db_config should have set _currently_loaded_hash")
        load_count_after_validate = mock_sy.loadData.call_count

        # Second: find_ref_paths with same config should NOT call loadData again
        path_addressing.find_ref_paths("/ACL_TABLE", config, reload_config=True)
        load_count_after_find = mock_sy.loadData.call_count

        self.assertEqual(load_count_after_validate, load_count_after_find,
                         "find_ref_paths should skip loadData when validate already loaded same config")

    def test_find_ref_paths__after_validate_different_config__loadData_called(self):
        """
        Cache miss in find_ref_paths: if validate loaded config_A, calling find_ref_paths
        with config_B must still call loadData.
        """
        config_wrapper = gu_common.ConfigWrapper()
        mock_sy = MagicMock()
        mock_sy.loadData = MagicMock()
        mock_sy.root = MagicMock()
        mock_sy.root.find_path = MagicMock(return_value=MagicMock(data=MagicMock(return_value=[])))
        config_wrapper.sonic_yang_with_loaded_models = mock_sy

        path_addressing = gu_common.PathAddressing(config_wrapper)
        config_a = {"ACL_TABLE": {"rule1": {}}}
        config_b = {"ACL_TABLE": {"rule2": {}}}

        config_wrapper.validate_config_db_config(config_a)
        self.assertIsNotNone(config_wrapper._currently_loaded_hash,
                             "validate_config_db_config should have set _currently_loaded_hash")
        load_count_after_validate = mock_sy.loadData.call_count

        path_addressing.find_ref_paths("/ACL_TABLE", config_b, reload_config=True)
        load_count_after_find = mock_sy.loadData.call_count

        self.assertEqual(load_count_after_find, load_count_after_validate + 1,
                         "find_ref_paths should call loadData exactly once when config differs")

    def test_validate_bgp_peer_group__valid_non_intersecting_ip_ranges__returns_true(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {
            "BGP_PEER_RANGE":
            {
                "BGPSLBPassive": {
                    "ip_range": ["1.1.1.1/31", "10.10.10.10/16", "100.100.100.100/24"]
                },
                "BgpVac": {
                    "ip_range": ["2.2.2.2/31", "20.20.20.20/16", "200.200.200.200/24"]
                }
            }
        }

        # Act
        actual, error = config_wrapper.validate_bgp_peer_group(config)

        # Assert
        self.assertTrue(actual)
        self.assertIsNone(error)

    def test_validate_bgp_peer_group__valid_intersecting_ip_ranges_in_different_vrfs__returns_true(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {
            "BGP_PEER_RANGE":
            {
                "VnetA|WLPARTNER_PASSIVE_V4": {
                    "ip_range": ["1.1.1.1/31", "10.10.10.10/16", "100.100.100.100/24"]
                },
                "VnetB|WLPARTNER_PASSIVE_V4": {
                    "ip_range": ["1.1.1.1/31", "10.10.10.10/16", "100.100.100.100/24"]
                },
                "WLPARTNER_PASSIVE_V4": {
                    "ip_range": ["1.1.1.1/31", "10.10.10.10/16", "100.100.100.100/24"]
                }
            }
        }

        # Act
        actual, error = config_wrapper.validate_bgp_peer_group(config)

        # Assert
        self.assertTrue(actual)
        self.assertIsNone(error)

    def test_validate_bgp_peer_group__same_ip_prefix__return_false(self):
        # duplicate v4 within same ip_range
        self.check_validate_bgp_peer_group(
            ["1.1.1.1/16", "1.1.1.1/16"],
            duplicated_ip="1.1.1.1/16")
        # duplicate v4 within different ip_ranges
        self.check_validate_bgp_peer_group(
            ["1.1.1.1/16"],
            ["1.1.1.1/16"],
            duplicated_ip="1.1.1.1/16")
        # duplicate v4 within different ip_ranges, but many ips
        self.check_validate_bgp_peer_group(
            ["1.1.1.1/16", "1.1.1.1/31", "10.10.10.10/16", "100.100.100.100/24"],
            ["2.2.2.2/31", "20.20.20.20/16", "200.200.200.200/24", "1.1.1.1/16"],
            duplicated_ip="1.1.1.1/16")
        # duplicate v6 within same ip_range
        self.check_validate_bgp_peer_group(
            ["fc00:1::32/16", "fc00:1::32/16"],
            duplicated_ip="fc00:1::32/16")
        # duplicate v6 within different ip_ranges
        self.check_validate_bgp_peer_group(
            ["fc00:1::32/16"],
            ["fc00:1::32/16"],
            duplicated_ip="fc00:1::32/16")
        # duplicate v6 within different ip_ranges, but many ips
        self.check_validate_bgp_peer_group(
            ["fc00:1::32/16", "fc00:1::32/31", "10:1::1/16", "100:1::1/24"],
            ["2:1::1/31", "20:1::1/16", "200:1::1/24", "fc00:1::32/16"],
            duplicated_ip="fc00:1::32/16")

    def check_validate_bgp_peer_group(self, ip_range, other_ip_range=[], duplicated_ip=None):
        # Check both default vrf and same vrf name in non-default vrf
        self._check_validate_bgp_peer_group(ip_range, other_ip_range, duplicated_ip, is_default_vrf=False)
        self._check_validate_bgp_peer_group(ip_range, other_ip_range, duplicated_ip, is_default_vrf=True)

    def _check_validate_bgp_peer_group(self, ip_range, other_ip_range=[], duplicated_ip=None, is_default_vrf=False):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        if is_default_vrf:
            peer_group_name_1 = "BGPSLBPassive"
            peer_group_name_2 = "BgpVac"
        else:
            peer_group_name_1 = "VnetA|WLPARTNER_PASSIVE_V4"
            peer_group_name_2 = "VnetA|WLPARTNER_PASSIVE_V4_2"
        config = {
            "BGP_PEER_RANGE":
            {
                peer_group_name_1: {
                    "ip_range": ip_range
                },
                peer_group_name_2: {
                    "ip_range": other_ip_range
                },
            }
        }

        # Act
        actual, error = config_wrapper.validate_bgp_peer_group(config)

        # Assert
        self.assertFalse(actual)
        self.assertTrue(duplicated_ip in error)

    def test_validate_lanes__no_port_table__success(self):
        config = {"ACL_TABLE": {}}
        self.validate_lanes(config)

    def test_validate_lanes__empty_port_table__success(self):
        config = {"PORT": {}}
        self.validate_lanes(config)

    def test_validate_lanes__empty_lane__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": "", "speed":"10000"}}}
        self.validate_lanes(config, 'has an empty lane')

    def test_validate_lanes__whitespace_lane__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": " ", "speed":"10000"}}}
        self.validate_lanes(config, 'has an empty lane')

    def test_validate_lanes__non_digits_lane__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": "10g", "speed":"10000"}}}
        self.validate_lanes(config, "has an invalid lane '10g'")

    def test_validate_lanes__space_between_digits_lane__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": " 1 0  ", "speed":"10000"}}}
        self.validate_lanes(config, "has an invalid lane '1 0'")

    def test_validate_lanes__single_valid_lane__success(self):
        config = {"PORT": {"Ethernet0": {"lanes": "66", "speed":"10000"}}}
        self.validate_lanes(config)

    def test_validate_lanes__different_valid_lanes_single_port__success(self):
        config = {"PORT": {"Ethernet0": {"lanes": "66, 67, 68", "speed":"10000"}}}
        self.validate_lanes(config)

    def test_validate_lanes__different_valid_and_invalid_empty_lanes_single_port__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": "66, , 68", "speed":"10000"}}}
        self.validate_lanes(config, 'has an empty lane')

    def test_validate_lanes__different_valid_and_invalid_non_digit_lanes_single_port__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": "66, 67, 10g", "speed":"10000"}}}
        self.validate_lanes(config, "has an invalid lane '10g'")

    def test_validate_lanes__different_valid_lanes_multi_ports__success(self):
        config = {"PORT": {
            "Ethernet0": {"lanes": " 64 , 65 \t", "speed":"10000"},
            "Ethernet1": {"lanes": " 66 , 67 \r\t\n, 68 ", "speed":"10000"},
            }}
        self.validate_lanes(config)

    def test_validate_lanes__same_valid_lanes_single_port__failure(self):
        config = {"PORT": {"Ethernet0": {"lanes": "65 \r\t\n, 65", "speed":"10000"}}}
        self.validate_lanes(config, '65')

    def test_validate_lanes__same_valid_lanes_multi_ports__failure(self):
        config = {"PORT": {
            "Ethernet0": {"lanes": "64, 65, 67", "speed":"10000"},
            "Ethernet1": {"lanes": "66, 67, 68", "speed":"10000"},
            }}
        self.validate_lanes(config, '67')

    def test_validate_lanes__same_valid_lanes_multi_ports_no_spaces__failure(self):
        config = {"PORT": {
            "Ethernet0": {"lanes": "64,65,67", "speed":"10000"},
            "Ethernet1": {"lanes": "66,67,68", "speed":"10000"},
            }}
        self.validate_lanes(config, '67')

    def validate_lanes(self, config_db, expected_error=None):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = expected_error is None # if expected_error is None, then the input is valid

        # Act
        actual, error = config_wrapper.validate_lanes(config_db)

        # Assert
        self.assertEqual(expected, actual)
        if expected_error:
            self.assertTrue(expected_error in error)

    def test_crop_tables_without_yang__returns_cropped_config_db_as_json(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        expected = Files.CROPPED_CONFIG_DB_AS_JSON

        # Act
        actual = config_wrapper.crop_tables_without_yang(Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_get_empty_tables__no_empty_tables__returns_no_tables(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}}

        # Act
        empty_tables = config_wrapper.get_empty_tables(config)

        # Assert
        self.assertCountEqual([], empty_tables)

    def test_get_empty_tables__single_empty_table__returns_one_table(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}, "another_table":{}}

        # Act
        empty_tables = config_wrapper.get_empty_tables(config)

        # Assert
        self.assertCountEqual(["another_table"], empty_tables)

    def test_get_empty_tables__multiple_empty_tables__returns_multiple_tables(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}, "another_table":{}, "yet_another_table":{}}

        # Act
        empty_tables = config_wrapper.get_empty_tables(config)

        # Assert
        self.assertCountEqual(["another_table", "yet_another_table"], empty_tables)

    def test_remove_empty_tables__no_empty_tables__returns_whole_config(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}}

        # Act
        actual = config_wrapper.remove_empty_tables(config)

        # Assert
        self.assertDictEqual({"any_table": {"key": "value"}}, actual)

    def test_remove_empty_tables__single_empty_tables__returns_config_without_empty_table(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}, "another_table":{}}

        # Act
        actual = config_wrapper.remove_empty_tables(config)

        # Assert
        self.assertDictEqual({"any_table": {"key": "value"}}, actual)

    def test_remove_empty_tables__multiple_empty_tables__returns_config_without_empty_tables(self):
        # Arrange
        config_wrapper = gu_common.ConfigWrapper()
        config = {"any_table": {"key": "value"}, "another_table":{}, "yet_another_table":{}}

        # Act
        actual = config_wrapper.remove_empty_tables(config)

        # Assert
        self.assertDictEqual({"any_table": {"key": "value"}}, actual)


class TestPatchWrapper(unittest.TestCase):
    def setUp(self):
        self.config_wrapper_mock = gu_common.ConfigWrapper()
        self.config_wrapper_mock.get_config_db_as_json=MagicMock(return_value=Files.CONFIG_DB_AS_JSON)

    def test_validate_config_db_patch_has_yang_models__table_without_yang_model__returns_false(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        patch = [ { 'op': 'remove', 'path': '/TABLE_WITHOUT_YANG' } ]
        expected = False

        # Act
        actual = patch_wrapper.validate_config_db_patch_has_yang_models(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_validate_config_db_patch_has_yang_models__table_with_yang_model__returns_true(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        patch = [ { 'op': 'remove', 'path': '/ACL_TABLE' } ]
        expected = True

        # Act
        actual = patch_wrapper.validate_config_db_patch_has_yang_models(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_config_db_patch_to_sonic_yang_patch__invalid_config_db_patch__failure(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        patch = [ { 'op': 'remove', 'path': '/TABLE_WITHOUT_YANG' } ]

        # Act and Assert
        self.assertRaises(ValueError, patch_wrapper.convert_config_db_patch_to_sonic_yang_patch, patch)

    def test_same_patch__no_diff__returns_true(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()

        # Act and Assert
        self.assertTrue(patch_wrapper.verify_same_json(Files.CONFIG_DB_AS_JSON, Files.CONFIG_DB_AS_JSON))

    def test_same_patch__diff__returns_false(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()

        # Act and Assert
        self.assertFalse(patch_wrapper.verify_same_json(Files.CONFIG_DB_AS_JSON, Files.CROPPED_CONFIG_DB_AS_JSON))

    def test_generate_patch__no_diff__empty_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()

        # Act
        patch = patch_wrapper.generate_patch(Files.CONFIG_DB_AS_JSON, Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertFalse(patch)

    def test_simulate_patch__empty_patch__no_changes(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        patch = jsonpatch.JsonPatch([])
        expected = Files.CONFIG_DB_AS_JSON

        # Act
        actual = patch_wrapper.simulate_patch(patch, Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_simulate_patch__non_empty_patch__changes_applied(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        patch = Files.SINGLE_OPERATION_CONFIG_DB_PATCH
        expected = Files.SINGLE_OPERATION_CONFIG_DB_PATCH.apply(Files.CONFIG_DB_AS_JSON)

        # Act
        actual = patch_wrapper.simulate_patch(patch, Files.CONFIG_DB_AS_JSON)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_simulate_config_db_patch__empties_leaf_list__field_is_dropped(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        config = {
            "BGP_ALLOWED_PREFIXES": {
                "DEPLOYMENT_ID|0": {
                    "prefixes_v4": ["10.20.0.0/16"],
                    "prefixes_v6": ["fc01:20::/64"],
                }
            }
        }
        patch = jsonpatch.JsonPatch(
            [{"op": "remove", "path": "/BGP_ALLOWED_PREFIXES/DEPLOYMENT_ID|0/prefixes_v4/0"}])
        # ConfigDB cannot store an empty leaf-list, the field has to be absent
        expected = {"BGP_ALLOWED_PREFIXES": {"DEPLOYMENT_ID|0": {"prefixes_v6": ["fc01:20::/64"]}}}

        # Act
        actual = patch_wrapper.simulate_config_db_patch(patch, config)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_simulate_config_db_patch__leaf_list_still_has_items__field_is_kept(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        config = {
            "BGP_ALLOWED_PREFIXES": {
                "DEPLOYMENT_ID|0": {
                    "prefixes_v4": ["10.20.0.0/16", "10.30.0.0/16"],
                }
            }
        }
        patch = jsonpatch.JsonPatch(
            [{"op": "remove", "path": "/BGP_ALLOWED_PREFIXES/DEPLOYMENT_ID|0/prefixes_v4/0"}])
        expected = {"BGP_ALLOWED_PREFIXES": {"DEPLOYMENT_ID|0": {"prefixes_v4": ["10.30.0.0/16"]}}}

        # Act
        actual = patch_wrapper.simulate_config_db_patch(patch, config)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_simulate_patch__sonic_yang_config__empty_yang_list_is_kept(self):
        # Arrange
        # simulate_patch must stay shape agnostic. In SonicYang json a list holds yang list
        # entries, not leaf-list items, so it must not be treated as an empty leaf-list.
        patch_wrapper = gu_common.PatchWrapper()
        config = {"sonic-vlan:sonic-vlan": {"VLAN": {"VLAN_LIST": [{"name": "Vlan1000"}]}}}
        patch = jsonpatch.JsonPatch(
            [{"op": "remove", "path": "/sonic-vlan:sonic-vlan/VLAN/VLAN_LIST/0"}])
        expected = {"sonic-vlan:sonic-vlan": {"VLAN": {"VLAN_LIST": []}}}

        # Act
        actual = patch_wrapper.simulate_patch(patch, config)

        # Assert
        self.assertDictEqual(expected, actual)

    def test_generate_patch__diff__non_empty_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper()
        after_update_json = Files.SINGLE_OPERATION_CONFIG_DB_PATCH.apply(Files.CONFIG_DB_AS_JSON)
        expected = Files.SINGLE_OPERATION_CONFIG_DB_PATCH

        # Act
        actual = patch_wrapper.generate_patch(Files.CONFIG_DB_AS_JSON, after_update_json)

        # Assert
        self.assertTrue(actual)
        self.assertEqual(expected, actual)

    def test_convert_config_db_patch_to_sonic_yang_patch__empty_patch__returns_empty_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = self.config_wrapper_mock)
        patch = jsonpatch.JsonPatch([])
        expected = jsonpatch.JsonPatch([])

        # Act
        actual = patch_wrapper.convert_config_db_patch_to_sonic_yang_patch(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_config_db_patch_to_sonic_yang_patch__single_operation_patch__returns_sonic_yang_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = self.config_wrapper_mock)
        patch = Files.SINGLE_OPERATION_CONFIG_DB_PATCH
        expected = Files.SINGLE_OPERATION_SONIC_YANG_PATCH

        # Act
        actual = patch_wrapper.convert_config_db_patch_to_sonic_yang_patch(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_config_db_patch_to_sonic_yang_patch__multiple_operations_patch__returns_sonic_yang_patch(self):
        # Arrange
        config_wrapper = self.config_wrapper_mock
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = config_wrapper)
        config_db_patch = Files.MULTI_OPERATION_CONFIG_DB_PATCH

        # Act
        sonic_yang_patch = patch_wrapper.convert_config_db_patch_to_sonic_yang_patch(config_db_patch)

        # Assert
        self.__assert_same_patch(config_db_patch, sonic_yang_patch, config_wrapper, patch_wrapper)

    def test_convert_sonic_yang_patch_to_config_db_patch__empty_patch__returns_empty_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = self.config_wrapper_mock)
        patch = jsonpatch.JsonPatch([])
        expected = jsonpatch.JsonPatch([])

        # Act
        actual = patch_wrapper.convert_sonic_yang_patch_to_config_db_patch(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_sonic_yang_patch_to_config_db_patch__single_operation_patch__returns_config_db_patch(self):
        # Arrange
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = self.config_wrapper_mock)
        patch = Files.SINGLE_OPERATION_SONIC_YANG_PATCH
        expected = Files.SINGLE_OPERATION_CONFIG_DB_PATCH

        # Act
        actual = patch_wrapper.convert_sonic_yang_patch_to_config_db_patch(patch)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_sonic_yang_patch_to_config_db_patch__multiple_operations_patch__returns_config_db_patch(self):
        # Arrange
        config_wrapper = self.config_wrapper_mock
        patch_wrapper = gu_common.PatchWrapper(config_wrapper = config_wrapper)
        sonic_yang_patch = Files.MULTI_OPERATION_SONIC_YANG_PATCH

        # Act
        config_db_patch = patch_wrapper.convert_sonic_yang_patch_to_config_db_patch(sonic_yang_patch)

        # Assert
        self.__assert_same_patch(config_db_patch, sonic_yang_patch, config_wrapper, patch_wrapper)

    def __assert_same_patch(self, config_db_patch, sonic_yang_patch, config_wrapper, patch_wrapper):
        sonic_yang = config_wrapper.get_sonic_yang_as_json()
        config_db = config_wrapper.get_config_db_as_json()

        after_update_sonic_yang = patch_wrapper.simulate_patch(sonic_yang_patch, sonic_yang)
        after_update_config_db = patch_wrapper.simulate_patch(config_db_patch, config_db)
        after_update_config_db_cropped = config_wrapper.crop_tables_without_yang(after_update_config_db)

        after_update_sonic_yang_as_config_db = \
            config_wrapper.convert_sonic_yang_to_config_db(after_update_sonic_yang)

        self.assertTrue(patch_wrapper.verify_same_json(after_update_config_db_cropped, after_update_sonic_yang_as_config_db))

class TestPathAddressing(unittest.TestCase):
    def setUp(self):
        self.path_addressing = gu_common.PathAddressing(gu_common.ConfigWrapper())
        self.sy_only_models = sonic_yang.SonicYang(gu_common.YANG_DIR)
        self.sy_only_models.loadYangModel()

    def test_get_path_tokens(self):
        def check(path, tokens):
            expected=tokens
            actual=self.path_addressing.get_path_tokens(path)
            self.assertEqual(expected, actual)

        check("", [])
        check("/", [])
        check("/token", ["token"])
        check("/more/than/one/token", ["more", "than", "one", "token"])
        check("/has/numbers/0/and/symbols/^", ["has", "numbers", "0", "and", "symbols", "^"])
        check("/~0/this/is/telda", ["~", "this", "is", "telda"])
        check("/~1/this/is/forward-slash", ["/", "this", "is", "forward-slash"])
        check("/\\\\/no-escaping", ["\\\\", "no-escaping"])
        check("////empty/tokens/are/ok", ["", "", "", "empty", "tokens", "are", "ok"])

    def test_create_path(self):
        def check(tokens, path):
            expected=path
            actual=self.path_addressing.create_path(tokens)
            self.assertEqual(expected, actual)

        check([], "",)
        check([""], "/",)
        check(["token"], "/token")
        check(["more", "than", "one", "token"], "/more/than/one/token")
        check(["has", "numbers", "0", "and", "symbols", "^"], "/has/numbers/0/and/symbols/^")
        check(["~", "this", "is", "telda"], "/~0/this/is/telda")
        check(["/", "this", "is", "forward-slash"], "/~1/this/is/forward-slash")
        check(["\\\\", "no-escaping"], "/\\\\/no-escaping")
        check(["", "", "", "empty", "tokens", "are", "ok"], "////empty/tokens/are/ok")
        check(["~token", "telda-not-followed-by-0-or-1"], "/~0token/telda-not-followed-by-0-or-1")

    def test_get_xpath_tokens(self):
        def check(path, tokens):
            expected=tokens
            actual=self.path_addressing.get_xpath_tokens(path)
            self.assertEqual(expected, actual)

        self.assertRaises(ValueError, check, "", [])
        check("/", [])
        check("/token", ["token"])
        check("/more/than/one/token", ["more", "than", "one", "token"])
        check("/multi/tokens/with/empty/last/token/", ["multi", "tokens", "with", "empty", "last", "token", ""])
        check("/has/numbers/0/and/symbols/^", ["has", "numbers", "0", "and", "symbols", "^"])
        check("/has[a='predicate']/in/the/beginning", ["has[a='predicate']", "in", "the", "beginning"])
        check("/ha/s[a='predicate']/in/the/middle", ["ha", "s[a='predicate']", "in", "the", "middle"])
        check("/ha/s[a='predicate-in-the-end']", ["ha", "s[a='predicate-in-the-end']"])
        check("/it/has[more='than'][one='predicate']/somewhere", ["it", "has[more='than'][one='predicate']", "somewhere"])
        check("/ha/s[a='predicate\"with']/double-quotes/inside", ["ha", "s[a='predicate\"with']", "double-quotes", "inside"])
        check('/a/predicate[with="double"]/quotes', ["a", 'predicate[with="double"]', "quotes"])
        check('/multiple["predicate"][with="double"]/quotes', ['multiple["predicate"][with="double"]', "quotes"])
        check('/multiple["predicate"][with="double"]/quotes', ['multiple["predicate"][with="double"]', "quotes"])
        check('/ha/s[a="predicate\'with"]/single-quote/inside', ["ha", 's[a="predicate\'with"]', "single-quote", "inside"])
        # XPATH 1.0 does not support single-quote within single-quoted string. str literal can be '[^']*'
        # Not validating no single-quote within single-quoted string
        check("/a/mix['of''quotes\"does']/not/work/well", ["a", "mix['of''quotes\"does']", "not", "work", "well"])
        # XPATH 1.0 does not support double-quotes within double-quoted string. str literal can be "[^"]*"
        # Not validating no double-quotes within double-quoted string
        check('/a/mix["of""quotes\'does"]/not/work/well', ["a", 'mix["of""quotes\'does"]', "not", "work", "well"])

    def test_find_ref_paths__ref_is_the_whole_key__returns_ref_paths(self):
        # Arrange
        path = "/PORT/Ethernet0"
        expected = [
            "/ACL_TABLE/NO-NSW-PACL-V4/ports/0",
            "/VLAN_MEMBER/Vlan1000|Ethernet0",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CROPPED_CONFIG_DB_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__ref_is_a_part_of_key__returns_ref_paths(self):
        # Arrange
        path = "/VLAN/Vlan1000"
        expected = [
            "/VLAN_MEMBER/Vlan1000|Ethernet0",
            "/VLAN_MEMBER/Vlan1000|Ethernet4",
            "/VLAN_MEMBER/Vlan1000|Ethernet8",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CROPPED_CONFIG_DB_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__ref_is_in_multilist__returns_ref_paths(self):
        # Arrange
        path = "/PORT/Ethernet8"
        expected = [
            "/INTERFACE/Ethernet8",
            "/INTERFACE/Ethernet8|10.0.0.1~130",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CONFIG_DB_WITH_INTERFACE)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__ref_is_in_leafref_union__returns_ref_paths(self):
        # Arrange
        path = "/PORTCHANNEL/PortChannel0001"
        expected = [
            "/ACL_TABLE/NO-NSW-PACL-V4/ports/1",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CONFIG_DB_WITH_PORTCHANNEL_AND_ACL)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__path_is_table__returns_ref_paths(self):
        # Arrange
        path = "/PORT"
        expected = [
            "/ACL_TABLE/DATAACL/ports/0",
            "/ACL_TABLE/EVERFLOW/ports/0",
            "/ACL_TABLE/EVERFLOWV6/ports/0",
            "/ACL_TABLE/EVERFLOWV6/ports/1",
            "/ACL_TABLE/NO-NSW-PACL-V4/ports/0",
            "/VLAN_MEMBER/Vlan1000|Ethernet0",
            "/VLAN_MEMBER/Vlan1000|Ethernet4",
            "/VLAN_MEMBER/Vlan1000|Ethernet8"
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CROPPED_CONFIG_DB_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__whole_config_path__returns_all_refs(self):
        # Arrange
        path = ""
        expected = [
            "/ACL_TABLE/DATAACL/ports/0",
            "/ACL_TABLE/EVERFLOW/ports/0",
            "/ACL_TABLE/EVERFLOWV6/ports/0",
            "/ACL_TABLE/EVERFLOWV6/ports/1",
            "/ACL_TABLE/NO-NSW-PACL-V4/ports/0",
            "/VLAN_MEMBER/Vlan1000|Ethernet0",
            "/VLAN_MEMBER/Vlan1000|Ethernet4",
            "/VLAN_MEMBER/Vlan1000|Ethernet8",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CROPPED_CONFIG_DB_AS_JSON)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__path_and_ref_paths_are_under_same_yang_container__returns_ref_paths(self):
        # Arrange
        path = "/LOOPBACK_INTERFACE/Loopback0"
        expected = [
            self.path_addressing.create_path(["LOOPBACK_INTERFACE", "Loopback0|10.1.0.32/32"]),
            self.path_addressing.create_path(["LOOPBACK_INTERFACE", "Loopback0|1100:1::32/128"]),
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CONFIG_DB_WITH_LOOPBACK_INTERFACES)

        # Assert
        self.assertEqual(expected, actual)

    def test_find_ref_paths__does_not_remove_tables_without_yang(self):
        # Arrange
        config = Files.CONFIG_DB_AS_JSON # This has a table without yang named 'TABLE_WITHOUT_YANG'
        any_path = ""
        expected_config = copy.deepcopy(config)

        # Act
        self.path_addressing.find_ref_paths(any_path, config)

        # Assert
        self.assertEqual(expected_config, config)

    def test_find_ref_paths__ref_path_is_leaflist_in_yang_but_string_in_config_db__path_to_string_returned(self):
        # Arrange
        path = "/BUFFER_PROFILE/egress_lossless_profile"
        expected = [
            "/BUFFER_PORT_EGRESS_PROFILE_LIST/Ethernet9/profile_list",
        ]

        # Act
        actual = self.path_addressing.find_ref_paths(path, Files.CONFIG_DB_WITH_PROFILE_LIST)

        # Assert
        self.assertEqual(expected, actual)

    def test_convert_path_to_xpath(self):
        def check(path, xpath, config=None):
            if not config:
                config = Files.CROPPED_CONFIG_DB_AS_JSON

            expected=xpath
            actual=self.path_addressing.convert_path_to_xpath(path, config, self.sy_only_models)
            self.assertEqual(expected, actual)

        check(path="", xpath="/")
        check(path="/VLAN_MEMBER", xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER")
        check(path="/VLAN/Vlan1000/dhcp_servers",
              xpath="/sonic-vlan:sonic-vlan/VLAN/VLAN_LIST[name='Vlan1000']/dhcp_servers")
        check(path="/VLAN/Vlan1000/dhcp_servers/0",
              xpath="/sonic-vlan:sonic-vlan/VLAN/VLAN_LIST[name='Vlan1000']/dhcp_servers[.='192.0.0.1']")
        check(path="/PORT/Ethernet0/lanes", xpath="/sonic-port:sonic-port/PORT/PORT_LIST[name='Ethernet0']/lanes")
        check(path="/ACL_TABLE/NO-NSW-PACL-V4/ports/0",
              xpath="/sonic-acl:sonic-acl/ACL_TABLE/ACL_TABLE_LIST[ACL_TABLE_NAME='NO-NSW-PACL-V4']/ports[.='Ethernet0']")
        check(path="/ACL_TABLE/NO-NSW-PACL-V4/ports/0",
              xpath="/sonic-acl:sonic-acl/ACL_TABLE/ACL_TABLE_LIST[ACL_TABLE_NAME='NO-NSW-PACL-V4']/ports[.='Ethernet0']")
        check(path="/VLAN_MEMBER/Vlan1000|Ethernet8/tagging_mode",
             xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']/tagging_mode")
        check(path="/VLAN_MEMBER/Vlan1000|Ethernet8",
              xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']")
        check(path="/DEVICE_METADATA/localhost/hwsku",
              xpath="/sonic-device_metadata:sonic-device_metadata/DEVICE_METADATA/localhost/hwsku",
              config=Files.CONFIG_DB_WITH_DEVICE_METADATA)
        check(path="/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK/FLEX_COUNTER_STATUS",
              xpath="/sonic-flex_counter:sonic-flex_counter/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK/FLEX_COUNTER_STATUS",
              config=Files.CONTRAINER_WITH_CONTAINER_CONFIG_DB)
        check(path="/ACL_RULE/SSH_ONLY|RULE1/L4_SRC_PORT",
              xpath="/sonic-acl:sonic-acl/ACL_RULE/ACL_RULE_LIST[ACL_TABLE_NAME='SSH_ONLY'][RULE_NAME='RULE1']/L4_SRC_PORT",
              config=Files.CONFIG_DB_CHOICE)
        check(path="/INTERFACE/Ethernet8",
              xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_LIST[name='Ethernet8']",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(path="/INTERFACE/Ethernet8|10.0.0.1~130",
              xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_IPPREFIX_LIST[name='Ethernet8'][ip-prefix='10.0.0.1/30']",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(path="/INTERFACE/Ethernet8|10.0.0.1~130/scope",
              xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_IPPREFIX_LIST[name='Ethernet8'][ip-prefix='10.0.0.1/30']/scope",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(path="/PORTCHANNEL_INTERFACE",
              xpath="/sonic-portchannel:sonic-portchannel/PORTCHANNEL_INTERFACE",
              config=Files.CONFIG_DB_WITH_PORTCHANNEL_INTERFACE)
        check(path="/PORTCHANNEL_INTERFACE/PortChannel0001|1.1.1.1~124",
              xpath="/sonic-portchannel:sonic-portchannel/PORTCHANNEL_INTERFACE/PORTCHANNEL_INTERFACE_IPPREFIX_LIST[name='PortChannel0001'][ip_prefix='1.1.1.1/24']",
              config=Files.CONFIG_DB_WITH_PORTCHANNEL_INTERFACE)
        check(path="/BGP_NEIGHBOR/1.2.3.4/holdtime",
              xpath="/sonic-bgp-neighbor:sonic-bgp-neighbor/BGP_NEIGHBOR/BGP_NEIGHBOR_TEMPLATE_LIST[neighbor='1.2.3.4']/holdtime",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(path="/BGP_NEIGHBOR/default|1.2.3.4/asn",
              xpath="/sonic-bgp-neighbor:sonic-bgp-neighbor/BGP_NEIGHBOR/BGP_NEIGHBOR_LIST[vrf_name='default'][neighbor='1.2.3.4']/asn",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(path="/BGP_MONITORS/5.6.7.8/name",
              xpath="/sonic-bgp-monitor:sonic-bgp-monitor/BGP_MONITORS/BGP_MONITORS_LIST[addr='5.6.7.8']/name",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(path="/LLDP/GLOBAL/mode",
              xpath="/sonic-lldp:sonic-lldp/LLDP/GLOBAL/mode",
              config=Files.CONFIG_DB_WITH_LLDP)
        check(path="/BUFFER_PORT_EGRESS_PROFILE_LIST/Ethernet9/profile_list",
              xpath="/sonic-buffer-port-egress-profile-list:sonic-buffer-port-egress-profile-list/BUFFER_PORT_EGRESS_PROFILE_LIST/BUFFER_PORT_EGRESS_PROFILE_LIST_LIST[port='Ethernet9']/profile_list",
              config=Files.CONFIG_DB_WITH_PROFILE_LIST)
        check(path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1",
              xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1/2",
              xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']/DOT1P_TO_TC_MAP[dot1p='2']",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(path="/EXP_TO_FC_MAP/Exp_to_fc_map2/4",
              xpath="/sonic-exp-fc-map:sonic-exp-fc-map/EXP_TO_FC_MAP/EXP_TO_FC_MAP_LIST[name='Exp_to_fc_map2']/EXP_TO_FC_MAP[exp='4']",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)

    def test_convert_xpath_to_path(self):
        def check(xpath, path, config=None):
            if not config:
                config = Files.CROPPED_CONFIG_DB_AS_JSON

            expected=path
            actual=self.path_addressing.convert_xpath_to_path(xpath, config, self.sy_only_models)
            self.assertEqual(expected, actual)

        check(xpath="/",path="")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER", path="/VLAN_MEMBER")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST",path="/VLAN_MEMBER")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']/name",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']/port",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']/tagging_mode",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8/tagging_mode")
        check(xpath="/sonic-vlan:sonic-acl/ACL_RULE", path="/ACL_RULE")
        check(xpath="/sonic-vlan:sonic-acl/ACL_RULE/ACL_RULE_LIST[ACL_TABLE_NAME='SSH_ONLY'][RULE_NAME='RULE1']",
              path="/ACL_RULE/SSH_ONLY|RULE1",
              config=Files.CONFIG_DB_CHOICE)
        check(xpath="/sonic-acl:sonic-acl/ACL_RULE/ACL_RULE_LIST[ACL_TABLE_NAME='SSH_ONLY'][RULE_NAME='RULE1']/L4_SRC_PORT",
              path="/ACL_RULE/SSH_ONLY|RULE1/L4_SRC_PORT",
              config=Files.CONFIG_DB_CHOICE)
        check(xpath="/sonic-vlan:sonic-vlan/VLAN/VLAN_LIST[name='Vlan1000']/dhcp_servers",
              path="/VLAN/Vlan1000/dhcp_servers")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN/VLAN_LIST[name='Vlan1000']/dhcp_servers[.='192.0.0.1']",
              path="/VLAN/Vlan1000/dhcp_servers/0")
        check(xpath="/sonic-port:sonic-port/PORT/PORT_LIST[name='Ethernet0']/lanes", path="/PORT/Ethernet0/lanes")
        check(xpath="/sonic-acl:sonic-acl/ACL_TABLE/ACL_TABLE_LIST[ACL_TABLE_NAME='NO-NSW-PACL-V4']/ports[.='Ethernet0']",
              path="/ACL_TABLE/NO-NSW-PACL-V4/ports/0")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']/tagging_mode",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8/tagging_mode")
        check(xpath="/sonic-vlan:sonic-vlan/VLAN_MEMBER/VLAN_MEMBER_LIST[name='Vlan1000'][port='Ethernet8']",
              path="/VLAN_MEMBER/Vlan1000|Ethernet8")
        check(xpath="/sonic-device_metadata:sonic-device_metadata/DEVICE_METADATA/localhost/hwsku",
              path="/DEVICE_METADATA/localhost/hwsku",
              config=Files.CONFIG_DB_WITH_DEVICE_METADATA)
        check(xpath="/sonic-flex_counter:sonic-flex_counter/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK",
              path="/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK",
              config=Files.CONTRAINER_WITH_CONTAINER_CONFIG_DB)
        check(xpath="/sonic-flex_counter:sonic-flex_counter/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK/FLEX_COUNTER_STATUS",
              path="/FLEX_COUNTER_TABLE/BUFFER_POOL_WATERMARK/FLEX_COUNTER_STATUS",
              config=Files.CONTRAINER_WITH_CONTAINER_CONFIG_DB)
        check(xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_LIST[name='Ethernet8']",
              path="/INTERFACE/Ethernet8",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_IPPREFIX_LIST[name='Ethernet8'][ip-prefix='10.0.0.1/30']",
              path="/INTERFACE/Ethernet8|10.0.0.1~130",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(xpath="/sonic-interface:sonic-interface/INTERFACE/INTERFACE_IPPREFIX_LIST[name='Ethernet8'][ip-prefix='10.0.0.1/30']/scope",
              path="/INTERFACE/Ethernet8|10.0.0.1~130/scope",
              config=Files.CONFIG_DB_WITH_INTERFACE)
        check(xpath="/sonic-portchannel:sonic-portchannel/PORTCHANNEL_INTERFACE",
              path="/PORTCHANNEL_INTERFACE",
              config=Files.CONFIG_DB_WITH_PORTCHANNEL_INTERFACE)
        check(xpath="/sonic-portchannel:sonic-portchannel/PORTCHANNEL_INTERFACE/PORTCHANNEL_INTERFACE_IPPREFIX_LIST[name='PortChannel0001'][ip_prefix='1.1.1.1/24']",
              path="/PORTCHANNEL_INTERFACE/PortChannel0001|1.1.1.1~124",
              config=Files.CONFIG_DB_WITH_PORTCHANNEL_INTERFACE)
        check(xpath="/sonic-bgp-neighbor:sonic-bgp-neighbor/BGP_NEIGHBOR/BGP_NEIGHBOR_TEMPLATE_LIST[neighbor='1.2.3.4']/holdtime",
              path="/BGP_NEIGHBOR/1.2.3.4/holdtime",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(xpath="/sonic-bgp-neighbor:sonic-bgp-neighbor/BGP_NEIGHBOR/BGP_NEIGHBOR_LIST[vrf_name='default'][neighbor='1.2.3.4']/asn",
              path="/BGP_NEIGHBOR/default|1.2.3.4/asn",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(xpath="/sonic-bgp-monitor:sonic-bgp-monitor/BGP_MONITORS/BGP_MONITORS_LIST[addr='5.6.7.8']/name",
              path="/BGP_MONITORS/5.6.7.8/name",
              config=Files.CONFIG_DB_WITH_BGP_NEIGHBOR)
        check(xpath="/sonic-lldp:sonic-lldp/LLDP/GLOBAL/mode",
              path="/LLDP/GLOBAL/mode",
              config=Files.CONFIG_DB_WITH_LLDP)
        check(xpath="/sonic-buffer-port-egress-profile-list:sonic-buffer-port-egress-profile-list/BUFFER_PORT_EGRESS_PROFILE_LIST/BUFFER_PORT_EGRESS_PROFILE_LIST_LIST[port='Ethernet9']/profile_list",
              path="/BUFFER_PORT_EGRESS_PROFILE_LIST/Ethernet9/profile_list",
              config=Files.CONFIG_DB_WITH_PROFILE_LIST)
        check(xpath="/sonic-buffer-port-egress-profile-list:sonic-buffer-port-egress-profile-list/BUFFER_PORT_EGRESS_PROFILE_LIST/BUFFER_PORT_EGRESS_PROFILE_LIST_LIST[port='Ethernet9']/profile_list[.='egress_lossy_profile']",
              path="/BUFFER_PORT_EGRESS_PROFILE_LIST/Ethernet9/profile_list",
              config=Files.CONFIG_DB_WITH_PROFILE_LIST)
        check(xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']",
              path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']/DOT1P_TO_TC_MAP",
              path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']/DOT1P_TO_TC_MAP[dot1p='2']",
              path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1/2",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']/DOT1P_TO_TC_MAP[dot1p='2']/dot1p",
              path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1/2",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(xpath="/sonic-dot1p-tc-map:sonic-dot1p-tc-map/DOT1P_TO_TC_MAP/DOT1P_TO_TC_MAP_LIST[name='Dot1p_to_tc_map1']/DOT1P_TO_TC_MAP[dot1p='2']/tc",
              path="/DOT1P_TO_TC_MAP/Dot1p_to_tc_map1/2",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)
        check(xpath="/sonic-exp-fc-map:sonic-exp-fc-map/EXP_TO_FC_MAP/EXP_TO_FC_MAP_LIST[name='Exp_to_fc_map2']/EXP_TO_FC_MAP[exp='4']",
              path="/EXP_TO_FC_MAP/Exp_to_fc_map2/4",
              config=Files.CONFIG_DB_WITH_TYPE1_TABLES)

    def test_has_path(self):
        def check(config, path, expected):
            actual=self.path_addressing.has_path(config, path)
            self.assertEqual(expected, actual)

        check(config={},
              path="",
              expected=True)
        check(config={"TABLE":{}},
              path="",
              expected=True)
        check(config={},
              path="/TABLE",
              expected=False)
        check(config={"TABLE":{}},
              path="/ANOTHER_TABLE",
              expected=False)
        check(config={"TABLE":{}},
              path="/ANOTHER_TABLE",
              expected=False)
        check(config={"TABLE":{"key1":{"key11":{"key111":"value111"}}}},
              path="/TABLE/key1/key11/key111",
              expected=True)
        check(config={"TABLE":{"key1":{"key11":{"key111":"value111"}}}},
              path="/TABLE/key1",
              expected=True)
        check(config={"TABLE":{"key1":{"key11":{"key111":"value111"}}}},
              path="/TABLE/key1/key1",
              expected=False)
        check(config={"ANOTHER_TABLE": {}, "TABLE":{"key1":{"key11":{"key111":"value111"}}}},
              path="/TABLE/key1/key11",
              expected=True)
        check(config={"ANOTHER_TABLE": {}, "TABLE":{"key1":{"key11":{"key111":[1,2,3,4,5]}}}},
              path="/TABLE/key1/key11/key111/4",
              expected=True)
        check(config={"ANOTHER_TABLE": {}, "TABLE":{"key1":{"key11":{"key111":[1,2,3,4,5]}}}},
              path="/TABLE/key1/key11/key111/5",
              expected=False)
<<<<<<< HEAD
=======

    def test_configdb_sorted_keys_by_backlinks__counts_cached_per_schema_xpath(self):
        config = {"PORT": {"Ethernet0": {}, "Ethernet4": {}, "Ethernet8": {}}}
        expected = gu_common.PathAddressing(gu_common.ConfigWrapper()).configdb_sorted_keys_by_backlinks(
            "/PORT", config)
        sy = self.path_addressing._create_sonic_yang_with_loaded_models()

        with mock.patch.object(sy, "find_schema_dependencies", wraps=sy.find_schema_dependencies) as lookup:
            first = self.path_addressing.configdb_sorted_keys_by_backlinks("/PORT", config)
            second = self.path_addressing.configdb_sorted_keys_by_backlinks("/PORT", config)

        self.assertEqual(expected, first)
        self.assertEqual(expected, second)
        # Every PORT key maps to the same schema node, so libyang is asked once.
        self.assertEqual(1, lookup.call_count)

    def test_configdb_sorted_keys_by_backlinks__other_models__counts_recomputed(self):
        config = {"PORT": {"Ethernet0": {}}}
        self.path_addressing.configdb_sorted_keys_by_backlinks("/PORT", config)

        with mock.patch.object(self.sy_only_models, "find_schema_dependencies",
                               wraps=self.sy_only_models.find_schema_dependencies) as lookup:
            self.path_addressing.configdb_sorted_keys_by_backlinks("/PORT", config, sy=self.sy_only_models)

        self.assertEqual(1, lookup.call_count)


class TestRedactForLog(unittest.TestCase):
    OPS = [{"op": "add", "path": "/BGP_NEIGHBOR/default|10.0.0.1/auth_password", "value": "Md5-pw-1"},
           {"op": "add", "path": "/PORT/Ethernet0/mtu", "value": "9100"}]

    def setUp(self):
        gu_common._redaction_failure_logged = False

    @staticmethod
    def fake_redact(patch):
        ops = getattr(patch, "patch", patch)
        return [dict(op, value="<redacted>") if op["path"].endswith("auth_password") else op for op in ops]

    def redact_module(self, redact=None, missing=False):
        module = types.ModuleType("master_key_manager.master_key_encryption_config")
        module.REDACTED = "<redacted>"
        if not missing:
            module.redact_secrets = redact or self.fake_redact
        return mock.patch.dict("sys.modules", {
            "master_key_manager": types.ModuleType("master_key_manager"),
            "master_key_manager.master_key_encryption_config": module,
        })

    def test_json_patch_and_change_print_as_json(self):
        with self.redact_module():
            for patch_obj in (jsonpatch.JsonPatch(self.OPS), gu_common.JsonChange(jsonpatch.JsonPatch(self.OPS))):
                logged = gu_common.redact_for_log(patch_obj)
                self.assertNotIn("Md5-pw-1", logged)
                self.assertEqual(json.loads(logged)[1], self.OPS[1])
        # An unregistered-only patch logs exactly as it printed before.
        port_only = jsonpatch.JsonPatch(self.OPS[1:])
        with self.redact_module():
            self.assertEqual(gu_common.redact_for_log(port_only), str(port_only))

    def test_list_prints_as_list(self):
        with self.redact_module():
            logged = gu_common.redact_for_log(copy.deepcopy(self.OPS))
        self.assertIsInstance(logged, list)
        self.assertEqual(logged[0]["value"], "<redacted>")

    def test_patch_is_untouched(self):
        patch_obj = jsonpatch.JsonPatch(copy.deepcopy(self.OPS))
        with self.redact_module():
            gu_common.redact_for_log(patch_obj)
        self.assertEqual(patch_obj.patch, self.OPS)

    def test_without_the_encryption_library_the_patch_is_logged_as_is(self):
        patch_obj = jsonpatch.JsonPatch(self.OPS)
        with mock.patch.dict("sys.modules", {"master_key_manager": None}):
            self.assertIs(gu_common.redact_for_log(patch_obj), patch_obj)

    def test_library_without_redact_secrets_logs_nothing_of_the_patch_and_warns_once(self):
        logger = MagicMock()
        with self.redact_module(missing=True), \
                patch.object(gu_common.genericUpdaterLogging, "get_logger", return_value=logger):
            self.assertEqual(gu_common.redact_for_log(jsonpatch.JsonPatch(self.OPS)), gu_common.PATCH_NOT_LOGGED)
            self.assertEqual(gu_common.redact_for_log(jsonpatch.JsonPatch(self.OPS)), gu_common.PATCH_NOT_LOGGED)
        logger.log_warning.assert_called_once()

    def test_redaction_failure_logs_nothing_of_the_patch(self):
        def boom(patch):
            raise RuntimeError()
        with self.redact_module(boom):
            logged = gu_common.redact_for_log(jsonpatch.JsonPatch(self.OPS))
        self.assertEqual(logged, gu_common.PATCH_NOT_LOGGED)

    def test_error_text_without_redact_secrets_is_not_logged(self):
        error = ValueError("tested value Md5-pw-1 at /PORT/Ethernet0/mtu 9100 failed")
        with self.redact_module(missing=True):
            self.assertEqual(gu_common.redact_error_for_log(error, self.OPS), gu_common.ERROR_NOT_LOGGED)

    def test_error_text_is_masked(self):
        test_op = [{"op": "test", "path": "/BGP_NEIGHBOR/default|10.0.0.1/auth_password", "value": "secret"}]
        config = {"BGP_NEIGHBOR": {"default|10.0.0.1": {"auth_password": "other"}}}
        with self.assertRaises(jsonpatch.JsonPatchTestFailed) as raised:
            jsonpatch.JsonPatch(test_op).apply(config)
        self.assertIn("secret", str(raised.exception))
        with self.redact_module():
            text = gu_common.redact_error_for_log(raised.exception, test_op)
        self.assertNotIn("secret", text)
        self.assertIn("<redacted>", text)

    def test_error_text_masks_secrets_inside_an_entry_value(self):
        entry = {"asn": "65100", "auth_password": "secret"}
        ops = [{"op": "add", "path": "/BGP_NEIGHBOR/default|10.0.0.1", "value": entry}]
        error = ValueError("cannot add {'asn': '65100', 'auth_password': 'secret'}")
        with self.redact_module(lambda p: [dict(ops[0], value={"asn": "65100", "auth_password": "<redacted>"})]):
            text = gu_common.redact_error_for_log(error, jsonpatch.JsonPatch(ops))
        self.assertEqual(text, "cannot add {'asn': '65100', 'auth_password': '<redacted>'}")

    def test_error_text_without_the_encryption_library_is_unchanged(self):
        with mock.patch.dict("sys.modules", {"master_key_manager": None}):
            self.assertEqual(gu_common.redact_error_for_log(ValueError("secret"), self.OPS), "secret")

    def replace_setting_a_password(self, apply_error=None):
        """Run ConfigReplacer.replace -> PatchApplier.apply on a target that sets a BGP password,
        with only the config DB, change applier and patch sorter faked. Returns the logger mock and
        the error raised, if any."""
        from generic_config_updater import generic_updater as gu
        old = {"BGP_NEIGHBOR": {"default|10.0.0.1": {"asn": "65100"}}, "PORT": {"Ethernet0": {"mtu": "9000"}}}
        target = copy.deepcopy(old)
        target["BGP_NEIGHBOR"]["default|10.0.0.1"]["auth_password"] = "Md5-pw-1"
        target["PORT"]["Ethernet0"]["mtu"] = "9100"
        config_wrapper = MagicMock()
        config_wrapper.get_config_db_as_json.side_effect = [old, old, target, target]
        config_wrapper.get_empty_tables.return_value = []
        patch_wrapper = MagicMock()
        patch_wrapper.generate_patch.side_effect = jsonpatch.make_patch
        patch_wrapper.simulate_config_db_patch.side_effect = lambda p, c: p.apply(c)
        patch_wrapper.diff_json.return_value = []
        patchsorter = MagicMock()
        patchsorter.sort.side_effect = lambda p, trace_io=None: [gu_common.JsonChange(jsonpatch.JsonPatch([op])) for op in p]
        changeapplier = MagicMock()
        changeapplier.apply.side_effect = apply_error or (lambda config, change: change.patch.apply(config))
        logger = MagicMock()
        raised = None
        with self.redact_module(), patch.object(gu_common.genericUpdaterLogging, "get_logger", return_value=logger):
            applier = gu.PatchApplier(patchsorter=patchsorter, changeapplier=changeapplier,
                                      config_wrapper=config_wrapper, patch_wrapper=patch_wrapper)
            replacer = gu.ConfigReplacer(patch_applier=applier, config_wrapper=config_wrapper,
                                         patch_wrapper=patch_wrapper)
            try:
                replacer.replace(target)
            except Exception as e:
                raised = e
        return logger, raised

    def test_replace_logs_no_password_whatever_the_log_line(self):
        logger, raised = self.replace_setting_a_password()
        self.assertIsNone(raised)
        messages = [str(arg) for c in logger.mock_calls for arg in c.args]
        self.assertTrue(any("<redacted>" in m for m in messages), "the patch was never logged")
        self.assertEqual([m for m in messages if "Md5-pw-1" in m], [])

    def test_replace_error_text_is_masked(self):
        def fail(config, change):
            if "auth_password" not in change.patch.patch[0]["path"]:
                return change.patch.apply(config)
            raise jsonpatch.JsonPointerException("member 'x' not found in {}".format(change.patch.patch))
        _, raised = self.replace_setting_a_password(fail)
        self.assertIsInstance(raised, gu_common.GenericConfigUpdaterError)
        self.assertNotIn("Md5-pw-1", str(raised))
        self.assertIn("<redacted>", str(raised))
        self.assertIsNone(raised.__cause__)

    def test_replace_error_without_a_secret_is_raised_as_is(self):
        def fail(config, change):
            raise jsonpatch.JsonPointerException("member 'x' not found")
        _, raised = self.replace_setting_a_password(fail)
        self.assertIsInstance(raised, jsonpatch.JsonPointerException)

    def test_ops_without_values_keeps_the_schema_names_only(self):
        ops = [{"op": "replace", "path": "/PORT/Ethernet0/mtu", "value": "9000"},
               {"op": "add", "path": "/SNMP_COMMUNITY/Secret-community-1", "value": {"TYPE": "RW"}},
               {"op": "remove", "path": "/TACPLUS_SERVER"},
               {"op": "move", "from": "/ACL_RULE/R1|A/PRIORITY", "path": "/ACL_RULE/R1|B/PRIORITY"}]
        self.assertEqual(gu_common.ops_without_values(ops),
                         [{"op": "replace", "path": "/PORT/mtu"},
                          {"op": "add", "path": "/SNMP_COMMUNITY"},
                          {"op": "remove", "path": "/TACPLUS_SERVER"},
                          {"op": "move", "from": "/ACL_RULE/PRIORITY", "path": "/ACL_RULE/PRIORITY"}])

    def test_config_mismatch_logs_where_it_differs_and_nothing_an_operator_set(self):
        # A TACACS passkey is not registered with the master key, so redaction would leave it in
        # the clear, and an SNMP community is the row key rather than a value.
        from generic_config_updater import generic_updater as gu
        target = {"PORT": {"Ethernet0": {"mtu": "9100"}},
                  "SNMP_COMMUNITY": {"public": {"TYPE": "RO"}},
                  "TACPLUS_SERVER": {"1.2.3.4": {"passkey": "Old-pw-0"}}}
        actual = {"PORT": {"Ethernet0": {"mtu": "9000"}},
                  "SNMP_COMMUNITY": {"public": {"TYPE": "RO"}, "Secret-community-1": {"TYPE": "RW"}},
                  "TACPLUS_SERVER": {"1.2.3.4": {"passkey": "Tacacs-pw-1"}}}
        logger = MagicMock()
        with self.redact_module():
            diffs = gu.report_config_mismatch(
                gu_common.PatchWrapper(config_wrapper=MagicMock()), logger, "asic0", {"PORT"},
                target, actual)
        self.assertEqual([call[0] for call in logger.mock_calls], ["log_warning", "log_error"])
        warning, error = [str(call.args[0]) for call in logger.mock_calls]
        # On a multi-ASIC device the two lines interleave, so each must name its own scope.
        self.assertTrue(warning.startswith("asic0: ") and error.startswith("asic0: "),
                        (warning, error))
        # Table and field are schema names and survive; the row key and the value do not.
        for text in ("/PORT/mtu", "/SNMP_COMMUNITY", "/TACPLUS_SERVER/passkey"):
            self.assertIn(text, error)
        self.assertNotIn("/PORT", warning)  # the warning names the other writer's tables only
        for secret in ("Tacacs-pw-1", "Old-pw-0", "Secret-community-1", "Ethernet0", "1.2.3.4",
                       "9000", "value"):
            self.assertNotIn(secret, warning + error)
        # The caller still gets the operations whole; only the log drops what an operator set.
        self.assertEqual(sorted(op["path"] for op in diffs),
                         ["/PORT/Ethernet0/mtu", "/SNMP_COMMUNITY/Secret-community-1",
                          "/TACPLUS_SERVER/1.2.3.4/passkey"])
        self.assertTrue(any(op.get("value") == "9000" for op in diffs))

    @staticmethod
    def raw_interpolations(source, name="<source>"):
        """Every (line, call, name) in *source* where a log call or an error f-string
        interpolates one of the bare names below. Read as syntax, not as lines: a call and the
        name it interpolates need not share one."""
        raw = {"patch", "change", "changes", "patch_ops", "yang_patch", "diffs", "foreign",
               "unconverged"}
        found = set()
        for node in ast.walk(ast.parse(source, name)):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if not (re.match(r"log_\w+$", called) or called.endswith("Error")):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.FormattedValue) and isinstance(inner.value, ast.Name) \
                        and inner.value.id in raw:
                    found.add((inner.lineno, called, inner.value.id))
        return sorted(found)

    def test_gcu_log_lines_never_interpolate_a_raw_patch(self):
        # Anything a log call prints must go through redact_for_log or ops_without_values, or the
        # values reach syslog in clear.
        root = os.path.dirname(gu_common.__file__)
        offenders = []
        for name in ("generic_updater.py", "gu_common.py", "main.py", "patch_sorter.py"):
            with open(os.path.join(root, name)) as fh:
                offenders += ["{}:{}: {}({{{}}})".format(name, line, call, raw)
                              for line, call, raw in self.raw_interpolations(fh.read(), name)]
        self.assertEqual(offenders, [])

    def test_the_raw_patch_guard_sees_a_call_wrapped_over_several_lines(self):
        # A wrapped call holds the name on none of the lines that carry the call itself.
        source = ("logger.log_error(f'at: {diffs}')\n"
                  "logger.log_warning(\n"
                  "    'drift, '\n"
                  "    f'another writer was active: {foreign}')\n"
                  "raise GenericConfigUpdaterError(f'{patch}')\n"
                  "logger.log_error(f'at: {ops_without_values(diffs)}')\n")
        self.assertEqual([(call, raw) for _, call, raw in self.raw_interpolations(source)],
                         [("log_error", "diffs"), ("log_warning", "foreign"),
                          ("GenericConfigUpdaterError", "patch")])
>>>>>>> 22e97f8d (NOS-15510: [gcu] take ports admin down in one step and create a new table in one step (#1365))
