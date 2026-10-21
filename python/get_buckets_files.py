#!/usr/bin/env python3
"""
python/get_buckets_files.py

Lists all files in all IBM Cloud Object Storage buckets.

Output files:
  <output_dir>/buckets_files.txt  – text file with per-bucket file listings
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, ensure_output_dir, failure,
    require_ibmcloud_cos, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_buckets_files.py",
        description="List all files in IBM Cloud Object Storage buckets.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="buckets_files.txt")
    p.add_argument("-m", metavar="MAX_ITEMS", type=int, default=100)
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cos()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}files{RESET} in all IBM Cloud Object Storage buckets...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instances "
              "--service-name cloud-object-storage --all-resource-groups --output json")

    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", "cloud-object-storage",
        "--all-resource-groups",
        "--output", "json",
    )
    if result.returncode != 0:
        failure("Failed to retrieve Cloud Object Storage service instances.")
    try:
        instances = json.loads(result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse COS instances response.")

    total_buckets = 0
    total_files = 0
    lines: list[str] = []

    for instance in instances:
        inst_name = instance.get("name", "")
        inst_crn = instance.get("crn", "")

        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cos buckets-extended "
                  f"--ibm-service-instance-id {inst_crn} --output json")

        buckets_result = _ibmcloud(
            "cos", "buckets-extended",
            "--ibm-service-instance-id", inst_crn,
            "--output", "json",
        )
        if buckets_result.returncode != 0:
            continue
        try:
            buckets_data = json.loads(buckets_result.stdout)
            buckets = buckets_data.get("Buckets") or []
        except json.JSONDecodeError:
            continue

        for bucket in buckets:
            bucket_name = bucket.get("Name", "")
            bucket_region = bucket.get("LocationConstraint", "")
            lines.append(f"## Bucket {inst_name}/{bucket_name} ##")
            total_buckets += 1

            if args.v:
                print(f"{BOLD}[DEBUG]{RESET} Listing objects in bucket {bucket_name}")

            files_result = _ibmcloud(
                "cos", "list-objects-v2",
                "--bucket", bucket_name,
                "--region", bucket_region,
                "--max-items", str(args.m),
                "--output", "json",
            )
            if files_result.returncode != 0:
                warning(f"Could not list files in bucket '{bucket_name}'.")
                lines.append("(No files found)")
                lines.append("")
                continue

            try:
                files_data = json.loads(files_result.stdout)
                contents = files_data.get("Contents") or []
            except json.JSONDecodeError:
                lines.append("(No files found)")
                lines.append("")
                continue

            if not contents:
                lines.append("(No files found)")
            else:
                total_files += len(contents)
                for obj in contents:
                    lines.append(obj.get("Key", ""))
            lines.append("")

    if args.v:
        print()
        print(f"{BOLD}[DEBUG]{RESET} Total buckets: {total_buckets}")
        print(f"{BOLD}[DEBUG]{RESET} Total files: {total_files}")

    print()
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"All bucket file listings saved to: {BOLD}{output_path}{RESET}")


if __name__ == "__main__":
    main()
