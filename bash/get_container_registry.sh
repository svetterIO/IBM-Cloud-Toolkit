#!/usr/bin/env bash

# get_container_registry.sh
#
# Enumerates IBM Cloud Container Registry namespaces, images, and Vulnerability
# Advisor scan results.
# Flags images that have CVEs reported by the Vulnerability Advisor.
#
# Output files:
#   <output_dir>/cr_namespaces.json   – all registry namespaces
#   <output_dir>/cr_images.json       – all images (digest, tags, size)
#   <output_dir>/cr_vulnerable.json   – images with CVEs (when found)
#
# Requires IBM Cloud CLI and the container-registry ("cr") plugin.
# Requires jq for JSON processing.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
OUTPUT_FILE="cr_images.json"
DEBUG=false

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-f OUTPUT_FILE] [-v]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: 'output')"
    echo "  -f OUTPUT_FILE  Specify the output file name for images (default: 'cr_images.json')"
    echo "  -v              Enable debug mode (outputs commands)"
    echo
    echo "This script enumerates IBM Cloud Container Registry namespaces, images,"
    echo "and Vulnerability Advisor scan results."
}

while getopts ":ho:f:v" opt; do
    case $opt in
        h)
            usage
            exit 0
            ;;
        o)
            OUTPUT_DIR="$OPTARG"
            ;;
        f)
            OUTPUT_FILE="$OPTARG"
            ;;
        v)
            DEBUG=true
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

require_ibmcloud_jq
require_ibmcloud_login
require_ibmcloud_cr

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

NS_OUTPUT_PATH="${OUTPUT_DIR}/cr_namespaces.json"
IMAGES_OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_FILE}"
VULN_OUTPUT_PATH="${OUTPUT_DIR}/cr_vulnerable.json"

echo " "
echo "${SEPARATOR}"
echo -e "Enumerating IBM Cloud ${ORANGE}${BOLD}Container Registry${RESET}..."
echo " "

# ── Namespaces ────────────────────────────────────────────────────────────────
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cr namespace-list --output json"
fi

NS_STDERR=$(mktemp)
if NS_JSON=$(ibmcloud cr namespace-list --output json 2>"$NS_STDERR"); then
    if ! printf '%s' "$NS_JSON" | jq '.' >/dev/null 2>&1; then
        mv "$NS_STDERR" "$OUTPUT_DIR/cr_namespaces.stderr"
        warning "Container Registry namespace-list returned invalid JSON. See $OUTPUT_DIR/cr_namespaces.stderr"
        NS_JSON='[]'
    else
        rm -f "$NS_STDERR"
        [ "$NS_JSON" = "null" ] && NS_JSON='[]'
    fi
else
    mv "$NS_STDERR" "$OUTPUT_DIR/cr_namespaces.stderr"
    warning "Failed to retrieve CR namespaces. See $OUTPUT_DIR/cr_namespaces.stderr"
    NS_JSON='[]'
fi

NS_COUNT=$(printf '%s' "$NS_JSON" | jq 'length')
echo -e "${BOLD}Total namespaces found: $NS_COUNT${RESET}"

if [ "$NS_COUNT" -gt 0 ]; then
    printf '%s' "$NS_JSON" | jq '.' > "$NS_OUTPUT_PATH"
    echo -e "${BOLD}Namespaces:${RESET}"
    while IFS= read -r ns; do
        ns_name=$(printf '%s' "$ns" | jq -r '.name // .Name // "unknown"')
        ns_rg=$(printf '%s' "$ns" | jq -r '.resource_group_name // .ResourceGroupName // "-"')
        echo "  - $ns_name  (resource group: $ns_rg)"
    done < <(printf '%s' "$NS_JSON" | jq -c '.[]')
    echo -e "Namespaces saved to: ${BOLD}${NS_OUTPUT_PATH}${RESET}"
else
    echo "No namespaces found."
fi

echo " "

# ── Images ────────────────────────────────────────────────────────────────────
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cr image-list --output json"
fi

IMG_STDERR=$(mktemp)
if IMG_JSON=$(ibmcloud cr image-list --output json 2>"$IMG_STDERR"); then
    if ! printf '%s' "$IMG_JSON" | jq '.' >/dev/null 2>&1; then
        mv "$IMG_STDERR" "$OUTPUT_DIR/cr_images.stderr"
        warning "Container Registry image-list returned invalid JSON. See $OUTPUT_DIR/cr_images.stderr"
        IMG_JSON='[]'
    else
        rm -f "$IMG_STDERR"
        [ "$IMG_JSON" = "null" ] && IMG_JSON='[]'
    fi
else
    mv "$IMG_STDERR" "$OUTPUT_DIR/cr_images.stderr"
    warning "Failed to retrieve CR images. See $OUTPUT_DIR/cr_images.stderr"
    IMG_JSON='[]'
fi

IMG_COUNT=$(printf '%s' "$IMG_JSON" | jq 'length')
echo -e "${BOLD}Total images found: $IMG_COUNT${RESET}"

if [ "$IMG_COUNT" -gt 0 ]; then
    printf '%s' "$IMG_JSON" | jq '.' > "$IMAGES_OUTPUT_PATH"
    echo -e "${BOLD}Images:${RESET}"
    while IFS= read -r img; do
        repo=$(printf '%s' "$img" | jq -r '.Repository // ""')
        tag=$(printf '%s' "$img" | jq -r '.Tag // ""')
        if [ -n "$repo" ]; then
            tag_str="${repo}:${tag}"
        else
            tag_str=$(printf '%s' "$img" | jq -r '.Digest // "unknown"')
        fi
        img_size=$(printf '%s' "$img" | jq -r '.Size // 0')
        echo "  - $tag_str  (size: $img_size bytes)"
    done < <(printf '%s' "$IMG_JSON" | jq -c '.[]')
    echo -e "All images saved to: ${BOLD}${IMAGES_OUTPUT_PATH}${RESET}"
else
    echo "No images found."
fi

echo " "

if [ "$IMG_COUNT" -eq 0 ]; then
    print_console_link "Manage Container Registry" "https://cloud.ibm.com/registry/images" \
        "IBM Cloud Console > Container Registry > Images"
    exit 0
fi

# ── Security Status (inline in image-list response) ───────────────────────────
# ibmcloud cr image-list already embeds SecurityStatus per image.
echo -e "Analysing ${BOLD}Security Status${RESET} from image list..."

# Images with IssueCount > 0
VULN_JSON=$(printf '%s' "$IMG_JSON" | jq '[.[] | select((.SecurityStatus.IssueCount // 0) > 0)]')
VULN_COUNT=$(printf '%s' "$VULN_JSON" | jq 'length')

# Images still scanning
SCANNING_COUNT=$(printf '%s' "$IMG_JSON" | jq '[.[] | select(.SecurityStatus.Status // "" | startswith("Scanning"))] | length')

# Clean images
OK_COUNT=$(printf '%s' "$IMG_JSON" | jq '[.[] | select(.SecurityStatus.Status == "Complete" and (.SecurityStatus.IssueCount // 0) == 0)] | length')

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} With issues: $VULN_COUNT  Scanning: $SCANNING_COUNT  Clean: $OK_COUNT"
fi

if [ "$VULN_COUNT" -gt 0 ]; then
    printf '%s' "$VULN_JSON" | jq '.' > "$VULN_OUTPUT_PATH"
    echo " "
    echo -e "${YELLOW}${BOLD}Warning:${RESET} ${VULN_COUNT} image(s) with security issues found"
    echo -e "Vulnerable images saved to: ${BOLD}${VULN_OUTPUT_PATH}${RESET}"
    while IFS= read -r v; do
        v_repo=$(printf '%s' "$v" | jq -r '.Repository // ""')
        v_tag=$(printf '%s' "$v" | jq -r '.Tag // ""')
        if [ -n "$v_repo" ]; then
            v_label="${v_repo}:${v_tag}"
        else
            v_label=$(printf '%s' "$v" | jq -r '.Digest // "unknown"')
        fi
        v_issues=$(printf '%s' "$v" | jq -r '.SecurityStatus.IssueCount // "?"')
        v_exempt=$(printf '%s' "$v" | jq -r '.SecurityStatus.ExemptionCount // 0')
        v_status=$(printf '%s' "$v" | jq -r '.SecurityStatus.Status // "?"')
        echo "  - $v_label  (issues: $v_issues, exemptions: $v_exempt, status: $v_status)"
    done < <(printf '%s' "$VULN_JSON" | jq -c '.[]')
else
    echo -e "${BOLD}Images with security issues: 0${RESET}"
fi

if [ "$SCANNING_COUNT" -gt 0 ]; then
    echo " "
    echo -e "${YELLOW}${BOLD}Note:${RESET} $SCANNING_COUNT image(s) still being scanned — re-run later for full results"
fi

print_console_link "Manage Container Registry" "https://cloud.ibm.com/registry/images" \
    "IBM Cloud Console > Container Registry > Images"
