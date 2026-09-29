"""
Tests for CLI prompt configuration commands.
"""

import os
import subprocess
import sys
from unittest import mock

import click
import pytest
from click.testing import CliRunner

import config.main as config
import show.main as show
import utilities_common.cli as clicommon
from utilities_common.db import Db

test_path = os.path.dirname(os.path.abspath(__file__))

# Valid prompt components
VALID_PROMPT_COMPONENTS = ['user', 'host', 'fqdn', 'time', 'date', 'dir']

INVALID_PROMPT_COMPONENTS = ['invalid-component', 'path', 'hostname', '']


class TestCli(object):
    """Test class for CLI configuration commands."""

    config_cli_prompt = config.config.commands["cli"].commands["prompt"]
    config_cli_prompt_format = config.config.commands["cli"].commands["prompt"].commands["format"]
    config_cli_prompt_reset = config.config.commands["cli"].commands["prompt"].commands["reset"]
    show_cli = show.cli.commands["cli"]
    show_cli_prompt = show.cli.commands["cli"].commands["prompt"]

    @classmethod
    def setup_class(cls):
        print("SETUP")
        os.environ["UTILITIES_UNIT_TESTING"] = "1"

    @classmethod
    def teardown_class(cls):
        os.environ['UTILITIES_UNIT_TESTING'] = "0"
        print("TEARDOWN")

    def test_cli_config_prompt_format_valid(self):
        """Test setting CLI prompt with valid components."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # config cli prompt format user host dir
        result = runner.invoke(self.config_cli_prompt_format, ['user', 'host', 'dir'], obj=obj)
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert "CLI prompt set to:" in result.output

        # Verify in database
        cli_table = db.cfgdb.get_entry('CLI', 'default')
        assert cli_table.get('prompt-format') == 'user,host,dir'

    def test_cli_config_prompt_format_with_time(self):
        """Test setting CLI prompt with time component."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # config cli prompt format time user host dir
        result = runner.invoke(self.config_cli_prompt_format, ['time', 'user', 'host', 'dir'], obj=obj)
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert "CLI prompt set to:" in result.output

        # Verify in database
        cli_table = db.cfgdb.get_entry('CLI', 'default')
        assert cli_table.get('prompt-format') == 'time,user,host,dir'

    def test_cli_config_prompt_format_invalid(self):
        """Test setting CLI prompt with invalid component."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # config cli prompt format invalid-component
        result = runner.invoke(self.config_cli_prompt_format, ['invalid-component'], obj=obj)
        print(result.exit_code, result.output)
        # Click should reject invalid choices
        assert result.exit_code != 0

    def test_cli_config_prompt_format_duplicate_components(self):
        """Test setting CLI prompt with duplicate components."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # config cli prompt format user user host dir (duplicate 'user')
        result = runner.invoke(self.config_cli_prompt_format, ['user', 'user', 'host', 'dir'], obj=obj)
        print(result.exit_code, result.output)
        assert "Duplicate components not allowed" in result.output

    def test_cli_config_prompt_format_host_fqdn_mutual_exclusion(self):
        """Test setting CLI prompt with both host and fqdn (mutually exclusive)."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # config cli prompt format user host fqdn dir (host and fqdn are mutually exclusive)
        result = runner.invoke(self.config_cli_prompt_format, ['user', 'host', 'fqdn', 'dir'], obj=obj)
        print(result.exit_code, result.output)
        assert "mutually exclusive" in result.output

    def test_cli_config_prompt_reset(self):
        """Test resetting CLI prompt to default."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # First set a custom prompt
        result = runner.invoke(self.config_cli_prompt_format, ['time', 'user', 'fqdn', 'dir'], obj=obj)
        assert result.exit_code == 0

        # Reset to default
        result = runner.invoke(self.config_cli_prompt_reset, [], obj=obj)
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert "reset to default" in result.output

        # Verify prompt-format is removed from database
        cli_table = db.cfgdb.get_entry('CLI', 'default')
        assert 'prompt-format' not in cli_table

    def test_cli_show_prompt_default(self):
        """Test show cli prompt with default configuration."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # show cli prompt
        result = runner.invoke(self.show_cli_prompt, [], obj=obj)
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        # Should show default prompt format
        assert "System Default" in result.output

    def test_cli_show_prompt_after_config(self):
        """Test show cli prompt after setting configuration."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # Set prompt to time user host dir
        result = runner.invoke(self.config_cli_prompt_format, ['time', 'user', 'host', 'dir'], obj=obj)
        assert result.exit_code == 0

        # show cli prompt
        result = runner.invoke(self.show_cli_prompt, [], obj=obj)
        print(result.exit_code, result.output)
        assert result.exit_code == 0
        assert "time" in result.output
        assert "user" in result.output
        assert "host" in result.output
        assert "dir" in result.output

    def test_cli_show_group(self):
        """Test show cli group command."""
        db = Db()
        runner = CliRunner()
        obj = {'db': db.cfgdb}

        # show cli (should show help or subcommands)
        result = runner.invoke(self.show_cli, [], obj=obj)
        print(result.exit_code, result.output)
        # Group command should show help
        assert result.exit_code == 0


# What the chatty child prints: about 350 KB, a few times what the pipes between it, the
# relay and the reader can hold, so it is still writing when the reader goes away, yet
# little enough that a stopped child's leftover output drains well inside the helper's
# drain budget even on a loaded CI runner.
_CHATTY_CHILD = "for i in range(30000): print('line', i)"

# A show-shaped parent for the pipeline tests below: a Click command that relays a chatty
# child with the helper under test. It runs as its own process so that Click's real EPIPE
# handling is in the loop, exactly as it is for `show`.
_RELAY_PARENT = """
import shlex, subprocess, sys
import click
import utilities_common.cli as clicommon

CHILD = {child!r}

@click.command()
@click.option("--shell", "use_shell", is_flag=True)
def main(use_shell):
    argv = [sys.executable, "-c", CHILD]
    cmd = " ".join(shlex.quote(a) for a in argv) if use_shell else argv
    proc = subprocess.Popen(cmd, shell=use_shell, text=True, stdout=subprocess.PIPE)
    clicommon.echo_child_output(proc)

main()
""".format(child=_CHATTY_CHILD)


def _chatty_child():
    """A child that prints far more than a pipe buffer holds and has no EPIPE handling."""
    return subprocess.Popen([sys.executable, "-c", _CHATTY_CHILD],
                            stdout=subprocess.PIPE, text=True)


class TestEchoChildOutput(object):
    """The relay helpers behind `show ... | head`.

    Contract: output is relayed until the child exits; if our own reader goes away first,
    the child is stopped and its leftover output read out, so nothing writes into the
    closed pipe and nothing lands on stderr, and the BrokenPipeError is re-raised for Click.
    """

    def test_relays_until_child_exits(self):
        @click.command()
        def relay():
            proc = subprocess.Popen([sys.executable, "-c", "print('a'); print('b')"],
                                    stdout=subprocess.PIPE, text=True)
            clicommon.echo_child_output(proc)
            assert proc.poll() == 0

        result = CliRunner().invoke(relay)
        assert result.exit_code == 0, result.output
        assert result.output == "a\nb\n"

    def test_stops_child_when_reader_goes_away(self):
        proc = _chatty_child()
        try:
            with mock.patch("click.echo", side_effect=BrokenPipeError):
                with pytest.raises(BrokenPipeError):
                    clicommon.echo_child_output(proc)
            assert proc.poll() is not None, "child was left running after the reader went away"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_alias_mode_relay_stops_child_when_reader_goes_away(self):
        proc = _chatty_child()
        try:
            with mock.patch("click.echo", side_effect=BrokenPipeError):
                with pytest.raises(BrokenPipeError):
                    clicommon._echo_output_in_alias_mode(proc, "some-helper")
            assert proc.poll() is not None, "child was left running after the reader went away"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    @pytest.mark.parametrize("use_shell", [False, True], ids=["direct", "shell"])
    def test_pipeline_leaves_nothing_on_stderr(self, use_shell):
        """The real thing: a Click parent relaying a chatty child into a reader that closes
        early. Exit status 1 comes from Click's own EPIPE handling; stderr must stay empty,
        also with shell=True where the signal reaches only the shell and the grandchild's
        leftover output has to be read out instead."""
        repo_root = os.path.dirname(test_path)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([repo_root] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        args = [sys.executable, "-c", _RELAY_PARENT] + (["--shell"] if use_shell else [])
        proc = subprocess.Popen(args, cwd=repo_root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Behave like `head`: take a little output, then close the pipe while the child is
        # still writing.
        for _ in range(2):
            assert proc.stdout.readline().startswith("line ")
        proc.stdout.close()
        try:
            _, err = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            pytest.fail("relay parent or its child still held stderr 60s after the reader closed")
        rc = proc.returncode
        assert rc == 1, "relay parent exited {} after its reader closed (expected 1):\n{}".format(rc, err)
        assert err == "", "output on stderr after the reader closed:\n{}".format(err)
