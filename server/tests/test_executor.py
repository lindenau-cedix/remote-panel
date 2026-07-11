"""Tests for executor.py."""

import pytest

from server.executor import execute
from server.whitelist import CommandSpec


def spec(argv, cwd=None, env=None, timeout=10):
    return CommandSpec(
        id="t",
        name="t",
        description="t",
        argv=argv,
        cwd=cwd,
        env=env or {},
        timeout_seconds=timeout,
    )


def test_exec_success():
    result = execute(spec(["/bin/echo", "hello"]))
    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.duration_ms >= 0


def test_exec_failure_exit_code():
    result = execute(spec(["/bin/sh", "-c", "exit 7"]))
    assert result.exit_code == 7


def test_exec_timeout():
    # `sleep` should be available; if not, skip.
    result = execute(spec(["/bin/sleep", "5"], timeout=1))
    assert result.timed_out is True
    assert result.exit_code == 124


def test_exec_does_not_use_shell(monkeypatch):
    """Defense-in-depth: ensure subprocess.run is called with shell=False and argv stays a list."""
    import server.executor as exec_mod

    captured = {}

    def fake_run(*args, **kwargs):
        # subprocess.run(argv, ...) -> argv may be in args[0] or kwargs['args']
        argv = kwargs.get("args")
        if argv is None and args:
            argv = args[0]
        captured["argv"] = argv
        captured.update(kwargs)
        from subprocess import CompletedProcess
        return CompletedProcess(args=argv or [], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(exec_mod.subprocess, "run", fake_run)
    execute(spec(["/bin/echo", "hi"]))
    assert "shell" in captured
    assert captured["shell"] is False, "shell must be False"
    assert isinstance(captured["argv"], list), f"argv must be a list, got {type(captured['argv'])}"
    assert captured["argv"] == ["/bin/echo", "hi"]


def test_exec_no_string_command(monkeypatch):
    """Make sure we never build a string command from argv."""
    import server.executor as exec_mod

    seen = {}

    def fake_run(*args, **kwargs):
        argv = kwargs.get("args")
        if argv is None and args:
            argv = args[0]
        seen["args"] = argv
        from subprocess import CompletedProcess
        return CompletedProcess(args=argv or [], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(exec_mod.subprocess, "run", fake_run)
    execute(spec(["/bin/echo", "hi"]))
    assert isinstance(seen["args"], list), "argv must remain a list, never a string"


def test_exec_cwd_and_env():
    result = execute(
        spec(["/bin/sh", "-c", "pwd; echo X=$X"], cwd="/tmp", env={"X": "42"})
    )
    assert result.exit_code == 0
    assert "/tmp" in result.stdout
    assert "X=42" in result.stdout


def test_exec_missing_executable():
    with pytest.raises(FileNotFoundError):
        execute(spec(["/no/such/binary/xyz123"]))