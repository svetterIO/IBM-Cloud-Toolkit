#!/usr/bin/env python3
"""
python/get_users.py

Enumerates account users including last-activity data. Identifies inactive users.

Output files:
  <output_dir>/users.txt          – all users (JSON objects, one per line)
  <output_dir>/inactive_users.txt – users not in ACTIVE state (JSON array)
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
    ensure_output_dir, failure, ibmcloud_access_token,
    ibmcloud_account_id, ibmcloud_get, print_console_link,
    require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_users.py",
        description="Enumerate IBM Cloud account users and flag inactive ones.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="users.txt")
    p.add_argument("-p", metavar="MAX_PARALLEL", type=int, default=10)
    p.add_argument("-v", action="store_true")
    p.add_argument("-d", action="store_true",
                   help="Full debug (show token); requires -v")
    return p.parse_args(argv)


def fetch_all_users(account_id: str, token: str, debug: bool) -> list[dict]:
    """Paginate through all users and return the combined list."""
    all_users: list[dict] = []
    next_url: str = f"https://iam.cloud.ibm.com/v2/accounts/{account_id}/users"
    page = 0
    while next_url:
        page += 1
        if debug:
            print(f"{BOLD}[DEBUG]{RESET} Fetching page {page}")
        data = ibmcloud_get(next_url, token)
        if data is None:
            failure(f"Failed to retrieve users on page {page}.")
        resources = data.get("resources") or []
        all_users.extend(resources)
        next_path = data.get("next_url")
        next_url = f"https://iam.cloud.ibm.com{next_path}" if next_path else ""
    return all_users


def fetch_activity(user: dict, account_id: str, token: str) -> dict:
    """Fetch last_activity for a single user."""
    iam_id = user.get("iam_id", "")
    url = f"https://iam.cloud.ibm.com/v2/accounts/{account_id}/users/{iam_id}?include_activity=true"
    data = ibmcloud_get(url, token) or {}
    last_activity = data.get("activity", "none")
    return {
        "iam_id": iam_id,
        "user_id": user.get("user_id", ""),
        "email": user.get("email", ""),
        "state": user.get("state", ""),
        "last_activity": last_activity,
    }


def main(argv=None):
    args = parse_args(argv)
    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f
    inactive_path = out_dir / f"inactive_{args.f}"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating all {ORANGE}{BOLD}Users{RESET} in IAM...")
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
            print(f"{BOLD}[DEBUG]{RESET} Access token obtained ({token[:20]}...)")
            print(f"{BOLD}[DEBUG]{RESET} Account ID obtained")

    users_raw = fetch_all_users(account_id, token, args.v)
    total = len(users_raw)
    if total == 0:
        failure(f"Failed to retrieve users for account {account_id}.")

    print(f"{BOLD}Total users: {total}{RESET}")
    print(f"Fetching activity data for each user (using {args.p} parallel workers)...")
    print(" ")

    enriched: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.p) as executor:
        futures = {
            executor.submit(fetch_activity, u, account_id, token): i
            for i, u in enumerate(users_raw)
        }
        done = 0
        for future in as_completed(futures):
            enriched.append(future.result())
            done += 1
            if not args.v and done % 10 == 0:
                print(f"\rProcessed: {done}/{total} users...", end="", flush=True)

    if not args.v:
        print(f"\rProcessed: {total}/{total} users... Done!")

    print()
    print("Aggregating results...")

    # Write output
    output_path.write_text(
        "\n".join(json.dumps(u) for u in enriched), encoding="utf-8"
    )

    active = sum(1 for u in enriched if u["state"] == "ACTIVE")
    vpn_only = sum(1 for u in enriched if u["state"] == "VPN_ONLY")
    inactive_users = [u for u in enriched if u["state"] not in ("ACTIVE", "VPN_ONLY")]
    inactive = len(inactive_users)

    print(" ")
    print(f"{BOLD}User Statistics:{RESET}")
    print(f"  Active users: {BOLD}{active}{RESET}")
    print(f"  VPN only users: {BOLD}{vpn_only}{RESET}")
    print(f"  Inactive users: {BOLD}{inactive}{RESET}")
    print(" ")
    print(f"All users saved to: {BOLD}{output_path}{RESET}")

    if inactive > 0:
        inactive_path.write_text(
            json.dumps(inactive_users, indent=2), encoding="utf-8"
        )
        print()
        print(f"{YELLOW}{BOLD}Warning:{RESET} Inactive users found")
        print(f"Inactive users saved to: {BOLD}{inactive_path}{RESET}")
        print()
        print(f"{BOLD}Inactive users:{RESET}")
        for u in inactive_users:
            print(f"  - {u['email']} (State: {u['state']})")
    else:
        print()
        print(f"{BOLD}Good:{RESET} No inactive users found.")
    print()
    print_console_link("Manage users", "https://cloud.ibm.com/iam/users",
                       "IBM Cloud Console > Manage > Access (IAM) > Users"
                       " — Status filter: Pending / Invite expired / Invalid")


if __name__ == "__main__":
    main()
