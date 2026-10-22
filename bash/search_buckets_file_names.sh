#!/usr/bin/env bash

# search_buckets_file_names.sh
#
# Scans all IBM Cloud Object Storage bucket file keys for names that suggest
# sensitive content (passwords, credentials, API keys, certificates, etc.).
#
# Bucket listings are fetched in parallel (default: 10 workers).
#
# Output files:
#   <output_dir>/bucket_file_names.json  – JSON array of all matches
#   <output_dir>/bucket_file_names.txt   – human-readable report
#
# Each match record contains: instance, bucket, region, key, matched_keywords.
#
# Requires: IBM Cloud CLI, jq.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
DEBUG=false
MAX_ITEMS=1000
MAX_PARALLEL=10
EXTRA_KEYWORDS=()
CUSTOM_KEYWORDS=()

# ── Default sensitive keyword list ────────────────────────────────────────────
DEFAULT_KEYWORDS=(
    # Credentials & secrets
    "password" "passwd" "pwd" "pass"
    "secret" "secrets"
    "credential" "credentials" "cred" "creds"
    "apikey" "api_key" "api-key"
    "token" "auth_token" "access_token"
    "private_key" "privatekey" "privkey"
    "encryption_key" "enckey"
    # Certificates & PKI
    "certificate" "cert" "certs"
    ".pem" ".p12" ".pfx" ".key" ".crt" ".cer" ".jks" ".keystore"
    # Config & env files
    ".env" "config" "configuration"
    "settings" ".conf" ".cfg" ".ini"
    ".properties" ".yaml" ".yml"
    # Database
    "database" "db_pass" "db_pwd" "dbpassword"
    "connection_string" "dsn"
    # SSH / VPN
    "id_rsa" "id_ed25519" "id_ecdsa" "id_dsa"
    "ssh_key" ".ssh"
    "vpn" "ovpn" ".ovpn"
    # Cloud / IAM
    "iam" "service_account" "serviceaccount"
    "kube_config" "kubeconfig" ".kubeconfig"
    # Generic sensitive names
    "backup" "dump" "export"
    "shadow" "htpasswd" ".htpasswd"
    "wallet"
)

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-m MAX_ITEMS] [-p MAX_PARALLEL] [-k KEYWORD] [-e KEYWORD] [-v]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Output folder (default: 'output')"
    echo "  -m MAX_ITEMS    Maximum object keys to scan per bucket (default: 1000)"
    echo "  -p MAX_PARALLEL Parallel workers for bucket scanning (default: 10)"
    echo "  -k KEYWORD      Override default keywords with this one (repeatable)."
    echo "                  Using -k at least once replaces the entire default list."
    echo "  -e KEYWORD      Extend the default keyword list (repeatable)."
    echo "  -v              Enable debug mode"
    echo
    echo "This script scans all COS bucket file keys for sensitive-looking names."
}

while getopts ":ho:m:p:k:e:v" opt; do
    case $opt in
        h)  usage; exit 0 ;;
        o)  OUTPUT_DIR="$OPTARG" ;;
        m)  MAX_ITEMS="$OPTARG" ;;
        p)  MAX_PARALLEL="$OPTARG" ;;
        k)  CUSTOM_KEYWORDS+=("$OPTARG") ;;
        e)  EXTRA_KEYWORDS+=("$OPTARG") ;;
        v)  DEBUG=true ;;
        \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
        :)  echo "Option -$OPTARG requires an argument." >&2; usage; exit 1 ;;
    esac
done

require_ibmcloud_jq
require_ibmcloud_cos
require_ibmcloud_login

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error creating output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

JSON_PATH="${OUTPUT_DIR}/bucket_file_names.json"
TXT_PATH="${OUTPUT_DIR}/bucket_file_names.txt"

# ── Build effective keyword list ──────────────────────────────────────────────
if [ ${#CUSTOM_KEYWORDS[@]} -gt 0 ]; then
    KEYWORDS=("${CUSTOM_KEYWORDS[@]}")
else
    KEYWORDS=("${DEFAULT_KEYWORDS[@]}")
fi
for kw in "${EXTRA_KEYWORDS[@]}"; do
    KEYWORDS+=("$kw")
done

KEYWORD_COUNT=${#KEYWORDS[@]}

echo " "
echo "${SEPARATOR}"
echo -e "Scanning IBM Cloud Object Storage buckets for ${ORANGE}${BOLD}sensitive file names${RESET}..."
echo " "
KEYWORD_DISPLAY=$(IFS=", "; echo "${KEYWORDS[*]}")
echo -e "${BOLD}Keywords (${KEYWORD_COUNT}):${RESET} ${CYAN}${KEYWORD_DISPLAY}${RESET}"
echo " "

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Running: ibmcloud resource service-instances --service-name cloud-object-storage --all-resource-groups --output json"
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

# ── Build flat bucket list ────────────────────────────────────────────────────
BUCKET_LIST=()
BUCKET_INDEX=0

while IFS= read -r instance; do
    INST_NAME=$(echo "$instance" | jq -r '.name')
    INST_CRN=$(echo "$instance"  | jq -r '.crn')

    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Enumerating buckets for instance: $INST_NAME"
    fi

    BUCKETS_JSON=$(ibmcloud cos buckets-extended \
        --ibm-service-instance-id "$INST_CRN" \
        --output json 2>&1) || true

    if [[ -z "${BUCKETS_JSON:-}" || "$BUCKETS_JSON" == "null" ]] || \
       ! echo "$BUCKETS_JSON" | jq empty 2>/dev/null || \
       [[ $(echo "$BUCKETS_JSON" | jq '.Buckets == null') == "true" ]]; then
        continue
    fi

    while IFS= read -r bucket; do
        BNAME=$(echo "$bucket"   | jq -r '.Name')
        BREGION=$(echo "$bucket" | jq -r '.LocationConstraint')
        BUCKET_LIST+=("${BUCKET_INDEX}|${INST_NAME}|${BNAME}|${BREGION}")
        BUCKET_INDEX=$((BUCKET_INDEX + 1))
    done < <(echo "$BUCKETS_JSON" | jq -c '.Buckets[]')

done < <(echo "$INSTANCES_JSON" | jq -c '.[]')

TOTAL_BUCKETS=${#BUCKET_LIST[@]}
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $TOTAL_BUCKETS bucket(s) across all instances"
fi

echo -e "${BOLD}Total buckets to scan: ${TOTAL_BUCKETS}${RESET}"

if [ "$TOTAL_BUCKETS" -eq 0 ]; then
    echo "No buckets found."
    echo "[]" > "$JSON_PATH"
    echo "No buckets found." > "$TXT_PATH"
    echo " "
    echo -e "Results saved to: ${BOLD}${JSON_PATH}${RESET}"
    print_console_link "IBM Cloud Object Storage" "https://cloud.ibm.com/objectstorage/instances"
    exit 0
fi

echo "Scanning up to ${MAX_ITEMS} keys per bucket with ${MAX_PARALLEL} parallel worker(s)..."
echo " "

# ── Parallel scan using background jobs + temp files ─────────────────────────
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Worker: scan one bucket, write JSON matches to TEMP_DIR/<idx>.json
# Also writes a truncation flag to TEMP_DIR/<idx>.truncated if applicable.
_scan_bucket() {
    local idx="$1" inst_name="$2" bname="$3" bregion="$4"
    local out_file="${TEMP_DIR}/${idx}.json"

    local files_json
    files_json=$(ibmcloud cos list-objects-v2 \
        --bucket "$bname" \
        --region "$bregion" \
        --max-items "$MAX_ITEMS" \
        --output json 2>/dev/null) || true

    if [[ -z "${files_json:-}" || "$files_json" == "null" ]] || \
       ! echo "$files_json" | jq empty 2>/dev/null; then
        echo "[]" > "$out_file"
        return
    fi

    local is_truncated
    is_truncated=$(echo "$files_json" | jq -r '.IsTruncated // false')
    if [[ "$is_truncated" == "true" ]]; then
        touch "${TEMP_DIR}/${idx}.truncated"
    fi

    # For each key, check whether any keyword matches (case-insensitive grep)
    local matches="[]"
    while IFS= read -r key; do
        local matched_kws=()
        for kw in "${KEYWORDS[@]}"; do
            if echo "$key" | grep -qi "$kw"; then
                matched_kws+=("$kw")
            fi
        done
        if [ ${#matched_kws[@]} -gt 0 ]; then
            local kw_json
            kw_json=$(printf '%s\n' "${matched_kws[@]}" | jq -R . | jq -sc .)
            local entry
            entry=$(jq -n \
                --arg inst "$inst_name" \
                --arg bkt "$bname" \
                --arg reg "$bregion" \
                --arg k "$key" \
                --argjson kws "$kw_json" \
                '{instance:$inst,bucket:$bkt,region:$reg,key:$k,matched_keywords:$kws}')
            matches=$(echo "$matches" | jq --argjson e "$entry" '. + [$e]')
        fi
    done < <(echo "$files_json" | jq -r '.Contents[].Key' 2>/dev/null)

    echo "$matches" > "$out_file"
}
export -f _scan_bucket
export TEMP_DIR MAX_ITEMS
# Export KEYWORDS as a serialised string so the subshell can reconstruct it
export KEYWORDS_SERIALISED
KEYWORDS_SERIALISED=$(printf '%s\n' "${KEYWORDS[@]}")

# Re-define _scan_bucket in a way that reconstructs KEYWORDS from env
# (export -f works for bash functions, but the array can't be exported directly)
_scan_bucket_wrapper() {
    local idx="$1" inst_name="$2" bname="$3" bregion="$4"
    # Reconstruct KEYWORDS array from the serialised env variable
    mapfile -t KEYWORDS <<< "$KEYWORDS_SERIALISED"
    _scan_bucket "$idx" "$inst_name" "$bname" "$bregion"
}
export -f _scan_bucket_wrapper

RUNNING=0
for entry in "${BUCKET_LIST[@]}"; do
    IFS='|' read -r idx inst_name bname bregion <<< "$entry"
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Scanning bucket: $bname (region: $bregion)"
    fi
    _scan_bucket_wrapper "$idx" "$inst_name" "$bname" "$bregion" &
    RUNNING=$((RUNNING + 1))
    if [ "$RUNNING" -ge "$MAX_PARALLEL" ]; then
        wait -n 2>/dev/null || wait
        RUNNING=$((RUNNING - 1))
    fi
done
wait

# ── Aggregate results ─────────────────────────────────────────────────────────
ALL_MATCHES="[]"
TOTAL_KEYS_SCANNED=0
TRUNCATED_BUCKETS=()

for (( i=0; i<TOTAL_BUCKETS; i++ )); do
    result_file="${TEMP_DIR}/${i}.json"
    if [ -f "$result_file" ]; then
        bucket_matches=$(cat "$result_file")
        if [[ "$bucket_matches" != "[]" ]] && echo "$bucket_matches" | jq empty 2>/dev/null; then
            ALL_MATCHES=$(echo "$ALL_MATCHES" | jq --argjson bm "$bucket_matches" '. + $bm')
        fi
    fi
    if [ -f "${TEMP_DIR}/${i}.truncated" ]; then
        IFS='|' read -r _ _ bname _ <<< "${BUCKET_LIST[$i]}"
        TRUNCATED_BUCKETS+=("$bname")
    fi
done

MATCH_COUNT=$(echo "$ALL_MATCHES" | jq 'length')

# ── Write output files ────────────────────────────────────────────────────────
echo "$ALL_MATCHES" | jq '.' > "$JSON_PATH"

{
    echo "IBM Cloud Object Storage — Sensitive File Name Scan"
    echo "======================================================================"
    echo "Keywords searched (${KEYWORD_COUNT}): ${KEYWORD_DISPLAY}"
    echo "Buckets scanned:  ${TOTAL_BUCKETS}"
    echo "Matches found:    ${MATCH_COUNT}"
    echo ""
    if [ ${#TRUNCATED_BUCKETS[@]} -gt 0 ]; then
        echo "NOTE: The following buckets were truncated at ${MAX_ITEMS} keys."
        echo "      Re-run with a larger -m to scan more:"
        for b in "${TRUNCATED_BUCKETS[@]}"; do echo "  - $b"; done
        echo ""
    fi
    if [ "$MATCH_COUNT" -gt 0 ]; then
        # Group by bucket
        echo "$ALL_MATCHES" | jq -r '
            group_by(.instance + "/" + .bucket)[] |
            . as $hits |
            "## \($hits[0].instance)/\($hits[0].bucket) (\($hits | length) match(es)) ##",
            ($hits[] | "  \(.key)", "    → matched: \(.matched_keywords | join(", "))")
            , ""
        '
    else
        echo "No sensitive file names found."
    fi
} > "$TXT_PATH"

# ── Console summary ───────────────────────────────────────────────────────────
echo "${SEPARATOR}"
echo -e "${BOLD}Sensitive File Name Scan — Summary:${RESET}"
echo -e "  Buckets scanned:  ${BOLD}${TOTAL_BUCKETS}${RESET}"

if [ "$MATCH_COUNT" -gt 0 ]; then
    echo -e "  Matches found:    ${BOLD}${RED}${MATCH_COUNT}${RESET}"
    echo ""
    # Display grouped results
    echo "$ALL_MATCHES" | jq -r '
        group_by(.instance + "/" + .bucket)[] |
        . as $hits |
        "  \($hits[0].instance)/\($hits[0].bucket) — \($hits | length) match(es):",
        ($hits[] | "    \(.key)", "      matched: \(.matched_keywords | join(", "))")
    ' | while IFS= read -r line; do
        echo -e "  $line"
    done
else
    echo -e "  Matches found:    ${BOLD}${GREEN}0${RESET}"
    echo ""
    echo -e "  ${BOLD}Good:${RESET} No object keys matched any sensitive keyword."
fi

if [ ${#TRUNCATED_BUCKETS[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${YELLOW}${BOLD}Note:${RESET} ${#TRUNCATED_BUCKETS[@]} bucket(s) truncated at ${MAX_ITEMS} keys."
    echo -e "  Re-run with a larger ${BOLD}-m${RESET} to scan more:"
    for b in "${TRUNCATED_BUCKETS[@]}"; do
        echo -e "    - $b"
    done
fi

echo " "
echo -e "Results (JSON):   ${BOLD}${JSON_PATH}${RESET}"
echo -e "Results (report): ${BOLD}${TXT_PATH}${RESET}"
print_console_link "IBM Cloud Object Storage" "https://cloud.ibm.com/objectstorage/instances"
