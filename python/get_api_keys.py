#!/usr/bin/env python3
"""
python/get_api_keys.py

Enumerates all IBM Cloud account-level API keys and identifies those
not rotated within a configurable number of days (default: 90).

Each key records whether it is still active (not disabled and not expired).

Output files:
  <output_dir>/api_keys.txt               – JSON array of all API keys
  <output_dir>/non_rotated_api_keys.txt   – JSON array of non-rotated keys
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, days_since_iso, ensure_output_dir, failure,
    iso_is_past, print_console_link, require_ibmcloud_login,
)

KEY_FIELDS = ("id", "name", "created_at", "created_by", "expires_at", "disabled", "leaked", "locked")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_api_keys.py",
        description="Enumerate IBM Cloud API keys and flag non-rotated ones.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output",
                   help="Output folder (default: 'output')")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="api_keys.txt",
                   help="Output file name (default: 'api_keys.txt')")
    p.add_argument("-d", metavar="ROTATION_DAYS", type=int, default=90,
                   help="Rotation threshold in days (default: 90)")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating all {ORANGE}{BOLD}API keys{RESET} ...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running command: ibmcloud iam api-keys -a -o JSON")

    result = _ibmcloud("iam", "api-keys", "-a", "-o", "JSON")
    if result.returncode != 0:
        failure("Failed to retrieve API keys.")

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse API keys response as JSON.")

    api_keys = []
    for entry in raw:
        key = {k: entry.get(k) for k in KEY_FIELDS}
        # A key is active unless it was disabled or its expiration date has passed
        key["active"] = not key["disabled"] and not iso_is_past(key["expires_at"] or "")
        api_keys.append(key)

    if not api_keys:
        print("No API keys found.")
        return

    total = len(api_keys)
    print(f"{BOLD}Total API keys found: {total}{RESET}")
    inactive = sum(1 for k in api_keys if not k["active"])
    print(f"{BOLD}Inactive API keys (disabled or expired): {inactive}{RESET}")
    print(" ")
    output_path.write_text(json.dumps(api_keys, indent=2), encoding="utf-8")
    print(f"Output saved to: {BOLD}{output_path}{RESET}")

    non_rotated = []
    for key in api_keys:
        created_at = key.get("created_at") or ""
        if not created_at:
            continue
        age = days_since_iso(created_at)
        if age is not None and age > args.d:
            non_rotated.append(key)

    if non_rotated:
        print(f"{BOLD}API keys not rotated in the last {args.d} days: {len(non_rotated)}{RESET}")
        nr_path = out_dir / f"non_rotated_{args.f}"
        nr_path.write_text(json.dumps(non_rotated, indent=2), encoding="utf-8")
        print(f"Non-rotated API keys saved to: {BOLD}{nr_path}{RESET}")
    else:
        print(f"{BOLD}API keys not rotated in the last {args.d} days: 0{RESET}")
        print(f"All API keys have been rotated within the last {BOLD}{args.d} days{RESET}.")
    print()
    print_console_link("Manage API keys", "https://cloud.ibm.com/iam/apikeys")


if __name__ == "__main__":
    main()
