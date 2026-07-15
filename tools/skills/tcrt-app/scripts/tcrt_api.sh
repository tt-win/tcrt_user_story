#!/bin/sh
# Portable App Token client. Requires only POSIX sh, curl, and mktemp.

set -u

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
DEFAULT_ENV_FILE="$SKILL_DIR/.env"

die() {
    printf '%s\n' "[tcrt-app] $*" >&2
    exit 2
}

strip_outer_quotes() {
    value=$1
    case "$value" in
        \"*\") value=${value#\"}; value=${value%\"} ;;
        \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    printf '%s' "$value"
}

trim_leading_whitespace() {
    value=$1
    while :; do
        case "$value" in
            ' '*) value=${value#' '} ;;
            '	'*) value=${value#'	'} ;;
            *) break ;;
        esac
    done
    printf '%s' "$value"
}

load_env_file() {
    env_file=$1
    file_base_url=''
    file_token=''
    [ -f "$env_file" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line=$(trim_leading_whitespace "$line")
        case "$line" in
            ''|\#*) continue ;;
            TCRT_BASE_URL=*) file_base_url=$(strip_outer_quotes "${line#TCRT_BASE_URL=}") ;;
            TCRT_APP_TOKEN=*) file_token=$(strip_outer_quotes "${line#TCRT_APP_TOKEN=}") ;;
        esac
    done < "$env_file"
}

usage() {
    cat >&2 <<'EOF'
Usage:
  sh scripts/tcrt_api.sh check
  sh scripts/tcrt_api.sh <METHOD> <PATH> [--data '<json>'] [--query 'k=v&k2=v2']
  sh scripts/tcrt_api.sh POST <PATH> --file field=@/path/to/file [--file ...]
EOF
    exit 2
}

[ "$#" -gt 0 ] || usage
command -v curl >/dev/null 2>&1 || die "curl is required; use python3 scripts/tcrt_api.py only when Python is available."

method=$1
shift
path=''
data=''
has_data=0
query=''
files=''
has_file=0
cr=$(printf '\r')

if [ "$method" = "check" ] || [ "$method" = "CHECK" ]; then
    [ "$#" -eq 0 ] || usage
    method=GET
    path=/api/app/teams
else
    [ "$#" -gt 0 ] || usage
    path=$1
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --data)
                [ "$#" -ge 2 ] || die "--data requires a JSON value"
                data=$2
                has_data=1
                shift 2
                ;;
            --query)
                [ "$#" -ge 2 ] || die "--query requires a query string"
                query=$2
                shift 2
                ;;
            --file)
                [ "$#" -ge 2 ] || die "--file requires a value like field=@/path/to/file"
                case "$2" in
                    *\"*|*\\*|*"$cr"*|*"
"*)
                        die "--file value contains unsupported characters" ;;
                esac
                case "$2" in
                    *@*)
                        file_path_part=${2#*@}
                        [ -f "$file_path_part" ] || die "--file path not found: $file_path_part" ;;
                esac
                files="$files$2
"
                has_file=1
                shift 2
                ;;
            *) die "unknown argument: $1" ;;
        esac
    done
fi

if [ "$has_data" -eq 1 ] && [ "$has_file" -eq 1 ]; then
    die "--data and --file are mutually exclusive"
fi

case "$path" in
    /*) ;;
    *) path=/$path ;;
esac

env_file=${TCRT_ENV_FILE:-$DEFAULT_ENV_FILE}
load_env_file "$env_file"
base_url=${TCRT_BASE_URL:-$file_base_url}
token=${TCRT_APP_TOKEN:-$file_token}

missing=''
[ -n "$base_url" ] || missing="$missing TCRT_BASE_URL"
[ -n "$token" ] || missing="$missing TCRT_APP_TOKEN"
[ -z "$missing" ] || die "Missing:$missing. Set exported variables or a local env file; never paste a token into chat."

base_url=${base_url%/}
url=$base_url$path
[ -z "$query" ] || url=$url?$query

case "$method$url$token" in
    *\"*|*\\*|*'
'*|*''*) die "request configuration contains unsupported characters" ;;
esac

umask 077
curl_config=$(mktemp "${TMPDIR:-/tmp}/tcrt-app-config.XXXXXX") || die "could not create temporary request config"
body_file=$(mktemp "${TMPDIR:-/tmp}/tcrt-app-body.XXXXXX") || {
    rm -f "$curl_config"
    die "could not create temporary response file"
}
data_file=''
cleanup() {
    rm -f "$curl_config" "$body_file"
    [ -z "$data_file" ] || rm -f "$data_file"
}
trap cleanup 0 1 2 15

if [ "$has_data" -eq 1 ]; then
    data_file=$(mktemp "${TMPDIR:-/tmp}/tcrt-app-data.XXXXXX") || die "could not create temporary request body"
    printf '%s' "$data" > "$data_file"
fi

{
    printf '%s\n' 'silent'
    printf '%s\n' 'show-error'
    printf 'request = "%s"\n' "$method"
    printf 'url = "%s"\n' "$url"
    printf 'header = "Authorization: Bearer %s"\n' "$token"
    printf 'output = "%s"\n' "$body_file"
    printf '%s\n' 'write-out = "%{http_code}"'
    if [ "$has_data" -eq 1 ]; then
        printf '%s\n' 'header = "Content-Type: application/json"'
        printf 'data-binary = "@%s"\n' "$data_file"
    elif [ "$has_file" -eq 1 ]; then
        printf '%s' "$files" | while IFS= read -r file_spec; do
            [ -n "$file_spec" ] || continue
            printf 'form = "%s"\n' "$file_spec"
        done
    fi
} > "$curl_config"

status=$(curl --config "$curl_config")
curl_exit=$?
case "$status" in
    ''|*[!0-9]*) status=000 ;;
esac

cat "$body_file"
printf 'HTTP %s\n' "$status" >&2

if [ "$curl_exit" -ne 0 ]; then
    exit "$curl_exit"
fi
case "$status" in
    4*|5*) exit 1 ;;
esac
