#!/usr/bin/env python3
"""
python/get_schematics.py

Enumerates IBM Cloud Schematics workspaces per region.

Output files:
  <output_dir>/schematics_workspaces.json  – JSON array of all workspaces
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, print_console_link,
    require_ibmcloud_login, require_ibmcloud_schematics, warning,
)

DEFAULT_REGIONS = "us-south eu-de ca-tor"


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_schematics.py",
        description="Enumerate IBM Cloud Schematics workspaces.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="schematics_workspaces.json")
    p.add_argument("-r", metavar="REGIONS", default=DEFAULT_REGIONS,
                   help="Space or comma-separated regions "
                        "(default: 'us-south eu-de ca-tor')")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def target_region(region: str) -> bool:
    result = _ibmcloud("target", "-r", region, "-q")
    return result.returncode == 0


def list_workspaces(region: str, debug: bool) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud schematics workspace list --output json")
    result = _ibmcloud("schematics", "workspace", "list", "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
        return data.get("workspaces") or []
    except json.JSONDecodeError:
        return []


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_schematics()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    # Normalise region list (allow comma or space separated)
    regions = [r.strip() for r in args.r.replace(",", " ").split() if r.strip()]

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}Schematics{RESET} workspaces ...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Processing Schematics regions: {' '.join(regions)}")

    all_workspaces: list[dict] = []
    region_counts: dict[str, int] = {}

    for region in regions:
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing region: {region}")
        if not target_region(region):
            warning(f"Failed to target region {region}")
            region_counts[region] = 0
            continue
        ws = list_workspaces(region, args.v)
        region_counts[region] = len(ws)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Region {region}: Found {len(ws)} workspace(s)")
        all_workspaces.extend(ws)

    total = len(all_workspaces)
    print(f"{BOLD}Total workspaces found: {total}{RESET}")
    print()

    if not all_workspaces:
        print("No Schematics workspaces found.")
        return

    print(f"{BOLD}Workspaces by region:{RESET}")
    for region in regions:
        count = region_counts.get(region, 0)
        if count > 0:
            print(f"  {BOLD}{region}:{RESET} {count} workspace(s)")
            region_ws = [w for w in all_workspaces if w.get("location") == region]
            for w in region_ws:
                print(f"    - {w.get('name')}")

    print()
    output_path.write_text(json.dumps(all_workspaces, indent=2), encoding="utf-8")
    print(f"All Schematics workspaces saved to: {BOLD}{output_path}{RESET}")
    print()
    print(f"{YELLOW}{BOLD}Security Note:{RESET} Review this file for secrets in variables "
          "using tools like TruffleHog/detect-secrets or manually.")
    print()
    # Navigate to: IBM Cloud Console > Schematics > Workspaces
    print_console_link("Manage Schematics workspaces", "https://cloud.ibm.com/schematics/workspaces")


if __name__ == "__main__":
    main()
