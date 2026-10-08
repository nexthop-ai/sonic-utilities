import re

import pytest

from scapy.all import (Ether, Dot1Q, IP, IPv6, TCP, UDP, ICMP, Raw,
                       ICMPv6EchoRequest, ICMPv6Unknown)

from sonic_snake.platforms.base import SonicSnakeBase
from utilities_common import sonic_snake_helper
from utilities_common.sonic_snake_helper import (
    create_traffic_packet,
    delete_vlan,
    resolve_ip_version,
    validate_buffer_config,
)


class TestResolveIpVersion:
    def test_ipv4_pair(self):
        assert resolve_ip_version('10.0.0.1', '10.0.0.100') == (4, None)

    def test_ipv6_pair(self):
        assert resolve_ip_version('2001:db8::1', '2001:db8::100') == (6, None)

    def test_family_mismatch(self):
        version, err = resolve_ip_version('10.0.0.1', '2001:db8::100')
        assert version is None
        assert 'mismatch' in err

    def test_invalid_src(self):
        version, err = resolve_ip_version('not-an-ip', '10.0.0.100')
        assert version is None
        assert 'source' in err.lower()

    def test_invalid_dst(self):
        version, err = resolve_ip_version('10.0.0.1', 'example.com')
        assert version is None
        assert 'destination' in err.lower()


def build_one(packet_type='udp', src_ip='10.0.0.1', dst_ip='10.0.0.100',
              vlan_id=None, dscp=0, icmp_type=8, icmp_code=0,
              payload_sizes=None, payload_patterns=None):
    packets = create_traffic_packet(
        packet_type, 'aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55', vlan_id,
        dst_ip, src_ip, 12345, 54321, 'S', icmp_type, icmp_code,
        payload_sizes or [18], payload_patterns or ['58'], dscp=dscp)
    assert packets is not None and len(packets) == 1
    return packets[0]


class TestCreateTrafficPacketIpv4:
    @pytest.mark.parametrize('packet_type,l4', [
        ('udp', UDP), ('tcp', TCP), ('icmp', ICMP)])
    def test_layers(self, packet_type, l4):
        pkt = build_one(packet_type=packet_type)
        assert pkt.haslayer(IP)
        assert not pkt.haslayer(IPv6)
        assert pkt.haslayer(l4)
        assert pkt.haslayer(Raw)
        assert bytes(pkt[Raw].load) == b'X' * 18

    def test_dscp_in_tos(self):
        pkt = build_one(dscp=46)
        assert pkt[IP].tos == 46 << 2

    def test_vlan_tag(self):
        pkt = build_one(vlan_id=100)
        assert pkt.haslayer(Dot1Q)
        assert pkt[Dot1Q].vlan == 100


class TestCreateTrafficPacketIpv6:
    V6 = {'src_ip': '2001:db8::1', 'dst_ip': '2001:db8::100'}

    @pytest.mark.parametrize('packet_type,l4', [('udp', UDP), ('tcp', TCP)])
    def test_layers(self, packet_type, l4):
        pkt = build_one(packet_type=packet_type, **self.V6)
        assert pkt.haslayer(IPv6)
        assert not pkt.haslayer(IP)
        assert pkt.haslayer(l4)
        # The burst loop rewrites packet[Raw] in random-payload modes, so
        # every variant must keep a Raw layer.
        assert pkt.haslayer(Raw)

    def test_addresses(self):
        pkt = build_one(**self.V6)
        assert pkt[IPv6].src == '2001:db8::1'
        assert pkt[IPv6].dst == '2001:db8::100'

    def test_dscp_in_traffic_class(self):
        pkt = build_one(dscp=46, **self.V6)
        assert pkt[IPv6].tc == 46 << 2

    def test_vlan_tag(self):
        pkt = build_one(vlan_id=200, **self.V6)
        assert pkt.haslayer(Dot1Q)
        assert pkt[Dot1Q].vlan == 200

    @pytest.mark.parametrize('icmp_type', [8, 128])
    def test_icmp_echo_mapping(self, icmp_type):
        # The v4 echo default (8) and the native v6 echo type (128) both
        # build an ICMPv6 Echo Request
        pkt = build_one(packet_type='icmp', icmp_type=icmp_type, **self.V6)
        assert pkt.haslayer(ICMPv6EchoRequest)
        assert pkt.haslayer(Raw)

    def test_icmp_other_type(self):
        pkt = build_one(packet_type='icmp', icmp_type=135, **self.V6)
        assert pkt.haslayer(ICMPv6Unknown)
        assert pkt[ICMPv6Unknown].type == 135
        assert pkt.haslayer(Raw)

    def test_header_is_40_bytes_longer_than_ipv4(self):
        v4 = build_one()
        v6 = build_one(**self.V6)
        assert len(v6) - len(v4) == 20  # IPv6 (40B) vs IPv4 (20B) header

    def test_builds_to_wire_format(self):
        # bytes() computes real checksums (UDP over IPv6 is mandatory)
        pkt = build_one(**self.V6)
        wire = bytes(pkt)
        reparsed = Ether(wire)
        assert reparsed[UDP].chksum != 0


class TestCreateTrafficPacketErrors:
    def test_family_mismatch_returns_none(self):
        packets = create_traffic_packet(
            'udp', 'aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55', None,
            '2001:db8::100', '10.0.0.1', 12345, 54321, 'S', 8, 0,
            [18], ['58'])
        assert packets is None

    def test_invalid_address_returns_none(self):
        packets = create_traffic_packet(
            'udp', 'aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55', None,
            'nonsense', '10.0.0.1', 12345, 54321, 'S', 8, 0,
            [18], ['58'])
        assert packets is None


class TestValidateBufferConfig:
    """setup() refuses a switch whose CONFIG_DB has no BUFFER_POOL."""

    @pytest.fixture
    def fake_db(self, monkeypatch):
        logged = {'info': [], 'warning': [], 'error': []}

        def install(success, output='', error=''):
            monkeypatch.setattr(
                sonic_snake_helper, 'run_sonic_db_cli',
                lambda *args: {'success': success, 'output': output, 'error': error})
            for level in logged:
                monkeypatch.setattr(
                    sonic_snake_helper, f'log_{level}',
                    lambda msg, _lvl=level: logged[_lvl].append(msg))
            return logged

        return install

    def test_pools_present_passes(self, fake_db):
        logged = fake_db(True, 'BUFFER_POOL|ingress_lossless_pool\nBUFFER_POOL|egress_lossy_pool')
        assert validate_buffer_config() is True
        assert logged['error'] == []

    def test_no_pools_fails_and_names_the_fix(self, fake_db):
        logged = fake_db(True, '')
        assert validate_buffer_config() is False
        assert any('config qos reload' in msg for msg in logged['error'])

    def test_unreadable_db_does_not_block(self, fake_db):
        logged = fake_db(False, error='Could not connect to Redis')
        assert validate_buffer_config() is True
        assert len(logged['warning']) == 1
        assert logged['error'] == []

class TestDeleteVlan:
    """cleanup() deletes the VLAN that setup() auto-created."""

    @pytest.fixture
    def fake_sonic_command(self, monkeypatch):
        calls = []
        logged = {'warning': [], 'error': []}

        def install(success, stderr=''):
            def fake(args):
                calls.append(args)
                return {'success': success, 'stdout': '', 'stderr': stderr}
            monkeypatch.setattr(
                sonic_snake_helper, 'run_sonic_command', fake)
            for level in logged:
                monkeypatch.setattr(
                    sonic_snake_helper, f'log_{level}',
                    lambda msg, _lvl=level: logged[_lvl].append(msg))
            return calls, logged

        return install

    def test_deletes_via_config_vlan_del(self, fake_sonic_command):
        calls, _ = fake_sonic_command(True)
        assert delete_vlan(20) is True
        assert calls == [['config', 'vlan', 'del', '20']]

    def test_absent_vlan_is_success(self, fake_sonic_command):
        fake_sonic_command(False, 'Error: Vlan20 does not exist')
        assert delete_vlan(20) is True

    @pytest.mark.parametrize('stderr', [
        'Error: VLAN ID 20 can not be removed. First remove all members '
        'assigned to this VLAN.',
        'Error: Vlan20 can not be removed. First remove IP addresses '
        'assigned to this VLAN',
    ])
    def test_vlan_still_referenced_warns_and_leaves_it(
            self, fake_sonic_command, stderr):
        # A VLAN SONiC refuses to drop is somebody else's; warn, do not error.
        _, logged = fake_sonic_command(False, stderr)
        assert delete_vlan(20) is False
        assert len(logged['warning']) == 1
        assert logged['error'] == []

    def test_unexpected_error_is_logged_as_error(self, fake_sonic_command):
        _, logged = fake_sonic_command(False, 'Error: something else broke')
        assert delete_vlan(20) is False
        assert len(logged['error']) == 1
        assert logged['warning'] == []

    def test_exception_is_swallowed(self, monkeypatch):
        def boom(args):
            raise RuntimeError('no config_db')

        monkeypatch.setattr(sonic_snake_helper, 'run_sonic_command', boom)
        assert delete_vlan(20) is False


# ---------------------------------------------------------------------------
# Mirror destination lifecycle
#
# `mirror port <src> Mode=Ingress DestPort=<dst>` binds a mirror and creates a
# destination for <dst> unless one exists; `Mode=Off` only unbinds. Cleanup
# must destroy the destination it created and touch nothing else in the table.
# The fake below prints what the XGS diag shell prints on an NH-4010 (TH5).
# ---------------------------------------------------------------------------

NO_RESOURCES = "bcm_mirror_port_set: No resources for operation"
INVALID_PARAM = "MIRror bcm_mirror_destination_destroy failed()  Invalid parameter\n"
MIRROR_GPORT_BASE = 0x3c000000       # mirror gport type tag seen in `dump sw mirror` on gold224
GPORT_ID_MASK = (1 << 26) - 1
CPU_DEST = {0: "local port cpu0"}   # created by SAI at init: must never be destroyed

# Verbatim drivshell output captured on gold224 (NH-4010, SONiC.main.Nexthop.69805)
GOLD224_DEST_SHOW = ("mirror dest show\n"
                     "\n"
                     "Mirror Dest  1: Mirror ID:  0; local port cpu0\n"
                     "Mirror Dest  2: Mirror ID:  1; local port d3c20\n"
                     "Mirror Dest  3: Mirror ID:  2; local port d3c16\n"
                     "drivshell>\n")
GOLD224_SHOW_BOUND = "mirror show\n\nd3c0: Mirror ingress to local port d3c16\ndrivshell>\n"
GOLD224_SHOW_EMPTY = "mirror show\n\nNo mirror ports configured\ndrivshell>\n"


def local_port(name):
    return f"local port {name}"


def leaked(count, first_port=10):
    """A destination table holding `count` unbound front-panel destinations (ids 1..count)."""
    return {i + 1: local_port(f"d3c{first_port + i}") for i in range(count)}


def dest_of(mirror_id, port):
    """A parse_mirror_destinations() entry for a local-port destination."""
    return {'mirror_id': mirror_id, 'target': local_port(port), 'port': port,
            'text': f"Mirror Dest  1: Mirror ID:{mirror_id:3d}" "; " f"{local_port(port)}"}


def gport_destroy(mirror_id):
    return f"mirror dest destroy Id=0x{MIRROR_GPORT_BASE | mirror_id:x}"


GPORT_DESTROY_1 = gport_destroy(1)


class FakeBcmShell:
    """
    Stand-in for bcmcmd that models the ASIC's mirror state the way the XGS
    diag shell exposes it: a destination table of limited capacity with one
    entry per destination port (a later `mirror port` to the same port reuses
    it) plus per-source-port bindings. Mode=Off unbinds but does not destroy,
    and a destination that is still bound refuses to be destroyed (BUSY).
    """

    def __init__(self, capacity=7, dests=None, bindings=None, accept_plain_id=False,
                 accept_gport_id=True, gport_base=MIRROR_GPORT_BASE, show_extra="", dest_show_extra=""):
        self.capacity = capacity
        self.dests = dict(dests or {})          # mirror id -> target, e.g. 'local port d3c3'
        self.bindings = dict(bindings or {})    # source port -> mirror id
        self.accept_plain_id = accept_plain_id  # the real SDK rejects a bare id (Invalid parameter)
        self.accept_gport_id = accept_gport_id
        self.gport_base = gport_base            # the type tag this "SDK" wants on mirror gports
        self.show_extra = show_extra            # extra `mirror show` text in an unknown layout
        self.dest_show_extra = dest_show_extra  # extra `mirror dest show` text in an unknown layout
        self.commands = []

    def install(self, monkeypatch):
        monkeypatch.setattr(sonic_snake_helper, 'run_bcm_command', self)
        return self

    def __call__(self, cmd):
        self.commands.append(cmd)
        return {'success': True, 'stdout': self._dispatch(cmd), 'stderr': ''}

    def destroys(self):
        return [c for c in self.commands if c.startswith("mirror dest destroy")]

    def _wrap(self, cmd, body=""):
        return f"{cmd}\n\n{body}drivshell>\n"

    def _dispatch(self, cmd):
        if cmd == "mirror dest show":
            body = "".join(f"Mirror Dest {i + 1:2d}: Mirror ID:{mid:3d}" "; " f"{target}\n"
                           for i, (mid, target) in enumerate(sorted(self.dests.items())))
            return self._wrap(cmd, body + self.dest_show_extra)

        if cmd == "mirror show":
            body = "".join(f"{src}: Mirror ingress to {self.dests[mid]}\n"
                           for src, mid in self.bindings.items()) + self.show_extra
            return self._wrap(cmd, body or "No mirror ports configured\n")

        if cmd == "dump sw mirror":
            body = "SW Information MIRROR - Unit 0\n  Dest num            :    " f"{self.capacity}\n"
            body += "".join(f"  Mirror dest: 0x{self.gport_base | mid:08x}  Ref count:    1\n"
                            "              MTP Gport : 0x08000000\n" for mid in sorted(self.dests))
            return self._wrap(cmd, body)

        m = re.fullmatch(r"mirror dest destroy Id=(\S+)", cmd)
        if m:
            arg = m.group(1)
            if arg.startswith("0x"):
                value = int(arg, 16)
                if not self.accept_gport_id or value & ~GPORT_ID_MASK != self.gport_base:
                    return self._wrap(cmd, INVALID_PARAM)
                mid = value & GPORT_ID_MASK
            else:
                if not self.accept_plain_id:
                    return self._wrap(cmd, INVALID_PARAM)
                mid = int(arg)
            if mid in self.bindings.values():   # BCM_E_BUSY, as gold224 prints it
                return self._wrap(cmd, "MIRror bcm_mirror_destination_destroy failed()  Operation still running\n")
            if mid not in self.dests:
                return self._wrap(cmd, "MIRror bcm_mirror_destination_destroy failed()  Entry not found\n")
            del self.dests[mid]
            return self._wrap(cmd)

        m = re.fullmatch(r"mirror port (\S+) Mode=Ingress DestPort=(\S+)", cmd)
        if m:
            target = local_port(m.group(2))
            existing = [mid for mid, t in self.dests.items() if t == target]
            if existing:
                mid = existing[0]               # the SDK reuses the port's destination
            else:
                if len(self.dests) >= self.capacity:
                    return self._wrap(cmd, f"{NO_RESOURCES}\n")
                mid = next(i for i in range(self.capacity + 1) if i not in self.dests)
                self.dests[mid] = target
            self.bindings[m.group(1)] = mid
            return self._wrap(cmd)

        m = re.fullmatch(r"mirror port (\S+) Mode=Off", cmd)
        if m:
            self.bindings.pop(m.group(1), None)  # the destination survives
            return self._wrap(cmd)

        raise AssertionError(f"unexpected bcmcmd {cmd!r}")


class LogRecorder:
    """Captures what base.py logs, to assert on the table-full report."""

    def __init__(self):
        self.lines = []

    def _record(self, level, msg, *args, **kwargs):
        self.lines.append((level, msg))

    def debug(self, msg, *args, **kwargs):
        self._record("debug", msg)

    def info(self, msg, *args, **kwargs):
        self._record("info", msg)

    def warning(self, msg, *args, **kwargs):
        self._record("warning", msg)

    def error(self, msg, *args, **kwargs):
        self._record("error", msg)

    def text(self, level=None):
        return "\n".join(m for lvl, m in self.lines if level is None or lvl == level)


class TestParseMirrorDestinations:
    def test_gold224_output(self):
        dests = SonicSnakeBase.parse_mirror_destinations(GOLD224_DEST_SHOW)
        assert [(d['mirror_id'], d['port'], d['target']) for d in dests] == [
            (0, 'cpu0', 'local port cpu0'),
            (1, 'd3c20', 'local port d3c20'),
            (2, 'd3c16', 'local port d3c16')]
        assert dests[2]['text'] == "Mirror Dest  3: Mirror ID:  2; local port d3c16"

    def test_non_port_destination_has_no_port(self):
        output = "mirror dest show\nMirror Dest  1: Mirror ID:  4; trunk 2\ndrivshell>\n"
        dests = SonicSnakeBase.parse_mirror_destinations(output)
        assert [(d['mirror_id'], d['port'], d['target']) for d in dests] == [(4, None, 'trunk 2')]

    def test_empty_table(self):
        assert SonicSnakeBase.parse_mirror_destinations("mirror dest show\n\ndrivshell>\n") == []

    def test_unrecognised_layout_yields_nothing(self):
        output = "mirror dest show\nMirror destination id: 0x20000000\n    gport: 0x8000004\ndrivshell>\n"
        assert SonicSnakeBase.parse_mirror_destinations(output) == []
        assert SonicSnakeBase._parse_mirror_table(output) == (
            [], ["Mirror destination id: 0x20000000", "gport: 0x8000004"])


class TestParseMirrorBindings:
    def test_no_mirror_ports(self):
        assert SonicSnakeBase.parse_mirror_bindings(GOLD224_SHOW_EMPTY) == (False, set(), [])

    def test_prompt_only(self):
        assert SonicSnakeBase.parse_mirror_bindings("mirror show\ndrivshell>\n") == (False, set(), [])

    def test_gold224_binding_names_the_destination_port(self):
        assert SonicSnakeBase.parse_mirror_bindings(GOLD224_SHOW_BOUND) == (
            True, {'local port d3c16'}, [])

    def test_several_bindings(self):
        output = ("mirror show\n"
                  "d3c0: Mirror ingress to local port d3c16\n"
                  "d3c1: Mirror ingress and egress to local port d3c20\n"
                  "drivshell>\n")
        assert SonicSnakeBase.parse_mirror_bindings(output) == (
            True, {'local port d3c16', 'local port d3c20'}, [])

    def test_unrecognised_lines_are_reported(self):
        output = "mirror show\nMirroring on unit 0:\n  something new\ndrivshell>\n"
        assert SonicSnakeBase.parse_mirror_bindings(output) == (
            True, set(), ["Mirroring on unit 0:", "something new"])


class TestReleaseMirrorDestination:
    def test_destroys_the_tx_destination(self, monkeypatch):
        bcm = FakeBcmShell(dests={**CPU_DEST, 1: local_port('d3c3')}).install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert bcm.dests == CPU_DEST
        assert bcm.destroys() == [GPORT_DESTROY_1]

    def test_snapshots_destinations_before_bindings(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1, first_port=3)).install(monkeypatch)
        SonicSnakeBase().release_mirror_destination('d3c3')
        assert bcm.commands[:2] == ["mirror dest show", "mirror show"]

    def test_keeps_it_while_another_source_port_mirrors_to_it(self, monkeypatch):
        dests = leaked(1, first_port=3)
        bcm = FakeBcmShell(dests=dests, bindings={'d3c1': 1}).install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert bcm.destroys() == []
        assert bcm.dests == dests

    def test_touches_no_other_destination(self, monkeypatch):
        others = {**CPU_DEST, **leaked(3, first_port=10)}
        bcm = FakeBcmShell(dests={**others, 4: local_port('d3c3')}).install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert bcm.dests == others
        assert bcm.destroys() == [gport_destroy(4)]

    def test_nothing_to_release_warns_and_touches_nothing(self, monkeypatch):
        import sonic_snake.platforms.base as base_module
        recorder = LogRecorder()
        monkeypatch.setattr(base_module, 'log', recorder)
        dests = {**CPU_DEST, **leaked(2)}
        bcm = FakeBcmShell(dests=dests).install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert bcm.commands == ["mirror dest show"]
        assert bcm.dests == dests
        assert "No mirror destination for d3c3 to release" in recorder.text("warning")

    def test_refuses_when_mirror_show_is_unrecognised(self, monkeypatch):
        dests = leaked(1, first_port=3)
        bcm = FakeBcmShell(dests=dests, show_extra="d3c0 -> 0x3c000001\n").install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is False
        assert bcm.destroys() == []
        assert bcm.dests == dests

    def test_reports_failure_when_mirror_dest_show_is_unrecognised(self, monkeypatch):
        import sonic_snake.platforms.base as base_module
        recorder = LogRecorder()
        monkeypatch.setattr(base_module, 'log', recorder)
        bcm = FakeBcmShell(dest_show_extra="Mirror destination id: 0x3c000001\n").install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is False
        assert bcm.destroys() == []
        assert "does not understand" in recorder.text("warning")
        assert "Cannot tell whether a mirror destination for d3c3" in recorder.text("warning")

    def test_still_releases_its_destination_next_to_an_unrecognised_line(self, monkeypatch):
        bcm = FakeBcmShell(dests={1: local_port('d3c3')},
                           dest_show_extra="Mirror destination id: 0x3c000009\n").install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert bcm.dests == {}

    def test_failed_destroy_is_reported(self, monkeypatch):
        dests = leaked(1, first_port=3)
        bcm = FakeBcmShell(dests=dests, accept_gport_id=False).install(monkeypatch)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is False
        assert bcm.dests == dests


class TestDestroyMirrorDestination:
    def test_mirror_gport_then_verifies(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1)).install(monkeypatch)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is True
        assert bcm.commands == [GPORT_DESTROY_1, "mirror dest show"]
        assert bcm.dests == {}

    def test_learns_a_different_gport_tag_from_dump_sw_mirror(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1), gport_base=0x50000000).install(monkeypatch)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is True
        assert bcm.commands == [GPORT_DESTROY_1, "dump sw mirror",
                                "mirror dest destroy Id=0x50000001", "mirror dest show"]
        assert bcm.dests == {}

    def test_falls_back_to_the_bare_mirror_id(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1), accept_gport_id=False, accept_plain_id=True).install(monkeypatch)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is True
        assert bcm.commands == [GPORT_DESTROY_1, "dump sw mirror", "mirror dest destroy Id=1", "mirror dest show"]
        assert bcm.dests == {}

    def test_silent_no_op_is_detected_by_relisting(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1), accept_plain_id=True).install(monkeypatch)
        real = bcm._dispatch
        bcm._dispatch = lambda cmd: bcm._wrap(cmd) if cmd == GPORT_DESTROY_1 else real(cmd)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is True
        assert bcm.commands == [GPORT_DESTROY_1, "mirror dest show", "dump sw mirror",
                                "mirror dest destroy Id=1", "mirror dest show"]
        assert bcm.dests == {}

    def test_gives_up_when_no_form_is_accepted(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1), accept_gport_id=False).install(monkeypatch)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is False
        assert bcm.commands == [GPORT_DESTROY_1, "dump sw mirror", "mirror dest destroy Id=1"]
        assert bcm.dests == leaked(1)

    def test_busy_destination_is_reported_as_failure(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1), bindings={'d3c0': 1}).install(monkeypatch)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is False
        assert bcm.dests == leaked(1)

    def test_nonzero_rc_means_failure(self, monkeypatch):
        monkeypatch.setattr(sonic_snake_helper, 'run_bcm_command',
                            lambda cmd: {'success': False, 'stdout': '', 'stderr': 'boom'})
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is False

    def test_id_reused_by_a_new_destination_counts_as_destroyed(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(1)).install(monkeypatch)
        real = bcm._dispatch

        def dispatch(cmd):
            out = real(cmd)
            if cmd.startswith("mirror dest destroy"):
                bcm.dests[1] = local_port('d3c30')   # another session grabbed the freed id
            return out

        bcm._dispatch = dispatch
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is True
        assert bcm.destroys() == [GPORT_DESTROY_1]


class TestCleanupMirror:
    def test_destroys_the_destination_it_created(self, monkeypatch):
        bcm = FakeBcmShell(dests=dict(CPU_DEST)).install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c3') is True
        assert bcm.dests == {**CPU_DEST, 1: local_port('d3c3')}
        assert bcm.bindings == {'d3c0': 1}

        assert snake.cleanup_mirror('d3c0', 'd3c3') is True
        assert bcm.bindings == {}
        assert bcm.dests == CPU_DEST
        off = bcm.commands.index("mirror port d3c0 Mode=Off")
        assert GPORT_DESTROY_1 in bcm.commands[off:]

    def test_leaves_destinations_it_did_not_create_alone(self, monkeypatch):
        others = {**CPU_DEST, **leaked(3, first_port=10)}
        bcm = FakeBcmShell(dests=others).install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c3') is True
        assert snake.cleanup_mirror('d3c0', 'd3c3') is True
        assert bcm.dests == others
        assert len(bcm.destroys()) == 1

    def test_leaves_other_sessions_alone(self, monkeypatch):
        bcm = FakeBcmShell().install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c3') is True
        assert snake.setup_mirror('d3c1', 'd3c4') is True
        other = bcm.bindings['d3c1']

        assert snake.cleanup_mirror('d3c0', 'd3c3') is True
        assert bcm.bindings == {'d3c1': other}
        assert bcm.dests == {other: local_port('d3c4')}

    def test_shared_tx_port_survives_until_its_last_user_cleans_up(self, monkeypatch):
        bcm = FakeBcmShell().install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c3') is True
        assert snake.setup_mirror('d3c1', 'd3c3') is True
        assert len(bcm.dests) == 1                        # the SDK reused the destination

        assert snake.cleanup_mirror('d3c0', 'd3c3') is True
        assert len(bcm.dests) == 1
        assert bcm.bindings == {'d3c1': 0}
        assert snake.cleanup_mirror('d3c1', 'd3c3') is True
        assert bcm.dests == {}
        assert bcm.bindings == {}

    def test_heals_a_leak_on_its_own_tx_port(self, monkeypatch):
        # a destination for the TX port left by an aborted run is reused by setup, then destroyed
        bcm = FakeBcmShell(dests={**CPU_DEST, 2: local_port('d3c16')}).install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c16') is True
        assert bcm.dests == {**CPU_DEST, 2: local_port('d3c16')}
        assert snake.cleanup_mirror('d3c0', 'd3c16') is True
        assert bcm.dests == CPU_DEST

    def test_repeated_sessions_do_not_exhaust_the_table(self, monkeypatch):
        bcm = FakeBcmShell(capacity=2, dests=dict(CPU_DEST)).install(monkeypatch)
        snake = SonicSnakeBase()
        for _ in range(10):
            assert snake.setup_mirror('d3c0', 'd3c3') is True
            assert snake.cleanup_mirror('d3c0', 'd3c3') is True
        assert bcm.dests == CPU_DEST

    def test_without_a_tx_port_it_only_unbinds(self, monkeypatch):
        bcm = FakeBcmShell(dests=leaked(2)).install(monkeypatch)
        assert SonicSnakeBase().cleanup_mirror('d3c0') is True
        assert bcm.commands == ["mirror port d3c0 Mode=Off"]
        assert bcm.dests == leaked(2)

    def test_unbind_failure_is_reported_and_skips_the_release(self, monkeypatch):
        monkeypatch.setattr(sonic_snake_helper, 'run_bcm_command',
                            lambda cmd: {'success': False, 'stdout': '', 'stderr': 'boom'})
        calls = []
        snake = SonicSnakeBase()
        monkeypatch.setattr(snake, 'release_mirror_destination', lambda tx: calls.append(tx))
        assert snake.cleanup_mirror('d3c0', 'd3c3') is False
        assert calls == []

    def test_reports_a_destination_it_could_not_release(self, monkeypatch):
        bcm = FakeBcmShell(accept_gport_id=False).install(monkeypatch)
        snake = SonicSnakeBase()
        assert snake.setup_mirror('d3c0', 'd3c3') is True
        assert snake.cleanup_mirror('d3c0', 'd3c3') is False
        assert bcm.dests == {0: local_port('d3c3')}


class TestSetupMirror:
    def test_creates_without_touching_other_destinations(self, monkeypatch):
        others = {**CPU_DEST, **leaked(2)}
        bcm = FakeBcmShell(dests=others).install(monkeypatch)
        assert SonicSnakeBase().setup_mirror('d3c0', 'd3c3') is True
        assert bcm.commands == ["mirror port d3c0 Mode=Ingress DestPort=d3c3"]
        assert bcm.dests == {**others, 3: local_port('d3c3')}
        assert bcm.bindings == {'d3c0': 3}

    def test_full_table_fails_and_lists_the_table(self, monkeypatch):
        import sonic_snake.platforms.base as base_module
        recorder = LogRecorder()
        monkeypatch.setattr(base_module, 'log', recorder)
        dests = {**CPU_DEST, **leaked(6)}                 # 7 of 7 on an NH-4010
        bcm = FakeBcmShell(capacity=7, dests=dests, bindings={'d3c1': 1}).install(monkeypatch)

        assert SonicSnakeBase().setup_mirror('d3c0', 'd3c3') is False
        assert bcm.dests == dests
        assert bcm.destroys() == []
        errors = recorder.text("error")
        assert "Mirror session limit reached" in errors
        assert "local port cpu0 [unbound]" in errors
        assert "local port d3c10 [bound]" in errors
        assert "local port d3c11 [unbound]" in errors
        assert gport_destroy(2) in errors                 # unbound d3c11: offered to the operator
        assert gport_destroy(1) not in errors             # bound: not offered
        assert gport_destroy(0) not in errors             # cpu0: not offered

    def test_internal_port_destinations_are_never_offered_to_the_operator(self, monkeypatch):
        import sonic_snake.platforms.base as base_module
        recorder = LogRecorder()
        monkeypatch.setattr(base_module, 'log', recorder)
        dests = {0: local_port('cpu0'), 1: local_port('lb0'), 2: local_port('rdb0'),
                 3: local_port('d3c11'), 4: 'trunk 2'}
        bcm = FakeBcmShell(capacity=5, dests=dests).install(monkeypatch)

        assert SonicSnakeBase().setup_mirror('d3c0', 'd3c3') is False
        errors = recorder.text("error")
        assert gport_destroy(3) in errors                 # the only front-panel unbound entry
        for mirror_id in (0, 1, 2, 4):
            assert gport_destroy(mirror_id) not in errors
        assert bcm.destroys() == []

    def test_other_bcm_errors_fail(self, monkeypatch):
        outputs = []

        def run(cmd):
            outputs.append(cmd)
            body = "Failed to execute the diagnostic command\n" if cmd.startswith("mirror port") else ""
            return {'success': True, 'stdout': f"{cmd}\n{body}drivshell>\n", 'stderr': ''}

        monkeypatch.setattr(sonic_snake_helper, 'run_bcm_command', run)
        assert SonicSnakeBase().setup_mirror('d3c0', 'd3c3') is False
        assert outputs == ["mirror port d3c0 Mode=Ingress DestPort=d3c3"]


class TestBcmOutputRobustness:
    """Empty or failed diag output must never read as a clean result."""

    @staticmethod
    def _bcm_returning(monkeypatch, success, stdout, recorder):
        import sonic_snake.platforms.base as base_module
        monkeypatch.setattr(base_module, 'log', recorder)
        monkeypatch.setattr(sonic_snake_helper, 'run_bcm_command',
                            lambda cmd: {'success': success, 'stdout': stdout, 'stderr': ''})

    def test_failed_dest_show_is_unreadable(self, monkeypatch):
        recorder = LogRecorder()
        self._bcm_returning(monkeypatch, False, '', recorder)
        assert SonicSnakeBase().list_mirror_destinations() == ([], False)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is False
        assert "no usable output" in recorder.text("warning")

    def test_empty_dest_show_output_is_unreadable(self, monkeypatch):
        recorder = LogRecorder()
        self._bcm_returning(monkeypatch, True, '', recorder)
        assert SonicSnakeBase().list_mirror_destinations() == ([], False)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is False
        assert "no usable output" in recorder.text("warning")

    def test_empty_table_with_prompt_is_readable(self, monkeypatch):
        recorder = LogRecorder()
        self._bcm_returning(monkeypatch, True, "mirror dest show\n\ndrivshell>\n", recorder)
        assert SonicSnakeBase().list_mirror_destinations() == ([], True)
        assert SonicSnakeBase().release_mirror_destination('d3c3') is True
        assert "No mirror destination for d3c3 to release" in recorder.text("warning")

    def test_destroy_is_not_counted_when_the_relisting_is_unreadable(self, monkeypatch):
        import sonic_snake.platforms.base as base_module
        recorder = LogRecorder()
        monkeypatch.setattr(base_module, 'log', recorder)
        bcm = FakeBcmShell(dests=leaked(1)).install(monkeypatch)
        real = bcm._dispatch
        bcm._dispatch = lambda cmd: "" if cmd == "mirror dest show" else real(cmd)
        assert SonicSnakeBase().destroy_mirror_destination(dest_of(1, 'd3c10')) is False
        assert bcm.dests == {}                          # the SDK did destroy it
        assert "Could not destroy" in recorder.text("warning")

    def test_unbind_error_text_with_rc_zero_is_a_failure(self, monkeypatch):
        recorder = LogRecorder()
        self._bcm_returning(monkeypatch, True,
                            "mirror port d3c0 Mode=Off\nFailed to execute the diagnostic command. "
                            "Error: Operation failed.\ndrivshell>\n", recorder)
        calls = []
        snake = SonicSnakeBase()
        monkeypatch.setattr(snake, 'release_mirror_destination', lambda tx: calls.append(tx))
        assert snake.cleanup_mirror('d3c0', 'd3c3') is False
        assert calls == []
        assert "Failed to disable port mirroring on d3c0" in recorder.text("error")

    def test_clean_unbind_output_passes(self, monkeypatch):
        recorder = LogRecorder()
        self._bcm_returning(monkeypatch, True, "mirror port d3c0 Mode=Off\n\ndrivshell>\n", recorder)
        assert SonicSnakeBase().cleanup_mirror('d3c0') is True
        assert recorder.text("error") == ""
