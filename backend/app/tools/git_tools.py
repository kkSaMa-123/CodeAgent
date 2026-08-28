"""生成工作区累计 Git diff。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.agent.context import truncate_text
from app.tools.base import ToolArguments, ToolContext, ToolResult
from app.tools.paths import resolve_workspace_path


def _git(workspace: Path, *arguments: str, accepted_codes: tuple[int, ...] = (0,)) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode not in accepted_codes:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


class GitDiffArguments(ToolArguments):
    path: str = "."


class GitDiffTool:
    name = "git_diff"
    description = "显示本次工作区中已跟踪修改和未跟踪新文件的累计 unified diff。"
    arguments_model = GitDiffArguments

    async def execute(self, arguments: ToolArguments, context: ToolContext) -> ToolResult:
        parsed = GitDiffArguments.model_validate(arguments)
        target = resolve_workspace_path(context.workspace, parsed.path)
        relative = target.relative_to(context.workspace).as_posix() or "."
        try:
            repository_root = Path(
                _git(context.workspace, "rev-parse", "--show-toplevel").strip()
            ).resolve()
            if repository_root != context.workspace:
                return ToolResult.error(
                    "git_repository_outside_workspace",
                    "Git 仓库根目录不能位于会话工作区之外",
                )
            tracked_diff = _git(
                context.workspace,
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--relative",
                "--",
                relative,
            )
            untracked_output = _git(
                context.workspace,
                "ls-files",
                "--others",
                "--exclude-standard",
                "--",
                relative,
            )
            untracked_files = tuple(line for line in untracked_output.splitlines() if line)
            untracked_diffs = []
            for untracked in untracked_files:
                resolve_workspace_path(context.workspace, untracked)
                untracked_diffs.append(
                    _git(
                        context.workspace,
                        "diff",
                        "--no-index",
                        "--no-color",
                        "--",
                        "/dev/null",
                        untracked,
                        accepted_codes=(0, 1),
                    )
                )
        except (OSError, RuntimeError) as exc:
            return ToolResult.error("git_error", "无法生成 Git diff", output=str(exc))

        complete_diff = tracked_diff + "".join(untracked_diffs)
        limited_diff = truncate_text(complete_diff, context.output_limit)
        return ToolResult.success(
            "已生成工作区累计 diff",
            output=limited_diff,
            metadata={
                "path": relative,
                "untracked_files": untracked_files,
                "truncated": limited_diff != complete_diff,
            },
        )
