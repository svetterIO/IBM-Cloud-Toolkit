#!/usr/bin/env python3
"""
python/get_databases.py

Enumerates IBM Cloud Databases (cdb deployments) and DB2 instances.
Flags databases with non-private endpoints.

Output files:
  <output_dir>/databases.json                  – all databases
  <output_dir>/public_endpoint_databases.json  – databases with public endpoints
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, ensure_output_dir,
    require_ibmcloud_cdb, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_databases.py",
        description="Enumerate IBM Cloud Databases.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="databases.json")
    p.add_argument("-v", action="store_true")
    return p.parse_args(argv)


def get_cdb_deployments(debug: bool, out_dir: Path) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cdb deployments --json")
    result = _ibmcloud("cdb", "deployments", "--json")
    if result.returncode != 0:
        (out_dir / "cdb_deployments.stderr").write_text(result.stderr, encoding="utf-8")
        warning(f"Failed to retrieve Cloud Databases. See {out_dir}/cdb_deployments.stderr")
        return []
    try:
        data = json.loads(result.stdout)
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning("Cloud Databases CLI returned invalid JSON.")
        return []


def get_db2_instances(debug: bool, out_dir: Path) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instances "
              "--service-name dashdb-for-transactions --all-resource-groups --output json")
    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", "dashdb-for-transactions",
        "--all-resource-groups",
        "--output", "json",
    )
    if result.returncode != 0:
        (out_dir / "db2_instances.stderr").write_text(result.stderr, encoding="utf-8")
        warning(f"Failed to retrieve DB2 instances. See {out_dir}/db2_instances.stderr")
        return []
    try:
        data = json.loads(result.stdout)
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning("DB2 CLI returned invalid JSON.")
        return []


def check_endpoint(db_guid: str, debug: bool) -> str:
    """Return the service-endpoints parameter for a given DB GUID."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instance {db_guid} --output json")
    result = _ibmcloud("resource", "service-instance", db_guid, "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return "private"
    try:
        data = json.loads(result.stdout)
        instances = data if isinstance(data, list) else [data]
        params = (instances[0] or {}).get("parameters") or {}
        return params.get("service-endpoints", "private")
    except (json.JSONDecodeError, IndexError, KeyError):
        return "private"


def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cdb()
    out_dir = ensure_output_dir(args.o)
    output_path = out_dir / args.f
    public_path = out_dir / f"public_endpoint_{args.f}"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating IBM Cloud {ORANGE}{BOLD}Databases{RESET}...")
    print(" ")

    cdb = get_cdb_deployments(args.v, out_dir)
    db2 = get_db2_instances(args.v, out_dir)

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(cdb)} Cloud Database(s)")
        print(f"{BOLD}[DEBUG]{RESET} Found {len(db2)} DB2 instance(s)")

    combined = cdb + db2
    if not combined:
        print()
        print(f"{BOLD}Total databases found: 0{RESET}")
        print("No databases found.")
        return

    total = len(combined)
    print(f"{BOLD}Total databases found: {total}{RESET}")
    print()
    print(f"{BOLD}Databases:{RESET}")
    for db in combined:
        name = db.get("name", "unknown")
        dtype = db.get("type") or db.get("service_id", "unknown")
        print(f"  - {name} (Type: {dtype})")

    # Unset resource group to check across all groups
    _ibmcloud("target", "--unset-resource-group", "-q")

    public_dbs: list[dict] = []
    for db in combined:
        guid = db.get("guid") or db.get("id", "")
        if not guid:
            continue
        ep = check_endpoint(guid, args.v)
        if ep != "private":
            public_dbs.append({
                "name": db.get("name"),
                "guid": guid,
                "crn": db.get("crn"),
                "service_endpoints": ep,
            })

    output_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print()
    print(f"All databases saved to: {BOLD}{output_path}{RESET}")
    print()

    if public_dbs:
        public_path.write_text(json.dumps(public_dbs, indent=2), encoding="utf-8")
        print(f"{BOLD}Databases with public endpoint: {len(public_dbs)}{RESET}")
        print(f"Databases with public endpoint saved to: {BOLD}{public_path}{RESET}")
    else:
        print(f"{BOLD}Databases with public endpoint: 0{RESET}")


if __name__ == "__main__":
    main()
