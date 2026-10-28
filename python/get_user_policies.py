#!/usr/bin/env python3
"""
python/get_user_policies.py

Identifies users with access policies assigned directly (not via groups).

Output files:
  <output_dir>/user_policies.txt  – text file with user IDs and their policies
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
        prog="get_user_policies.py",
        description="Identify users with direct IAM access policies.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="user_policies.txt")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating Users with {ORANGE}{BOLD}direct access policies{RESET} in IAM...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving access token and account ID")

    token = ibmcloud_access_token()
    account_id = ibmcloud_account_id()

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} GET https://iam.cloud.ibm.com/v2/accounts/<id>/users")

    users_data = ibmcloud_get(
        f"https://iam.cloud.ibm.com/v2/accounts/{account_id}/users", token
    )
    if users_data is None:
        failure(f"Failed to retrieve users for account {account_id}.")

    users = users_data.get("resources") or []
    if not users:
        failure(f"Failed to retrieve users for account {account_id}.")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(users)} user(s), checking policies...")

    found = False
    lines: list[str] = []

    for user in users:
        iam_id = user.get("iam_id", "")
        user_id = user.get("user_id", "")
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} GET policies for {user_id}")
        policies_data = ibmcloud_get(
            f"https://iam.cloud.ibm.com/v1/policies?account_id={account_id}&iam_id={iam_id}",
            token,
        )
        if policies_data is None:
            continue
        policies = policies_data.get("policies") or []
        if policies:
            found = True
            lines.append(f"User ID: {user_id}")
            lines.append(json.dumps(policies_data, indent=2))
            lines.append("")

    if found:
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"Users with direct access policies saved to: {BOLD}{output_path}{RESET}")
    else:
        print("No users with direct access policies found.")
    print()
    print_console_link("Review user access policies", "https://cloud.ibm.com/iam/users",
                       "IBM Cloud Console > Manage > Access (IAM) > Users"
                       " > [select user] > Access > Access policies")


if __name__ == "__main__":
    main()
