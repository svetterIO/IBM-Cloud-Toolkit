#!/usr/bin/env bash

# download_buckets_files.sh
#
# Downloads files from all IBM Cloud Object Storage buckets.
# Supports optional flattening of output filenames (strip path components).
#
# A manifest file (_path_manifest.json) is written next to the download folder.
# Each entry records: instance, bucket, region, endpoint_region, original_key,
# local_path, browser_url, and public (whether the object is publicly accessible).
#
# Requires: IBM Cloud CLI and jq.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

# Define additional colors if not in utils.sh
GREEN="${GREEN:-\033[32m}"
RED="${RED:-\033[31m}"
OUTPUT_DIR="output/bucket_files"
DEBUG=false
MAX_ITEMS=10
OVERWRITE=false
FLATTEN=false

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-v] [-m MAX_ITEMS] [-y] [-f]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for downloads (default: 'output/bucket_files')"
    echo "  -v              Enable debug mode (show commands being run)"
    echo "  -m MAX_ITEMS    Number of objects to list per bucket (default: 10)"
    echo "  -y              Overwrite files if they already exist"
    echo "  -f              Flatten output (use only the filename from object key)"
    echo
    echo "This script downloads all files from all IBM Cloud Object Storage buckets."
}

while getopts ":ho:vm:yf" opt; do
    case $opt in
        h) usage; exit 0 ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        v) DEBUG=true ;;
        m) MAX_ITEMS="$OPTARG" ;;
        y) OVERWRITE=true ;;
        f) FLATTEN=true ;;
        \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
        :) echo "Option -$OPTARG requires an argument." >&2; usage; exit 1 ;;
    esac
done

require_ibmcloud_jq
require_ibmcloud_cos
require_ibmcloud_login

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

# Strip storage-class suffix from a COS LocationConstraint to get the bare
# region used in public S3 endpoint hostnames.
# e.g. "us-south-smart" -> "us-south", "eu-de-standard" -> "eu-de"
location_to_endpoint_region() {
    echo "$1" | sed -E 's/-(standard|smart|vault|cold|flex|onerate_active|active)$//I'
}

# Build the HTTPS browser URL for a COS object.
# $1 = endpoint_region (bare, e.g. "us-south")
# $2 = bucket name
# $3 = object key (will be URL-encoded)
cos_browser_url() {
    local region="$1" bucket="$2" key="$3"
    local encoded_key
    encoded_key=$(printf '%s' "$key" | python3 -c "import sys,urllib.parse; print(urllib.parse.quote(sys.stdin.read(),safe=''))" 2>/dev/null \
        || printf '%s' "$key" | sed 's/ /%20/g')
    echo "https://s3.${region}.cloud-object-storage.appdomain.cloud/${bucket}/${encoded_key}"
}

# Check if a COS object is publicly accessible (no auth needed).
# Returns 0 (true) if HTTP 200, 1 (false) otherwise.
is_object_public() {
    local url="$1"
    local http_code
    if command -v curl &>/dev/null; then
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 --head "$url" 2>/dev/null)
        [[ "$http_code" == "200" ]]
    else
        return 1
    fi
}

# Manifest: path of the JSON file that maps COS keys -> local paths + URLs
MANIFEST_PATH="${OUTPUT_DIR%/}_path_manifest.json"
MANIFEST_ENTRIES="[]"

echo " "
echo "${SEPARATOR}"
echo -e "Downloading ${ORANGE}${BOLD}files${RESET} from all IBM Cloud Object Storage buckets..."
echo " "

# Counters
TOTAL_INSTANCES=0
TOTAL_BUCKETS=0
TOTAL_FILES=0
DOWNLOADED_FILES=0
SKIPPED_FILES=0
FAILED_FILES=0

# Debug output
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Output directory: $OUTPUT_DIR"
    echo -e "${BOLD}[DEBUG]${RESET} Max items per bucket: $MAX_ITEMS"
    echo -e "${BOLD}[DEBUG]${RESET} Overwrite mode: $OVERWRITE"
    echo -e "${BOLD}[DEBUG]${RESET} Flatten mode: $FLATTEN"
    echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud resource service-instances --service-name cloud-object-storage --output json"
fi

INSTANCES_JSON=$(ibmcloud resource service-instances --service-name cloud-object-storage --output json 2>&1) || true
EXIT_CODE=$?

# Validate JSON
if ! echo "$INSTANCES_JSON" | jq empty 2>/dev/null; then
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Invalid JSON response"
        echo -e "${BOLD}[DEBUG]${RESET} Response: $INSTANCES_JSON"
    fi
    failure "Failed to retrieve valid JSON for Cloud Object Storage service instances."
fi

if [ $EXIT_CODE -ne 0 ] || [[ "$INSTANCES_JSON" =~ "FAILED" ]]; then
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Command failed"
    fi
    failure "Failed to retrieve Cloud Object Storage service instances."
fi

if [[ -z "${INSTANCES_JSON:-}" || "$INSTANCES_JSON" == "[]" || "$INSTANCES_JSON" == "null" ]]; then
    echo "No Cloud Object Storage service instances found."
    exit 0
fi

TOTAL_INSTANCES=$(echo "$INSTANCES_JSON" | jq 'length')
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $TOTAL_INSTANCES COS instance(s)"
fi

echo -e "${BOLD}Cloud Object Storage instances: $TOTAL_INSTANCES${RESET}"
echo " "
while IFS= read -r instance; do 
    INSTANCE_NAME=$(echo "$instance" | jq -r '.name')
    INSTANCE_CRN=$(echo "$instance" | jq -r '.crn')
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Processing instance: $INSTANCE_NAME"
        echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cos buckets-extended --ibm-service-instance-id \"$INSTANCE_CRN\" --output json"
    fi
    BUCKETS_JSON=$(ibmcloud cos buckets-extended --ibm-service-instance-id "$INSTANCE_CRN" --output json 2>&1) || true
    # Validate JSON
    if ! echo "$BUCKETS_JSON" | jq empty 2>/dev/null; then
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} Invalid JSON response for instance: $INSTANCE_NAME"
        fi
        warning "Failed to retrieve buckets for instance: $INSTANCE_NAME"
        continue
    fi
    if [[ -z "${BUCKETS_JSON:-}" || "$BUCKETS_JSON" == "null" || $(echo "$BUCKETS_JSON" | jq '.Buckets == null') == "true" ]]; then
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} No buckets in instance: $INSTANCE_NAME"
        fi
        continue
    fi
    BUCKET_COUNT=$(echo "$BUCKETS_JSON" | jq '.Buckets | length')
    TOTAL_BUCKETS=$((TOTAL_BUCKETS + BUCKET_COUNT))
    echo -e "Processing instance: ${BOLD}$INSTANCE_NAME${RESET} ($BUCKET_COUNT bucket(s))"
    while IFS= read -r bucket; do
        BUCKET_NAME=$(echo "$bucket" | jq -r '.Name')
        BUCKET_REGION=$(echo "$bucket" | jq -r '.LocationConstraint')
        ENDPOINT_REGION=$(location_to_endpoint_region "$BUCKET_REGION")
        echo -e "  Bucket: ${BOLD}$BUCKET_NAME${RESET} (Region: $BUCKET_REGION)"
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cos list-objects-v2 --max-items $MAX_ITEMS --bucket \"$BUCKET_NAME\" --region \"$BUCKET_REGION\" --output json"
        fi
        FILES_JSON=$(ibmcloud cos list-objects-v2 --max-items "$MAX_ITEMS" --bucket "$BUCKET_NAME" --region "$BUCKET_REGION" --output json 2>&1) || true
        # Validate JSON
        if ! echo "$FILES_JSON" | jq empty 2>/dev/null; then
            if [ "$DEBUG" = true ]; then
                echo -e "${BOLD}[DEBUG]${RESET} Invalid JSON response for bucket: $BUCKET_NAME"
            fi
            warning "Failed to list objects in bucket: $BUCKET_NAME"
            continue
        fi
        if [[ -z "${FILES_JSON:-}" || "$FILES_JSON" == "null" || $(echo "$FILES_JSON" | jq '.KeyCount == 0') == "true" ]]; then
            echo "    (No files found)"
        else
            FILE_COUNT=$(echo "$FILES_JSON" | jq '.Contents | length')
            IS_TRUNCATED=$(echo "$FILES_JSON" | jq -r '.IsTruncated // false')
            TOTAL_FILES=$((TOTAL_FILES + FILE_COUNT))
            echo "    Found $FILE_COUNT file(s)"
            if [[ "$IS_TRUNCATED" == "true" ]]; then
                echo -e "    ${YELLOW}Note: Bucket contains more files than max-items limit${RESET}"
            fi
            while IFS= read -r file_key; do
                if [ "$FLATTEN" = true ]; then
                    base_name=$(basename "$file_key")
                    local_path="${OUTPUT_DIR}/${base_name}"
                else
                    local_path="${OUTPUT_DIR}/${file_key}"
                    mkdir -p "$(dirname "$local_path")" 2>/dev/null || {
                        warning "Cannot create directory for '${file_key}'"
                        FAILED_FILES=$((FAILED_FILES + 1))
                        continue
                    }
                fi
                BROWSER_URL=$(cos_browser_url "$ENDPOINT_REGION" "$BUCKET_NAME" "$file_key")
                # Check if object is publicly accessible
                if is_object_public "$BROWSER_URL"; then
                    IS_PUBLIC="true"
                else
                    IS_PUBLIC="false"
                fi
                # Append to manifest (always, even for skipped/failed)
                ENTRY=$(jq -n \
                    --arg inst "$INSTANCE_NAME" \
                    --arg bkt "$BUCKET_NAME" \
                    --arg reg "$BUCKET_REGION" \
                    --arg ereg "$ENDPOINT_REGION" \
                    --arg key "$file_key" \
                    --arg lp "$local_path" \
                    --arg url "$BROWSER_URL" \
                    --argjson pub "$IS_PUBLIC" \
                    '{instance:$inst,bucket:$bkt,region:$reg,endpoint_region:$ereg,original_key:$key,local_path:$lp,browser_url:$url,public:$pub}')
                MANIFEST_ENTRIES=$(echo "$MANIFEST_ENTRIES" | jq --argjson e "$ENTRY" '. + [$e]')
                if [ "$DEBUG" = true ]; then
                    echo -e "${BOLD}[DEBUG]${RESET} Downloading: $file_key -> $local_path"
                fi
                if [ "$OVERWRITE" = false ] && [ -f "$local_path" ]; then
                    echo -e "    ${CYAN}Skipped (exists):${RESET} $(basename "$file_key")"
                    SKIPPED_FILES=$((SKIPPED_FILES + 1))
                    continue
                fi
                if ibmcloud cos download --bucket "$BUCKET_NAME" --region "$BUCKET_REGION" --key "$file_key" "$local_path" &>/dev/null; then
                    echo "    Downloaded: $(basename "$file_key")"
                    DOWNLOADED_FILES=$((DOWNLOADED_FILES + 1))
                else
                    echo "    Failed: $(basename "$file_key")"
                    FAILED_FILES=$((FAILED_FILES + 1))
                fi
            done < <(echo "$FILES_JSON" | jq -r '.Contents[].Key')
        fi
    done < <(echo "$BUCKETS_JSON" | jq -c '.Buckets[]')
    echo " "
done < <(echo "$INSTANCES_JSON" | jq -c '.[]')

echo "${SEPARATOR}"
echo -e "${BOLD}Download Summary:${RESET}"
echo -e "  COS Instances: ${BOLD}$TOTAL_INSTANCES${RESET}"
echo -e "  Buckets processed: ${BOLD}$TOTAL_BUCKETS${RESET}"
echo -e "  Files found: ${BOLD}$TOTAL_FILES${RESET}"
echo -e "  Files downloaded: ${BOLD}${GREEN}$DOWNLOADED_FILES${RESET}"
echo -e "  Files skipped: ${BOLD}${CYAN}$SKIPPED_FILES${RESET}"

if [ $FAILED_FILES -gt 0 ]; then
    echo -e "  Files failed: ${BOLD}${RED}$FAILED_FILES${RESET}"
fi

echo " "
echo -e "Files saved to: ${BOLD}${OUTPUT_DIR}${RESET}"
# Write manifest if we have entries
if [[ $(echo "$MANIFEST_ENTRIES" | jq 'length') -gt 0 ]]; then
    echo "$MANIFEST_ENTRIES" | jq '.' > "$MANIFEST_PATH"
    echo -e "Path manifest:  ${BOLD}${MANIFEST_PATH}${RESET}"
    echo -e "  (maps original COS keys -> local paths + browser URLs)"
fi
if [ "$DEBUG" = true ]; then
    echo " "
    echo -e "${BOLD}[DEBUG]${RESET} Summary:"
    echo -e "${BOLD}[DEBUG]${RESET}   Total instances: $TOTAL_INSTANCES"
    echo -e "${BOLD}[DEBUG]${RESET}   Total buckets: $TOTAL_BUCKETS"
    echo -e "${BOLD}[DEBUG]${RESET}   Total files: $TOTAL_FILES"
    echo -e "${BOLD}[DEBUG]${RESET}   Downloaded: $DOWNLOADED_FILES"
    echo -e "${BOLD}[DEBUG]${RESET}   Skipped: $SKIPPED_FILES"
    echo -e "${BOLD}[DEBUG]${RESET}   Failed: $FAILED_FILES"
    echo -e "${BOLD}[DEBUG]${RESET}   Max items per bucket: $MAX_ITEMS"
    echo -e "${BOLD}[DEBUG]${RESET}   Flatten mode: $FLATTEN"
    echo -e "${BOLD}[DEBUG]${RESET}   Overwrite mode: $OVERWRITE"
fi
print_console_link "IBM Cloud Object Storage" "https://cloud.ibm.com/objectstorage/instances"
echo " "