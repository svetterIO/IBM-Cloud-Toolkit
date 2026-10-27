#!/usr/bin/env bash
# ibm_cloud_enum.sh
#
# Main enumeration script for IBM Cloud. Runs all resource enumeration scripts in sequence,
# or a single named action.
#
# Usage: ./ibm_cloud_enum.sh [ACTION] [-h] [-o OUTPUT_DIR] [-v] [-d] [-p PARALLEL] [-m MAX_ITEMS] [-f] [-s]
# ACTION (optional): run only one module, e.g. get_api_keys  (omit to run all)
# -h: Show help
# -o OUTPUT_DIR: Specify output directory for all scripts (default: time-bound 'output_YYYYMMDD_HHMMSS')
# -v: Enable debug mode for all scripts
# -d: Enable full debug mode (requires -v, only for scripts that support it)
# -p PARALLEL: Number of parallel workers for get_users.sh and get_service_api_keys.sh (default: 10)
# -m MAX_ITEMS: Maximum number of files to download per bucket (required to enable downloading)
# -f: Flatten downloaded files (strip path, keep only filename)
# -s: Search bucket file names for sensitive patterns (opt-in; can be noisy)
# Requires IBM Cloud CLI, jq for JSON parsing, curl for REST API requests,
# and the following plugins of IBM Cloud CLI: databases ("cdb"), vpc-infrastructure ("is")
srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"
VERSION="v2.0"
BANNER="\n${BLUE}${BOLD}==============================================${RESET}
${ORANGE}${BOLD}          IBM Cloud ToolKit ${VERSION} ${RESET}
${BLUE}${BOLD}==============================================${RESET}
IBM Cloud enumeration tool
github.com/manotux/IBM-Cloud-Toolkit
v2.0 by manotux & svetterIO
${BLUE}${BOLD}==============================================${RESET}\n"
OUTPUT_DIR=""
OUTPUT_DIR_SET=false
DEBUG=false
DEBUG_FULL=false
PARALLEL_WORKERS=10
MAX_LIST_ITEMS=100
LIST_PARALLEL=10
MAX_DOWNLOAD_ITEMS=""
FLATTEN_DOWNLOADS=false
SEARCH_FILE_NAMES=false
ACTION=""

# All available actions (same names as the underlying scripts, without .sh)
VALID_ACTIONS="get_api_keys get_service_api_keys get_custom_roles get_users get_user_policies
get_mfa get_regions get_floating_IPs get_VSIs get_schematics get_clusters get_databases
get_buckets get_buckets_files get_security_groups get_load_balancers get_code_engine
download_buckets_files search_buckets_file_names"

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [ACTION] [-h] [-o OUTPUT_DIR] [-v] [-d] [-p PARALLEL] [-n LIST_ITEMS] [-m MAX_ITEMS] [-f] [-s]"
    echo
    echo "Arguments:"
    echo "  ACTION          (optional) Run only one module instead of all, e.g.:"
    echo "                    get_api_keys | get_service_api_keys | get_custom_roles | get_users"
    echo "                    get_user_policies | get_mfa | get_regions | get_floating_IPs | get_VSIs"
    echo "                    get_schematics | get_clusters | get_databases | get_buckets"
    echo "                    get_buckets_files | get_security_groups | get_load_balancers | get_code_engine"
    echo "                    download_buckets_files | search_buckets_file_names"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: time-bound 'output_YYYYMMDD_HHMMSS')"
    echo "  -v              Enable debug mode for all scripts"
    echo "  -d              Enable full debug mode (requires -v, for scripts that support it)"
    echo "  -p PARALLEL     Number of parallel workers for get_users.sh and get_service_api_keys.sh (default: 10)"
    echo "  -n LIST_ITEMS   Maximum file keys to list per bucket in get_buckets_files (default: 100)"
    echo "  -q LIST_PARALLEL  Parallel workers for get_buckets_files listing (default: 10)"
    echo "  -m MAX_ITEMS    Maximum number of files to download per bucket (required to enable downloading)"
    echo "  -f              Flatten downloaded files (strip directory path, keep only filename)"
    echo "  -s              Search bucket file names for sensitive patterns (opt-in; can be noisy)"
    echo
    echo "This script runs all IBM Cloud enumeration scripts."
    echo
    echo "Scripts with debug support (-v): All scripts"
    echo "Scripts with full debug support (-d): get_custom_roles, get_users, get_user_policies,"
    echo "                                      get_mfa, get_clusters, get_code_engine"
    echo "Scripts with parallel support (-p): get_users, get_service_api_keys"
    echo "Listing options (-n, -q): get_buckets_files"
    echo "Download options (-m, -f): download_buckets_files"
    echo "Search options (-s): search_buckets_file_names"
}

# If first argument looks like an action name (no leading -), capture it
if [[ $# -gt 0 && "$1" != -* ]]; then
    ACTION="$1"
    shift
fi

while getopts ":ho:p:n:q:m:vdfs" opt; do
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
        n)
            MAX_LIST_ITEMS="$OPTARG"
            ;;
        q)
            LIST_PARALLEL="$OPTARG"
            ;;
        m)
            MAX_DOWNLOAD_ITEMS="$OPTARG"
            ;;
        f)
            FLATTEN_DOWNLOADS=true
            ;;
        s)
            SEARCH_FILE_NAMES=true
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
# Shift past all recognised options; anything remaining is module-specific extra flags.
# These are passed straight through to the module in single-action mode.
shift $((OPTIND - 1))
MODULE_EXTRA_ARGS=("$@")

# Check if -d is used without -v
if [ "$DEBUG_FULL" = true ] && [ "$DEBUG" = false ]; then
    echo "Error: -d flag requires -v flag to be set" >&2
    usage
    exit 1
fi

# Default to a time-bound output folder (e.g. output_20261026_082939) so runs never overwrite each other
if [ "$OUTPUT_DIR_SET" != true ]; then
    OUTPUT_DIR="output_$(date +%Y%m%d_%H%M%S)"
    OUTPUT_DIR_SET=true
fi

echo -e "$BANNER"
require_ibmcloud_login

# Build flag arrays
COMMON_FLAGS=""
if [ "$OUTPUT_DIR_SET" = true ]; then
    COMMON_FLAGS="-o $OUTPUT_DIR"
fi
if [ "$DEBUG" = true ]; then
    COMMON_FLAGS="$COMMON_FLAGS -v"
fi
FULL_DEBUG_FLAGS="$COMMON_FLAGS"
if [ "$DEBUG_FULL" = true ]; then
    FULL_DEBUG_FLAGS="$FULL_DEBUG_FLAGS -d"
fi

# Helper: print the command then run it
run_script() {
    echo -e "\n${CYAN}${BOLD}>>>${RESET} $*"
    "$@"
}

# ── Single-action mode ─────────────────────────────────────────────────────────
if [[ -n "$ACTION" ]]; then
    # Validate action name
    if ! echo "$VALID_ACTIONS" | tr ' \n' '\n' | grep -qx "$ACTION"; then
        echo "Error: unknown action '$ACTION'" >&2
        echo "Available actions: $(echo $VALID_ACTIONS | tr '\n' ' ')" >&2
        exit 1
    fi

    # Show IBM Cloud account info
    ACCOUNT_JSON=$(ibmcloud account show --output json 2>/dev/null)
    TARGET_JSON=$(ibmcloud target --output json 2>/dev/null)
    ACCOUNT_NAME=$(echo "$ACCOUNT_JSON"  | jq -r '.name // "-"' 2>/dev/null || echo "-")
    ACCOUNT_ID=$(echo "$ACCOUNT_JSON"    | jq -r '.account_id // "-"' 2>/dev/null || echo "-")
    SOFTLAYER_ID=$(echo "$ACCOUNT_JSON"  | jq -r '.ims_account_id // "-"' 2>/dev/null || echo "-")
    USER_EMAIL=$(echo "$TARGET_JSON"     | jq -r '.user.user_email // "-"' 2>/dev/null || echo "-")
    echo -e "${ORANGE}${BOLD}IBM Cloud Account:${RESET}"
    echo -e "· ${BOLD}Account Name:${RESET} $ACCOUNT_NAME"
    echo -e "· ${BOLD}Account ID / Softlayer Account:${RESET} $ACCOUNT_ID - $SOFTLAYER_ID"
    echo -e "· ${BOLD}User Email:${RESET} $USER_EMAIL"
    echo

    # Pass through runner-level flags (-o, -v) and any extra module-specific
    # flags the user typed after ACTION (e.g. -p 20 -m 50).
    PASSTHROUGH=($COMMON_FLAGS "${MODULE_EXTRA_ARGS[@]}")
    run_script "$srcdir/${ACTION}.sh" "${PASSTHROUGH[@]}"

    echo " "
    echo "${SEPARATOR}"
    if [ "$OUTPUT_DIR_SET" = true ]; then
        echo -e "Results saved to folder ${BOLD}${OUTPUT_DIR}${RESET}"
    else
        echo -e "Results saved to default folder ${BOLD}output${RESET}"
    fi
    echo " "
    exit 0
fi

# ── Full-run mode ──────────────────────────────────────────────────────────────
require_ibmcloud_jq
require_ibmcloud_cdb
require_ibmcloud_is
require_ibmcloud_schematics
require_ibmcloud_cos
require_ibmcloud_sl
require_ibmcloud_ce
require_curl
# Create output directory only if explicitly set
if [ "$OUTPUT_DIR_SET" = true ]; then
    if [ ! -d "$OUTPUT_DIR" ]; then
        mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
    fi
fi
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
# get_api_keys.sh: supports -v only
run_script "$srcdir/get_api_keys.sh" $COMMON_FLAGS
# get_service_api_keys.sh: supports -v and -p
run_script "$srcdir/get_service_api_keys.sh" $COMMON_FLAGS -p $PARALLEL_WORKERS
# get_custom_roles.sh: supports -v and -d
run_script "$srcdir/get_custom_roles.sh" $FULL_DEBUG_FLAGS
# get_users.sh: supports -v, -d, and -p
run_script "$srcdir/get_users.sh" $FULL_DEBUG_FLAGS -p $PARALLEL_WORKERS
# get_user_policies.sh: supports -v and -d
run_script "$srcdir/get_user_policies.sh" $FULL_DEBUG_FLAGS
# get_mfa.sh: supports -v and -d
run_script "$srcdir/get_mfa.sh" $FULL_DEBUG_FLAGS
# get_regions.sh: supports -v only
run_script "$srcdir/get_regions.sh" $COMMON_FLAGS
# get_floating_IPs.sh: supports -v only
run_script "$srcdir/get_floating_IPs.sh" $COMMON_FLAGS
# get_VSIs.sh: supports -v only
run_script "$srcdir/get_VSIs.sh" $COMMON_FLAGS
# get_schematics.sh: supports -v only (has -r but we use defaults)
run_script "$srcdir/get_schematics.sh" $COMMON_FLAGS
# get_clusters.sh: supports -v and -d
run_script "$srcdir/get_clusters.sh" $FULL_DEBUG_FLAGS
# get_databases.sh: supports -v only
run_script "$srcdir/get_databases.sh" $COMMON_FLAGS
# get_buckets.sh: supports -v only
run_script "$srcdir/get_buckets.sh" $COMMON_FLAGS
# get_security_groups.sh: supports -v only
run_script "$srcdir/get_security_groups.sh" $COMMON_FLAGS
# get_load_balancers.sh: supports -v only
run_script "$srcdir/get_load_balancers.sh" $COMMON_FLAGS
# get_code_engine.sh: supports -v and -d
run_script "$srcdir/get_code_engine.sh" $FULL_DEBUG_FLAGS
# get_buckets_files.sh: list file keys per bucket (default: -n 100 keys, -q 10 workers)
run_script "$srcdir/get_buckets_files.sh" $COMMON_FLAGS -m $MAX_LIST_ITEMS -p $LIST_PARALLEL
# search_buckets_file_names.sh: opt-in only (-s flag), can be noisy
if [ "$SEARCH_FILE_NAMES" = true ]; then
    run_script "$srcdir/search_buckets_file_names.sh" $COMMON_FLAGS
else
    echo " "
    echo "${SEPARATOR}"
    echo -e "${CYAN}Skipping bucket file name search.${RESET}"
    scriptname=$(basename "$0")
    echo -e "To search bucket file names for sensitive patterns, re-run with ${BOLD}-s${RESET}:"
    echo -e "  ${BOLD}./$scriptname -s${RESET}"
fi
# download_buckets_files.sh: runs last, only when -m is explicitly provided
if [[ -n "$MAX_DOWNLOAD_ITEMS" ]]; then
    DOWNLOAD_FLAGS="$COMMON_FLAGS -m $MAX_DOWNLOAD_ITEMS"
    if [ "$FLATTEN_DOWNLOADS" = true ]; then
        DOWNLOAD_FLAGS="$DOWNLOAD_FLAGS -f"
    fi
    run_script "$srcdir/download_buckets_files.sh" $DOWNLOAD_FLAGS
else
    echo " "
    echo "${SEPARATOR}"
    echo -e "${CYAN}Skipping bucket file download.${RESET}"
    echo -e "To download files from Object Storage buckets, re-run with ${BOLD}-m MAX_ITEMS${RESET}:"
    scriptname=$(basename "$0")
    echo -e "  ${BOLD}./$scriptname -m 10${RESET}   (download up to 10 files per bucket)"
    echo -e "  Add ${BOLD}-f${RESET} to flatten paths (keep only filename)."
    echo -e "  Add ${BOLD}-n N${RESET} to change the listing limit (current: ${BOLD}${MAX_LIST_ITEMS}${RESET} keys per bucket)."
    echo -e "  Add ${BOLD}-q N${RESET} to change bucket-listing workers (current: ${BOLD}${LIST_PARALLEL}${RESET})."
fi
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
    echo -e "  Bucket file listing: ${BOLD}${MAX_LIST_ITEMS}${RESET} keys per bucket, ${BOLD}${LIST_PARALLEL}${RESET} parallel worker(s)"
    if [ "$SEARCH_FILE_NAMES" = true ]; then
        echo -e "  Bucket file name search: ${BOLD}enabled${RESET}"
    fi
    if [[ -n "$MAX_DOWNLOAD_ITEMS" ]]; then
        echo -e "  Max download items per bucket: ${BOLD}$MAX_DOWNLOAD_ITEMS${RESET}"
    fi
    if [ "$FLATTEN_DOWNLOADS" = true ]; then
        echo -e "  Flatten downloads: ${BOLD}enabled${RESET}"
    fi
fi
echo " "