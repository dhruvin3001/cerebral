import subprocess
import sys


def test_cli_save_session_exits_cleanly():
    result = subprocess.run(
        ["uv", "run", "cli.py", "save-session",
         "--summary", "User prefers pathlib over os.path for all file operations"],
        capture_output=True,
        text=True,
        cwd="/Users/dhruvin07/agent-ws/cerebral",
    )
    assert result.returncode == 0
    assert "saved" in result.stdout.lower()


def test_cli_no_summary_exits_cleanly():
    result = subprocess.run(
        ["uv", "run", "cli.py", "save-session", "--summary", "   "],
        capture_output=True,
        text=True,
        cwd="/Users/dhruvin07/agent-ws/cerebral",
    )
    assert result.returncode == 0
