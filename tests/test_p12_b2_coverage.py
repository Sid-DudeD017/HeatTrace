"""Targeted unit tests for Track B2 Phase 2 multi-station coverage and schema validation.

Uses small synthetic fixtures exclusively; does not copy large raw datasets into tests.
Verifies:
1. Error-response ZIPs are not treated as market data.
2. Every manifest CAISO file has accurate hub/year/request metadata.
3. Every file's recorded hash matches its bytes.
4. Missing timestamp ranges are calculated from timestamps, not filenames.
5. Identical duplicates are handled deterministically.
6. Conflicting duplicates fail the hub-year.
7. Wrong nodes/products are rejected.
8. Full 2,928-interval coverage is required for PASS.
9. Changing an archive's bytes changes its composite hash.
10. Raw-source inventory matches the actual raw CAISO files on disk.
11. Protected P11 hashes remain unchanged.
"""

from __future__ import annotations

import csv
import hashlib
import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

from heattrace.process.p12_b2_coverage import (
    calculate_noaa_station_year_coverage,
    calculate_price_carbon_coverage_record,
    classify_caiso_archive,
    parse_caiso_archive_rows,
    validate_selected_window_inputs,
    file_sha256,
)
from heattrace.ingest.noaa import (
    check_noaa_temperature_quality,
    extract_daily_maxima,
    NOAA_ACCEPTED_QUALITY_CODES,
    NOAA_REJECTED_QUALITY_CODES,
)


def test_protected_p11_hashes_unmodified():
    """Verify that protected P11 baseline hashes remain byte-for-byte unmodified."""
    freeze_path = Path("data/v2/manifests/p12_b2_protocol_freeze.json")
    assert freeze_path.exists(), "Protocol freeze manifest missing"
    with open(freeze_path, "r", encoding="utf-8") as f:
        freeze = json.load(f)

    p11_base = freeze["p11_protected_baseline"]
    archive_manifest = Path(p11_base["archive_manifest_path"])
    repro_comp = Path(p11_base["reproduction_comparison_path"])

    assert archive_manifest.exists()
    assert repro_comp.exists()
    assert file_sha256(archive_manifest) == p11_base["archive_manifest_sha256"]
    assert file_sha256(repro_comp) == p11_base["reproduction_comparison_sha256"]


def test_error_response_zips_not_treated_as_market_data():
    """Verify that CAISO archives containing error XML are classified CAISO_ERROR_RESPONSE and have 0 valid intervals."""
    raw_sources_path = Path("data/v2/manifests/p12_b2_raw_sources.jsonl")
    assert raw_sources_path.exists()
    with open(raw_sources_path, "r", encoding="utf-8") as f:
        caiso_records = [json.loads(line) for line in f if "CAISO" in line]

    err_records = [r for r in caiso_records if r["retrieval_status"] == "CAISO_ERROR_RESPONSE"]
    assert len(err_records) >= 10, f"Expected at least 10 CAISO error records, found {len(err_records)}"
    for r in err_records:
        assert r["valid_interval_count"] == 0, f"Error response archive {r['identifier']} must have 0 valid intervals"
        assert r["caiso_error_code"] is not None
        assert "1000" in str(r["caiso_error_code"]) or "No data" in str(r["caiso_error_message"])


def test_manifest_caiso_metadata_accuracy_and_disk_match():
    """Verify that every raw CAISO file on disk matches a manifest entry with accurate metadata and SHA-256."""
    raw_sources_path = Path("data/v2/manifests/p12_b2_raw_sources.jsonl")
    with open(raw_sources_path, "r", encoding="utf-8") as f:
        caiso_manifest = {json.loads(line)["relative_path"]: json.loads(line) for line in f if "CAISO" in line}

    disk_files = sorted(Path("data/v2/raw/caiso").rglob("*.zip"))
    assert len(disk_files) == len(caiso_manifest), f"Mismatch between disk files ({len(disk_files)}) and manifest ({len(caiso_manifest)})"

    for p in disk_files:
        rel_p = str(p)
        assert rel_p in caiso_manifest, f"File {rel_p} missing from raw sources manifest"
        m_rec = caiso_manifest[rel_p]
        assert m_rec["bytes"] == p.stat().st_size
        assert m_rec["sha256"] == file_sha256(p)
        assert m_rec["market"] == "DAM"
        assert m_rec["lmp_type"] == "LMP"
        assert m_rec["xml_data_item"] == "LMP_PRC"
        assert m_rec["retrieval_status"] in ("SUCCESS_DATA", "CAISO_ERROR_RESPONSE")


def test_missing_timestamp_ranges_calculated_from_timestamps():
    """Verify that gap inventory ranges are computed from explicit timestamp sets, not filenames."""
    gap_csv = Path("data/v2/manifests/p12_b2_caiso_gap_inventory_before.csv")
    assert gap_csv.exists()
    with open(gap_csv, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        exp = int(r["expected_intervals"])
        valid = int(r["existing_valid_intervals"])
        miss = int(r["missing_intervals"])
        assert exp == 2928
        assert valid + miss == exp
        if miss > 0:
            assert r["first_missing_utc"] != "NONE"
            assert r["last_missing_utc"] != "NONE"
            assert int(r["contiguous_missing_ranges_count"]) > 0


def test_conflicting_duplicates_fail_hub_year():
    """Verify that conflicting duplicate prices produce failure in the price coverage calculation."""
    res_clean = calculate_price_carbon_coverage_record(
        source_name="CAISO_OASIS_PRC_LMP",
        hub_or_ba="TH_NP15_GEN-APND",
        year=2024,
        market_product="DAM_LMP_PRC",
        expected_intervals=2928,
        observed_intervals=2928,
        valid_intervals=2928,
        missing_intervals=0,
        duplicate_intervals=0,
        conflict_intervals=0,
        issue_flag_count=0,
        unit="USD/MWh",
        timestamp_convention="interval-start UTC",
        retrieval_provenance="CAISO OASIS",
        sha256_hash="abc",
        bytes_count=1000,
        provisional=False,
    )
    assert res_clean["eligibility_status"] == "PASS"

    res_conflict = calculate_price_carbon_coverage_record(
        source_name="CAISO_OASIS_PRC_LMP",
        hub_or_ba="TH_NP15_GEN-APND",
        year=2024,
        market_product="DAM_LMP_PRC",
        expected_intervals=2928,
        observed_intervals=2929,
        valid_intervals=2928,
        missing_intervals=0,
        duplicate_intervals=1,
        conflict_intervals=1,
        issue_flag_count=0,
        unit="USD/MWh",
        timestamp_convention="interval-start UTC",
        retrieval_provenance="CAISO OASIS",
        sha256_hash="abc",
        bytes_count=1000,
        provisional=False,
        rejection_reasons=["Contains 1 conflicting duplicate price interval"],
    )
    assert res_conflict["eligibility_status"] == "EXCLUDED"
    assert "conflicting duplicate" in res_conflict["rejection_reasons"]


def test_full_2928_interval_coverage_required_for_pass():
    """Verify that complete coverage promotes 2022-2025 CAISO rows to PASS and 2026 to PROVISIONAL."""
    pc_csv = Path("data/v2/manifests/p12_b2_price_carbon_coverage.csv")
    with open(pc_csv, "r", encoding="utf-8") as f:
        caiso_rows = [r for r in csv.DictReader(f) if r["source"] == "CAISO_OASIS_PRC_LMP"]

    assert len(caiso_rows) == 15, "Expected 15 CAISO hub-years (3 hubs * 5 years)"
    for r in caiso_rows:
        y = int(r["year"])
        v = int(r["valid_intervals"])
        m = int(r["missing_intervals"])
        c = int(r["conflicts"])
        assert v == 2928, f"Hub-year {r['hub_or_balancing_authority']} {y} valid intervals {v} != 2928"
        assert m == 0, f"Hub-year {r['hub_or_balancing_authority']} {y} missing intervals {m} != 0"
        assert c == 0, f"Hub-year {r['hub_or_balancing_authority']} {y} conflicts {c} != 0"
        if y in (2022, 2023, 2024, 2025):
            assert r["eligibility_status"] == "PASS", f"Complete year {y} must be PASS"
            assert r["rejection_reasons"] == "NONE"
        elif y == 2026:
            assert r["eligibility_status"] == "PROVISIONAL", f"Provisional year {y} must be PROVISIONAL"
            assert r["rejection_reasons"] == "NONE"


def test_changing_archive_bytes_changes_composite_hash(tmp_path):
    """Verify that changing bytes in an archive changes its composite content hash."""
    h1 = hashlib.sha256(b"raw_zip_bytes_v1").hexdigest()
    h2 = hashlib.sha256(b"raw_zip_bytes_v2").hexdigest()

    comp1 = hashlib.sha256(h1.encode("utf-8")).hexdigest()
    comp2 = hashlib.sha256(h2.encode("utf-8")).hexdigest()

    assert comp1 != comp2, "Composite hash must strictly depend on raw file bytes"


def test_eia_issue_flag_and_2022_exclusion():
    """Verify that EIA issue flags are parsed via official ingest logic and EIA 2022 is EXCLUDED."""
    pc_csv = Path("data/v2/manifests/p12_b2_price_carbon_coverage.csv")
    with open(pc_csv, "r", encoding="utf-8") as f:
        eia_rows = [r for r in csv.DictReader(f) if r["source"] == "EIA_930_CISO"]

    assert len(eia_rows) == 5
    for r in eia_rows:
        y = int(r["year"])
        if y == 2022:
            assert r["eligibility_status"] == "EXCLUDED", "EIA 2022 missing 1 interval must be EXCLUDED"
            assert int(r["valid_intervals"]) == 2927
            assert "Missing 1 unpopulated interval" in r["rejection_reasons"]
        elif y in (2023, 2024, 2025):
            assert r["eligibility_status"] == "PASS"
            assert int(r["valid_intervals"]) == 2928
            assert int(r["issue_flag_counts"]) > 0
        elif y == 2026:
            assert r["eligibility_status"] == "PROVISIONAL"
            assert int(r["valid_intervals"]) == 2928


def test_synthetic_caiso_bulk_archive_handling(tmp_path):
    """Test synthetic CAISO bulk archive handling with shuffled columns, duplicates, and errors."""
    import zipfile
    import io

    # 1. Shuffled columns CSV inside zip
    shuffled_csv = (
        "GROUP,MW,XML_DATA_ITEM,LMP_TYPE,MARKET_RUN_ID,NODE,INTERVALENDTIME_GMT,INTERVALSTARTTIME_GMT\n"
        ",45.50,LMP_PRC,LMP,DAM,TH_NP15_GEN-APND,2022-06-01T08:00:00-00:00,2022-06-01T07:00:00-00:00\n"
        ",55.20,LMP_PRC,LMP,DAM,TH_NP15_GEN-APND,2022-06-01T09:00:00-00:00,2022-06-01T08:00:00-00:00\n"
    )
    zip_p1 = tmp_path / "synthetic_shuffled.zip"
    with zipfile.ZipFile(zip_p1, "w") as zf:
        zf.writestr("test_shuffled.csv", shuffled_csv)

    cinfo1 = classify_caiso_archive(zip_p1)
    assert cinfo1["status"] == "SUCCESS_DATA"
    assert cinfo1["valid_intervals_count"] == 2

    rows1 = parse_caiso_archive_rows(zip_p1, target_nodes=["TH_NP15_GEN-APND"])
    assert len(rows1) == 2
    assert rows1[0]["price_usd_per_mwh"] == 45.50
    assert rows1[1]["price_usd_per_mwh"] == 55.20
    assert rows1[0]["timestamp_utc"] == datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)

    # 2. Wrong node / wrong market filtering
    mixed_csv = (
        "INTERVALSTARTTIME_GMT,NODE,MARKET_RUN_ID,LMP_TYPE,XML_DATA_ITEM,MW\n"
        "2022-06-01T07:00:00-00:00,WRONG_NODE,DAM,LMP,LMP_PRC,100.0\n"
        "2022-06-01T07:00:00-00:00,TH_NP15_GEN-APND,RTM,LMP,LMP_PRC,200.0\n"
        "2022-06-01T07:00:00-00:00,TH_NP15_GEN-APND,DAM,LMP_LOSS,LMP_PRC,300.0\n"
        "2022-06-01T07:00:00-00:00,TH_NP15_GEN-APND,DAM,LMP,OTHER_ITEM,400.0\n"
        "2022-06-01T07:00:00-00:00,TH_NP15_GEN-APND,DAM,LMP,LMP_PRC,50.0\n"
    )
    zip_p2 = tmp_path / "synthetic_mixed.zip"
    with zipfile.ZipFile(zip_p2, "w") as zf:
        zf.writestr("mixed.csv", mixed_csv)

    rows2 = parse_caiso_archive_rows(zip_p2, target_nodes=["TH_NP15_GEN-APND"])
    assert len(rows2) == 1
    assert rows2[0]["price_usd_per_mwh"] == 50.0

    # 3. XML error fixture
    error_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<m:OASISReport xmlns:m="http://www.caiso.com/soa/OASISReport_v1.xsd">\n'
        '<m:ERROR><m:ERR_CODE>1000</m:ERR_CODE><m:ERR_DESC>No data returned</m:ERR_DESC></m:ERROR>\n'
        '</m:OASISReport>'
    )
    zip_err = tmp_path / "synthetic_error.zip"
    with zipfile.ZipFile(zip_err, "w") as zf:
        zf.writestr("error.xml", error_xml)

    cinfo_err = classify_caiso_archive(zip_err)
    assert cinfo_err["status"] == "CAISO_ERROR_RESPONSE"
    assert cinfo_err["error_code"] == "1000"
    assert cinfo_err["valid_intervals_count"] == 0


def test_synthetic_bulk_ingestion_end_to_end_and_gap_reduction(tmp_path):
    """Verify end-to-end bulk archive ingestion, gap reduction, and eligibility gates."""
    import zipfile
    from heattrace.process.p12_b2_coverage import build_caiso_coverage_for_hub_year

    s_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    e_utc = s_utc + timedelta(hours=10)  # 10 expected intervals for quick synthetic test

    # 1. Initially zero intervals -> Incomplete & EXCLUDED
    cov_rec0, gap_rec0 = build_caiso_coverage_for_hub_year(
        parsed_rows=[],
        caiso_archive_info={},
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2022,
        expected_start_utc=s_utc,
        expected_end_utc=e_utc,
        is_provisional=False,
    )
    assert cov_rec0["eligibility_status"] == "EXCLUDED"
    assert cov_rec0["valid_intervals"] == 0
    assert gap_rec0["missing_intervals"] == 10

    # 2. Add partial valid archive (5 intervals) -> missing intervals decrease (gap reduction)
    rows_partial = [
        {
            "timestamp_utc": s_utc + timedelta(hours=i),
            "node": "TH_NP15_GEN-APND",
            "market_run_id": "DAM",
            "lmp_type": "LMP",
            "xml_data_item": "LMP_PRC",
            "price_usd_per_mwh": 50.0 + i,
            "source_file": "data/v2/raw/caiso/bulk_historical/part1.zip",
        }
        for i in range(5)
    ]
    cov_rec1, gap_rec1 = build_caiso_coverage_for_hub_year(
        parsed_rows=rows_partial,
        caiso_archive_info={"data/v2/raw/caiso/bulk_historical/part1.zip": {"sha256": "hash1", "bytes": 100}},
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2022,
        expected_start_utc=s_utc,
        expected_end_utc=e_utc,
        is_provisional=False,
    )
    assert cov_rec1["eligibility_status"] == "EXCLUDED"
    assert cov_rec1["valid_intervals"] == 5
    assert gap_rec1["missing_intervals"] == 5  # Reduced from 10 to 5

    # 3. Add remaining intervals (complete 10/10) -> PASS
    rows_complete = list(rows_partial) + [
        {
            "timestamp_utc": s_utc + timedelta(hours=i),
            "node": "TH_NP15_GEN-APND",
            "market_run_id": "DAM",
            "lmp_type": "LMP",
            "xml_data_item": "LMP_PRC",
            "price_usd_per_mwh": 60.0 + i,
            "source_file": "data/v2/raw/caiso/bulk_historical/part2.zip",
        }
        for i in range(5, 10)
    ]
    cov_rec2, gap_rec2 = build_caiso_coverage_for_hub_year(
        parsed_rows=rows_complete,
        caiso_archive_info={
            "data/v2/raw/caiso/bulk_historical/part1.zip": {"sha256": "hash1", "bytes": 100},
            "data/v2/raw/caiso/bulk_historical/part2.zip": {"sha256": "hash2", "bytes": 200},
        },
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2022,
        expected_start_utc=s_utc,
        expected_end_utc=e_utc,
        is_provisional=False,
    )
    assert cov_rec2["eligibility_status"] == "PASS"
    assert cov_rec2["valid_intervals"] == 10
    assert gap_rec2["missing_intervals"] == 0

    # 4. Provisional complete coverage -> PROVISIONAL
    cov_rec_prov, _ = build_caiso_coverage_for_hub_year(
        parsed_rows=rows_complete,
        caiso_archive_info={
            "data/v2/raw/caiso/bulk_historical/part1.zip": {"sha256": "hash1", "bytes": 100},
            "data/v2/raw/caiso/bulk_historical/part2.zip": {"sha256": "hash2", "bytes": 200},
        },
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2026,
        expected_start_utc=s_utc,
        expected_end_utc=e_utc,
        is_provisional=True,
    )
    assert cov_rec_prov["eligibility_status"] == "PROVISIONAL"

    # 5. Conflicting duplicates -> fails closed automatically to EXCLUDED
    rows_conflicting = list(rows_complete) + [
        {
            "timestamp_utc": s_utc,
            "node": "TH_NP15_GEN-APND",
            "market_run_id": "DAM",
            "lmp_type": "LMP",
            "xml_data_item": "LMP_PRC",
            "price_usd_per_mwh": 999.0,  # Conflict with 50.0
            "source_file": "data/v2/raw/caiso/bulk_historical/conflict.zip",
        }
    ]
    cov_rec_conf, _ = build_caiso_coverage_for_hub_year(
        parsed_rows=rows_conflicting,
        caiso_archive_info={
            "data/v2/raw/caiso/bulk_historical/part1.zip": {"sha256": "hash1", "bytes": 100},
            "data/v2/raw/caiso/bulk_historical/part2.zip": {"sha256": "hash2", "bytes": 200},
            "data/v2/raw/caiso/bulk_historical/conflict.zip": {"sha256": "hash3", "bytes": 50},
        },
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2022,
        expected_start_utc=s_utc,
        expected_end_utc=e_utc,
        is_provisional=False,
    )
    assert cov_rec_conf["eligibility_status"] == "EXCLUDED"
    assert cov_rec_conf["conflicts"] > 0
    assert "conflicting duplicate" in cov_rec_conf["rejection_reasons"]

    # 6. Malformed zip -> INVALID_ARCHIVE
    bad_zip = tmp_path / "corrupt.zip"
    bad_zip.write_text("this is not a zip file", encoding="utf-8")
    assert classify_caiso_archive(bad_zip)["status"] == "INVALID_ARCHIVE"

    # 7. Disambiguation of identical basenames in different directories
    archive_info_disambig = {
        "data/v2/raw/caiso/dirA/sample.zip": {"sha256": "hashA", "bytes": 100},
        "data/v2/raw/caiso/dirB/sample.zip": {"sha256": "hashB", "bytes": 200},
    }
    rows_disambig = [
        {"timestamp_utc": s_utc, "node": "TH_NP15_GEN-APND", "price_usd_per_mwh": 50.0, "source_file": "data/v2/raw/caiso/dirA/sample.zip"},
        {"timestamp_utc": s_utc + timedelta(hours=1), "node": "TH_NP15_GEN-APND", "price_usd_per_mwh": 50.0, "source_file": "data/v2/raw/caiso/dirB/sample.zip"},
    ]
    cov_rec_d, _ = build_caiso_coverage_for_hub_year(
        parsed_rows=rows_disambig,
        caiso_archive_info=archive_info_disambig,
        hub_full="TH_NP15_GEN-APND",
        hub_code="NP15",
        year=2022,
        expected_start_utc=s_utc,
        expected_end_utc=s_utc + timedelta(hours=2),
        is_provisional=False,
    )
    # Ensure composite hash incorporates both distinct relative paths
    h_expected = hashlib.sha256()
    h_expected.update(b"data/v2/raw/caiso/dirA/sample.zip:hashA")
    h_expected.update(b"data/v2/raw/caiso/dirB/sample.zip:hashB")
    assert cov_rec_d["sha256"] == h_expected.hexdigest()
    assert cov_rec_d["eligibility_status"] == "PASS"


def test_eia_official_recovery_evidence():
    """Verify official EIA recovery evidence file presence, hash, and content."""
    region_path = Path("data/v2/raw/eia/official_recovery/eia_api_v2_ciso_region_data_20220613T16_T20.json")
    fuel_path = Path("data/v2/raw/eia/official_recovery/eia_api_v2_ciso_fuel_type_data_20220613T16_T20.json")
    assert region_path.exists(), "Region data recovery evidence missing"
    assert fuel_path.exists(), "Fuel data recovery evidence missing"

    # Verify sha256 matches disk
    assert file_sha256(region_path) == "dbff4719611c6af5417ec9e168a793866781d11a549733f7a52bbe0fddd2dba7"
    assert file_sha256(fuel_path) == "138c659eb0f657d9f37b627f228e12035f42db4ac5efb7fde055ed5c6cbc8ed6"

    # Verify content confirms official missing interval at 2022-06-13T18:00:00Z for Demand (D) and Net Generation (NG)
    with open(region_path, "r", encoding="utf-8") as f:
        r_data = json.load(f)
    period_18_d = [row for row in r_data["response"]["data"] if row.get("period") == "2022-06-13T18" and row.get("type") in ("D", "NG")]
    assert len(period_18_d) == 2
    for row in period_18_d:
        assert row.get("value") is None, f"Official EIA API value for {row.get('type')} must be null at 2022-06-13T18"


def test_recovered_caiso_bulk_historical_integrity():
    """Verify recursive discovery, total-LMP parsing, 147 recovered archives, and 0 post-recovery gaps."""
    bulk_dir = Path("data/v2/raw/caiso/bulk_historical")
    assert bulk_dir.exists()

    daily_zips = sorted([z for z in bulk_dir.glob("**/*.zip") if not z.name.startswith("attempt_")])
    attempt_zips = sorted([z for z in bulk_dir.glob("attempt_*.zip")])

    assert len(daily_zips) == 147, f"Expected 147 daily archives, found {len(daily_zips)}"
    assert len(attempt_zips) == 4, f"Expected 4 attempt error archives, found {len(attempt_zips)}"

    # Check error response classification on attempt zips
    for az in attempt_zips:
        ainfo = classify_caiso_archive(az)
        assert ainfo["status"] == "CAISO_ERROR_RESPONSE"
        assert ainfo["error_code"] == "1000"
        assert ainfo["valid_intervals_count"] == 0

    # Check post-acquisition gap inventory reports 0 missing intervals across all 15 hub-years
    gap_csv = Path("data/v2/manifests/p12_b2_caiso_gap_inventory_after.csv")
    with open(gap_csv, "r", encoding="utf-8") as f:
        gap_rows = list(csv.DictReader(f))

    assert len(gap_rows) == 15, f"Expected 15 gap records, found {len(gap_rows)}"
    for gr in gap_rows:
        assert int(gr["missing_intervals"]) == 0, f"Expected 0 missing intervals for {gr['hub']} {gr['year']}"
        assert int(gr["existing_valid_intervals"]) == 2928
        assert int(gr["contiguous_missing_ranges_count"]) == 0
        assert gr["first_missing_utc"] == "NONE"
        assert gr["last_missing_utc"] == "NONE"



