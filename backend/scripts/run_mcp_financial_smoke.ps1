param(
    [string]$BaseUrl = "http://127.0.0.1:8010",
    [string]$SeedUserId = "",
    [string]$AuthToken = ""
)

$ErrorActionPreference = "Stop"

function Resolve-SeedUserId {
    param([string]$Current)

    if ($Current -and $Current.Trim().Length -gt 0) {
        return $Current.Trim()
    }

    $manifestPath = Join-Path $PSScriptRoot "..\tmp\seed_manifest_single_user.json"
    $manifestPath = [System.IO.Path]::GetFullPath($manifestPath)
    if (-not (Test-Path $manifestPath)) {
        throw "Seed user id is missing and manifest not found: $manifestPath"
    }

    $manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
    if (-not $manifest.seed_user_id) {
        throw "seed_user_id not found in manifest: $manifestPath"
    }
    return [string]$manifest.seed_user_id
}

function Invoke-Mcp {
    param(
        [string]$Method,
        [hashtable]$Params
    )

    $uri = "$($BaseUrl.TrimEnd('/'))/mcp"
    $headers = @{}
    if ($AuthToken -and $AuthToken.Trim().Length -gt 0) {
        $token = $AuthToken.Trim()
        if (-not $token.ToLower().StartsWith("bearer ")) {
            $token = "Bearer $token"
        }
        $headers["Authorization"] = $token
    }

    $payload = @{
        jsonrpc = "2.0"
        id = [Guid]::NewGuid().ToString()
        method = $Method
    }
    if ($Params) {
        $payload["params"] = $Params
    }

    return Invoke-RestMethod -Method POST -Uri $uri -ContentType "application/json" -Headers $headers -Body ($payload | ConvertTo-Json -Depth 20)
}

function Parse-ToolResult {
    param([object]$Response)

    if (-not $Response.result -or -not $Response.result.content) {
        throw "Missing JSON-RPC result/content"
    }

    $item = $Response.result.content | Select-Object -First 1
    if (-not $item.text) {
        throw "Missing content.text in tool response"
    }

    return ($item.text | ConvertFrom-Json)
}

function Assert-Envelope {
    param(
        [object]$Data,
        [string]$ToolName
    )

    $required = @("trace_id", "version", "params_hash", "sql_snapshot_ts", "audit")
    foreach ($key in $required) {
        if (-not $Data.PSObject.Properties.Name.Contains($key)) {
            throw "[$ToolName] Missing required envelope field: $key"
        }
    }
}

$seedUser = Resolve-SeedUserId -Current $SeedUserId
Write-Host "[INFO] BaseUrl: $BaseUrl"
Write-Host "[INFO] SeedUserId: $seedUser"

$toolsResponse = Invoke-Mcp -Method "tools/list" -Params @{}
if (-not $toolsResponse.result -or -not $toolsResponse.result.tools) {
    throw "tools/list did not return tools"
}

$toolNames = @($toolsResponse.result.tools | ForEach-Object { $_.name })
$requiredTools = @(
    "spend_analytics_v1",
    "anomaly_signals_v1",
    "cashflow_forecast_v1",
    "jar_allocation_suggest_v1",
    "risk_profile_non_investment_v1",
    "suitability_guard_v1"
)

foreach ($name in $requiredTools) {
    if ($toolNames -notcontains $name) {
        throw "Missing tool from tools/list: $name"
    }
}

Write-Host "[PASS] tools/list contains all required financial tools"

$tests = @(
    @{ name = "spend_analytics_v1"; args = @{ user_id = $seedUser; range = "30d" } },
    @{ name = "anomaly_signals_v1"; args = @{ user_id = $seedUser; lookback_days = 90 } },
    @{ name = "cashflow_forecast_v1"; args = @{ user_id = $seedUser; horizon = "weekly_12" } },
    @{ name = "jar_allocation_suggest_v1"; args = @{ user_id = $seedUser } },
    @{ name = "risk_profile_non_investment_v1"; args = @{ user_id = $seedUser; lookback_days = 180 } },
    @{ name = "suitability_guard_v1"; args = @{ user_id = $seedUser; intent = "invest"; requested_action = "buy"; prompt = "toi muon mua co phieu" } }
)

foreach ($test in $tests) {
    $response = Invoke-Mcp -Method "tools/call" -Params @{ name = $test.name; arguments = $test.args }
    if ($response.error) {
        throw "Tool call failed for $($test.name): $($response.error | ConvertTo-Json -Depth 10)"
    }

    $data = Parse-ToolResult -Response $response
    Assert-Envelope -Data $data -ToolName $test.name

    if ($test.name -eq "anomaly_signals_v1") {
        if (-not $data.external_engines) {
            throw "[anomaly_signals_v1] Missing external_engines"
        }
        foreach ($engine in @("river_adwin", "pyod_ecod", "kats_cusum")) {
            if (-not $data.external_engines.PSObject.Properties.Name.Contains($engine)) {
                throw "[anomaly_signals_v1] Missing external engine output: $engine"
            }
        }
    }

    if ($test.name -eq "cashflow_forecast_v1") {
        if (-not $data.external_engines) {
            throw "[cashflow_forecast_v1] Missing external_engines"
        }
        if (-not $data.external_engines.PSObject.Properties.Name.Contains("darts_exponential_smoothing")) {
            throw "[cashflow_forecast_v1] Missing darts_exponential_smoothing output"
        }
    }

    Write-Host "[PASS] $($test.name)"
}

Write-Host "[DONE] MCP financial smoke test passed for all required tools."
