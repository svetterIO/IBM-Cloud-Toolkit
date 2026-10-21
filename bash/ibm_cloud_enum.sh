#!/usr/bin/env bash
# ibm_cloud_enum.sh
#
# Main enumeration script for IBM Cloud. Runs all resource enumeration scripts in sequence.
# Usage: ./ibm_cloud_enum.sh [-h] [-o OUTPUT_DIR] [-v] [-d] [-p PARALLEL] [-m MAX_ITEMS] [-f]
# -h: Show help
# -o OUTPUT_DIR: Specify output directory for all scripts (default: each script uses its own default)
# -v: Enable debug mode for all scripts
# -d: Enable full debug mode (requires -v, only for scripts that support it)
# -p PARALLEL: Number of parallel workers for get_users.sh and get_service_api_keys.sh (default: 10)
# -m MAX_ITEMS: Maximum number of files to download per bucket (default: 10)
# -f: Flatten downloaded files (strip path, keep only filename)
# Requires IBM Cloud CLI, jq for JSON parsing, curl for REST API requests,
# and the following plugins of IBM Cloud CLI: databases ("cdb"), vpc-infrastructure ("is")
srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"
BANNER="\n${BLUE}${BOLD}==============================================${RESET}
${ORANGE}${BOLD}          IBM Cloud ToolKit v1.2 ${RESET}
${BLUE}${BOLD}==============================================${RESET}
IBM Cloud enumeration tool
github.com/manotux/IBM-Cloud-Toolkit
${BLUE}${BOLD}==============================================${RESET}\n"
OUTPUT_DIR=""
OUTPUT_DIR_SET=false
DEBUG=false
DEBUG_FULL=false
PARALLEL_WORKERS=10
MAX_DOWNLOAD_ITEMS=10
FLATTEN_DOWNLOADS=false
usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-v] [-d] [-p PARALLEL] [-m MAX_ITEMS] [-f]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: each script uses 'output')"
    echo "  -v              Enable debug mode for all scripts"
    echo "  -d              Enable full debug mode (requires -v, for scripts that support it)"
    echo "  -p PARALLEL     Number of parallel workers for get_users.sh and get_service_api_keys.sh (default: 10)"
    echo "  -m MAX_ITEMS    Maximum number of files to download per bucket (default: 10)"
    echo "  -f              Flatten downloaded files (strip directory path, keep only filename)"
    echo
    echo "This script runs all IBM Cloud enumeration scripts."
    echo
    echo "Scripts with debug support (-v): All scripts"
    echo "Scripts with full debug support (-d): get_custom_roles, get_users, get_user_policies,"
    echo "                                      get_mfa, get_clusters, get_code_engine"
    echo "Scripts with parallel support (-p): get_users, get_service_api_keys"
    echo "Download options (-m, -f): download_buckets_files"
}
while getopts ":ho:p:m:vdf" opt; do
    case $opt in
        h)
            usage
            exit 0
            ;;
        o)
            OUTPUT_DIR="$OPTARG"
            OUTPUT_DIR_SET=true
            ;;
        v)
            DEBUG=true
            ;;
        d)
            DEBUG_FULL=true
            ;;
        p)
            PARALLEL_WORKERS="$OPTARG"
            ;;
        m)
            MAX_DOWNLOAD_ITEMS="$OPTARG"
            ;;
        f)
            FLATTEN_DOWNLOADS=true
            ;;
        \?)
            echo "Invalid option: -$OPTARG" >&2
            usage
            exit 1
            ;;
        :)
            echo "Option -$OPTARG requires an argument." >&2
            usage
            exit 1
            ;;
    esac
done
# Check if -d is used without -v
if [ "$DEBUG_FULL" = true ] && [ "$DEBUG" = false ]; then
    echo "Error: -d flag requires -v flag to be set" >&2
    usage
    exit 1
fi
echo -e "$BANNER"
require_ibmcloud_jq
require_ibmcloud_cdb
require_ibmcloud_is
require_ibmcloud_schematics
require_ibmcloud_cos
require_ibmcloud_login
require_ibmcloud_sl
require_ibmcloud_ce
require_curl
# Dynamically retrieve and print IBM Cloud account info
ACCOUNT_JSON=$(ibmcloud account show --output json 2>/dev/null)
TARGET_JSON=$(ibmcloud target --output json 2>/dev/null)
ACCOUNT_NAME=$(echo "$ACCOUNT_JSON" | jq -r '.name // "-"')
ACCOUNT_ID=$(echo "$ACCOUNT_JSON" | jq -r '.account_id // "-"')
SOFTLAYER_ID=$(echo "$ACCOUNT_JSON" | jq -r '.ims_account_id // "-"')
USER_EMAIL=$(echo "$TARGET_JSON" | jq -r '.user.user_email // "-"')
echo -e "${ORANGE}${BOLD}IBM Cloud Account:${RESET}"
echo -e "· ${BOLD}Account Name:${RESET} $ACCOUNT_NAME"
echo -e "· ${BOLD}Account ID / Softlayer Account:${RESET} $ACCOUNT_ID - $SOFTLAYER_ID"
echo -e "· ${BOLD}User Email:${RESET} $USER_EMAIL"
# Create output directory only if explicitly set
if [ "$OUTPUT_DIR_SET" = true ]; then
    if [ ! -d "$OUTPUT_DIR" ]; then
        mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
    fi
fi
# Build common flags (without output directory)
COMMON_FLAGS=""
if [ "$OUTPUT_DIR_SET" = true ]; then
    COMMON_FLAGS="-o $OUTPUT_DIR"
fi
if [ "$DEBUG" = true ]; then
    COMMON_FLAGS="$COMMON_FLAGS -v"
fi
# Flags for scripts that support full debug (-d)
FULL_DEBUG_FLAGS="$COMMON_FLAGS"
if [ "$DEBUG_FULL" = true ]; then
    FULL_DEBUG_FLAGS="$FULL_DEBUG_FLAGS -d"
fi
# get_api_keys.sh: supports -v only
"$srcdir/get_api_keys.sh" $COMMON_FLAGS
# get_service_api_keys.sh: supports -v and -p
SERVICE_API_FLAGS="$COMMON_FLAGS -p $PARALLEL_WORKERS"
"$srcdir/get_service_api_keys.sh" $SERVICE_API_FLAGS
# get_custom_roles.sh: supports -v and -d
"$srcdir/get_custom_roles.sh" $FULL_DEBUG_FLAGS
# get_users.sh: supports -v, -d, and -p
USER_FLAGS="$FULL_DEBUG_FLAGS -p $PARALLEL_WORKERS"
"$srcdir/get_users.sh" $USER_FLAGS
# get_user_policies.sh: supports -v and -d
"$srcdir/get_user_policies.sh" $FULL_DEBUG_FLAGS
# get_mfa.sh: supports -v and -d
"$srcdir/get_mfa.sh" $FULL_DEBUG_FLAGS
# get_regions.sh: supports -v only
"$srcdir/get_regions.sh" $COMMON_FLAGS
# get_floating_IPs.sh: supports -v only
"$srcdir/get_floating_IPs.sh" $COMMON_FLAGS
# get_VSIs.sh: supports -v only
"$srcdir/get_VSIs.sh" $COMMON_FLAGS
# get_schematics.sh: supports -v only (has -r but we use defaults)
"$srcdir/get_schematics.sh" $COMMON_FLAGS
# get_clusters.sh: supports -v and -d
"$srcdir/get_clusters.sh" $FULL_DEBUG_FLAGS
# get_databases.sh: supports -v only
"$srcdir/get_databases.sh" $COMMON_FLAGS
# get_buckets.sh: supports -v only
"$srcdir/get_buckets.sh" $COMMON_FLAGS
# get_buckets_files.sh: supports -v only (commented out by default)
# "$srcdir/get_buckets_files.sh" $COMMON_FLAGS
# download_buckets_files.sh: supports -v, -m, -f
DOWNLOAD_FLAGS="$COMMON_FLAGS -m $MAX_DOWNLOAD_ITEMS"
if [ "$FLATTEN_DOWNLOADS" = true ]; then
    DOWNLOAD_FLAGS="$DOWNLOAD_FLAGS -f"
fi
"$srcdir/download_buckets_files.sh" $DOWNLOAD_FLAGS
# get_security_groups.sh: supports -v only
"$srcdir/get_security_groups.sh" $COMMON_FLAGS
# get_code_engine.sh: supports -v and -d
"$srcdir/get_code_engine.sh" $FULL_DEBUG_FLAGS
echo " "
echo "${SEPARATOR}"
echo "IBM Cloud enumeration completed."
# Display output location
if [ "$OUTPUT_DIR_SET" = true ]; then
    echo -e "Results saved to folder ${BOLD}${OUTPUT_DIR}${RESET}"
else
    echo -e "Results saved to default folder ${BOLD}output${RESET}"
fi
if [ "$DEBUG" = true ]; then
    echo " "
    echo -e "${BOLD}Configuration used:${RESET}"
    echo -e "  Debug mode: ${BOLD}enabled${RESET}"
    if [ "$DEBUG_FULL" = true ]; then
        echo -e "  Full debug: ${BOLD}enabled${RESET} (unredacted tokens)"
    fi
    if [ "$OUTPUT_DIR_SET" = true ]; then
        echo -e "  Output directory: ${BOLD}$OUTPUT_DIR${RESET}"
    else
        echo -e "  Output directory: ${BOLD}output${RESET} (default)"
    fi
    if [ $PARALLEL_WORKERS -ne 10 ]; then
        echo -e "  Parallel workers: ${BOLD}$PARALLEL_WORKERS${RESET}"
    fi
    if [ $MAX_DOWNLOAD_ITEMS -ne 10 ]; then
        echo -e "  Max download items per bucket: ${BOLD}$MAX_DOWNLOAD_ITEMS${RESET}"
    fi
    if [ "$FLATTEN_DOWNLOADS" = true ]; then
        echo -e "  Flatten downloads: ${BOLD}enabled${RESET}"
    fi
fi
echo " "