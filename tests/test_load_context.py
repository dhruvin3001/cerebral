from unittest.mock import MagicMock
from main import _do_load_context, GLOBAL_USER_ID
from memory import project_user_id


def _mk_results(*texts):
    return {"results": [{"memory": t} for t in texts]}


def _mk_mem0(global_by_type=None, project_by_type=None):
    """Mock mem0 whose get_all returns memories keyed by (user_id, cerebral_type)."""
    global_by_type = global_by_type or {}
    project_by_type = project_by_type or {}
    p_uid = project_user_id("test-project")

    def get_all(filters=None):
        uid = filters.get("user_id") if filters else None
        ctype = filters.get("cerebral_type") if filters else None
        if uid == GLOBAL_USER_ID:
            if ctype is None:
                all_mems = []
                for mems in global_by_type.values():
                    all_mems.extend(mems)
                return _mk_results(*all_mems)
            return _mk_results(*global_by_type.get(ctype, []))
        if uid == p_uid:
            if ctype is None:
                all_mems = []
                for mems in project_by_type.values():
                    all_mems.extend(mems)
                return _mk_results(*all_mems)
            return _mk_results(*project_by_type.get(ctype, []))
        return _mk_results()

    mock = MagicMock()
    mock.get_all.side_effect = get_all
    return mock


def test_loads_all_warnings_no_limit():
    mem0 = _mk_mem0(
        global_by_type={"warning": [f"warning {i}" for i in range(10)]},
    )
    result = _do_load_context(mem0, "test-project")
    for i in range(10):
        assert f"warning {i}" in result


def test_loads_all_corrections_both_scopes():
    mem0 = _mk_mem0(
        global_by_type={"correction": ["global correction"]},
        project_by_type={"correction": ["project correction"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "global correction" in result
    assert "project correction" in result


def test_loads_global_preferences_not_project_preferences():
    mem0 = _mk_mem0(
        global_by_type={"preference": ["global pref"]},
        project_by_type={"preference": ["project pref - should be excluded"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "global pref" in result
    assert "project pref - should be excluded" not in result


def test_loads_project_decisions_not_global_decisions():
    mem0 = _mk_mem0(
        global_by_type={"decision": ["global decision - excluded"]},
        project_by_type={"decision": ["project decision"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert "project decision" in result
    assert "global decision - excluded" not in result


def test_excludes_facts_workarounds_patterns_from_brief():
    mem0 = _mk_mem0(
        global_by_type={
            "fact": ["a fact - lazy only"],
            "workaround": ["a workaround - lazy only"],
            "pattern": ["a pattern - lazy only"],
        },
        project_by_type={
            "fact": ["project fact - lazy only"],
            "workaround": ["project workaround - lazy only"],
            "pattern": ["project pattern - lazy only"],
        },
    )
    result = _do_load_context(mem0, "test-project")
    assert "lazy only" not in result


def test_no_memories_returns_empty_brief_message():
    mem0 = _mk_mem0()
    result = _do_load_context(mem0, "test-project")
    assert "No memories found" in result


def test_deduplicates_repeated_memories():
    mem0 = _mk_mem0(
        global_by_type={"warning": ["dup warning", "dup warning", "unique warning"]},
    )
    result = _do_load_context(mem0, "test-project")
    assert result.count("dup warning") == 1
    assert "unique warning" in result


def test_brief_uses_get_all_not_search():
    mem0 = _mk_mem0(global_by_type={"warning": ["w"]})
    _do_load_context(mem0, "test-project")
    mem0.get_all.assert_called()
    mem0.search.assert_not_called()
