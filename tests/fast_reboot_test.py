import os
import re
import pytest
import shutil
import subprocess
import tempfile
from pathlib import Path


FAST_REBOOT = Path(__file__).parents[1] / "scripts" / "fast-reboot"


@pytest.mark.parametrize("reboot_type", ["warm-reboot", "fastfast-reboot", "express-reboot", "fast-reboot"])
@pytest.mark.parametrize("probe_success", [False, True])
@pytest.mark.parametrize("namespace", ["", "asic1"])
def test_lag_keepalive_preserves_only_negotiated_retry_counts(tmp_path, reboot_type, probe_success, namespace):
    script = FAST_REBOOT.read_text()
    function = re.search(r"^function start_lag_keepalive\(\).*?^}", script, re.M | re.S).group()
    # Redirect the marker to a test-owned path, never touching live reboot state.
    dev = namespace.removeprefix("asic")
    marker = tmp_path / f"probe_success{dev}"
    if probe_success:
        marker.touch()
    else:
        (tmp_path / "probe_success_other_asic").touch()
    function = function.replace("/tmp/teamd_retry_count_probe_success", str(tmp_path / "probe_success"))
    driver = function + '''
debug() { :; }
timeout() { printf '<%s>\\n' "$@"; }
sleep() { printf 'sleep:%s\\n' "$1"; }
start_lag_keepalive
'''
    env = dict(os.environ, REBOOT_TYPE=reboot_type, NETNS=namespace, DEV=dev,
               LAG_KEEPALIVE_SCRIPT="/usr/local/bin/lag_keepalive.py")
    result = subprocess.run(["bash", "-e", "-c", driver], env=env,
                            capture_output=True, text=True, timeout=10)
    expected = ["<--foreground>", "<30>", "<python3>", "</usr/local/bin/lag_keepalive.py>",
                "<--fork-into-background>", "<--namespace>", f"<{namespace}>"]
    if probe_success and reboot_type != "fast-reboot":
        expected.append("<--preserve-retry-count>")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == expected + ["sleep:5"]


def test_lag_keepalive_starts_after_negotiation_before_shutdown():
    script = FAST_REBOOT.read_text()
    start = "execute_in_namespaces asic start_lag_keepalive"
    assert script.count(start) == 1
    assert (script.index("    setup_control_plane_assistant", script.index("execute_in_namespaces all init_warm")) <
            script.index("    execute_in_namespaces asic probe_teamd_retry_count") <
            script.index("    execute_in_namespaces asic pause_orchagent") <
            script.index("    execute_in_namespaces asic increase_teamd_retry_count") <
            script.index("\nset +e") <
            script.index("    execute_in_namespaces asic filter_routes") <
            script.index("trap '' EXIT HUP INT QUIT TERM KILL ABRT ALRM") <
            script.index(start) < script.index("\n    stop_service $service"))


@pytest.mark.parametrize("reboot_type", ["warm-reboot", "fastfast-reboot", "express-reboot", "fast-reboot"])
@pytest.mark.parametrize("increase_status", [0, 1])
@pytest.mark.parametrize("keepalive_status", [0, 1, 124])
def test_lag_keepalive_shutdown_sequence(reboot_type, increase_status, keepalive_status):
    script = FAST_REBOOT.read_text()
    start = script.index("execute_in_namespaces all init_warm_reboot_states")
    keepalive_call = "execute_in_namespaces asic start_lag_keepalive"
    end = script.index(keepalive_call, start) + len(keepalive_call)
    sequence = re.sub(r"^function \w+\(\).*?^}\n", "", script[start:end], flags=re.M | re.S)
    driver = '''
execute_in_namespaces() { shift; "$@"; }
init_warm_reboot_states() { echo init; }
setup_control_plane_assistant() { echo cpa; }
probe_teamd_retry_count() { echo probe; }
pause_orchagent() { echo pause; }
increase_teamd_retry_count() { echo increase; return "$INCREASE_STATUS"; }
filter_routes() { echo filter; }
start_lag_keepalive() { echo keepalive; return "$KEEPALIVE_STATUS"; }
''' + sequence + '\necho shutdown\n'
    env = dict(os.environ, REBOOT_TYPE=reboot_type, NUM_ASIC="1",
               REQUIRE_TEAMD_RETRY_COUNT="no", INCREASE_STATUS=str(increase_status),
               KEEPALIVE_STATUS=str(keepalive_status))
    result = subprocess.run(["bash", "-e", "-c", driver], env=env,
                            capture_output=True, text=True, timeout=10)
    if reboot_type == "fast-reboot":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["init", "cpa", "pause", "filter", "keepalive", "shutdown"]
    else:
        assert result.returncode == increase_status, result.stderr
        expected = ["init", "cpa", "probe", "pause", "increase"]
        if not increase_status:
            expected.extend(["keepalive", "shutdown"])
        assert result.stdout.splitlines() == expected


def run_cpa_tunnel_check(tmp_path, tunnel_type="", tunnel_term_type=""):
    command_log = tmp_path / "commands.log"
    script = f'''
EXIT_LEFTOVER_CPA_TUNNEL=30
source <(sed -n '/^function abort_reboot_if_cpa_tunnel_is_leftover()/,/^}}/p' "{FAST_REBOOT}")

debug() {{ :; }}
error() {{ printf '%s\n' "$*" >&2; }}
sonic-db-cli() {{
    printf '%s\n' "$*" >> "$COMMAND_LOG"
    if [[ "$3" == "KEYS" && "$4" == "ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL:*" ]]; then
        if [[ -n "$TUNNEL_TYPE" ]]; then
            printf 'ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL:oid:0x1\n'
        fi
    elif [[ "$3" == "HGET" && "$5" == "SAI_TUNNEL_ATTR_TYPE" ]]; then
        printf '%s\n' "$TUNNEL_TYPE"
    elif [[ "$3" == "KEYS" && "$4" == "ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL_TERM_TABLE_ENTRY:*" ]]; then
        if [[ -n "$TUNNEL_TERM_TYPE" ]]; then
            printf 'ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL_TERM_TABLE_ENTRY:oid:0x2\n'
        fi
    elif [[ "$3" == "HGET" && "$5" == "SAI_TUNNEL_TERM_TABLE_ENTRY_ATTR_TUNNEL_TYPE" ]]; then
        printf '%s\n' "$TUNNEL_TERM_TYPE"
    fi
}}

abort_reboot_if_cpa_tunnel_is_leftover
'''
    env = os.environ.copy()
    env["COMMAND_LOG"] = str(command_log)
    env["TUNNEL_TYPE"] = tunnel_type
    env["TUNNEL_TERM_TYPE"] = tunnel_term_type
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True
    )
    return result, command_log.read_text().splitlines()


class TestFastReboot:
    @pytest.mark.parametrize(
        "working_script,failing_script", [
            pytest.param('whoami', 'logname', id='without_logname'),
            pytest.param('logname', 'whoami', id='without_whoami'),
        ]
    )
    def test_fast_reboot_user(self, working_script, failing_script):
        test_path = os.path.dirname(os.path.abspath(__file__))
        fast_reboot = os.path.join(test_path, '..', 'scripts', 'fast-reboot')
        with tempfile.TemporaryDirectory() as tmp_dir:
            working_script_path = os.path.join(tmp_dir, working_script)
            with open(working_script_path, 'w') as f:
                f.write('echo root')
                os.chmod(working_script_path, 0o700)
            shutil.copy('/bin/false', os.path.join(tmp_dir, failing_script))
            shutil.copy('/bin/true', os.path.join(tmp_dir, 'sonic-cfggen'))
            shutil.copy('/bin/true', os.path.join(tmp_dir, 'sonic-db-cli'))
            env = os.environ.copy()
            env['PATH'] = f"{tmp_dir}:{env.get('PATH', '')}"
            res = subprocess.run([fast_reboot, '-h'], env=env)
        assert res.returncode == 0

    def test_cpa_tunnel_check_uses_uds_and_continues_without_vxlan(self, tmp_path):
        result, commands = run_cpa_tunnel_check(
            tmp_path,
            tunnel_type="SAI_TUNNEL_TYPE_IPINIP",
            tunnel_term_type="SAI_TUNNEL_TYPE_IPINIP",
        )

        assert result.returncode == 0
        assert commands == [
            "--unixsocket ASIC_DB KEYS ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL:*",
            "--unixsocket ASIC_DB HGET ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL:oid:0x1 SAI_TUNNEL_ATTR_TYPE",
            "--unixsocket ASIC_DB KEYS ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL_TERM_TABLE_ENTRY:*",
            "--unixsocket ASIC_DB HGET "
            "ASIC_STATE:SAI_OBJECT_TYPE_TUNNEL_TERM_TABLE_ENTRY:oid:0x2 "
            "SAI_TUNNEL_TERM_TABLE_ENTRY_ATTR_TUNNEL_TYPE",
        ]

    @pytest.mark.parametrize(
        "tunnel_type,tunnel_term_type",
        [
            ("SAI_TUNNEL_TYPE_VXLAN", ""),
            ("", "SAI_TUNNEL_TYPE_VXLAN"),
        ],
    )
    def test_cpa_tunnel_check_aborts_for_leftover_vxlan(
        self, tmp_path, tunnel_type, tunnel_term_type
    ):
        result, commands = run_cpa_tunnel_check(
            tmp_path,
            tunnel_type=tunnel_type,
            tunnel_term_type=tunnel_term_type,
        )

        assert result.returncode == 30
        assert "Device has leftover CPA tunnel configuration" in result.stderr
        assert commands
        assert all(command.startswith("--unixsocket ASIC_DB ") for command in commands)

# fast-reboot runs its main flow at the top level and cannot be sourced, so these
# tests extract the CPA functions with sed and run them against stub commands.
CPA_FUNCTIONS = ['debug', 'error', 'abort_reboot_if_cpa_tunnel_is_leftover', 'setup_control_plane_assistant']

# KEYS returns one object of the requested type when FAKE_VXLAN_TUNNEL=yes; HGET reports it as VxLAN.
SONIC_DB_CLI_STUB = '''#!/bin/bash
if [[ "$3" == "KEYS" && "${FAKE_VXLAN_TUNNEL}" == "yes" ]]; then
    echo "${4%\\*}oid:0x2a000000000001"
elif [[ "$3" == "HGET" ]]; then
    echo "SAI_TUNNEL_TYPE_VXLAN"
fi
'''

ASSISTANT_STUB = '''#!/bin/bash
echo "assistant $*" >> "${CALL_LOG}"
'''


def run_setup_control_plane_assistant(tmp_path, vxlan_tunnel, assistant_ip_list, hwsku='Force10-S6000'):
    for name, body in (('sonic-db-cli', SONIC_DB_CLI_STUB), ('neighbor_advertiser', ASSISTANT_STUB),
                       ('logger', '#!/bin/bash\n')):
        stub = tmp_path / name
        stub.write_text(body)
        stub.chmod(0o755)
    call_log = tmp_path / 'calls.log'
    call_log.touch()

    fast_reboot = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'fast-reboot')
    extract = ';'.join('/^function {}()/,/^}}/p'.format(name) for name in CPA_FUNCTIONS)
    driver = (
        f'source <(grep -E "^EXIT_[A-Z_]+=[0-9]+$" "{fast_reboot}")\n'
        f'source <(sed -n \'{extract}\' "{fast_reboot}")\n'
        f'for f in {" ".join(CPA_FUNCTIONS)}; do declare -F $f > /dev/null || exit 99; done\n'
        'check_mirror_session_acls() { echo "check_mirror_session_acls" >> "${CALL_LOG}"; }\n'
        'setup_control_plane_assistant\n'
    )
    env = os.environ.copy()
    env.update({
        'PATH': f"{tmp_path}:{env.get('PATH', '')}",
        'FAKE_VXLAN_TUNNEL': 'yes' if vxlan_tunnel else 'no',
        'ASSISTANT_IP_LIST': assistant_ip_list,
        'ASSISTANT_SCRIPT': str(tmp_path / 'neighbor_advertiser'),
        'HWSKU': hwsku,
        'CALL_LOG': str(call_log),
    })
    res = subprocess.run(['bash', '-e', '-c', driver], env=env, capture_output=True, text=True)
    assert res.returncode != 99, 'functions not extracted from fast-reboot: {}'.format(res.stderr)
    return res, call_log.read_text().splitlines()


class TestControlPlaneAssistantLeftoverTunnel:
    def test_vxlan_tunnel_without_cpa_does_not_abort(self, tmp_path):
        res, calls = run_setup_control_plane_assistant(tmp_path, vxlan_tunnel=True, assistant_ip_list='')
        assert res.returncode == 0, res.stderr
        assert calls == []

    def test_vxlan_tunnel_on_cpa_incapable_hwsku_does_not_abort(self, tmp_path):
        res, calls = run_setup_control_plane_assistant(
            tmp_path, vxlan_tunnel=True, assistant_ip_list='10.0.0.1', hwsku='DellEMC-Z9332f-M-O16C64')
        assert res.returncode == 0, res.stderr
        assert calls == []

    def test_leftover_tunnel_with_cpa_aborts(self, tmp_path):
        res, calls = run_setup_control_plane_assistant(tmp_path, vxlan_tunnel=True, assistant_ip_list='10.0.0.1')
        assert res.returncode == 30
        assert 'leftover CPA tunnel' in res.stderr
        assert calls == []

    def test_no_tunnel_with_cpa_sets_up_assistant(self, tmp_path):
        res, calls = run_setup_control_plane_assistant(tmp_path, vxlan_tunnel=False, assistant_ip_list='10.0.0.1')
        assert res.returncode == 0, res.stderr
        assert calls == ['assistant -s 10.0.0.1 -m set', 'check_mirror_session_acls']
<<<<<<< HEAD
=======

    @pytest.mark.parametrize("stp_mode", ["pvst", "mst"])
    @pytest.mark.parametrize("reboot_type", ["warm-reboot", "fast-reboot"])
    def test_reboot_refused_with_spanning_tree_configured(self, stp_mode, reboot_type):
        result = run_spanning_tree_check(stp_mode, reboot_type)

        assert result.returncode == 2
        assert "reboot continues" not in result.stdout
        assert f"mode {stp_mode}" in result.stderr
        assert f"{reboot_type} is not supported" in result.stderr
        assert "cold reboot" in result.stderr

    def test_reboot_continues_without_spanning_tree(self):
        result = run_spanning_tree_check("")

        assert result.returncode == 0
        assert "reboot continues" in result.stdout
        assert result.stderr == ""

    def test_spanning_tree_check_runs_before_the_reboot_is_armed(self):
        lines = FAST_REBOOT.read_text().splitlines()
        check = lines.index("abort_reboot_if_spanning_tree_is_configured")
        armed = next(i for i, line in enumerate(lines) if line.startswith('case "$REBOOT_TYPE" in'))

        assert check < armed


# stop_service picks a stop path from the FEATURE row's scope fields, so these tests extract it
# with its two scope helpers and record which path ran.
SCOPE_FUNCTIONS = ['is_asic_service', 'is_global_service', 'stop_service']

SCOPE_DB_CLI_STUB = '''#!/bin/bash
if [[ "$2" == "hget" ]]; then
    case "$4" in
        has_global_scope) printf '%s' "${HAS_GLOBAL_SCOPE}" ;;
        has_per_asic_scope) printf '%s' "${HAS_PER_ASIC_SCOPE}" ;;
    esac
elif [[ "$2" == "exists" ]]; then
    printf '%s' "${ROW_EXISTS}"
fi
'''


def run_stop_service(tmp_path, has_global_scope='', has_per_asic_scope='', row_exists='1'):
    stub = tmp_path / 'sonic-db-cli'
    stub.write_text(SCOPE_DB_CLI_STUB)
    stub.chmod(0o755)
    call_log = tmp_path / 'calls.log'
    call_log.touch()

    fast_reboot = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts', 'fast-reboot')
    extract = ';'.join('/^function {}()/,/^}}/p'.format(name) for name in SCOPE_FUNCTIONS)
    driver = (
        f'source <(sed -n \'{extract}\' "{fast_reboot}")\n'
        f'for f in {" ".join(SCOPE_FUNCTIONS)}; do declare -F $f > /dev/null || exit 99; done\n'  # noqa: E702
        'stop_systemd_service() { echo "stop_systemd_service $*" >> "${CALL_LOG}"; }\n'
        'execute_in_namespaces() { echo "execute_in_namespaces $*" >> "${CALL_LOG}"; }\n'
        'stop_service swss\n'
    )
    env = os.environ.copy()
    env.update({
        'PATH': f"{tmp_path}:{env.get('PATH', '')}",
        'HAS_GLOBAL_SCOPE': has_global_scope,
        'HAS_PER_ASIC_SCOPE': has_per_asic_scope,
        'ROW_EXISTS': row_exists,
        'CALL_LOG': str(call_log),
    })
    # No errexit: fast-reboot turns it off before the shutdown loop that calls stop_service.
    res = subprocess.run(['bash', '-c', driver], env=env, capture_output=True, text=True)
    assert res.returncode != 99, 'functions not extracted from fast-reboot: {}'.format(res.stderr)
    return res, call_log.read_text().splitlines()


class TestStopServiceScope:
    def test_row_without_scope_fields_is_stopped(self, tmp_path):
        res, calls = run_stop_service(tmp_path)
        assert res.returncode == 0, res.stderr
        assert calls == ['stop_systemd_service swss']

    def test_service_without_a_feature_row_is_left_alone(self, tmp_path):
        """A service listed for shutdown but absent from FEATURE is not a feature, so it is skipped.

        The shutdown order file is static and can name a service with no FEATURE row at all.
        Reading that as global scope would stop a service the unpatched script leaves running,
        so the absent-field default is deliberately confined to rows that exist.
        """
        res, calls = run_stop_service(tmp_path, row_exists='0')
        assert res.returncode == 0, res.stderr
        assert calls == []

    @pytest.mark.parametrize('has_global_scope', ['True', 'true', 'TRUE'])
    def test_global_scope_is_stopped_whatever_the_case(self, tmp_path, has_global_scope):
        res, calls = run_stop_service(tmp_path, has_global_scope=has_global_scope)
        assert res.returncode == 0, res.stderr
        assert calls == ['stop_systemd_service swss']

    def test_explicit_false_global_scope_is_not_stopped(self, tmp_path):
        res, calls = run_stop_service(tmp_path, has_global_scope='False')
        assert res.returncode == 0, res.stderr
        assert calls == []

    def test_per_asic_scope_alone_stops_in_asic_namespaces(self, tmp_path):
        res, calls = run_stop_service(tmp_path, has_global_scope='False', has_per_asic_scope='True')
        assert res.returncode == 0, res.stderr
        assert calls == ['execute_in_namespaces asic stop_systemd_service swss']

    def test_both_scopes_stop_in_all_namespaces(self, tmp_path):
        res, calls = run_stop_service(tmp_path, has_global_scope='True', has_per_asic_scope='True')
        assert res.returncode == 0, res.stderr
        assert calls == ['execute_in_namespaces all stop_systemd_service swss']
>>>>>>> baccfdea (NOS-15456: [fast-reboot] Read an absent FEATURE scope field as its default (#1428))
