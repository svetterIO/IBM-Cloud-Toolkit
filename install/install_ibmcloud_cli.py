#!/usr/bin/env python3
"""
install/install_ibmcloud_cli.py

Cross-platform IBM Cloud CLI installer.
Detects the current OS and runs the appropriate installation method,
then optionally installs the toolkit plugins.

Supports: Linux, macOS, Windows
Requires: Python 3.8+, internet access
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

PLUGINS = [
    "cloud-databases",
    "vpc-infrastructure",
    "schematics",
    "cloud-object-storage",
    "container-registry",
    "ks",
    "sl",
    "code-engine",
]

# IBM Cloud CLI installers
INSTALLER_URLS = {
    "linux": "https://clis.cloud.ibm.com/install/linux",
    "darwin": "https://clis.cloud.ibm.com/install/osx",
    "windows": "https://download.clis.cloud.ibm.com/ibm-cloud-cli/latest/IBM_Cloud_CLI_latest_windows_amd64.exe",
}


def prompt(question: str) -> bool:
    """Ask a yes/no question and return True for yes."""
    while True:
        answer = input(f"{question} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def ibmcloud_installed() -> bool:
    return shutil.which("ibmcloud") is not None


def install_cli_unix(system: str) -> None:
    """Install IBM Cloud CLI on Linux or macOS via the shell installer."""
    url = INSTALLER_URLS[system]
    print(f"Downloading installer from {url} ...")
    with urllib.request.urlopen(url) as response:  # noqa: S310
        script = response.read()
    subprocess.run(["sh"], input=script, check=True)


def install_cli_windows() -> None:
    """Download and silently install IBM Cloud CLI on Windows."""
    url = INSTALLER_URLS["windows"]
    print(f"Downloading installer from {url} ...")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".exe")
    os.close(tmp_fd)
    try:
        urllib.request.urlretrieve(url, tmp_path)  # noqa: S310
        print("Running installer (silent)...")
        subprocess.run([tmp_path, "/S"], check=True)
        print("IBM Cloud CLI installed successfully.")
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def install_plugins() -> None:
    print("\nInstalling IBM Cloud CLI plugins...")
    for plugin in PLUGINS:
        print(f"  Installing plugin: {plugin}")
        result = subprocess.run(
            ["ibmcloud", "plugin", "install", plugin, "-f"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("    OK")
        else:
            print(f"    Warning: failed to install '{plugin}'")
    print("Plugin installation complete.")


def main() -> None:
    print("IBM Cloud CLI Installer")
    print("========================")
    print()

    system = platform.system().lower()  # 'linux', 'darwin', 'windows'
    if system not in INSTALLER_URLS:
        print(f"Unsupported operating system: {platform.system()}", file=sys.stderr)
        sys.exit(1)

    if prompt("Install / verify IBM Cloud CLI?"):
        if ibmcloud_installed():
            result = subprocess.run(
                ["ibmcloud", "version"],
                capture_output=True,
                text=True,
            )
            version_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"
            print(f"IBM Cloud CLI is already installed: {version_line}")
        else:
            print("IBM Cloud CLI not found. Installing...")
            if system == "windows":
                install_cli_windows()
            else:
                install_cli_unix(system)
            print("IBM Cloud CLI installed successfully.")

    print()
    if prompt("Install IBM Cloud CLI plugins for the toolkit?"):
        install_plugins()

    print()
    print("Next steps:")
    print("  1. Log in:       ibmcloud login")
    if system == "windows":
        print(r"  2. Run toolkit:  python python\ibm_cloud_enum.py")
    else:
        print("  2. Run toolkit:  python3 python/ibm_cloud_enum.py")
    print()
    print("For more info, see: https://cloud.ibm.com/docs/cli")
    print("Completed.")


if __name__ == "__main__":
    main()
