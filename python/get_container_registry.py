#!/usr/bin/env python3
"""
python/get_container_registry.py

Enumerates IBM Cloud Container Registry namespaces, images, and settings.
Flags images with known vulnerabilities (Vulnerability Advisor) and images
that have not been scanned.

Output files:
  <output_dir>/cr_namespaces.json    – all registry namespaces
  <output_dir>/cr_images.json        – all images (digest, tags, size, age)
  <output_dir>/cr_vulnerable.json    – images with CVEs found by VA
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils import (
    BOLD, ORANGE, RESET, SEPARATOR, YELLOW,
    _ibmcloud, ensure_output_dir, print_console_link,
    require_ibmcloud_cr, require_ibmcloud_login, warning,
)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="get_container_registry.py",
        description="Enumerate IBM Cloud Container Registry namespaces, images, and vulnerability status.",
    )
    p.add_argument("-o", metavar="OUTPUT_DIR", default="reports")
    p.add_argument("-f", metavar="OUTPUT_FILE", default="cr_images.json")
    p.add_argument("-v", action="store_true", help="Enable debug output")
    return p.parse_args(argv)


# ── Namespaces ────────────────────────────────────────────────────────────────

def get_namespaces(debug: bool, out_dir: Path) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cr namespace-list --output json")
    result = _ibmcloud("cr", "namespace-list", "--output", "json")
    if result.returncode != 0:
        (out_dir / "cr_namespaces.stderr").write_text(result.stderr, encoding="utf-8")
        warning(f"Failed to retrieve CR namespaces. See {out_dir}/cr_namespaces.stderr")
        return []
    try:
        data = json.loads(result.stdout)
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning("Container Registry namespace-list returned invalid JSON.")
        return []


# ── Images ────────────────────────────────────────────────────────────────────

def get_images(debug: bool, out_dir: Path) -> list[dict]:
    if debug:
        print(f"{BOLD}[DEBUG]{RESET} Running: ibmcloud cr image-list --output json")
    result = _ibmcloud("cr", "image-list", "--output", "json")
    if result.returncode != 0:
        (out_dir / "cr_images.stderr").write_text(result.stderr, encoding="utf-8")
        warning(f"Failed to retrieve CR images. See {out_dir}/cr_images.stderr")
        return []
    try:
        data = json.loads(result.stdout)
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        warning("Container Registry image-list returned invalid JSON.")
        return []


# ── Vulnerability Advisor ─────────────────────────────────────────────────────

def _security_status(img: dict) -> dict:
    """Return the SecurityStatus sub-object from an image record (may be empty)."""
    return img.get("SecurityStatus") or {}


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    args = parse_args(argv)

    require_ibmcloud_login()
    require_ibmcloud_cr()
    out_dir = ensure_output_dir(args.o)

    ns_path       = out_dir / "cr_namespaces.json"
    images_path   = out_dir / args.f
    vuln_path     = out_dir / "cr_vulnerable.json"

    print(" ")
    print(SEPARATOR)
    print(f"Enumerating IBM Cloud {ORANGE}{BOLD}Container Registry{RESET}...")
    print(" ")

    # ── Namespaces ────────────────────────────────────────────────────────────
    namespaces = get_namespaces(args.v, out_dir)
    ns_count = len(namespaces)
    print(f"{BOLD}Total namespaces found: {ns_count}{RESET}")

    if namespaces:
        ns_path.write_text(json.dumps(namespaces, indent=2), encoding="utf-8")
        print(f"{BOLD}Namespaces:{RESET}")
        for ns in namespaces:
            name = ns.get("name") or ns.get("Name") or str(ns)
            rg   = ns.get("resource_group_name") or ns.get("ResourceGroupName") or "-"
            print(f"  - {name}  (resource group: {rg})")
        print(f"Namespaces saved to: {BOLD}{ns_path}{RESET}")
    else:
        print("No namespaces found.")

    print()

    # ── Images ────────────────────────────────────────────────────────────────
    images = get_images(args.v, out_dir)
    img_count = len(images)
    print(f"{BOLD}Total images found: {img_count}{RESET}")

    if images:
        images_path.write_text(json.dumps(images, indent=2), encoding="utf-8")
        print(f"{BOLD}Images:{RESET}")
        for img in images:
            repo = img.get("Repository") or ""
            tag  = img.get("Tag") or ""
            tag_str = f"{repo}:{tag}" if repo else img.get("Digest", "unknown")
            size = img.get("Size", 0)
            print(f"  - {tag_str}  (size: {size} bytes)")
        print(f"All images saved to: {BOLD}{images_path}{RESET}")
    else:
        print("No images found.")

    print()

    if img_count == 0:
        print_console_link(
            "Manage Container Registry",
            "https://cloud.ibm.com/registry/images",
            "IBM Cloud Console > Container Registry > Images",
        )
        return

    # ── Vulnerability / Security Status (inline in image-list response) ───────
    # ibmcloud cr image-list already embeds SecurityStatus per image.
    # No separate VA call needed — parse it directly from the images list.
    print(f"Analysing {BOLD}Security Status{RESET} from image list...")

    vulnerable = [
        img for img in images
        if _security_status(img).get("IssueCount", 0) > 0
    ]
    scanning = [
        img for img in images
        if _security_status(img).get("Status", "").startswith("Scanning")
    ]
    ok_images = [
        img for img in images
        if _security_status(img).get("Status") == "Complete" and _security_status(img).get("IssueCount", 0) == 0
    ]

    if args.v:
        print(f"{BOLD}[DEBUG]{RESET} With issues: {len(vulnerable)}  "
              f"Scanning: {len(scanning)}  Clean: {len(ok_images)}")

    if vulnerable:
        vuln_path.write_text(json.dumps(vulnerable, indent=2), encoding="utf-8")
        print()
        print(f"{YELLOW}{BOLD}Warning:{RESET} {len(vulnerable)} image(s) with security issues found")
        print(f"Vulnerable images saved to: {BOLD}{vuln_path}{RESET}")
        for img in vulnerable:
            repo    = img.get("Repository") or ""
            tag     = img.get("Tag") or ""
            label   = f"{repo}:{tag}" if repo else img.get("Digest", "unknown")
            issues  = _security_status(img).get("IssueCount", "?")
            exempt  = _security_status(img).get("ExemptionCount", 0)
            status  = _security_status(img).get("Status", "?")
            print(f"  - {label}  (issues: {issues}, exemptions: {exempt}, status: {status})")
    else:
        print(f"{BOLD}Images with security issues: 0{RESET}")

    if scanning:
        print()
        print(f"{YELLOW}{BOLD}Note:{RESET} {len(scanning)} image(s) still being scanned — re-run later for full results")

    print()
    print_console_link(
        "Manage Container Registry",
        "https://cloud.ibm.com/registry/images",
        "IBM Cloud Console > Container Registry > Images",
    )


if __name__ == "__main__":
    main()
