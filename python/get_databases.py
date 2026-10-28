#!/usr/bin/env python3
"""
python/get_databases.py

Enumerates IBM Cloud Databases (cdb deployments), DB2 instances and Cloudant instances.
Flags databases with non-private endpoints and retrieves their public endpoints
(hostname:port).

Output files:
  <output_dir>/databases.json                  – all databases
  <output_dir>/public_endpoint_databases.json  – databases with public endpoints
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, ensure_output_dir, print_console_link,
    require_ibmcloud_cdb, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_databases.py",
        description="Enumerate IBM Cloud Databases.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
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


def get_resource_instances(service_name: str, label: str, stem: str,
                           debug: bool, out_dir: Path) -> list[dict]:
    """List resource controller instances of a service (e.g. DB2, Cloudant)."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instances "
              f"--service-name {service_name} --all-resource-groups --output json")
    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", service_name,
        "--all-resource-groups",
        "--output", "json",
    )
    if result.returncode != 0:
        (out_dir / f"{stem}.stderr").write_text(result.stderr, encoding="utf-8")
        warning(f"Failed to retrieve {label} instances. See {out_dir}/{stem}.stderr")
        return []
    try:
        data = json.loads(result.stdout)
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning(f"{label} CLI returned invalid JSON.")
        return []


def get_instance(db_guid: str, debug: bool) -> dict:
    """Return the resource controller details of a service instance."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instance {db_guid} --output json")
    result = _ibmcloud("resource", "service-instance", db_guid, "--output", "json")
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
        instances = data if isinstance(data, list) else [data]
        return instances[0] or {}
    except (json.JSONDecodeError, IndexError):
        return {}


def extension_public_endpoint(instance: dict) -> str:
    """Return 'hostname:port' from the instance extensions.endpoints.public (default port 443)."""
    endpoints = (instance.get("extensions") or {}).get("endpoints")
    if not isinstance(endpoints, dict):
        return ""
    host = endpoints.get("public")
    if not isinstance(host, str) or not host:
        return ""
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split("/", 1)[0]
    return host if ":" in host else f"{host}:443"


def _collect_host_ports(node, found: set) -> None:
    if isinstance(node, dict):
        if node.get("hostname") and node.get("port") is not None:
            found.add(f"{node['hostname']}:{node['port']}")
        for value in node.values():
            _collect_host_ports(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_host_ports(item, found)


def cdb_public_endpoints(ref: str, debug: bool) -> list[str]:
    """Return the public hostname:port pairs of a Cloud Databases deployment."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cdb deployment-connections {ref} "
              "--endpoint-type public --all --output json")
    result = subprocess.run(
        ["ibmcloud", "cdb", "deployment-connections", ref,
         "--endpoint-type", "public", "--all", "--output", "json"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    found: set = set()
    _collect_host_ports(data, found)
    return sorted(found)


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
    db2 = get_resource_instances("dashdb-for-transactions", "DB2", "db2_instances", args.v, out_dir)
    cloudant = get_resource_instances("cloudantnosqldb", "Cloudant", "cloudant_instances", args.v, out_dir)

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(cdb)} Cloud Database(s)")
        print(f"{BOLD}[DEBUG]{RESET} Found {len(db2)} DB2 instance(s)")
        print(f"{BOLD}[DEBUG]{RESET} Found {len(cloudant)} Cloudant instance(s)")

    combined = (
        [{**d, "db_service": "cloud-databases"} for d in cdb]
        + [{**d, "db_service": "db2"} for d in db2]
        + [{**d, "db_service": "cloudant"} for d in cloudant]
    )
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
        dtype = db.get("type") or db.get("service_id") or db["db_service"]
        print(f"  - {name} (Type: {dtype})")

    # Unset resource group to check across all groups
    _ibmcloud("target", "--unset-resource-group", "-q")

    public_dbs: list[dict] = []
    for db in combined:
        guid = db.get("guid") or db.get("id", "")
        if not guid:
            continue
        service = db["db_service"]
        instance = get_instance(guid, args.v)
        if not instance:
            continue
        ep_type = (instance.get("parameters") or {}).get("service-endpoints") or "private"
        ext_endpoint = extension_public_endpoint(instance)
        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Database \"{instance.get('name')}\": endpoint type = {ep_type}")
        if ep_type == "private" and not (service == "cloudant" and ext_endpoint):
            continue

        if service == "cloud-databases":
            endpoints = cdb_public_endpoints(db.get("crn") or db.get("name", ""), args.v)
        else:
            endpoints = [ext_endpoint] if ext_endpoint else []
        public_dbs.append({
            "name": instance.get("name"),
            "guid": guid,
            "crn": instance.get("crn"),
            "db_service": service,
            "service_endpoints": ep_type,
            "public_endpoints": endpoints,
        })

    output_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print()
    print(f"All databases saved to: {BOLD}{output_path}{RESET}")
    print()

    if public_dbs:
        public_path.write_text(json.dumps(public_dbs, indent=2), encoding="utf-8")
        print(f"{BOLD}Databases with public endpoint: {len(public_dbs)}{RESET}")
        for db in public_dbs:
            print(f"  - {db['name']} ({db['db_service']}): "
                  f"{', '.join(db['public_endpoints']) or 'endpoint not retrieved'}")
        print(f"Databases with public endpoint saved to: {BOLD}{public_path}{RESET}")
    else:
        print(f"{BOLD}Databases with public endpoint: 0{RESET}")
    print()
    print_console_link("Manage Cloud Databases", "https://cloud.ibm.com/databases-overview/resources",
                       "IBM Cloud Console > Databases")


if __name__ == "__main__":
    main()
