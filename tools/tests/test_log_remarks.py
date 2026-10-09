import json
from pathlib import Path

import a5_scan


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


DIFF = "--- before\n+++ after\n@@ -0,0 +1,2 @@\n+t ERROR s: boom\n+t WARNING s: [1303] x\n"


def test_error_before_4xx_is_reported(tmp_path):
    _write_run(tmp_path, 400, DIFF)
    findings = a5_scan.scan(tmp_path)
    assert [f["entity"] for f in findings] == ["TC-X"]
    assert findings[0]["status_4xx"] == [400]
    assert findings[0]["error_lines"] == ["t ERROR s: boom"]
    assert "on hold (A-5)" in a5_scan.remark(findings[0])


def test_error_with_a_success_response_is_not_a5(tmp_path):
    _write_run(tmp_path, 201, DIFF)
    assert a5_scan.scan(tmp_path) == []


def test_expected_5xx_error_lines_are_skipped(tmp_path):
    _write_run(tmp_path, 400, "+++ after\n+t ERROR s: Traceback (most recent call last)\n")
    assert a5_scan.scan(tmp_path) == []


def test_main_exit_codes(tmp_path, capsys):
    _write_run(tmp_path, 400, DIFF)
    assert a5_scan.main([str(tmp_path)]) == 0
    assert a5_scan.main([str(tmp_path), "--strict"]) == 1
    assert a5_scan.main([str(tmp_path / "missing")]) == 2
