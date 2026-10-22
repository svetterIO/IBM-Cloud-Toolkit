#!/usr/bin/env bash

# get_buckets_files.sh
#
# This script enumerates all files in all IBM Cloud Object Storage buckets.
# Bucket listings are fetched in parallel (default: 10 workers) to speed up
# accounts with many buckets.
#
# For each bucket it outputs a section:
#   ## Bucket <service_instance_name>/<bucket_name> ##
#   <File list or "(No files found)">
#
# Requires: IBM Cloud CLI and jq.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
OUTPUT_FILE="buckets_files.txt"
DEBUG=false
MAX_ITEMS=100
MAX_PARALLEL=10

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-f OUTPUT_FILE] [-m MAX_ITEMS] [-p MAX_PARALLEL] [-v]"
    echo
    echo "Options:"
    echo "  -h               Show this help message"
    echo "  -o OUTPUT_DIR    Specify the output folder for results (default: 'output')"
    echo "  -f OUTPUT_FILE   Specify the output file name (default: 'buckets_files.txt')"
    echo "  -m MAX_ITEMS     Maximum number of object keys to retrieve per bucket (default: 100)"
    echo "  -p MAX_PARALLEL  Number of parallel workers for bucket listing (default: 10)"
    echo "  -v               Enable debug mode (outputs ibmcloud commands)"
    echo
    echo "This script lists all files in all IBM Cloud Object Storage buckets in the account."
}

while getopts ":ho:f:m:p:v" opt; do
    case $opt in
        h)  usage; exit 0 ;;
        o)  OUTPUT_DIR="$OPTARG" ;;
        f)  OUTPUT_FILE="$OPTARG" ;;
        m)  MAX_ITEMS="$OPTARG" ;;
        p)  MAX_PARALLEL="$OPTARG" ;;
        v)  DEBUG=true ;;
        \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
        :)  echo "Option -$OPTARG requires an argument." >&2; usage; exit 1 ;;
    esac
done

require_ibmcloud_jq
require_ibmcloud_cos
require_ibmcloud_login

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_FILE}"
: > "$OUTPUT_PATH" || failure "Error while creating the output file: ${BOLD}$OUTPUT_PATH${RESET}"

echo " "
echo "${SEPARATOR}"
echo -e "Enumerating ${ORANGE}${BOLD}files${RESET} in all IBM Cloud Object Storage buckets (using ${MAX_PARALLEL} parallel workers)..."
echo " "

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud resource service-instances --service-name cloud-object-storage --all-resource-groups --output json"
fi

INSTANCES_JSON=$(ibmcloud resource service-instances \
    --service-name cloud-object-storage \
    --all-resource-groups \
    --output json 2>&1) || true

if [[ -z "${INSTANCES_JSON:-}" || "$INSTANCES_JSON" == "[]" || "$INSTANCES_JSON" == "null" ]]; then
    failure "Failed to retrieve Cloud Object Storage service instances."
fi
if ! echo "$INSTANCES_JSON" | jq empty 2>/dev/null; then
    failure "Failed to parse COS instances response."
fi

# ── Build flat list of all buckets across all instances ───────────────────────
# Each entry is: <index>|<instance_name>|<bucket_name>|<bucket_region>
BUCKET_LIST=()
BUCKET_INDEX=0

while IFS= read -r instance; do
    INSTANCE_NAME=$(echo "$instance" | jq -r '.name')
    INSTANCE_CRN=$(echo "$instance"  | jq -r '.crn')

    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Running: ibmcloud cos buckets-extended --ibm-service-instance-id \"$INSTANCE_CRN\" --output json"
    fi

    BUCKETS_JSON=$(ibmcloud cos buckets-extended \
        --ibm-service-instance-id "$INSTANCE_CRN" \
        --output json 2>&1) || true

    if [[ -z "${BUCKETS_JSON:-}" || "$BUCKETS_JSON" == "null" ]] || \
       ! echo "$BUCKETS_JSON" | jq empty 2>/dev/null || \
       [[ $(echo "$BUCKETS_JSON" | jq '.Buckets == null') == "true" ]]; then
        continue
    fi

    while IFS= read -r bucket; do
        BNAME=$(echo "$bucket"   | jq -r '.Name')
        BREGION=$(echo "$bucket" | jq -r '.LocationConstraint')
        BUCKET_LIST+=("${BUCKET_INDEX}|${INSTANCE_NAME}|${BNAME}|${BREGION}")
        BUCKET_INDEX=$((BUCKET_INDEX + 1))
    done < <(echo "$BUCKETS_JSON" | jq -c '.Buckets[]')

done < <(echo "$INSTANCES_JSON" | jq -c '.[]')

TOTAL_BUCKETS=${#BUCKET_LIST[@]}
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $TOTAL_BUCKETS bucket(s) across all instances"
fi

echo -e "${BOLD}Total buckets found: ${TOTAL_BUCKETS}${RESET}"

if [ "$TOTAL_BUCKETS" -eq 0 ]; then
    echo "No buckets found."
    echo " "
    echo -e "All bucket file listings saved to: ${BOLD}${OUTPUT_PATH}${RESET}"
    print_console_link "IBM Cloud Object Storage" "https://cloud.ibm.com/objectstorage/instances"
    exit 0
fi

echo "Listing objects in $TOTAL_BUCKETS bucket(s) with $MAX_PARALLEL parallel worker(s)..."

# ── Parallel listing using background jobs + temp files ───────────────────────
# Each worker writes its result to a numbered temp file so output can be
# reassembled in the original bucket order after all jobs finish.

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Worker function: list one bucket and write result to $TEMP_DIR/<index>.txt
_list_bucket() {
    local idx="$1" inst_name="$2" bname="$3" bregion="$4"
    local out_file="${TEMP_DIR}/${idx}.txt"

    printf '## Bucket %s/%s ##\n' "$inst_name" "$bname" > "$out_file"

    local files_json
    files_json=$(ibmcloud cos list-objects-v2 \
        --bucket "$bname" \
        --region "$bregion" \
        --max-items "$MAX_ITEMS" \
        --output json 2>/dev/null) || true

    if [[ -z "${files_json:-}" || "$files_json" == "null" ]] || \
       ! echo "$files_json" | jq empty 2>/dev/null || \
       [[ $(echo "$files_json" | jq '.KeyCount == 0') == "true" ]]; then
        echo "(No files found)" >> "$out_file"
    else
        local count is_truncated
        count=$(echo "$files_json"       | jq -r '.Contents | length')
        is_truncated=$(echo "$files_json" | jq -r '.IsTruncated // false')
        if [[ "$is_truncated" == "true" ]]; then
            echo "(Showing first ${MAX_ITEMS} of more objects)" >> "$out_file"
        fi
        echo "$files_json" | jq -r '.Contents[].Key' >> "$out_file"
    fi
    echo >> "$out_file"   # blank separator line
}
export -f _list_bucket
export TEMP_DIR MAX_ITEMS

RUNNING=0
for entry in "${BUCKET_LIST[@]}"; do
    IFS='|' read -r idx inst_name bname bregion <<< "$entry"
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Listing bucket: $bname (region: $bregion)"
    fi
    _list_bucket "$idx" "$inst_name" "$bname" "$bregion" &
    RUNNING=$((RUNNING + 1))
    # When the worker pool is full, wait for at least one to finish
    if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
        wait -n 2>/dev/null || wait   # wait -n requires bash 4.3+; fall back gracefully
        RUNNING=$((RUNNING - 1))
    fi
done
# Wait for all remaining workers
wait

# ── Reassemble output in original bucket order ────────────────────────────────
TOTAL_FILES=0
for (( i=0; i<TOTAL_BUCKETS; i++ )); do
    temp_file="${TEMP_DIR}/${i}.txt"
    if [ -f "$temp_file" ]; then
        cat "$temp_file" >> "$OUTPUT_PATH"
        # Count non-header, non-empty, non-marker lines as files
        count=$(grep -v '^##\|^(\|^$' "$temp_file" 2>/dev/null | wc -l || echo 0)
        TOTAL_FILES=$((TOTAL_FILES + count))
    fi
done

if [ "$DEBUG" = true ]; then
    echo " "
    echo -e "${BOLD}[DEBUG]${RESET} Total buckets: $TOTAL_BUCKETS"
    echo -e "${BOLD}[DEBUG]${RESET} Total files listed: $TOTAL_FILES"
fi

echo " "
echo -e "All bucket file listings saved to: ${BOLD}${OUTPUT_PATH}${RESET}"
print_console_link "IBM Cloud Object Storage" "https://cloud.ibm.com/objectstorage/instances"
