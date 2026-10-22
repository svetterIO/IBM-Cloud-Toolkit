#!/usr/bin/env python3
"""
python/get_buckets_files.py

Lists all files in all IBM Cloud Object Storage buckets.
Bucket listings are fetched in parallel (default: 10 workers) to speed up
accounts with many buckets.

Output files:
  <output_dir>/buckets_files.txt  – text file with per-bucket file listings
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    p.add_argument("-p", metavar="MAX_PARALLEL", type=int, default=10,
                   help="Parallel workers for bucket listing (default: 10)")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def _list_bucket(inst_name: str, bucket_name: str, bucket_region: str,
                 max_items: int, debug: bool) -> dict:
    """Fetch the object listing for one bucket and return a result dict."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Listing objects in bucket {bucket_name}")

    result = _ibmcloud(
        "cos", "list-objects-v2",
        "--bucket", bucket_name,
        "--region", bucket_region,
        "--max-items", str(max_items),
        "--output", "json",
    )

    if result.returncode != 0:
        warning(f"Could not list files in bucket '{bucket_name}'.")
        return {
            "inst_name": inst_name,
            "bucket_name": bucket_name,
            "keys": None,          # signals failure
            "truncated": False,
            "count": 0,
        }

    try:
        files_data = json.loads(result.stdout)
        contents = files_data.get("Contents") or []
        truncated = files_data.get("IsTruncated", False)
    except json.JSONDecodeError:
        contents = []
        truncated = False

    return {
        "inst_name": inst_name,
        "bucket_name": bucket_name,
        "keys": [obj.get("Key", "") for obj in contents],
        "truncated": truncated,
        "count": len(contents),
    }


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cos()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}files{RESET} in all IBM Cloud Object Storage buckets"
          f" (using {args.p} parallel workers)...")
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

    # ── Collect all (inst_name, bucket_name, bucket_region) tuples ────────────
    all_buckets: list[tuple[str, str, str]] = []
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
            all_buckets.append((
                inst_name,
                bucket.get("Name", ""),
                bucket.get("LocationConstraint", ""),
            ))

    total_buckets = len(all_buckets)
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {total_buckets} bucket(s) across all instances")

    print(f"{BOLD}Total buckets found: {total_buckets}{RESET}")
    if total_buckets == 0:
        print("No buckets found.")
        output_path.write_text("", encoding="utf-8")
        return

    print(f"Listing objects in {total_buckets} bucket(s)"
          f" with {args.p} parallel worker(s)...")

    # ── Parallel bucket listing ───────────────────────────────────────────────
    # Preserve insertion order for deterministic output: use a dict keyed by
    # submission order, filled as futures complete.
    order: list[int] = list(range(total_buckets))
    results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=args.p) as executor:
        future_to_idx = {
            executor.submit(
                _list_bucket,
                inst, bname, bregion, args.m, args.v
            ): idx
            for idx, (inst, bname, bregion) in enumerate(all_buckets)
        }
        done = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
            done += 1
            if not args.v and done % 5 == 0:
                print(f"\rProcessed: {done}/{total_buckets} buckets...",
                      end="", flush=True)

    if not args.v:
        print(f"\rProcessed: {total_buckets}/{total_buckets} buckets... Done!")

    # ── Assemble output in original bucket order ──────────────────────────────
    lines: list[str] = []
    total_files = 0

    for idx in order:
        r = results[idx]
        lines.append(f"## Bucket {r['inst_name']}/{r['bucket_name']} ##")
        if r["keys"] is None:
            lines.append("(Error listing bucket)")
        elif not r["keys"]:
            lines.append("(No files found)")
        else:
            total_files += r["count"]
            if r["truncated"]:
                lines.append(f"(Showing first {args.m} of more objects)")
            lines.extend(r["keys"])
        lines.append("")

    if args.v:
        print()
        print(f"{BOLD}[DEBUG]{RESET} Total buckets: {total_buckets}")
        print(f"{BOLD}[DEBUG]{RESET} Total files listed: {total_files}")

    print()
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"All bucket file listings saved to: {BOLD}{output_path}{RESET}")


if __name__ == "__main__":
    main()
