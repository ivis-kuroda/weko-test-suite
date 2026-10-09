import copy

import check_log_rule as rule
import log_expect as le

HANDLER = le.handler_expectation([le.Variant("1301", 400)], "OP-SWORD-POST")


def _case(**change):
    data = {
        "id": "TC-X",
        "expect": [{"kind": "http_status", "status": 400}, copy.deepcopy(HANDLER)],
        "evidence": {"sources": ["app_log"], "ignore": [".*"]},
        "tags": ["log:handler-line"],
    }
    data.update(change)
    return data


def _problems(data):
    return rule.check_entity(None, data)


def test_a_conforming_case_has_no_problem():
    assert _problems(_case()) == []


def test_an_ignore_other_than_the_presence_only_pattern_is_refused():
    data = _case()
    data["evidence"]["ignore"] = ["(WARNING|ERROR).*1301"]
    assert any("evidence.ignore must be exactly" in p for p in _problems(data))
    data["evidence"]["ignore"] = []
    assert any("evidence.ignore must be exactly" in p for p in _problems(data))


def test_the_tag_must_agree_with_the_expectations():
    assert any(
        "asserts no handler line" in p
        for p in _problems(_case(expect=[{"kind": "http_status", "status": 400}]))
    )
    assert any("asserts a handler line" in p for p in _problems(_case(tags=["log:not-judged"])))
    assert any("exactly one of" in p for p in _problems(_case(tags=[])))


def test_the_level_must_fit_the_status():
    data = _case()
    data["expect"][1]["assert"]["pattern"] = data["expect"][1]["assert"]["pattern"].replace(
        "WARNING", "ERROR"
    )
    assert any("do not fit" in p for p in _problems(data))


def test_the_log_must_be_read_since_the_run_started():
    data = _case()
    data["expect"][1]["params"]["since"] = "2026-01-01T00:00:00Z"
    assert any("since" in p for p in _problems(data))


def test_scenarios_are_checked_per_step():
    step = {"id": "S-1", "expect": [{"kind": "http_status", "status": 404}, copy.deepcopy(HANDLER)]}
    scenario = {
        "id": "SC-X",
        "steps": [step],
        "evidence": {"sources": ["app_log"], "ignore": [".*"]},
        "tags": ["log:handler-line"],
    }
    assert _problems(scenario) == []
    step["expect"][1]["assert"]["pattern"] = step["expect"][1]["assert"]["pattern"].replace(
        "WARNING", "ERROR"
    )
    assert any(p.startswith("SC-X/S-1:") and "do not fit" in p for p in _problems(scenario))


def test_an_entity_without_the_app_log_channel_is_out_of_scope():
    assert _problems({"id": "TC-Y", "evidence": {"sources": ["db_records"]}}) == []


def test_main_checks_a_tree(tmp_path, capsys):
    import yaml

    (tmp_path / "cases").mkdir()
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "cases" / "TC-X.yaml").write_text(yaml.safe_dump(_case()), encoding="utf-8")
    assert rule.main([str(tmp_path)]) == 0
    bad = _case()
    bad["evidence"]["ignore"] = ["ERROR"]
    (tmp_path / "cases" / "TC-X.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    assert rule.main([str(tmp_path)]) == 1
    assert rule.main([str(tmp_path / "missing")]) == 2
