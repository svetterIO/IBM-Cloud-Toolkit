#!/usr/bin/env python3
"""
python/ibm_cloud_enum.py

IBM Cloud ToolKit v2.0 – Python runner.

Executes all enumeration modules sequentially, mirroring the behaviour
of bash/ibm_cloud_enum.sh.  No external dependencies beyond the IBM Cloud
CLI and Python 3.8+ standard library.

Usage:
    python ibm_cloud_enum.py [-h] [-o OUTPUT_DIR] [-v] [-d]
                             [-p PARALLEL] [-m MAX_ITEMS] [-f]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BLUE, BOLD, ORANGE, RESET, SEPARATOR,
    _ibmcloud, failure, ibmcloud_account_id, ibmcloud_access_token,
    ibmcloud_account_name, is_ibmcloud_logged_in,
    require_ibmcloud_cdb, require_ibmcloud_ce, require_ibmcloud_cos,
    require_ibmcloud_is, require_ibmcloud_login, require_ibmcloud_schematics,
    require_ibmcloud_sl,
)

VERSION = "v2.0"

BANNER = f"""
{BLUE}{BOLD}=============================================={RESET}
{ORANGE}{BOLD}          IBM Cloud ToolKit {VERSION} {RESET}
{BLUE}{BOLD}=============================================={RESET}
IBM Cloud enumeration tool
github.com/manotux/IBM-Cloud-Toolkit
{BLUE}{BOLD}=============================================={RESET}
"""


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="ibm_cloud_enum.py",
        description="IBM Cloud ToolKit – run all enumeration modules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="",
                   help="Output folder for all modules (default: each module uses 'output')")
    p.add_argument("-v", action="store_true",
                   help="Enable debug mode for all modules")
    p.add_argument("-d", action="store_true",
                   help="Full debug mode (unredacted tokens); requires -v")
    p.add_argument("-p", metavar="PARALLEL", type=int, default=10,
                   help="Parallel workers for get_users and get_service_api_keys (default: 10)")
    p.add_argument("-m", metavar="MAX_ITEMS", type=int, default=10,
                   help="Maximum files to download per bucket (default: 10)")
    p.add_argument("-f", action="store_true",
                   help="Flatten downloaded files (keep only filename)")
    return p.parse_args(argv)


def get_account_info() -> dict:
    """Return basic account metadata."""
    info: dict[str, str] = {
        "account_name": "-",
        "account_id": "-",
        "softlayer_id": "-",
        "user_email": "-",
    }
    account_result = _ibmcloud("account", "show", "--output", "json")
    if account_result.returncode == 0:
        try:
            data = json.loads(account_result.stdout)
            info["account_name"] = data.get("name", "-")
            info["account_id"] = data.get("account_id", "-")
            info["softlayer_id"] = data.get("ims_account_id", "-")
        except json.JSONDecodeError:
            pass

    target_result = _ibmcloud("target", "--output", "json")
    if target_result.returncode == 0:
        try:
            data = json.loads(target_result.stdout)
            info["user_email"] = (data.get("user") or {}).get("user_email", "-")
        except json.JSONDecodeError:
            pass

    return info


def _run_module(module_main, common_flags: list[str], extra_flags: list[str] = None) -> None:
    """Call a module's main() function with the assembled flag list."""
    flags = common_flags + (extra_flags or [])
    try:
        module_main(flags)
    except SystemExit as exc:
        # A module called sys.exit(0) – that's normal completion; re-raise only on errors.
        if exc.code not in (None, 0):
            raise


def main(argv=None):
    args = parse_args(argv)

    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    print(BANNER)

    # Dependency and login checks
    require_ibmcloud_login()
    require_ibmcloud_cdb()
    require_ibmcloud_is()
    require_ibmcloud_schematics()
    require_ibmcloud_cos()
    require_ibmcloud_sl()
    require_ibmcloud_ce()

    # Display account info
    info = get_account_info()
    print(f"{ORANGE}{BOLD}IBM Cloud Account:{RESET}")
    print(f"· {BOLD}Account Name:{RESET} {info['account_name']}")
    print(f"· {BOLD}Account ID / Softlayer Account:{RESET} "
          f"{info['account_id']} - {info['softlayer_id']}")
    print(f"· {BOLD}User Email:{RESET} {info['user_email']}")
    print()

    # Build flag lists
    common: list[str] = []
    if args.o:
        from utils import ensure_output_dir
        ensure_output_dir(args.o)
        common += ["-o", args.o]
    if args.v:
        common.append("-v")

    full_debug: list[str] = list(common)
    if args.d:
        full_debug.append("-d")

    # Lazy imports of all modules to avoid side effects at import time
    import get_api_keys
    import get_service_api_keys
    import get_custom_roles
    import get_users
    import get_user_policies
    import get_mfa
    import get_regions
    import get_floating_IPs
    import get_VSIs
    import get_schematics
    import get_clusters
    import get_databases
    import get_buckets
    import download_buckets_files
    import get_security_groups
    import get_code_engine

    _run_module(get_api_keys.main, common)
    _run_module(get_service_api_keys.main, common, ["-p", str(args.p)])
    _run_module(get_custom_roles.main, full_debug)
    _run_module(get_users.main, full_debug, ["-p", str(args.p)])
    _run_module(get_user_policies.main, common)
    _run_module(get_mfa.main, full_debug)
    _run_module(get_regions.main, common)
    _run_module(get_floating_IPs.main, common)
    _run_module(get_VSIs.main, common)
    _run_module(get_schematics.main, common)
    _run_module(get_clusters.main, full_debug)
    _run_module(get_databases.main, common)
    _run_module(get_buckets.main, common)
    # get_buckets_files is disabled by default (can be very slow)
    # import get_buckets_files; _run_module(get_buckets_files.main, common)

    dl_flags = ["-m", str(args.m)]
    if args.f:
        dl_flags.append("-f")
    _run_module(download_buckets_files.main, common, dl_flags)

    _run_module(get_security_groups.main, common)
    _run_module(get_code_engine.main, full_debug)

    print(" ")
    print(SEPARATOR)
    print("IBM Cloud enumeration completed.")

    output_dir = args.o if args.o else "output"
    print(f"Results saved to folder {BOLD}{output_dir}{RESET}")

    if args.v:
        print()
        print(f"{BOLD}Configuration used:{RESET}")
        print(f"  Debug mode: {BOLD}enabled{RESET}")
        if args.d:
            print(f"  Full debug: {BOLD}enabled{RESET} (unredacted tokens)")
        print(f"  Output directory: {BOLD}{output_dir}{RESET}")
        if args.p != 10:
            print(f"  Parallel workers: {BOLD}{args.p}{RESET}")
        if args.m != 10:
            print(f"  Max download items per bucket: {BOLD}{args.m}{RESET}")
        if args.f:
            print(f"  Flatten downloads: {BOLD}enabled{RESET}")

    print(" ")


if __name__ == "__main__":
    main()
