#!/usr/bin/env python3
"""
python/get_regions.py

Enumerates enabled IBM Cloud regions.

Output files:
  <output_dir>/regions.txt  – one region name per line
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    ensure_output_dir, failure, get_regions,
    print_console_link, require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_regions.py",
        description="Enumerate enabled IBM Cloud regions.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="regions.txt")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating enabled {ORANGE}{BOLD}regions{RESET} on IBM Cloud account...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running command: ibmcloud regions --output json")

    regions = get_regions()
    total = len(regions)

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {total} region(s)")

    print(f"{BOLD}Total regions found: {total}{RESET}")
    print()
    print(f"{BOLD}Regions:{RESET}")
    for r in regions:
        print(f"  - {r}")

    output_path.write_text("\n".join(regions) + "\n", encoding="utf-8")
    print()
    print(f"All regions saved to: {BOLD}{output_path}{RESET}")
    print()
    # There is no region list page in the IBM Cloud UI. Use these instead:
    # - Docs: official list of all available regions and data centres.
    # - Resource list: filter by Location to see which resources exist in each region,
    #   which helps identify resources provisioned in unexpected or disallowed regions.
    print_console_link("IBM Cloud regions reference (docs)", "https://cloud.ibm.com/docs/overview?topic=overview-locations")
    print_console_link("Resource list (filter by Location to audit regions)", "https://cloud.ibm.com/resources")


if __name__ == "__main__":
    main()
