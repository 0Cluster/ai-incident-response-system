import pytest

from app.automation.actions.script import ScriptAction


def test_script_rejects_shell_metachars():
    with pytest.raises(ValueError):
        ScriptAction(action_name="script", script_path="run.sh; rm -rf /")


def test_script_rejects_empty():
    with pytest.raises(ValueError):
        ScriptAction(action_name="script", script_path="  ")
