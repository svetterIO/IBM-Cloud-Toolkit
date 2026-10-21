#!/usr/bin/env python3
"""
python/download_buckets_files.py

Downloads files from all IBM Cloud Object Storage buckets.
Supports optional flattening of output filenames and overwrite control.

Output:
  Downloaded files placed under <output_dir>/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, CYAN, GREEN, ORANGE, RED, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, failure,
    require_ibmcloud_cos, require_ibmcloud_login, warning,
)


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

    print(" ")
    print(SEPARATOR)
    print(f"Downloading {ORANGE}{BOLD}files{RESET} from all IBM Cloud Object Storage buckets...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Output directory: {out_dir}")
        print(f"{BOLD}[DEBUG]{RESET} Max items per bucket: {args.m}")
        print(f"{BOLD}[DEBUG]{RESET} Overwrite mode: {args.y}")
        print(f"{BOLD}[DEBUG]{RESET} Flatten mode: {args.f}")

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
                if args.f:
                    local_path = out_dir / Path(key).name
                else:
                    local_path = out_dir / key
                    local_path.parent.mkdir(parents=True, exist_ok=True)

                if args.v:
                    print(f"{BOLD}[DEBUG]{RESET} Downloading: {key} -> {local_path}")

                if not args.y and local_path.exists():
                    print(f"    Skipped (exists): {Path(key).name}")
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
                    print(f"    Downloaded: {Path(key).name}")
                    downloaded += 1
                else:
                    print(f"    Failed: {Path(key).name}")
                    failed += 1

        print()

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


if __name__ == "__main__":
    main()
