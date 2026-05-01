import json
from pathlib import Path
from unittest.mock import patch
import pytest
from project import get_project_id


def test_reads_cerebral_config_file(tmp_path):
    config = tmp_path / ".cerebral"
    config.write_text(json.dumps({"project_id": "my-project"}))
    assert get_project_id(str(tmp_path)) == "my-project"


def test_falls_back_to_git_remote(tmp_path):
    with patch("project._get_git_remote", return_value="https://github.com/dhruvin3001/drobe.git"):
        assert get_project_id(str(tmp_path)) == "github.com/dhruvin3001/drobe"


def test_falls_back_to_folder_name(tmp_path):
    with patch("project._get_git_remote", return_value=None):
        assert get_project_id(str(tmp_path)) == tmp_path.name


def test_env_var_overrides_all(tmp_path, monkeypatch):
    monkeypatch.setenv("CEREBRAL_PROJECT", "forced-project")
    assert get_project_id(str(tmp_path)) == "forced-project"


def test_sanitizes_ssh_git_remote(tmp_path):
    with patch("project._get_git_remote", return_value="git@github.com:dhruvin3001/drobe.git"):
        assert get_project_id(str(tmp_path)) == "github.com/dhruvin3001/drobe"
