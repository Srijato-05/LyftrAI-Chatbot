param(
    [string]$Base = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"
$Base = $Base.TrimEnd("/")

function Assert-True($cond, $msg) {
    if (-not $cond) { throw "FAIL: $msg" }
    Write-Host "PASS: $msg" -ForegroundColor Green
}

Write-Host "Running contract smoke checks against $Base ..." -ForegroundColor Cyan

# 1. GET /health
$health = Invoke-RestMethod -Uri "$Base/health" -Method Get
Assert-True ($health.status -eq "ok") "GET /health status=ok"
Assert-True ($health.keys_configured -ge 2) "GET /health keys_configured >= 2 ($($health.keys_configured))"
Assert-True ($health.cache_enabled -eq $true) "GET /health cache_enabled=true"

$nonce = [guid]::NewGuid().ToString("N").Substring(0, 8)
$promptA = "In one short sentence, what is the capital of France? (smoke-$nonce)"
$sid1 = "s-smoke-1-$nonce"
$sid2 = "s-smoke-2-$nonce"

# 2. Live inference
$r1 = Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Body (@{
    session_id = $sid1
    message = $promptA
} | ConvertTo-Json)
Assert-True ($r1.session_id -eq $sid1) "POST /chat echoes session_id"
Assert-True ($r1.metadata.resolution_source -eq "LIVE_INFERENCE") "First send is LIVE_INFERENCE"
Assert-True ($r1.metadata.key_id -eq "key_1") "First send answered by key_1"
Assert-True ($r1.metadata.fallback_attempts -eq 0) "First send fallback_attempts=0"

Start-Sleep -Milliseconds 300

# 3. Cache hit in a second session
$r2 = Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Body (@{
    session_id = $sid2
    message = $promptA
} | ConvertTo-Json)
Assert-True ($r2.metadata.resolution_source -eq "LLM_CACHE") "Repeat first message in new session is LLM_CACHE"
Assert-True ($r2.reply -eq $r1.reply) "Cache hit reply matches live reply"
Assert-True ($null -eq $r2.metadata.key_id) "Cache hit key_id is null"
Assert-True ($r2.metadata.fallback_attempts -eq 0) "Cache hit fallback_attempts=0"
Assert-True ($r2.metadata.latency_ms -lt $r1.metadata.latency_ms) "Cache hit faster than live ($($r2.metadata.latency_ms)ms < $($r1.metadata.latency_ms)ms)"

# 4. Multi-turn memory + per-request input_tokens growth
$r3 = Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Body (@{
    session_id = $sid1
    message = "What country is that city in?"
} | ConvertTo-Json)
Assert-True ($r3.metadata.input_tokens -gt $r1.metadata.input_tokens) "Follow-up input_tokens grew with history"

# 5. Simulated failover key_1=429 -> key_2
$r4 = Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Headers @{
    "X-Simulate-Failure" = "key_1=429"
} -Body (@{
    session_id = "s-smoke-sim-$nonce"
    message = "Say hello in three words."
} | ConvertTo-Json)
Assert-True ($r4.metadata.key_id -eq "key_2") "X-Simulate-Failure key_1=429 failed over to key_2"
Assert-True ($r4.metadata.fallback_attempts -eq 1) "fallback_attempts=1"

# 6. Simulated all-keys fail *=429 -> 503 and nothing saved
$failSid = "s-smoke-503-$nonce"
try {
    Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Headers @{
        "X-Simulate-Failure" = "*=429"
    } -Body (@{
        session_id = $failSid
        message = "Should return 503"
    } | ConvertTo-Json) | Out-Null
    throw "Expected 503 error"
} catch {
    $code = [int]$_.Exception.Response.StatusCode
    Assert-True ($code -eq 503) "X-Simulate-Failure *=429 returned 503"
}

try {
    Invoke-RestMethod -Uri "$Base/sessions/$failSid/messages" -Method Get | Out-Null
    throw "Expected 404 error"
} catch {
    $code = [int]$_.Exception.Response.StatusCode
    Assert-True ($code -eq 404) "Failed 503 request did not create session (GET returned 404)"
}

# 7. Validation 422
try {
    Invoke-RestMethod -Uri "$Base/chat" -Method Post -ContentType "application/json" -Body '{"session_id":"s-bad","message":"   "}' | Out-Null
    throw "Expected 422 error"
} catch {
    $code = [int]$_.Exception.Response.StatusCode
    Assert-True ($code -eq 422) "Whitespace message returned 422"
}

# 8. History endpoint
$hist = Invoke-RestMethod -Uri "$Base/sessions/$sid1/messages" -Method Get
Assert-True ($hist.messages.Count -eq 4) "GET /sessions/{id}/messages returned 4 messages"

Write-Host "`nALL SMOKE CHECKS PASSED!" -ForegroundColor Green

