import hashlib
import json
import sqlite3
import sys
import tempfile
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "notes/cloud_migration_manifest.json"


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf8"))


def test_missing_lookups_fails_closed():
    from src.build_cloud_migration_bundle import validate_lookups
    with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as folder:
        cfg = {"environment": {"lookups": "profiles2/lookups.dat"}, "locked_hashes": {"lookups": "x"}}
        try:
            validate_lookups(Path(folder), cfg)
        except FileNotFoundError as exc:
            assert "missing BRouter runtime dependency" in str(exc)
        else:
            raise AssertionError("missing lookups.dat was accepted")


def test_manifest_paths_are_sorted_unique_and_linux_relative():
    paths = [x["relative_path"] for x in manifest()["items"]]
    assert paths == sorted(paths)
    assert len(paths) == len(set(paths))
    assert all("\\" not in p and not Path(p).is_absolute() for p in paths)


def test_required_execution_payload_is_present():
    paths = {x["relative_path"] for x in manifest()["items"]}
    required = {
        "src/run_brouter_production.py", "src/route_segment_utils.py",
        "src/audit_routing_contract.py", "config/brouter_production.yaml",
        "data/processed/routing/production/production_manifest.parquet",
        "data/processed/routing/production/route_cache.sqlite",
        "scripts/start_brouter_linux.sh",
    }
    assert required <= paths


def test_payload_hashes_match_staging_copy():
    stage = ROOT / "data/interim/cloud_migration_bundle"
    for item in manifest()["items"]:
        assert sha256(stage / item["relative_path"]) == item["sha256"]


def test_locked_artifact_hashes_are_preserved():
    m = manifest()
    assert m["production_manifest_sha256"] == "9d9691a81ffa5f804224ee270890cf5acf579db8d53342574229d503290834ee"
    assert m["coordinate_artifact_sha256"] == "8e5b4bbe3511b0145234f209768f0eec0f766e9121716ae510170724dab1ad06"
    assert m["locked_hashes"]["brouter_jar"] == "93e9821640093cde82ed470ac8c08ab84fc7ae3b570e30c9ab41d686c7af1d4a"
    assert m["locked_hashes"]["lookups"] == "bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419"


def test_lookups_is_explicit_runtime_dependency():
    m = manifest()
    item = next(x for x in m["items"] if x["relative_path"].endswith("profiles2/lookups.dat"))
    assert item["category"] == "brouter_profile_runtime_dependency"
    assert item["sha256"] == "bf8fc3b2c052b7204e9c5a8d78e4d6ab6b125d3236a943f34583b838c477f419"
    assert "preflight" in item["required_for"]


def test_rd5_aliases_are_metadata_not_duplicate_payloads():
    m = manifest()
    assert m["rd5_runtime_aliases"] == {
        "data/raw/routing/E120_N20.rd5": "E120_N20_20260918.rd5",
        "data/raw/routing/E120_N25.rd5": "E120_N25_20260918.rd5",
    }
    paths = {x["relative_path"] for x in m["items"]}
    assert "data/raw/routing/E120_N20.rd5" not in paths
    assert "data/raw/routing/E120_N25.rd5" not in paths


def test_archive_has_no_raw_trip_files_or_unrelated_html():
    archive = ROOT / "data/interim/youbike_phase8_1b_cloud_bundle.tar.gz"
    with tarfile.open(archive, "r:gz") as tf:
        names = tf.getnames()
    assert not any(n.lower().endswith((".zip", ".csv")) for n in names)
    assert not any(n.lower().endswith(".html") for n in names)
    assert not any(n.endswith(("-wal", "-shm")) for n in names)


def test_cache_snapshot_is_integral_and_not_live_wal_copy():
    snapshot = ROOT / "data/interim/cloud_migration_bundle/data/processed/routing/production/route_cache.sqlite"
    with sqlite3.connect(snapshot) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = db.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    assert rows == manifest()["cache_snapshot"]["rows"]
    assert manifest()["cache_snapshot"]["method"].startswith("Python sqlite3 online backup API")


def test_bundle_does_not_claim_cloud_or_full_run_actions():
    receipt = json.loads((ROOT / "notes/cloud_migration_bundle_receipt.json").read_text())
    assert receipt["full_routing_launched"] is False
    assert receipt["cloud_resources_created"] is False
    assert receipt["upload_performed"] is False


def test_linux_launcher_has_no_windows_absolute_path():
    text = (ROOT / "scripts/start_brouter_linux.sh").read_text(encoding="utf8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "C:\\" not in text
    assert "btools.server.RouteServer" in text
    assert "ensure_alias E120_N20.rd5 E120_N20_20260918.rd5" in text
    assert "ensure_alias E120_N25.rd5 E120_N25_20260918.rd5" in text
    assert "Refusing wrong RD5 alias" in text
    assert "Missing required BRouter runtime file" in text


def test_runtime_modules_import_from_bundle(monkeypatch):
    src = ROOT / "data/interim/cloud_migration_bundle/src"
    monkeypatch.syspath_prepend(str(src))
    for name in ("route_segment_utils", "audit_routing_contract", "run_brouter_production"):
        __import__(name)
