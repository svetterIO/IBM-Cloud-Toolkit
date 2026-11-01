#!/usr/bin/env python3
"""
python/get_security_groups.py

Enumerates IBM Cloud VPC and Classic Infrastructure security groups.
Flags VPC security groups with unrestricted inbound rules (0.0.0.0/0).
Fetches the list of resources (targets) attached to each VPC security group.

Output files:
  <output_dir>/security_groups.json              – all VPC security groups (with targets)
  <output_dir>/security_groups_unrestricted.json – VPC SGs with 0.0.0.0/0 inbound (with targets)
  <output_dir>/security_groups_classic.json      – Classic infrastructure SGs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, CYAN, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, get_regions, print_console_link,
    require_ibmcloud_is, require_ibmcloud_login,
    require_ibmcloud_sl, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_security_groups.py",
        description="Enumerate IBM Cloud VPC and Classic security groups.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-v", action="store_true", help="Verbose: show one line per security group")
    p.add_argument("-d", action="store_true", help="Full debug: append ibmcloud command to each line; requires -v")
    return p.parse_args(argv)


def target_region(region: str) -> bool:
    result = _ibmcloud("target", "-r", region, "-q")
    return result.returncode == 0


def get_vpc_sgs(region: str) -> list[dict]:
    result = _ibmcloud("is", "security-groups", "--all-resource-groups", "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        raw = json.loads(result.stdout)
        if not isinstance(raw, list):
            return []
    except json.JSONDecodeError:
        return []
    return [
        {"region": region, "name": sg.get("name"), "id": sg.get("id"), "rules": sg.get("rules") or []}
        for sg in raw
    ]


def get_sg_targets(sg_id: str, region: str, show_cmd: bool) -> list[dict]:
    """Call ibmcloud is security-group-targets <sg_id> and return a list of
    {id, name, resource_type} objects.  Returns [] gracefully on any failure."""
    cmd_str = f"ibmcloud is security-group-targets {sg_id} --output json"
    if show_cmd:
        # printed by caller alongside the main -v line
        pass
    result = _ibmcloud("is", "security-group-targets", sg_id, "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        raw = json.loads(result.stdout)
        if not isinstance(raw, list):
            return []
    except json.JSONDecodeError:
        return []
    return [
        {
            "id": t.get("id"),
            "name": t.get("name"),
            "resource_type": t.get("resource_type"),
        }
        for t in raw
    ]


def is_unrestricted(sg: dict) -> bool:
    for rule in sg.get("rules") or []:
        if (
            rule.get("direction") == "inbound"
            and (rule.get("remote") or {}).get("cidr_block") == "0.0.0.0/0"
        ):
            return True
    return False


def get_classic_sgs(debug: bool) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud sl securitygroup list --output json")
    result = _ibmcloud("sl", "securitygroup", "list", "--output", "json")
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    combined = stdout + stderr
    if any(kw in combined for kw in ("FAILED", "Unauthorized", "not linked to an account in IMS")):
        print(f"{CYAN}Classic Infrastructure security groups: Not available{RESET}")
        print(f"{CYAN}(Account may not have Classic Infrastructure enabled){RESET}")
        return []
    if result.returncode != 0 or not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning("Failed to parse Classic security groups response as JSON.")
        return []


def main(argv=None):
    args = parse_args(argv)

    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    require_ibmcloud_login()
    require_ibmcloud_is()
    require_ibmcloud_sl()
    out_dir = ensure_output_dir(args.o)
    vpc_path = out_dir / "security_groups.json"
    vpc_unres_path = out_dir / "security_groups_unrestricted.json"
    classic_path = out_dir / "security_groups_classic.json"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}VPC Security Groups{RESET} in all enabled IBM Cloud regions...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving regions")

    regions = get_regions()
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(regions)} region(s) to process")

    all_vpc: list[dict] = []
    region_counts: dict[str, int] = {}

    for i, region in enumerate(regions, 1):
        if not args.v:
            print(f"\rScanning region {i}/{len(regions)}: {region:<20}", end="", flush=True)
        if not target_region(region):
            warning(f"Failed to target region {region}")
            region_counts[region] = 0
            continue
        sgs = get_vpc_sgs(region)
        region_counts[region] = len(sgs)
        all_vpc.extend(sgs)

    if not args.v:
        print()  # newline after the final \r progress line

    # ── Fetch targets for every collected SG ─────────────────────────────────
    total_sgs = len(all_vpc)
    for i, sg in enumerate(all_vpc, 1):
        sg_id = sg.get("id", "")
        sg_name = sg.get("name", "")
        sg_region = sg.get("region", "")

        if not args.v:
            print(f"\rFetching targets {i}/{total_sgs}: {sg_name:<30}", end="", flush=True)

        targets = get_sg_targets(sg_id, sg_region, args.d)
        sg["targets"] = targets

        if args.v:
            line = (
                f"{BOLD}[DEBUG]{RESET} SG: {sg_name} — region: {sg_region}"
                f" — {len(targets)} target(s)"
            )
            if args.d:
                line += f" — {CYAN}ibmcloud is security-group-targets {sg_id} --output json{RESET}"
            print(line)

    if not args.v and total_sgs > 0:
        print()  # newline after the final \r targets progress line

    # Re-compute unrestricted from the now-enriched list
    unrestricted = [sg for sg in all_vpc if is_unrestricted(sg)]

    total_vpc = len(all_vpc)
    total_unres = len(unrestricted)

    print()
    print(f"{BOLD}Total VPC Security Groups: {total_vpc}{RESET}")
    if total_unres > 0:
        print(f"{YELLOW}{BOLD}Security Groups with unrestricted inbound rules (0.0.0.0/0): {total_unres}{RESET}")
    else:
        print(f"{BOLD}Security Groups with unrestricted inbound rules: 0{RESET}")

    print()
    if all_vpc:
        print(f"{BOLD}VPC Security Groups by region:{RESET}")
        for region in regions:
            count = region_counts.get(region, 0)
            if count > 0:
                print(f"  {BOLD}{region}:{RESET} {count} security group(s)")
                for sg in [s for s in all_vpc if s.get("region") == region]:
                    target_count = len(sg.get("targets") or [])
                    print(f"    - {sg['name']} ({target_count} target(s))")
        print()
        vpc_path.write_text(json.dumps(all_vpc, indent=2), encoding="utf-8")
        print(f"All VPC Security Groups saved to: {BOLD}{vpc_path}{RESET}")
        if unrestricted:
            vpc_unres_path.write_text(json.dumps(unrestricted, indent=2), encoding="utf-8")
            print(f"{YELLOW}{BOLD}Warning:{RESET} VPC Security Groups with unrestricted inbound rules "
                  f"saved to: {BOLD}{vpc_unres_path}{RESET}")
    else:
        print("No VPC Security Groups found.")

    print()
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}Classic Infrastructure Security Groups{RESET}...")
    print()

    classic = get_classic_sgs(args.v)
    if classic:
        classic_path.write_text(json.dumps(classic, indent=2), encoding="utf-8")
        print(f"{BOLD}Total Classic Security Groups: {len(classic)}{RESET}")
        print()
        print(f"{BOLD}Classic Security Groups:{RESET}")
        for sg in classic:
            print(f"  - {sg.get('name')}")
        print()
        print(f"All Classic Infrastructure Security Groups saved to: {BOLD}{classic_path}{RESET}")
    else:
        print(f"{BOLD}Total Classic Security Groups: 0{RESET}")
        print("No Classic Infrastructure Security Groups found.")
    print()
    print_console_link("Manage VPC Security Groups", "https://cloud.ibm.com/infrastructure/network/securityGroups",
                       "IBM Cloud Console > VPC Infrastructure > Network > Security groups")
    print_console_link("Manage VPCs", "https://cloud.ibm.com/infrastructure/network/vpcs",
                       "IBM Cloud Console > VPC Infrastructure > Network > VPCs"
                       " (lists VPCs with attached security groups)")
    # Classic Infrastructure security groups are managed via the SL CLI;
    # there is no dedicated Classic SG page in the IBM Cloud console.


if __name__ == "__main__":
    main()
