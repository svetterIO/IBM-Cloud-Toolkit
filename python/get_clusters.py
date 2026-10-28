#!/usr/bin/env python3
"""
python/get_clusters.py

Enumerates IBM Cloud Kubernetes/OpenShift clusters.
Flags clusters with public endpoints enabled.

Output files:
  <output_dir>/clusters.json                 – all clusters
  <output_dir>/public_endpoint_clusters.json – clusters with public endpoints
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    ensure_output_dir, failure, ibmcloud_access_token,
    ibmcloud_get, print_console_link, require_ibmcloud_login,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_clusters.py",
        description="Enumerate IBM Cloud Kubernetes/OpenShift clusters.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="clusters.json")
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
    public_path = out_dir / f"public_endpoint_{args.f}"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating IBM Cloud {ORANGE}{BOLD}Clusters{RESET}...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving access token")

    token = ibmcloud_access_token()

    if args.v:
        if args.d:
            print(f"{BOLD}[DEBUG]{RESET} Access token: {token}")
        else:
            print(f"{BOLD}[DEBUG]{RESET} Access token obtained ({token[:20]}...)")
        print(f"{BOLD}[DEBUG]{RESET} GET https://containers.cloud.ibm.com/global/v2/vpc/getClusters")

    url = "https://containers.cloud.ibm.com/global/v2/vpc/getClusters"
    clusters_raw = ibmcloud_get(url, token)

    if not clusters_raw:
        print("No clusters found.")
        return

    clusters = [
        {
            "name": c.get("name"),
            "region": c.get("region"),
            "masterKubeVersion": c.get("masterKubeVersion"),
            "type": c.get("type"),
            "publicServiceEndpointEnabled": (
                c.get("serviceEndpoints", {}).get("publicServiceEndpointEnabled")
            ),
            "publicServiceEndpointURL": (
                c.get("serviceEndpoints", {}).get("publicServiceEndpointURL")
            ),
            "ingress": c.get("ingress", {}).get("hostname"),
        }
        for c in (clusters_raw if isinstance(clusters_raw, list) else [])
    ]

    total = len(clusters)
    output_path.write_text(json.dumps(clusters, indent=2), encoding="utf-8")
    print(f"{BOLD}Total clusters found: {total}{RESET}")
    print(f"All clusters saved to: {BOLD}{output_path}{RESET}")

    public = [c for c in clusters if c.get("publicServiceEndpointEnabled")]
    if public:
        public_path.write_text(json.dumps(public, indent=2), encoding="utf-8")
        print(f"{BOLD}Clusters with public endpoint: {len(public)}{RESET}")
        print(f"Clusters with public endpoint saved to: {BOLD}{public_path}{RESET}")
    else:
        print(f"{BOLD}Clusters with public endpoint: 0{RESET}")
    print()
    print_console_link("Manage Kubernetes / OpenShift clusters", "https://cloud.ibm.com/kubernetes/clusters")


if __name__ == "__main__":
    main()
