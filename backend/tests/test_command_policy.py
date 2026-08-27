from __future__ import annotations

import pytest

from app.safety import CommandRisk, classify_command


@pytest.mark.parametrize(
    "command",
    [
        "pytest -q",
        "python -m pytest tests",
        "ruff check .",
        "npm run build",
        "git diff",
        "git status",
    ],
)
def test_allows_low_risk_validation_and_read_only_commands(command: str) -> None:
    assert classify_command(command).risk is CommandRisk.ALLOW


@pytest.mark.parametrize(
    "command",
    ["pip install httpx", "npm install vue", "rm generated.txt", "git commit -am test", "git push"],
)
def test_requires_approval_for_sensitive_changes(command: str) -> None:
    assert classify_command(command).risk is CommandRisk.APPROVAL_REQUIRED


@pytest.mark.parametrize(
    "command",
    [
        "shutdown -h now",
        "mkfs.ext4 /dev/sda",
        "dd if=/dev/zero of=/dev/disk1",
        ":(){ :|:& };:",
        "rm -rf /",
        "cat /etc/passwd",
    ],
)
def test_denies_system_destructive_or_outside_commands(command: str) -> None:
    assert classify_command(command).risk is CommandRisk.DENY
