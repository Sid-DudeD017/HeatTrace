#!/usr/bin/env python3
"""Self-contained read-only verifier for HeatTrace v1 archive."""
import json
import hashlib
import sys
from pathlib import Path

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def main():
    archive_root = Path(__file__).resolve().parent
    manifest_path = archive_root / "archive_manifest.json"
    if not manifest_path.exists():
        print("FAIL: archive_manifest.json missing!")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    inventory = manifest.get("inventory", [])
    errors = []
    checked = 0
    inv_paths = set()

    for item in inventory:
        rel_path = item["path"]
        inv_paths.add(rel_path)
        expected_size = item["bytes"]
        expected_sha = item["sha256"]
        target = archive_root / rel_path
        if not target.exists():
            errors.append(f"Missing file: {rel_path}")
            continue
        actual_size = target.stat().st_size
        if actual_size != expected_size:
            errors.append(f"Size mismatch for {rel_path}: got {actual_size}, expected {expected_size}")
        actual_sha = sha256_file(target)
        if actual_sha != expected_sha:
            errors.append(f"SHA mismatch for {rel_path}: got {actual_sha}, expected {expected_sha}")
        checked += 1

    # Check for extraneous files
    all_disk_files = set()
    for p in archive_root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(archive_root))
            if rel not in ("archive_manifest.json", "verify_archive.py"):
                all_disk_files.add(rel)

    extraneous = all_disk_files - inv_paths
    if extraneous:
        for ex in sorted(extraneous):
            errors.append(f"Extraneous unindexed file: {ex}")

    if errors:
        print(f"VERIFICATION FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print(f"SUCCESS: All {checked} inventory files verified byte-identical against archive manifest.")
    print(f"Decision: {manifest.get('scientific_decision')}")
    print(f"Implementation commit: {manifest.get('stage1_implementation_commit')}")

if __name__ == "__main__":
    main()
