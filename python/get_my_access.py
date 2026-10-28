#!/usr/bin/env python3
"""
python/get_my_access.py

Enumerates the access capabilities of the identity currently logged in to the
IBM Cloud CLI (user, service ID or trusted profile):

  - Identity details decoded from the current IAM token
  - Access policies attached directly to the identity
  - Access groups the identity is a member of, and the policies of each group

Output files:
  <output_dir>/my_access.json  – full JSON with identity, direct policies and group policies
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, ensure_output_dir, failure, ibmcloud_account_id,
    ibmcloud_account_name, ibmcloud_get, print_console_link,
    require_ibmcloud_login,
)

IAM_URL = "https://iam.cloud.ibm.com"
PAGE_SIZE = 100


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_my_access.py",
        description="Enumerate the access policies and groups of the current IBM Cloud identity.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="my_access.json")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    return p.parse_args(argv)


def get_token_and_claims() -> tuple[str, dict]:
    """Return (bare bearer token, decoded JWT claims) of the active CLI session."""
    result = _ibmcloud("iam", "oauth-tokens", "--output", "json")
    if result.returncode != 0:
        failure("Failed to retrieve IAM token. Are you logged in?")
    try:
        raw = json.loads(result.stdout).get("iam_token", "")
        token = raw.split(" ", 1)[-1]
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (json.JSONDecodeError, IndexError, ValueError):
        failure("Failed to decode the IAM token.")
    return token, claims


def identity_type(iam_id: str) -> str:
    if iam_id.startswith("iam-ServiceId"):
        return "Service ID"
    if iam_id.startswith("iam-Profile"):
        return "Trusted profile"
    return "User"


def role_names(policy: dict) -> list[str]:
    roles = policy.get("roles")
    if roles is None:
        roles = ((policy.get("control") or {}).get("grant") or {}).get("roles") or []
    return [r.get("display_name") or r.get("role_id", "").split(":")[-1] for r in roles]


def resource_desc(policy: dict) -> str:
    resources = policy.get("resources")
    if resources is None:
        resources = [policy.get("resource") or {}]
    parts = []
    for res in resources:
        attrs = [f"{a.get('name')}={a.get('value')}" for a in res.get("attributes") or []]
        parts.append(", ".join(attrs) if attrs else "all resources")
    return " | ".join(parts) if parts else "all resources"


def print_policies(policies: list[dict], indent: str = "  ") -> None:
    if not policies:
        print(f"{indent}(no policies)")
        return
    for pol in policies:
        print(f"{indent}- Roles: {BOLD}{', '.join(role_names(pol)) or '-'}{RESET}")
        print(f"{indent}  Resource: {resource_desc(pol)}")


def list_groups(account_id: str, iam_id: str, token: str, debug: bool) -> list[dict]:
    groups: list[dict] = []
    offset = 0
    while True:
        url = (f"{IAM_URL}/v2/groups?account_id={account_id}&iam_id={iam_id}"
               f"&limit={PAGE_SIZE}&offset={offset}")
        if debug:
            print(f"{BOLD}[DEBUG]{RESET} GET {url}")
        data = ibmcloud_get(url, token)
        if data is None:
            break
        page = data.get("groups") or []
        groups.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return groups


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}your own access{RESET} (policies and access groups) in IAM...")
    print(" ")

    token, claims = get_token_and_claims()
    account_id = ibmcloud_account_id()
    iam_id = claims.get("iam_id", "")
    if not iam_id:
        failure("Could not determine the IAM ID of the current identity from the token.")

    identity = {
        "type": identity_type(iam_id),
        "iam_id": iam_id,
        "identifier": claims.get("identifier") or claims.get("sub", ""),
        "email": claims.get("email", ""),
        "name": claims.get("name", ""),
        "account_id": account_id,
        "account_name": ibmcloud_account_name(),
    }

    ui_url = f"https://cloud.ibm.com/iam/users/{iam_id}?tab=userdetails"

    print(f"{BOLD}Identity{RESET}")
    for key in ("type", "iam_id", "identifier", "email", "name", "account_name", "account_id"):
        if identity.get(key):
            print(f"  {key:<13}: {identity[key]}")
    print()

    # Direct policies
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} GET {IAM_URL}/v1/policies?account_id={account_id}&iam_id={iam_id}&type=access")
        print(f"{BOLD}[DEBUG]{RESET} UI: {ui_url}")
    pol_data = ibmcloud_get(
        f"{IAM_URL}/v1/policies?account_id={account_id}&iam_id={iam_id}&type=access", token
    )
    direct = (pol_data or {}).get("policies") or []
    print(f"{BOLD}Direct access policies ({len(direct)}){RESET}")
    print_policies(direct)
    print()

    # Access groups and their policies
    groups = list_groups(account_id, iam_id, token, args.v)
    print(f"{BOLD}Access groups ({len(groups)}){RESET}")
    group_results = []
    for grp in groups:
        gid = grp.get("id", "")
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} GET policies for access group {gid}")
            print(f"{BOLD}[DEBUG]{RESET} UI: https://cloud.ibm.com/iam/groups/{gid}?tab=access")
        gdata = ibmcloud_get(
            f"{IAM_URL}/v1/policies?account_id={account_id}&access_group_id={gid}&type=access",
            token,
        )
        gpolicies = (gdata or {}).get("policies") or []
        group_results.append({"id": gid, "name": grp.get("name", ""), "policies": gpolicies})
        print(f"  {BOLD}{grp.get('name', gid)}{RESET} ({gid}) - {len(gpolicies)} policy(ies)")
        print_policies(gpolicies, indent="    ")
    if not groups:
        print("  (not a member of any access group)")
    print()

    result = {
        "identity": identity,
        "direct_policies": direct,
        "access_groups": group_results,
    }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Access details saved to: {BOLD}{output_path}{RESET}")
    print()
    print_console_link("Review your access", ui_url,
                       "IBM Cloud Console > Manage > Access (IAM) > Users > [your user]")


if __name__ == "__main__":
    main()
