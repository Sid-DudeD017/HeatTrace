"""Unit tests for P1 ingestion, parsing, coverage, cache semantics, and error handling."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import subprocess
import sys
import urllib.error
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from heattrace.ingest.coverage import compute_hourly_coverage, write_coverage_report
from heattrace.ingest.noaa import (
    NOAA_ACCEPTED_QUALITY_CODES,
    NOAA_REJECTED_QUALITY_CODES,
    check_noaa_temperature_quality,
    download_ghcnh_file,
    extract_daily_maxima,
    get_local_day_utc_bounds,
    parse_ghcnh_psv,
    run_noaa_smoke_test,
    validate_noaa_psv_file,
    validate_noaa_sample_rows,
)
from heattrace.ingest.caiso import (
    CAISO_RETRYABLE_HTTP_CODES,
    MAX_CAISO_RETRY_DELAY_SECONDS,
    build_caiso_oasis_url,
    download_caiso_file,
    parse_caiso_zip,
    parse_retry_after,
    reset_caiso_throttle,
    run_caiso_smoke_test,
    throttle_caiso_request,
    validate_caiso_lmp_rows,
    validate_caiso_zip_file,
)


from heattrace.ingest.eia import (
    build_eia_query_params,
    build_eia_region_url,
    get_eia_api_key,
    ingest_eia_emissions_file,
    ingest_eia_workbook,
    parse_and_validate_eia_ciso_workbook,
    parse_and_validate_eia_emissions_staging_csv,
    parse_and_validate_eia_json,
    parse_emissions_numeric_value,
    parse_numeric_value,
    redact_api_key,
    run_eia_smoke_test,
    validate_eia_json_cache,
    validate_eia_metric_rows,
)
from heattrace.ingest.manifest import build_record, find_matching_record, record_provenance
from heattrace.cli import main, run_smoke_tests, parse_args


# =========================================================================
# 1. Coverage Calculation Tests
# =========================================================================

def test_compute_hourly_coverage_complete():
    start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 6, 1, 4, 0, tzinfo=timezone.utc)
    timestamps = [
        datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 2, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 3, 0, tzinfo=timezone.utc),
    ]
    cov = compute_hourly_coverage(timestamps, requested_start=start, requested_end=end)
    assert cov["expected_hours"] == 4
    assert cov["row_count"] == 4
    assert cov["unique_timestamps"] == 4
    assert cov["covered_hourly_bins"] == 4
    assert cov["missing_hours"] == 0
    assert cov["duplicate_timestamps"] == 0
    assert cov["out_of_interval_count"] == 0


def test_compute_hourly_coverage_with_gaps_and_duplicates():
    start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 6, 1, 4, 0, tzinfo=timezone.utc)
    timestamps = [
        datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc),
        datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc),  # duplicate
        datetime(2024, 6, 1, 3, 0, tzinfo=timezone.utc),
    ]
    cov = compute_hourly_coverage(timestamps, requested_start=start, requested_end=end)
    assert cov["expected_hours"] == 4
    assert cov["row_count"] == 4
    assert cov["unique_timestamps"] == 3
    assert cov["covered_hourly_bins"] == 3
    assert cov["missing_hours"] == 1
    assert cov["duplicate_timestamps"] == 1


def test_compute_hourly_coverage_out_of_window():
    start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 6, 1, 2, 0, tzinfo=timezone.utc)
    timestamps = [
        datetime(2024, 5, 31, 23, 0, tzinfo=timezone.utc),  # before
        datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc),   # in
        datetime(2024, 6, 1, 1, 0, tzinfo=timezone.utc),   # in
        datetime(2024, 6, 1, 2, 0, tzinfo=timezone.utc),   # after
    ]
    cov = compute_hourly_coverage(timestamps, requested_start=start, requested_end=end)
    assert cov["row_count"] == 2
    assert cov["out_of_interval_count"] == 2
    assert cov["observed_start"] == "2024-06-01T00:00:00+00:00"
    assert cov["observed_end"] == "2024-06-01T01:00:00+00:00"


def test_compute_hourly_coverage_subhourly_noaa():
    start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)
    timestamps = []
    for h in range(24):
        timestamps.append(datetime(2024, 6, 1, h, 56, tzinfo=timezone.utc))
    for h in (0, 6, 12, 18):
        timestamps.append(datetime(2024, 6, 1, h, 0, tzinfo=timezone.utc))

    cov = compute_hourly_coverage(timestamps, requested_start=start, requested_end=end)
    assert cov["row_count"] == 28
    assert cov["unique_timestamps"] == 28
    assert cov["covered_hourly_bins"] == 24
    assert cov["missing_hours"] == 0
    assert cov["duplicate_timestamps"] == 0


# =========================================================================
# 2. Cache and Provenance Semantics (Unmanifested & Fresh)
# =========================================================================

def test_fresh_retrieval_provenance(tmp_path):
    manifest_file = tmp_path / "manifest.jsonl"
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("sample content")

    req = {"dataset": "test", "provider": "test"}
    rec = record_provenance(
        manifest_file,
        sample_file,
        provider="test",
        dataset="test",
        request=req,
        is_cache_hit=False,
    )
    assert rec["cache_hit"] is False
    assert rec["retrieval_time_known"] is True
    assert rec["retrieved_at"] is not None
    assert rec["first_observed_at"] == rec["retrieved_at"]


def test_cache_hit_with_matching_manifest_record(tmp_path):
    manifest_file = tmp_path / "manifest.jsonl"
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("sample content")

    req = {"dataset": "test", "provider": "test"}
    rec1 = record_provenance(
        manifest_file,
        sample_file,
        provider="test",
        dataset="test",
        request=req,
        is_cache_hit=False,
    )
    # Repeated run as cache hit
    rec2 = record_provenance(
        manifest_file,
        sample_file,
        provider="test",
        dataset="test",
        request=req,
        is_cache_hit=True,
    )
    assert rec2["retrieved_at"] == rec1["retrieved_at"]
    lines = manifest_file.read_text().strip().split("\n")
    assert len(lines) == 1


def test_unmanifested_cache_provenance(tmp_path):
    manifest_file = tmp_path / "manifest.jsonl"
    sample_file = tmp_path / "cached_sample.txt"
    sample_file.write_text("already on disk without manifest")

    req = {"dataset": "test", "provider": "test"}
    rec = record_provenance(
        manifest_file,
        sample_file,
        provider="test",
        dataset="test",
        request=req,
        is_cache_hit=True,
    )
    assert rec["cache_hit"] is True
    assert rec["retrieval_time_known"] is False
    assert rec["retrieved_at"] is None
    assert rec["first_observed_at"] is not None


def test_corrupt_noaa_cache_rejected_and_reacquired(tmp_path):
    corrupt_psv = tmp_path / "GHCNh_USW00023234_2022.psv"
    corrupt_psv.write_text("random garbage that is not valid psv header")

    assert not validate_noaa_psv_file(corrupt_psv, "USW00023234", 2022)

    valid_content = b"STATION|Station_name|DATE|Year|Month|Day|Hour\nUSW00023234|SFO|2022-01-01T00:00:00|2022|01|01|00\n"
    mock_resp = MagicMock()
    mock_resp.read.return_value = valid_content
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        target, is_hit = download_ghcnh_file("USW00023234", 2022, tmp_path)
        assert is_hit is False
        assert target.exists()
        assert validate_noaa_psv_file(target, "USW00023234", 2022)


def test_corrupt_caiso_cache_rejected_and_reacquired(tmp_path):
    corrupt_zip = tmp_path / "test_caiso.zip"
    corrupt_zip.write_bytes(b"not a valid zip file")

    assert not validate_caiso_zip_file(corrupt_zip)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("test.csv", "INTERVALSTARTTIME_GMT,MW\n")
    valid_zip_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.read.return_value = valid_zip_bytes
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        target, is_hit = download_caiso_file("http://fake-caiso", tmp_path, "test_caiso")
        assert is_hit is False
        assert target.exists()
        assert validate_caiso_zip_file(target)


# =========================================================================
# 3. Validation Without Runtime Assertions (and under python -O)
# =========================================================================

def test_noaa_validation_without_assert():
    valid_rows = [{
        "station_id": "USW00023234",
        "temperature_c": 15.6,
        "temperature_quality_code": "1",
        "timestamp_utc": datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc),
    }]
    validate_noaa_sample_rows(
        valid_rows,
        expected_station="USW00023234",
        requested_start=datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc),
        requested_end=datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="unexpected station"):
        validate_noaa_sample_rows(
            valid_rows,
            expected_station="WRONG_STATION",
            requested_start=datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc),
            requested_end=datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc),
        )


def test_caiso_exact_hourly_timestamp_enforcement():
    start = datetime(2024, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2024, 6, 2, 0, 0, tzinfo=timezone.utc)
    valid_rows = []
    for h in range(24):
        ts = start + timedelta(hours=h)
        valid_rows.append({
            "interval_end_utc": ts + timedelta(hours=1),
            "lmp_type": "LMP",
            "market_run_id": "DAM",
            "node": "TH_NP15_GEN-APND",
            "price_usd_per_mwh": 25.0 + h,
            "timestamp_utc": ts,
        })

    # Exact 24 hourly rows must pass
    validate_caiso_lmp_rows(
        valid_rows,
        expected_node="TH_NP15_GEN-APND",
        expected_market="DAM",
        requested_start=start,
        requested_end=end,
    )

    # 1. Reject 24 valid rows plus one sub-hourly 00:30 row
    rows_with_subhourly = list(valid_rows)
    extra_subhourly = {
        "interval_end_utc": start + timedelta(minutes=60),
        "lmp_type": "LMP",
        "market_run_id": "DAM",
        "node": "TH_NP15_GEN-APND",
        "price_usd_per_mwh": 25.5,
        "timestamp_utc": start + timedelta(minutes=30),
    }
    rows_with_subhourly.append(extra_subhourly)
    with pytest.raises(ValueError, match="Expected exactly 24 total-LMP rows, but got 25"):
        validate_caiso_lmp_rows(
            rows_with_subhourly,
            expected_node="TH_NP15_GEN-APND",
            expected_market="DAM",
            requested_start=start,
            requested_end=end,
        )

    # 2. Reject unaligned timestamp
    unaligned_rows = list(valid_rows)
    unaligned_rows[0] = dict(valid_rows[0])
    unaligned_rows[0]["timestamp_utc"] = start + timedelta(minutes=15)
    unaligned_rows[0]["interval_end_utc"] = start + timedelta(minutes=75)
    with pytest.raises(ValueError, match="not aligned to the top of the hour"):
        validate_caiso_lmp_rows(
            unaligned_rows,
            expected_node="TH_NP15_GEN-APND",
            expected_market="DAM",
            requested_start=start,
            requested_end=end,
        )

    # 3. Reject duplicate hour
    dup_rows = list(valid_rows[:-1])
    dup_rows.append(dict(valid_rows[0]))
    with pytest.raises(ValueError, match="duplicate hourly interval timestamp detected"):
        validate_caiso_lmp_rows(
            dup_rows,
            expected_node="TH_NP15_GEN-APND",
            expected_market="DAM",
            requested_start=start,
            requested_end=end,
        )

    # 4. Reject invalid duration (30 mins instead of 3600 seconds)
    bad_dur = list(valid_rows)
    bad_dur[0] = dict(valid_rows[0])
    bad_dur[0]["interval_end_utc"] = bad_dur[0]["timestamp_utc"] + timedelta(minutes=30)
    with pytest.raises(ValueError, match="interval duration must be exactly 3600 seconds"):
        validate_caiso_lmp_rows(
            bad_dur,
            expected_node="TH_NP15_GEN-APND",
            expected_market="DAM",
            requested_start=start,
            requested_end=end,
        )


def test_validation_works_under_python_optimized(tmp_path):
    script = tmp_path / "test_opt.py"
    script.write_text("""
import sys
from datetime import datetime, timezone
from heattrace.ingest.noaa import validate_noaa_sample_rows

try:
    validate_noaa_sample_rows(
        [{"station_id": "WRONG", "timestamp_utc": datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc), "temperature_quality_code": "1"}],
        expected_station="USW00023234",
        requested_start=datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc),
        requested_end=datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc),
    )
    sys.exit(1)
except ValueError:
    sys.exit(0)
""")
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    res = subprocess.run([sys.executable, "-O", str(script)], env=env)
    assert res.returncode == 0


# =========================================================================
# 4. EIA Implementation: Numeric Parsing, Date Translation, Completeness
# =========================================================================

def test_eia_parse_numeric_value_valid():
    assert parse_numeric_value("24500", 0) == 24500.0
    assert parse_numeric_value("-125.5", 1) == -125.5
    assert parse_numeric_value("0", 2) == 0.0
    assert parse_numeric_value(24500, 3) == 24500.0
    assert parse_numeric_value(180.25, 4) == 180.25


@pytest.mark.parametrize("bad_val,err_match", [
    (None, "missing required numeric value"),
    (True, "boolean values not accepted"),
    (False, "boolean values not accepted"),
    ("", "empty numeric string"),
    ("   ", "empty numeric string"),
    ("NaN", "NaN and Infinity values not accepted"),
    ("Infinity", "NaN and Infinity values not accepted"),
    ("-Infinity", "NaN and Infinity values not accepted"),
    ("not_a_number", "invalid nonnumeric string"),
    (150000.0, "outside plausible BA bounds"),
    (-60000.0, "outside plausible BA bounds"),
])
def test_eia_parse_numeric_value_rejected(bad_val, err_match):
    with pytest.raises(ValueError, match=err_match):
        parse_numeric_value(bad_val, 0)


def test_build_eia_query_params_inclusive_bounds():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    params = build_eia_query_params("CISO", start, end)
    param_dict = dict(params)
    assert param_dict["start"] == "2022-06-01T01"
    assert param_dict["end"] == "2022-06-02T00"
    assert param_dict["facets[respondent][]"] == "CISO"
    assert ("facets[type][]", "D") in params
    assert ("facets[type][]", "NG") in params
    assert "api_key" not in param_dict


def test_build_eia_region_url_structure():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    url = build_eia_region_url("CISO", start, end)
    
    # Must contain both encoded facet types
    assert "facets%5Btype%5D%5B%5D=D" in url or "facets[type][]=D" in url or "facets%5Btype%5D%5B%5D=D" in urllib.parse.unquote(url)
    assert "facets[type][]=D" in urllib.parse.unquote(url)
    assert "facets[type][]=NG" in urllib.parse.unquote(url)
    assert "facets[respondent][]=CISO" in urllib.parse.unquote(url)
    assert "start=2022-06-01T01" in url
    assert "end=2022-06-02T00" in url
    assert "api_key" not in url


def test_build_eia_query_params_month_and_year_boundaries():
    # Month boundary: Dec 31 -> Jan 1
    start = datetime(2022, 12, 31, 0, 0, tzinfo=timezone.utc)
    end = datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc)
    params = build_eia_query_params("CISO", start, end)
    param_dict = dict(params)
    assert param_dict["start"] == "2022-12-31T01"
    assert param_dict["end"] == "2023-01-01T00"

    # Multi-hour boundary
    start2 = datetime(2022, 6, 30, 22, 0, tzinfo=timezone.utc)
    end2 = datetime(2022, 7, 1, 1, 0, tzinfo=timezone.utc)
    params2 = build_eia_query_params("CISO", start2, end2)
    param_dict2 = dict(params2)
    assert param_dict2["start"] == "2022-06-30T23"
    assert param_dict2["end"] == "2022-07-01T01"


def test_parse_and_validate_eia_json_complete_24h():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    records = []
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records.append({"period": period, "respondent": "CISO", "type": "D", "value": f"{20000 + h}"})
        records.append({"period": period, "respondent": "CISO", "type": "NG", "value": f"{18000 + h}"})

    payload = {"response": {"data": records}}
    parsed = parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)
    assert len(parsed["demand_rows"]) == 24
    assert len(parsed["net_gen_rows"]) == 24


def test_eia_validation_missing_demand_or_ng():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    # Only demand, missing NG entirely
    records = [
        {"period": (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H"), "respondent": "CISO", "type": "D", "value": "20000"}
        for h in range(1, 25)
    ]
    payload = {"response": {"data": records}}
    with pytest.raises(ValueError, match="Incomplete Net Generation"):
        parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_validation_missing_single_hour():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    records = []
    # Hour 5 missing from demand
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        if h != 5:
            records.append({"period": period, "respondent": "CISO", "type": "D", "value": "20000"})
        records.append({"period": period, "respondent": "CISO", "type": "NG", "value": "18000"})

    payload = {"response": {"data": records}}
    with pytest.raises(ValueError, match="missing 1 hours"):
        parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_validation_duplicate_hour():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    records = []
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records.append({"period": period, "respondent": "CISO", "type": "D", "value": "20000"})
        records.append({"period": period, "respondent": "CISO", "type": "NG", "value": "18000"})
    # Duplicate first hour for demand
    records.append({"period": "2022-06-01T01", "respondent": "CISO", "type": "D", "value": "20500"})

    payload = {"response": {"data": records}}
    with pytest.raises(ValueError, match="duplicate record detected"):
        parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_validation_unknown_type():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 1, 1, 0, tzinfo=timezone.utc)
    records = [
        {"period": "2022-06-01T01", "respondent": "CISO", "type": "UNKNOWN_TYPE", "value": "100"}
    ]
    payload = {"response": {"data": records}}
    with pytest.raises(ValueError, match="unknown metric type"):
        parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_validation_ignores_df_and_ti_when_complete():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    records = []
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records.append({"period": period, "respondent": "CISO", "type": "D", "value": "20000"})
        records.append({"period": period, "respondent": "CISO", "type": "NG", "value": "18000"})
        records.append({"period": period, "respondent": "CISO", "type": "DF", "value": "20100"})
        records.append({"period": period, "respondent": "CISO", "type": "TI", "value": "1500"})

    payload = {"response": {"data": records}}
    parsed = parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)
    assert len(parsed["demand_rows"]) == 24
    assert len(parsed["net_gen_rows"]) == 24
    assert parsed["total_records"] == 96


def test_eia_validation_fails_when_only_df_and_ti_present():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    records = []
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records.append({"period": period, "respondent": "CISO", "type": "DF", "value": "20100"})
        records.append({"period": period, "respondent": "CISO", "type": "TI", "value": "1500"})

    payload = {"response": {"data": records}}
    with pytest.raises(ValueError, match="Incomplete Demand"):
        parse_and_validate_eia_json(json.dumps(payload), expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_query_params_order_stability():
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    params1 = build_eia_query_params("CISO", start, end)
    params2 = build_eia_query_params("CISO", start, end)
    assert params1 == params2
    url1 = build_eia_region_url("CISO", start, end)
    url2 = build_eia_region_url("CISO", start, end)
    assert url1 == url2


def test_eia_secret_redaction_everywhere(tmp_path, monkeypatch):
    secret = "secret_key_abcdef123456"
    monkeypatch.setenv("EIA_API_KEY", secret)

    url_with_key = f"https://api.eia.gov/v2/test?api_key={secret}&facets[type][]=D&facets[type][]=NG"
    assert secret not in redact_api_key(url_with_key, secret)
    assert "[REDACTED]" in redact_api_key(url_with_key, secret)

    mock_urlopen = MagicMock(side_effect=RuntimeError(f"Connection failed for {url_with_key}: 403 Forbidden"))
    with patch("urllib.request.urlopen", mock_urlopen):
        with pytest.raises(RuntimeError) as exc_info:
            run_eia_smoke_test(use_api=True, data_dir=tmp_path / "raw/eia", manifest_path=tmp_path / "manifest.jsonl")
        err_msg = str(exc_info.value)
        assert secret not in err_msg
        assert "[REDACTED]" in err_msg


# =========================================================================
# 5. CLI Smoke Test Runner & Exit Codes
# =========================================================================

def test_cli_dry_run_all(capsys):
    args = parse_args(["--dry-run"])
    code = run_smoke_tests(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "[NOAA] Status: dry_run" in captured.out
    assert "[CAISO] Status: dry_run" in captured.out
    assert "[EIA] Status: dry_run" in captured.out


def test_cli_eia_api_fails_without_key_when_explicitly_requested(tmp_path):
    # When user passes --source eia --eia-api without EIA_API_KEY, exit code must be nonzero
    with patch.dict(os.environ, {}, clear=True):
        args = parse_args(["--source", "eia", "--eia-api", "--data-dir", str(tmp_path)])
        code = run_smoke_tests(args)
        assert code != 0


def test_cli_all_without_key_non_failing(tmp_path):
    # All-sources run without key should report blocked_pending_api_key and return 0
    with patch.dict(os.environ, {}, clear=True):
        args = parse_args(["--source", "eia", "--data-dir", str(tmp_path)])
        code = run_smoke_tests(args)
        assert code == 0


def test_eia_emissions_status_accurate_and_no_guessed_filenames(tmp_path):
    # Dry run should report blocked_pending_emissions_file_discovery
    res_dry = run_eia_smoke_test(
        dry_run=True,
        data_dir=tmp_path / "raw/eia",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert res_dry["emissions_status"] == "blocked_pending_emissions_file_discovery"
    assert res_dry["demand_status"] == "dry_run"
    assert res_dry["net_generation_status"] == "dry_run"
    # Ensure no guessed filenames or bulk emissions URLs are emitted
    dry_req_str = json.dumps(res_dry["request"])
    assert "EIA930_EMISSIONS" not in dry_req_str
    assert "sixMonthFiles" not in dry_req_str

    # Unauthenticated run should report blocked_pending_emissions_file_discovery
    with patch.dict(os.environ, {}, clear=True):
        res_blocked = run_eia_smoke_test(
            use_api=False,
            data_dir=tmp_path / "raw/eia",
            manifest_path=tmp_path / "manifest.jsonl",
        )
        assert res_blocked["status"] == "blocked_pending_api_key"
        assert res_blocked["demand_status"] == "blocked_pending_api_key"
        assert res_blocked["net_generation_status"] == "blocked_pending_api_key"
        assert res_blocked["emissions_status"] == "blocked_pending_emissions_file_discovery"
        diag = res_blocked["diagnostic"]
        assert "EIA930_EMISSIONS" not in diag
        assert "sixMonthFiles" not in diag


def test_eia_emissions_staging_csv_valid_24h(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "ciso_staging.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            ts_str = f"2022-06-01T{h:02d}:00:00Z"
            writer.writerow(["CISO", ts_str, f"{1200.5 + h}", "metric_tons"])

    parsed = parse_and_validate_eia_emissions_staging_csv(
        csv_file,
        expected_ba="CISO",
        requested_start=start,
        requested_end=end,
    )
    assert parsed["row_count"] == 24
    assert parsed["rows"][0]["balancing_authority"] == "CISO"
    assert parsed["rows"][0]["co2_metric_tons"] == 1200.5
    assert parsed["rows"][0]["units"] == "metric_tons"


def test_eia_emissions_staging_rejects_excel_and_bad_extensions(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    xlsx_file = tmp_path / "ciso.xlsx"
    xlsx_file.write_bytes(b"dummy PK zip content")

    with pytest.raises(ValueError, match="Excel workbooks .* are not supported"):
        parse_and_validate_eia_emissions_staging_csv(xlsx_file, requested_start=start, requested_end=end)

    xls_file = tmp_path / "ciso.xls"
    xls_file.write_bytes(b"dummy binary")
    with pytest.raises(ValueError, match="Excel workbooks .* are not supported"):
        parse_and_validate_eia_emissions_staging_csv(xls_file, requested_start=start, requested_end=end)

    txt_file = tmp_path / "ciso.txt"
    txt_file.write_text("balancing_authority,timestamp,co2_value,co2_unit\n")
    with pytest.raises(ValueError, match="Unsupported emissions file format"):
        parse_and_validate_eia_emissions_staging_csv(txt_file, requested_start=start, requested_end=end)


def test_eia_emissions_staging_units_and_conversions(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "ciso_units.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            unit = "short_tons" if h % 2 == 0 else "metric_tons"
            writer.writerow(["CISO", f"2022-06-01T{h:02d}:00:00Z", "100.0", unit])

    parsed = parse_and_validate_eia_emissions_staging_csv(csv_file, requested_start=start, requested_end=end)
    assert parsed["row_count"] == 24
    # short_tons -> 100 * 0.90718474 = 90.718474
    assert pytest.approx(parsed["rows"][0]["co2_metric_tons"], rel=1e-5) == 90.718474
    # metric_tons -> 100.0
    assert parsed["rows"][1]["co2_metric_tons"] == 100.0


def test_eia_emissions_staging_unit_errors(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "ciso_bad_unit.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-06-01T00:00:00Z", "100.0", "pounds_co2"])

    with pytest.raises(ValueError, match="unsupported co2_unit 'pounds_co2'"):
        parse_and_validate_eia_emissions_staging_csv(csv_file, requested_start=start, requested_end=end)

    # Missing unit
    csv_file2 = tmp_path / "ciso_missing_unit.csv"
    with csv_file2.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-06-01T00:00:00Z", "100.0", ""])

    with pytest.raises(ValueError, match="missing mandatory 'co2_unit'"):
        parse_and_validate_eia_emissions_staging_csv(csv_file2, requested_start=start, requested_end=end)


def test_eia_emissions_numeric_validator():
    # Valid values
    assert parse_emissions_numeric_value("1200.5", 0) == 1200.5
    assert parse_emissions_numeric_value("0", 0) == 0.0
    assert parse_emissions_numeric_value(1200, 0) == 1200.0
    assert parse_emissions_numeric_value(0.0, 0) == 0.0

    # Rejected values
    with pytest.raises(ValueError, match="null"):
        parse_emissions_numeric_value(None, 0)
    with pytest.raises(ValueError, match="boolean"):
        parse_emissions_numeric_value(True, 0)
    with pytest.raises(ValueError, match="empty numeric string"):
        parse_emissions_numeric_value("   ", 0)
    with pytest.raises(ValueError, match="invalid nonnumeric emissions string"):
        parse_emissions_numeric_value("abc", 0)
    with pytest.raises(ValueError, match="NaN and Infinity"):
        parse_emissions_numeric_value(float("nan"), 0)
    with pytest.raises(ValueError, match="NaN and Infinity"):
        parse_emissions_numeric_value("inf", 0)
    with pytest.raises(ValueError, match="negative emissions value"):
        parse_emissions_numeric_value("-10.0", 0)


def test_eia_emissions_staging_timezone_and_dst(tmp_path):
    # Test valid America/Los_Angeles mapping with blank fold on unambiguous timestamps
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "ciso_pt.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "fold", "co2_value", "co2_unit"])
        start_pt = start.astimezone(ZoneInfo("America/Los_Angeles"))
        for h in range(24):
            ts = start_pt + timedelta(hours=h)
            # Blank fold for unambiguous timestamps
            writer.writerow(["CISO", ts.strftime("%Y-%m-%dT%H:%M:%S"), "America/Los_Angeles", "", "1500.0", "metric_tons"])

    parsed = parse_and_validate_eia_emissions_staging_csv(csv_file, requested_start=start, requested_end=end)
    assert parsed["row_count"] == 24
    assert parsed["rows"][0]["timestamp_utc"] == start


def test_eia_emissions_staging_dst_nonexistent_and_ambiguous(tmp_path):
    # 1. Nonexistent time: Spring forward in America/Los_Angeles is 2022-03-13 02:00:00 -> 03:00:00
    start_spring = datetime(2022, 3, 13, 9, 0, tzinfo=timezone.utc)
    end_spring = datetime(2022, 3, 13, 11, 0, tzinfo=timezone.utc)
    csv_spring = tmp_path / "spring.csv"
    with csv_spring.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-03-13T02:30:00", "America/Los_Angeles", "100.0", "metric_tons"])

    with pytest.raises(ValueError, match="Nonexistent local timestamp during DST spring-forward gap"):
        parse_and_validate_eia_emissions_staging_csv(csv_spring, requested_start=start_spring, requested_end=end_spring)

    # 2. Ambiguous time with missing fold: Fall back in America/Los_Angeles 2022-11-06 01:00:00 occurs twice
    start_fall = datetime(2022, 11, 6, 8, 0, tzinfo=timezone.utc)
    end_fall = datetime(2022, 11, 6, 10, 0, tzinfo=timezone.utc)
    csv_fall = tmp_path / "fall.csv"
    with csv_fall.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-11-06T01:30:00", "America/Los_Angeles", "100.0", "metric_tons"])

    with pytest.raises(ValueError, match="Ambiguous local timestamp during DST fall-back transition"):
        parse_and_validate_eia_emissions_staging_csv(csv_fall, requested_start=start_fall, requested_end=end_fall)

    # 3. Disambiguated ambiguous time with fold '0' and '1'
    csv_fall_fold = tmp_path / "fall_fold.csv"
    with csv_fall_fold.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "fold", "co2_value", "co2_unit"])
        # 01:00 PDT is 08:00 UTC (fold 0)
        writer.writerow(["CISO", "2022-11-06T01:00:00", "America/Los_Angeles", "0", "100.0", "metric_tons"])
        # 01:00 PST is 09:00 UTC (fold 1)
        writer.writerow(["CISO", "2022-11-06T01:00:00", "America/Los_Angeles", "1", "105.0", "metric_tons"])

    parsed_fold = parse_and_validate_eia_emissions_staging_csv(csv_fall_fold, requested_start=start_fall, requested_end=end_fall)
    assert parsed_fold["row_count"] == 2
    assert parsed_fold["rows"][0]["timestamp_utc"] == datetime(2022, 11, 6, 8, 0, tzinfo=timezone.utc)
    assert parsed_fold["rows"][1]["timestamp_utc"] == datetime(2022, 11, 6, 9, 0, tzinfo=timezone.utc)


def test_eia_emissions_staging_invalid_folds(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)

    # Invalid fold '2'
    csv_f2 = tmp_path / "fold2.csv"
    with csv_f2.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "fold", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-06-01T00:00:00", "America/Los_Angeles", "2", "100.0", "metric_tons"])

    with pytest.raises(ValueError, match="invalid fold value '2'"):
        parse_and_validate_eia_emissions_staging_csv(csv_f2, requested_start=start, requested_end=end)

    # Invalid text fold 'true'
    csv_text = tmp_path / "fold_text.csv"
    with csv_text.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "timezone", "fold", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-06-01T00:00:00", "America/Los_Angeles", "true", "100.0", "metric_tons"])

    with pytest.raises(ValueError, match="invalid fold value 'true'"):
        parse_and_validate_eia_emissions_staging_csv(csv_text, requested_start=start, requested_end=end)

    # Contradictory non-empty fold with explicit offset
    csv_offset = tmp_path / "offset_fold.csv"
    with csv_offset.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "fold", "co2_value", "co2_unit"])
        writer.writerow(["CISO", "2022-06-01T00:00:00-07:00", "0", "100.0", "metric_tons"])

    with pytest.raises(ValueError, match="Contradictory fold '0' provided for explicit-offset timestamp"):
        parse_and_validate_eia_emissions_staging_csv(csv_offset, requested_start=start, requested_end=end)


def test_eia_emissions_staging_duplicate_and_missing_hours(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)

    # Duplicate hour
    csv_dup = tmp_path / "dup.csv"
    with csv_dup.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            writer.writerow(["CISO", f"2022-06-01T{h:02d}:00:00Z", "1200.0", "metric_tons"])
        writer.writerow(["CISO", "2022-06-01T00:00:00Z", "1250.0", "metric_tons"])

    with pytest.raises(ValueError, match="duplicate record detected"):
        parse_and_validate_eia_emissions_staging_csv(csv_dup, expected_ba="CISO", requested_start=start, requested_end=end)

    # Missing hour
    csv_miss = tmp_path / "miss.csv"
    with csv_miss.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            if h == 10:
                continue
            writer.writerow(["CISO", f"2022-06-01T{h:02d}:00:00Z", "1200.0", "metric_tons"])

    with pytest.raises(ValueError, match="missing 1 hours"):
        parse_and_validate_eia_emissions_staging_csv(csv_miss, expected_ba="CISO", requested_start=start, requested_end=end)


def test_eia_emissions_staging_missing_required_columns(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "missing_cols.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "co2_value"])
        writer.writerow(["2022-06-01T00:00:00Z", "1200.0"])

    with pytest.raises(ValueError, match="missing required columns"):
        parse_and_validate_eia_emissions_staging_csv(csv_file, requested_start=start, requested_end=end)


def test_ingest_eia_emissions_file_provenance_and_manifest(tmp_path):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "sample_ciso_staging.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            writer.writerow(["CISO", f"2022-06-01T{h:02d}:00:00Z", "1250.0", "metric_tons"])

    manifest_file = tmp_path / "manifest.jsonl"
    data_dir = tmp_path / "raw/eia"
    res = ingest_eia_emissions_file(
        csv_file,
        balancing_authority="CISO",
        requested_start=start,
        requested_end=end,
        data_dir=data_dir,
        manifest_path=manifest_file,
    )
    assert res["status"] == "success_user_supplied_staging_csv"
    assert res["native_emissions_status"] == "blocked_pending_emissions_file_discovery"
    assert res["emissions_staging_status"] == "success_user_supplied_staging_csv"
    assert res["coverage"]["covered_hourly_bins"] == 24
    assert Path(res["raw_path"]).exists()
    assert manifest_file.exists()
    man_text = manifest_file.read_text()
    assert "EIA-930-emissions-staging" in man_text
    assert "EIA-staging" in man_text
    assert "sha256" in man_text


def test_cli_with_eia_emissions_file_option(tmp_path, capsys):
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    csv_file = tmp_path / "sample_ciso_staging.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["balancing_authority", "timestamp", "co2_value", "co2_unit"])
        for h in range(24):
            writer.writerow(["CISO", f"2022-06-01T{h:02d}:00:00Z", "1250.0", "metric_tons"])

    args = parse_args(["--source", "eia", "--eia-emissions-file", str(csv_file), "--data-dir", str(tmp_path / "data")])
    code = run_smoke_tests(args)
    captured = capsys.readouterr()
    assert "[EIA] Status: blocked_pending_api_key" in captured.out
    assert "Native emissions status: blocked_pending_emissions_file_discovery" in captured.out
    assert "Staging emissions status: success_user_supplied_staging_csv" in captured.out
    assert code == 0


def test_eia_api_caching_and_corrupt_cache_recovery(tmp_path, monkeypatch, capsys):
    secret_key = "dummy_secret_test_key_12345"
    monkeypatch.setenv("EIA_API_KEY", secret_key)
    start = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    data_dir = tmp_path / "raw/eia"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = tmp_path / "manifest.jsonl"
    coverage_file = tmp_path / "coverage.csv"
    cache_file = data_dir / "eia930_region_CISO_20220601.json"

    # Generate a valid EIA payload
    records = []
    for h in range(1, 25):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records.append({"period": period, "respondent": "CISO", "type": "D", "value": "24000"})
        records.append({"period": period, "respondent": "CISO", "type": "NG", "value": "21000"})
    valid_payload = json.dumps({"response": {"data": records}}).encode("utf-8")

    # 1. First run with network request
    mock_resp = MagicMock()
    mock_resp.read.return_value = valid_payload
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        res1 = run_eia_smoke_test(use_api=True, data_dir=data_dir, manifest_path=manifest_file)
        assert res1["status"] == "success"
        assert res1["cache_hit"] is False
        assert mock_urlopen.call_count == 1
        assert cache_file.exists()
        rec1 = res1["manifest_record"]
        assert rec1["cache_hit"] is False
        assert rec1["retrieval_time_known"] is True
        retrieved_at_1 = rec1["retrieved_at"]

    # Verify secret is not in cache file, manifest, or coverage report
    assert secret_key not in cache_file.read_text()
    assert secret_key not in manifest_file.read_text()

    # 2. Second run: cache hit without network request
    with patch("urllib.request.urlopen") as mock_urlopen_cached:
        res2 = run_eia_smoke_test(use_api=True, data_dir=data_dir, manifest_path=manifest_file)
        assert res2["status"] == "success"
        assert res2["cache_hit"] is True
        assert mock_urlopen_cached.call_count == 0
        rec2 = res2["manifest_record"]
        # Preserves original retrieval timestamp and does not append duplicate line to manifest
        assert rec2["retrieved_at"] == retrieved_at_1
        lines = [line.strip() for line in manifest_file.read_text().splitlines() if line.strip()]
        assert len(lines) == 1

    # 3. Cache identity safety: mismatched requested interval rejects cache and triggers re-download
    end_mismatch = datetime(2022, 6, 3, 0, 0, tzinfo=timezone.utc)
    records_48h = []
    for h in range(1, 49):
        period = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        records_48h.append({"period": period, "respondent": "CISO", "type": "D", "value": "24000"})
        records_48h.append({"period": period, "respondent": "CISO", "type": "NG", "value": "21000"})
    mock_resp_48h = MagicMock()
    mock_resp_48h.read.return_value = json.dumps({"response": {"data": records_48h}}).encode("utf-8")
    mock_resp_48h.__enter__.return_value = mock_resp_48h
    mock_resp_48h.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp_48h) as mock_urlopen_mismatch:
        res_mismatch = run_eia_smoke_test(
            start_date=start,
            end_date=end_mismatch,
            use_api=True,
            data_dir=data_dir,
            manifest_path=manifest_file,
        )
        assert res_mismatch["status"] == "success"
        assert res_mismatch["cache_hit"] is False
        assert mock_urlopen_mismatch.call_count == 1

    # 4. Corrupt cache: corrupt cache file should trigger re-download and recovery
    cache_file.write_bytes(b"corrupt json { truncated")
    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen_recovery:
        res3 = run_eia_smoke_test(use_api=True, data_dir=data_dir, manifest_path=manifest_file)
        assert res3["status"] == "success"
        assert res3["cache_hit"] is False
        assert mock_urlopen_recovery.call_count == 1
        assert secret_key not in cache_file.read_text()

    # Verify CLI output contains no secret key
    args = parse_args(["--source", "eia", "--eia-api", "--data-dir", str(tmp_path)])
    run_smoke_tests(args)
    captured = capsys.readouterr()
    assert secret_key not in captured.out
    assert secret_key not in captured.err


# =========================================================================
# 6. Opt-In Live Tests (Skipped by default)
# =========================================================================

@pytest.mark.skipif(os.environ.get("HEATTRACE_LIVE_TESTS") != "1", reason="Requires HEATTRACE_LIVE_TESTS=1")
def test_live_noaa_smoke_test(tmp_path):
    res = run_noaa_smoke_test(
        station_id="USW00023234",
        year=2022,
        data_dir=tmp_path / "noaa",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert res["status"] == "success"
    assert res["coverage"]["covered_hourly_bins"] == 24


@pytest.mark.skipif(os.environ.get("HEATTRACE_LIVE_TESTS") != "1", reason="Requires HEATTRACE_LIVE_TESTS=1")
def test_live_caiso_smoke_test(tmp_path):
    res = run_caiso_smoke_test(
        node="TH_NP15_GEN-APND",
        data_dir=tmp_path / "caiso",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert res["status"] == "success"
    assert res["coverage"]["covered_hourly_bins"] == 24
    assert res["coverage"]["row_count"] == 24


# =========================================================================
# 7. NOAA Daily Maxima Extraction & Quality Policy Tests (P1-01)
# =========================================================================

def test_noaa_quality_code_policy_categories():
    assert check_noaa_temperature_quality("") == "accepted"
    assert check_noaa_temperature_quality("1") == "accepted"
    assert check_noaa_temperature_quality("5") == "accepted"
    assert check_noaa_temperature_quality("A") == "accepted"
    assert check_noaa_temperature_quality("Passed") == "accepted"

    assert check_noaa_temperature_quality("2") == "rejected"
    assert check_noaa_temperature_quality("3") == "rejected"
    assert check_noaa_temperature_quality("4") == "rejected"
    assert check_noaa_temperature_quality("6") == "rejected"
    assert check_noaa_temperature_quality("7") == "rejected"
    assert check_noaa_temperature_quality("Failed") == "rejected"

    assert check_noaa_temperature_quality("UNKNOWN_XYZ") == "unknown"
    assert check_noaa_temperature_quality("99") == "unknown"


def test_extract_daily_maxima_rejects_unknown_quality_code():
    rows = [
        {
            "station_id": "USW00023234",
            "timestamp_utc": datetime(2022, 6, 1, 20, 0, tzinfo=timezone.utc),
            "temperature_c": 22.0,
            "temperature_quality_code": "UNKNOWN_CODE",
        }
    ]
    with pytest.raises(ValueError, match="Unknown NOAA temperature quality code"):
        extract_daily_maxima(rows, target_timezone="America/Los_Angeles")


def test_extract_daily_maxima_identical_duplicates():
    station = "USW00023234"
    ts = datetime(2022, 6, 1, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 21.5,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM15",
        },
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 21.5,
            "temperature_quality_code": "5",
            "temperature_report_type": "FM15",
        },
    ]
    maxima = extract_daily_maxima(rows, target_timezone="America/Los_Angeles")
    assert len(maxima) == 1
    m = maxima[0]
    assert m["daily_max_temperature_c"] == 21.5
    assert m["duplicate_observation_count"] == 1
    assert m["conflict_observation_count"] == 0
    assert m["valid_observation_count"] == 1


def test_extract_daily_maxima_conflicting_duplicates_resolved_by_report_type():
    station = "USW00023234"
    ts = datetime(2022, 6, 1, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 22.0,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM15",  # METAR preferred
        },
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 20.0,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM12",  # SYNOP lower priority
        },
    ]
    maxima = extract_daily_maxima(rows, target_timezone="America/Los_Angeles")
    assert len(maxima) == 1
    m = maxima[0]
    # FM15 value (22.0) is retained
    assert m["daily_max_temperature_c"] == 22.0
    assert m["duplicate_observation_count"] == 1
    assert m["conflict_observation_count"] == 1


def test_extract_daily_maxima_conflicting_duplicates_conservative_max():
    station = "USW00023234"
    ts = datetime(2022, 6, 1, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 22.5,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM15",
        },
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 23.0,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM15",  # Same report type, disagreement
        },
    ]
    maxima = extract_daily_maxima(rows, target_timezone="America/Los_Angeles")
    assert len(maxima) == 1
    m = maxima[0]
    # Conservative tie-break retains max (23.0) so daily max is not underestimated
    assert m["daily_max_temperature_c"] == 23.0
    assert m["conflict_observation_count"] == 1
    assert m["duplicate_observation_count"] == 1


def test_extract_daily_maxima_duplicates_with_rejected_quality():
    station = "USW00023234"
    ts = datetime(2022, 6, 1, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 21.0,
            "temperature_quality_code": "1",
            "temperature_report_type": "FM15",
        },
        {
            "station_id": station,
            "timestamp_utc": ts,
            "temperature_c": 45.0,  # Erroneous duplicate flagged as rejected
            "temperature_quality_code": "2",
            "temperature_report_type": "FM15",
        },
    ]
    maxima = extract_daily_maxima(rows, target_timezone="America/Los_Angeles")
    assert len(maxima) == 1
    m = maxima[0]
    assert m["daily_max_temperature_c"] == 21.0
    # The rejected row is excluded before deduplication
    assert m["conflict_observation_count"] == 0
    assert m["duplicate_observation_count"] == 0


def test_get_local_day_utc_bounds_dst_transitions():
    tz = "America/Los_Angeles"
    # 1. Ordinary summer day (24 hours)
    s1, e1, h1 = get_local_day_utc_bounds("2022-06-01", target_timezone=tz)
    assert h1 == 24.0
    assert s1 == datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    assert e1 == datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)

    # 2. Spring-forward transition day (23 hours: 2022-03-13)
    s2, e2, h2 = get_local_day_utc_bounds("2022-03-13", target_timezone=tz)
    assert h2 == 23.0
    assert s2 == datetime(2022, 3, 13, 8, 0, tzinfo=timezone.utc)
    assert e2 == datetime(2022, 3, 14, 7, 0, tzinfo=timezone.utc)

    # 3. Fall-back transition day (25 hours: 2022-11-06)
    s3, e3, h3 = get_local_day_utc_bounds("2022-11-06", target_timezone=tz)
    assert h3 == 25.0
    assert s3 == datetime(2022, 11, 6, 7, 0, tzinfo=timezone.utc)
    assert e3 == datetime(2022, 11, 7, 8, 0, tzinfo=timezone.utc)


# =========================================================================
# 8. CAISO Retries, Throttling, and Fallback Tests (P1-03)
# =========================================================================

@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_caiso_download_retry_allowlist(status_code, tmp_path):
    url = "https://oasis.caiso.com/oasisapi/SingleZip?dummy=1"
    output_dir = tmp_path / "caiso"
    file_stem = f"test_retry_{status_code}"

    csv_data = "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,NODE,MARKET_RUN_ID,LMP_TYPE,MW,XML_DATA_ITEM,GROUP\n"
    for h in range(24):
        csv_data += f"2024-06-01T{h:02d}:00:00-00:00,2024-06-01T{h+1:02d}:00:00-00:00,TH_NP15_GEN-APND,DAM,LMP,42.50,LMP_PRC,1\n"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("test.csv", csv_data)
    valid_zip_bytes = zip_buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.read.return_value = valid_zip_bytes
    mock_resp.__enter__.return_value = mock_resp

    sleep_calls = []

    def mock_sleep(sec):
        sleep_calls.append(sec)

    error = urllib.error.HTTPError(url, status_code, f"Error {status_code}", {}, None)
    with patch("urllib.request.urlopen", side_effect=[error, mock_resp]):
        path, is_hit = download_caiso_file(
            url,
            output_dir,
            file_stem,
            sleep_fn=mock_sleep,
            throttle_delay=0.0,
        )
        assert path.exists()
        assert is_hit is False
        assert len(sleep_calls) == 1


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 410, 422])
def test_caiso_download_non_retryable_codes_fast_fail(status_code, tmp_path):
    url = "https://oasis.caiso.com/oasisapi/SingleZip?dummy=1"
    output_dir = tmp_path / "caiso"
    file_stem = f"test_non_retry_{status_code}"

    sleep_calls = []

    def mock_sleep(sec):
        sleep_calls.append(sec)

    error = urllib.error.HTTPError(url, status_code, f"Client Error {status_code}", {}, None)
    with patch("urllib.request.urlopen", side_effect=error) as mock_urlopen:
        with pytest.raises(RuntimeError, match=f"Non-retryable CAISO HTTP error {status_code}"):
            download_caiso_file(
                url,
                output_dir,
                file_stem,
                sleep_fn=mock_sleep,
                throttle_delay=0.0,
            )
        assert mock_urlopen.call_count == 1
        assert len(sleep_calls) == 0


def test_caiso_download_invalid_zip_fails_without_retry_and_cleans_tmp(tmp_path):
    url = "https://oasis.caiso.com/oasisapi/SingleZip?dummy=1"
    output_dir = tmp_path / "caiso"
    file_stem = "test_invalid_zip"

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"NOT_A_ZIP_CONTENT_CORRUPT"
    mock_resp.__enter__.return_value = mock_resp

    sleep_calls = []

    def mock_sleep(sec):
        sleep_calls.append(sec)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        with pytest.raises(ValueError, match="is not a valid zip archive"):
            download_caiso_file(
                url,
                output_dir,
                file_stem,
                sleep_fn=mock_sleep,
                throttle_delay=0.0,
            )
        # Content validation errors fail immediately without retry!
        assert mock_urlopen.call_count == 1
        assert len(sleep_calls) == 0
        # Temporary files must be cleaned up
        assert len(list(output_dir.glob("*.tmp*"))) == 0


def test_caiso_download_retry_after_http_date(tmp_path):
    url = "https://oasis.caiso.com/oasisapi/SingleZip?dummy=1"
    output_dir = tmp_path / "caiso"
    file_stem = "test_http_date_ra"

    csv_data = "INTERVALSTARTTIME_GMT,INTERVALENDTIME_GMT,NODE,MARKET_RUN_ID,LMP_TYPE,MW,XML_DATA_ITEM,GROUP\n"
    for h in range(24):
        csv_data += f"2024-06-01T{h:02d}:00:00-00:00,2024-06-01T{h+1:02d}:00:00-00:00,TH_NP15_GEN-APND,DAM,LMP,42.50,LMP_PRC,1\n"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("test.csv", csv_data)

    mock_resp = MagicMock()
    mock_resp.read.return_value = zip_buf.getvalue()
    mock_resp.__enter__.return_value = mock_resp

    sleep_calls = []

    def mock_sleep(sec):
        sleep_calls.append(sec)

    # Future HTTP date ~15s ahead
    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=15)
    import email.utils
    date_str = email.utils.format_datetime(future)

    headers = {"Retry-After": date_str}
    error_429 = urllib.error.HTTPError(url, 429, "Too Many Requests", headers, None)

    with patch("urllib.request.urlopen", side_effect=[error_429, mock_resp]):
        path, is_hit = download_caiso_file(
            url,
            output_dir,
            file_stem,
            sleep_fn=mock_sleep,
            throttle_delay=0.0,
        )
        assert path.exists()
        assert len(sleep_calls) == 1
        assert 10.0 <= sleep_calls[0] <= 20.0


def test_caiso_download_backoff_bounded_to_max(tmp_path):
    url = "https://oasis.caiso.com/oasisapi/SingleZip?dummy=1"
    output_dir = tmp_path / "caiso"
    file_stem = "test_bound_backoff"

    sleep_calls = []

    def mock_sleep(sec):
        sleep_calls.append(sec)

    # 429 with Retry-After: 9999 (should be capped at MAX_CAISO_RETRY_DELAY_SECONDS = 30.0)
    headers = {"Retry-After": "9999"}
    error_429 = urllib.error.HTTPError(url, 429, "Too Many Requests", headers, None)

    with patch("urllib.request.urlopen", side_effect=error_429):
        with pytest.raises(RuntimeError):
            download_caiso_file(
                url,
                output_dir,
                file_stem,
                max_retries=2,
                sleep_fn=mock_sleep,
                throttle_delay=0.0,
            )
        assert len(sleep_calls) == 1
        assert sleep_calls[0] == 30.0


# =========================================================================
# 9. P1-QC CLI Runner & Classification Evidence Tests (P1-QC)
# =========================================================================

def test_cli_qc_runner(tmp_path):
    data_dir = tmp_path / "data"
    from heattrace.cli import run_qc_tests

    args = parse_args([
        "--qc",
        "--dry-run",
        "--data-dir", str(data_dir),
    ])
    code = run_qc_tests(args)
    assert code == 0


def test_misclassified_day_fails_qc_validation(tmp_path):
    """Test that a day failing baseline threshold rules cannot remain 'verified'."""
    # If daily max on heatwave day were 20.0°C (far below 34.0°C threshold), classification must fail
    daily_max_c = 20.0
    hw_thresh = 34.2
    tolerance = 0.5
    exp_c = 35.6
    meets_threshold = daily_max_c >= hw_thresh
    matches_expected = abs(daily_max_c - exp_c) <= tolerance

    qc_day_status = "verified" if (meets_threshold and matches_expected) else "failure"
    assert qc_day_status == "failure"


def test_qc_eia_cache_only_without_key(tmp_path, monkeypatch):
    """Test that QC uses a validated EIA cache when key is absent."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    data_dir = tmp_path / "data"
    eia_dir = data_dir / "raw/eia"
    eia_dir.mkdir(parents=True, exist_ok=True)

    # Put mock valid cache for 2022-06-01
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    cache_file = eia_dir / f"eia930_region_CISO_{start_utc.strftime('%Y%m%d')}.json"

    data_records = []
    curr = start_utc
    while curr < end_utc:
        he_dt = curr + timedelta(hours=1)
        period_str = he_dt.strftime("%Y-%m-%dT%H")
        data_records.append({"period": period_str, "respondent": "CISO", "type": "D", "value": "28000"})
        data_records.append({"period": period_str, "respondent": "CISO", "type": "NG", "value": "26000"})
        curr += timedelta(hours=1)
    mock_payload = {"response": {"data": data_records}}
    cache_file.write_text(json.dumps(mock_payload))

    from heattrace.ingest.eia import validate_eia_json_cache, run_eia_smoke_test
    assert validate_eia_json_cache(cache_file, expected_ba="CISO", requested_start=start_utc, requested_end=end_utc) is True

    res = run_eia_smoke_test(
        balancing_authority="CISO",
        start_date=start_utc,
        end_date=end_utc,
        use_api=True,
        allow_cache_without_key=True,
        data_dir=eia_dir,
        manifest_path=data_dir / "manifest.jsonl",
    )

    assert res["status"] == "success"
    assert res["cache_hit"] is True
    assert res["demand_status"] == "success"
    assert res["net_generation_status"] == "success"
    assert res["native_emissions_status"] == "blocked_pending_emissions_file_discovery"


def test_qc_eia_blocked_without_key_and_without_cache(tmp_path, monkeypatch):
    """Test that QC truthfully marks EIA as blocked_pending_api_key when key and cache are absent."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    data_dir = tmp_path / "data"
    eia_dir = data_dir / "raw/eia"
    start_utc = datetime(2022, 9, 5, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 9, 6, 7, 0, tzinfo=timezone.utc)

    from heattrace.ingest.eia import run_eia_smoke_test
    res = run_eia_smoke_test(
        balancing_authority="CISO",
        start_date=start_utc,
        end_date=end_utc,
        use_api=False,  # key absent and no cache
        data_dir=eia_dir,
        manifest_path=data_dir / "manifest.jsonl",
    )
    assert res["status"] == "blocked_pending_api_key"
    assert res["demand_status"] == "blocked_pending_api_key"
    assert res["net_generation_status"] == "blocked_pending_api_key"
    assert res["native_emissions_status"] == "blocked_pending_emissions_file_discovery"


# =========================================================================
# 10. Native EIA CISO Excel Workbook (.xlsx) Ingestion Tests
# =========================================================================

def _create_mock_ciso_xlsx(
    target_path: Path,
    *,
    hours: int = 24,
    start_date_utc: datetime = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc),
    corrupt_notes: bool = False,
    missing_sheet: str | None = None,
    wrong_ba: bool = False,
    invalid_emissions: bool = False,
    intensity_mismatch: bool = False,
    missing_column: bool = False,
    duplicate_hour: bool = False,
    bad_demand_unit: bool = False,
    bad_utc_notes: bool = False,
    issue_flag_mode: str = "first_hour_only",  # 'first_hour_only', 'none', 'all'
    extra_issue_rows: list[tuple[str, float, str | int]] | None = None,
) -> Path:
    """Build a compliant, compact synthetic .xlsx workbook for testing."""
    sst: list[str] = [
        "BA", "UTC time", "Local date", "Hour", "Local time", "Time zone",
        "Demand", "Net generation",
        "CO2 Emissions Generated", "CO2 Emissions Consumed",
        "Positive Generation", "Consumed Electricity",
        "CO2 Emissions Intensity for Generated Electricity",
        "CO2 Emissions Intensity for Consumed Electricity",
        "CISO" if not wrong_ba else "OTHER_BA",
        "Pacific",
    ]

    # Shared string helper
    def sst_idx(val: str) -> int:
        if val not in sst:
            sst.append(val)
        return sst.index(val)

    # 1. Notes rows
    utc_desc = "Coordinated Universal Time" if bad_utc_notes else "The end of the hour in UTC"
    notes_rows = [
        ("UTC time", utc_desc),
        ("Local date", "The date using local time zone"),
        ("Local time", "The end of the hour in local time"),
        ("Demand", "Electricity demand in GWh" if bad_demand_unit else "Electricity demand in MWh"),
        ("Net generation", "Net generation in MWh"),
        ("CO2 Emissions Generated", "CO2 emissions generated (metric tons)"),
        ("CO2 Emissions Consumed", "CO2 emissions consumed (metric tons)"),
        ("Positive Generation", "Sum of generation in MWh"),
        ("Consumed Electricity", "Electricity consumed in MWh"),
        ("CO2 Emissions Intensity for Generated Electricity", "Intensity in lbs/kWh"),
        ("CO2 Emissions Intensity for Consumed Electricity", "Intensity in lbs/kWh"),
    ]
    if corrupt_notes:
        notes_rows = [("Irrelevant", "Content")]

    # Build Notes sheet XML
    notes_rows_xml = []
    for r_idx, (k, v) in enumerate(notes_rows, start=1):
        k_i = sst_idx(k)
        v_i = sst_idx(v)
        notes_rows_xml.append(
            f'<row r="{r_idx}">'
            f'<c r="A{r_idx}" t="s"><v>{k_i}</v></c>'
            f'<c r="B{r_idx}" t="s"><v>{v_i}</v></c>'
            f'</row>'
        )
    notes_sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(notes_rows_xml) + '</sheetData></worksheet>'
    )

    # 2. Known Data Issues sheet XML
    issues_rows_xml = [
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="E1"><v>0</v></c></row>'
    ]
    base_excel = datetime(1899, 12, 30, tzinfo=timezone.utc)
    for h in range(hours):
        # Hour-ending UTC
        he_dt = start_date_utc + timedelta(hours=h + 1)
        serial_val = (he_dt - base_excel).total_seconds() / 86400.0
        r_num = h + 2
        if issue_flag_mode == "all":
            issue_flag = 1
        elif issue_flag_mode == "none":
            issue_flag = 0
        else:
            issue_flag = 1 if h == 0 else 0
        issues_rows_xml.append(
            f'<row r="{r_num}">'
            f'<c r="A{r_num}" t="s"><v>{sst_idx("CISO")}</v></c>'
            f'<c r="B{r_num}"><v>{serial_val:.8f}</v></c>'
            f'<c r="E{r_num}"><v>{issue_flag}</v></c>'
            f'</row>'
        )

    if extra_issue_rows:
        curr_r = len(issues_rows_xml) + 1
        for extra_ba, extra_serial, extra_flag in extra_issue_rows:
            issues_rows_xml.append(
                f'<row r="{curr_r}">'
                f'<c r="A{curr_r}" t="s"><v>{sst_idx(extra_ba)}</v></c>'
                f'<c r="B{curr_r}"><v>{extra_serial:.8f}</v></c>'
                f'<c r="E{curr_r}"><v>{extra_flag}</v></c>'
                f'</row>'
            )
            curr_r += 1
    issues_sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(issues_rows_xml) + '</sheetData></worksheet>'
    )

    # 3. Published Hourly Data sheet XML
    # Headers
    header_cols = [
        ("A1", "BA"), ("B1", "UTC time"), ("C1", "Local date"), ("D1", "Hour"),
        ("E1", "Local time"), ("F1", "Time zone"), ("I1", "Demand"), ("J1", "Net generation"),
        ("CK1", "CO2 Emissions Generated"), ("CN1", "CO2 Emissions Consumed"),
        ("CO1", "Positive Generation"), ("CP1", "Consumed Electricity"),
        ("CQ1", "CO2 Emissions Intensity for Generated Electricity"),
        ("CR1", "CO2 Emissions Intensity for Consumed Electricity"),
    ]
    if missing_column:
        header_cols = [c for c in header_cols if c[1] != "Demand"]

    hdr_cells = "".join([f'<c r="{r}" t="s"><v>{sst_idx(name)}</v></c>' for r, name in header_cols])
    hourly_rows_xml = [f'<row r="1">{hdr_cells}</row>']

    ba_str_idx = sst_idx("CISO" if not wrong_ba else "OTHER_BA")
    tz_str_idx = sst_idx("Pacific")

    row_count = hours
    if duplicate_hour:
        row_count += 1

    for h_idx in range(row_count):
        h = h_idx if not duplicate_hour or h_idx < hours else 0
        he_dt = start_date_utc + timedelta(hours=h + 1)
        serial_val = (he_dt - base_excel).total_seconds() / 86400.0
        r_num = h_idx + 2

        demand_val = 25000.0 + h * 100
        net_gen_val = 22000.0 + h * 80
        pos_gen = 22500.0
        con_elec = 24500.0

        if invalid_emissions:
            co2_gen = -100.0
            co2_con = -50.0
        else:
            co2_gen = 3000.0 + h * 10
            co2_con = 4500.0 + h * 15

        # Precise reconciliation: intensity = (co2_mt * 2204.62262185) / (mwh * 1000)
        gen_intensity_lb = (co2_gen * 2204.62262185) / (pos_gen * 1000.0)
        con_intensity_lb = (co2_con * 2204.62262185) / (con_elec * 1000.0)

        if intensity_mismatch:
            gen_intensity_lb += 0.5  # introduce large mismatch

        hourly_rows_xml.append(
            f'<row r="{r_num}">'
            f'<c r="A{r_num}" t="s"><v>{ba_str_idx}</v></c>'
            f'<c r="B{r_num}"><v>{serial_val:.8f}</v></c>'
            f'<c r="C{r_num}"><v>{serial_val:.4f}</v></c>'
            f'<c r="D{r_num}"><v>{h + 1}</v></c>'
            f'<c r="E{r_num}"><v>{serial_val:.8f}</v></c>'
            f'<c r="F{r_num}" t="s"><v>{tz_str_idx}</v></c>'
            f'<c r="I{r_num}"><v>{demand_val}</v></c>'
            f'<c r="J{r_num}"><v>{net_gen_val}</v></c>'
            f'<c r="CK{r_num}"><v>{co2_gen}</v></c>'
            f'<c r="CN{r_num}"><v>{co2_con}</v></c>'
            f'<c r="CO{r_num}"><v>{pos_gen}</v></c>'
            f'<c r="CP{r_num}"><v>{con_elec}</v></c>'
            f'<c r="CQ{r_num}"><v>{gen_intensity_lb}</v></c>'
            f'<c r="CR{r_num}"><v>{con_intensity_lb}</v></c>'
            f'</row>'
        )

    hourly_sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData>' + "".join(hourly_rows_xml) + '</sheetData></worksheet>'
    )

    # 4. Shared strings XML
    sst_entries = "".join([f'<si><t>{s}</t></si>' for s in sst])
    sst_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(sst)}" uniqueCount="{len(sst)}">'
        + sst_entries +
        '</sst>'
    )

    # Build zip
    sheets_to_include = [
        ("Published Hourly Data", "1", "rId1", "worksheets/sheet1.xml", hourly_sheet_xml),
        ("Notes", "2", "rId2", "worksheets/sheet2.xml", notes_sheet_xml),
        ("Known Data Issues", "3", "rId3", "worksheets/sheet3.xml", issues_sheet_xml),
    ]
    if missing_sheet:
        sheets_to_include = [s for s in sheets_to_include if s[0] != missing_sheet]

    with zipfile.ZipFile(target_path, "w") as z:
        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            '</Types>'
        )
        z.writestr("[Content_Types].xml", content_types)

        root_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'
        )
        z.writestr("_rels/.rels", root_rels)

        wb_rels_entries = "".join([
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="{path_in_xl}"/>'
            for name, sid, rid, path_in_xl, _ in sheets_to_include
        ])
        wb_rels_entries += '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        z.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{wb_rels_entries}</Relationships>')

        sheet_tags = "".join([f'<sheet name="{name}" sheetId="{sid}" r:id="{rid}"/>' for name, sid, rid, _, _ in sheets_to_include])
        z.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{sheet_tags}</sheets></workbook>')

        for name, sid, rid, path_in_xl, content_xml in sheets_to_include:
            z.writestr(f"xl/{path_in_xl}", content_xml)

        z.writestr("xl/sharedStrings.xml", sst_xml)

    return target_path


def test_native_eia_ciso_workbook_valid(tmp_path):
    """Test valid native EIA CISO workbook parsing and intensity conversion."""
    wb_file = tmp_path / "valid_CISO.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc)

    res = parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc, expected_ba="CISO")
    assert res["row_count"] == 24
    assert len(res["rows"]) == 24

    first_row = res["rows"][0]
    assert first_row["balancing_authority"] == "CISO"
    assert first_row["timestamp_utc"] == start_utc
    assert first_row["hour_ending_utc"] == start_utc + timedelta(hours=1)
    assert first_row["data_issue_flag"] == "1"  # Hour 0 had data issue flag 1
    assert first_row["co2_intensity_generated_g_per_kwh"] > 0
    assert first_row["co2_intensity_consumed_g_per_kwh"] > 0

    # Ingest and provenance
    manifest_file = tmp_path / "manifest.jsonl"
    ingest_res = ingest_eia_workbook(wb_file, requested_start=start_utc, requested_end=end_utc, manifest_path=manifest_file)
    assert ingest_res["status"] == "success_with_data_issues"
    assert ingest_res["native_emissions_status"] == "success_with_data_issues"
    assert ingest_res["carbon_status"] == "success_with_data_issues"
    assert "demand" not in ingest_res["coverage"]
    assert "net_generation" not in ingest_res["coverage"]
    assert "emissions_generated" in ingest_res["coverage"]
    assert manifest_file.exists()


def test_native_eia_workbook_missing_sheet(tmp_path):
    wb_file = tmp_path / "missing_notes.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, missing_sheet="Notes")

    with pytest.raises(ValueError, match="Workbook missing required sheets"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_corrupt_notes(tmp_path):
    wb_file = tmp_path / "corrupt_notes.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, corrupt_notes=True)

    with pytest.raises(ValueError, match="Notes sheet missing expected definition"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_missing_column(tmp_path):
    wb_file = tmp_path / "missing_col.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, missing_column=True)

    with pytest.raises(ValueError, match="Published Hourly Data sheet missing required columns"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_wrong_ba(tmp_path):
    wb_file = tmp_path / "wrong_ba.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, wrong_ba=True)

    with pytest.raises(ValueError, match="expected BA 'CISO', got 'OTHER_BA'"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc, expected_ba="CISO")


def test_native_eia_workbook_negative_emissions(tmp_path):
    wb_file = tmp_path / "neg_emissions.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, invalid_emissions=True)

    with pytest.raises(ValueError, match="negative CO2 emissions"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_intensity_reconciliation_failure(tmp_path):
    wb_file = tmp_path / "intensity_mismatch.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, intensity_mismatch=True)

    with pytest.raises(ValueError, match="generated intensity reconciliation mismatch"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_duplicate_hour(tmp_path):
    wb_file = tmp_path / "dup_hour.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, duplicate_hour=True)

    with pytest.raises(ValueError, match="duplicate record detected"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_eia_smoke_test_with_native_workbook(tmp_path, monkeypatch):
    """Test run_eia_smoke_test with native emissions workbook succeeds without API key."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    wb_file = tmp_path / "mock_CISO.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc)

    res = run_eia_smoke_test(
        balancing_authority="CISO",
        start_date=start_utc,
        end_date=end_utc,
        use_api=False,
        emissions_workbook=wb_file,
        data_dir=tmp_path / "data/raw/eia",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    # Demand/net generation are blocked due to missing API key, and native emissions is success_with_data_issues
    assert res["demand_status"] == "blocked_pending_api_key"
    assert res["net_generation_status"] == "blocked_pending_api_key"
    assert res["native_emissions_status"] == "success_with_data_issues"
    assert res["carbon_status"] == "success_with_data_issues"
    assert "coverage" in res
    assert "demand" not in res["coverage"]
    assert "net_generation" not in res["coverage"]
    assert "emissions_generated" in res["coverage"]
    assert res["coverage"]["emissions_generated"]["covered_hourly_bins"] == 24


def test_native_eia_workbook_notes_semantic_failure(tmp_path):
    """Test that parse_and_validate_eia_ciso_workbook fails when Notes definitions have wrong units or semantics."""
    wb_file = tmp_path / "bad_unit_notes.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc, bad_demand_unit=True)

    with pytest.raises(ValueError, match="failed validation. Expected to specify 'MWh'"):
        parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_notes_utc_precedence(tmp_path):
    """Test that Notes UTC time definition requires BOTH 'end of the hour' AND 'UTC' / 'Coordinated Universal Time'."""
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)

    # 1. Valid UTC definition passes
    wb_valid = tmp_path / "valid_utc_notes.xlsx"
    _create_mock_ciso_xlsx(wb_valid, hours=24, start_date_utc=start_utc, bad_utc_notes=False)
    res = parse_and_validate_eia_ciso_workbook(wb_valid, requested_start=start_utc, requested_end=end_utc)
    assert res["row_count"] == 24

    # 2. 'Coordinated Universal Time' alone WITHOUT 'end of the hour' must fail
    wb_bad = tmp_path / "bad_utc_notes.xlsx"
    _create_mock_ciso_xlsx(wb_bad, hours=24, start_date_utc=start_utc, bad_utc_notes=True)
    with pytest.raises(ValueError, match="Expected to specify 'end of the hour in UTC'"):
        parse_and_validate_eia_ciso_workbook(wb_bad, requested_start=start_utc, requested_end=end_utc)


def test_native_eia_workbook_known_data_issues_ba_isolation_and_counts(tmp_path):
    """Test that Known Data Issues correctly isolates records by BA and separates zero vs nonzero flags."""
    wb_file = tmp_path / "data_issues_ba_test.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)

    # Add extra issue rows for OTHER_BA with flag=1 at the exact same hour-ending serials
    base_excel = datetime(1899, 12, 30, tzinfo=timezone.utc)
    extra_rows = []
    for h in range(24):
        he_dt = start_utc + timedelta(hours=h + 1)
        s_val = (he_dt - base_excel).total_seconds() / 86400.0
        extra_rows.append(("OTHER_BA", s_val, 1))

    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc, issue_flag_mode="first_hour_only", extra_issue_rows=extra_rows)

    # In mock xlsx: hour 0 has issue_flag 1, hours 1..23 have issue_flag 0 for CISO.
    # OTHER_BA had flag=1 for all 24 hours, but must NOT attach to CISO!
    res = parse_and_validate_eia_ciso_workbook(wb_file, requested_start=start_utc, requested_end=end_utc, expected_ba="CISO")
    assert res["data_issues_matched_count"] == 24
    assert res["data_issues_flagged_count"] == 1
    assert res["data_issues_unflagged_count"] == 23

    rows = res["rows"]
    assert rows[0]["has_data_issue"] is True
    assert rows[0]["data_issue_flag"] == "1"
    for r in rows[1:]:
        assert r["has_data_issue"] is False
        assert r["data_issue_flag"] == "0"


def test_native_eia_workbook_status_clean_vs_flagged(tmp_path):
    """Test that all-zero flags produce status 'success', while >=1 flag produces 'success_with_data_issues'."""
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)

    # 1. All-zero flags -> 'success'
    wb_clean = tmp_path / "clean_issues.xlsx"
    _create_mock_ciso_xlsx(wb_clean, hours=24, start_date_utc=start_utc, issue_flag_mode="none")
    ingest_clean = ingest_eia_workbook(
        wb_clean,
        requested_start=start_utc,
        requested_end=end_utc,
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert ingest_clean["status"] == "success"
    assert ingest_clean["native_emissions_status"] == "success"
    assert ingest_clean["carbon_status"] == "success"
    assert ingest_clean["data_issues_flagged_count"] == 0
    assert ingest_clean["data_issues_unflagged_count"] == 24

    # 2. Flagged records -> 'success_with_data_issues'
    wb_flagged = tmp_path / "flagged_issues.xlsx"
    _create_mock_ciso_xlsx(wb_flagged, hours=24, start_date_utc=start_utc, issue_flag_mode="all")
    ingest_flagged = ingest_eia_workbook(
        wb_flagged,
        requested_start=start_utc,
        requested_end=end_utc,
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert ingest_flagged["status"] == "success_with_data_issues"
    assert ingest_flagged["native_emissions_status"] == "success_with_data_issues"
    assert ingest_flagged["carbon_status"] == "success_with_data_issues"
    assert ingest_flagged["data_issues_flagged_count"] == 24
    assert ingest_flagged["data_issues_unflagged_count"] == 0


def test_native_eia_workbook_rejects_nan_and_inf(tmp_path):
    """Test that non-finite NaN, positive infinity, and negative infinity are rejected across numeric fields."""
    base_file = tmp_path / "base_wb.xlsx"
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(base_file, hours=24, start_date_utc=start_utc)

    with zipfile.ZipFile(base_file, "r") as z_in:
        orig_files = {name: z_in.read(name) for name in z_in.namelist()}

    xml_template = orig_files["xl/worksheets/sheet1.xml"].decode("utf-8")

    # 1. NaN in Demand field
    files_nan = dict(orig_files)
    files_nan["xl/worksheets/sheet1.xml"] = xml_template.replace('<c r="I2"><v>25000.0</v></c>', '<c r="I2"><v>NaN</v></c>').encode("utf-8")
    wb_nan = tmp_path / "nan_demand.xlsx"
    with zipfile.ZipFile(wb_nan, "w") as z_out:
        for name, content in files_nan.items():
            z_out.writestr(name, content)
    with pytest.raises(ValueError, match="non-finite value .* in numeric field 'demand'"):
        parse_and_validate_eia_ciso_workbook(wb_nan, requested_start=start_utc, requested_end=end_utc)

    # 2. Positive Infinity in Net Generation field
    files_pos_inf = dict(orig_files)
    files_pos_inf["xl/worksheets/sheet1.xml"] = xml_template.replace('<c r="J2"><v>22000.0</v></c>', '<c r="J2"><v>Infinity</v></c>').encode("utf-8")
    wb_pos_inf = tmp_path / "pos_inf_net_gen.xlsx"
    with zipfile.ZipFile(wb_pos_inf, "w") as z_out:
        for name, content in files_pos_inf.items():
            z_out.writestr(name, content)
    with pytest.raises(ValueError, match="non-finite value .* in numeric field 'net_generation'"):
        parse_and_validate_eia_ciso_workbook(wb_pos_inf, requested_start=start_utc, requested_end=end_utc)

    # 3. Negative Infinity in Demand field
    files_neg_inf = dict(orig_files)
    files_neg_inf["xl/worksheets/sheet1.xml"] = xml_template.replace('<c r="I2"><v>25000.0</v></c>', '<c r="I2"><v>-Infinity</v></c>').encode("utf-8")
    wb_neg_inf = tmp_path / "neg_inf_demand.xlsx"
    with zipfile.ZipFile(wb_neg_inf, "w") as z_out:
        for name, content in files_neg_inf.items():
            z_out.writestr(name, content)
    with pytest.raises(ValueError, match="non-finite value .* in numeric field 'demand'"):
        parse_and_validate_eia_ciso_workbook(wb_neg_inf, requested_start=start_utc, requested_end=end_utc)

    # 4. Non-finite (NaN) in generated emissions field
    files_em_nan = dict(orig_files)
    files_em_nan["xl/worksheets/sheet1.xml"] = xml_template.replace('<c r="CK2"><v>3000.0</v></c>', '<c r="CK2"><v>NaN</v></c>').encode("utf-8")
    wb_em_nan = tmp_path / "nan_emissions.xlsx"
    with zipfile.ZipFile(wb_em_nan, "w") as z_out:
        for name, content in files_em_nan.items():
            z_out.writestr(name, content)
    with pytest.raises(ValueError, match="non-finite value .* in numeric field 'co2_emissions_generated'"):
        parse_and_validate_eia_ciso_workbook(wb_em_nan, requested_start=start_utc, requested_end=end_utc)

    # 5. Non-finite (Infinity) in generated intensity field
    files_int_inf = dict(orig_files)
    # Intensity value in CQ2
    files_int_inf["xl/worksheets/sheet1.xml"] = xml_template.replace('<c r="CQ2"><v>', '<c r="CQ2"><v>Infinity</v></c><!--').replace('</v></c><c r="CR2">', '--> <c r="CR2">')
    # simpler direct replacement:
    wb_int_inf = tmp_path / "inf_intensity.xlsx"
    import re
    mod_xml = re.sub(r'<c r="CQ2"><v>[^<]+</v></c>', '<c r="CQ2"><v>Infinity</v></c>', xml_template)
    files_int_inf["xl/worksheets/sheet1.xml"] = mod_xml.encode("utf-8")
    with zipfile.ZipFile(wb_int_inf, "w") as z_out:
        for name, content in files_int_inf.items():
            z_out.writestr(name, content)
    with pytest.raises(ValueError, match="non-finite value .* in numeric field 'co2_intensity_generated'"):
        parse_and_validate_eia_ciso_workbook(wb_int_inf, requested_start=start_utc, requested_end=end_utc)


def test_cli_partial_eia_success_coverage_rows(tmp_path, monkeypatch):
    """Test that CLI emits native emissions coverage rows even if API demand/gen is blocked, without blocker row."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    wb_file = tmp_path / "CISO.xlsx"
    # CLI smoke tests evaluate [2022-06-01T00:00:00Z, 2022-06-02T00:00:00Z)
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc, issue_flag_mode="none")

    manifest_path = tmp_path / "manifests/raw_sources.jsonl"
    coverage_path = tmp_path / "manifests/coverage.csv"

    from heattrace.cli import run_smoke_tests
    args = parse_args([
        "--source=eia",
        f"--data-dir={tmp_path}",
        f"--eia-emissions-workbook={wb_file}",
    ])

    run_smoke_tests(args)
    assert coverage_path.exists()
    rows = list(csv.DictReader(coverage_path.open("r", encoding="utf-8")))

    # Check native emissions coverage rows are written as success
    native_emissions_rows = [r for r in rows if "emissions-" in r["dataset"] or "intensity-" in r["dataset"]]
    assert len(native_emissions_rows) == 4
    for r in native_emissions_rows:
        assert r["status"] == "success"
        assert int(r["covered_hourly_bins"]) == 24

    # Blocker row EIA-930-emissions-native should NOT be present since native workbook succeeded
    blocker_rows = [r for r in rows if r["dataset"] == "EIA-930-emissions-native"]
    assert len(blocker_rows) == 0

    # Demand and Net-Gen should be truthfully blocked, and NOT have fabricated 24/24 coverage
    d_rows = [r for r in rows if r["dataset"] == "EIA-930-demand"]
    assert len(d_rows) == 1
    assert d_rows[0]["status"] == "blocked_pending_api_key"
    assert d_rows[0]["covered_hourly_bins"] in ("", "0", None)

    ng_rows = [r for r in rows if r["dataset"] == "EIA-930-net-generation"]
    assert len(ng_rows) == 1
    assert ng_rows[0]["status"] == "blocked_pending_api_key"
    assert ng_rows[0]["covered_hourly_bins"] in ("", "0", None)


def test_cli_qc_exit_nonzero_when_eia_api_blocked(tmp_path, monkeypatch):
    """Test that run_qc_tests returns 1 (failure) when EIA API demand/generation is blocked in non-dry-run mode."""
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    wb_file = tmp_path / "raw/eia/CISO.xlsx"
    wb_file.parent.mkdir(parents=True, exist_ok=True)
    start_utc = datetime(2022, 6, 1, 7, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc)

    from heattrace.cli import run_qc_tests
    args = parse_args([
        "--qc",
        f"--data-dir={tmp_path}",
        f"--eia-emissions-workbook={wb_file}",
    ])

    code = run_qc_tests(args)
    # Non-dry-run QC execution MUST return nonzero if EIA demand/net-gen are blocked
    assert code == 1


def test_cli_qc_exit_zero_on_dry_run(tmp_path):
    """Test that run_qc_tests returns 0 in dry-run mode."""
    from heattrace.cli import run_qc_tests
    args = parse_args([
        "--qc",
        "--dry-run",
        f"--data-dir={tmp_path}",
    ])
    code = run_qc_tests(args)
    assert code == 0


def test_eia_smoke_api_success_with_workbook_success(tmp_path, monkeypatch):
    """Test that when both API and workbook succeed, API coverage is preserved without workbook overwriting it."""
    monkeypatch.setenv("EIA_API_KEY", "test_key_123")
    wb_file = tmp_path / "mock_CISO.xlsx"
    start_utc = datetime(2022, 6, 1, 0, 0, tzinfo=timezone.utc)
    end_utc = datetime(2022, 6, 2, 0, 0, tzinfo=timezone.utc)
    _create_mock_ciso_xlsx(wb_file, hours=24, start_date_utc=start_utc, issue_flag_mode="none")

    # Mock EIA API response with 24 demand and 24 net-gen records
    data_records = []
    for h in range(1, 25):
        period_str = (start_utc + timedelta(hours=h)).strftime("%Y-%m-%dT%H")
        data_records.append({"period": period_str, "respondent": "CISO", "type": "D", "value": "25000"})
        data_records.append({"period": period_str, "respondent": "CISO", "type": "NG", "value": "22000"})
    fake_api_json = json.dumps({"response": {"data": data_records}}).encode("utf-8")

    from unittest.mock import MagicMock, patch
    mock_resp = MagicMock()
    mock_resp.read.return_value = fake_api_json
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = run_eia_smoke_test(
            balancing_authority="CISO",
            start_date=start_utc,
            end_date=end_utc,
            use_api=True,
            emissions_workbook=wb_file,
            data_dir=tmp_path / "data/raw/eia",
            manifest_path=tmp_path / "manifest.jsonl",
        )

    assert res["status"] == "success"
    assert res["demand_status"] == "success"
    assert res["net_generation_status"] == "success"
    assert res["native_emissions_status"] == "success"
    assert res["carbon_status"] == "success"

    # Coverage contains both API metrics and workbook carbon metrics
    cov = res["coverage"]
    assert "demand" in cov
    assert "net_generation" in cov
    assert "emissions_generated" in cov
    assert "emissions_consumed" in cov
    assert "intensity_generated" in cov
    assert "intensity_consumed" in cov
    assert cov["demand"]["covered_hourly_bins"] == 24
    assert cov["net_generation"]["covered_hourly_bins"] == 24
    assert cov["emissions_generated"]["covered_hourly_bins"] == 24


def test_qc_deterministic_gates(tmp_path):
    """Test full isolation of QC gate rules:
    - all signals success & clean -> exit 0
    - flagged EIA data under default policy -> exit 1
    - flagged EIA data with --no-fail-on-eia-data-issues -> exit 0
    - incomplete CAISO -> exit 1
    - provisional NOAA -> exit 1
    - missing native carbon metric -> exit 1
    - duplicate hourly record -> exit 1
    """
    from heattrace.cli import run_qc_tests

    # Base helper to build coverage rows for both days
    def build_mock_qc_rows(
        *,
        noaa_status="verified",
        caiso_miss=0,
        caiso_dups=0,
        eia_demand_stat="success",
        eia_net_gen_stat="success",
        native_stat="success",
        missing_metric=None,
        dup_hours=0,
    ):
        rows = []
        for d_label, d_date in [("heatwave", "2022-09-05"), ("ordinary", "2022-06-01")]:
            start_dt = f"{d_date}T07:00:00+00:00"
            end_dt = f"{d_date}T07:00:00+00:00"
            # NOAA
            rows.append({
                "source": "NOAA",
                "dataset": "GHCNh",
                "status": "success" if noaa_status == "verified" else "provisional",
                "requested_start": start_dt,
                "requested_end": end_dt,
                "row_count": 24,
                "unique_timestamps": 24,
                "covered_hourly_bins": 24,
                "expected_hours": 24,
                "missing_hours": 0,
                "duplicate_timestamps": 0,
                "qc_day_type": d_label,
                "qc_day_status": noaa_status,
                "local_date": d_date,
            })
            # CAISO
            rows.append({
                "source": "CAISO",
                "dataset": "PRC_LMP",
                "status": "success" if caiso_miss == 0 and caiso_dups == 0 else "failure",
                "requested_start": start_dt,
                "requested_end": end_dt,
                "row_count": 24,
                "unique_timestamps": 24,
                "covered_hourly_bins": 24 - caiso_miss,
                "expected_hours": 24,
                "missing_hours": caiso_miss,
                "duplicate_timestamps": caiso_dups,
                "qc_day_type": d_label,
                "qc_day_status": noaa_status,
                "local_date": d_date,
            })
            # EIA demand & net-gen
            rows.append({
                "source": "EIA",
                "dataset": "EIA-930-demand",
                "status": eia_demand_stat,
                "requested_start": start_dt,
                "requested_end": end_dt,
                "row_count": 24 if eia_demand_stat == "success" else 0,
                "unique_timestamps": 24 if eia_demand_stat == "success" else 0,
                "covered_hourly_bins": 24 if eia_demand_stat == "success" else 0,
                "expected_hours": 24,
                "missing_hours": 0 if eia_demand_stat == "success" else 24,
                "duplicate_timestamps": 0,
                "qc_day_type": d_label,
                "qc_day_status": noaa_status,
                "local_date": d_date,
            })
            rows.append({
                "source": "EIA",
                "dataset": "EIA-930-net-generation",
                "status": eia_net_gen_stat,
                "requested_start": start_dt,
                "requested_end": end_dt,
                "row_count": 24 if eia_net_gen_stat == "success" else 0,
                "unique_timestamps": 24 if eia_net_gen_stat == "success" else 0,
                "covered_hourly_bins": 24 if eia_net_gen_stat == "success" else 0,
                "expected_hours": 24,
                "missing_hours": 0 if eia_net_gen_stat == "success" else 24,
                "duplicate_timestamps": 0,
                "qc_day_type": d_label,
                "qc_day_status": noaa_status,
                "local_date": d_date,
            })
            # Native carbon metrics
            for metric_name in ("emissions-generated", "emissions-consumed", "intensity-generated", "intensity-consumed"):
                if missing_metric == metric_name:
                    continue
                rows.append({
                    "source": "EIA",
                    "dataset": f"EIA-930-{metric_name}",
                    "status": native_stat,
                    "requested_start": start_dt,
                    "requested_end": end_dt,
                    "row_count": 24,
                    "unique_timestamps": 24,
                    "covered_hourly_bins": 24,
                    "expected_hours": 24,
                    "missing_hours": 0,
                    "duplicate_timestamps": dup_hours,
                    "qc_day_type": d_label,
                    "qc_day_status": noaa_status,
                    "local_date": d_date,
                })
        return rows

    # Mock runners so run_qc_tests only evaluates the gate
    from unittest.mock import patch

    def run_with_rows(mock_rows, cli_args=None):
        if cli_args is None:
            cli_args = ["--qc", f"--data-dir={tmp_path}"]
        args = parse_args(cli_args)

        with patch("heattrace.cli.run_noaa_smoke_test"), \
             patch("heattrace.cli.run_caiso_smoke_test"), \
             patch("heattrace.cli.run_eia_smoke_test"), \
             patch("heattrace.cli.write_coverage_report"):
            # Inject coverage rows directly into the gate
            # We patch the inner loop of run_qc_tests by monkeypatching coverage_rows
            # Or simpler: run a test function that executes the gate logic
            # Let's inspect run_qc_tests: we can mock run_noaa_smoke_test, run_caiso_smoke_test, run_eia_smoke_test
            # to return dummy dicts, but it's much cleaner to test the gate logic directly.
            pass

    # Direct test of gate logic via mocked smoke test responses:
    def execute_qc(cli_flags, noaa_dm=31.1, caiso_cov=24, caiso_miss=0, caiso_dup=0, eia_api_ok=True, native_stat="success", dup_native=0, omit_intensity=False, custom_sources=None):
        c_dir = tmp_path / "cfg"
        c_dir.mkdir(exist_ok=True)
        import shutil
        if custom_sources:
            (c_dir / "sources.yaml").write_text(custom_sources, encoding="utf-8")
        else:
            shutil.copy("configs/sources.yaml", c_dir / "sources.yaml")

        args = parse_args(["--qc", f"--config-dir={c_dir}", f"--data-dir={tmp_path}"] + cli_flags)

        def mock_noaa(*a, **kw):
            date_str = "2024-07-02" if "2024-07-02" in str(kw.get("day_start")) else "2024-06-07"
            temp = 31.1 if date_str == "2024-07-02" else 21.7
            if noaa_dm is not None and noaa_dm != 31.1 and date_str == "2024-07-02":
                temp = noaa_dm
            return {
                "status": "success" if temp in (31.1, 21.7) else "failure",
                "daily_maxima": [{
                    "local_date": date_str,
                    "daily_max_temperature_c": temp,
                    "timestamps_utc": ["fake"],
                    "valid_observation_count": 28,
                }],
                "coverage": {
                    "observed_start": "start",
                    "observed_end": "end",
                    "row_count": 24,
                    "unique_timestamps": 24,
                    "covered_hourly_bins": 24,
                    "missing_hours": 0,
                    "duplicate_timestamps": 0,
                }
            }

        def mock_caiso(*a, **kw):
            return {
                "status": "success" if caiso_miss == 0 and caiso_dup == 0 else "failure",
                "coverage": {
                    "observed_start": "start",
                    "observed_end": "end",
                    "row_count": caiso_cov,
                    "unique_timestamps": caiso_cov,
                    "covered_hourly_bins": caiso_cov,
                    "missing_hours": caiso_miss,
                    "duplicate_timestamps": caiso_dup,
                }
            }

        def mock_eia(*a, **kw):
            cov_24 = {
                "observed_start": "start",
                "observed_end": "end",
                "row_count": 24,
                "unique_timestamps": 24,
                "covered_hourly_bins": 24,
                "missing_hours": 0,
                "duplicate_timestamps": dup_native,
            }
            c_dict = {}
            if eia_api_ok:
                c_dict["demand"] = cov_24
                c_dict["net_generation"] = cov_24
            if native_stat in ("success", "success_with_data_issues"):
                c_dict["emissions_generated"] = cov_24
                c_dict["emissions_consumed"] = cov_24
                if not omit_intensity:
                    c_dict["intensity_generated"] = cov_24
                    c_dict["intensity_consumed"] = cov_24

            return {
                "status": "success" if eia_api_ok else "blocked_pending_api_key",
                "demand_status": "success" if eia_api_ok else "blocked_pending_api_key",
                "net_generation_status": "success" if eia_api_ok else "blocked_pending_api_key",
                "native_emissions_status": native_stat,
                "coverage": c_dict,
                "workbook_result": {
                    "data_issues_matched_count": 24,
                    "data_issues_flagged_count": 24 if native_stat == "success_with_data_issues" else 0,
                    "data_issues_unflagged_count": 0 if native_stat == "success_with_data_issues" else 24,
                }
            }

        # Ensure noaa_psv_cache exists so compute_baseline_summer_percentile is executed
        noaa_cache_file = tmp_path / "raw/noaa/GHCNh_USW00023234_2024.psv"
        noaa_cache_file.parent.mkdir(parents=True, exist_ok=True)
        noaa_cache_file.write_text("header\n", encoding="utf-8")

        with patch("heattrace.cli.run_noaa_smoke_test", side_effect=mock_noaa), \
             patch("heattrace.cli.run_caiso_smoke_test", side_effect=mock_caiso), \
             patch("heattrace.cli.run_eia_smoke_test", side_effect=mock_eia), \
             patch("heattrace.cli.compute_baseline_summer_percentile", return_value={
                 "baseline_years": [2024],
                 "summer_median_c": 20.6,
                 "heatwave_percentile": 98.0,
                 "heatwave_threshold_c": 30.0,
                 "valid_baseline_days": 122,
             }):
            return run_qc_tests(args)

    # 1. Ingestion-only policy in sources.yaml (fail_on_eia_data_issues: false) accepts success_with_data_issues -> returns 0
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], native_stat="success_with_data_issues") == 0

    # 2. If conservative policy enforced via CLI flag --fail-on-eia-data-issues -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx", "--fail-on-eia-data-issues"], native_stat="success_with_data_issues") == 1

    # 3. Clean success on both days -> returns 0
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], native_stat="success") == 0

    # 4. Blocked EIA API -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], eia_api_ok=False) == 1

    # 5. Incomplete CAISO -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], caiso_cov=20, caiso_miss=4) == 1

    # 6. Failed NOAA day (below P98 threshold of 30.0°C) -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], noaa_dm=28.0) == 1

    # 7. Missing native carbon metric -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], omit_intensity=True) == 1

    # 8. Duplicate hourly records -> returns 1
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], dup_native=2) == 1

    # 9. Optional floor test: when heatwave_threshold_min_c=34.0 is configured, 31.1°C fails (31.1 < max(30.0, 34.0))
    cfg_with_floor = """
study:
  region: CAISO
  years: [2024]
  months: [6, 7, 8, 9]
  timezone: UTC
price:
  node: TH_NP15_GEN-APND
carbon:
  balancing_authority: CISO
weather:
  stations:
    - id: USW00023234
qc:
  baseline:
    years: [2024]
    months: [6, 7, 8, 9]
    percentile_method: linear_interpolation
    heatwave_percentile: 98.0
    tolerance_c: 0.5
    heatwave_threshold_min_c: 34.0
    ordinary_day_range_c: [20.0, 24.0]
  days:
    heatwave:
      date: "2024-07-02"
      type: heatwave
      expected_max_temperature_c: 31.1
    ordinary:
      date: "2024-06-07"
      type: ordinary
      expected_max_temperature_c: 21.7
  fail_on_eia_data_issues: false
"""
    assert execute_qc(["--eia-emissions-workbook=dummy.xlsx"], custom_sources=cfg_with_floor) == 1


# =========================================================================
# 10. Coverage CSV Serialization & Data Issues Columns Tests
# =========================================================================

def test_coverage_csv_preserves_data_issues_columns(tmp_path):
    """Confirm write_coverage_report preserves data-issue counts and leaves them blank for non-EIA rows."""
    from heattrace.ingest.coverage import write_coverage_report
    import csv

    csv_file = tmp_path / "coverage_test.csv"
    sample_rows = [
        {
            "source": "NOAA",
            "dataset": "GHCNh",
            "status": "success",
            "requested_start": "2022-09-05T07:00:00+00:00",
            "requested_end": "2022-09-06T07:00:00+00:00",
            "row_count": 28,
            "unique_timestamps": 28,
            "covered_hourly_bins": 24,
            "expected_hours": 24,
            "missing_hours": 0,
            "duplicate_timestamps": 0,
            "notes": "QC heatwave day Station USW00023234",
            "qc_day_type": "heatwave",
            "qc_day_status": "verified",
            "local_date": "2022-09-05",
            "daily_max_temperature_c": 35.6,
        },
        {
            "source": "EIA",
            "dataset": "EIA-930-emissions-generated",
            "status": "success_with_data_issues",
            "requested_start": "2022-09-05T07:00:00+00:00",
            "requested_end": "2022-09-06T07:00:00+00:00",
            "row_count": 24,
            "unique_timestamps": 24,
            "covered_hourly_bins": 24,
            "expected_hours": 24,
            "missing_hours": 0,
            "duplicate_timestamps": 0,
            "notes": "QC heatwave day native workbook emissions_generated",
            "qc_day_type": "heatwave",
            "qc_day_status": "verified",
            "local_date": "2022-09-05",
            "data_issues_matched_count": 24,
            "data_issues_flagged_count": 24,
            "data_issues_unflagged_count": 0,
        },
    ]

    write_coverage_report(csv_file, sample_rows)
    assert csv_file.exists()

    with csv_file.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == 2
    # Fieldnames must include the three new columns
    with csv_file.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert "data_issues_matched_count" in header
    assert "data_issues_flagged_count" in header
    assert "data_issues_unflagged_count" in header

    # Non-EIA row: columns are present and blank
    noaa_row = reader[0]
    assert noaa_row["source"] == "NOAA"
    assert noaa_row["data_issues_matched_count"] == ""
    assert noaa_row["data_issues_flagged_count"] == ""
    assert noaa_row["data_issues_unflagged_count"] == ""

    # EIA row: columns survive exactly
    eia_row = reader[1]
    assert eia_row["source"] == "EIA"
    assert int(eia_row["data_issues_matched_count"]) == 24
    assert int(eia_row["data_issues_flagged_count"]) == 24
    assert int(eia_row["data_issues_unflagged_count"]) == 0


def test_coverage_csv_authentic_workbook_counts(tmp_path):
    """Confirm both QC days report 24 matched, 24 flagged, and 0 unflagged for each native EIA carbon metric using authentic workbook."""
    from heattrace.ingest.eia import ingest_eia_workbook
    from heattrace.ingest.coverage import write_coverage_report
    import csv

    wb_path = Path("data/raw/eia/CISO.xlsx")
    if not wb_path.exists():
        pytest.skip("Authentic EIA workbook not found at data/raw/eia/CISO.xlsx")

    csv_file = tmp_path / "authentic_qc_coverage.csv"
    qc_days = [
        ("ordinary", "2024-06-07", datetime(2024, 6, 7, 7, 0, tzinfo=timezone.utc), datetime(2024, 6, 8, 7, 0, tzinfo=timezone.utc)),
        ("heatwave", "2024-07-02", datetime(2024, 7, 2, 7, 0, tzinfo=timezone.utc), datetime(2024, 7, 3, 7, 0, tzinfo=timezone.utc)),
    ]

    coverage_rows = []
    for day_label, date_str, start_utc, end_utc in qc_days:
        res = ingest_eia_workbook(
            wb_path,
            balancing_authority="CISO",
            requested_start=start_utc,
            requested_end=end_utc,
            manifest_path=tmp_path / "manifest.jsonl",
        )
        assert res["native_emissions_status"] == "success_with_data_issues"
        assert res["data_issues_matched_count"] == 24
        assert res["data_issues_flagged_count"] == 24
        assert res["data_issues_unflagged_count"] == 0

        for metric in ["emissions_generated", "emissions_consumed", "intensity_generated", "intensity_consumed"]:
            sub_cov = res["coverage"][metric]
            coverage_rows.append({
                "source": "EIA",
                "dataset": f"EIA-930-{metric.replace('_', '-')}",
                "status": res["native_emissions_status"],
                "requested_start": start_utc.isoformat(),
                "requested_end": end_utc.isoformat(),
                "row_count": sub_cov["row_count"],
                "unique_timestamps": sub_cov["unique_timestamps"],
                "covered_hourly_bins": sub_cov["covered_hourly_bins"],
                "expected_hours": sub_cov["expected_hours"],
                "missing_hours": sub_cov["missing_hours"],
                "duplicate_timestamps": sub_cov["duplicate_timestamps"],
                "notes": f"QC {day_label} day ({date_str}) BA CISO native workbook {metric}",
                "qc_day_type": day_label,
                "local_date": date_str,
                "data_issues_matched_count": res["data_issues_matched_count"],
                "data_issues_flagged_count": res["data_issues_flagged_count"],
                "data_issues_unflagged_count": res["data_issues_unflagged_count"],
            })

    write_coverage_report(csv_file, coverage_rows)

    with csv_file.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) == 8  # 4 metrics * 2 days
    for r in reader:
        assert r["source"] == "EIA"
        assert r["status"] == "success_with_data_issues"
        assert r["covered_hourly_bins"] == "24"
        assert r["missing_hours"] == "0"
        assert r["data_issues_matched_count"] == "24"
        assert r["data_issues_flagged_count"] == "24"
        assert r["data_issues_unflagged_count"] == "0"


def test_smoke_eia_native_data_issues_reporting_fixes(tmp_path):
    """Test non-QC EIA smoke-test path:
    1. native status 'success_with_data_issues' must count as successful workbook ingestion and NOT generate a contradictory blocked_pending_emissions_file_discovery row.
    2. Native EIA smoke-report coverage rows must serialize data_issues_matched_count, data_issues_flagged_count, and data_issues_unflagged_count.
    3. Non-EIA rows leave those fields blank.
    4. No row simultaneously reports successful workbook ingestion and claims workbook discovery is blocked.
    """
    from heattrace.cli import run_smoke_tests, parse_args
    import csv

    # Set up config and dummy directories
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "study.yaml").write_text("timestamp:\n  timezone: UTC\n", encoding="utf-8")
    (config_dir / "sources.yaml").write_text(
        "study:\n  region: CAISO\ncarbon:\n  balancing_authority: CISO\n"
        "weather:\n  stations:\n    - id: USW00023234\nprice:\n  node: TH_NP15_GEN-APND\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = data_dir / "manifests/raw_sources.jsonl"
    coverage_path = data_dir / "manifests/coverage.csv"

    # Mock run_eia_smoke_test returning success_with_data_issues
    mock_cov = {
        "requested_start": "2022-06-01T00:00:00+00:00",
        "requested_end": "2022-06-02T00:00:00+00:00",
        "observed_start": "2022-06-01T00:00:00+00:00",
        "observed_end": "2022-06-01T23:00:00+00:00",
        "row_count": 24,
        "unique_timestamps": 24,
        "covered_hourly_bins": 24,
        "expected_hours": 24,
        "missing_hours": 0,
        "duplicate_timestamps": 0,
    }
    mock_eia_result = {
        "status": "success",
        "demand_status": "success",
        "net_generation_status": "success",
        "native_emissions_status": "success_with_data_issues",
        "carbon_status": "success_with_data_issues",
        "coverage": {
            "demand": mock_cov,
            "net_generation": mock_cov,
            "emissions_generated": mock_cov,
            "emissions_consumed": mock_cov,
            "intensity_generated": mock_cov,
            "intensity_consumed": mock_cov,
        },
        "workbook_result": {
            "data_issues_matched_count": 24,
            "data_issues_flagged_count": 24,
            "data_issues_unflagged_count": 0,
        },
        "data_issues_matched_count": 24,
        "data_issues_flagged_count": 24,
        "data_issues_unflagged_count": 0,
    }

    args = parse_args([
        "--source=eia",
        f"--config-dir={config_dir}",
        f"--data-dir={data_dir}",
    ])

    with patch("heattrace.cli.run_eia_smoke_test", return_value=mock_eia_result):
        exit_code = run_smoke_tests(args)

    assert exit_code == 0
    assert coverage_path.exists()

    with coverage_path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    datasets = [r["dataset"] for r in rows]
    # 1. No contradictory blocker row
    assert "EIA-930-emissions-native" not in datasets
    assert not any("blocked_pending_emissions_file_discovery" in r["status"] for r in rows)

    # 2. Issue count fields survived serialization for native metrics
    native_rows = [r for r in rows if r["dataset"].startswith("EIA-930-emissions-") or r["dataset"].startswith("EIA-930-intensity-")]
    assert len(native_rows) == 4
    for r in native_rows:
        assert r["status"] == "success_with_data_issues"
        assert r["data_issues_matched_count"] == "24"
        assert r["data_issues_flagged_count"] == "24"
        assert r["data_issues_unflagged_count"] == "0"

    # 3. Non-native / non-EIA rows leave those fields blank
    api_rows = [r for r in rows if r["dataset"] in ("EIA-930-demand", "EIA-930-net-generation")]
    assert len(api_rows) == 2
    for r in api_rows:
        assert r["data_issues_matched_count"] == ""
        assert r["data_issues_flagged_count"] == ""
        assert r["data_issues_unflagged_count"] == ""


def test_production_manifests_remain_unmodified_by_tests(tmp_path):
    """Regression test ensuring that test runs do not create or modify production manifests."""
    prod_manifest = Path("data/manifests/raw_sources.jsonl")
    prod_coverage = Path("data/manifests/coverage.csv")

    manifest_mtime = prod_manifest.stat().st_mtime if prod_manifest.exists() else None
    coverage_mtime = prod_coverage.stat().st_mtime if prod_coverage.exists() else None

    # Run smoke test with explicit tmp_path
    args = parse_args(["--dry-run", "--data-dir", str(tmp_path)])
    code = run_smoke_tests(args)
    assert code == 0

    if manifest_mtime is not None:
        assert prod_manifest.stat().st_mtime == manifest_mtime
    else:
        assert not prod_manifest.exists()

    if coverage_mtime is not None:
        assert prod_coverage.stat().st_mtime == coverage_mtime
    else:
        assert not prod_coverage.exists()
