"""The handler-line expectations: what they accept and what they must not accept."""

import re

import log_expect as le
from log_expect import Variant

POST = ("POST", "/sword/service-document")
DEPOSIT = r"/sword/deposit/[^\s:]+"


def _search(variants, method, path, log):
    return re.search(le.handler_pattern(variants, method, path), log) is not None


HANDLER_4XX = (
    "2026-10-09T01:02:03.000Z WARNING sword-stub: "
    "[1301] POST /sword/service-document: No file part."
)
FLASK_STYLE = "[2026-10-09 01:02:03,000] WARNING in views: [1301] POST /sword/service-document: x"
PRE_RAISE = "2026-10-09T01:02:03.000Z ERROR sword-stub: No file part."


def test_the_handler_line_at_warning_is_found():
    assert _search([Variant("1301", 400)], *POST, HANDLER_4XX)
    assert _search([Variant("1301", 400)], *POST, FLASK_STYLE)


def test_the_prefixed_code_is_accepted_too():
    line = "x WARNING y: [WEKO_SWORDSERVER_E_1301] POST /sword/service-document: m"
    assert _search([Variant("1301", 400)], *POST, line)


def test_a_missing_handler_line_is_not_satisfied_by_other_lines():
    noise = (
        "t ERROR s: celery task failed\nTraceback (most recent call last):\n"
        "t ERROR s: No file part.\n"
        "t INFO s: POST /sword/service-document -> 400\n"
    )
    assert not _search([Variant("1301", 400)], *POST, noise)
    assert not _search([Variant("1301", 400)], *POST, PRE_RAISE)


def test_the_level_must_match_the_status():
    wrong_level = HANDLER_4XX.replace("WARNING", "ERROR")
    assert not _search([Variant("1301", 400)], *POST, wrong_level)
    assert _search(
        [Variant("3201", 501)], *POST, "t ERROR s: [3201] POST /sword/service-document: x"
    )
    assert not _search(
        [Variant("3201", 501)], *POST, "t WARNING s: [3201] POST /sword/service-document: x"
    )


def test_code_method_and_path_must_all_match():
    assert not _search([Variant("1302", 400)], *POST, HANDLER_4XX)
    assert not _search([Variant("1301", 400)], "PUT", DEPOSIT, HANDLER_4XX)
    assert not _search([Variant("1301", 400)], "POST", "/sword/other", HANDLER_4XX)
    put = "t WARNING s: [1301] PUT /sword/deposit/900001: No file part."
    assert _search([Variant("1301", 400)], "PUT", DEPOSIT, put)


def test_bands_and_alternatives():
    band = [Variant(r"140[4-7]", 415)]
    assert _search(band, *POST, "t WARNING s: [1406] POST /sword/service-document: m")
    assert not _search(band, *POST, "t WARNING s: [1408] POST /sword/service-document: m")
    either = [Variant("1501", 400), Variant("3201", 501)]
    assert _search(either, *POST, "t WARNING s: [1501] POST /sword/service-document: m")
    assert _search(either, *POST, "t ERROR s: [3201] POST /sword/service-document: m")


def test_the_match_stays_on_one_line():
    split = "t WARNING s: other\n[1301] POST /sword/service-document: m"
    assert not _search([Variant("1301", 400)], *POST, split)


def test_a_503_needs_its_stack_trace_attached_to_the_handler_line():
    variant = [Variant("3108", 503, trace=True)]
    with_trace = (
        "t ERROR s: [3108] GET /sword/deposit/9: Failed to access the database.\n"
        "Traceback (most recent call last):\n  File x\n"
    )
    without = "t ERROR s: [3108] GET /sword/deposit/9: Failed.\nt INFO s: next line\n"
    elsewhere = without + "Traceback (most recent call last):\n"
    assert _search(variant, "GET", DEPOSIT, with_trace)
    assert not _search(variant, "GET", DEPOSIT, without)
    assert not _search(variant, "GET", DEPOSIT, elsewhere)


def test_the_expectation_reads_the_log_since_the_run_started():
    exp = le.handler_expectation([Variant("1301", 400)], "OP-SWORD-POST-NOFILE")
    assert exp["kind"] == "operation_result"
    assert exp["operation"] == "OP-APP-LOG"
    assert exp["params"] == {"since": "{{run.startedAt}}"}
    assert exp["assert"]["kind"] == "matches"
    assert le.is_handler_expectation(exp)


def test_level_for_status():
    assert le.level_for_status(404) == "WARNING"
    assert le.level_for_status(501) == "ERROR"
    assert le.level_for_status(503) == "ERROR"


def test_no_handler_line_is_expected_for_a_success():
    import pytest

    with pytest.raises(ValueError):
        le.level_for_status(201)
