#!/usr/bin/env python3
"""
python/get_code_engine.py

Enumerates IBM Cloud Code Engine projects and their resources.

Output files:
  <output_dir>/code_engine_projects.json
  <output_dir>/code_engine_apps.json
  <output_dir>/code_engine_apps_envvars.json
  <output_dir>/code_engine_apps_public_endpoints.json
  <output_dir>/code_engine_functions.json
  <output_dir>/code_engine_configmaps.json
  <output_dir>/code_engine_secrets.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, failure, ibmcloud_access_token,
    ibmcloud_get, require_ibmcloud_ce, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_code_engine.py",
        description="Enumerate IBM Cloud Code Engine projects and resources.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="output")
    p.add_argument("-v", action="store_true")
    p.add_argument("-d", action="store_true",
                   help="Full debug (show token); requires -v")
    return p.parse_args(argv)


def target_region_and_group(region: str, rg: str) -> bool:
    result = _ibmcloud("target", "-r", region, "-g", rg, "-q")
    return result.returncode == 0


def main(argv=None):
    args = parse_args(argv)
    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    require_ibmcloud_login()
    require_ibmcloud_ce()
    out_dir = ensure_output_dir(args.o)

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating {ORANGE}{BOLD}Code Engine Projects{RESET} across all regions via API...")
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Retrieving access token")

    token = ibmcloud_access_token()
    if args.v:
        if args.d:
            print(f"{BOLD}[DEBUG]{RESET} Access token: {token}")
        else:
            print(f"{BOLD}[DEBUG]{RESET} Access token obtained ({token[:20]}...)")
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource groups --output json")

    # Get resource groups
    rg_result = _ibmcloud("resource", "groups", "--output", "json")
    if rg_result.returncode != 0:
        failure("Failed to retrieve resource groups.")
    try:
        rgs = json.loads(rg_result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse resource groups response.")

    if not rgs:
        failure("No resource groups found in this account.")

    first_rg = rgs[0].get("name", "")
    if not first_rg:
        failure("Could not determine a valid resource group.")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {len(rgs)} resource group(s), using: {first_rg}")
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud target -r us-east -g {first_rg}")

    if not target_region_and_group("us-east", first_rg):
        failure(f"Failed to target us-east region with resource group: {first_rg}")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud ce project list --all --output json")

    projects_result = _ibmcloud("ce", "project", "list", "--all", "--output", "json")
    if projects_result.returncode != 0:
        failure("Failed to retrieve Code Engine projects.")

    try:
        projects = json.loads(projects_result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse Code Engine projects response.")

    if not projects:
        print("No Code Engine projects found.")
        return

    # Save projects
    projects_path = out_dir / "code_engine_projects.json"
    projects_path.write_text(json.dumps(projects, indent=2), encoding="utf-8")
    print(f"All Code Engine Projects saved to: {BOLD}{projects_path}{RESET}")

    all_apps: list[dict] = []
    all_envvars: list[dict] = []
    all_public_apps: list[dict] = []
    all_functions: list[dict] = []
    all_configmaps: list[dict] = []
    all_secrets: list[dict] = []

    for project in projects:
        project_name = project.get("name", "")
        region_id = project.get("region_id", "")
        project_id = project.get("guid", "")

        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Processing project: {project_name} (region: {region_id})")

        base_url = f"https://api.{region_id}.codeengine.cloud.ibm.com/v2/projects/{project_id}"

        # Applications
        apps_data = ibmcloud_get(f"{base_url}/apps", token) or {}
        apps = apps_data.get("apps") or []
        if apps:
            if args.v:
                print(f"{BOLD}[DEBUG]{RESET} Project '{project_name}': Found {len(apps)} application(s)")
            all_apps.extend(apps)
            for app in apps:
                all_envvars.append({
                    "project": project_name,
                    "application": app.get("name"),
                    "run_env_variables": app.get("run_env_variables"),
                })
                if app.get("managed_domain_mappings") == "local_public":
                    all_public_apps.append({
                        "project": project_name,
                        "application": app.get("name"),
                        "managed_domain_mappings": app.get("managed_domain_mappings"),
                        "endpoint": app.get("endpoint"),
                    })

        # Functions
        funcs_data = ibmcloud_get(f"{base_url}/functions", token) or {}
        funcs = funcs_data.get("functions") or []
        if funcs:
            if args.v:
                print(f"{BOLD}[DEBUG]{RESET} Project '{project_name}': Found {len(funcs)} function(s)")
            all_functions.append({"project": project_name, "functions": funcs})

        # Secrets
        secrets_data = ibmcloud_get(f"{base_url}/secrets", token) or {}
        secrets = secrets_data.get("secrets") or []
        if secrets:
            if args.v:
                print(f"{BOLD}[DEBUG]{RESET} Project '{project_name}': Found {len(secrets)} secret(s)")
            all_secrets.append({"project": project_name, "secrets": secrets})

        # ConfigMaps
        cm_data = ibmcloud_get(f"{base_url}/config_maps", token) or {}
        cms = cm_data.get("config_maps") or []
        if cms:
            if args.v:
                print(f"{BOLD}[DEBUG]{RESET} Project '{project_name}': Found {len(cms)} configmap(s)")
            all_configmaps.append({"project": project_name, "configmaps": cms})

    # Save all resources
    def _save(data: list, filename: str, label: str) -> None:
        if data:
            path = out_dir / filename
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"{BOLD}Total {label}: {len(data)}{RESET}")
            print(f"{label} saved to: {BOLD}{path}{RESET}")
        else:
            print(f"{BOLD}Total {label}: 0{RESET}")

    _save(all_apps, "code_engine_apps.json", "Applications")

    if all_envvars:
        envvars_path = out_dir / "code_engine_apps_envvars.json"
        envvars_path.write_text(json.dumps(all_envvars, indent=2), encoding="utf-8")
        print(f"Code Engine Applications Environment Variables saved to: {BOLD}{envvars_path}{RESET}")

    if all_public_apps:
        public_path = out_dir / "code_engine_apps_public_endpoints.json"
        public_path.write_text(json.dumps(all_public_apps, indent=2), encoding="utf-8")
        print(f"{BOLD}Applications with public endpoint: {len(all_public_apps)}{RESET}")
        print(f"Code Engine Applications with public endpoint saved to: {BOLD}{public_path}{RESET}")
    else:
        print(f"{BOLD}Applications with public endpoint: 0{RESET}")

    _save(all_functions, "code_engine_functions.json", "Functions")
    _save(all_configmaps, "code_engine_configmaps.json", "ConfigMaps")
    _save(all_secrets, "code_engine_secrets.json", "Secrets")

    print()
    print("Review Env Vars and ConfigMaps for secrets using tools like "
          "TruffleHog/detect-secrets or manually.")

    # Restore clean target state
    _ibmcloud("target", "--unset-resource-group", "-q")


if __name__ == "__main__":
    main()
