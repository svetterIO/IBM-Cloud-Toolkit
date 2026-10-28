#!/usr/bin/env python3
"""
python/search_buckets_file_names.py

Scans all IBM Cloud Object Storage bucket file keys for names that suggest
sensitive content (passwords, credentials, API keys, certificates, etc.).

Bucket listings are fetched in parallel (default: 10 workers).

Output files:
  <output_dir>/bucket_file_names.json  – JSON array of all matches
  <output_dir>/bucket_file_names.txt   – human-readable report

Each match record contains:
  instance      – COS service instance name
  bucket        – bucket name
  region        – LocationConstraint
  key           – full object key (path)
  matched_keywords – list of keywords found in the key
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BLUE, BOLD, CYAN, GREEN, ORANGE, RED, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, failure, print_console_link,
    require_ibmcloud_cos, require_ibmcloud_login, warning,
)

# ── Default keyword list ──────────────────────────────────────────────────────

DEFAULT_KEYWORDS: list[str] = [
    # Credentials & secrets
    "password", "passwd", "pwd", "pass",
    "secret", "secrets",
    "credential", "credentials", "cred", "creds",
    "apikey", "api_key", "api-key",
    "token", "auth_token", "access_token",
    "private_key", "privatekey", "privkey",
    "encryption_key", "enckey",
    # Certificates & PKI
    "certificate", "cert", "certs",
    ".pem", ".p12", ".pfx", ".key", ".crt", ".cer", ".jks", ".keystore",
    # Config & env files
    ".env", "config", "configuration",
    "settings", ".conf", ".cfg", ".ini",
    ".properties", ".yaml", ".yml",
    # Database
    "database", "db_pass", "db_pwd", "dbpassword",
    "connection_string", "dsn",
    # SSH / VPN
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "ssh_key", ".ssh",
    "vpn", "ovpn", ".ovpn",
    # Cloud / IAM
    "iam", "service_account", "serviceaccount",
    "kube_config", "kubeconfig",
    ".kubeconfig",
    # Generic sensitive names
    "backup", "dump", "export",
    "shadow", "htpasswd", ".htpasswd",
    "wallet",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compile_patterns(keywords: list[str]) -> list[re.Pattern]:
    """Compile each keyword into a case-insensitive regex pattern."""
    return [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]


def _matches(key: str, patterns: list[re.Pattern]) -> list[str]:
    """Return the list of keywords whose pattern matches anywhere in *key*."""
    return [p.pattern for p in patterns if p.search(key)]


def _list_bucket(inst_name: str, bucket_name: str, bucket_region: str,
                 max_items: int, patterns: list[re.Pattern],
                 debug: bool) -> dict:
    """Fetch object keys for one bucket, return matches and metadata."""
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Scanning bucket: {bucket_name}")

    result = _ibmcloud(
        "cos", "list-objects-v2",
        "--bucket", bucket_name,
        "--region", bucket_region,
        "--max-items", str(max_items),
        "--output", "json",
    )

    if result.returncode != 0 or not result.stdout:
        warning(f"Could not list objects in bucket '{bucket_name}'.")
        return {
            "inst_name": inst_name,
            "bucket_name": bucket_name,
            "region": bucket_region,
            "total_keys": 0,
            "matches": [],
            "truncated": False,
        }

    try:
        data = json.loads(result.stdout)
        contents = data.get("Contents") or []
        truncated = data.get("IsTruncated", False)
    except json.JSONDecodeError:
        contents = []
        truncated = False

    matches = []
    for obj in contents:
        key = obj.get("Key", "")
        hit_keywords = _matches(key, patterns)
        if hit_keywords:
            matches.append({
                "instance": inst_name,
                "bucket": bucket_name,
                "region": bucket_region,
                "key": key,
                "matched_keywords": hit_keywords,
            })

    return {
        "inst_name": inst_name,
        "bucket_name": bucket_name,
        "region": bucket_region,
        "total_keys": len(contents),
        "matches": matches,
        "truncated": truncated,
    }


# ── Argument parsing ──────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="search_buckets_file_names.py",
        description=(
            "Scan all IBM Cloud Object Storage bucket file keys for names that\n"
            "suggest sensitive content (passwords, credentials, API keys, etc.).\n\n"
            "Use -k to override the default keyword list, or -e to extend it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports",
                   help="Report folder (default: reports)")
    p.add_argument("-m", metavar="MAX_ITEMS", type=int, default=1000,
                   help="Maximum object keys to scan per bucket (default: 1000)")
    p.add_argument("-p", metavar="MAX_PARALLEL", type=int, default=10,
                   help="Parallel workers for bucket scanning (default: 10)")
    p.add_argument("-k", metavar="KEYWORD", action="append", dest="keywords",
                   help="Override default keywords with these (repeatable: -k pwd -k secret). "
                        "Replaces the entire default list.")
    p.add_argument("-e", metavar="KEYWORD", action="append", dest="extra_keywords",
                   help="Extend the default keyword list (repeatable: -e myapp -e internal). "
                        "Added on top of the defaults.")
    p.add_argument("-v", action="store_true",
                   help="Enable debug mode")
    return p.parse_args(argv)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cos()
    out_dir = ensure_output_dir(args.o)
    json_path = out_dir / "bucket_file_names.json"
    txt_path  = out_dir / "bucket_file_names.txt"

    # Build effective keyword list
    if args.keywords:
        keywords = args.keywords
    else:
        keywords = list(DEFAULT_KEYWORDS)
    if args.extra_keywords:
        keywords = keywords + [kw for kw in args.extra_keywords if kw not in keywords]

    patterns = _compile_patterns(keywords)

    print(" ")
    print(SEPARATOR)
    print(f"Scanning IBM Cloud Object Storage buckets for {ORANGE}{BOLD}sensitive file names{RESET}...")
    print(" ")
    print(f"{BOLD}Keywords ({len(keywords)}):{RESET} "
          + ", ".join(f"{CYAN}{kw}{RESET}" for kw in keywords))
    print(" ")

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud resource service-instances "
              "--service-name cloud-object-storage --all-resource-groups --output json")

    result = _ibmcloud(
        "resource", "service-instances",
        "--service-name", "cloud-object-storage",
        "--all-resource-groups",
        "--output", "json",
    )
    if result.returncode != 0:
        failure("Failed to retrieve Cloud Object Storage service instances.")
    try:
        instances = json.loads(result.stdout)
    except json.JSONDecodeError:
        failure("Failed to parse COS instances response.")

    # ── Collect all buckets ───────────────────────────────────────────────────
    all_buckets: list[tuple[str, str, str]] = []
    for instance in instances:
        inst_name = instance.get("name", "")
        inst_crn  = instance.get("crn", "")

        if args.v:
            print(f"{BOLD}[DEBUG]{RESET} Enumerating buckets for instance: {inst_name}")

        br = _ibmcloud(
            "cos", "buckets-extended",
            "--ibm-service-instance-id", inst_crn,
            "--output", "json",
        )
        if br.returncode != 0 or not br.stdout:
            continue
        try:
            bd = json.loads(br.stdout)
            buckets = bd.get("Buckets") or []
        except json.JSONDecodeError:
            continue

        for bucket in buckets:
            all_buckets.append((
                inst_name,
                bucket.get("Name", ""),
                bucket.get("LocationConstraint", ""),
            ))

    total_buckets = len(all_buckets)
    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} Found {total_buckets} bucket(s) across all instances")

    print(f"{BOLD}Total buckets to scan: {total_buckets}{RESET}")

    if total_buckets == 0:
        print("No buckets found.")
        json_path.write_text("[]", encoding="utf-8")
        txt_path.write_text("No buckets found.\n", encoding="utf-8")
        return

    print(f"Scanning up to {BOLD}{args.m}{RESET} keys per bucket "
          f"with {BOLD}{args.p}{RESET} parallel worker(s)...")
    print(" ")

    # ── Parallel scan ─────────────────────────────────────────────────────────
    order: list[int] = list(range(total_buckets))
    bucket_results: dict[int, dict] = {}

    with ThreadPoolExecutor(max_workers=args.p) as executor:
        future_to_idx = {
            executor.submit(
                _list_bucket, inst, bname, bregion, args.m, patterns, args.v
            ): idx
            for idx, (inst, bname, bregion) in enumerate(all_buckets)
        }
        done = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                bucket_results[idx] = future.result()
            except Exception as exc:  # noqa: BLE001
                inst, bname, bregion = all_buckets[idx]
                warning(f"Error scanning bucket '{bname}': {exc}")
                bucket_results[idx] = {
                    "inst_name": inst, "bucket_name": bname, "region": bregion,
                    "total_keys": 0, "matches": [], "truncated": False,
                }
            done += 1
            if not args.v and done % 5 == 0:
                print(f"\rScanned: {done}/{total_buckets} buckets...",
                      end="", flush=True)

    if not args.v:
        print(f"\rScanned: {total_buckets}/{total_buckets} buckets... Done!")

    # ── Aggregate results ─────────────────────────────────────────────────────
    all_matches: list[dict] = []
    total_keys_scanned = 0
    truncated_buckets: list[str] = []

    for idx in order:
        r = bucket_results[idx]
        total_keys_scanned += r["total_keys"]
        all_matches.extend(r["matches"])
        if r["truncated"]:
            truncated_buckets.append(r["bucket_name"])

    # ── Write output files ────────────────────────────────────────────────────
    json_path.write_text(
        json.dumps(all_matches, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    txt_lines: list[str] = [
        "IBM Cloud Object Storage — Sensitive File Name Scan",
        "=" * 70,
        f"Keywords searched ({len(keywords)}): {', '.join(keywords)}",
        f"Buckets scanned:  {total_buckets}",
        f"Keys scanned:     {total_keys_scanned}",
        f"Matches found:    {len(all_matches)}",
        "",
    ]
    if truncated_buckets:
        txt_lines.append(
            f"NOTE: The following buckets were truncated at {args.m} keys "
            "(re-run with a larger -m to scan more):"
        )
        for b in truncated_buckets:
            txt_lines.append(f"  - {b}")
        txt_lines.append("")

    if all_matches:
        # Group by bucket for a readable report
        by_bucket: dict[str, list[dict]] = {}
        for m in all_matches:
            key = f"{m['instance']}/{m['bucket']}"
            by_bucket.setdefault(key, []).append(m)

        for bucket_key, hits in sorted(by_bucket.items()):
            txt_lines.append(f"## {bucket_key} ({len(hits)} match(es)) ##")
            for h in hits:
                kws = ", ".join(h["matched_keywords"])
                txt_lines.append(f"  {h['key']}")
                txt_lines.append(f"    → matched: {kws}")
            txt_lines.append("")
    else:
        txt_lines.append("No sensitive file names found.")

    txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

    # ── Console summary ───────────────────────────────────────────────────────
    print()
    print(SEPARATOR)
    print(f"{BOLD}Sensitive File Name Scan — Summary:{RESET}")
    print(f"  Buckets scanned:  {BOLD}{total_buckets}{RESET}")
    print(f"  Keys scanned:     {BOLD}{total_keys_scanned}{RESET}")

    if all_matches:
        print(f"  Matches found:    {BOLD}{RED}{len(all_matches)}{RESET}")
        print()
        # Group and display by bucket
        by_bucket = {}
        for m in all_matches:
            bk = f"{m['instance']}/{m['bucket']}"
            by_bucket.setdefault(bk, []).append(m)

        for bucket_key, hits in sorted(by_bucket.items()):
            print(f"  {YELLOW}{BOLD}{bucket_key}{RESET} — {len(hits)} match(es):")
            for h in hits:
                kws = ", ".join(f"{RED}{kw}{RESET}" for kw in h["matched_keywords"])
                print(f"    {h['key']}")
                print(f"      matched: {kws}")
    else:
        print(f"  Matches found:    {BOLD}{GREEN}0{RESET}")
        print()
        print(f"  {BOLD}Good:{RESET} No object keys matched any sensitive keyword.")

    if truncated_buckets:
        print()
        print(f"  {YELLOW}{BOLD}Note:{RESET} {len(truncated_buckets)} bucket(s) were truncated "
              f"at {args.m} keys. Re-run with a larger {BOLD}-m{RESET} to scan more:")
        for b in truncated_buckets:
            print(f"    - {b}")

    print()
    print(f"Results (JSON):   {BOLD}{json_path}{RESET}")
    print(f"Results (report): {BOLD}{txt_path}{RESET}")

    if args.v:
        print()
        print(f"{BOLD}[DEBUG]{RESET} Keywords used ({len(keywords)}): {', '.join(keywords)}")

    print_console_link("IBM Cloud Object Storage", "https://cloud.ibm.com/objectstorage/instances")


if __name__ == "__main__":
    main()
