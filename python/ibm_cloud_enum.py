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
import datetime
import json
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BLUE, BOLD, CYAN, ORANGE, RESET, SEPARATOR,
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
v2.0 by manotux & svetterIO
{BLUE}{BOLD}=============================================={RESET}
"""


# Canonical mapping: action name -> (module_attr, script_filename, flag_set)
# flag_set is one of: "common", "full_debug", "service_api", "users", "list_files", "download"
ACTIONS: dict[str, tuple[str, str, str]] = {
    "get_api_keys":          ("get_api_keys",          "get_api_keys.py",          "common"),
    "get_service_api_keys":  ("get_service_api_keys",  "get_service_api_keys.py",  "service_api"),
    "get_custom_roles":      ("get_custom_roles",       "get_custom_roles.py",      "full_debug"),
    "get_users":             ("get_users",              "get_users.py",             "users"),
    "get_user_policies":     ("get_user_policies",      "get_user_policies.py",     "common"),
    "get_mfa":               ("get_mfa",                "get_mfa.py",               "full_debug"),
    "get_regions":           ("get_regions",            "get_regions.py",           "common"),
    "get_floating_IPs":      ("get_floating_IPs",       "get_floating_IPs.py",      "common"),
    "get_VSIs":              ("get_VSIs",               "get_VSIs.py",              "common"),
    "get_schematics":        ("get_schematics",         "get_schematics.py",        "common"),
    "get_clusters":          ("get_clusters",           "get_clusters.py",          "full_debug"),
    "get_databases":         ("get_databases",          "get_databases.py",         "common"),
    "get_buckets":           ("get_buckets",            "get_buckets.py",           "common"),
    "get_buckets_files":     ("get_buckets_files",      "get_buckets_files.py",     "buckets_files"),
    "get_security_groups":        ("get_security_groups",       "get_security_groups.py",        "common"),
    "get_load_balancers":         ("get_load_balancers",        "get_load_balancers.py",         "common"),
    "get_code_engine":            ("get_code_engine",           "get_code_engine.py",            "full_debug"),
    "download_buckets_files":     ("download_buckets_files",    "download_buckets_files.py",     "download"),
    "search_buckets_file_names":  ("search_buckets_file_names", "search_buckets_file_names.py",  "common"),
}


def parse_args(argv=None):
    """Two-phase parse.

    Phase 1: peek at argv to detect whether an ACTION was given.

    - No action  → full-run mode: parse all runner flags normally.
    - Action given → single-action mode: parse only -o/-v (runner-level flags
      that always apply), leave everything else as module pass-through extras.
      This prevents runner flags like -p/-m from silently swallowing flags that
      were meant for the module (e.g. `get_buckets_files -p 20 -m 50`).
    """
    argv = sys.argv[1:] if argv is None else list(argv)

    # Detect whether a known action name appears in argv (before any '--').
    # We scan carefully: skip flag arguments together with their values so that
    # e.g. "-p 5" doesn't cause "5" to be mistaken for an action name.
    FLAGS_WITH_VALUE = {"-o", "-p", "-n", "-q", "-m"}
    action = None
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--":
            break
        if tok in FLAGS_WITH_VALUE:
            i += 2   # skip flag + its value
            continue
        if tok.startswith("-"):
            i += 1   # boolean flag, no value
            continue
        # First bare word is the action candidate
        if tok in ACTIONS:
            action = tok
        break

    desc_base = (
        "IBM Cloud ToolKit – run all enumeration modules, or a single one.\n\n"
        "When ACTION is given, all remaining flags are forwarded as-is to that\n"
        "module (same as calling the script directly).\n\n"
        "Available actions (same names as the underlying scripts):\n  "
        + "\n  ".join(sorted(ACTIONS))
    )

    if action is not None:
        # Single-action mode: consume -o, -v, and -d (full-debug toggle); leave
        # everything else as pass-through extras for the module itself.
        # -d is claimed here so it is never forwarded raw to modules that define
        # -d differently (e.g. ROTATION_DAYS in get_service_api_keys/get_api_keys).
        p = argparse.ArgumentParser(
            prog="ibm_cloud_enum.py",
            description=desc_base,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p.add_argument("action",
                       help="Module to run (e.g. get_api_keys).")
        p.add_argument("-o", metavar="OUTPUT_DIR", default="",
                       help="Report folder (default: time-bound 'reports/report_YYYYMMDD_HHMMSS')")
        p.add_argument("-v", action="store_true",
                       help="Enable verbose/debug mode")
        p.add_argument("-d", action="store_true",
                       help="Full debug mode (unredacted tokens); requires -v")
        args, extras = p.parse_known_args(argv)
        # Synthesise missing full-run attributes so the rest of main() still works
        args.p = 10
        args.n = 100
        args.q = 10
        args.m = None
        args.f = False
        args.s = False
        args._extras = extras
        return args

    # Full-run mode: parse every runner flag.
    p = argparse.ArgumentParser(
        prog="ibm_cloud_enum.py",
        description=desc_base,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("action", nargs="?", default=None,
                   metavar="ACTION",
                   help="Run a single module instead of all (e.g. get_api_keys). "
                        "Omit to run everything.")
    p.add_argument("-o", metavar="OUTPUT_DIR", default="",
                   help="Report folder for all modules (default: time-bound 'reports/report_YYYYMMDD_HHMMSS')")
    p.add_argument("-v", action="store_true",
                   help="Enable debug mode for all modules")
    p.add_argument("-d", action="store_true",
                   help="Full debug mode (unredacted tokens); requires -v")
    p.add_argument("-p", metavar="PARALLEL", type=int, default=10,
                   help="Parallel workers for get_users and get_service_api_keys (default: 10)")
    p.add_argument("-n", metavar="LIST_ITEMS", type=int, default=100,
                   help="Maximum file keys to list per bucket in get_buckets_files (default: 100)")
    p.add_argument("-q", metavar="LIST_PARALLEL", type=int, default=10,
                   help="Parallel workers for get_buckets_files listing (default: 10)")
    p.add_argument("-m", metavar="MAX_ITEMS", type=int, default=None,
                   help="Maximum files to download per bucket (required to enable downloading)")
    p.add_argument("-f", action="store_true",
                   help="Flatten downloaded files (keep only filename); only used with -m")
    p.add_argument("-s", action="store_true",
                   help="Search bucket file names for sensitive patterns (opt-in; can be noisy)")
    args = p.parse_args(argv)
    args._extras = []
    return args


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


def _run_module(module_main, script_name: str, common_flags: list[str], extra_flags: list[str] = None) -> None:
    """Print the command being executed, then call the module's main()."""
    flags = common_flags + (extra_flags or [])
    cmd = " ".join(["python", f"python/{script_name}"] + flags)
    print(f"\n{CYAN}{BOLD}>>>{RESET} {cmd}")
    try:
        module_main(flags)
    except SystemExit as exc:
        # A module called sys.exit(0) – that's normal completion; re-raise only on errors.
        if exc.code not in (None, 0):
            raise


def _import_all() -> dict:
    """Lazily import all modules and return a name->module mapping."""
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
    import get_buckets_files
    import download_buckets_files
    import get_security_groups
    import get_load_balancers
    import get_code_engine
    import search_buckets_file_names
    return {
        "get_api_keys": get_api_keys,
        "get_service_api_keys": get_service_api_keys,
        "get_custom_roles": get_custom_roles,
        "get_users": get_users,
        "get_user_policies": get_user_policies,
        "get_mfa": get_mfa,
        "get_regions": get_regions,
        "get_floating_IPs": get_floating_IPs,
        "get_VSIs": get_VSIs,
        "get_schematics": get_schematics,
        "get_clusters": get_clusters,
        "get_databases": get_databases,
        "get_buckets": get_buckets,
        "get_buckets_files": get_buckets_files,
        "download_buckets_files": download_buckets_files,
        "get_security_groups": get_security_groups,
        "get_load_balancers": get_load_balancers,
        "get_code_engine": get_code_engine,
        "search_buckets_file_names": search_buckets_file_names,
    }


def _build_flags(args, flag_set: str) -> list[str]:
    """Return the flag list for a given flag_set name."""
    common: list[str] = []
    if args.o:
        common += ["-o", args.o]
    if args.v:
        common.append("-v")

    if flag_set == "common":
        return common
    if flag_set == "full_debug":
        return common + (["-d"] if args.d else [])
    if flag_set == "service_api":
        flags = common + ["-p", str(args.p)]
        if args.d:
            flags.append("-d")
        return flags
    if flag_set == "users":
        return common + (["-d"] if args.d else []) + ["-p", str(args.p)]
    if flag_set == "buckets_files":
        return common + ["-m", str(args.n), "-p", str(args.q)]
    if flag_set == "download":
        flags = common + ["-m", str(args.m)]
        if args.f:
            flags.append("-f")
        return flags
    return common


def _run_action(action_name: str, args, modules: dict) -> None:
    """Execute a single action by name."""
    mod_attr, script_file, flag_set = ACTIONS[action_name]
    mod = modules[mod_attr]
    flags = _build_flags(args, flag_set)
    _run_module(mod.main, script_file, flags)


def main(argv=None):
    args = parse_args(argv)

    if args.d and not args.v:
        print("Error: -d flag requires -v flag to be set", file=sys.stderr)
        sys.exit(1)

    # Default to a time-bound report folder inside reports/ (e.g. reports/report_20261026_082939)
    # so runs never overwrite each other.
    if not args.o:
        args.o = "reports/" + datetime.datetime.now().strftime("report_%Y%m%d_%H%M%S")

    # ── Single-action mode ────────────────────────────────────────────────────
    if args.action is not None:
        if args.action not in ACTIONS:
            print(f"Error: unknown action '{args.action}'", file=sys.stderr)
            print(f"Available actions: {', '.join(sorted(ACTIONS))}", file=sys.stderr)
            sys.exit(1)

        print(BANNER)
        require_ibmcloud_login()

        # Show account info (same as full-run mode)
        info = get_account_info()
        print(f"{ORANGE}{BOLD}IBM Cloud Account:{RESET}")
        print(f"· {BOLD}Account Name:{RESET} {info['account_name']}")
        print(f"· {BOLD}Account ID / Softlayer Account:{RESET} "
              f"{info['account_id']} - {info['softlayer_id']}")
        print(f"· {BOLD}User Email:{RESET} {info['user_email']}")
        print()

        if args.o:
            from utils import ensure_output_dir
            ensure_output_dir(args.o)

        # Build the flag list using the same _build_flags logic as full-run mode,
        # so runner flags (-o, -v, -d) are only forwarded where the module accepts
        # them. Then append any remaining extras the user typed after ACTION.
        _, script_file, flag_set = ACTIONS[args.action]
        passthrough = _build_flags(args, flag_set) + args._extras
        modules = _import_all()
        mod = modules[ACTIONS[args.action][0]]
        _run_module(mod.main, script_file, passthrough)

        print(" ")
        print(SEPARATOR)
        output_dir = args.o if args.o else "reports"
        print(f"Results saved to folder {BOLD}{output_dir}{RESET}")
        print(" ")
        return

    # ── Full-run mode ─────────────────────────────────────────────────────────
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

    if args.o:
        from utils import ensure_output_dir
        ensure_output_dir(args.o)

    modules = _import_all()

    FULL_RUN_ORDER = [
        "get_api_keys",
        "get_service_api_keys",
        "get_custom_roles",
        "get_users",
        "get_user_policies",
        "get_mfa",
        "get_regions",
        "get_floating_IPs",
        "get_VSIs",
        "get_schematics",
        "get_clusters",
        "get_databases",
        "get_buckets",
        "get_security_groups",
        "get_load_balancers",
        "get_code_engine",
        "get_buckets_files",             # lists keys per bucket (default: -n 100 keys per bucket)
    ]

    for action in FULL_RUN_ORDER:
        _run_action(action, args, modules)

    # search_buckets_file_names runs only when -s is explicitly provided (opt-in, can be noisy)
    if args.s:
        _run_action("search_buckets_file_names", args, modules)
    else:
        print()
        print(SEPARATOR)
        print(f"{CYAN}Skipping bucket file name search.{RESET}")
        print(f"To search bucket file names for sensitive patterns, re-run with {BOLD}-s{RESET}:")
        print(f"  {BOLD}python python/ibm_cloud_enum.py -s{RESET}")

    # download_buckets_files runs last, only when -m is explicitly provided
    if args.m is not None:
        _run_action("download_buckets_files", args, modules)
    else:
        print()
        print(SEPARATOR)
        print(f"{CYAN}Skipping bucket file download.{RESET}")
        print(f"To download files from Object Storage buckets, re-run with {BOLD}-m MAX_ITEMS{RESET}:")
        print(f"  {BOLD}python python/ibm_cloud_enum.py -m 10{RESET}   (download up to 10 files per bucket)")
        print(f"  Add {BOLD}-f{RESET} to flatten paths (keep only filename).")
        print(f"  Add {BOLD}-n N{RESET} to change the listing limit (current: {BOLD}{args.n}{RESET} keys per bucket).")

    print(" ")
    print(SEPARATOR)
    print("IBM Cloud enumeration completed.")

    output_dir = args.o if args.o else "reports"
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
        print(f"  Bucket file listing: {BOLD}{args.n}{RESET} keys per bucket, "
              f"{BOLD}{args.q}{RESET} parallel worker(s)")
        if args.m is not None:
            print(f"  Max download items per bucket: {BOLD}{args.m}{RESET}")
        if args.f and args.m is not None:
            print(f"  Flatten downloads: {BOLD}enabled{RESET}")

    print(" ")


if __name__ == "__main__":
    main()
