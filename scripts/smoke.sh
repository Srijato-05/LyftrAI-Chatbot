#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-http://localhost:8000}"
BASE="${BASE%/}"
NONCE="$(date +%s)-$RANDOM"

echo "Running contract smoke checks against $BASE ..."

health=$(curl -fsS "$BASE/health")
echo "$health" | grep -q '"status":"ok"'
echo "PASS: GET /health"

sid1="s-smoke-1-$NONCE"
sid2="s-smoke-2-$NONCE"
prompt="In one short sentence, what is the capital of France? ($NONCE)"

r1=$(curl -fsS -X POST "$BASE/chat" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$sid1\",\"message\":\"$prompt\"}")
echo "$r1" | grep -q '"resolution_source":"LIVE_INFERENCE"'
echo "$r1" | grep -q '"key_id":"key_1"'
echo "PASS: LIVE_INFERENCE on key_1"

sleep 0.3

r2=$(curl -fsS -X POST "$BASE/chat" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$sid2\",\"message\":\"$prompt\"}")
echo "$r2" | grep -q '"resolution_source":"LLM_CACHE"'
echo "$r2" | grep -q '"key_id":null'
echo "PASS: LLM_CACHE hit in new session"

r3=$(curl -fsS -X POST "$BASE/chat" -H "Content-Type: application/json" \
  -H "X-Simulate-Failure: key_1=429" \
  -d "{\"session_id\":\"s-smoke-sim-$NONCE\",\"message\":\"Say hi.\"}")
echo "$r3" | grep -q '"key_id":"key_2"'
echo "$r3" | grep -q '"fallback_attempts":1'
echo "PASS: X-Simulate-Failure key_1=429 -> key_2"

status503=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/chat" \
  -H "Content-Type: application/json" -H "X-Simulate-Failure: *=429" \
  -d "{\"session_id\":\"s-smoke-503-$NONCE\",\"message\":\"Fail all\"}")
test "$status503" = "503"
echo "PASS: X-Simulate-Failure *=429 -> 503"

status404=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/sessions/s-smoke-503-$NONCE/messages")
test "$status404" = "404"
echo "PASS: Failed 503 request left no history (404)"

status422=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/chat" \
  -H "Content-Type: application/json" -d '{"session_id":"s-bad","message":"   "}')
test "$status422" = "422"
echo "PASS: Whitespace message -> 422"

hist=$(curl -fsS "$BASE/sessions/$sid1/messages")
echo "$hist" | grep -q '"role":"user"'
echo "PASS: GET /sessions/{id}/messages"

echo "ALL SMOKE CHECKS PASSED!"

