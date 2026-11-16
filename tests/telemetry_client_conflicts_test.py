# Copyright 2026 Nexthop Systems Inc. All rights reserved.
# This software is proprietary and confidential. Unauthorized use, distribution, or modification is strictly prohibited.
from utilities_common.telemetry_client_conflicts import split_telemetry_client_dst_group_conflicts


def subscription(dst_group):
    return {'dst_group': dst_group, 'path_target': 'COUNTERS_DB',
            'paths': 'COUNTERS/Ethernet*', 'report_type': 'periodic'}


class TestSplitTelemetryClientDstGroupConflicts(object):

    def test_subscriptions_without_a_destination_group_are_split_out(self):
        cfg = {
            'TELEMETRY_CLIENT': {
                'Global': {'encoding': 'JSON_IETF', 'src_ip': '10.0.0.1'},
                'DestinationGroup|DCI': {'dst_addr': '10.0.0.2:8081'},
                'DestinationGroup|HS': {'dst_addr': '10.0.0.3:8081'},
                'Subscription|GOOD': subscription('HS'),
                # Accepted by the old contains() check, rejected by the new must.
                'Subscription|SUBSTRING': subscription('CI'),
                'Subscription|NAMES_SUBSCRIPTION': subscription('GOOD'),
                # Outside the constraint.
                'Subscription|NO_GROUP': {'path_target': 'COUNTERS_DB'},
            },
            'PORT': {'Ethernet0': {'mtu': '9100'}},
        }
        kept, removed, reasons = split_telemetry_client_dst_group_conflicts(cfg)

        assert sorted(kept['TELEMETRY_CLIENT']) == [
            'DestinationGroup|DCI', 'DestinationGroup|HS', 'Global',
            'Subscription|GOOD', 'Subscription|NO_GROUP']
        assert kept['PORT'] is cfg['PORT']
        assert removed == {'TELEMETRY_CLIENT': {
            'Subscription|SUBSTRING': subscription('CI'),
            'Subscription|NAMES_SUBSCRIPTION': subscription('GOOD'),
        }}
        assert reasons == [
            "TELEMETRY_CLIENT|Subscription|NAMES_SUBSCRIPTION dropped: dst_group 'GOOD' names no "
            "DestinationGroup, so it had no collector to dial",
            "TELEMETRY_CLIENT|Subscription|SUBSTRING dropped: dst_group 'CI' names no "
            "DestinationGroup, so it had no collector to dial",
        ]

    def test_input_is_not_modified(self):
        table = {'DestinationGroup|DCI': {'dst_addr': '10.0.0.2:8081'},
                 'Subscription|BAD': subscription('CI')}
        cfg = {'TELEMETRY_CLIENT': table}
        snapshot = {key: dict(value) for key, value in table.items()}

        kept, _, _ = split_telemetry_client_dst_group_conflicts(cfg)

        assert cfg['TELEMETRY_CLIENT'] is table
        assert table == snapshot
        assert 'Subscription|BAD' not in kept['TELEMETRY_CLIENT']

    def test_tuple_keys_from_config_db_are_kept_as_given(self):
        cfg = {'TELEMETRY_CLIENT': {
            'Global': {'encoding': 'JSON_IETF'},
            ('DestinationGroup', 'DCI'): {'dst_addr': '10.0.0.2:8081'},
            ('Subscription', 'GOOD'): subscription('DCI'),
            ('Subscription', 'BAD'): subscription('CI'),
        }}
        kept, removed, _ = split_telemetry_client_dst_group_conflicts(cfg)

        assert ('Subscription', 'GOOD') in kept['TELEMETRY_CLIENT']
        assert removed == {'TELEMETRY_CLIENT': {('Subscription', 'BAD'): subscription('CI')}}

    def test_valid_config_is_returned_unchanged(self):
        cfg = {'TELEMETRY_CLIENT': {
            'DestinationGroup|HS': {'dst_addr': '10.0.0.2:8081'},
            'Subscription|A': subscription('HS'),
        }}
        assert split_telemetry_client_dst_group_conflicts(cfg) == (cfg, {}, [])

    def test_config_without_the_table_is_returned_unchanged(self):
        cfg = {'PORT': {'Ethernet0': {}}}
        assert split_telemetry_client_dst_group_conflicts(cfg) == (cfg, {}, [])
