import json
import os
import shutil
import unittest

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, call, patch
from .gutest_helpers import create_side_effect_dict, create_side_effect_skipfirstarg_dict, Files

import generic_config_updater.generic_updater as gu
import generic_config_updater.patch_sorter as ps
import generic_config_updater.change_applier as ca

# import sys
# sys.path.insert(0,'../../generic_config_updater')
# import generic_updater as gu

class TestPatchApplier(unittest.TestCase):
    def test_apply__invalid_patch_producing_empty_tables__failure(self):
        # Arrange
        patch_applier = self.__create_patch_applier(valid_patch_does_not_produce_empty_tables=False)

        # Act and assert
        self.assertRaises(ValueError, patch_applier.apply, Files.MULTI_OPERATION_CONFIG_DB_PATCH)

    def test_apply__json_not_fully_updated__failure(self):
        # Arrange
        patch_applier = self.__create_patch_applier(verified_same_config=False)

        # Act and assert
        self.assertRaises(gu.GenericConfigUpdaterError, patch_applier.apply, Files.MULTI_OPERATION_CONFIG_DB_PATCH)

    def test_apply__no_errors__update_successful(self):
        # Arrange
        changes = [Mock(), Mock()]
        patch_applier = self.__create_patch_applier(changes)

        # Act
        patch_applier.apply(Files.MULTI_OPERATION_CONFIG_DB_PATCH)

        # Assert
        patch_applier.config_wrapper.get_config_db_as_json.assert_has_calls([call(), call()])
        patch_applier.patch_wrapper.simulate_config_db_patch.assert_has_calls(
            [call(Files.MULTI_OPERATION_CONFIG_DB_PATCH, Files.CONFIG_DB_AS_JSON)])
        patch_applier.patchsorter.sort.assert_has_calls([call(Files.MULTI_OPERATION_CONFIG_DB_PATCH, trace_io=None)])
        patch_applier.changeapplier.apply.assert_called()
<<<<<<< HEAD
        patch_applier.patch_wrapper.verify_same_json.assert_has_calls(
            [call(Files.CONFIG_DB_AFTER_MULTI_PATCH, Files.CONFIG_DB_AFTER_MULTI_PATCH)])
=======
        patch_applier.patch_wrapper.diff_json.assert_has_calls(
            [call(Files.CONFIG_DB_AFTER_MULTI_PATCH, Files.CONFIG_DB_AFTER_MULTI_PATCH,
                  field_custom_validations=None)])

    def test_apply__restarts_services_once_after_all_changes(self):
        # Arrange
        changes = [Mock(), Mock()]
        patch_applier = self.__create_patch_applier(changes)
        calls = Mock()
        calls.attach_mock(patch_applier.changeapplier, "changeapplier")
        calls.attach_mock(patch_applier.config_wrapper.get_config_db_as_json, "get_config")

        # Act
        patch_applier.apply(Files.MULTI_OPERATION_CONFIG_DB_PATCH)

        # Assert
        order = [name for name, _, _ in calls.mock_calls
                 if name in ("get_config", "changeapplier.apply", "changeapplier.restart_services")]
        self.assertEqual(order, ["get_config", "changeapplier.apply", "changeapplier.apply",
                                 "changeapplier.restart_services", "get_config"])
        patch_applier.changeapplier.restart_services.assert_called_once_with()

    # A 1.00 Gb/s port shaper with two queues asking 800 Mb/s each.
    OVERSUBSCRIBED_CONFIG = {
        "SCHEDULER": {
            "port.shaper": {"meter_type": "bytes", "pir": "125000000"},
            "q.shaper": {"meter_type": "bytes", "pir": "100000000"},
        },
        "QUEUE": {
            "Ethernet0|1": {"scheduler": "q.shaper"},
            "Ethernet0|2": {"scheduler": "q.shaper"},
        },
        "PORT_QOS_MAP": {"Ethernet0": {"scheduler": "port.shaper"}},
    }

    WITHIN_BUDGET_CONFIG = {
        "SCHEDULER": {
            "port.shaper": {"meter_type": "bytes", "pir": "125000000"},
            "q.shaper": {"meter_type": "bytes", "pir": "50000000"},
        },
        "QUEUE": {
            "Ethernet0|1": {"scheduler": "q.shaper"},
            "Ethernet0|2": {"scheduler": "q.shaper"},
        },
        "PORT_QOS_MAP": {"Ethernet0": {"scheduler": "port.shaper"}},
    }

    def test_apply__patch_oversubscribes_a_port__warns_once_with_scope(self):
        # Arrange
        patch_applier, patch = self.__create_qos_patch_applier(
            self.WITHIN_BUDGET_CONFIG, self.OVERSUBSCRIBED_CONFIG)

        # Act
        patch_applier.apply(patch)

        # Assert
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        qos_warnings = [w for w in warnings if "per-queue shapers exceed the port shaper" in w]
        self.assertEqual(len(qos_warnings), 1, warnings)
        self.assertTrue(qos_warnings[0].startswith("localhost: "), qos_warnings[0])
        self.assertIn("Ethernet0: 1.60 Gb/s across 2 shaped queues", qos_warnings[0])

    def test_apply__oversubscription_already_present__stays_silent(self):
        # An operator who configured this on purpose must not be warned again
        # by every later patch that leaves QoS alone.
        # Arrange
        patch_applier, patch = self.__create_qos_patch_applier(
            self.OVERSUBSCRIBED_CONFIG, self.OVERSUBSCRIBED_CONFIG)

        # Act
        patch_applier.apply(patch)

        # Assert
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "per-queue shapers" in w], [], warnings)

    def test_apply__rejected_patch__is_not_advised_about(self):
        # The advisory runs after field-operation validation, so a patch it
        # rejects leaves no advisory about a configuration that never lands.
        # Arrange
        patch_applier, patch = self.__create_qos_patch_applier(
            self.WITHIN_BUDGET_CONFIG, self.OVERSUBSCRIBED_CONFIG)
        patch_applier.config_wrapper.validate_field_operation.side_effect = ValueError("rejected")

        # Act and assert
        self.assertRaises(ValueError, patch_applier.apply, patch)
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "per-queue shapers" in w], [], warnings)

    def test_apply__patch_rejected_by_yang__is_not_advised_about(self):
        # Arrange
        patch_applier, patch = self.__create_qos_patch_applier(
            self.WITHIN_BUDGET_CONFIG, self.OVERSUBSCRIBED_CONFIG)
        patch_applier.patchsorter.sort.side_effect = ValueError("Given patch will produce invalid config")

        # Act and assert
        self.assertRaises(ValueError, patch_applier.apply, patch)
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "per-queue shapers" in w], [], warnings)
        patch_applier.changeapplier.apply.assert_not_called()

    def test_apply__patch_producing_empty_tables__is_not_advised_about(self):
        # Arrange
        patch_applier, patch = self.__create_qos_patch_applier(
            self.WITHIN_BUDGET_CONFIG, self.OVERSUBSCRIBED_CONFIG)
        patch_applier.config_wrapper.get_empty_tables.return_value = ["AnyTable"]

        # Act and assert
        self.assertRaises(gu.EmptyTableError, patch_applier.apply, patch)
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "per-queue shapers" in w], [], warnings)

    def test_apply__advisory_raises__patch_is_not_failed(self):
        # A QUEUE scheduler that is not a plain string makes the check raise;
        # the patch must still be applied.
        # Arrange
        broken = dict(self.OVERSUBSCRIBED_CONFIG)
        broken["QUEUE"] = {"Ethernet0|1": {"scheduler": ["q.shaper"]}}
        patch_applier, patch = self.__create_qos_patch_applier(
            self.WITHIN_BUDGET_CONFIG, broken)

        # Act
        patch_applier.apply(patch)

        # Assert
        patch_applier.logger.log_debug.assert_called()
        debugs = [args[0] for args, _ in patch_applier.logger.log_debug.call_args_list]
        self.assertTrue(any("QoS oversubscription check skipped" in d for d in debugs), debugs)

    def test_apply__drift_in_a_table_the_patch_does_not_write__names_the_other_writer(self):
        # Arrange
        patch_applier = self.__create_patch_applier(diffs=[CONCURRENT_WRITE_OP])
        patch_applier.logger = Mock()

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError) as context:
            patch_applier.apply(Files.MULTI_OPERATION_CONFIG_DB_PATCH)
        self.assertIn("in table(s): DEVICE_METADATA", str(context.exception))
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertTrue(any("another writer was active" in w for w in warnings), warnings)
        self.assertTrue(any("DEVICE_METADATA" in w for w in warnings), warnings)

    def test_apply__unconverged_patched_table__error_names_the_table(self):
        # Arrange
        patch_applier = self.__create_patch_applier(diffs=[UNCONVERGED_PORT_OP])

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError) as context:
            patch_applier.apply(Files.MULTI_OPERATION_CONFIG_DB_PATCH)
        self.assertIn("in table(s): PORT", str(context.exception))

    def test_apply__drift_alongside_an_unconverged_table__error_names_both_tables(self):
        # Arrange
        patch_applier = self.__create_patch_applier(diffs=[CONCURRENT_WRITE_OP, UNCONVERGED_PORT_OP])

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError) as context:
            patch_applier.apply(Files.MULTI_OPERATION_CONFIG_DB_PATCH)
        self.assertIn("in table(s): DEVICE_METADATA, PORT", str(context.exception))

    def test_apply__concurrent_write_to_another_table__reports_the_other_writer(self):
        # The reported failure: the patch's own table converges, but another writer
        # changes an unrelated table between the two reads of ConfigDB.
        # Arrange
        json_patch = jsonpatch.JsonPatch(
            [{"op": "add", "path": "/VLAN_MEMBER",
              "value": {"Vlan100|Ethernet8": {"tagging_mode": "untagged"}}}])
        old_config = {"PORT": {"Ethernet8": {"admin_status": "up"}}}
        new_config = {
            "VLAN_MEMBER": {"Vlan100|Ethernet8": {"tagging_mode": "untagged"}},
            "PORT": {"Ethernet8": {"admin_status": "down"}},
        }
        patch_applier = self.__create_patch_applier_with_real_patch_wrapper(old_config, new_config)

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError):
            patch_applier.apply(json_patch)
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertTrue(any("another writer was active" in w for w in warnings), warnings)
        self.assertTrue(any("PORT" in w for w in warnings), warnings)

    def test_apply__patched_table_did_not_converge__failure(self):
        # Every difference is in the patch's own table, so no other writer may be named.
        # Arrange
        json_patch = jsonpatch.JsonPatch(
            [{"op": "add", "path": "/VLAN_MEMBER",
              "value": {"Vlan100|Ethernet8": {"tagging_mode": "untagged"}}}])
        old_config = {"PORT": {"Ethernet8": {"admin_status": "up"}}}
        new_config = {"PORT": {"Ethernet8": {"admin_status": "up"}}}
        patch_applier = self.__create_patch_applier_with_real_patch_wrapper(old_config, new_config)

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError) as context:
            patch_applier.apply(json_patch)
        self.assertIn("in table(s): VLAN_MEMBER", str(context.exception))
        # Matched on the text rather than on log_warning itself, which apply also uses for the
        # QoS advisory.
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "another writer" in w], [], warnings)
        errors = [args[0] for args, _ in patch_applier.logger.log_error.call_args_list]
        self.assertTrue(any("ConfigDB did not reach the target config at" in e for e in errors), errors)
        self.assertTrue(any("/VLAN_MEMBER" in e for e in errors), errors)

    def test_apply__whole_config_patch_did_not_converge__names_no_other_writer(self):
        # A path-"" operation leaves the patched tables unknowable, so every difference goes
        # unattributed rather than being read as another writer.
        # Arrange
        json_patch = jsonpatch.JsonPatch(
            [{"op": "replace", "path": "",
              "value": {"PORT": {"Ethernet8": {"admin_status": "down"}}}}])
        old_config = {"PORT": {"Ethernet8": {"admin_status": "up"}}}
        new_config = {"PORT": {"Ethernet8": {"admin_status": "up"}}}
        patch_applier = self.__create_patch_applier_with_real_patch_wrapper(old_config, new_config)

        # Act and assert
        with self.assertRaises(gu.GenericConfigUpdaterError) as context:
            patch_applier.apply(json_patch)
        self.assertIn("in table(s): PORT", str(context.exception))
        warnings = [args[0] for args, _ in patch_applier.logger.log_warning.call_args_list]
        self.assertEqual([w for w in warnings if "another writer" in w], [], warnings)

    def __create_patch_applier_with_real_patch_wrapper(self, old_config, new_config):
        # The real PatchWrapper runs the comparison under test instead of mocking it away.
        config_wrapper = Mock()
        config_wrapper.get_config_db_as_json.side_effect = [old_config, new_config]
        config_wrapper.get_empty_tables.return_value = []
        config_wrapper.remove_null_values.return_value = []

        changeapplier = Mock()
        changeapplier.apply.return_value = None
        changeapplier.remove_backend_tables_from_config.return_value = None

        patchsorter = Mock()
        patchsorter.sort.return_value = [Mock()]

        patch_applier = gu.PatchApplier(
            patchsorter, changeapplier, config_wrapper,
            gu_common.PatchWrapper(config_wrapper=config_wrapper))
        patch_applier.logger = Mock()
        return patch_applier

    def __create_qos_patch_applier(self, old_config, target_config):
        patch = jsonpatch.make_patch(old_config, target_config)

        config_wrapper = Mock()
        config_wrapper.get_config_db_as_json.side_effect = [old_config, target_config]
        config_wrapper.get_empty_tables.return_value = []
        config_wrapper.remove_null_values.return_value = []

        patch_wrapper = Mock()
        patch_wrapper.simulate_config_db_patch.return_value = target_config
        patch_wrapper.diff_json.return_value = []

        patchsorter = Mock()
        patchsorter.sort.return_value = [Mock()]

        changeapplier = Mock()

        patch_applier = gu.PatchApplier(patchsorter, changeapplier, config_wrapper, patch_wrapper)
        patch_applier.logger = Mock()
        return patch_applier, patch
>>>>>>> c2e8d2c2 (NOS-22993: [gcu] Restart services that read config only at startup, once per patch (#1382))

    def __create_patch_applier(self,
                               changes=None,
                               valid_patch_does_not_produce_empty_tables=True,
                               verified_same_config=True):
        config_wrapper = Mock()
        config_wrapper.get_config_db_as_json.side_effect = \
            [Files.CONFIG_DB_AS_JSON, Files.CONFIG_DB_AFTER_MULTI_PATCH]
        empty_tables = [] if valid_patch_does_not_produce_empty_tables else ["AnyTable"]
        config_wrapper.get_empty_tables.side_effect = \
            create_side_effect_dict({(str(Files.CONFIG_DB_AFTER_MULTI_PATCH),): empty_tables})

        patch_wrapper = Mock()
        patch_wrapper.simulate_config_db_patch.side_effect = \
            create_side_effect_dict(
                {(str(Files.MULTI_OPERATION_CONFIG_DB_PATCH), str(Files.CONFIG_DB_AS_JSON)):
                    Files.CONFIG_DB_AFTER_MULTI_PATCH})
        patch_wrapper.verify_same_json.side_effect = \
            create_side_effect_dict(
                {(str(Files.CONFIG_DB_AFTER_MULTI_PATCH), str(Files.CONFIG_DB_AFTER_MULTI_PATCH)):
                    verified_same_config})

        changes = [Mock(), Mock()] if not changes else changes
        patchsorter = Mock()
        patchsorter.sort.side_effect = \
            create_side_effect_dict({(str(Files.MULTI_OPERATION_CONFIG_DB_PATCH),): changes})

        changeapplier = Mock()
        changeapplier.apply.side_effect = create_side_effect_skipfirstarg_dict({
                (str(changes[0]),): Files.CONFIG_DB_AFTER_MULTI_PATCH,
                (str(changes[1]),): Files.CONFIG_DB_AFTER_MULTI_PATCH})

        return gu.PatchApplier(patchsorter, changeapplier, config_wrapper, patch_wrapper)

class TestConfigReplacer(unittest.TestCase):
    def test_replace__json_not_fully_updated__failure(self):
        # Arrange
        config_replacer = self.__create_config_replacer(verified_same_config=False)

        # Act and assert
        self.assertRaises(gu.GenericConfigUpdaterError, config_replacer.replace, Files.CONFIG_DB_AFTER_MULTI_PATCH)

    def test_replace__no_errors__update_successful(self):
        # Arrange
        config_replacer = self.__create_config_replacer()

        # Act
        config_replacer.replace(Files.CONFIG_DB_AFTER_MULTI_PATCH)

        # Assert
        config_replacer.config_wrapper.get_config_db_as_json.assert_has_calls([call(), call()])
        config_replacer.patch_wrapper.generate_patch.assert_has_calls(
            [call(Files.CONFIG_DB_AS_JSON, Files.CONFIG_DB_AFTER_MULTI_PATCH)])
        config_replacer.patch_applier.apply.assert_has_calls(
            [call(Files.MULTI_OPERATION_CONFIG_DB_PATCH, trace_io=None)]
        )
        config_replacer.patch_wrapper.verify_same_json.assert_has_calls(
            [call(Files.CONFIG_DB_AFTER_MULTI_PATCH, Files.CONFIG_DB_AFTER_MULTI_PATCH)])

    def __create_config_replacer(self, changes=None, verified_same_config=True):
        config_wrapper = Mock()
        config_wrapper.get_config_db_as_json.side_effect = \
            [Files.CONFIG_DB_AS_JSON, Files.CONFIG_DB_AFTER_MULTI_PATCH]

        patch_wrapper = Mock()
        patch_wrapper.generate_patch.side_effect = \
            create_side_effect_dict(
                {(str(Files.CONFIG_DB_AS_JSON), str(Files.CONFIG_DB_AFTER_MULTI_PATCH)):
                    Files.MULTI_OPERATION_CONFIG_DB_PATCH})
        patch_wrapper.verify_same_json.side_effect = \
            create_side_effect_dict(
                {(str(Files.CONFIG_DB_AFTER_MULTI_PATCH), str(Files.CONFIG_DB_AFTER_MULTI_PATCH)): \
                    verified_same_config})

        changes = [Mock(), Mock()] if not changes else changes
        patchsorter = Mock()
        patchsorter.sort.side_effect = create_side_effect_dict({(str(Files.MULTI_OPERATION_CONFIG_DB_PATCH),): \
            changes})

        patch_applier = Mock()
        patch_applier.apply.side_effect = create_side_effect_dict({(str(Files.MULTI_OPERATION_CONFIG_DB_PATCH),): 0})

        return gu.ConfigReplacer(patch_applier, config_wrapper, patch_wrapper)


@patch('generic_config_updater.generic_updater.get_config_json', MagicMock(return_value={}))
class TestFileSystemConfigRollbacker(unittest.TestCase):
    def setUp(self):
        self.checkpoints_dir = os.path.join(os.getcwd(),"checkpoints")
        self.checkpoint_ext = ".cp.json"
        self.any_checkpoint_name = "anycheckpoint"
        self.any_other_checkpoint_name = "anyothercheckpoint"
        self.any_config = {}
        self.clean_up()

    def tearDown(self):
        self.clean_up()

    def test_rollback__checkpoint_does_not_exist__failure(self):
        # Arrange
        rollbacker = self.create_rollbacker()

        # Act and assert
        self.assertRaises(ValueError, rollbacker.rollback, "NonExistingCheckpoint")

    def test_rollback__no_errors__success(self):
        # Arrange
        self.create_checkpoints_dir()
        self.add_checkpoint(self.any_checkpoint_name, self.any_config)
        rollbacker = self.create_rollbacker()

        # Act
        rollbacker.rollback(self.any_checkpoint_name)

        # Assert
        rollbacker.config_replacer.replace.assert_has_calls([call(self.any_config)])

    def test_checkpoint__checkpoints_dir_does_not_exist__checkpoint_created(self):
        # Arrange
        rollbacker = self.create_rollbacker()
        self.assertFalse(os.path.isdir(self.checkpoints_dir))

        # Act
        rollbacker.checkpoint(self.any_checkpoint_name)

        # Assert
        self.assertTrue(os.path.isdir(self.checkpoints_dir))
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_checkpoint_name))

    def test_checkpoint__checkpoints_dir_exists__checkpoint_created(self):
        # Arrange
        self.create_checkpoints_dir()
        rollbacker = self.create_rollbacker()

        # Act
        rollbacker.checkpoint(self.any_checkpoint_name)

        # Assert
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_checkpoint_name))

    def test_list_checkpoints__checkpoints_dir_does_not_exist__empty_list(self):
        # Arrange
        rollbacker = self.create_rollbacker()
        self.assertFalse(os.path.isdir(self.checkpoints_dir))
        expected = []

        # Act
        actual = rollbacker.list_checkpoints()

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__checkpoints_dir_exist_but_no_files__empty_list(self):
        # Arrange
        self.create_checkpoints_dir()
        rollbacker = self.create_rollbacker()
        expected = []

        # Act
        actual = rollbacker.list_checkpoints()

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__checkpoints_dir_has_multiple_files(self):
        # Arrange
        self.create_checkpoints_dir()
        self.add_checkpoint(self.any_checkpoint_name, self.any_config)
        self.add_checkpoint(self.any_other_checkpoint_name, self.any_config)
        rollbacker = self.create_rollbacker()
        expected = [self.any_checkpoint_name, self.any_other_checkpoint_name]

        # Act
        actual = rollbacker.list_checkpoints()

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__checkpoints_dir_has_multiple_files_with_time(self):
        # Arrange
        self.create_checkpoints_dir()
        mod_time1 = self.add_checkpoint(self.any_checkpoint_name, self.any_config)
        mod_time2 = self.add_checkpoint(self.any_other_checkpoint_name, self.any_config)
        rollbacker = self.create_rollbacker()
        expected = [
            {"name": self.any_checkpoint_name, "time": mod_time1},
            {"name": self.any_other_checkpoint_name, "time": mod_time2}
        ]

        # Act
        actual = rollbacker.list_checkpoints(includes_time=True)

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__checkpoints_names_have_special_characters_multiple_files(self):
        # Arrange
        self.create_checkpoints_dir()
        self.add_checkpoint("check.point1", self.any_config)
        self.add_checkpoint(".checkpoint2", self.any_config)
        self.add_checkpoint("checkpoint3.", self.any_config)
        rollbacker = self.create_rollbacker()
        expected = ["check.point1", ".checkpoint2", "checkpoint3."]

        # Act
        actual = rollbacker.list_checkpoints()

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__checkpoints_names_have_special_characters_multiple_files_with_time(self):
        # Arrange
        self.create_checkpoints_dir()
        mod_time1 = self.add_checkpoint("check.point1", self.any_config)
        mod_time2 = self.add_checkpoint(".checkpoint2", self.any_config)
        mod_time3 = self.add_checkpoint("checkpoint3.", self.any_config)
        rollbacker = self.create_rollbacker()
        expected = [
            {"name": "check.point1", "time": mod_time1},
            {"name": ".checkpoint2", "time": mod_time2},
            {"name": "checkpoint3.", "time": mod_time3}
        ]

        # Act
        actual = rollbacker.list_checkpoints(includes_time=True)

        # Assert
        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual(expected, actual)

    def test_delete_checkpoint__checkpoint_does_not_exist__failure(self):
        # Arrange
        rollbacker = self.create_rollbacker()

        # Act and assert
        self.assertRaises(ValueError, rollbacker.delete_checkpoint, self.any_checkpoint_name)

    def test_delete_checkpoint__checkpoint_exist__success(self):
        # Arrange
        self.create_checkpoints_dir()
        self.add_checkpoint(self.any_checkpoint_name, self.any_config)
        rollbacker = self.create_rollbacker()

        # Act
        rollbacker.delete_checkpoint(self.any_checkpoint_name)

        # Assert
        self.assertFalse(self.check_checkpoint_exists(self.any_checkpoint_name))

    def test_multiple_operations(self):
        rollbacker = self.create_rollbacker()

        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual([], rollbacker.list_checkpoints())

        rollbacker.checkpoint(self.any_checkpoint_name)
        self.assertCountEqual([self.any_checkpoint_name], rollbacker.list_checkpoints())
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_checkpoint_name))

        rollbacker.rollback(self.any_checkpoint_name)
        rollbacker.config_replacer.replace.assert_has_calls([call(self.any_config)])

        rollbacker.checkpoint(self.any_other_checkpoint_name)
        self.assertCountEqual([self.any_checkpoint_name, self.any_other_checkpoint_name], rollbacker.list_checkpoints())
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_other_checkpoint_name))

        rollbacker.delete_checkpoint(self.any_checkpoint_name)
        self.assertCountEqual([self.any_other_checkpoint_name], rollbacker.list_checkpoints())

        rollbacker.delete_checkpoint(self.any_other_checkpoint_name)
        self.assertCountEqual([], rollbacker.list_checkpoints())

    def test_multiple_operations_with_time(self):
        rollbacker = self.create_rollbacker()

        # 'assertCountEqual' does check same count, same elements ignoring order
        self.assertCountEqual([], rollbacker.list_checkpoints(includes_time=True))

        rollbacker.checkpoint(self.any_checkpoint_name)
        self.assertCountEqual(
            [self.any_checkpoint_name],
            self.extract_checkpoint_names(rollbacker.list_checkpoints(includes_time=True))
        )
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_checkpoint_name))

        rollbacker.rollback(self.any_checkpoint_name)
        rollbacker.config_replacer.replace.assert_has_calls([call(self.any_config)])

        rollbacker.checkpoint(self.any_other_checkpoint_name)
        self.assertCountEqual(
            [self.any_checkpoint_name, self.any_other_checkpoint_name],
            self.extract_checkpoint_names(rollbacker.list_checkpoints(includes_time=True))
        )
        self.assertEqual(self.any_config, self.get_checkpoint(self.any_other_checkpoint_name))

        rollbacker.delete_checkpoint(self.any_checkpoint_name)
        self.assertCountEqual(
            [self.any_other_checkpoint_name],
            self.extract_checkpoint_names(rollbacker.list_checkpoints(includes_time=True))
        )

        rollbacker.delete_checkpoint(self.any_other_checkpoint_name)
        self.assertCountEqual([], rollbacker.list_checkpoints(includes_time=True))

    def extract_checkpoint_names(self, checkpoint_list):
        """Extract checkpoint names from the list of dictionaries."""
        return [checkpoint["name"] for checkpoint in checkpoint_list]

    def clean_up(self):
        if os.path.isdir(self.checkpoints_dir):
            shutil.rmtree(self.checkpoints_dir)

    def create_checkpoints_dir(self):
        os.makedirs(self.checkpoints_dir)

    def add_checkpoint(self, name, json_content, mod_time=None):
        path=os.path.join(self.checkpoints_dir, f"{name}{self.checkpoint_ext}")
        with open(path, "w") as fh:
            fh.write(json.dumps(json_content))

        if mod_time is None:
            mod_time = datetime.now(timezone.utc).timestamp()
        os.utime(path, (mod_time, mod_time))

        return datetime.fromtimestamp(mod_time, tz=timezone.utc).isoformat()

    def get_checkpoint(self, name):
        path=os.path.join(self.checkpoints_dir, f"{name}{self.checkpoint_ext}")
        with open(path) as fh:
            text = fh.read()
            return json.loads(text)

    def check_checkpoint_exists(self, name):
        path=os.path.join(self.checkpoints_dir, f"{name}{self.checkpoint_ext}")
        return os.path.isfile(path)

    def create_rollbacker(self):
        replacer = Mock()
        replacer.replace.side_effect = create_side_effect_dict({(str(self.any_config),): 0})

        config_wrapper = Mock()
        config_wrapper.get_config_db_as_json.return_value = self.any_config

        return gu.FileSystemConfigRollbacker(checkpoints_dir=self.checkpoints_dir,
                                             config_replacer=replacer,
                                             config_wrapper=config_wrapper)

class TestGenericUpdateFactory(unittest.TestCase):
    def setUp(self):
        self.any_verbose=True
        self.any_dry_run=True
        self.any_ignore_non_yang_tables=True
        self.any_ignore_paths=[""]

    def test_create_patch_applier__invalid_config_format__failure(self):
        # Arrange
        factory = gu.GenericUpdateFactory()

        # Act and assert
        self.assertRaises(ValueError,
                          factory.create_patch_applier,
                          "INVALID_FORMAT",
                          self.any_verbose,
                          self.any_dry_run,
                          self.any_ignore_non_yang_tables,
                          self.any_ignore_paths)

    def test_create_patch_applier__different_options(self):
        # Arrange
        options = [
            {"verbose": {True: None, False: None}},
            {"dry_run": {True: None, False: gu.ConfigLockDecorator}},
            {
                "config_format": {
                    gu.ConfigFormat.SONICYANG: gu.SonicYangDecorator,
                    gu.ConfigFormat.CONFIGDB: None,
                }
            },
            {"ignore_non_yang_tables": {True: None, False: None}},
            {"ignore_paths": {(): None, ("", "/ACL_TABLE"): None}},
        ]

        # Act and assert
        self.recursively_test_create_func(options, 0, {}, [], self.validate_create_patch_applier)

    def test_create_config_replacer__invalid_config_format__failure(self):
        # Arrange
        factory = gu.GenericUpdateFactory()

        # Act and assert
        self.assertRaises(ValueError,
                          factory.create_config_replacer,
                          "INVALID_FORMAT",
                          self.any_verbose,
                          self.any_dry_run,
                          self.any_ignore_non_yang_tables,
                          self.any_ignore_paths)

    def test_create_config_replacer__different_options(self):
        # Arrange
        options = [
            {"verbose": {True: None, False: None}},
            {"dry_run": {True: None, False: gu.ConfigLockDecorator}},
            {
                "config_format": {
                    gu.ConfigFormat.SONICYANG: gu.SonicYangDecorator,
                    gu.ConfigFormat.CONFIGDB: None,
                }
            },
            {"ignore_non_yang_tables": {True: None, False: None}},
            {"ignore_paths": {(): None, ("", "/ACL_TABLE"): None}},
        ]

        # Act and assert
        self.recursively_test_create_func(options, 0, {}, [], self.validate_create_config_replacer)

    def test_create_config_rollbacker__different_options(self):
        # Arrange
        options = [
            {"verbose": {True: None, False: None}},
            {"dry_run": {True: None, False: gu.ConfigLockDecorator}},
            {"ignore_non_yang_tables": {True: None, False: None}},
            {"ignore_paths": {(): None, ("", "/ACL_TABLE"): None}},
        ]

        # Act and assert
        self.recursively_test_create_func(options, 0, {}, [], self.validate_create_config_rollbacker)

    def recursively_test_create_func(self, options, cur_option, params, expected_decorators, create_func):
        if cur_option == len(options):
            create_func(params, expected_decorators)
            return

        param = list(options[cur_option].keys())[0]
        for key in options[cur_option][param]:
            params[param] = key
            decorator = options[cur_option][param][key]
            if decorator != None:
                expected_decorators.append(decorator)
            self.recursively_test_create_func(options, cur_option+1, params, expected_decorators, create_func)
            if decorator != None:
                expected_decorators.pop()

    def validate_create_patch_applier(self, params, expected_decorators):
        factory = gu.GenericUpdateFactory()
        patch_applier = factory.create_patch_applier(params["config_format"],
                                                     params["verbose"],
                                                     params["dry_run"],
                                                     params["ignore_non_yang_tables"],
                                                     params["ignore_paths"])
        for decorator_type in expected_decorators:
            self.assertIsInstance(patch_applier, decorator_type)

            patch_applier = patch_applier.decorated_patch_applier

        self.assertIsInstance(patch_applier, gu.PatchApplier)
        if params["dry_run"]:
            self.assertIsInstance(patch_applier.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(patch_applier.changeapplier, ca.DryRunChangeApplier)
            self.assertIsInstance(patch_applier.changeapplier.config_wrapper, gu.DryRunConfigWrapper)
        else:
            self.assertIsInstance(patch_applier.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(patch_applier.changeapplier, ca.ChangeApplier)

        if params["ignore_non_yang_tables"] or params["ignore_paths"]:
            self.assertIsInstance(patch_applier.patchsorter, ps.NonStrictPatchSorter)
            expected_config_splitters = []
            if params["ignore_non_yang_tables"]:
                expected_config_splitters.append(ps.TablesWithoutYangConfigSplitter.__name__)
            if params["ignore_paths"]:
                expected_config_splitters.append(ps.IgnorePathsFromYangConfigSplitter.__name__)
            actual_config_splitters = [type(splitter).__name__ for splitter in patch_applier.patchsorter.config_splitter.inner_config_splitters]
            self.assertCountEqual(expected_config_splitters, actual_config_splitters)
        else:
            self.assertIsInstance(patch_applier.patchsorter, ps.StrictPatchSorter)

    def validate_create_config_replacer(self, params, expected_decorators):
        factory = gu.GenericUpdateFactory()
        config_replacer = factory.create_config_replacer(params["config_format"],
                                                         params["verbose"],
                                                         params["dry_run"],
                                                         params["ignore_non_yang_tables"],
                                                         params["ignore_paths"])
        for decorator_type in expected_decorators:
            self.assertIsInstance(config_replacer, decorator_type)

            config_replacer = config_replacer.decorated_config_replacer

        self.assertIsInstance(config_replacer, gu.ConfigReplacer)
        if params["dry_run"]:
            self.assertIsInstance(config_replacer.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(config_replacer.patch_applier.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(config_replacer.patch_applier.changeapplier, ca.DryRunChangeApplier)
            self.assertIsInstance(config_replacer.patch_applier.changeapplier.config_wrapper, gu.DryRunConfigWrapper)
        else:
            self.assertIsInstance(config_replacer.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(config_replacer.patch_applier.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(config_replacer.patch_applier.changeapplier, ca.ChangeApplier)

        if params["ignore_non_yang_tables"] or params["ignore_paths"]:
            self.assertIsInstance(config_replacer.patch_applier.patchsorter, ps.NonStrictPatchSorter)
            expected_config_splitters = []
            if params["ignore_non_yang_tables"]:
                expected_config_splitters.append(ps.TablesWithoutYangConfigSplitter.__name__)
            if params["ignore_paths"]:
                expected_config_splitters.append(ps.IgnorePathsFromYangConfigSplitter.__name__)
            actual_config_splitters = [type(splitter).__name__ for splitter in
                    config_replacer.patch_applier.patchsorter.config_splitter.inner_config_splitters]
            self.assertCountEqual(expected_config_splitters, actual_config_splitters)
        else:
            self.assertIsInstance(config_replacer.patch_applier.patchsorter, ps.StrictPatchSorter)

    def validate_create_config_rollbacker(self, params, expected_decorators):
        factory = gu.GenericUpdateFactory()
        config_rollbacker = factory.create_config_rollbacker(params["verbose"], params["dry_run"], params["ignore_non_yang_tables"], params["ignore_paths"])
        for decorator_type in expected_decorators:
            self.assertIsInstance(config_rollbacker, decorator_type)

            config_rollbacker = config_rollbacker.decorated_config_rollbacker

        self.assertIsInstance(config_rollbacker, gu.FileSystemConfigRollbacker)
        if params["dry_run"]:
            self.assertIsInstance(config_rollbacker.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(config_rollbacker.config_replacer.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(
                config_rollbacker.config_replacer.patch_applier.config_wrapper, gu.DryRunConfigWrapper)
            self.assertIsInstance(config_rollbacker.config_replacer.patch_applier.changeapplier, ca.DryRunChangeApplier)
            self.assertIsInstance(
                config_rollbacker.config_replacer.patch_applier.changeapplier.config_wrapper, gu.DryRunConfigWrapper)
        else:
            self.assertIsInstance(config_rollbacker.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(config_rollbacker.config_replacer.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(
                config_rollbacker.config_replacer.patch_applier.config_wrapper, gu.ConfigWrapper)
            self.assertIsInstance(config_rollbacker.config_replacer.patch_applier.changeapplier, ca.ChangeApplier)

        if params["ignore_non_yang_tables"] or params["ignore_paths"]:
            self.assertIsInstance(config_rollbacker.config_replacer.patch_applier.patchsorter, ps.NonStrictPatchSorter)
            expected_config_splitters = []
            if params["ignore_non_yang_tables"]:
                expected_config_splitters.append(ps.TablesWithoutYangConfigSplitter.__name__)
            if params["ignore_paths"]:
                expected_config_splitters.append(ps.IgnorePathsFromYangConfigSplitter.__name__)
            actual_config_splitters = [type(splitter).__name__ for splitter in
                    config_rollbacker.config_replacer.patch_applier.patchsorter.config_splitter.inner_config_splitters]
            self.assertCountEqual(expected_config_splitters, actual_config_splitters)
        else:
            self.assertIsInstance(config_rollbacker.config_replacer.patch_applier.patchsorter, ps.StrictPatchSorter)

class TestGenericUpdater(unittest.TestCase):
    def setUp(self):
        self.any_checkpoint_name = "anycheckpoint"
        self.any_other_checkpoint_name = "anyothercheckpoint"
        self.any_checkpoints_list = [self.any_checkpoint_name, self.any_other_checkpoint_name]
        self.any_checkpoints_list_with_time = [
            {"name": self.any_checkpoint_name, "time": datetime.now(timezone.utc).isoformat()},
            {"name": self.any_other_checkpoint_name, "time": datetime.now(timezone.utc).isoformat()}
        ]

        self.any_config_format = gu.ConfigFormat.SONICYANG
        self.any_verbose = True
        self.list_checkpoints_includes_time = True
        self.any_dry_run = True
        self.any_ignore_non_yang_tables = True
        self.any_ignore_paths = ["", "/ACL_TABLE"]

    def test_apply_patch__creates_applier_and_apply(self):
        # Arrange
        patch_applier = Mock()
        patch_applier.apply.side_effect = create_side_effect_dict({(str(Files.SINGLE_OPERATION_SONIC_YANG_PATCH), "True"): 0})

        factory = Mock()
        factory.create_patch_applier.side_effect = \
            create_side_effect_dict(
                {(str(self.any_config_format),
                  str(self.any_verbose),
                  str(self.any_dry_run),
                  str(self.any_ignore_non_yang_tables),
                  str(self.any_ignore_paths)): patch_applier})

        generic_updater = gu.GenericUpdater(factory)

        # Act
        generic_updater.apply_patch(Files.SINGLE_OPERATION_SONIC_YANG_PATCH,
                                    self.any_config_format,
                                    self.any_verbose,
                                    self.any_dry_run,
                                    self.any_ignore_non_yang_tables,
                                    self.any_ignore_paths)

        # Assert
        patch_applier.apply.assert_has_calls([call(Files.SINGLE_OPERATION_SONIC_YANG_PATCH, True, trace_io=None)])

    def test_replace__creates_replacer_and_replace(self):
        # Arrange
        config_replacer = Mock()
        config_replacer.replace.side_effect = create_side_effect_dict({(str(Files.SONIC_YANG_AS_JSON),): 0})

        factory = Mock()
        factory.create_config_replacer.side_effect = \
            create_side_effect_dict(
                {(str(self.any_config_format),
                  str(self.any_verbose),
                  str(self.any_dry_run),
                  str(self.any_ignore_non_yang_tables),
                  str(self.any_ignore_paths)): config_replacer})

        generic_updater = gu.GenericUpdater(factory)

        # Act
        generic_updater.replace(Files.SONIC_YANG_AS_JSON,
                                self.any_config_format,
                                self.any_verbose,
                                self.any_dry_run,
                                self.any_ignore_non_yang_tables,
                                self.any_ignore_paths)

        # Assert
        config_replacer.replace.assert_has_calls([call(Files.SONIC_YANG_AS_JSON, trace_io=None)])

    def test_rollback__creates_rollbacker_and_rollback(self):
        # Arrange
        config_rollbacker = Mock()
        config_rollbacker.rollback.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})

        factory = Mock()
        factory.create_config_rollbacker.side_effect = \
            create_side_effect_dict({(str(self.any_verbose),
                                      str(self.any_dry_run),
                                      str(self.any_ignore_non_yang_tables),
                                      str(self.any_ignore_paths)): config_rollbacker})

        generic_updater = gu.GenericUpdater(factory)

        # Act
        generic_updater.rollback(self.any_checkpoint_name,
                                 self.any_verbose,
                                 self.any_dry_run,
                                 self.any_ignore_non_yang_tables,
                                 self.any_ignore_paths)

        # Assert
        config_rollbacker.rollback.assert_has_calls([call(self.any_checkpoint_name)])

    def test_checkpoint__creates_rollbacker_and_checkpoint(self):
        # Arrange
        config_rollbacker = Mock()
        config_rollbacker.checkpoint.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})

        factory = Mock()
        factory.create_config_rollbacker.side_effect = \
            create_side_effect_dict({(str(self.any_verbose),): config_rollbacker})

        generic_updater = gu.GenericUpdater(factory)

        # Act
        generic_updater.checkpoint(self.any_checkpoint_name, self.any_verbose)

        # Assert
        config_rollbacker.checkpoint.assert_has_calls([call(self.any_checkpoint_name)])

    def test_delete_checkpoint__creates_rollbacker_and_deletes_checkpoint(self):
        # Arrange
        config_rollbacker = Mock()
        config_rollbacker.delete_checkpoint.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})

        factory = Mock()
        factory.create_config_rollbacker.side_effect = \
            create_side_effect_dict({(str(self.any_verbose),): config_rollbacker})

        generic_updater = gu.GenericUpdater(factory)

        # Act
        generic_updater.delete_checkpoint(self.any_checkpoint_name, self.any_verbose)

        # Assert
        config_rollbacker.delete_checkpoint.assert_has_calls([call(self.any_checkpoint_name)])

    def test_list_checkpoints__creates_rollbacker_and_list_checkpoints(self):
        # Arrange
        config_rollbacker = Mock()
        config_rollbacker.list_checkpoints.return_value = self.any_checkpoints_list

        factory = Mock()
        factory.create_config_rollbacker.side_effect = \
            create_side_effect_dict({(str(self.any_verbose),): config_rollbacker})

        generic_updater = gu.GenericUpdater(factory)

        expected = self.any_checkpoints_list

        # Act
        actual = generic_updater.list_checkpoints(False, self.any_verbose)

        # Assert
        self.assertCountEqual(expected, actual)

    def test_list_checkpoints__creates_rollbacker_and_list_checkpoints_with_time(self):
        # Arrange
        config_rollbacker = Mock()
        config_rollbacker.list_checkpoints.return_value = self.any_checkpoints_list_with_time

        factory = Mock()
        factory.create_config_rollbacker.side_effect = \
            create_side_effect_dict({(str(self.any_verbose),): config_rollbacker})

        generic_updater = gu.GenericUpdater(factory)

        expected = self.any_checkpoints_list_with_time

        # Act
        actual = generic_updater.list_checkpoints(self.list_checkpoints_includes_time, self.any_verbose)

        # Assert
        self.assertCountEqual(expected, actual)

class TestDecorator(unittest.TestCase):
    def setUp(self):
        self.decorated_patch_applier = Mock()
        self.decorated_config_replacer = Mock()
        self.decorated_config_rollbacker = Mock()

        self.any_checkpoint_name = "anycheckpoint"
        self.any_other_checkpoint_name = "anyothercheckpoint"
        self.any_checkpoints_list = [self.any_checkpoint_name, self.any_other_checkpoint_name]
        self.decorated_config_rollbacker.list_checkpoints.return_value = self.any_checkpoints_list

        self.decorator = gu.Decorator(
            self.decorated_patch_applier, self.decorated_config_replacer, self.decorated_config_rollbacker)

    def test_apply__calls_decorated_applier(self):
        # Act
        self.decorator.apply(Files.SINGLE_OPERATION_SONIC_YANG_PATCH)

        # Assert
        self.decorated_patch_applier.apply.assert_has_calls(
            [call(Files.SINGLE_OPERATION_SONIC_YANG_PATCH, True, trace_io=None)]
        )

    def test_replace__calls_decorated_replacer(self):
        # Act
        self.decorator.replace(Files.SONIC_YANG_AS_JSON)

        # Assert
        self.decorated_config_replacer.replace.assert_has_calls([call(Files.SONIC_YANG_AS_JSON, trace_io=None)])

    def test_rollback__calls_decorated_rollbacker(self):
        # Act
        self.decorator.rollback(self.any_checkpoint_name)

        # Assert
        self.decorated_config_rollbacker.rollback.assert_has_calls([call(self.any_checkpoint_name)])

    def test_checkpoint__calls_decorated_rollbacker(self):
        # Act
        self.decorator.checkpoint(self.any_checkpoint_name)

        # Assert
        self.decorated_config_rollbacker.checkpoint.assert_has_calls([call(self.any_checkpoint_name)])

    def test_delete_checkpoint__calls_decorated_rollbacker(self):
        # Act
        self.decorator.delete_checkpoint(self.any_checkpoint_name)

        # Assert
        self.decorated_config_rollbacker.delete_checkpoint.assert_has_calls([call(self.any_checkpoint_name)])

    def test_list_checkpoints__calls_decorated_rollbacker(self):
        # Arrange
        expected = self.any_checkpoints_list

        # Act
        actual = self.decorator.list_checkpoints(includes_time=False)

        # Assert
        self.decorated_config_rollbacker.list_checkpoints.assert_called_once()
        self.assertListEqual(expected, actual)

class TestSonicYangDecorator(unittest.TestCase):
    def test_apply__converts_to_config_db_and_calls_decorated_class(self):
        # Arrange
        sonic_yang_decorator = self.__create_sonic_yang_decorator()

        # Act
        sonic_yang_decorator.apply(Files.SINGLE_OPERATION_SONIC_YANG_PATCH)

        # Assert
        sonic_yang_decorator.patch_wrapper.convert_sonic_yang_patch_to_config_db_patch.assert_has_calls(
            [call(Files.SINGLE_OPERATION_SONIC_YANG_PATCH)]
        )
        sonic_yang_decorator.decorated_patch_applier.apply.assert_has_calls(
            [call(Files.SINGLE_OPERATION_CONFIG_DB_PATCH, True, trace_io=None)]
        )

    def test_replace__converts_to_config_db_and_calls_decorated_class(self):
        # Arrange
        sonic_yang_decorator = self.__create_sonic_yang_decorator()

        # Act
        sonic_yang_decorator.replace(Files.SONIC_YANG_AS_JSON)

        # Assert
        sonic_yang_decorator.config_wrapper.convert_sonic_yang_to_config_db.assert_has_calls(
            [call(Files.SONIC_YANG_AS_JSON)])
        sonic_yang_decorator.decorated_config_replacer.replace.assert_has_calls(
            [call(Files.CONFIG_DB_AS_JSON, trace_io=None)]
        )

    def __create_sonic_yang_decorator(self):
        patch_applier = Mock()
        patch_applier.apply.side_effect = create_side_effect_dict(
            {(str(Files.SINGLE_OPERATION_CONFIG_DB_PATCH), 'True'): 0}
        )

        patch_wrapper = Mock()
        patch_wrapper.convert_sonic_yang_patch_to_config_db_patch.side_effect = \
            create_side_effect_dict({(str(Files.SINGLE_OPERATION_SONIC_YANG_PATCH),): \
                Files.SINGLE_OPERATION_CONFIG_DB_PATCH})

        config_replacer = Mock()
        config_replacer.replace.side_effect = create_side_effect_dict({(str(Files.CONFIG_DB_AS_JSON),): 0})

        config_wrapper = Mock()
        config_wrapper.convert_sonic_yang_to_config_db.side_effect = \
            create_side_effect_dict({(str(Files.SONIC_YANG_AS_JSON),): Files.CONFIG_DB_AS_JSON})

        return gu.SonicYangDecorator(decorated_patch_applier=patch_applier,
                                    decorated_config_replacer=config_replacer,
                                    patch_wrapper=patch_wrapper,
                                    config_wrapper=config_wrapper)

class TestConfigLockDecorator(unittest.TestCase):
    def setUp(self):
        self.any_checkpoint_name = "anycheckpoint"

    def test_apply__lock_config(self):
        # Arrange
        config_lock_decorator = self.__create_config_lock_decorator()

        # Act
        config_lock_decorator.apply(Files.SINGLE_OPERATION_SONIC_YANG_PATCH)

        # Assert
        config_lock_decorator.config_lock.acquire_lock.assert_called_once()
        config_lock_decorator.decorated_patch_applier.apply.assert_has_calls(
            [call(Files.SINGLE_OPERATION_SONIC_YANG_PATCH, True, trace_io=None)]
        )
        config_lock_decorator.config_lock.release_lock.assert_called_once()

    def test_replace__lock_config(self):
        # Arrange
        config_lock_decorator = self.__create_config_lock_decorator()

        # Act
        config_lock_decorator.replace(Files.SONIC_YANG_AS_JSON)

        # Assert
        config_lock_decorator.config_lock.acquire_lock.assert_called_once()
        config_lock_decorator.decorated_config_replacer.replace.assert_has_calls(
            [call(Files.SONIC_YANG_AS_JSON, trace_io=None)]
        )
        config_lock_decorator.config_lock.release_lock.assert_called_once()

    def test_rollback__lock_config(self):
        # Arrange
        config_lock_decorator = self.__create_config_lock_decorator()

        # Act
        config_lock_decorator.rollback(self.any_checkpoint_name)

        # Assert
        config_lock_decorator.config_lock.acquire_lock.assert_called_once()
        config_lock_decorator.decorated_config_rollbacker.rollback.assert_has_calls([call(self.any_checkpoint_name)])
        config_lock_decorator.config_lock.release_lock.assert_called_once()

    def test_checkpoint__lock_config(self):
        # Arrange
        config_lock_decorator = self.__create_config_lock_decorator()

        # Act
        config_lock_decorator.checkpoint(self.any_checkpoint_name)

        # Assert
        config_lock_decorator.config_lock.acquire_lock.assert_called_once()
        config_lock_decorator.decorated_config_rollbacker.checkpoint.assert_has_calls([call(self.any_checkpoint_name)])
        config_lock_decorator.config_lock.release_lock.assert_called_once()

    def __create_config_lock_decorator(self):
        config_lock = Mock()

        patch_applier = Mock()
        patch_applier.apply.side_effect = create_side_effect_dict(
            {(str(Files.SINGLE_OPERATION_SONIC_YANG_PATCH), 'True'): 0}
        )

        config_replacer = Mock()
        config_replacer.replace.side_effect = create_side_effect_dict({(str(Files.SONIC_YANG_AS_JSON),): 0})

        config_rollbacker = Mock()
        config_rollbacker.rollback.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})
        config_rollbacker.checkpoint.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})

        config_rollbacker.delete_checkpoint.side_effect = create_side_effect_dict({(self.any_checkpoint_name,): 0})

        return gu.ConfigLockDecorator(config_lock=config_lock,
                                      decorated_patch_applier=patch_applier,
                                      decorated_config_replacer=config_replacer,
                                      decorated_config_rollbacker=config_rollbacker)
