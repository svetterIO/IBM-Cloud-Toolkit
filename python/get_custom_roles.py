#!/usr/bin/env python3
"""
python/get_custom_roles.py

Enumerates all custom IAM roles in the IBM Cloud account.

Output files:
  <output_dir>/custom_roles.txt  – JSON array of custom roles
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    ensure_output_dir, failure, ibmcloud_access_token,
    ibmcloud_account_id, ibmcloud_get, print_console_link,
    require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_custom_roles.py",
        description="Enumerate custom IAM roles in the IBM Cloud account.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="custom_roles.txt")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    p.add_argument("-d", action="store_true",
                   help="Full debug (show token); requires -v")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating all {ORANGE}{BOLD}custom IAM roles{RESET} ...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving access token")

    token = ibmcloud_access_token()
    account_id = ibmcloud_account_id()

    if args.v:
        if args.d:
            print(f"{BOLD}[DEBUG]{RESET} Access token: {token}")
            print(f"{BOLD}[DEBUG]{RESET} Account ID: {account_id}")
        else:
            print(f"{BOLD}[DEBUG]{RESET} Access token obtained ({token[:20]}...) [use -d for full token]")
            print(f"{BOLD}[DEBUG]{RESET} Account ID obtained")
        print(f"{BOLD}[DEBUG]{RESET} Running: GET https://iam.cloud.ibm.com/v2/roles?account_id=<redacted>")

    url = f"https://iam.cloud.ibm.com/v2/roles?account_id={account_id}"
    data = ibmcloud_get(url, token)
    if data is None:
        failure("Failed to retrieve custom roles.")

    custom_roles = data.get("custom_roles") or []

    if not custom_roles:
        print(f"{BOLD}Total custom roles found: 0{RESET}")
        print("No custom roles found.")
        return

    total = len(custom_roles)
    output_path.write_text(json.dumps(custom_roles, indent=2), encoding="utf-8")
    print(f"{BOLD}Total custom roles found: {total}{RESET}")
    print(f"Output with all custom roles saved to: {BOLD}{output_path}{RESET}")
    print(" ")
    print("Review custom roles for excessive privileges.")
    print()
    print_console_link("Manage custom IAM roles", "https://cloud.ibm.com/iam/roles")


if __name__ == "__main__":
    main()
