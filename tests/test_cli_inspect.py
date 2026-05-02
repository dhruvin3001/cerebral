from cli import _format_inspect_table


def test_format_inspect_table_sorts_by_retrieval_count_desc():
    rows = [
        {"id": "a", "memory": "low use", "metadata": {"retrieval_count": 1, "cerebral_type": "fact"}, "user_id": "g"},
        {"id": "b", "memory": "high use", "metadata": {"retrieval_count": 10, "cerebral_type": "warning"}, "user_id": "g"},
        {"id": "c", "memory": "never", "metadata": None, "user_id": "g"},
    ]
    output = _format_inspect_table(rows)
    assert output.index("high use") < output.index("low use") < output.index("never")


def test_format_inspect_table_handles_missing_metadata():
    rows = [{"id": "a", "memory": "untouched", "metadata": None, "user_id": "g"}]
    output = _format_inspect_table(rows)
    assert "untouched" in output
    assert "0" in output


def test_format_inspect_table_truncates_long_memory_text():
    long_text = "x" * 200
    rows = [{"id": "a", "memory": long_text, "metadata": {"retrieval_count": 1}, "user_id": "g"}]
    output = _format_inspect_table(rows)
    assert "x" * 200 not in output
    assert "..." in output


def test_format_inspect_table_distinguishes_global_and_project_scope():
    rows = [
        {"id": "a", "memory": "global mem", "metadata": None, "user_id": "dhruvin"},
        {"id": "b", "memory": "project mem", "metadata": None, "user_id": "project:foo/bar"},
    ]
    output = _format_inspect_table(rows)
    assert "global" in output
    assert "project" in output
