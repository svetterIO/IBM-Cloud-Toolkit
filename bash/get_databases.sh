#!/usr/bin/env bash

# get_databases.sh
#
# This script enumerates all IBM Cloud Databases (Cloud Databases, DB2 and Cloudant) and outputs them as a JSON array.
# For each database, it outputs: id, name, type, endpoint, and other relevant info.
# If any database has a public endpoint enabled, a separate output file is created with only those databases,
# including their public endpoints (hostname:port).
# Requires IBM Cloud CLI and databases ("cdb") plugin. Requires jq for JSON processing.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
OUTPUT_FILE="databases.json"
DEBUG=false

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-f OUTPUT_FILE] [-v]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: 'output')"
    echo "  -f OUTPUT_FILE  Specify the output file name (default: 'databases.json')"
    echo "  -v              Enable debug mode (outputs commands)"
    echo
    echo "This script enumerates all IBM Cloud Databases (Cloud Databases, DB2 and Cloudant)."
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
require_ibmcloud_cdb

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_FILE}"
PUBLIC_ENDPOINT_OUTPUT_PATH="${OUTPUT_DIR}/public_endpoint_${OUTPUT_FILE}"

echo " "
echo "${SEPARATOR}"
echo -e "Enumerating IBM Cloud ${ORANGE}${BOLD}Databases${RESET}..."
echo " "

# Retrieve resource controller instances of a service as a JSON array on stdout.
# Usage: get_resource_instances <service-name> <label> <stderr/stdout file stem>
get_resource_instances() {
    local service_name="$1" label="$2" stem="$3"
    local stderr_file json

    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud resource service-instances --service-name $service_name --all-resource-groups --output json" >&2
    fi

    stderr_file=$(mktemp) || failure "Failed to create a temporary error file."

    if json=$(ibmcloud resource service-instances \
        --service-name "$service_name" \
        --all-resource-groups \
        --output json \
        2>"$stderr_file"); then

        if ! printf '%s' "$json" | jq '.' >/dev/null 2>&1; then
            mv "$stderr_file" "$OUTPUT_DIR/$stem.stderr"
            printf '%s\n' "$json" > "$OUTPUT_DIR/$stem.stdout"
            warning "$label CLI returned invalid JSON. Review $OUTPUT_DIR/$stem.stderr and $OUTPUT_DIR/$stem.stdout." >&2
            echo '[]'
        elif [ "$json" = "null" ]; then
            rm -f "$stderr_file"
            echo '[]'
        else
            rm -f "$stderr_file"
            echo "$json"
        fi
    else
        mv "$stderr_file" "$OUTPUT_DIR/$stem.stderr"
        warning "Failed to retrieve $label instances. Review $OUTPUT_DIR/$stem.stderr." >&2
        echo '[]'
    fi
}

# Debug output
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cdb deployments --json"
fi

# Get Cloud Databases (cdb plugin)
CDB_STDERR=$(mktemp)

if DBS_JSON=$(ibmcloud cdb deployments --json 2>"$CDB_STDERR"); then
    if ! printf '%s' "$DBS_JSON" | jq '.' >/dev/null 2>&1; then
        mv "$CDB_STDERR" "$OUTPUT_DIR/cdb_deployments.stderr"
        warning "Cloud Databases CLI returned invalid JSON. See $OUTPUT_DIR/cdb_deployments.stderr"
        DBS_JSON='[]'
    else
        rm -f "$CDB_STDERR"

        if [ "$DBS_JSON" = "null" ]; then
            DBS_JSON='[]'
        fi
    fi
else
    mv "$CDB_STDERR" "$OUTPUT_DIR/cdb_deployments.stderr"
    warning "Failed to retrieve Cloud Databases. See $OUTPUT_DIR/cdb_deployments.stderr"
    DBS_JSON='[]'
fi

CDB_COUNT=$(echo "${DBS_JSON:-[]}" | jq 'length')

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $CDB_COUNT Cloud Database(s)"
fi

# Get DB2 instances
DB2_JSON=$(get_resource_instances "dashdb-for-transactions" "DB2" "db2_instances")
DB2_COUNT=$(printf '%s' "$DB2_JSON" | jq 'length')

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $DB2_COUNT DB2 instance(s)"
fi

# Get Cloudant instances
CLOUDANT_JSON=$(get_resource_instances "cloudantnosqldb" "Cloudant" "cloudant_instances")
CLOUDANT_COUNT=$(printf '%s' "$CLOUDANT_JSON" | jq 'length')

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Found $CLOUDANT_COUNT Cloudant instance(s)"
fi

# Merge all JSON arrays, tagging each entry with the service it came from
COMBINED_DBS=$(jq -s 'add' \
    <(echo "${DBS_JSON:-[]}" | jq 'map(. + {db_service: "cloud-databases"})') \
    <(echo "${DB2_JSON:-[]}" | jq 'map(. + {db_service: "db2"})') \
    <(echo "${CLOUDANT_JSON:-[]}" | jq 'map(. + {db_service: "cloudant"})'))
if [[ -z "${COMBINED_DBS:-}" || "$COMBINED_DBS" == "[]" || "$COMBINED_DBS" == "null" ]]; then
    echo " "
    echo -e "${BOLD}Total databases found: 0${RESET}"
    echo "No databases found."
    exit 0
fi

# Use the combined JSON for processing
DBS_JSON="$COMBINED_DBS"
# Count total databases
TOTAL_DBS=$(echo "$DBS_JSON" | jq 'length')
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Total databases (combined): $TOTAL_DBS"
fi

echo -e "${BOLD}Total databases found: $TOTAL_DBS${RESET}"
echo " "

# Display database names and types
echo -e "${BOLD}Databases:${RESET}"
while IFS= read -r db; do
    db_name=$(echo "$db" | jq -r '.name')
    db_type=$(echo "$db" | jq -r '.type // .service_id // .db_service // "unknown"')
    db_guid=$(echo "$db" | jq -r '.guid // .id')
    echo "  - $db_name (Type: $db_type)"
    if [ "$DEBUG" = true ]; then
        echo -e "    ${BOLD}[DEBUG]${RESET} GUID: $db_guid"
    fi
done < <(echo "$DBS_JSON" | jq -c '.[]')
echo " "
: > "$OUTPUT_PATH" || failure "Error while creating the output file: ${BOLD}$OUTPUT_PATH${RESET}"

# Enumerate databases with public endpoint enabled
PUBLIC_ENDPOINT_DBS="[]"

# unset resource group to check db_guid in all if previously set manually
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Unsetting resource group to query across all groups"
fi

ibmcloud target --unset-resource-group -q &>/dev/null
if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Checking endpoint types for each database..."
fi

PUBLIC_COUNT=0
while IFS= read -r db; do
    db_guid=$(echo "$db" | jq -r '.guid // .id // empty')
    if [[ -z "$db_guid" ]]; then
        continue
    fi
    db_service=$(echo "$db" | jq -r '.db_service')
    db_ref=$(echo "$db" | jq -r '.crn // .name')

    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud resource service-instance \"$db_guid\" --output json"
    fi
    DB_INSTANCE_JSON=$(ibmcloud resource service-instance "$db_guid" --output json 2>/dev/null </dev/null) || true
    if [[ -z "${DB_INSTANCE_JSON:-}" || "$DB_INSTANCE_JSON" == "[]" ]] || ! echo "$DB_INSTANCE_JSON" | jq -e 'type == "array"' >/dev/null 2>&1; then
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} Could not retrieve details for this database"
        fi
        continue
    fi
    ENDPOINT_TYPE=$(echo "$DB_INSTANCE_JSON" | jq -r '.[0].parameters["service-endpoints"] // "private"')
    # Public endpoint advertised in the instance extensions (e.g. Cloudant), as hostname:port
    EXT_ENDPOINT=$(echo "$DB_INSTANCE_JSON" | jq -r '
        (try .[0].extensions.endpoints.public catch null) // "" |
        if type == "string" and . != "" then
            (sub("^https?://"; "") | split("/")[0] | if contains(":") then . else . + ":443" end)
        else "" end')
    db_name=$(echo "$DB_INSTANCE_JSON" | jq -r '.[0].name')
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Database \"$db_name\": endpoint type = $ENDPOINT_TYPE"
    fi

    if [[ "$ENDPOINT_TYPE" == "private" && ! ( "$db_service" == "cloudant" && -n "$EXT_ENDPOINT" ) ]]; then
        continue
    fi

    if [[ "$db_service" == "cloud-databases" ]]; then
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud cdb deployment-connections \"$db_ref\" --endpoint-type public --all --output json"
        fi
        ENDPOINTS_JSON=$(ibmcloud cdb deployment-connections "$db_ref" --endpoint-type public --all --output json 2>/dev/null </dev/null \
            | jq -c '[.. | objects | select((.hostname // "") != "" and .port != null) | "\(.hostname):\(.port)"] | unique' 2>/dev/null) || ENDPOINTS_JSON="[]"
        [[ -n "$ENDPOINTS_JSON" ]] || ENDPOINTS_JSON="[]"
    elif [[ -n "$EXT_ENDPOINT" ]]; then
        ENDPOINTS_JSON=$(jq -c -n --arg e "$EXT_ENDPOINT" '[$e]')
    else
        ENDPOINTS_JSON="[]"
    fi

    PUBLIC_COUNT=$((PUBLIC_COUNT + 1))
    ENTRY=$(echo "$DB_INSTANCE_JSON" | jq -c --arg guid "$db_guid" --arg svc "$db_service" --arg ep "$ENDPOINT_TYPE" \
        --argjson endpoints "$ENDPOINTS_JSON" \
        '.[0] | {name, guid: $guid, crn, db_service: $svc, service_endpoints: $ep, public_endpoints: $endpoints}')
    PUBLIC_ENDPOINT_DBS=$(echo "$PUBLIC_ENDPOINT_DBS" | jq -c --argjson e "$ENTRY" '. + [$e]')
done < <(echo "$DBS_JSON" | jq -c '.[]')

# Save all databases to the output file
echo "$DBS_JSON" | jq '.' > "$OUTPUT_PATH"
echo -e "All databases saved to: ${BOLD}${OUTPUT_PATH}${RESET}"

# Save databases with public endpoint to a separate file
echo " "
if [[ $(echo "$PUBLIC_ENDPOINT_DBS" | jq 'length') -gt 0 ]]; then
    : > "$PUBLIC_ENDPOINT_OUTPUT_PATH" || failure "Error while creating the output file: ${BOLD}$PUBLIC_ENDPOINT_OUTPUT_PATH${RESET}"
    echo "$PUBLIC_ENDPOINT_DBS" | jq '.' > "$PUBLIC_ENDPOINT_OUTPUT_PATH"
    echo -e "${BOLD}Databases with public endpoint: $PUBLIC_COUNT${RESET}"
    echo "$PUBLIC_ENDPOINT_DBS" | jq -r '.[] | "  - \(.name) (\(.db_service)): \(if (.public_endpoints | length) > 0 then (.public_endpoints | join(", ")) else "endpoint not retrieved" end)"'
    echo -e "Databases with public endpoint saved to: ${BOLD}${PUBLIC_ENDPOINT_OUTPUT_PATH}${RESET}"
else
    echo -e "${BOLD}Databases with public endpoint: 0${RESET}"
fi

if [ "$DEBUG" = true ]; then
    echo " "
    echo -e "${BOLD}[DEBUG]${RESET} Summary:"
    echo -e "${BOLD}[DEBUG]${RESET}   Cloud Databases: $CDB_COUNT"
    echo -e "${BOLD}[DEBUG]${RESET}   DB2 Instances: $DB2_COUNT"
    echo -e "${BOLD}[DEBUG]${RESET}   Cloudant Instances: $CLOUDANT_COUNT"
    echo -e "${BOLD}[DEBUG]${RESET}   Total: $TOTAL_DBS"
    echo -e "${BOLD}[DEBUG]${RESET}   Public Endpoints: $PUBLIC_COUNT"
fi
print_console_link "Manage Cloud Databases" "https://cloud.ibm.com/databases-overview/resources" \
    "IBM Cloud Console > Databases"
