param(
    [string]$BaseUrl = "http://127.0.0.1:8020",
    [string]$SeedUserId = "",
    [string]$AuthToken = ""
)

$ErrorActionPreference = "Stop"

if (-not $SeedUserId) {
    throw "Provide -SeedUserId"
}

function Invoke-Mcp {
    param(
        [string]$Method,
        [hashtable]$Params
    )

    $uri = "$($BaseUrl.TrimEnd('/'))/mcp"
    $headers = @{}
    if ($AuthToken) {
        $token = $AuthToken
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

    Invoke-RestMethod -Method POST -Uri $uri -Headers $headers -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 20)
}

function Parse-ToolContent {
    param([object]$Response)
    $text = $Response.result.content[0].text
    $text | ConvertFrom-Json
}

Write-Host "[INFO] BaseUrl: $BaseUrl"
Write-Host "[INFO] SeedUserId: $SeedUserId"

$list = Invoke-Mcp -Method "tools/list" -Params @{}
$names = @($list.result.tools | ForEach-Object { $_.name })

foreach ($required in @(
    "cashflow_forecast_v1",
    "anomaly_signals_v1",
    "recurring_cashflow_detect_v1",
    "goal_feasibility_v1",
    "what_if_scenario_v1"
)) {
    if ($names -notcontains $required) {
        throw "Missing tool: $required"
    }
}
Write-Host "[PASS] tools/list"

$forecastRes = Invoke-Mcp -Method "tools/call" -Params @{
    name = "cashflow_forecast_v1"
    arguments = @{
        user_id = $SeedUserId
        horizon = "weekly_12"
    }
}
if ($forecastRes.error) {
    throw "cashflow_forecast_v1 failed: $($forecastRes.error | ConvertTo-Json -Depth 10)"
}
$forecast = Parse-ToolContent -Response $forecastRes
Write-Host "[INFO] forecast darts available=$($forecast.external_engines.darts_exponential_smoothing.available) ready=$($forecast.external_engines.darts_exponential_smoothing.ready)"

$anomalyRes = Invoke-Mcp -Method "tools/call" -Params @{
    name = "anomaly_signals_v1"
    arguments = @{
        user_id = $SeedUserId
        lookback_days = 90
    }
}
if ($anomalyRes.error) {
    throw "anomaly_signals_v1 failed: $($anomalyRes.error | ConvertTo-Json -Depth 10)"
}
$anomaly = Parse-ToolContent -Response $anomalyRes
Write-Host "[INFO] anomaly river available=$($anomaly.external_engines.river_adwin.available)"
Write-Host "[INFO] anomaly pyod available=$($anomaly.external_engines.pyod_ecod.available)"
Write-Host "[INFO] anomaly kats available=$($anomaly.external_engines.kats_cusum.available)"

$recurringRes = Invoke-Mcp -Method "tools/call" -Params @{
    name = "recurring_cashflow_detect_v1"
    arguments = @{
        user_id = $SeedUserId
        lookback_months = 6
        min_occurrence_months = 3
    }
}
if ($recurringRes.error) {
    throw "recurring_cashflow_detect_v1 failed: $($recurringRes.error | ConvertTo-Json -Depth 10)"
}
$recurring = Parse-ToolContent -Response $recurringRes
Write-Host "[INFO] recurring expenses=$(@($recurring.recurring_expense).Count) fixed_ratio=$($recurring.fixed_cost_ratio)"

$goalRes = Invoke-Mcp -Method "tools/call" -Params @{
    name = "goal_feasibility_v1"
    arguments = @{
        user_id = $SeedUserId
        target_amount = 60000000
        horizon_months = 6
    }
}
if ($goalRes.error) {
    throw "goal_feasibility_v1 failed: $($goalRes.error | ConvertTo-Json -Depth 10)"
}
$goal = Parse-ToolContent -Response $goalRes
Write-Host "[INFO] goal feasible=$($goal.feasible) gap=$($goal.gap_amount) grade=$($goal.grade)"

$scenarioRes = Invoke-Mcp -Method "tools/call" -Params @{
    name = "what_if_scenario_v1"
    arguments = @{
        user_id = $SeedUserId
        horizon_months = 12
        seasonality = $true
    }
}
if ($scenarioRes.error) {
    throw "what_if_scenario_v1 failed: $($scenarioRes.error | ConvertTo-Json -Depth 10)"
}
$scenario = Parse-ToolContent -Response $scenarioRes
Write-Host "[INFO] scenario variants=$(@($scenario.scenario_comparison).Count) best=$($scenario.best_variant_by_goal)"

Write-Host "[DONE] Finance MCP smoke completed"
