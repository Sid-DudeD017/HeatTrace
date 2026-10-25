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


def load_json_reject_duplicates(text: str) -> dict:
    """Load JSON while rejecting duplicate object keys."""
    def pairs_hook(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError(f"Duplicate JSON key detected: '{k}'")
            obj[k] = v
        return obj

    return json.loads(text, object_pairs_hook=pairs_hook)


def verify_archive(archive_root: Path) -> list[str]:
    """Run full read-only verification suite against archive directory. Returns list of errors."""
    errors = []
    manifest_path = archive_root / "archive_manifest.json"
    if not manifest_path.exists():
        return ["archive_manifest.json missing!"]

    # 1. Parse JSON rejecting duplicate keys
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = load_json_reject_duplicates(manifest_text)
    except Exception as e:
        return [f"Failed to parse archive_manifest.json: {e}"]

    # 2. Check required fields
    required_fields = [
        "schema_version",
        "archive_id",
        "runner_execution_commit",
        "analysis_implementation_commit",
        "scientific_decision",
        "decision_details",
        "confirmatory_vs_exploratory",
        "reproduction_summary",
        "file_count",
        "inventory",
        "external_source_inputs",
    ]
    for rf in required_fields:
        if rf not in manifest:
            errors.append(f"Missing required manifest field: '{rf}'")

    if errors:
        return errors

    inventory = manifest.get("inventory", [])
    declared_file_count = manifest.get("file_count")

    # 3. Check declared file count
    if len(inventory) != declared_file_count:
        errors.append(f"Declared file_count ({declared_file_count}) does not match inventory length ({len(inventory)})")

    inv_paths = set()
    root_resolved = archive_root.resolve()

    # 4. Check each inventory item
    for item in inventory:
        rel_path = item.get("path")
        if not rel_path:
            errors.append("Inventory item missing 'path'")
            continue

        # Check path security: absolute, .., escaping root
        p_obj = Path(rel_path)
        if p_obj.is_absolute():
            errors.append(f"Absolute inventory path forbidden: '{rel_path}'")
            continue
        if ".." in p_obj.parts:
            errors.append(f"Path traversal ('..') forbidden in inventory path: '{rel_path}'")
            continue

        # Check duplicates
        if rel_path in inv_paths:
            errors.append(f"Duplicate inventory path: '{rel_path}'")
            continue
        inv_paths.add(rel_path)

        expected_size = item.get("bytes")
        expected_sha = item.get("sha256")

        target = (archive_root / rel_path)
        # Check target resolution escapes archive root
        try:
            target_resolved = target.resolve()
            if not str(target_resolved).startswith(str(root_resolved)):
                errors.append(f"Inventory path escapes archive root: '{rel_path}'")
                continue
        except Exception as e:
            errors.append(f"Failed to resolve path '{rel_path}': {e}")
            continue

        if not target.exists():
            errors.append(f"Missing inventory file: '{rel_path}'")
            continue

        # Symlinks are strictly prohibited
        if target.is_symlink():
            errors.append(f"Symlink forbidden in archive payload: '{rel_path}'")
            continue

        if not target.is_file():
            errors.append(f"Inventory target is not a regular file: '{rel_path}'")
            continue

        actual_size = target.stat().st_size
        if actual_size != expected_size:
            errors.append(f"Size mismatch for '{rel_path}': got {actual_size}, expected {expected_size}")

        actual_sha = sha256_file(target)
        if actual_sha != expected_sha:
            errors.append(f"SHA-256 mismatch for '{rel_path}': got {actual_sha}, expected {expected_sha}")

    # 5. Check for extraneous unindexed files
    all_disk_files = set()
    for p in archive_root.rglob("*"):
        if p.is_file() or p.is_symlink():
            if p.is_symlink():
                errors.append(f"Symlink forbidden in archive: '{p.relative_to(archive_root)}'")
            rel = str(p.relative_to(archive_root))
            if rel in ("archive_manifest.json", "verify_archive.py", ".DS_Store") or rel.startswith("__pycache__"):
                continue
            all_disk_files.add(rel)

    extraneous = all_disk_files - inv_paths
    if extraneous:
        for ex in sorted(extraneous):
            errors.append(f"Extraneous unindexed file found in archive: '{ex}'")

    # 6. Verify internal frozen-manifest dependencies
    # HeatGuard v3 manifest dependencies
    hg_m_path = archive_root / "frozen_models/p6_heatguard_calibration_v3/manifest.json"
    if hg_m_path.exists():
        try:
            with open(hg_m_path, "r", encoding="utf-8") as f:
                hg_m = json.load(f)
            for fname, exp_hash in hg_m.get("file_hashes", {}).items():
                dep_path = archive_root / "frozen_models/p6_heatguard_calibration_v3" / fname
                if not dep_path.exists():
                    errors.append(f"Missing HeatGuard v3 dependency file: '{fname}'")
                elif sha256_file(dep_path) != exp_hash:
                    errors.append(f"HeatGuard v3 dependency hash mismatch for '{fname}'")
        except Exception as e:
            errors.append(f"Error checking HeatGuard v3 internal dependencies: {e}")

    # Temperature v2 manifest dependencies
    tm_m_path = archive_root / "frozen_models/p6_temperature_v2/artifact_manifest.json"
    if tm_m_path.exists():
        try:
            with open(tm_m_path, "r", encoding="utf-8") as f:
                tm_m = json.load(f)
            for fname, exp_hash in tm_m.get("file_hashes", {}).items():
                dep_path = archive_root / "frozen_models/p6_temperature_v2" / fname
                if not dep_path.exists():
                    errors.append(f"Missing Temperature v2 dependency file: '{fname}'")
                elif sha256_file(dep_path) != exp_hash:
                    errors.append(f"Temperature v2 dependency hash mismatch for '{fname}'")
        except Exception as e:
            errors.append(f"Error checking Temperature v2 internal dependencies: {e}")

    return errors


def main():
    archive_root = Path(__file__).resolve().parent
    errors = verify_archive(archive_root)

    if errors:
        print(f"VERIFICATION FAILED with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    with open(archive_root / "archive_manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    print(f"SUCCESS: All {manifest.get('file_count')} inventory files verified byte-identical against archive manifest.")
    print(f"Decision: {manifest.get('scientific_decision')}")
    print(f"Runner execution commit: {manifest.get('runner_execution_commit')}")
    print(f"Analysis implementation commit: {manifest.get('analysis_implementation_commit')}")


if __name__ == "__main__":
    main()
