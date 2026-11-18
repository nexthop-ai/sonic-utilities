# Copyright 2026 Nexthop Systems Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from unittest import mock

import pytest

from utilities_common.prefix_masklength_range import (PREFIX_TABLE, masklength_range_refusal,
                                                      models_refuse_malformed_masklength_range, prefix_row_refusal,
                                                      split_malformed_prefix_rows)


def yang_leaf(name, patterns=()):
    leaf = mock.Mock()
    leaf.keyword.return_value = 'leaf'
    leaf.name.return_value = name
    leaf.type.return_value.patterns.side_effect = lambda: iter(patterns)
    return leaf


def models_with_masklength_range(patterns):
    lists = []
    for _ in ('PREFIX_LIST', 'PREFIX_NOSEQ_LIST'):
        entry = mock.Mock()
        entry.children.return_value = [yang_leaf('ip_prefix'), yang_leaf('masklength_range', patterns)]
        lists.append(entry)
    container = mock.Mock()
    container.children.return_value = lists
    sy = mock.Mock()
    sy.confDbYangMap = {PREFIX_TABLE: {'container': container}}
    return sy


class TestModelsRefuseMalformedMasklengthRange(object):

    def test_models_with_a_pattern(self):
        assert models_refuse_malformed_masklength_range(models_with_masklength_range([('exact|...', False)]))

    def test_models_without_a_pattern(self):
        assert not models_refuse_malformed_masklength_range(models_with_masklength_range([]))

    def test_models_without_the_table(self):
        sy = mock.Mock()
        sy.confDbYangMap = {}
        assert not models_refuse_malformed_masklength_range(sy)


class TestMasklengthRangeRefusal(object):

    @pytest.mark.parametrize('ip_prefix,masklength_range', [
        ('10.0.0.0/8', 'exact'),
        ('10.0.0.0/8', '8..32'),
        ('10.1.0.0/16', '8..24'),
        ('2001:db8::/32', '48..64'),
        ('2001:db8::/32', '128..128'),
        ('::ffff:10.0.0.0/104', '104..128'),
    ])
    def test_accepted(self, ip_prefix, masklength_range):
        assert masklength_range_refusal(ip_prefix, masklength_range) is None

    @pytest.mark.parametrize('ip_prefix,masklength_range,reason', [
        ('10.0.0.0/8', '', "is not 'exact'"),
        ('10.0.0.0/8', '24', "is not 'exact'"),
        ('10.0.0.0/8', '24..', "is not 'exact'"),
        ('10.0.0.0/8', '8..129', "is not 'exact'"),
        ('10.0.0.0/8', '024..32', "is not 'exact'"),
        ('10.0.0.0/8', '24..8', 'low bound above its high bound'),
        ('10.1.2.0/28', '16..24', 'high bound below the prefix length'),
        ('2001:db8::/64', '32..48', 'high bound below the prefix length'),
        ('10.0.0.0/8', '8..64', 'above 32 for an IPv4 prefix'),
    ])
    def test_refused(self, ip_prefix, masklength_range, reason):
        assert reason in masklength_range_refusal(ip_prefix, masklength_range)

    def test_a_row_key_with_and_without_a_sequence_number(self):
        assert prefix_row_refusal(('PL', '10', '10.0.0.0/8', '')) is not None
        assert prefix_row_refusal(('PL', '10.0.0.0/8', '24..8')) is not None
        assert prefix_row_refusal(('PL', '10', '10.0.0.0/8', '8..24')) is None
        assert prefix_row_refusal('PL') is None


class TestSplitMalformedPrefixRows(object):

    def test_refused_rows_are_split_out_whole(self):
        config = {
            'PREFIX': {
                'PL_S3_LO_V4|10|10.8.13.1/32|': {'action': 'permit'},
                'PL_S3_LO_V4|20|10.2.0.0/16|16..24': {'action': 'permit'},
                'PL|10.0.0.0/8|24..8': {},
            },
            'PREFIX_SET': {'PL_S3_LO_V4': {'mode': 'IPv4'}},
        }
        kept, removed, reasons = split_malformed_prefix_rows(config)
        assert kept == {
            'PREFIX': {'PL_S3_LO_V4|20|10.2.0.0/16|16..24': {'action': 'permit'}},
            'PREFIX_SET': {'PL_S3_LO_V4': {'mode': 'IPv4'}},
        }
        assert removed == {'PREFIX': {
            'PL_S3_LO_V4|10|10.8.13.1/32|': {'action': 'permit'},
            'PL|10.0.0.0/8|24..8': {},
        }}
        assert reasons == [
            "PREFIX|PL_S3_LO_V4|10|10.8.13.1/32| dropped: its masklength_range is not 'exact' or <low>..<high> "
            "with bounds 0 to 128",
            "PREFIX|PL|10.0.0.0/8|24..8 dropped: its masklength_range has a low bound above its high bound",
        ]
        assert 'PL_S3_LO_V4|10|10.8.13.1/32|' in config['PREFIX'], "the input is left as it was"

    def test_tuple_keys(self):
        kept, removed, _ = split_malformed_prefix_rows({'PREFIX': {('PL', '10', '10.0.0.0/8', ''): {}}})
        assert kept == {'PREFIX': {}}
        assert removed == {'PREFIX': {('PL', '10', '10.0.0.0/8', ''): {}}}

    @pytest.mark.parametrize('config', [
        {},
        {'PREFIX': {'PL|10|10.0.0.0/8|exact': {}}},
    ])
    def test_nothing_refused(self, config):
        assert split_malformed_prefix_rows(config) == (config, {}, [])
