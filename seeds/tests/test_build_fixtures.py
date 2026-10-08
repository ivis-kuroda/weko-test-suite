import hashlib
import io
import json
import zipfile
from pathlib import Path

import build_fixtures as bf
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
BY_NAME = {fixture.name: fixture for fixture in bf.catalogue()}


def names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def read(data: bytes, member: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(member)


def bag_problems(data: bytes) -> list[str]:
    """What bagit-python's validate() would object to, for the cases we build."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        present = set(archive.namelist())
        if "bagit.txt" not in present:
            return ["bagit.txt missing"]
        problems = []
        listed = set()
        for line in archive.read("manifest-sha256.txt").decode().splitlines():
            checksum, path = line.split("  ", 1)
            listed.add(path)
            if path not in present:
                problems.append(f"{path} missing")
            elif hashlib.sha256(archive.read(path)).hexdigest() != checksum:
                problems.append(f"{path} checksum")
        payload = {n for n in present if n.startswith("data/") and not n.endswith("/")}
        problems += [f"{n} not in manifest" for n in sorted(payload - listed)]
        for line in archive.read("tagmanifest-sha256.txt").decode().splitlines():
            checksum, path = line.split("  ", 1)
            if hashlib.sha256(archive.read(path)).hexdigest() != checksum:
                problems.append(f"{path} tag checksum")
        octets, count = (
            archive.read("bag-info.txt").decode().split("Payload-Oxum: ")[1].split()[0].split(".")
        )
        if (int(octets), int(count)) != (
            sum(len(archive.read(n)) for n in payload),
            len(payload),
        ):
            problems.append("Payload-Oxum")
        return problems


def test_every_fixture_is_reproducible():
    for fixture in bf.catalogue():
        assert fixture.build() == fixture.build(), fixture.name


def test_committed_manifest_is_current():
    committed = (ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8")
    assert committed == bf.manifest_text(), "run: python seeds/build_fixtures.py build"


def test_manifest_hashes_and_digests_agree():
    for entry in json.loads(bf.manifest_text())["fixtures"]:
        data = BY_NAME[entry["name"]].build()
        assert entry["bytes"] == len(data)
        assert entry["digest"] == "SHA-256=" + hashlib.sha256(data).hexdigest()


def test_digest_matches_the_weko_test_helper_algorithm():
    data = bf.build_zip({"a.txt": b"x" * 10000})
    body = io.BytesIO(data)
    calculator = hashlib.sha256()  # weko tests/helpers.py calculate_hash, verbatim
    for byte_block in iter(lambda: body.read(4096), b""):
        calculator.update(byte_block)
    assert bf.digest_header(data) == f"SHA-256={calculator.hexdigest()}"


@pytest.mark.parametrize("name", ["bagit-normal.zip", "rocrate-normal.zip"])
def test_normal_bags_are_valid(name):
    assert bag_problems(BY_NAME[name].build()) == []


def test_normal_layouts():
    simple = names(BY_NAME["simplezip-normal.zip"].build())
    assert "data/index.csv" in simple and bf.SWORD_METADATA_FILE not in simple
    bagit = names(BY_NAME["bagit-normal.zip"].build())
    assert bf.SWORD_METADATA_FILE in bagit and "bagit.txt" in bagit
    assert bf.ROCRATE_METADATA_FILE in names(BY_NAME["rocrate-normal.zip"].build())


def test_broken_zip_cannot_be_opened():
    data = BY_NAME["broken.zip"].build()
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(data))


def test_checksum_mismatch_and_missing_bagit_txt_fail_validation():
    assert bag_problems(BY_NAME["bagit-checksum-mismatch.zip"].build()) == [
        "data/data.csv checksum"
    ]
    assert bag_problems(BY_NAME["bagit-no-bagit-txt.zip"].build()) == ["bagit.txt missing"]


def test_metadata_defects_leave_the_bag_itself_valid():
    for name in ("bagit-non-utf8-metadata.zip", "bagit-jsonld-syntax-error.zip"):
        assert bag_problems(BY_NAME[name].build()) == [], name
    assert bf.SWORD_METADATA_FILE not in names(BY_NAME["bagit-missing-metadata.zip"].build())
    assert bag_problems(BY_NAME["bagit-missing-metadata.zip"].build()) == []


def test_non_utf8_metadata_is_not_utf8_at_the_recorded_offset():
    fixture = BY_NAME["bagit-non-utf8-metadata.zip"]
    raw = read(fixture.build(), bf.SWORD_METADATA_FILE)
    with pytest.raises(UnicodeDecodeError) as caught:
        raw.decode("utf-8")
    assert caught.value.start == fixture.facts["byteOffset"]


def test_jsonld_syntax_error_position_is_recorded():
    fixture = BY_NAME["bagit-jsonld-syntax-error.zip"]
    raw = read(fixture.build(), bf.SWORD_METADATA_FILE).decode("utf-8")
    with pytest.raises(json.JSONDecodeError) as caught:
        json.loads(raw)
    assert (caught.value.lineno, caught.value.colno) == (
        fixture.facts["line"],
        fixture.facts["column"],
    )
    assert fixture.facts["line"] > 1


def test_packaging_defects():
    assert bf.SWORD_METADATA_FILE in names(BY_NAME["simplezip-with-sword-json.zip"].build())
    crate = names(BY_NAME["rocrate-missing-metadata.zip"].build())
    assert "ro-crate-metadata.json" in crate and bf.ROCRATE_METADATA_FILE not in crate
    assert any(n.endswith(".xml") for n in names(BY_NAME["simplezip-xml.zip"].build()))


def test_multi_item_and_put_item_rows():
    multi = read(BY_NAME["simplezip-multi-item.zip"].build(), "data/index.csv").decode()
    assert len(multi.splitlines()) == 5 + 2
    without_id = read(BY_NAME["put-item-without-id.zip"].build(), "data/index.csv").decode()
    assert without_id.splitlines()[5].startswith(",")
    with_id = read(bf.put_item_zip("42"), "data/index.csv").decode()
    assert with_id.splitlines()[5].startswith("42,")


def test_similar_fixtures_differ_only_in_content():
    a = BY_NAME["simplezip-title-a.zip"].build()
    similar = BY_NAME["simplezip-title-a-similar.zip"].build()
    assert a != similar
    assert read(a, "data/index.csv") == read(similar, "data/index.csv")


@pytest.mark.parametrize("total", [None, 1, 2, 1000])
@pytest.mark.parametrize("filename", ["payload.zip", "p.zip"])
def test_sized_zip_makes_the_multipart_body_exactly_that_long(total, filename):
    minimum = bf.min_content_length(filename)
    size = minimum + {None: 0, 1: 1, 2: 2, 1000: 1000}[total]
    data = bf.sized_zip(size, filename)
    request = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ).build_request("POST", "http://x.invalid/", files={"file": (filename, data)})
    assert len(request.read()) == size
    assert int(request.headers["content-length"]) == size


def test_sized_zip_refuses_a_size_below_the_minimum():
    with pytest.raises(ValueError):
        bf.sized_zip(bf.min_content_length() - 1)


def test_cli_check_passes_on_the_committed_manifest():
    assert bf.main(["build", "--check"]) == 0


def test_cli_writes_files(tmp_path):
    out = tmp_path / "gen"
    assert bf.main(["build", "--out", str(out), "--manifest", str(tmp_path / "m.json")]) == 0
    assert (out / "bagit-normal.zip").read_bytes() == BY_NAME["bagit-normal.zip"].build()


def test_no_title_fixture_has_an_empty_title_cell():
    row = read(BY_NAME["simplezip-no-title.zip"].build(), "data/index.csv").decode().splitlines()[5]
    cells = row.split("\t") if "\t" in row else row.split(",")
    assert "" in cells
    normal_zip = BY_NAME["simplezip-normal.zip"].build()
    normal = read(normal_zip, "data/index.csv").decode().splitlines()[5]
    assert row != normal
