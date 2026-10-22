#!/usr/bin/env python3
"""
python/get_service_api_keys.py

Enumerates all Service IDs and their associated API keys.
Detects leaked keys (containing an apikey value) and non-rotated keys.

Output files:
  <output_dir>/service_api_keys.json           – all service API keys
  <output_dir>/leaked_service_api_keys.json    – keys with exposed apikey values
  <output_dir>/non_rotated_service_api_keys.json
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, days_since_iso, ensure_output_dir, failure,
    print_console_link, require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_service_api_keys.py",
        description="Enumerate Service IDs and their API keys.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="service_api_keys.json")
    p.add_argument("-d", metavar="ROTATION_DAYS", type=int, default=90)
    p.add_argument("-p", metavar="MAX_PARALLEL", type=int, default=10)
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def fetch_keys_for_service(service_id: str, service_name: str, debug: bool) -> list[dict]:
    if debug:
        print(f"  {BOLD}[DEBUG]{RESET} Fetching keys for Service ID: {service_name} ({service_id})")
    result = _ibmcloud("iam", "service-api-keys", service_id, "-o", "JSON")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        keys = json.loads(result.stdout)
        if not isinstance(keys, list):
            return []
        for k in keys:
            k["service_id"] = service_id
            k["service_name"] = service_name
        return keys
    except json.JSONDecodeError:
        return []


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f
    non_rotated_path = out_dir / f"non_rotated_{args.f}"
    leaked_path = out_dir / "leaked_service_api_keys.json"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating all {ORANGE}{BOLD}Service IDs and their API keys{RESET}...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running command: ibmcloud iam service-ids -o JSON")

    result = _ibmcloud("iam", "service-ids", "-o", "JSON")
    if result.returncode != 0:
        failure("Failed to retrieve Service IDs.")

    try:
        service_ids_raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse Service IDs response as JSON.")

    if not service_ids_raw:
        print("No Service IDs found.")
        return

    total_svc = len(service_ids_raw)
    print(f"{BOLD}Total Service IDs: {total_svc}{RESET}")
    print(f"Fetching API keys for each Service ID (using {args.p} parallel workers)...")
    print(" ")

    id_name_map = {s["id"]: s.get("name", s["id"]) for s in service_ids_raw}

    all_keys: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.p) as executor:
        futures = {
            executor.submit(fetch_keys_for_service, sid, sname, args.v): sid
            for sid, sname in id_name_map.items()
        }
        for future in as_completed(futures):
            all_keys.extend(future.result())

    if not all_keys:
        print(f"{BOLD}Total Service API keys: 0{RESET}")
        print("No Service API keys found.")
        return

    print(f"{BOLD}Total Service API keys: {len(all_keys)}{RESET}")
    output_path.write_text(json.dumps(all_keys, indent=2), encoding="utf-8")
    print(f"All Service API keys saved to: {BOLD}{output_path}{RESET}")

    # Leaked keys
    leaked = [k for k in all_keys if k.get("apikey")]
    if leaked:
        print(f"\n{YELLOW}{BOLD}Warning: Leaked Service API keys found: {len(leaked)}{RESET}")
        leaked_path.write_text(json.dumps(leaked, indent=2), encoding="utf-8")
        print(f"Leaked keys saved to: {BOLD}{leaked_path}{RESET}")
        for k in leaked:
            print(f"  - {k.get('name')} (Service: {k.get('service_name')})")
    else:
        print(f"\n{BOLD}Good:{RESET} No Service API keys contained apikey values.")

    # Non-rotated
    print("\nAnalyzing key rotation...")
    non_rotated = []
    for k in all_keys:
        created_at = k.get("created_at") or ""
        if not created_at:
            continue
        age = days_since_iso(created_at)
        if age is not None and age > args.d:
            non_rotated.append(k)

    if non_rotated:
        print(f"{YELLOW}{BOLD}Service API keys not rotated in {args.d} days: {len(non_rotated)}{RESET}")
        non_rotated_path.write_text(json.dumps(non_rotated, indent=2), encoding="utf-8")
        print(f"Non-rotated keys saved to: {BOLD}{non_rotated_path}{RESET}")
        for k in non_rotated:
            print(f"  - {k.get('name')} (Service: {k.get('service_name')}, Created: {k.get('created_at')})")
    else:
        print(f"{BOLD}Service API keys not rotated in {args.d} days: 0{RESET}")
        print(f"{BOLD}Good:{RESET} All Service API keys have been rotated within the last {args.d} days.")

    print("\nCompleted Service API key extraction.")
    print()
    print_console_link("Manage Service IDs and their API keys", "https://cloud.ibm.com/iam/serviceids")


if __name__ == "__main__":
    main()
