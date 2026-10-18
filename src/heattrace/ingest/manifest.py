"""JSONL provenance records for acquired source files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .provenance import sha256_file


def _canonical_request(req: dict[str, Any] | None) -> dict[str, Any]:
    """Return a deterministic representation of request parameters without volatile keys."""
    if not req:
        return {}
    # Use json roundtrip to normalize nested tuples to lists so in-memory requests
    # match parsed JSONL entries identically.
    sorted_dict = {k: req[k] for k in sorted(req.keys())}
    return json.loads(json.dumps(sorted_dict, sort_keys=True))


def build_record(
    path: str | Path,
    *,
    provider: str,
    dataset: str,
    request: dict[str, Any] | None = None,
    retrieved_at: datetime | None = None,
    cache_hit: bool = False,
    first_observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Build a deterministic, serializable raw-source manifest record.
    
    If cache_hit is True and retrieved_at is None (unmanifested cache file),
    retrieved_at is set to None and retrieval_time_known is False.
    """
    source = Path(path)
    now_utc = datetime.now(timezone.utc)

    if cache_hit:
        if retrieved_at is not None:
            if retrieved_at.tzinfo is None:
                raise ValueError("retrieved_at must be timezone-aware")
            ret_str: str | None = retrieved_at.astimezone(timezone.utc).isoformat()
            ret_known = True
        else:
            ret_str = None
            ret_known = False

        obs_ts = first_observed_at or now_utc
        if obs_ts.tzinfo is None:
            raise ValueError("first_observed_at must be timezone-aware")
        obs_str = obs_ts.astimezone(timezone.utc).isoformat()
    else:
        # Fresh download
        ts = retrieved_at or now_utc
        if ts.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        ret_str = ts.astimezone(timezone.utc).isoformat()
        obs_str = ret_str
        ret_known = True

    return {
        "cache_hit": cache_hit,
        "dataset": dataset,
        "first_observed_at": obs_str,
        "path": str(source),
        "provider": provider,
        "request": _canonical_request(request),
        "retrieval_time_known": ret_known,
        "retrieved_at": ret_str,
        "sha256": sha256_file(source),
        "size_bytes": source.stat().st_size,
    }


def find_matching_record(
    manifest_path: str | Path,
    *,
    provider: str,
    dataset: str,
    target_path: str | Path,
    sha256: str,
    request: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Find an existing manifest record matching provider, dataset, path, sha256, and request."""
    manifest = Path(manifest_path)
    if not manifest.exists():
        return None

    norm_path = str(Path(target_path))
    canon_req = _canonical_request(request)

    with manifest.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                rec.get("provider") == provider
                and rec.get("dataset") == dataset
                and rec.get("path") == norm_path
                and rec.get("sha256") == sha256
                and _canonical_request(rec.get("request")) == canon_req
            ):
                return rec
    return None


def record_provenance(
    manifest_path: str | Path,
    target_path: str | Path,
    *,
    provider: str,
    dataset: str,
    request: dict[str, Any] | None = None,
    retrieved_at: datetime | None = None,
    is_cache_hit: bool = False,
) -> dict[str, Any]:
    """Record provenance deterministically.
    
    If is_cache_hit is True and a matching record already exists in the manifest,
    returns the existing original record without appending a duplicate retrieval entry.
    If is_cache_hit is True but no matching record exists in the manifest,
    records retrieved_at=None, retrieval_time_known=False, and first_observed_at=now.
    """
    path = Path(target_path)
    current_sha = sha256_file(path)
    
    if is_cache_hit:
        existing = find_matching_record(
            manifest_path,
            provider=provider,
            dataset=dataset,
            target_path=path,
            sha256=current_sha,
            request=request,
        )
        if existing is not None:
            return existing

        # Cache hit without existing record
        record = build_record(
            path,
            provider=provider,
            dataset=dataset,
            request=request,
            retrieved_at=None,
            cache_hit=True,
        )
        append_record(manifest_path, record)
        return record

    # Fresh download
    record = build_record(
        path,
        provider=provider,
        dataset=dataset,
        request=request,
        retrieved_at=retrieved_at,
        cache_hit=False,
    )
    append_record(manifest_path, record)
    return record


def append_record(path: str | Path, record: dict[str, Any]) -> None:
    """Append one manifest record, creating its parent directory."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
