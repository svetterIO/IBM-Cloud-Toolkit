#!/usr/bin/env python3
"""
python/get_buckets.py

Enumerates all IBM Cloud Object Storage buckets in the account.

Output files:
  <output_dir>/buckets.json  – JSON array of buckets with instance metadata
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
    require_ibmcloud_cos, require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_buckets.py",
        description="Enumerate IBM Cloud Object Storage buckets.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="buckets.json")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def get_cos_instances(debug: bool) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instances "
              "--service-name cloud-object-storage --all-resource-groups --output json")
    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", "cloud-object-storage",
        "--all-resource-groups",
        "--output", "json",
    )
    if result.returncode != 0 or not result.stdout.strip():
        failure("Failed to retrieve Cloud Object Storage service instances.")
    try:
        data = json.loads(result.stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        failure("Failed to parse COS instances response as JSON.")
    return []


def get_buckets_for_instance(crn: str, debug: bool) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cos buckets --ibm-service-instance-id {crn} --output json")
    result = _ibmcloud("cos", "buckets", "--ibm-service-instance-id", crn, "--output", "json")
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
        buckets = data.get("Buckets") or []
        return buckets if isinstance(buckets, list) else []
    except json.JSONDecodeError:
        return []


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cos()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating IBM Cloud {ORANGE}{BOLD}Object Storage buckets{RESET}...")
    print(" ")

    instances = get_cos_instances(args.v)
    all_buckets: list[dict] = []

    for instance in instances:
        inst_name = instance.get("name", "")
        inst_crn = instance.get("crn", "")
        region_id = instance.get("region_id", "")

        buckets = get_buckets_for_instance(inst_crn, args.v)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Found {len(buckets)} bucket(s) in instance {inst_name}")

        for b in buckets:
            all_buckets.append({
                "bucket_name": b.get("Name"),
                "service_instance_name": inst_name,
                "service_instance_crn": inst_crn,
                "region_id": region_id,
                "CreationDate": b.get("CreationDate"),
            })

    total = len(all_buckets)
    if total == 0:
        print(f"{BOLD}Total buckets found: 0{RESET}")
        print("No Cloud Object Storage buckets found.")
        return

    print(f"{BOLD}Total buckets found: {total}{RESET}")
    print()
    output_path.write_text(json.dumps(all_buckets, indent=2), encoding="utf-8")
    print(f"All buckets saved to: {BOLD}{output_path}{RESET}")


if __name__ == "__main__":
    main()
