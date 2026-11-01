#!/usr/bin/env python3
"""
python/get_user_policies.py

Identifies users with access policies assigned directly (not via groups).

Output files:
  <output_dir>/user_policies.txt  – NDJSON (one policy record per line)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, BRIGHT_RED, CYAN, ORANGE, RESET, SEPARATOR,
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
    p.add_argument("-v", action="store_true", help="Verbose: show ibmcloud command per user")
    p.add_argument("-d", action="store_true", help="Full debug: also show the console URL; requires -v")
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
    print(f"Enumerating Users with {ORANGE}{BOLD}direct access policies{RESET} in IAM...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving access token and account ID")

    token = ibmcloud_access_token()
    account_id = ibmcloud_account_id()

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} GET https://iam.cloud.ibm.com/v2/accounts/{account_id}/users")

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

    records: list[dict] = []

    for user in users:
        iam_id = user.get("iam_id", "")
        user_id = user.get("user_id", "")
        email  = user.get("email", user_id)
        url = f"https://iam.cloud.ibm.com/v1/policies?account_id={account_id}&iam_id={iam_id}"
        if args.v:
            line = f"{BOLD}[DEBUG]{RESET} User: {email} - {CYAN}ibmcloud iam user-policies {user_id}{RESET}"
            if args.d:
                line += f" - https://cloud.ibm.com/iam/users/{iam_id}?tab=iam"
            print(line)
        policies_data = ibmcloud_get(url, token)
        if policies_data is None:
            continue
        user_policies = policies_data.get("policies") or []
        if user_policies:
            found_suffix = f": {BRIGHT_RED}{BOLD}FOUND direct access policy{RESET}"
            line = f"{BOLD}[DEBUG]{RESET} User: {email}{found_suffix} - {CYAN}ibmcloud iam user-policies {user_id}{RESET}"
            if args.d:
                line += f" - https://cloud.ibm.com/iam/users/{iam_id}?tab=iam"
            print(line)
        for policy in user_policies:
            roles = ", ".join(
                r.get("display_name") or r.get("role_id", "")
                for r in (policy.get("roles") or [])
            )
            resources = "; ".join(
                ", ".join(
                    f"{a.get('name')}={a.get('value')}"
                    for a in (res.get("attributes") or [])
                )
                for res in (policy.get("resources") or [])
            )
            records.append({
                "user_id":   user_id,
                "iam_id":    iam_id,
                "policy_id": policy.get("id", ""),
                "type":      policy.get("type", ""),
                "state":     policy.get("state", ""),
                "roles":     roles,
                "resources": resources,
            })

    if records:
        output_path.write_text(
            "\n".join(json.dumps(r) for r in records), encoding="utf-8"
        )

        unique_users = len({r["user_id"] for r in records})
        print(f"{BOLD}Users with Direct Policies:{RESET} {unique_users}")
        print(f"{BOLD}Total Direct Policies:     {RESET} {len(records)}")

        # Notable assignments: policies whose role or resource string contains
        # any of the high-interest keywords below.
        _NOTABLE_KEYWORDS = [
            "administrator",
            "manager",
            "billing",
            "enterprise",
            "support",
            "console",
            "iam identity",
        ]
        notable: list[str] = []
        for r in records:
            combined = (r["roles"] + " " + r["resources"]).lower()
            if any(kw in combined for kw in _NOTABLE_KEYWORDS):
                # Build a readable label: "Roles on serviceName"
                # Extract the serviceName attribute from the resources string when present.
                service_part = ""
                for seg in r["resources"].split(";"):
                    for attr in seg.split(","):
                        attr = attr.strip()
                        if attr.startswith("serviceName="):
                            service_part = attr.split("=", 1)[1].strip()
                            break
                    if service_part:
                        break
                label = r["roles"]
                if service_part:
                    label += f" on {service_part}"
                notable.append(label)

        if notable:
            print()
            print(f"{BOLD}Notable Direct Assignments:{RESET}")
            for item in notable:
                print(f"  - {item}")

        print(f"\nUsers with direct access policies saved to: {BOLD}{output_path}{RESET}")
    else:
        print("No users with direct access policies found.")
    print()
    print_console_link("Review user access policies", "https://cloud.ibm.com/iam/users",
                       "IBM Cloud Console > Manage > Access (IAM) > Users"
                       " > [select user] > Access > Access policies")


if __name__ == "__main__":
    main()
