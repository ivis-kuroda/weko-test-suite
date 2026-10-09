import json
from pathlib import Path

import log_remarks


def _write_run(root: Path, status: int, diff: str) -> Path:
    run = root / "run1"
    loc = run / "TC-X" / "case"
    loc.mkdir(parents=True)
    (loc / "during-network-http-OP.json").write_text(
        json.dumps({"response": {"status": status}}), encoding="utf-8"
    )
    (loc / "diff-app-log-OP.diff").write_text(diff, encoding="utf-8")
    entries = [
        {
            "entity": "TC-X",
            "source": "http_exchange",
            "role": "capture",
            "path": "TC-X/case/during-network-http-OP.json",
        },
        {
            "entity": "TC-X",
            "source": "app_log",
            "role": "diff",
            "path": "TC-X/case/diff-app-log-OP.diff",
        },
    ]
    (run / "index.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return run


DIFF = (
    "--- before\n+++ after\n@@ -0,0 +1,2 @@\n"
    "+t ERROR s: boom\n+t WARNING s: [1303] POST /sword/x: m\n"
)


def test_error_line_with_a_4xx_is_a_remark_and_an_a5_candidate(tmp_path):
    _write_run(tmp_path, 400, DIFF)
    found = log_remarks.scan(tmp_path)
    assert [f["entity"] for f in found] == ["TC-X"]
    assert found[0]["statuses"] == [400]
    assert found[0]["error_lines"] == ["t ERROR s: boom"]
    assert found[0]["a5_candidate"] is True
    text = log_remarks.remark(found[0])
    assert "not part of the verdict" in text and "A-5 candidate" in text


def test_error_line_with_a_success_response_is_a_remark_but_not_a5(tmp_path):
    _write_run(tmp_path, 201, DIFF)
    found = log_remarks.scan(tmp_path)
    assert found[0]["a5_candidate"] is False
    assert "A-5" not in log_remarks.remark(found[0])


def test_the_expected_5xx_handler_line_is_not_reported_but_its_trace_is_counted(tmp_path):
    diff = (
        "+++ after\n"
        "+t ERROR s: [3108] GET /sword/deposit/9: Failed\n"
        "+Traceback (most recent call last):\n"
    )
    _write_run(tmp_path, 503, diff)
    found = log_remarks.scan(tmp_path)
    assert found[0]["error_lines"] == []
    assert found[0]["traces"] == 1


def test_a_clean_log_has_no_remark(tmp_path):
    _write_run(tmp_path, 400, "+++ after\n+t WARNING s: [1303] POST /sword/x: m\n")
    assert log_remarks.scan(tmp_path) == []


def test_main_exit_codes(tmp_path):
    _write_run(tmp_path, 400, DIFF)
    assert log_remarks.main([str(tmp_path)]) == 0
    assert log_remarks.main([str(tmp_path), "--strict"]) == 1
    assert log_remarks.main([str(tmp_path / "missing")]) == 2
