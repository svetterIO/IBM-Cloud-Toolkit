#!/usr/bin/env python3
"""
python/get_mfa.py

Retrieves IBM Cloud account identity settings and checks MFA status.

Output files:
  <output_dir>/account_settings.json  – full identity settings JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, CYAN, ORANGE, RESET, SEPARATOR, YELLOW,
    ensure_output_dir, failure, ibmcloud_access_token,
    ibmcloud_account_id, ibmcloud_get, print_console_link,
    require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_mfa.py",
        description="Check IBM Cloud account MFA requirement status.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="account_settings.json")
    p.add_argument("-v", action="store_true")
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
    print(f"Checking IBM Cloud {ORANGE}{BOLD}MFA Status{RESET}...")
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

    url = f"https://iam.cloud.ibm.com/v1/accounts/{account_id}/settings/identity"
    data = ibmcloud_get(url, token)
    if data is None:
        failure("Failed to retrieve account identity settings.")

    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    mfa_setting = data.get("mfa", "NONE")
    user_mfa_count = len(data.get("user_mfa") or [])

    print(f"{BOLD}MFA Configuration:{RESET}")
    print(f"  Account: {BOLD}{account_id}{RESET}")
    print(f"  MFA Setting: {CYAN}{BOLD}{mfa_setting}{RESET}")
    if mfa_setting != "TOTP4ALL":
        print(f"  {YELLOW}{BOLD}Warning:{RESET} MFA might {BOLD}not be required{RESET} for all users")
    else:
        print(f"  {BOLD}Status:{RESET} MFA is required for all users")

    if user_mfa_count > 0:
        print(f"  User-specific MFA settings: {BOLD}{user_mfa_count}{RESET}")
        print()
        print(f"{YELLOW}{BOLD}Note:{RESET} There are user-specific MFA configurations. "
              "Review the output file for details.")
    else:
        print(f"  User-specific MFA settings: {BOLD}0{RESET}")

    print(" ")
    print(f"Account identity settings saved to: {BOLD}{output_path}{RESET}")

    print()
    # Navigate to: IBM Cloud Console > Manage > Access (IAM) > Settings > Authentication tab
    print_console_link("Account IAM settings (MFA)", "https://cloud.ibm.com/iam/settings?tab=authentication")
    if args.v:
        print()
        print(f"{BOLD}[DEBUG]{RESET} Summary:")
        print(f"{BOLD}[DEBUG]{RESET}   MFA Setting: {mfa_setting}")
        print(f"{BOLD}[DEBUG]{RESET}   User-specific settings: {user_mfa_count}")
        print(f"{BOLD}[DEBUG]{RESET}   MFA Required for all: {'Yes' if mfa_setting == 'TOTP4ALL' else 'No'}")


if __name__ == "__main__":
    main()
