#!/usr/bin/env python3
"""
python/get_VSIs.py

Enumerates IBM Cloud Virtual Server Instances (VSIs) in each region.
Flags VSIs with the metadata service enabled.

Output files:
  <output_dir>/VSIs.json                 – all VSIs
  <output_dir>/metadata_enabled_VSIs.json – VSIs with metadata service enabled
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, get_regions,
    print_console_link, require_ibmcloud_is, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_VSIs.py",
        description="Enumerate IBM Cloud VSIs in each region.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="VSIs.json")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def target_region(region: str) -> bool:
    result = _ibmcloud("target", "-r", region, "-q")
    return result.returncode == 0


def get_vsis_in_region(region: str, debug: bool) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud is instances --output json")
    result = _ibmcloud("is", "instances", "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        raw = json.loads(result.stdout)
        if not isinstance(raw, list):
            return []
    except json.JSONDecodeError:
        return []

    vsis = []
    for v in raw:
        floating_ips = []
        for ni in v.get("network_interfaces") or []:
            for fip in ni.get("floating_ips") or []:
                addr = fip.get("address")
                if addr:
                    floating_ips.append(addr)
        vsis.append({
            "id": v.get("id"),
            "name": v.get("name"),
            "region": region,
            "image": (v.get("image") or {}).get("name"),
            "metadata_enabled": (v.get("metadata_service") or {}).get("enabled", False),
            "floating_IPs": ", ".join(floating_ips),
        })
    return vsis


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_is()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f
    metadata_path = out_dir / f"metadata_enabled_{args.f}"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}VSIs{RESET} in all enabled IBM Cloud regions...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving regions")

    regions = get_regions()
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(regions)} region(s) to process")

    all_vsis: list[dict] = []
    region_counts: dict[str, int] = {}

    for region in regions:
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing region: {region}")
        if not target_region(region):
            warning(f"Failed to target region {region}")
            region_counts[region] = 0
            continue
        vsis = get_vsis_in_region(region, args.v)
        region_counts[region] = len(vsis)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Region {region}: Found {len(vsis)} VSI(s)")
        all_vsis.extend(vsis)

    total = len(all_vsis)
    metadata_enabled = [v for v in all_vsis if v.get("metadata_enabled")]
    meta_count = len(metadata_enabled)

    print()
    print(f"{BOLD}Total VSIs: {total}{RESET}")
    if meta_count > 0:
        print(f"{YELLOW}{BOLD}VSIs with metadata enabled: {meta_count}{RESET}")
    else:
        print(f"{BOLD}VSIs with metadata enabled: 0{RESET}")

    print()
    if not all_vsis:
        print("No VSIs found.")
        return

    print(f"{BOLD}VSIs by region:{RESET}")
    for region in regions:
        count = region_counts.get(region, 0)
        if count > 0:
            print(f"  {BOLD}{region}:{RESET} {count} VSI(s)")
            region_vsis = [v for v in all_vsis if v.get("region") == region]
            for v in region_vsis:
                if v.get("metadata_enabled"):
                    print(f"    - {v['name']} {YELLOW}(metadata enabled){RESET}")
                else:
                    print(f"    - {v['name']}")

    print()
    output_path.write_text(json.dumps(all_vsis, indent=2), encoding="utf-8")
    print(f"All VSIs saved to: {BOLD}{output_path}{RESET}")

    if metadata_enabled:
        metadata_path.write_text(json.dumps(metadata_enabled, indent=2), encoding="utf-8")
        print()
        print(f"{YELLOW}{BOLD}Warning: VSIs with metadata enabled{RESET}")
        print(f"VSIs with metadata enabled saved to: {BOLD}{metadata_path}{RESET}")
        print()
        print(f"{BOLD}VSIs with metadata enabled:{RESET}")
        for v in metadata_enabled:
            print(f"  - {v['name']} (Region: {v['region']})")
    else:
        print()
        print(f"{BOLD}Good:{RESET} No VSIs with metadata enabled found.")
    print()
    print_console_link("Manage Virtual Server Instances (VPC)", "https://cloud.ibm.com/vpc/compute/vs")


if __name__ == "__main__":
    main()
