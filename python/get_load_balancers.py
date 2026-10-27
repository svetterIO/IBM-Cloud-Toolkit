#!/usr/bin/env python3
"""
python/get_load_balancers.py

Enumerates IBM Cloud VPC Load Balancers in every enabled region, including their
listeners (protocol:port). Flags public load balancers and reports their
hostname:port endpoints.

Output files:
  <output_dir>/load_balancers.json         – all VPC load balancers
  <output_dir>/public_load_balancers.json  – public load balancers with endpoints
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, get_regions, print_console_link,
    require_ibmcloud_is, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_load_balancers.py",
        description="Enumerate IBM Cloud VPC Load Balancers.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="load_balancers.json")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    return p.parse_args(argv)


def run_json(args: list[str], debug: bool):
    """Run an ibmcloud command and return parsed JSON, or None on failure."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud {' '.join(args)}")
    result = _ibmcloud(*args)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_listeners(lb_id: str, debug: bool) -> list[dict]:
    data = run_json(["is", "load-balancer-listeners", lb_id, "--output", "json"], debug)
    return data if isinstance(data, list) else []


def public_endpoints(lb: dict, listeners: list[dict]) -> list[str]:
    """Return hostname:port pairs for a load balancer, one per listener."""
    hostname = lb.get("hostname", "")
    ports = sorted({l.get("port") for l in listeners if l.get("port") is not None})
    return [f"{hostname}:{port}" for port in ports] if hostname else []


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_is()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f
    public_path = out_dir / f"public_{args.f}"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}VPC Load Balancers{RESET} in all enabled IBM Cloud regions...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving regions")
    regions = get_regions()
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(regions)} region(s) to process")

    all_lbs: list[dict] = []
    public_lbs: list[dict] = []
    region_counts: dict[str, int] = {}

    for region in regions:
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing region: {region}")
        if _ibmcloud("target", "-r", region, "-q").returncode != 0:
            warning(f"Failed to target region {region}")
            region_counts[region] = 0
            continue

        data = run_json(["is", "load-balancers", "--all-resource-groups", "--output", "json"], args.v)
        if not isinstance(data, list):
            region_counts[region] = 0
            continue

        region_counts[region] = len(data)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Region {region}: Found {len(data)} load balancer(s)")

        for lb in data:
            listeners = get_listeners(lb.get("id", ""), args.v)
            entry = {
                "region": region,
                "name": lb.get("name"),
                "id": lb.get("id"),
                "crn": lb.get("crn"),
                "hostname": lb.get("hostname"),
                "is_public": bool(lb.get("is_public")),
                "operating_status": lb.get("operating_status"),
                "provisioning_status": lb.get("provisioning_status"),
                "public_ips": [ip.get("address") for ip in lb.get("public_ips") or []],
                "private_ips": [ip.get("address") for ip in lb.get("private_ips") or []],
                "vpc": (lb.get("vpc") or {}).get("name"),
                "subnets": [s.get("name") for s in lb.get("subnets") or []],
                "security_groups": [s.get("name") for s in lb.get("security_groups") or []],
                "listeners": [
                    {"protocol": l.get("protocol"), "port": l.get("port"),
                     "default_pool": (l.get("default_pool") or {}).get("name")}
                    for l in listeners
                ],
                "pools": [p.get("name") for p in lb.get("pools") or []],
            }
            all_lbs.append(entry)
            if entry["is_public"]:
                public_lbs.append({**entry, "public_endpoints": public_endpoints(lb, listeners)})

    print(f"{BOLD}Total VPC Load Balancers: {len(all_lbs)}{RESET}")
    if public_lbs:
        print(f"{YELLOW}{BOLD}Public Load Balancers: {len(public_lbs)}{RESET}")
    else:
        print(f"{BOLD}Public Load Balancers: 0{RESET}")
    print()

    if all_lbs:
        print(f"{BOLD}VPC Load Balancers by region:{RESET}")
        for region in regions:
            if region_counts.get(region, 0) > 0:
                print(f"  {BOLD}{region}:{RESET} {region_counts[region]} load balancer(s)")
                for lb in [x for x in all_lbs if x["region"] == region]:
                    kind = "public" if lb["is_public"] else "private"
                    print(f"    - {lb['name']} ({kind}, {lb['hostname']})")
        print()
        output_path.write_text(json.dumps(all_lbs, indent=2), encoding="utf-8")
        print(f"All VPC Load Balancers saved to: {BOLD}{output_path}{RESET}")
        if public_lbs:
            print()
            print(f"{BOLD}Public endpoints:{RESET}")
            for lb in public_lbs:
                print(f"  - {lb['name']}: {', '.join(lb['public_endpoints']) or 'no listeners'}")
            public_path.write_text(json.dumps(public_lbs, indent=2), encoding="utf-8")
            print(f"{YELLOW}{BOLD}Warning:{RESET} Public Load Balancers saved to: {BOLD}{public_path}{RESET}")
    else:
        print("No VPC Load Balancers found.")
    print()
    print_console_link("Manage VPC Load Balancers", "https://cloud.ibm.com/infrastructure/network/loadBalancers",
                       "IBM Cloud Console > VPC Infrastructure > Network > Load balancers")


if __name__ == "__main__":
    main()
