#!/usr/bin/env bash
input=$(cat)
command=$(jq -r '.tool_input.command // ""' <<< "$input")
status=$(jq -r 'if .tool_response.interrupted then "interrupted" else "ok" end' <<< "$input")
ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

printf '%s\n' "{\"ts\":\"$ts\",\"cmd\":$(jq -Rn --arg c "$command" '$c'),\"status\":\"$status\"}" \
  >> "$(dirname "$0")/../audit.jsonl"

exit 0
