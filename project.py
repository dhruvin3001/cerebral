import json
import os
import re
import subprocess
from pathlib import Path


def get_project_id(cwd: str) -> str:
    if override := os.getenv("CEREBRAL_PROJECT"):
        return override

    config_path = _find_up(".cerebral", cwd)
    if config_path:
        data = json.loads(Path(config_path).read_text())
        if project_id := data.get("project_id"):
            return project_id

    remote = _get_git_remote(cwd)
    if remote:
        return _sanitize_remote(remote)

    return Path(cwd).name


def _find_up(filename: str, start: str) -> str | None:
    current = Path(start).resolve()
    while True:
        candidate = current / filename
        if candidate.exists():
            return str(candidate)
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _get_git_remote(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _sanitize_remote(remote: str) -> str:
    remote = re.sub(r"^git@([^:]+):", r"\1/", remote)
    remote = re.sub(r"^https?://", "", remote)
    remote = re.sub(r"\.git$", "", remote)
    return remote.strip("/")
