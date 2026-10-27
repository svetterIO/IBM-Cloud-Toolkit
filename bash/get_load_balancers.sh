#!/usr/bin/env bash

# get_load_balancers.sh
#
# This script enumerates all VPC Load Balancers in each enabled IBM Cloud region, including their
# listeners (protocol:port). Public load balancers are flagged and their hostname:port endpoints
# are reported and saved to a separate file.
# Requires IBM Cloud CLI and vpc-infrastructure ("is") plugin. Requires jq for JSON processing.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
OUTPUT_FILE="load_balancers.json"
DEBUG=false

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-o OUTPUT_DIR] [-f OUTPUT_FILE] [-v]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: 'output')"
    echo "  -f OUTPUT_FILE  Specify the output file name (default: 'load_balancers.json')"
    echo "  -v              Enable debug mode (outputs commands)"
    echo
    echo "This script enumerates IBM Cloud VPC Load Balancers."
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
require_ibmcloud_is

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_FILE}"
PUBLIC_OUTPUT_PATH="${OUTPUT_DIR}/public_${OUTPUT_FILE}"

echo " "
echo "${SEPARATOR}"
echo -e "Enumerating ${ORANGE}${BOLD}VPC Load Balancers${RESET} in all enabled IBM Cloud regions..."
echo " "

if [ "$DEBUG" = true ]; then
    echo -e "${BOLD}[DEBUG]${RESET} Retrieving regions"
fi

REGIONS=$(get_regions)
if [ "$DEBUG" = true ]; then
    REGION_COUNT=$(echo "$REGIONS" | wc -w | tr -d ' ')
    echo -e "${BOLD}[DEBUG]${RESET} Found $REGION_COUNT region(s) to process"
fi

ALL_LBS="[]"
PUBLIC_LBS="[]"
declare -A REGION_LB_COUNTS

for region in $REGIONS; do
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Processing region: $region"
        echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud target -r \"$region\""
    fi
    if ! ibmcloud target -r "$region" -q &>/dev/null; then
        warning "Failed to target region $region"
        REGION_LB_COUNTS[$region]=0
        continue
    fi

    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud is load-balancers --all-resource-groups --output json"
    fi
    LB_JSON=$(ibmcloud is load-balancers --all-resource-groups --output json 2>/dev/null </dev/null) || LB_JSON=""
    if ! echo "$LB_JSON" | jq -e 'type == "array"' >/dev/null 2>&1; then
        REGION_LB_COUNTS[$region]=0
        continue
    fi

    LB_COUNT=$(echo "$LB_JSON" | jq 'length')
    REGION_LB_COUNTS[$region]=$LB_COUNT
    if [ "$DEBUG" = true ]; then
        echo -e "${BOLD}[DEBUG]${RESET} Region $region: Found $LB_COUNT load balancer(s)"
    fi

    while IFS= read -r lb; do
        [[ -n "$lb" ]] || continue
        LB_ID=$(echo "$lb" | jq -r '.id')
        if [ "$DEBUG" = true ]; then
            echo -e "${BOLD}[DEBUG]${RESET} Running command: ibmcloud is load-balancer-listeners \"$LB_ID\" --output json"
        fi
        LISTENERS=$(ibmcloud is load-balancer-listeners "$LB_ID" --output json 2>/dev/null </dev/null) || LISTENERS=""
        echo "$LISTENERS" | jq -e 'type == "array"' >/dev/null 2>&1 || LISTENERS="[]"

        ENTRY=$(echo "$lb" | jq -c --arg region "$region" --argjson listeners "$LISTENERS" '{
            region: $region,
            name: .name,
            id: .id,
            crn: .crn,
            hostname: .hostname,
            is_public: (.is_public // false),
            operating_status: .operating_status,
            provisioning_status: .provisioning_status,
            public_ips: [(.public_ips // [])[] | .address],
            private_ips: [(.private_ips // [])[] | .address],
            vpc: .vpc.name,
            subnets: [(.subnets // [])[] | .name],
            security_groups: [(.security_groups // [])[] | .name],
            listeners: [$listeners[] | {protocol, port, default_pool: .default_pool.name}],
            pools: [(.pools // [])[] | .name]
        }')
        ALL_LBS=$(echo "$ALL_LBS" | jq -c --argjson e "$ENTRY" '. + [$e]')

        if [[ $(echo "$ENTRY" | jq -r '.is_public') == "true" ]]; then
            PUBLIC_ENTRY=$(echo "$ENTRY" | jq -c '. + {public_endpoints: (
                (.hostname // "") as $h |
                if $h == "" then []
                else [.listeners[].port | select(. != null)] | unique | map("\($h):\(.)") end)}')
            PUBLIC_LBS=$(echo "$PUBLIC_LBS" | jq -c --argjson e "$PUBLIC_ENTRY" '. + [$e]')
        fi
    done < <(echo "$LB_JSON" | jq -c '.[]')
    unset LB_JSON
done

TOTAL_LBS=$(echo "$ALL_LBS" | jq 'length')
TOTAL_PUBLIC=$(echo "$PUBLIC_LBS" | jq 'length')

echo -e "${BOLD}Total VPC Load Balancers: $TOTAL_LBS${RESET}"
if [[ $TOTAL_PUBLIC -gt 0 ]]; then
    echo -e "${YELLOW}${BOLD}Public Load Balancers: $TOTAL_PUBLIC${RESET}"
else
    echo -e "${BOLD}Public Load Balancers: 0${RESET}"
fi
echo " "

if [[ $TOTAL_LBS -gt 0 ]]; then
    echo -e "${BOLD}VPC Load Balancers by region:${RESET}"
    for region in $REGIONS; do
        if [[ ${REGION_LB_COUNTS[$region]:-0} -gt 0 ]]; then
            echo -e "  ${BOLD}$region:${RESET} ${REGION_LB_COUNTS[$region]} load balancer(s)"
            echo "$ALL_LBS" | jq -r --arg region "$region" \
                '.[] | select(.region == $region) | "    - \(.name) (\(if .is_public then "public" else "private" end), \(.hostname))"'
        fi
    done
    echo " "
    : > "$OUTPUT_PATH" || failure "Error while creating the output file: ${BOLD}$OUTPUT_PATH${RESET}"
    echo "$ALL_LBS" | jq '.' > "$OUTPUT_PATH"
    echo -e "All VPC Load Balancers saved to: ${BOLD}${OUTPUT_PATH}${RESET}"

    if [[ $TOTAL_PUBLIC -gt 0 ]]; then
        echo " "
        echo -e "${BOLD}Public endpoints:${RESET}"
        echo "$PUBLIC_LBS" | jq -r '.[] | "  - \(.name): \(if (.public_endpoints | length) > 0 then (.public_endpoints | join(", ")) else "no listeners" end)"'
        : > "$PUBLIC_OUTPUT_PATH" || failure "Error while creating the output file: ${BOLD}$PUBLIC_OUTPUT_PATH${RESET}"
        echo "$PUBLIC_LBS" | jq '.' > "$PUBLIC_OUTPUT_PATH"
        echo -e "${YELLOW}${BOLD}Warning:${RESET} Public Load Balancers saved to: ${BOLD}${PUBLIC_OUTPUT_PATH}${RESET}"
    fi
else
    echo "No VPC Load Balancers found."
fi

if [ "$DEBUG" = true ]; then
    echo " "
    echo -e "${BOLD}[DEBUG]${RESET} Summary:"
    echo -e "${BOLD}[DEBUG]${RESET}   Load Balancers: $TOTAL_LBS"
    echo -e "${BOLD}[DEBUG]${RESET}   Public: $TOTAL_PUBLIC"
fi
print_console_link "Manage VPC Load Balancers" "https://cloud.ibm.com/infrastructure/network/loadBalancers" \
    "IBM Cloud Console > VPC Infrastructure > Network > Load balancers"
