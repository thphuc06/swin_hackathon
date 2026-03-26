[CmdletBinding()]
param(
    [string]$SettingsPath = "ops/aws/deploy.settings.json",
    [string]$Profile,
    [string]$Region,
    [string]$GatewayName,
    [string]$GatewayRoleArn,
    [string]$GatewayOauthProviderArn,
    [string]$CognitoUserPoolId,
    [string]$CognitoClientId,
    [string]$CognitoAllowedClientIds,
    [string]$SpecialistRuntimeArn,
    [switch]$CreateGatewayIfMissing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "Deploy.Common.ps1")

function Convert-CsvToJsonArray {
    param(
        [AllowEmptyString()]
        [string]$Value
    )

    $items = @()
    foreach ($entry in [string]$Value -split ",") {
        $trimmed = $entry.Trim()
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $items += $trimmed
        }
    }

    return (ConvertTo-Json -InputObject @($items) -Compress)
}

function Get-GatewayIfExists {
    param(
        [string]$GatewayId,
        [string]$Profile,
        [string]$Region
    )

    if ([string]::IsNullOrWhiteSpace($GatewayId)) {
        return $null
    }

    $result = Invoke-AwsCliRaw -Arguments @("bedrock-agentcore-control", "get-gateway", "--gateway-identifier", $GatewayId) -Profile $Profile -Region $Region -JsonOutput
    if ($result.ExitCode -ne 0) {
        if ($result.Output -match "ResourceNotFoundException" -or $result.Output -match "ValidationException") {
            return $null
        }
        throw "Failed to query gateway '$GatewayId':`n$($result.Output)"
    }

    return $result.Output | ConvertFrom-Json
}

function New-GatewayFromTemplate {
    param(
        [Parameter(Mandatory = $true)]
        $Settings,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [Parameter(Mandatory = $true)]
        [string]$GatewayName,
        [Parameter(Mandatory = $true)]
        [string]$GatewayRoleArn,
        [Parameter(Mandatory = $true)]
        [string]$CognitoDiscoveryUrl,
        [Parameter(Mandatory = $true)]
        [string]$CognitoAllowedClientsJson
    )

    $templatePath = $Settings.gateway.createTemplatePath
    $rendered = Render-TemplateText -TemplatePath $templatePath -Replacements @{
        "REPLACE_ME_UNIQUE_GATEWAY_CLIENT_TOKEN" = (New-ClientToken -Prefix "gateway")
        "REPLACE_ME_GATEWAY_NAME" = $GatewayName
        "REPLACE_ME_GATEWAY_ROLE_ARN" = $GatewayRoleArn
        "REPLACE_ME_COGNITO_DISCOVERY_URL" = $CognitoDiscoveryUrl
        "REPLACE_ME_COGNITO_ALLOWED_CLIENTS_JSON" = $CognitoAllowedClientsJson
    }

    $tempPath = Write-JsonTempFile -Object ($rendered | ConvertFrom-Json) -FileStem "gateway-create"
    try {
        Write-Host "Creating gateway from $templatePath"
        $response = Invoke-AwsCliJson -Arguments @(
            "bedrock-agentcore-control",
            "create-gateway",
            "--cli-input-json",
            "file://$tempPath"
        ) -Profile $Profile -Region $Region

        $gatewayId = $response.gatewayId
        if ([string]::IsNullOrWhiteSpace($gatewayId)) {
            $gatewayId = $response.gatewayIdentifier
        }
        if ([string]::IsNullOrWhiteSpace($gatewayId) -and $response.gatewayArn -match "gateway/(.+)$") {
            $gatewayId = $Matches[1]
        }
        if ([string]::IsNullOrWhiteSpace($gatewayId)) {
            throw "Gateway was created but the response did not include a gateway id."
        }

        Write-Warning "Gateway '$gatewayId' was created. Copy it into ops/aws/deploy.settings.json to keep future deploys pinned."
        return Get-GatewayIfExists -GatewayId $gatewayId -Profile $Profile -Region $Region
    }
    finally {
        $tempRoot = Split-Path -Path $tempPath -Parent
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

function Get-GatewayTargetByName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GatewayId,
        [Parameter(Mandatory = $true)]
        [string]$TargetName,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    $response = Invoke-AwsCliJson -Arguments @(
        "bedrock-agentcore-control",
        "list-gateway-targets",
        "--gateway-identifier",
        $GatewayId,
        "--no-paginate"
    ) -Profile $Profile -Region $Region

    if (-not $response -or -not $response.items) {
        return $null
    }

    return $response.items | Where-Object { $_.name -eq $TargetName } | Select-Object -First 1
}

function Wait-GatewayTargetReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GatewayId,
        [Parameter(Mandatory = $true)]
        [string]$TargetId,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    while ($true) {
        Start-Sleep -Seconds 10
        $target = Invoke-AwsCliJson -Arguments @(
            "bedrock-agentcore-control",
            "get-gateway-target",
            "--gateway-identifier",
            $GatewayId,
            "--target-id",
            $TargetId
        ) -Profile $Profile -Region $Region

        Write-Host "Gateway target $TargetId -> $($target.status)"
        switch ($target.status) {
            "READY" { return $target }
            "FAILED" { throw "Gateway target '$TargetId' failed." }
            "UPDATE_UNSUCCESSFUL" { throw "Gateway target '$TargetId' update failed." }
            "SYNCHRONIZE_UNSUCCESSFUL" { throw "Gateway target '$TargetId' synchronize failed." }
        }
    }
}

$settings = Get-DeploySettings -SettingsPath $SettingsPath
$resolvedProfile = Resolve-DeploySetting -ExplicitValue $Profile -DefaultValue $settings.profile -Name "AWS profile" -Required
$resolvedRegion = Resolve-DeploySetting -ExplicitValue $Region -DefaultValue $settings.region -Name "AWS region" -Required
$resolvedGatewayOauthProviderArn = Resolve-DeploySetting -ExplicitValue $GatewayOauthProviderArn -EnvironmentNames @("DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN", "GATEWAY_OAUTH_PROVIDER_ARN") -Name "gateway oauth provider arn" -Required

$gatewayId = ""
if ($settings.gateway -and $settings.gateway.id) {
    $gatewayId = $settings.gateway.id
}

$gateway = Get-GatewayIfExists -GatewayId $gatewayId -Profile $resolvedProfile -Region $resolvedRegion
if (-not $gateway) {
    if (-not $CreateGatewayIfMissing) {
        throw "Gateway '$gatewayId' was not found. Pass -CreateGatewayIfMissing or update ops/aws/deploy.settings.json."
    }
    $resolvedGatewayName = Resolve-DeploySetting -ExplicitValue $GatewayName -EnvironmentNames @("DEPLOY_GATEWAY_NAME", "GATEWAY_NAME") -Name "gateway name" -Required
    $resolvedGatewayRoleArn = Resolve-DeploySetting -ExplicitValue $GatewayRoleArn -EnvironmentNames @("DEPLOY_GATEWAY_ROLE_ARN", "GATEWAY_ROLE_ARN") -Name "gateway role arn" -Required
    $resolvedCognitoUserPoolId = Resolve-DeploySetting -ExplicitValue $CognitoUserPoolId -EnvironmentNames @("DEPLOY_COGNITO_USER_POOL_ID", "COGNITO_USER_POOL_ID") -Name "COGNITO_USER_POOL_ID" -Required
    $resolvedCognitoClientId = Resolve-DeploySetting -ExplicitValue $CognitoClientId -EnvironmentNames @("DEPLOY_COGNITO_CLIENT_ID", "COGNITO_CLIENT_ID") -Name "COGNITO_CLIENT_ID" -Required
    $resolvedCognitoAllowedClientIds = Resolve-DeploySetting -ExplicitValue $CognitoAllowedClientIds -EnvironmentNames @("DEPLOY_COGNITO_ALLOWED_CLIENT_IDS", "COGNITO_ALLOWED_CLIENT_IDS") -DefaultValue $resolvedCognitoClientId -Name "COGNITO_ALLOWED_CLIENT_IDS" -Required
    $resolvedCognitoDiscoveryUrl = "https://cognito-idp.$resolvedRegion.amazonaws.com/$resolvedCognitoUserPoolId/.well-known/openid-configuration"
    $resolvedCognitoAllowedClientsJson = Convert-CsvToJsonArray -Value $resolvedCognitoAllowedClientIds
    $gateway = New-GatewayFromTemplate -Settings $settings -Profile $resolvedProfile -Region $resolvedRegion -GatewayName $resolvedGatewayName -GatewayRoleArn $resolvedGatewayRoleArn -CognitoDiscoveryUrl $resolvedCognitoDiscoveryUrl -CognitoAllowedClientsJson $resolvedCognitoAllowedClientsJson
    $gatewayId = $gateway.gatewayId
    if ([string]::IsNullOrWhiteSpace($gatewayId) -and $gateway.gatewayArn -match "gateway/(.+)$") {
        $gatewayId = $Matches[1]
    }
}

if ([string]::IsNullOrWhiteSpace($SpecialistRuntimeArn)) {
    $manifest = Get-RuntimeManifest -ManifestPath (Get-RuntimeManifestPath -Name "Specialist")
    $runtime = Get-AgentRuntimeIfExists -RuntimeId $manifest.runtimeId -Profile $resolvedProfile -Region $resolvedRegion
    if (-not $runtime) {
        throw "Specialist runtime '$($manifest.runtimeId)' was not found. Pass -SpecialistRuntimeArn or deploy specialist first."
    }
    $SpecialistRuntimeArn = $runtime.agentRuntimeArn
}

$encodedRuntimeArn = [System.Uri]::EscapeDataString($SpecialistRuntimeArn)
$targetTemplateText = Render-TemplateText -TemplatePath $settings.gateway.targetTemplatePath -Replacements @{
    "REPLACE_ME_GATEWAY_ID" = $gatewayId
    "REPLACE_ME_AWS_REGION" = $resolvedRegion
    "REPLACE_ME_URLENCODED_SPECIALIST_RUNTIME_ARN" = $encodedRuntimeArn
    "REPLACE_ME_UNIQUE_TARGET_CLIENT_TOKEN" = (New-ClientToken -Prefix "gateway-target")
    "REPLACE_ME_GATEWAY_OAUTH_PROVIDER_ARN" = $resolvedGatewayOauthProviderArn
}
$renderedTarget = $targetTemplateText | ConvertFrom-Json
$existingTarget = Get-GatewayTargetByName -GatewayId $gatewayId -TargetName $renderedTarget.name -Profile $resolvedProfile -Region $resolvedRegion

if ($existingTarget) {
    $updateInput = [ordered]@{
        gatewayIdentifier                = $gatewayId
        targetId                         = $existingTarget.targetId
        name                             = $renderedTarget.name
        description                      = $renderedTarget.description
        targetConfiguration              = $renderedTarget.targetConfiguration
        credentialProviderConfigurations = $renderedTarget.credentialProviderConfigurations
    }

    $updatePath = Write-JsonTempFile -Object $updateInput -FileStem "gateway-target-update"
    try {
        Write-Host "Updating gateway target '$($renderedTarget.name)' ($($existingTarget.targetId))"
        Invoke-AwsCliJson -Arguments @(
            "bedrock-agentcore-control",
            "update-gateway-target",
            "--gateway-identifier",
            $gatewayId,
            "--target-id",
            $existingTarget.targetId,
            "--cli-input-json",
            "file://$updatePath"
        ) -Profile $resolvedProfile -Region $resolvedRegion | Out-Null
        $targetId = $existingTarget.targetId
    }
    finally {
        $tempRoot = Split-Path -Path $updatePath -Parent
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}
else {
    $createPath = Write-JsonTempFile -Object $renderedTarget -FileStem "gateway-target-create"
    try {
        Write-Host "Creating gateway target '$($renderedTarget.name)'"
        $createResponse = Invoke-AwsCliJson -Arguments @(
            "bedrock-agentcore-control",
            "create-gateway-target",
            "--cli-input-json",
            "file://$createPath"
        ) -Profile $resolvedProfile -Region $resolvedRegion
        $targetId = $createResponse.targetId
    }
    finally {
        $tempRoot = Split-Path -Path $createPath -Parent
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

Wait-GatewayTargetReady -GatewayId $gatewayId -TargetId $targetId -Profile $resolvedProfile -Region $resolvedRegion | Out-Null
Write-Host "Synchronizing gateway target '$targetId'"
Invoke-AwsCliJson -Arguments @(
    "bedrock-agentcore-control",
    "synchronize-gateway-targets",
    "--gateway-identifier",
    $gatewayId,
    "--target-id-list",
    $targetId
) -Profile $resolvedProfile -Region $resolvedRegion | Out-Null

$readyTarget = Wait-GatewayTargetReady -GatewayId $gatewayId -TargetId $targetId -Profile $resolvedProfile -Region $resolvedRegion
[pscustomobject]@{
    GatewayId            = $gatewayId
    GatewayEndpoint      = Get-GatewayEndpointFromId -GatewayId $gatewayId -Region $resolvedRegion
    TargetId             = $targetId
    TargetName           = $renderedTarget.name
    TargetStatus         = $readyTarget.status
    SpecialistRuntimeArn = $SpecialistRuntimeArn
}
