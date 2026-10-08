#!/usr/bin/env python3
"""Deterministic importer: SWORD V3 error-code test viewpoint workbook -> repository files.

Reads the review workbook (sheets ``テスト観点`` and ``独自コード対応表``) and the
integration test case document (Markdown), and writes:

* ``specs/viewpoints/VP-SW-<ID>.yaml``  one viewpoint per file, in the exact
  canonical form of the agentic-test-hub YAML writer;
* ``fixtures/error-code-map.json``      the per-code expectation table consumed
  by ``tools/check_error_codes.py``;
* ``docs/spec-trace.md``                viewpoint -> case traceability and a
  coverage report (Japanese, for human readers).

The workbook and the case document are untrusted *data*: they are only read,
never executed. Output is a pure function of the inputs (no timestamps, stable
ordering), so running the tool twice produces byte-identical files.

Mapping onto the hub viewpoint schema (``packages/core/src/schema/viewpoint.ts``)
-----------------------------------------------------------------------------

``id``         ``VP-SW-`` + workbook ID (``BD-01`` -> ``VP-SW-BD-01``).
``title``      the ``観点`` cell, verbatim (the schema only requires non-empty).
``rationale``  ``前提`` + ``操作`` + ``期待結果`` joined into one Japanese sentence run.
``source``     one ``design`` ref per cited document in the ``出典`` cell
               (``基本`` -> ``basic_design.md``, ``詳細`` -> ``detailed_design.md``);
               a parenthesised remark becomes the ref's ``note``; text that does
               not follow that pattern becomes a single ``other`` ref.
``risk``       ``high`` when the viewpoint is in the AU (authentication and
               authorisation) family or maps to an error code whose HTTP status is
               5xx; ``low`` when its section is about message language or log
               policy; otherwise ``medium``. A proposal for the reviewer, not a
               judgement.
``parents``    always empty.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

VIEWPOINT_SHEET = "テスト観点"
CODE_SHEET = "独自コード対応表"
ID_PREFIX = "VP-SW-"

DOCUMENTS = {
    "基本": "basic_design.md v1.4",
    "詳細": "detailed_design.md v1.3",
}
LOW_RISK_SECTIONS = ("メッセージ言語・ロケール", "ログ方針")
REACHABILITY_KEYWORDS = (
    "到達不能",
    "到達経路なし",
    "設定依存",
    "設定変更",
    "実施不可",
    "条件付き",
    "代替",
)
# Cases that legitimately have no viewpoint, with the reason shown in the report.
KNOWN_UNLINKED_CASES = {"S1-01": "前提作成ケース（観点に紐づかない）"}
# Viewpoint IDs that are intentionally absent from the workbook.
KNOWN_ABSENT_VIEWPOINTS = {"UI-10": "観点表 v4.2 で除外（欠番）"}

CASE_ID = re.compile(r"S\d+-\d+")
VIEWPOINT_ID = re.compile(r"^[A-Z]{2}-\d+$")


class ImportError_(Exception):
    """The inputs do not have the expected shape."""


@dataclass
class Viewpoint:
    """One row of the ``テスト観点`` sheet."""

    id: str
    kind: str
    title: str
    cases: list[str]
    precondition: str
    operation: str
    expected: str
    source_raw: str
    section: str
    row: int


@dataclass
class CodeRow:
    """One row of the ``独自コード対応表`` sheet."""

    code: str
    msgid: str
    status: int
    viewpoints: list[str]
    cases: list[str]
    summary: str
    verification: str
    match: str
    row: int


@dataclass
class Workbook:
    """Parsed workbook content."""

    viewpoints: list[Viewpoint] = field(default_factory=list)
    codes: list[CodeRow] = field(default_factory=list)


# --------------------------------------------------------------------------- reading


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def split_ids(value: str) -> list[str]:
    """Split ``"S5-06, S5-09"`` / ``"S5-06、S5-09"`` into ``["S5-06", "S5-09"]``."""
    return [part for part in re.split(r"[,、，\s]+", value.strip()) if part]


def _header_index(rows: list[tuple], expected: list[str], sheet: str) -> tuple[int, int]:
    """Locate the header row; return ``(row index, first column index)``."""
    for index, row in enumerate(rows):
        cells = [_text(c) for c in row]
        if expected[0] in cells:
            start = cells.index(expected[0])
            if cells[start : start + len(expected)] == expected:
                return index, start
    raise ImportError_(f"sheet {sheet!r}: header {expected} not found")


def read_workbook(path: Path) -> Workbook:
    """Read both sheets of the workbook."""
    try:
        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except (OSError, ValueError) as exc:
        raise ImportError_(f"cannot open workbook {path}: {exc}") from exc
    result = Workbook()
    for name in (VIEWPOINT_SHEET, CODE_SHEET):
        if name not in book.sheetnames:
            raise ImportError_(f"workbook has no sheet {name!r}")

    rows = list(book[VIEWPOINT_SHEET].iter_rows(values_only=True))
    head = ["ID", "種別", "観点", "対応テストケース", "前提", "操作", "期待結果", "出典"]
    h, c0 = _header_index(rows, head, VIEWPOINT_SHEET)
    section = ""
    seen: set[str] = set()
    for offset, row in enumerate(rows[h + 1 :], start=h + 2):
        cells = [_text(c) for c in row[c0 : c0 + len(head)]]
        cells += [""] * (len(head) - len(cells))
        if not any(cells):
            continue
        if cells[0] and not any(cells[1:]):
            section = cells[0]  # a section-title row
            continue
        vp_id = cells[0]
        if not VIEWPOINT_ID.match(vp_id):
            raise ImportError_(f"row {offset}: unexpected viewpoint id {vp_id!r}")
        if vp_id in seen:
            raise ImportError_(f"row {offset}: duplicate viewpoint id {vp_id}")
        seen.add(vp_id)
        if not cells[2]:
            raise ImportError_(f"row {offset}: {vp_id} has no title")
        result.viewpoints.append(
            Viewpoint(
                id=vp_id,
                kind=cells[1],
                title=cells[2],
                cases=split_ids(cells[3]),
                precondition=cells[4],
                operation=cells[5],
                expected=cells[6],
                source_raw=cells[7],
                section=section,
                row=offset,
            )
        )

    rows = list(book[CODE_SHEET].iter_rows(values_only=True))
    head = ["独自コード", "エラーID(msgid)", "ステータス", "対応観点ID", "対応ケースID"]
    h, c0 = _header_index(rows, head, CODE_SHEET)
    width = 9  # code .. 備考
    seen_codes: set[str] = set()
    for offset, row in enumerate(rows[h + 1 :], start=h + 2):
        cells = [_text(c) for c in row[c0 : c0 + width]]
        cells += [""] * (width - len(cells))
        if not cells[0]:
            continue
        if cells[0] in seen_codes:
            raise ImportError_(f"row {offset}: duplicate code {cells[0]}")
        seen_codes.add(cells[0])
        try:
            status = int(cells[2])
        except ValueError as exc:
            raise ImportError_(f"row {offset}: status {cells[2]!r} is not an integer") from exc
        result.codes.append(
            CodeRow(
                code=cells[0],
                msgid=cells[1],
                status=status,
                viewpoints=split_ids(cells[3]),
                cases=split_ids(cells[4]),
                summary=cells[5],
                verification=cells[6],
                match=cells[7],
                row=offset,
            )
        )
    return result


def read_spec_cases(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Return ``(case ids in document order, viewpoint -> cases from the section 3 table)``."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ImportError_(f"cannot read case document {path}: {exc}") from exc
    cases: list[str] = []
    for line in lines:
        match = re.match(r"^#### (S\d+-\d+)", line)
        if match:
            cases.append(match.group(1))
    table: dict[str, list[str]] = {}
    in_section = False
    for line in lines:
        if line.startswith("## 3."):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        row = re.match(r"^\|\s*([A-Z]{2}-\d+)\s*\|\s*(.+?)\s*\|\s*\d+\s*\|$", line)
        if in_section and row:
            table[row.group(1)] = split_ids(row.group(2))
    if not cases:
        raise ImportError_(f"{path}: no '#### S<n>-<m>' case headings found")
    return cases, table


# ------------------------------------------------------------------ viewpoint mapping


def parse_sources(raw: str) -> list[dict[str, str]]:
    """Turn the ``出典`` cell into hub ``SourceRef`` dicts (``kind``, ``ref``, ``note``?)."""
    raw = raw.strip()
    if not raw:
        return [{"kind": "other", "ref": "（出典の記載なし）"}]
    segments = re.findall(r"(基本|詳細)\s*(.*?)(?=、(?:基本|詳細)|$)", raw)
    rebuilt = "、".join(f"{doc} {rest}" for doc, rest in segments)
    if not segments or re.sub(r"\s+", "", rebuilt) != re.sub(r"\s+", "", raw):
        return [{"kind": "other", "ref": raw}]
    refs: list[dict[str, str]] = []
    for doc, rest in segments:
        note_match = re.search(r"[（(](.*)[）)]\s*$", rest)
        note = note_match.group(1).strip() if note_match else ""
        sections_text = rest[: note_match.start()] if note_match else rest
        sections = [s.strip() for s in sections_text.split(",") if s.strip()]
        if not sections or not all(re.fullmatch(r"\d+(\.\d+)*", s) for s in sections):
            return [{"kind": "other", "ref": raw}]
        ref = {
            "kind": "design",
            "ref": f"{DOCUMENTS[doc]} " + ", ".join(f"§{s}" for s in sections),
        }
        if note:
            ref["note"] = note
        refs.append(ref)
    return refs


def rationale_of(vp: Viewpoint) -> str:
    """Condense precondition, operation and expected result into one prose run."""

    def clean(text: str) -> str:
        return text.strip().rstrip("。").strip()

    parts = [("前提", vp.precondition), ("操作", vp.operation), ("期待結果", vp.expected)]
    body = "。".join(f"{label}：{clean(text)}" for label, text in parts if clean(text))
    if not body:
        raise ImportError_(f"{vp.id}: precondition, operation and expectation are all empty")
    return body + "。"


def risk_of(vp: Viewpoint, status_by_viewpoint: dict[str, int]) -> str:
    """Apply the documented risk rule."""
    if vp.id.startswith("AU-") or status_by_viewpoint.get(vp.id, 0) >= 500:
        return "high"
    if any(key in vp.section for key in LOW_RISK_SECTIONS):
        return "low"
    return "medium"


def viewpoint_entity(vp: Viewpoint, status_by_viewpoint: dict[str, int]) -> dict:
    """Build the hub ``Viewpoint`` entity (keys in schema order)."""
    return {
        "id": ID_PREFIX + vp.id,
        "title": vp.title,
        "rationale": rationale_of(vp),
        "source": parse_sources(vp.source_raw),
        "risk": risk_of(vp, status_by_viewpoint),
        "parents": [],
    }


# --------------------------------------------------------------------- YAML emission

_PLAIN_FORBIDDEN = re.compile(
    r"""^[\n\t ,\[\]{}#&*!|>'"%@`]|^[?-]$|^[?-][ \t]|[\n:][ \t]|[ \t]\n|[\n\t ]\#|[\n\t :]$"""
)
_IMPLICIT_NON_STRING = (
    re.compile(r"^(?:~|[Nn]ull|NULL)?$"),
    re.compile(r"^(?:[Tt]rue|TRUE|[Ff]alse|FALSE)$"),
    re.compile(r"^[-+]?[0-9]+$"),
    re.compile(r"^0o[0-7]+$"),
    re.compile(r"^0x[0-9a-fA-F]+$"),
    re.compile(r"^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?$"),
    re.compile(r"^[-+]?\.(?:inf|Inf|INF)$"),
    re.compile(r"^\.(?:nan|NaN|NAN)$"),
)


def yaml_scalar(value: str) -> str:
    """Render a single-line string the way the hub's ``yaml`` writer does.

    The hub writes plain scalars where they are unambiguous and double-quoted
    scalars otherwise (``singleQuote: false``, no line folding). Multi-line
    strings never occur in this importer's output and are rejected.
    """
    if any(ord(ch) < 0x20 or 0x7F <= ord(ch) <= 0x9F for ch in value):
        raise ValueError(f"control character in {value!r}")
    if value == "" or _PLAIN_FORBIDDEN.search(value):
        return _quote(value)
    if any(pattern.match(value) for pattern in _IMPLICIT_NON_STRING):
        return _quote(value)
    return value


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def viewpoint_yaml(entity: dict) -> str:
    """Serialise a viewpoint entity in canonical hub form (ends with a newline)."""
    lines = [
        f"id: {yaml_scalar(entity['id'])}",
        f"title: {yaml_scalar(entity['title'])}",
        f"rationale: {yaml_scalar(entity['rationale'])}",
        "source:",
    ]
    for ref in entity["source"]:
        lines.append(f"  - kind: {yaml_scalar(ref['kind'])}")
        lines.append(f"    ref: {yaml_scalar(ref['ref'])}")
        if "note" in ref:
            lines.append(f"    note: {yaml_scalar(ref['note'])}")
    lines.append(f"risk: {yaml_scalar(entity['risk'])}")
    if entity["parents"]:
        lines.append("parents:")
        lines.extend(f"  - {yaml_scalar(p)}" for p in entity["parents"])
    else:
        lines.append("parents: []")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------- code map


def reachability_note(row: CodeRow) -> str:
    """Return the workbook's remarks on how (or whether) the code can be reached."""
    parts = [
        p.replace("**", "").strip()
        for p in (row.verification, row.match)
        if any(key in p for key in REACHABILITY_KEYWORDS)
    ]
    return " / ".join(parts)


def code_map_entries(book: Workbook) -> list[dict]:
    """Build the ``error-code-map.json`` list, sorted by code."""
    entries = [
        {
            "code": row.code,
            "msgid": row.msgid,
            "status": row.status,
            "viewpoints": [ID_PREFIX + v for v in sorted(row.viewpoints)],
            "cases": sorted(row.cases, key=_case_key),
            "summary": row.summary,
            "verification": row.verification,
            "match": row.match,
            "reachability_note": reachability_note(row),
        }
        for row in book.codes
    ]
    return sorted(entries, key=lambda e: e["code"])


def code_map_json(entries: list[dict]) -> str:
    """Serialise the map deterministically."""
    return json.dumps(entries, ensure_ascii=False, indent=2) + "\n"


def _case_key(case_id: str) -> tuple[int, int]:
    group, number = case_id[1:].split("-")
    return int(group), int(number)


# ------------------------------------------------------------------- trace document


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_trace(
    book: Workbook,
    spec_cases: list[str],
    spec_table: dict[str, list[str]],
    xlsx_name: str,
    spec_name: str,
) -> str:
    """Render ``docs/spec-trace.md`` (Japanese)."""
    vp_ids = [vp.id for vp in book.viewpoints]
    vp_set = set(vp_ids)
    case_set = set(spec_cases)

    referenced: dict[str, list[str]] = {}
    for vp in book.viewpoints:
        for case in vp.cases:
            referenced.setdefault(case, []).append(vp.id)

    without_case = [vp.id for vp in book.viewpoints if not vp.cases]
    unreferenced = [c for c in spec_cases if c not in referenced]
    unknown_cases = sorted(
        {c for vp in book.viewpoints for c in vp.cases if c not in case_set}, key=_case_key
    )
    absent_found = [v for v in KNOWN_ABSENT_VIEWPOINTS if v in vp_set]

    mismatches: list[str] = []
    for vp in book.viewpoints:
        in_md = spec_table.get(vp.id)
        if in_md is None:
            mismatches.append(
                f"- {vp.id}: 仕様書 3 章の対応表に行がない（観点表: {', '.join(vp.cases)}）"
            )
        elif sorted(in_md, key=_case_key) != sorted(vp.cases, key=_case_key):
            mismatches.append(
                f"- {vp.id}: 観点表 {', '.join(vp.cases) or '（なし）'} / "
                f"仕様書 3 章 {', '.join(in_md) or '（なし）'}"
            )
    for vp_id in spec_table:
        if vp_id not in vp_set:
            mismatches.append(f"- {vp_id}: 仕様書 3 章にあるが観点表にない")

    code_vp_unknown = sorted(
        {(r.code, v) for r in book.codes for v in r.viewpoints if v not in vp_set}
    )
    code_case_unknown = sorted(
        {(r.code, c) for r in book.codes for c in r.cases if c not in case_set},
        key=lambda t: (t[0], _case_key(t[1])),
    )

    out: list[str] = []
    add = out.append
    add("# 観点・ケース トレーサビリティ")
    add("")
    add("> このファイルは `tools/import_viewpoints.py` が生成した機械生成の提案であり、")
    add("> レビュー前の内容を含みます。直接編集せず、入力を直して再生成してください。")
    add("")
    add(f"- 観点表: `{xlsx_name}`（シート `テスト観点`・`独自コード対応表`）")
    add(f"- ケース仕様書: `{spec_name}`")
    add("")
    add("## 概要")
    add("")
    add("| 項目 | 件数 |")
    add("| --- | ---: |")
    add(f"| 観点 | {len(book.viewpoints)} |")
    add(f"| ケース（仕様書の `#### S<n>-<m>` 見出し） | {len(spec_cases)} |")
    add(f"| 独自コード | {len(book.codes)} |")
    add(f"| ケースを持たない観点 | {len(without_case)} |")
    add(f"| どの観点からも参照されないケース | {len(unreferenced)} |")
    add("")
    add("## 観点 → ケース")
    add("")
    add("| 観点 | 観点名 | ケース |")
    add("| --- | --- | --- |")
    for vp in book.viewpoints:
        cases = "、".join(vp.cases) if vp.cases else "（なし）"
        add(f"| `{ID_PREFIX}{vp.id}` | {_cell(vp.title)} | {cases} |")
    add("")
    add("## ケース → 観点")
    add("")
    add("| ケース | 観点 |")
    add("| --- | --- |")
    for case in spec_cases:
        if case in referenced:
            add(f"| {case} | {'、'.join(referenced[case])} |")
        elif case in KNOWN_UNLINKED_CASES:
            add(f"| {case} | （なし。{KNOWN_UNLINKED_CASES[case]}） |")
        else:
            add(f"| {case} | **（なし。要確認）** |")
    add("")
    add("## カバレッジ確認")
    add("")
    add("### ケースを持たない観点")
    add("")
    add("、".join(without_case) if without_case else "なし。")
    add("")
    add("### どの観点からも参照されないケース")
    add("")
    if unreferenced:
        for case in unreferenced:
            reason = KNOWN_UNLINKED_CASES.get(case)
            add(
                f"- {case}"
                + (f"：{reason}" if reason else "：**要確認**（観点表から参照されていない）")
            )
    else:
        add("なし。")
    add("")
    add("### 観点表が参照するが仕様書に存在しないケース")
    add("")
    add("、".join(unknown_cases) if unknown_cases else "なし。")
    add("")
    add("### 観点表と仕様書 3 章の対応表の食い違い")
    add("")
    add("\n".join(mismatches) if mismatches else "なし。")
    add("")
    add("### 独自コード対応表の参照整合")
    add("")
    problems = [f"- {c}: 観点表にない観点 {v}" for c, v in code_vp_unknown] + [
        f"- {c}: 仕様書にないケース {k}" for c, k in code_case_unknown
    ]
    add("\n".join(problems) if problems else "すべての参照が解決できる。")
    add("")
    add("### 意図的な欠番")
    add("")
    for vp_id, reason in KNOWN_ABSENT_VIEWPOINTS.items():
        state = (
            "**観点表に存在する（要確認）**"
            if vp_id in absent_found
            else "観点表に存在しない（想定どおり）"
        )
        add(f"- {vp_id}：{reason}。{state}")
    add("")
    return "\n".join(out)


# ------------------------------------------------------------------------------ CLI


def write_if_changed(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` (UTF-8, LF), creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run(xlsx: Path, spec_md: Path, out_root: Path) -> dict[str, int]:
    """Generate all outputs under ``out_root``; return counts."""
    book = read_workbook(xlsx)
    spec_cases, spec_table = read_spec_cases(spec_md)

    status_by_viewpoint: dict[str, int] = {}
    for row in book.codes:
        for vp_id in row.viewpoints:
            status_by_viewpoint[vp_id] = max(status_by_viewpoint.get(vp_id, 0), row.status)

    for vp in book.viewpoints:
        entity = viewpoint_entity(vp, status_by_viewpoint)
        write_if_changed(
            out_root / "specs" / "viewpoints" / f"{entity['id']}.yaml", viewpoint_yaml(entity)
        )
    write_if_changed(
        out_root / "fixtures" / "error-code-map.json", code_map_json(code_map_entries(book))
    )
    write_if_changed(
        out_root / "docs" / "spec-trace.md",
        render_trace(book, spec_cases, spec_table, xlsx.name, spec_md.name),
    )
    return {"viewpoints": len(book.viewpoints), "codes": len(book.codes), "cases": len(spec_cases)}


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the process exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--xlsx", type=Path, required=True, help="viewpoint workbook")
    parser.add_argument("--spec-md", type=Path, required=True, help="case document (Markdown)")
    parser.add_argument("--out-root", type=Path, default=Path("."), help="repository root")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        counts = run(args.xlsx, args.spec_md, args.out_root)
    except ImportError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"imported {counts['viewpoints']} viewpoints, {counts['codes']} codes; "
        f"{counts['cases']} cases in the case document"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
