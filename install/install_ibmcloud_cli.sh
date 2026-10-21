#!/usr/bin/env bash

# install/install_ibmcloud_cli.sh
#
# Installs the IBM Cloud CLI on Linux or macOS, then optionally installs
# the plugins used by the IBM Cloud ToolKit.
# Requires: curl, bash 4+

set -euo pipefail

PLUGINS=(
    cloud-databases
    vpc-infrastructure
    schematic
    schematics
    cloud-object-storage
    container-registry
    ks
    sl
    code-engine
)

check_command() {
    type -P "$1" &>/dev/null
}

install_cli() {
    OS_TYPE="$(uname -s)"
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        echo "Detected macOS."
        echo "Running: curl -fsSL https://clis.cloud.ibm.com/install/osx | sh"
        curl -fsSL https://clis.cloud.ibm.com/install/osx | sh
    elif [[ "$OS_TYPE" == "Linux" ]]; then
        echo "Detected Linux."
        echo "Running: curl -fsSL https://clis.cloud.ibm.com/install/linux | sh"
        curl -fsSL https://clis.cloud.ibm.com/install/linux | sh
    else
        echo "Unsupported OS: $OS_TYPE" >&2
        exit 1
    fi
}

install_plugins() {
    echo
    echo "Installing IBM Cloud CLI plugins..."
    for plugin in "${PLUGINS[@]}"; do
        echo "  Installing plugin: $plugin"
        ibmcloud plugin install "$plugin" -f || echo "  Warning: failed to install plugin '$plugin'"
    done
    echo "Plugin installation complete."
}

# ── Main ──────────────────────────────────────────────────────────────────────

echo "IBM Cloud CLI Installer"
echo "========================"
echo

read -rp "Install / verify IBM Cloud CLI? (y/n) " INSTALL_CLI
if [[ "$INSTALL_CLI" =~ ^([yY])$ ]]; then
    if check_command "ibmcloud"; then
        echo "IBM Cloud CLI is already installed: $(ibmcloud version 2>/dev/null | head -1)"
    else
        echo "IBM Cloud CLI not found. Installing..."
        install_cli
        echo "IBM Cloud CLI installed successfully."
    fi
fi

echo
read -rp "Install IBM Cloud CLI plugins for the toolkit? (y/n) " INSTALL_PLUGINS
if [[ "$INSTALL_PLUGINS" =~ ^([yY])$ ]]; then
    install_plugins
fi

echo
echo "Next steps:"
echo "  1. Log in:       ibmcloud login"
echo "  2. Run toolkit:  bash/ibm_cloud_enum.sh"
echo
echo "For more info, see: https://cloud.ibm.com/docs/cli"
echo "Completed."
