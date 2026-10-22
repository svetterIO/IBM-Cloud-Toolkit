#!/usr/bin/env python3
"""
python/download_buckets_files.py

Downloads files from all IBM Cloud Object Storage buckets.
Supports optional flattening of output filenames and overwrite control.

On Windows (and as a general best-practice) object keys are sanitized before
being used as local file paths:
  - URL-encoded characters (%XX) are decoded to their literal form first.
  - Characters that are illegal on Windows ( : * ? " < > | % \\ ) and ASCII
    control characters are replaced with underscores.
  - Each path component is truncated to 200 characters so that the total path
    stays well within Windows MAX_PATH (260).

A manifest file (_path_manifest.json) is written next to the download folder.
Each entry records:
  - original_key   : the raw COS object key
  - local_path     : the sanitized path on disk (relative to the download folder)
  - browser_url    : a pre-signed-style HTTPS URL to open the object in a browser
                     (uses the public IBM COS endpoint pattern; works for public
                      objects / signed sessions)

Output:
  <output_dir>/               Downloaded files (sanitized paths)
  <output_dir>_path_manifest.json   Key → local path + browser URL mapping
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import urllib.parse
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, CYAN, GREEN, ORANGE, RED, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, failure,
    require_ibmcloud_cos, require_ibmcloud_login, warning,
)

# ── Path sanitization ─────────────────────────────────────────────────────────

# Characters forbidden in Windows file/directory names
_WIN_FORBIDDEN = re.compile(r'[:\*\?"<>\|%\\]')
# ASCII control characters (0-31)
_CTRL = re.compile(r'[\x00-\x1f]')
# Max length for a single path component (well under the 255 FS limit and
# far enough from MAX_PATH that nesting many components still works)
_MAX_COMPONENT = 200


def sanitize_key(key: str) -> str:
    """Return a local-filesystem-safe relative path for a COS object key.

    Steps:
      1. URL-decode %XX sequences so the real characters are visible.
      2. Split on '/'.
      3. For each component replace forbidden/control chars with '_'.
      4. Truncate components that exceed _MAX_COMPONENT characters.
      5. Rejoin with the OS path separator.
    """
    decoded = urllib.parse.unquote(key)
    # Use PurePosixPath to split cleanly on '/' regardless of OS
    parts = PurePosixPath(decoded).parts
    safe_parts: list[str] = []
    for part in parts:
        # Replace forbidden characters
        part = _WIN_FORBIDDEN.sub("_", part)
        # Replace control characters
        part = _CTRL.sub("_", part)
        # Strip leading/trailing dots and spaces (Windows quirk)
        part = part.strip(". ")
        if not part:
            part = "_"
        # Truncate
        if len(part) > _MAX_COMPONENT:
            # Keep the extension if present
            stem, _, ext = part[:_MAX_COMPONENT].rpartition(".")
            if ext and len(ext) <= 10:
                part = stem[:_MAX_COMPONENT - len(ext) - 1] + "." + ext
            else:
                part = part[:_MAX_COMPONENT]
        safe_parts.append(part)
    return str(Path(*safe_parts)) if safe_parts else "_"


def cos_browser_url(endpoint: str, bucket: str, key: str) -> str:
    """Build an HTTPS URL to open the object in a browser / download directly."""
    encoded_key = urllib.parse.quote(key, safe="")
    return f"https://{endpoint}/{bucket}/{encoded_key}"


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="download_buckets_files.py",
        description="Download files from IBM Cloud Object Storage buckets.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output/bucket_files")
    p.add_argument("-v", action="store_true")
    p.add_argument("-m", metavar="MAX_ITEMS", type=int, default=10)
    p.add_argument("-y", action="store_true", help="Overwrite existing files")
    p.add_argument("-f", action="store_true", help="Flatten output (filename only)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cos()
    out_dir = ensure_output_dir(args.o)

    # Manifest lives beside the download folder, not inside it
    manifest_path = out_dir.parent / (out_dir.name + "_path_manifest.json")
    manifest: list[dict] = []

    on_windows = platform.system() == "Windows"

    print(" ")
    print(SEPARATOR)
    print(f"Downloading {ORANGE}{BOLD}files{RESET} from all IBM Cloud Object Storage buckets...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Output directory: {out_dir}")
        print(f"{BOLD}[DEBUG]{RESET} Max items per bucket: {args.m}")
        print(f"{BOLD}[DEBUG]{RESET} Overwrite mode: {args.y}")
        print(f"{BOLD}[DEBUG]{RESET} Flatten mode: {args.f}")
        if on_windows:
            print(f"{BOLD}[DEBUG]{RESET} Windows mode: path sanitization enabled")

    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", "cloud-object-storage",
        "--output", "json",
    )
    if result.returncode != 0:
        failure("Failed to retrieve Cloud Object Storage service instances.")
    try:
        instances = json.loads(result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse COS instances response.")

    if not instances:
        print("No Cloud Object Storage service instances found.")
        return

    total_instances = len(instances)
    total_buckets = 0
    total_files = 0
    downloaded = 0
    skipped = 0
    failed = 0

    print(f"{BOLD}Cloud Object Storage instances: {total_instances}{RESET}")
    print()

    for instance in instances:
        inst_name = instance.get("name", "")
        inst_crn = instance.get("crn", "")

        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing instance: {inst_name}")

        buckets_result = _ibmcloud(
            "cos", "buckets-extended",
            "--ibm-service-instance-id", inst_crn,
            "--output", "json",
        )
        if buckets_result.returncode != 0:
            warning(f"Failed to retrieve buckets for instance: {inst_name}")
            continue
        try:
            buckets_data = json.loads(buckets_result.stdout)
            buckets = buckets_data.get("Buckets") or []
        except json.JSONDecodeError:
            warning(f"Invalid JSON for instance: {inst_name}")
            continue

        total_buckets += len(buckets)
        print(f"Processing instance: {BOLD}{inst_name}{RESET} ({len(buckets)} bucket(s))")

        for bucket in buckets:
            bname = bucket.get("Name", "")
            bregion = bucket.get("LocationConstraint", "")
            # Derive a COS public endpoint for browser URLs
            cos_endpoint = f"s3.{bregion}.cloud-object-storage.appdomain.cloud"

            print(f"  Bucket: {BOLD}{bname}{RESET} (Region: {bregion})")

            files_result = _ibmcloud(
                "cos", "list-objects-v2",
                "--max-items", str(args.m),
                "--bucket", bname,
                "--region", bregion,
                "--output", "json",
            )
            if files_result.returncode != 0:
                warning(f"Failed to list objects in bucket: {bname}")
                continue
            try:
                files_data = json.loads(files_result.stdout)
                contents = files_data.get("Contents") or []
            except json.JSONDecodeError:
                print("    (No files found)")
                continue

            if not contents:
                print("    (No files found)")
                continue

            is_truncated = files_data.get("IsTruncated", False)
            total_files += len(contents)
            print(f"    Found {len(contents)} file(s)")
            if is_truncated:
                print(f"    {YELLOW}Note: Bucket contains more files than max-items limit{RESET}")

            for obj in contents:
                key = obj.get("Key", "")

                # Build local path ─────────────────────────────────────────
                if args.f:
                    # Flatten: just the filename, sanitized
                    raw_name = PurePosixPath(key).name or key
                    safe_rel = sanitize_key(raw_name)
                    local_path = out_dir / safe_rel
                else:
                    safe_rel = sanitize_key(key)
                    local_path = out_dir / safe_rel
                    try:
                        local_path.parent.mkdir(parents=True, exist_ok=True)
                    except OSError as exc:
                        warning(f"Cannot create directory for '{key}': {exc}")
                        failed += 1
                        continue

                browser_url = cos_browser_url(cos_endpoint, bname, key)

                # Add to manifest (always, even if skipped/failed)
                manifest.append({
                    "instance": inst_name,
                    "bucket": bname,
                    "region": bregion,
                    "original_key": key,
                    "local_path": str(local_path),
                    "browser_url": browser_url,
                })

                if args.v:
                    sanitized_note = (
                        f" (sanitized from: {key})"
                        if str(safe_rel) != key else ""
                    )
                    print(f"{BOLD}[DEBUG]{RESET} Downloading: {key} -> {local_path}{sanitized_note}")

                if not args.y and local_path.exists():
                    print(f"    Skipped (exists): {local_path.name}")
                    skipped += 1
                    continue

                dl_result = _ibmcloud(
                    "cos", "download",
                    "--bucket", bname,
                    "--region", bregion,
                    "--key", key,
                    str(local_path),
                )
                if dl_result.returncode == 0:
                    print(f"    Downloaded: {local_path.name}")
                    downloaded += 1
                else:
                    print(f"    Failed: {local_path.name}")
                    failed += 1

        print()

    # Write manifest
    if manifest:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    print(SEPARATOR)
    print(f"{BOLD}Download Summary:{RESET}")
    print(f"  COS Instances: {BOLD}{total_instances}{RESET}")
    print(f"  Buckets processed: {BOLD}{total_buckets}{RESET}")
    print(f"  Files found: {BOLD}{total_files}{RESET}")
    print(f"  Files downloaded: {BOLD}{GREEN}{downloaded}{RESET}")
    print(f"  Files skipped: {BOLD}{CYAN}{skipped}{RESET}")
    if failed > 0:
        print(f"  Files failed: {BOLD}{RED}{failed}{RESET}")
    print()
    print(f"Files saved to: {BOLD}{out_dir}{RESET}")
    if manifest:
        print(f"Path manifest:  {BOLD}{manifest_path}{RESET}")
        print(f"  (maps original COS keys → local paths + browser URLs)")


if __name__ == "__main__":
    main()
