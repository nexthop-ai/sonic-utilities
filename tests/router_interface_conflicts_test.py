from utilities_common.router_interface_conflicts import find_router_interface_vlan_conflicts


class TestFindRouterInterfaceVlanConflicts(object):

    def test_addressed_router_interface_keeps_its_row(self):
        tables = {
            'INTERFACE': {'Ethernet0': {}, ('Ethernet0', '10.0.0.1/31'): {}},
            'VLAN_MEMBER': {('Vlan10', 'Ethernet0'): {'tagging_mode': 'untagged'}},
        }
        assert find_router_interface_vlan_conflicts(tables) == {'VLAN_MEMBER': [('Vlan10', 'Ethernet0')]}

    def test_address_rows_alone_make_a_router_interface(self):
        tables = {
            'PORTCHANNEL_INTERFACE': {'PortChannel2|10.0.0.3/31': {}},
            'VLAN_MEMBER': {'Vlan10|PortChannel2': {'tagging_mode': 'tagged'},
                            'Vlan20|PortChannel2': {'tagging_mode': 'tagged'}},
        }
        assert find_router_interface_vlan_conflicts(tables) == {
            'VLAN_MEMBER': ['Vlan10|PortChannel2', 'Vlan20|PortChannel2']}

    def test_ipv6_link_local_only_keeps_its_row(self):
        tables = {
            'INTERFACE': {'Ethernet0': {'ipv6_use_link_local_only': 'enable'}},
            'VLAN_MEMBER': {'Vlan10|Ethernet0': {'tagging_mode': 'untagged'}},
        }
        assert find_router_interface_vlan_conflicts(tables) == {'VLAN_MEMBER': ['Vlan10|Ethernet0']}

    def test_bare_row_is_dropped_and_memberships_kept(self):
        tables = {
            'INTERFACE': {'Ethernet4': {'mpls': 'enable'}},
            'PORTCHANNEL_INTERFACE': {'PortChannel2': {'ipv6_use_link_local_only': 'disable'}},
            'VLAN_MEMBER': {'Vlan10|Ethernet4': {'tagging_mode': 'untagged'},
                            'Vlan10|PortChannel2': {'tagging_mode': 'tagged'}},
        }
        assert find_router_interface_vlan_conflicts(tables) == {
            'INTERFACE': ['Ethernet4'], 'PORTCHANNEL_INTERFACE': ['PortChannel2']}

    def test_no_conflict(self):
        tables = {
            'INTERFACE': {'Ethernet0': {}, 'Ethernet0|10.0.0.1/31': {}},
            'VLAN_MEMBER': {'Vlan10|Ethernet4': {'tagging_mode': 'untagged'}},
        }
        assert find_router_interface_vlan_conflicts(tables) == {}
        assert find_router_interface_vlan_conflicts({}) == {}
