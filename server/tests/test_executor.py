"""Tests for executor.py."""

from subprocess import CompletedProcess

import pytest

from server.executor import (
    CONNECT_TIMEOUT_SECONDS,
    KNOWN_HOSTS_PATH,
    _wrap_for_ssh,
    execute,
)
from server.whitelist import CommandSpec, SshTarget


def spec(argv, cwd=None, env=None, timeout=10, ssh=None):
    return CommandSpec(
        id="t",
        name="t",
        description="t",
        argv=argv,
        cwd=cwd,
        env=env or {},
        timeout_seconds=timeout,
        ssh=ssh,
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


# ---- ssh-wrap --------------------------------------------------------------


def _ssh_target() -> SshTarget:
    return SshTarget(
        host="localhost",
        user="root",
        key_path="/etc/panel/ssh/test.ed25519",
    )


def test_wrap_for_ssh_basic_shape():
    wrapped = _wrap_for_ssh(spec(["/usr/local/bin/sim24", "book"]), _ssh_target())
    # ssh -i KEY -o ... -l USER HOST -- ARGV...
    assert wrapped[0] == "ssh"
    assert wrapped[wrapped.index("-i") + 1] == "/etc/panel/ssh/test.ed25519"
    assert wrapped[wrapped.index("-l") + 1] == "root"
    # "host" appears twice: once in -l user@host form is NOT used; we use
    # -l + target.host. Verify it appears after -l.
    assert "localhost" in wrapped
    assert "--" in wrapped
    # Original argv is preserved verbatim after --.
    sep = wrapped.index("--")
    assert wrapped[sep + 1:] == ["/usr/local/bin/sim24", "book"]


def test_wrap_for_ssh_includes_security_options():
    wrapped = _wrap_for_ssh(spec(["/bin/true"]), _ssh_target())
    # The wrap uses `-o KEY=VAL` (single token). Reconstruct that dict
    # from the argv by walking the list.
    opts: dict[str, str] = {}
    i = 0
    while i < len(wrapped):
        if wrapped[i] == "-o" and i + 1 < len(wrapped):
            kv = wrapped[i + 1]
            if "=" in kv:
                k, v = kv.split("=", 1)
                opts[k] = v
            i += 2
        else:
            i += 1
    assert opts["BatchMode"] == "yes"
    assert opts["StrictHostKeyChecking"] == "yes"
    assert opts["UserKnownHostsFile"] == KNOWN_HOSTS_PATH
    assert opts["LogLevel"] == "ERROR"
    assert opts["ConnectTimeout"] == str(CONNECT_TIMEOUT_SECONDS)


def test_wrap_for_ssh_env_forwarding():
    wrapped = _wrap_for_ssh(
        spec(["/usr/local/bin/sim24", "book"], env={"X": "42", "Y": "hello"}),
        _ssh_target(),
    )
    sep = wrapped.index("--")
    remote = wrapped[sep + 1:]
    # Env vars appear first as KEY=VAL prefix.
    assert remote[0] == "X=42"
    assert remote[1] == "Y=hello"
    assert remote[2:] == ["/usr/local/bin/sim24", "book"]


def test_wrap_for_ssh_cwd_forwarding():
    wrapped = _wrap_for_ssh(
        spec(["/usr/local/bin/sim24", "book"], cwd="/etc/sim24"),
        _ssh_target(),
    )
    sep = wrapped.index("--")
    remote = wrapped[sep + 1:]
    assert remote == ["cd", "/etc/sim24", "&&", "/usr/local/bin/sim24", "book"]


def test_wrap_for_ssh_combined_env_and_cwd():
    wrapped = _wrap_for_ssh(
        spec(["/bin/true"], env={"A": "1"}, cwd="/tmp"),
        _ssh_target(),
    )
    sep = wrapped.index("--")
    remote = wrapped[sep + 1:]
    assert remote == ["A=1", "cd", "/tmp", "&&", "/bin/true"]


def test_execute_ssh_uses_wrapped_argv(monkeypatch):
    """execute() with ssh_target wraps argv before calling subprocess.run."""
    import server.executor as exec_mod

    captured = {}

    def fake_run(*args, **kwargs):
        argv = kwargs.get("args")
        if argv is None and args:
            argv = args[0]
        captured["argv"] = argv
        captured["cwd"] = kwargs.get("cwd")
        captured["shell"] = kwargs.get("shell")
        captured["timeout"] = kwargs.get("timeout")
        return CompletedProcess(args=argv or [], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(exec_mod.subprocess, "run", fake_run)

    target = _ssh_target()
    execute(
        spec(["/usr/local/bin/sim24", "book"], timeout=42),
        ssh_target=target,
    )
    assert captured["argv"][0] == "ssh"
    assert "--" in captured["argv"]
    # Local cwd is dropped; the remote shell prefix sets the cwd.
    assert captured["cwd"] is None
    # Still no shell.
    assert captured["shell"] is False
    # Spec timeout is honored.
    assert captured["timeout"] == 42


def test_execute_ssh_preserves_returncode(monkeypatch):
    """A non-zero exit on the remote side is propagated as a non-zero exit_code."""
    import server.executor as exec_mod

    def fake_run(*args, **kwargs):
        argv = kwargs.get("args") or (args[0] if args else [])
        return CompletedProcess(args=argv, returncode=42, stdout="oops", stderr="")

    monkeypatch.setattr(exec_mod.subprocess, "run", fake_run)
    result = execute(spec(["/bin/true"]), ssh_target=_ssh_target())
    assert result.exit_code == 42
    assert result.stdout == "oops"
    assert result.timed_out is False


def test_execute_local_when_no_ssh(monkeypatch):
    """No ssh_target → subprocess.run gets the local argv unchanged."""
    import server.executor as exec_mod

    captured = {}

    def fake_run(*args, **kwargs):
        argv = kwargs.get("args") or (args[0] if args else [])
        captured["argv"] = argv
        return CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(exec_mod.subprocess, "run", fake_run)
    execute(spec(["/bin/echo", "hi"]))
    assert captured["argv"] == ["/bin/echo", "hi"]


def test_execute_ssh_missing_binary_raises():
    """If the SSH-wrapped argv's first element (`ssh`) isn't on disk, propagate FileNotFoundError.

    We force this by monkeypatching the executor's known ssh path; on
    any sane Linux install /usr/bin/ssh exists, so we point PATH at an
    empty dir for this test.
    """
    import os
    import tempfile

    empty = tempfile.mkdtemp()
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = empty
    try:
        with pytest.raises(FileNotFoundError):
            execute(spec(["/bin/true"]), ssh_target=_ssh_target())
    finally:
        os.environ["PATH"] = old_path