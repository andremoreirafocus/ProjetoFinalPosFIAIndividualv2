#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONTEXT_OUTPUT="$SCRIPT_DIRECTORY/sample_agent_context_before_llm.json"
LLM_RESPONSE_OUTPUT="$SCRIPT_DIRECTORY/sample_llm_response_to_report_request.json"
AGENT_REPORT_OUTPUT="$SCRIPT_DIRECTORY/sample_agent_report.json"
FINAL_PDF_OUTPUT="$SCRIPT_DIRECTORY/sample_credit_review_report_v4.pdf"

ARTIFACTS=(
    "$CONTEXT_OUTPUT"
    "$LLM_RESPONSE_OUTPUT"
    "$AGENT_REPORT_OUTPUT"
    "$FINAL_PDF_OUTPUT"
)

for artifact in "${ARTIFACTS[@]}"; do
    if [[ -e "$artifact" ]]; then
        rm -- "$artifact"
        printf 'Removido: %s\n' "$artifact"
    else
        printf 'Já estava ausente: %s\n' "$artifact"
    fi
done
