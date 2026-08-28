from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import sys
from pathlib import Path

from app.tools.base import ToolContext
from app.tools.command import RunCommandArguments, RunCommandTool, execute_command


def context(workspace: Path, cancelled=lambda: False, output_limit: int = 20_000) -> ToolContext:
    return ToolContext("session", workspace, cancelled, output_limit)


def test_execute_command_captures_stdout_stderr_and_nonzero(tmp_path: Path) -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr); raise SystemExit(7)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"

    outcome = asyncio.run(execute_command(command, context(tmp_path), timeout_seconds=5))

    assert outcome.exit_code == 7
    assert outcome.stdout == "out\n"
    assert outcome.stderr == "err\n"


def test_run_command_success_nonzero_and_output_limit(tmp_path: Path) -> None:
    # Git 只读命令在自动允许列表内。
    os.system(f"git -C {shlex.quote(str(tmp_path))} init -q")
    tool = RunCommandTool()
    success = asyncio.run(
        tool.execute(RunCommandArguments(command="git status --short"), context(tmp_path))
    )
    nonzero = asyncio.run(
        tool.execute(
            RunCommandArguments(command="git show missing-reference"),
            context(tmp_path, output_limit=300),
        )
    )

    assert success.status == "success"
    assert json.loads(success.output)["exit_code"] == 0
    assert nonzero.error_type == "command_failed"
    assert len(nonzero.output) <= 300


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_timeout_kills_child_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    child_code = (
        f"import os,time; open({str(pid_file)!r},'w').write(str(os.getpid())); time.sleep(60)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
    )
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(parent_code)}"

    outcome = asyncio.run(execute_command(command, context(tmp_path), timeout_seconds=0.2))
    child_pid = int(pid_file.read_text())

    assert outcome.timed_out is True
    assert not _process_exists(child_pid)


def test_cancellation_kills_active_process(tmp_path: Path) -> None:
    cancelled = False

    async def scenario():
        nonlocal cancelled
        command = f"{shlex.quote(sys.executable)} -c {shlex.quote('import time; time.sleep(60)')}"
        running = asyncio.create_task(
            execute_command(command, context(tmp_path, lambda: cancelled), timeout_seconds=10)
        )
        await asyncio.sleep(0.1)
        cancelled = True
        return await running

    outcome = asyncio.run(scenario())

    assert outcome.cancelled is True
    assert outcome.exit_code == -signal.SIGTERM
