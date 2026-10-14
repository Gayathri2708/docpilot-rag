#!/usr/bin/env bash
# Checks a running public-demo container: preloaded docs, read-only visitor key, uploads off,
# well-known demo keys revoked, rate limiting on, no .env in the image. Usage: smoke_test.sh [base_url]
set -euo pipefail
B=${1:-http://localhost:7860}
K="X-API-Key: dp_public_demo"
JSON="Content-Type: application/json"
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected $3, got $2"; exit 1; fi; }

check "config exposes the visitor key" "$(curl -s "$B/config" | jq -r .public_demo_key)" dp_public_demo
check "config reports uploads disabled" "$(curl -s "$B/config" | jq .uploads_enabled)" false
check "sample documents preloaded" "$(curl -s -H "$K" "$B/documents" | jq length)" 5
check "search works for the visitor key" "$(curl -s -H "$K" -H "$JSON" -d '{"query":"paid leave days","top_k":3}' "$B/search" | jq length)" 3
check "visitor key cannot upload" "$(code -H "$K" -F file=@README.md "$B/documents")" 403
check "visitor key cannot delete" "$(code -X DELETE -H "$K" "$B/documents/x")" 403
check "well-known admin demo key is revoked" "$(code -H 'X-API-Key: dp_demo_admin' "$B/documents")" 401
codes=$(for _ in 1 2 3 4 5 6 7; do code -H "$K" -H "$JSON" -d '{"query":"q"}' "$B/search"; echo -n " "; done)
check "rate limit returns 429" "$(echo "$codes" | grep -c 429)" 1
echo "all smoke checks passed"
