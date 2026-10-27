#!/usr/bin/env bash

# get_my_access.sh
#
# Enumerates the access capabilities of the identity currently logged in to the
# IBM Cloud CLI (user, service ID or trusted profile):
#   - Identity details decoded from the current IAM token
#   - Access policies attached directly to the identity
#   - Access groups the identity belongs to, and the policies of each group
# Requires IBM Cloud CLI, jq, and curl.

srcdir="$(dirname "${BASH_SOURCE[0]}")"
. "$srcdir/utils.sh"

OUTPUT_DIR="output"
OUTPUT_FILE="my_access.json"
VERBOSE=0
PAGE_SIZE=100
IAM_URL="https://iam.cloud.ibm.com"

usage() {
    scriptname=$(basename "$0")
    echo "Usage: ./$scriptname [-h] [-v] [-o OUTPUT_DIR] [-f OUTPUT_FILE]"
    echo
    echo "Options:"
    echo "  -h              Show this help message"
    echo "  -v              Enable debug output"
    echo "  -o OUTPUT_DIR   Specify the output folder for results (default: 'output')"
    echo "  -f OUTPUT_FILE  Specify the output file name (default: 'my_access.json')"
    echo
    echo "This script enumerates the policies and access groups of the current IBM Cloud identity."
}

while getopts ":hvo:f:" opt; do
    case $opt in
        h) usage; exit 0 ;;
        v) VERBOSE=1 ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        f) OUTPUT_FILE="$OPTARG" ;;
        \?) echo "Invalid option: -$OPTARG" >&2; usage; exit 1 ;;
        :) echo "Option -$OPTARG requires an argument." >&2; usage; exit 1 ;;
    esac
done

debug() {
    if [[ $VERBOSE -eq 1 ]]; then
        echo -e "${BOLD}[DEBUG]${RESET} $*"
    fi
    return 0
}

# GET an IAM endpoint and extract a JSON array field; prints '[]' on any failure.
# Usage: iam_get_array <url> <jq field>
iam_get_array() {
    local out
    out=$(curl -s -X GET "$1" -H "Authorization: Bearer $IBMCLOUD_ACCESS_TOKEN" | jq -c ".$2 // []" 2>/dev/null) || out=""
    echo "${out:-[]}"
}

# Print a JSON array of policies (stdin) in a readable form.
print_policies() {
    local indent="$1"
    local json
    json=$(cat)
    if [[ $(echo "$json" | jq 'length') -eq 0 ]]; then
        echo "${indent}(no policies)"
        return
    fi
    echo "$json" | jq -r --arg i "$indent" '
        .[] |
        ((.roles // .control.grant.roles // []) | map(.display_name // (.role_id | split(":") | last)) | join(", ")) as $roles |
        ((.resources // [.resource // {}])
            | map(((.attributes // []) | map("\(.name)=\(.value)") | join(", ")) | if . == "" then "all resources" else . end)
            | join(" | ")) as $res |
        "\($i)- Roles: \($roles)\n\($i)  Resource: \($res)"'
}

require_ibmcloud_jq
require_curl
require_ibmcloud_login

if [ ! -d "$OUTPUT_DIR" ]; then
    mkdir -p "$OUTPUT_DIR" || failure "Error while creating the output directory: ${BOLD}$OUTPUT_DIR${RESET}"
fi

OUTPUT_PATH="${OUTPUT_DIR}/${OUTPUT_FILE}"

echo " "
echo "${SEPARATOR}"
echo -e "Enumerating ${ORANGE}${BOLD}your own access${RESET} (policies and access groups) in IAM..."
echo " "

IBMCLOUD_ACCESS_TOKEN=$(ibmcloud_access_token)
if [[ -z "${IBMCLOUD_ACCESS_TOKEN:-}" || "$IBMCLOUD_ACCESS_TOKEN" == "null" ]]; then
    failure "Failed to obtain IBM Cloud access token. Make sure you are logged in with 'ibmcloud login'."
fi

IBMCLOUD_ACCOUNT_ID=$(ibmcloud_account_id)
if [[ -z "${IBMCLOUD_ACCOUNT_ID:-}" || "$IBMCLOUD_ACCOUNT_ID" == "null" ]]; then
    failure "Failed to obtain IBM Cloud account ID. Make sure you are logged in."
fi
IBMCLOUD_ACCOUNT_NAME=$(ibmcloud_account_name)

# Decode the JWT payload (base64url, padding may be missing)
PAYLOAD=$(echo "$IBMCLOUD_ACCESS_TOKEN" | cut -d '.' -f 2 | tr '_-' '/+')
case $(( ${#PAYLOAD} % 4 )) in
    2) PAYLOAD="${PAYLOAD}==" ;;
    3) PAYLOAD="${PAYLOAD}=" ;;
esac
CLAIMS=$(echo "$PAYLOAD" | base64 -d 2>/dev/null) || failure "Failed to decode the IAM token."

IAM_ID=$(echo "$CLAIMS" | jq -r '.iam_id // empty')
[[ -n "$IAM_ID" ]] || failure "Could not determine the IAM ID of the current identity from the token."

case "$IAM_ID" in
    iam-ServiceId*) ID_TYPE="Service ID" ;;
    iam-Profile*)   ID_TYPE="Trusted profile" ;;
    *)              ID_TYPE="User" ;;
esac

IDENTITY=$(echo "$CLAIMS" | jq -c \
    --arg type "$ID_TYPE" --arg acc "$IBMCLOUD_ACCOUNT_ID" --arg accname "$IBMCLOUD_ACCOUNT_NAME" \
    '{type: $type, iam_id: .iam_id, identifier: (.identifier // .sub // ""), email: (.email // ""),
      name: (.name // ""), account_id: $acc, account_name: $accname}')

UI_URL="https://cloud.ibm.com/iam/users/${IAM_ID}?tab=userdetails"

echo -e "${BOLD}Identity${RESET}"
echo "$IDENTITY" | jq -r 'to_entries[] | select(.value != "") | "  \(.key): \(.value)"'
echo

# Direct policies
debug "GET $IAM_URL/v1/policies?account_id=$IBMCLOUD_ACCOUNT_ID&iam_id=$IAM_ID&type=access"
debug "UI: $UI_URL"
DIRECT=$(iam_get_array "$IAM_URL/v1/policies?account_id=$IBMCLOUD_ACCOUNT_ID&iam_id=$IAM_ID&type=access" policies)

echo -e "${BOLD}Direct access policies ($(echo "$DIRECT" | jq 'length'))${RESET}"
echo "$DIRECT" | print_policies "  "
echo

# Access groups (paginated)
ACCESS_GROUPS='[]'
OFFSET=0
while true; do
    debug "GET $IAM_URL/v2/groups?account_id=$IBMCLOUD_ACCOUNT_ID&iam_id=$IAM_ID&limit=$PAGE_SIZE&offset=$OFFSET"
    PAGE=$(iam_get_array "$IAM_URL/v2/groups?account_id=$IBMCLOUD_ACCOUNT_ID&iam_id=$IAM_ID&limit=$PAGE_SIZE&offset=$OFFSET" groups)
    ACCESS_GROUPS=$(jq -c -n --argjson a "$ACCESS_GROUPS" --argjson b "$PAGE" '$a + $b')
    if [[ $(echo "$PAGE" | jq 'length') -lt $PAGE_SIZE ]]; then
        break
    fi
    OFFSET=$((OFFSET + PAGE_SIZE))
done

GROUP_COUNT=$(echo "$ACCESS_GROUPS" | jq 'length')
echo -e "${BOLD}Access groups ($GROUP_COUNT)${RESET}"

GROUP_RESULTS='[]'
while IFS= read -r grp; do
    [[ -n "$grp" ]] || continue
    GID=$(echo "$grp" | jq -r '.id')
    GNAME=$(echo "$grp" | jq -r '.name')
    debug "GET policies for access group $GID"
    debug "UI: https://cloud.ibm.com/iam/groups/${GID}?tab=access"
    GPOLICIES=$(iam_get_array "$IAM_URL/v1/policies?account_id=$IBMCLOUD_ACCOUNT_ID&access_group_id=$GID&type=access" policies)
    GROUP_RESULTS=$(jq -c -n --argjson r "$GROUP_RESULTS" --arg id "$GID" --arg name "$GNAME" --argjson p "$GPOLICIES" \
        '$r + [{id: $id, name: $name, policies: $p}]')
    echo -e "  ${BOLD}${GNAME}${RESET} (${GID}) - $(echo "$GPOLICIES" | jq 'length') policy(ies)"
    echo "$GPOLICIES" | print_policies "    "
done < <(echo "$ACCESS_GROUPS" | jq -c '.[]')

if [[ "$GROUP_COUNT" -eq 0 ]]; then
    echo "  (not a member of any access group)"
fi
echo

jq -n --argjson identity "$IDENTITY" --argjson direct "$DIRECT" --argjson groups "$GROUP_RESULTS" \
    '{identity: $identity, direct_policies: $direct, access_groups: $groups}' > "$OUTPUT_PATH" \
    || failure "Error while creating the output file: ${BOLD}$OUTPUT_PATH${RESET}"

echo -e "Access details saved to: ${BOLD}${OUTPUT_PATH}${RESET}"
print_console_link "Review your access" "$UI_URL" \
    "IBM Cloud Console > Manage > Access (IAM) > Users > [your user]"
