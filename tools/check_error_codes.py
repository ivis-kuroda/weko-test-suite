#!/usr/bin/env python3
"""Tier-0 static conformance check for the SWORD V3 error codes.

Compares the error specification declared in ``weko_swordserver/errors.py``
against ``fixtures/error-code-map.json`` (the test-side expectation) without
importing the application: ``errors.py`` is only parsed with :mod:`ast`.

Checks, per code:

* the code exists on both sides (no code only in one of them);
* the message id (``_("MSGID")``) is the same on both sides;
* the HTTP status of the ``ErrorType`` member equals the mapped status;
* the hundreds band of the code matches the ``NNxx errors.`` docstring of the
  exception class that declares it;
* the class attribute name equals the message id (``ErrorSpec.__set_name__``
  relies on that for its fallback to the bundled catalog);
* optionally, the message id is a key of the ``en`` gettext catalog and has a
  non-empty translation.

Exit status: 0 when clean, 1 when discrepancies were found, 2 for usage or
parse errors.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

GETTEXT_NAMES = frozenset({"_", "gettext", "lazy_gettext"})
BAND_PATTERN = re.compile(r"^\s*(\d{2})xx\b")


class CheckError(Exception):
    """Input could not be read or parsed (maps to exit status 2)."""


@dataclass(frozen=True)
class SpecEntry:
    """One ``ErrorSpec(...)`` class attribute found in ``errors.py``."""

    code: str
    msgid: str
    error_type: str
    attr: str
    class_name: str
    band: str | None
    line: int


@dataclass(frozen=True)
class ParsedErrors:
    """What was extracted from ``errors.py``."""

    specs: list[SpecEntry]
    http_codes: dict[str, int]


def _literal_str(node: ast.expr, what: str, line: int) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise CheckError(f"errors.py:{line}: {what} is not a string literal")


def _parse_error_types(tree: ast.Module) -> dict[str, int]:
    """Return ``{member name: HTTP status}`` from the ``ErrorType`` enum."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ErrorType":
            members: dict[str, int] = {}
            for stmt in node.body:
                if not (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Tuple)
                ):
                    continue
                elts = stmt.value.elts
                if len(elts) >= 2 and isinstance(elts[1], ast.Constant):
                    value = elts[1].value
                    if isinstance(value, int):
                        members[stmt.targets[0].id] = value
                        continue
                raise CheckError(f"errors.py:{stmt.lineno}: cannot read HTTP status of ErrorType")
            if not members:
                raise CheckError("errors.py: ErrorType enum has no readable members")
            return members
    raise CheckError("errors.py: class ErrorType not found")


def _spec_call_args(call: ast.Call, line: int) -> tuple[ast.expr, ast.expr, ast.expr]:
    names = ("code", "msgid", "error_type")
    found: dict[str, ast.expr] = dict(zip(names, call.args, strict=False))
    for kw in call.keywords:
        if kw.arg in names:
            found[kw.arg] = kw.value
    missing = [n for n in names if n not in found]
    if missing:
        raise CheckError(f"errors.py:{line}: ErrorSpec call lacks {', '.join(missing)}")
    return found["code"], found["msgid"], found["error_type"]


def _msgid_of(node: ast.expr, line: int) -> str:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in GETTEXT_NAMES
        and len(node.args) == 1
    ):
        return _literal_str(node.args[0], "message id", line)
    return _literal_str(node, "message id", line)


def parse_errors_source(source: str) -> ParsedErrors:
    """Extract the error specification from the text of ``errors.py``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CheckError(f"errors.py: syntax error: {exc}") from exc

    http_codes = _parse_error_types(tree)
    specs: list[SpecEntry] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name == "ErrorType":
            continue
        doc = ast.get_docstring(node) or ""
        band_match = BAND_PATTERN.match(doc)
        band = band_match.group(1) if band_match else None
        for stmt in node.body:
            if not (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "ErrorSpec"
            ):
                continue
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                raise CheckError(f"errors.py:{stmt.lineno}: unsupported ErrorSpec assignment")
            code_node, msgid_node, type_node = _spec_call_args(stmt.value, stmt.lineno)
            if not (
                isinstance(type_node, ast.Attribute)
                and isinstance(type_node.value, ast.Name)
                and type_node.value.id == "ErrorType"
            ):
                raise CheckError(f"errors.py:{stmt.lineno}: error type is not ErrorType.<name>")
            specs.append(
                SpecEntry(
                    code=_literal_str(code_node, "code", stmt.lineno),
                    msgid=_msgid_of(msgid_node, stmt.lineno),
                    error_type=type_node.attr,
                    attr=stmt.targets[0].id,
                    class_name=node.name,
                    band=band,
                    line=stmt.lineno,
                )
            )
    return ParsedErrors(specs=specs, http_codes=http_codes)


def load_code_map(path: Path) -> dict[str, dict]:
    """Read ``error-code-map.json`` into ``{code: entry}``; duplicates are an error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"{path}: cannot read map: {exc}") from exc
    if not isinstance(data, list):
        raise CheckError(f"{path}: expected a JSON list of entries")
    result: dict[str, dict] = {}
    for index, entry in enumerate(data):
        if not isinstance(entry, dict) or not {"code", "msgid", "status"} <= entry.keys():
            raise CheckError(f"{path}: entry {index} lacks code/msgid/status")
        code = str(entry["code"])
        if code in result:
            raise CheckError(f"{path}: duplicate code {code}")
        result[code] = entry
    return result


def parse_po_catalog(text: str) -> dict[str, str]:
    """Return ``{msgid: msgstr}`` from gettext ``.po`` text (header entry excluded)."""
    entries: dict[str, str] = {}
    current: str | None = None  # "msgid" or "msgstr", the field being continued
    msgid = ""
    msgstr = ""
    have_entry = False

    def flush() -> None:
        nonlocal msgid, msgstr, have_entry
        if have_entry and msgid != "":
            entries[msgid] = msgstr
        msgid, msgstr, have_entry = "", "", False

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#~"):
            continue
        if line.startswith("msgid "):
            flush()
            current, have_entry = "msgid", True
            msgid = _po_string(line[len("msgid ") :])
        elif line.startswith("msgstr "):
            current = "msgstr"
            msgstr = _po_string(line[len("msgstr ") :])
        elif line.startswith('"') and current is not None:
            if current == "msgid":
                msgid += _po_string(line)
            else:
                msgstr += _po_string(line)
        elif line == "" or line.startswith("#"):
            if line == "":
                current = None
        else:
            current = None
    flush()
    return entries


def _po_string(token: str) -> str:
    try:
        value = ast.literal_eval(token.strip())
    except (ValueError, SyntaxError) as exc:
        raise CheckError(f"catalog: unreadable string {token!r}") from exc
    if not isinstance(value, str):
        raise CheckError(f"catalog: not a string: {token!r}")
    return value


def compare(
    parsed: ParsedErrors,
    code_map: dict[str, dict],
    catalog: dict[str, str] | None = None,
) -> tuple[list[str], int]:
    """Return ``(discrepancy lines, number of distinct codes checked)``."""
    problems: list[str] = []
    by_code: dict[str, SpecEntry] = {}
    for spec in parsed.specs:
        if spec.code in by_code:
            first = by_code[spec.code]
            problems.append(
                f"{spec.code}: declared twice in errors.py "
                f"({first.class_name}.{first.attr} and {spec.class_name}.{spec.attr})"
            )
            continue
        by_code[spec.code] = spec

    for code in sorted(by_code.keys() - code_map.keys()):
        spec = by_code[code]
        problems.append(f"{code}: in errors.py ({spec.class_name}.{spec.attr}) but not in map")
    for code in sorted(code_map.keys() - by_code.keys()):
        problems.append(f"{code}: in map ({code_map[code]['msgid']}) but not in errors.py")

    for code in sorted(by_code.keys() & code_map.keys()):
        spec, expected = by_code[code], code_map[code]
        if spec.msgid != expected["msgid"]:
            problems.append(
                f"{code}: msgid mismatch (errors.py {spec.msgid!r}, map {expected['msgid']!r})"
            )
        if spec.attr != spec.msgid:
            problems.append(
                f"{code}: attribute name {spec.attr!r} differs from msgid {spec.msgid!r}"
            )
        status = parsed.http_codes.get(spec.error_type)
        if status is None:
            problems.append(f"{code}: unknown ErrorType.{spec.error_type}")
        elif status != expected["status"]:
            problems.append(
                f"{code}: HTTP status mismatch (errors.py {status} via "
                f"ErrorType.{spec.error_type}, map {expected['status']})"
            )
        if spec.band is None:
            problems.append(f"{code}: class {spec.class_name} has no 'NNxx errors.' docstring")
        elif not code.startswith(spec.band):
            problems.append(
                f"{code}: band mismatch (class {spec.class_name} is documented as {spec.band}xx)"
            )

    if catalog is not None:
        for code in sorted(by_code):
            msgid = by_code[code].msgid
            if msgid not in catalog:
                problems.append(f"{code}: msgid {msgid!r} missing from en catalog")
            elif catalog[msgid].strip() == "":
                problems.append(f"{code}: msgid {msgid!r} has an empty translation in en catalog")

    return problems, len(by_code.keys() | code_map.keys())


def _read(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"{what}: cannot read {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the process exit status."""
    parser = argparse.ArgumentParser(
        description="Statically compare weko_swordserver/errors.py with the error-code map."
    )
    parser.add_argument("--errors", type=Path, required=True, help="path to errors.py")
    parser.add_argument("--map", type=Path, required=True, help="path to error-code-map.json")
    parser.add_argument("--catalog", type=Path, help="path to the en messages.po")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0

    try:
        parsed = parse_errors_source(_read(args.errors, "errors"))
        code_map = load_code_map(args.map)
        catalog = parse_po_catalog(_read(args.catalog, "catalog")) if args.catalog else None
    except CheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problems, checked = compare(parsed, code_map, catalog)
    for line in problems:
        print(line)
    print(f"checked {checked} codes, {len(problems)} discrepancies")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
