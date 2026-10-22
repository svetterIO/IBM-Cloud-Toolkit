#!/usr/bin/env python3
"""
python/get_floating_IPs.py

Enumerates all floating IPs in each enabled IBM Cloud region.

Output files:
  <output_dir>/floating_ips.txt  – one IP address per line
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, ensure_output_dir, get_regions,
    print_console_link, require_ibmcloud_is, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_floating_IPs.py",
        description="Enumerate floating IPs across all IBM Cloud regions.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="floating_ips.txt")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def target_region(region: str) -> bool:
    result = _ibmcloud("target", "-r", region, "-q")
    return result.returncode == 0


def get_floating_ips_in_region(region: str, debug: bool) -> list[str]:
    """Return list of floating IP addresses for the currently targeted region."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud is floating-ips -q")
    result = _ibmcloud("is", "floating-ips", "-q")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    ips = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 2:
            ips.append(parts[1])
    return ips


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_is()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}floating IPs{RESET} in all enabled IBM Cloud regions...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving regions")

    regions = get_regions()
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(regions)} region(s) to process")

    all_ips: list[str] = []
    region_counts: dict[str, int] = {}

    for region in regions:
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing region: {region}")
        if not target_region(region):
            warning(f"Failed to target region {region}")
            continue
        ips = get_floating_ips_in_region(region, args.v)
        region_counts[region] = len(ips)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Region {region}: Found {len(ips)} floating IP(s)")
        all_ips.extend(ips)

    total = len(all_ips)
    print()
    print(f"{BOLD}Total floating IPs found: {total}{RESET}")
    print()

    if not all_ips:
        print("No floating IPs found in any region.")
        return

    print(f"{BOLD}Floating IPs by region:{RESET}")
    for region in regions:
        count = region_counts.get(region, 0)
        if count > 0:
            print(f"  {BOLD}{region}:{RESET} {count} IP(s)")

    output_path.write_text("\n".join(all_ips) + "\n", encoding="utf-8")
    print()
    print(f"All floating IPs saved to: {BOLD}{output_path}{RESET}")
    print()
    print_console_link("Manage Floating IPs", "https://cloud.ibm.com/infrastructure/network/floatingIPs",
                       "IBM Cloud Console > VPC Infrastructure > Network > Floating IPs")


if __name__ == "__main__":
    main()
