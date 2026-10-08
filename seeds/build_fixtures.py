#!/usr/bin/env python3
"""Deterministic registration packages for the SWORD v3 test cases (S0-04).

Everything is generated from code, byte for byte reproducibly: archives use
stored (uncompressed) entries, a fixed timestamp, sorted names and fixed
permissions, so the same source gives the same SHA-256 on every machine and
Python version. The committed `fixtures/manifest.json` records use, size and
hash of each fixture (and the Digest header value); CI regenerates and
compares. The archives themselves are not committed: build them on demand.

    python seeds/build_fixtures.py build            # -> fixtures/generated/
    python seeds/build_fixtures.py build --check    # manifest up to date?
    python seeds/build_fixtures.py digest FILE      # Digest header value
    python seeds/build_fixtures.py put-item --id 42 --out F.zip
    python seeds/build_fixtures.py sized --size 1048576 --out F.zip

What these fixtures can and cannot promise
------------------------------------------
Structure is faithful to what weko-swordserver inspects: archive layout,
packaging detection, BagIt manifests/tag manifests, JSON-LD syntax. Metadata
*content* is generic. Whether a CSV, XML or RO-Crate maps onto an item type
depends on the target's item types and the SWORD client's mapping; the
skeletons here are enough to reach the checks that precede mapping, not to
register an item. Cases that must reach registration need metadata exported
from the target environment (see fixtures/README.md).

Stdlib only, so it runs under any interpreter the suite uses.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIXED_DATE = (2025, 1, 1, 0, 0, 0)
"""Timestamp of every archive entry."""

PKG_SIMPLEZIP = "http://purl.org/net/sword/3.0/package/SimpleZip"
PKG_BAGIT = "http://purl.org/net/sword/3.0/package/SWORDBagIt"

SWORD_METADATA_FILE = "metadata/sword.json"
ROCRATE_METADATA_FILE = "data/ro-crate-metadata.json"
"""Names weko_search_ui.config expects (SWORD_METADATA_FILE, ROCRATE_METADATA_FILE)."""

MULTIPART_BOUNDARY_LEN = 32
"""httpx writes a 16-byte random boundary as 32 hex characters."""

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Archives
# ---------------------------------------------------------------------------


def build_zip(entries: Mapping[str, bytes]) -> bytes:
    """A reproducible ZIP: stored entries in name order, fixed date and mode.

    A name ending in `/` becomes a directory entry.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o40755 << 16 if name.endswith("/") else 0o100644 << 16
            archive.writestr(info, entries[name])
    return buffer.getvalue()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_header(data: bytes) -> str:
    """The `Digest` header value weko accepts for `data`.

    weko's `is_valid_file_hash` compares the part after `SHA-256=` with the
    lower-case hex SHA-256 of the *uploaded file part* (the zip bytes, not the
    whole multipart body); the tests' `calculate_hash` is the same hexdigest.
    No base64, unlike RFC 3230.
    """
    return f"SHA-256={sha256_hex(data)}"


def bag_entries(
    payload: Mapping[str, bytes],
    tags: Mapping[str, bytes] | None = None,
    *,
    corrupt_manifest_for: str | None = None,
    include_bagit_txt: bool = True,
) -> dict[str, bytes]:
    """Archive entries of a BagIt bag, valid unless told otherwise.

    @param payload: paths relative to `data/` and their bytes.
    @param tags: extra tag files outside `data/` (e.g. `metadata/sword.json`),
        listed in the tag manifest like bagit-python does.
    @param corrupt_manifest_for: a payload path whose manifest checksum is
        replaced by a wrong one (checksum mismatch).
    @param include_bagit_txt: drop `bagit.txt` to model a missing bag declaration.
    """
    tags = dict(tags or {})
    entries: dict[str, bytes] = {f"data/{path}": body for path, body in payload.items()}
    entries.update(tags)

    manifest_lines = []
    for path in sorted(payload):
        checksum = sha256_hex(payload[path])
        if path == corrupt_manifest_for:
            checksum = ("0" if checksum[0] != "0" else "1") + checksum[1:]
        manifest_lines.append(f"{checksum}  data/{path}")
    manifest = ("\n".join(manifest_lines) + "\n").encode()

    octets = sum(len(body) for body in payload.values())
    bag_info = (
        "Bag-Software-Agent: build_fixtures.py (weko-test-suite)\n"
        "Bagging-Date: 2025-01-01\n"
        f"Payload-Oxum: {octets}.{len(payload)}\n"
    ).encode()
    bagit_txt = b"BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"

    entries["manifest-sha256.txt"] = manifest
    entries["bag-info.txt"] = bag_info
    if include_bagit_txt:
        entries["bagit.txt"] = bagit_txt

    tag_files = [name for name in entries if not name.startswith("data/")]
    tagmanifest = "\n".join(f"{sha256_hex(entries[n])}  {n}" for n in sorted(tag_files)) + "\n"
    entries["tagmanifest-sha256.txt"] = tagmanifest.encode()
    return entries


# ---------------------------------------------------------------------------
# Metadata content
# ---------------------------------------------------------------------------


def rocrate_json(title: str = "WEKO SWORD test dataset", files: tuple[str, ...] = ()) -> str:
    """A small RO-Crate 1.1 document (pretty printed, trailing newline)."""
    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "name": title,
            "description": "Generated for SWORD API tests.",
            "datePublished": "2025-01-01",
            "hasPart": [{"@id": f} for f in files],
        },
    ]
    graph += [{"@id": f, "@type": "File", "name": f} for f in files]
    document = {"@context": "https://w3id.org/ro/crate/1.1/context", "@graph": graph}
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


DEFAULT_ITEM_TYPE = ("Default Item Type", "https://weko.invalid/items/jsonschema/1")


def import_csv(
    rows: list[dict[str, str]],
    item_type: tuple[str, str] = DEFAULT_ITEM_TYPE,
) -> bytes:
    """A skeleton WEKO import CSV (UTF-8, LF), laid out like the real export.

    Five header lines (item type, keys, names, system markers, rules), then
    one line per item. Columns: `.id` (empty = new item), `.uri`,
    `.publish_status`, `.metadata.pubdate`, `.metadata.title`.
    """
    keys = [".id", ".uri", ".publish_status", ".metadata.pubdate", ".metadata.title"]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["#ItemType", item_type[0], item_type[1]])
    writer.writerow(keys)
    writer.writerow([".ID", ".URI", ".PUBLISH_STATUS", "PubDate", "Title"])
    writer.writerow(["System", "System", "System", "", ""])
    writer.writerow(["", "", "", "Required", "Required"])
    for row in rows:
        writer.writerow([row.get(k, "") for k in keys])
    return out.getvalue().encode("utf-8")


def item_row(title: str, item_id: str = "") -> dict[str, str]:
    return {
        ".id": item_id,
        ".publish_status": "public",
        ".metadata.pubdate": "2025-01-01",
        ".metadata.title": title,
    }


JPCOAR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<jpcoar:jpcoar xmlns:jpcoar="https://github.com/JPCOAR/schema/blob/master/2.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/">
  <dc:title xml:lang="en">{title}</dc:title>
  <dc:type>conference paper</dc:type>
</jpcoar:jpcoar>
"""

SAMPLE_HTML = b"<!DOCTYPE html>\n<html><body><p>sample attachment</p></body></html>\n"
SAMPLE_RST = b"Sample\n======\n\nAttachment for SWORDBagIt tests.\n"
SAMPLE_DATA_CSV = b"id,value\n1,alpha\n2,beta\n"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _simplezip_csv(title: str = "Test item A", payload: bytes = SAMPLE_HTML) -> bytes:
    return build_zip({"data/index.csv": import_csv([item_row(title)]), "data/sample.html": payload})


def _crate_payload(title: str = "Test item A") -> dict[str, bytes]:
    return {"data.csv": SAMPLE_DATA_CSV, "sample.rst": SAMPLE_RST}


def _sword_json(title: str = "Test item A") -> bytes:
    return rocrate_json(title, ("data/data.csv", "data/sample.rst")).encode("utf-8")


def _bagit(
    title: str = "Test item A",
    metadata: bytes | None = None,
    **kwargs: Any,
) -> bytes:
    tags = (
        {}
        if kwargs.pop("no_metadata", False)
        else {SWORD_METADATA_FILE: metadata or _sword_json(title)}
    )
    return build_zip(bag_entries(_crate_payload(title), tags, **kwargs))


def _rocrate(title: str = "Test item A") -> bytes:
    payload = _crate_payload(title)
    payload["ro-crate-metadata.json"] = rocrate_json(title, ("data.csv", "sample.rst")).encode(
        "utf-8"
    )
    return build_zip(bag_entries(payload))


def _syntax_error_json() -> bytes:
    """sword.json with the comma after `"@type"` of the root dataset removed."""
    lines = rocrate_json(files=("data/data.csv",)).splitlines()
    for number, line in enumerate(lines):
        if line.strip() == '"@type": "Dataset",':
            lines[number] = line.rstrip(",")
            break
    else:  # pragma: no cover - guarded by a unit test
        raise AssertionError("root dataset line not found")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _non_utf8_json() -> bytes:
    """sword.json whose dataset name is Shift_JIS-encoded (invalid UTF-8)."""
    text = rocrate_json("TITLE-PLACEHOLDER", ("data/data.csv",))
    head, tail = text.split("TITLE-PLACEHOLDER")
    return head.encode("utf-8") + "日本語".encode("cp932") + tail.encode("utf-8")


def _broken_zip() -> bytes:
    """Starts like a ZIP (local file header) but cannot be opened as one."""
    return b"PK\x03\x04" + bytes(range(32)) + b"not a zip archive\n"


def _multi_item_csv() -> bytes:
    rows = [item_row("Multi item 1"), item_row("Multi item 2")]
    return build_zip({"data/index.csv": import_csv(rows), "data/sample.html": SAMPLE_HTML})


@dataclass(frozen=True)
class Fixture:
    name: str
    packaging: str
    purpose: str
    build: Callable[[], bytes]
    facts: dict[str, Any] = field(default_factory=dict)


def _facts_syntax_error() -> dict[str, Any]:
    try:
        json.loads(_syntax_error_json().decode("utf-8"))
    except json.JSONDecodeError as error:
        return {"member": SWORD_METADATA_FILE, "line": error.lineno, "column": error.colno}
    raise AssertionError("fixture is valid JSON")  # pragma: no cover


def _facts_non_utf8() -> dict[str, Any]:
    data = _non_utf8_json()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        return {"member": SWORD_METADATA_FILE, "byteOffset": error.start, "encoding": "cp932"}
    raise AssertionError("fixture is valid UTF-8")  # pragma: no cover


def catalogue() -> list[Fixture]:
    """Every fixture, in the order of the S0-04 list."""
    return [
        Fixture(
            "simplezip-normal.zip",
            PKG_SIMPLEZIP,
            "Normal SimpleZip with CSV metadata (format TSV/CSV). Skeleton columns only.",
            _simplezip_csv,
        ),
        Fixture(
            "bagit-normal.zip",
            PKG_BAGIT,
            "Normal SWORDBagIt: valid bag, metadata/sword.json (RO-Crate JSON-LD).",
            _bagit,
        ),
        Fixture(
            "rocrate-normal.zip",
            PKG_SIMPLEZIP,
            "Normal RO-Crate in SimpleZip: data/ro-crate-metadata.json, also a valid bag "
            "(weko validates bags on the JSON-LD path regardless of packaging).",
            _rocrate,
        ),
        Fixture(
            "broken.zip",
            PKG_SIMPLEZIP,
            "Not openable as a ZIP (S5-09).",
            _broken_zip,
        ),
        Fixture(
            "bagit-checksum-mismatch.zip",
            PKG_BAGIT,
            "SWORDBagIt whose manifest checksum of data/data.csv is wrong: bag.validate() fails.",
            lambda: _bagit(corrupt_manifest_for="data.csv"),
            {"member": "data/data.csv"},
        ),
        Fixture(
            "bagit-no-bagit-txt.zip",
            PKG_BAGIT,
            "SWORDBagIt without bagit.txt (structure missing; measure what weko answers, F-12).",
            lambda: _bagit(include_bagit_txt=False),
        ),
        Fixture(
            "bagit-non-utf8-metadata.zip",
            PKG_BAGIT,
            "Valid bag whose metadata/sword.json is not UTF-8 (Shift_JIS bytes).",
            lambda: build_zip(
                bag_entries(_crate_payload(), {SWORD_METADATA_FILE: _non_utf8_json()})
            ),
            _facts_non_utf8(),
        ),
        Fixture(
            "bagit-jsonld-syntax-error.zip",
            PKG_BAGIT,
            "Valid bag whose metadata/sword.json has a JSON syntax error at a known position.",
            lambda: build_zip(
                bag_entries(_crate_payload(), {SWORD_METADATA_FILE: _syntax_error_json()})
            ),
            _facts_syntax_error(),
        ),
        Fixture(
            "bagit-missing-metadata.zip",
            PKG_BAGIT,
            "SWORDBagIt without metadata/sword.json (packaging error).",
            lambda: _bagit(no_metadata=True),
        ),
        Fixture(
            "simplezip-with-sword-json.zip",
            PKG_SIMPLEZIP,
            "SimpleZip that contains metadata/sword.json (unexpected for SimpleZip).",
            lambda: build_zip(
                {
                    "data/index.csv": import_csv([item_row("Test item A")]),
                    "data/sample.html": SAMPLE_HTML,
                    SWORD_METADATA_FILE: _sword_json(),
                }
            ),
        ),
        Fixture(
            "rocrate-missing-metadata.zip",
            PKG_SIMPLEZIP,
            "RO-Crate whose ro-crate-metadata.json sits at the archive root, not under data/ "
            "(weko reports it missing).",
            lambda: build_zip(
                {
                    "ro-crate-metadata.json": rocrate_json(files=("data.csv",)).encode(),
                    "data/data.csv": SAMPLE_DATA_CSV,
                }
            ),
        ),
        Fixture(
            "simplezip-xml.zip",
            PKG_SIMPLEZIP,
            "SimpleZip with a JPCOAR XML metadata file (format XML; needs XML import enabled "
            "and a workflow in the SWORD settings).",
            lambda: build_zip(
                {
                    "data/metadata.xml": JPCOAR_XML.format(title="Test item A").encode(),
                    "data/sample.html": SAMPLE_HTML,
                }
            ),
        ),
        Fixture(
            "simplezip-multi-item.zip",
            PKG_SIMPLEZIP,
            "SimpleZip CSV with two items (EP4 accepts one: multiple items in PUT).",
            _multi_item_csv,
            {"items": 2},
        ),
        Fixture(
            "put-item-without-id.zip",
            PKG_SIMPLEZIP,
            "EP4 body whose item has no id (treated as a new item, not registered for PUT).",
            _simplezip_csv,
        ),
        Fixture(
            "simplezip-title-a.zip",
            PKG_SIMPLEZIP,
            "Normal SimpleZip, title A (different titles for duplicate checks).",
            lambda: _simplezip_csv("Distinct title A"),
        ),
        Fixture(
            "simplezip-no-title.zip",
            PKG_SIMPLEZIP,
            "SimpleZip whose CSV item has an empty title (metadata deficiency, S5-07).",
            lambda: _simplezip_csv(""),
        ),
        Fixture(
            "simplezip-title-b.zip",
            PKG_SIMPLEZIP,
            "Normal SimpleZip, title B.",
            lambda: _simplezip_csv("Distinct title B"),
        ),
        Fixture(
            "simplezip-title-a-similar.zip",
            PKG_SIMPLEZIP,
            "Same title as title-a, different attachment: similar, not identical.",
            lambda: _simplezip_csv("Distinct title A", payload=SAMPLE_HTML + b"<!-- v2 -->\n"),
        ),
    ]


def put_item_zip(item_id: str, title: str = "Test item A") -> bytes:
    """EP4 body for one item with `.id` set (consistency with the URL's recid)."""
    return build_zip(
        {
            "data/index.csv": import_csv([item_row(title, item_id)]),
            "data/sample.html": SAMPLE_HTML,
        }
    )


# ---------------------------------------------------------------------------
# Requests of a given Content-Length (S5-03)
# ---------------------------------------------------------------------------


def multipart_overhead(
    filename: str = "payload.zip",
    field_name: str = "file",
    content_type: str = "application/zip",
    boundary_len: int = MULTIPART_BOUNDARY_LEN,
) -> int:
    """Bytes httpx adds around a single file part's content in the body."""
    boundary = "x" * boundary_len
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    )
    tail = f"\r\n--{boundary}--\r\n"
    return len(head) + len(tail)


def sized_zip(
    content_length: int,
    filename: str = "payload.zip",
    field_name: str = "file",
    content_type: str = "application/zip",
) -> bytes:
    """A SimpleZip such that the multipart body is exactly `content_length` bytes.

    weko compares the *request's* Content-Length header (whole multipart body,
    boundary and part headers included) with the configured maximum, so the
    boundary cases are built on that number, not on the file size. The
    archive is the normal SimpleZip plus a stored zero-filled padding member.

    Valid when the request is sent by this suite's HTTP executor (httpx, 32
    character boundary, content type guessed from a `.zip` filename) with the
    same `filename`; another client changes the overhead. Fails when
    `content_length` is smaller than the smallest archive this can make
    (`min_content_length`). Memory-bound: meant for the lowered test limit
    (S0-12), not for the 15 GiB default.
    """
    overhead = multipart_overhead(filename, field_name, content_type)
    target_file_size = content_length - overhead
    smallest = _padded_zip(0)
    if target_file_size < len(smallest):
        raise ValueError(
            f"content_length {content_length} is below the minimum "
            f"{len(smallest) + overhead} for this filename"
        )
    data = _padded_zip(target_file_size - len(smallest))
    assert len(data) == target_file_size
    return data


def _padded_zip(padding: int) -> bytes:
    """Stored entries make the archive grow by exactly one byte per padding byte."""
    return build_zip(
        {"data/index.csv": import_csv([item_row("Sized")]), "data/pad.bin": bytes(padding)}
    )


def min_content_length(filename: str = "payload.zip") -> int:
    """The smallest Content-Length `sized_zip` can hit for this filename."""
    return len(_padded_zip(0)) + multipart_overhead(filename)


# ---------------------------------------------------------------------------
# Manifest and CLI
# ---------------------------------------------------------------------------


def manifest_document() -> dict[str, Any]:
    fixtures = []
    for fixture in catalogue():
        data = fixture.build()
        entry: dict[str, Any] = {
            "name": fixture.name,
            "packaging": fixture.packaging,
            "purpose": fixture.purpose,
            "bytes": len(data),
            "sha256": sha256_hex(data),
            "digest": digest_header(data),
        }
        if fixture.facts:
            entry["facts"] = fixture.facts
        fixtures.append(entry)
    return {"generatedBy": "seeds/build_fixtures.py", "fixtures": fixtures}


def manifest_text() -> str:
    return json.dumps(manifest_document(), indent=2, ensure_ascii=False) + "\n"


def cmd_build(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    text = manifest_text()
    if args.check:
        if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != text:
            sys.stderr.write(f"{manifest_path} is out of date; run build without --check\n")
            return 1
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for fixture in catalogue():
        (out / fixture.name).write_bytes(fixture.build())
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(text, encoding="utf-8")
    sys.stdout.write(f"wrote {len(catalogue())} fixtures to {out} and {manifest_path}\n")
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    sys.stdout.write(digest_header(Path(args.file).read_bytes()) + "\n")
    return 0


def cmd_put_item(args: argparse.Namespace) -> int:
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    data = put_item_zip(args.id, args.title)
    Path(args.out).write_bytes(data)
    sys.stdout.write(json.dumps({"out": args.out, "digest": digest_header(data)}) + "\n")
    return 0


def cmd_sized(args: argparse.Namespace) -> int:
    data = sized_zip(args.size, args.filename)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_bytes(data)
    info = {
        "out": args.out,
        "fileBytes": len(data),
        "contentLength": args.size,
        "digest": digest_header(data),
    }
    sys.stdout.write(json.dumps(info) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="write all fixtures and the manifest")
    build.add_argument("--out", default=str(ROOT / "fixtures" / "generated"))
    build.add_argument("--manifest", default=str(ROOT / "fixtures" / "manifest.json"))
    build.add_argument("--check", action="store_true", help="only verify the manifest")
    build.set_defaults(func=cmd_build)

    digest = sub.add_parser("digest", help="print the Digest header value of a file")
    digest.add_argument("file")
    digest.set_defaults(func=cmd_digest)

    put_item = sub.add_parser("put-item", help="EP4 body for one item with a given id")
    put_item.add_argument("--id", required=True)
    put_item.add_argument("--title", default="Test item A")
    put_item.add_argument("--out", required=True)
    put_item.set_defaults(func=cmd_put_item)

    sized = sub.add_parser("sized", help="zip making the multipart body an exact size")
    sized.add_argument("--size", type=int, required=True, help="Content-Length of the request")
    sized.add_argument("--filename", default="payload.zip", help="filename of the file part")
    sized.add_argument("--out", required=True)
    sized.set_defaults(func=cmd_sized)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
