[CmdletBinding()]
param(
    [ValidateSet("All", "Specialist", "Orchestrator", "Gateway")]
    [string]$Component = "All",
    [string]$SettingsPath = "ops/aws/deploy.settings.terraform.json",
    [string]$Profile,
    [string]$Region,
    [string]$ImageTag,
    [string]$BackendApiBase,
    [string]$PolicyAllowedTools,
    [string]$GatewayTimeoutSeconds,
    [string]$GatewayName,
    [string]$GatewayRoleArn,
    [string]$GatewayOauthProviderArn,
    [string]$CognitoUserPoolId,
    [string]$CognitoClientId,
    [string]$CognitoAllowedClientIds,
    [string]$CognitoServiceClientIds,
    [string]$OrchestratorRuntimeRoleArn,
    [string]$SpecialistRuntimeRoleArn,
    [string]$SupabaseUrl,
    [string]$SupabaseServiceRoleKey,
    [string]$StockAgentExternalEnabled,
    [string]$StockAgentExternalUrl,
    [string]$StockAgentExternalBaseUrl,
    [string]$StockAgentExternalEndpointPath,
    [string]$StockAgentExternalModelProvider,
    [string]$StockAgentExternalModel,
    [string]$StockAgentExternalAuthToken,
    [string]$StockAgentExternalTimeoutSeconds,
    [string]$StockAgentExternalConnectTimeoutSeconds,
    [string]$StockAgentExternalReadTimeoutSeconds,
    [switch]$InstallOptionalFinanceExtras,
    [switch]$CreateGatewayIfMissing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "Deploy.Common.ps1")

function Save-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath,
        [Parameter(Mandatory = $true)]
        $Object
    )

    $fullPath = Join-RepoPath $RelativePath
    $json = $Object | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($fullPath, $json, $script:Utf8NoBom)
}

function Save-RuntimeManifestId {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Specialist", "Orchestrator")]
        [string]$Name,
        [AllowEmptyString()]
        [string]$RuntimeId
    )

    if ([string]::IsNullOrWhiteSpace($RuntimeId)) {
        return
    }

    $manifestPath = Get-RuntimeManifestPath -Name $Name
    $manifest = Get-RuntimeManifest -ManifestPath $manifestPath
    if ([string]$manifest.runtimeId -eq $RuntimeId) {
        return
    }

    $manifest.runtimeId = $RuntimeId
    Save-JsonFile -RelativePath $manifestPath -Object $manifest
    Write-Host "Pinned $Name runtime id '$RuntimeId' in $manifestPath"
}

function Save-GatewayId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SettingsPath,
        [AllowEmptyString()]
        [string]$GatewayId
    )

    if ([string]::IsNullOrWhiteSpace($GatewayId)) {
        return
    }

    $settingsObject = Get-DeploySettings -SettingsPath $SettingsPath
    if (-not $settingsObject.gateway) {
        $settingsObject | Add-Member -MemberType NoteProperty -Name "gateway" -Value ([pscustomobject]@{})
    }

    if ([string]$settingsObject.gateway.id -eq $GatewayId) {
        return
    }

    $settingsObject.gateway.id = $GatewayId
    Save-JsonFile -RelativePath $SettingsPath -Object $settingsObject
    Write-Host "Pinned gateway id '$GatewayId' in $SettingsPath"
}

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

function Deploy-Specialist {
    param(
        [Parameter(Mandatory = $true)]
        $Settings,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [Parameter(Mandatory = $true)]
        [string]$ImageTag,
        [AllowEmptyString()]
        [string]$CognitoUserPoolId,
        [AllowEmptyString()]
        [string]$CognitoClientId,
        [AllowEmptyString()]
        [string]$CognitoAllowedClientIds,
        [AllowEmptyString()]
        [string]$CognitoServiceClientIds,
        [AllowEmptyString()]
        [string]$SpecialistRuntimeRoleArn,
        [AllowEmptyString()]
        [string]$SupabaseUrl,
        [AllowEmptyString()]
        [string]$SupabaseServiceRoleKey,
        [AllowEmptyString()]
        [string]$StockAgentExternalEnabled,
        [AllowEmptyString()]
        [string]$StockAgentExternalUrl,
        [AllowEmptyString()]
        [string]$StockAgentExternalBaseUrl,
        [AllowEmptyString()]
        [string]$StockAgentExternalEndpointPath,
        [AllowEmptyString()]
        [string]$StockAgentExternalModelProvider,
        [AllowEmptyString()]
        [string]$StockAgentExternalModel,
        [AllowEmptyString()]
        [string]$StockAgentExternalAuthToken,
        [AllowEmptyString()]
        [string]$StockAgentExternalTimeoutSeconds,
        [switch]$InstallOptionalFinanceExtras
    )

    $manifest = Get-RuntimeManifest -ManifestPath (Get-RuntimeManifestPath -Name "Specialist")
    $resolvedSupabaseUrl = Resolve-DeploySetting -ExplicitValue $SupabaseUrl -EnvironmentNames @("DEPLOY_SUPABASE_URL", "SUPABASE_URL") -Name "SUPABASE_URL" -Required
    $resolvedSupabaseServiceRoleKey = Resolve-DeploySetting -ExplicitValue $SupabaseServiceRoleKey -EnvironmentNames @("DEPLOY_SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY") -Name "SUPABASE_SERVICE_ROLE_KEY" -Required
    $resolvedAppEnv = Resolve-DeploySetting -ExplicitValue "" -EnvironmentNames @("DEPLOY_APP_ENV", "APP_ENV") -DefaultValue ([string]$Settings.appEnv) -Name "APP_ENV" -Required
    $resolvedCognitoUserPoolId = Resolve-DeploySetting -ExplicitValue $CognitoUserPoolId -EnvironmentNames @("DEPLOY_COGNITO_USER_POOL_ID", "COGNITO_USER_POOL_ID") -Name "COGNITO_USER_POOL_ID" -Required
    $resolvedCognitoClientId = Resolve-DeploySetting -ExplicitValue $CognitoClientId -EnvironmentNames @("DEPLOY_COGNITO_CLIENT_ID", "COGNITO_CLIENT_ID") -Name "COGNITO_CLIENT_ID" -Required
    $resolvedCognitoAllowedClientIds = Resolve-DeploySetting -ExplicitValue $CognitoAllowedClientIds -EnvironmentNames @("DEPLOY_COGNITO_ALLOWED_CLIENT_IDS", "COGNITO_ALLOWED_CLIENT_IDS") -DefaultValue $resolvedCognitoClientId -Name "COGNITO_ALLOWED_CLIENT_IDS" -Required
    $resolvedCognitoServiceClientIds = Resolve-DeploySetting -ExplicitValue $CognitoServiceClientIds -EnvironmentNames @("DEPLOY_COGNITO_SERVICE_CLIENT_IDS", "COGNITO_SERVICE_CLIENT_IDS") -Name "COGNITO_SERVICE_CLIENT_IDS" -Required
    $resolvedSpecialistRuntimeRoleArn = Resolve-DeploySetting -ExplicitValue $SpecialistRuntimeRoleArn -EnvironmentNames @("DEPLOY_SPECIALIST_RUNTIME_ROLE_ARN", "SPECIALIST_RUNTIME_ROLE_ARN") -Name "specialist runtime role arn" -Required
    $resolvedCognitoDiscoveryUrl = "https://cognito-idp.$Region.amazonaws.com/$resolvedCognitoUserPoolId/.well-known/openid-configuration"
    $resolvedStockAgentExternalEnabled = Resolve-DeploySetting -ExplicitValue $StockAgentExternalEnabled -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_ENABLED", "STOCK_AGENT_EXTERNAL_ENABLED") -DefaultValue "false" -Name "STOCK_AGENT_EXTERNAL_ENABLED"
    $resolvedStockAgentExternalUrl = Resolve-DeploySetting -ExplicitValue $StockAgentExternalUrl -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_URL", "STOCK_AGENT_EXTERNAL_URL") -Name "STOCK_AGENT_EXTERNAL_URL"
    $resolvedStockAgentExternalBaseUrl = Resolve-DeploySetting -ExplicitValue $StockAgentExternalBaseUrl -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_BASE_URL", "STOCK_AGENT_EXTERNAL_BASE_URL") -Name "STOCK_AGENT_EXTERNAL_BASE_URL"
    $resolvedStockAgentExternalEndpointPath = Resolve-DeploySetting -ExplicitValue $StockAgentExternalEndpointPath -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_ENDPOINT_PATH", "STOCK_AGENT_EXTERNAL_ENDPOINT_PATH") -DefaultValue "/ask" -Name "STOCK_AGENT_EXTERNAL_ENDPOINT_PATH"
    $resolvedStockAgentExternalModelProvider = Resolve-DeploySetting -ExplicitValue $StockAgentExternalModelProvider -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_MODEL_PROVIDER", "STOCK_AGENT_EXTERNAL_MODEL_PROVIDER") -DefaultValue "bedrock" -Name "STOCK_AGENT_EXTERNAL_MODEL_PROVIDER"
    $resolvedStockAgentExternalModel = Resolve-DeploySetting -ExplicitValue $StockAgentExternalModel -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_MODEL", "STOCK_AGENT_EXTERNAL_MODEL") -DefaultValue "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0" -Name "STOCK_AGENT_EXTERNAL_MODEL"
    $resolvedStockAgentExternalAuthToken = Resolve-DeploySetting -ExplicitValue $StockAgentExternalAuthToken -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_AUTH_TOKEN", "STOCK_AGENT_EXTERNAL_AUTH_TOKEN") -Name "STOCK_AGENT_EXTERNAL_AUTH_TOKEN"
    $resolvedStockAgentExternalTimeoutSeconds = Resolve-DeploySetting -ExplicitValue $StockAgentExternalTimeoutSeconds -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS", "STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS") -DefaultValue "10" -Name "STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS"

    $useOptionalFinanceExtras = $InstallOptionalFinanceExtras.IsPresent
    if (-not $useOptionalFinanceExtras -and $Settings.build.specialistOptionalFinanceExtras) {
        $useOptionalFinanceExtras = [bool]$Settings.build.specialistOptionalFinanceExtras
    }

    $dockerBuildArgs = ""
    if ($useOptionalFinanceExtras) {
        $dockerBuildArgs = "--build-arg INSTALL_OPTIONAL_FINANCE_EXTRAS=true"
    }

    return Invoke-RuntimeDeploymentFromManifest -Manifest $manifest -Settings $Settings -Profile $Profile -Region $Region -ImageTag $ImageTag -DockerBuildArgs $dockerBuildArgs -BindingValues @{
        APP_ENV                    = $resolvedAppEnv
        AWS_REGION                 = $Region
        IMAGE_TAG                  = $ImageTag
        IMAGE_REPO_URI             = [string]$manifest.imageRepoUri
        RUNTIME_ROLE_ARN           = $resolvedSpecialistRuntimeRoleArn
        CLIENT_TOKEN               = (New-ClientToken -Prefix "specialist-runtime")
        COGNITO_DISCOVERY_URL      = $resolvedCognitoDiscoveryUrl
        COGNITO_ALLOWED_CLIENTS_JSON = (Convert-CsvToJsonArray -Value $resolvedCognitoAllowedClientIds)
        COGNITO_USER_POOL_ID       = $resolvedCognitoUserPoolId
        COGNITO_CLIENT_ID          = $resolvedCognitoClientId
        COGNITO_ALLOWED_CLIENT_IDS = $resolvedCognitoAllowedClientIds
        COGNITO_SERVICE_CLIENT_IDS = $resolvedCognitoServiceClientIds
        SUPABASE_URL               = $resolvedSupabaseUrl
        SUPABASE_SERVICE_ROLE_KEY  = $resolvedSupabaseServiceRoleKey
        STOCK_AGENT_EXTERNAL_ENABLED = $resolvedStockAgentExternalEnabled
        STOCK_AGENT_EXTERNAL_URL = $resolvedStockAgentExternalUrl
        STOCK_AGENT_EXTERNAL_BASE_URL = $resolvedStockAgentExternalBaseUrl
        STOCK_AGENT_EXTERNAL_ENDPOINT_PATH = $resolvedStockAgentExternalEndpointPath
        STOCK_AGENT_EXTERNAL_MODEL_PROVIDER = $resolvedStockAgentExternalModelProvider
        STOCK_AGENT_EXTERNAL_MODEL = $resolvedStockAgentExternalModel
        STOCK_AGENT_EXTERNAL_AUTH_TOKEN = $resolvedStockAgentExternalAuthToken
        STOCK_AGENT_EXTERNAL_TIMEOUT_SECONDS = $resolvedStockAgentExternalTimeoutSeconds
    }
}

function Deploy-Orchestrator {
    param(
        [Parameter(Mandatory = $true)]
        $Settings,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [Parameter(Mandatory = $true)]
        [string]$ImageTag,
        [AllowEmptyString()]
        [string]$BackendApiBase,
        [AllowEmptyString()]
        [string]$PolicyAllowedTools,
        [AllowEmptyString()]
        [string]$GatewayTimeoutSeconds,
        [AllowEmptyString()]
        [string]$StockAgentExternalEnabled,
        [AllowEmptyString()]
        [string]$StockAgentExternalUrl,
        [AllowEmptyString()]
        [string]$StockAgentExternalBaseUrl,
        [AllowEmptyString()]
        [string]$StockAgentExternalEndpointPath,
        [AllowEmptyString()]
        [string]$StockAgentExternalAuthToken,
        [AllowEmptyString()]
        [string]$StockAgentExternalModelProvider,
        [AllowEmptyString()]
        [string]$StockAgentExternalModel,
        [AllowEmptyString()]
        [string]$StockAgentExternalConnectTimeoutSeconds,
        [AllowEmptyString()]
        [string]$StockAgentExternalReadTimeoutSeconds,
        [AllowEmptyString()]
        [string]$CognitoUserPoolId,
        [AllowEmptyString()]
        [string]$CognitoClientId,
        [AllowEmptyString()]
        [string]$CognitoAllowedClientIds,
        [AllowEmptyString()]
        [string]$OrchestratorRuntimeRoleArn,
        [Parameter(Mandatory = $true)]
        [string]$GatewayId
    )

    $manifest = Get-RuntimeManifest -ManifestPath (Get-RuntimeManifestPath -Name "Orchestrator")
    $resolvedBackendApiBase = Resolve-DeploySetting -ExplicitValue $BackendApiBase -EnvironmentNames @("DEPLOY_BACKEND_API_BASE", "BACKEND_API_BASE") -Name "BACKEND_API_BASE" -Required
    $resolvedPolicyAllowedTools = Resolve-DeploySetting -ExplicitValue $PolicyAllowedTools -EnvironmentNames @("DEPLOY_POLICY_ALLOWED_TOOLS", "POLICY_ALLOWED_TOOLS") -DefaultValue ([string]$Settings.orchestrator.policyAllowedTools) -Name "POLICY_ALLOWED_TOOLS" -Required
    $resolvedGatewayTimeoutSeconds = Resolve-DeploySetting -ExplicitValue $GatewayTimeoutSeconds -EnvironmentNames @("DEPLOY_GATEWAY_TIMEOUT_SECONDS", "GATEWAY_TIMEOUT_SECONDS") -DefaultValue ([string]$Settings.orchestrator.gatewayTimeoutSeconds) -Name "GATEWAY_TIMEOUT_SECONDS" -Required
    $resolvedStockAgentExternalEnabled = Resolve-DeploySetting -ExplicitValue $StockAgentExternalEnabled -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_ENABLED", "STOCK_AGENT_EXTERNAL_ENABLED") -DefaultValue "false" -Name "STOCK_AGENT_EXTERNAL_ENABLED"
    $resolvedStockAgentExternalUrl = Resolve-DeploySetting -ExplicitValue $StockAgentExternalUrl -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_URL", "STOCK_AGENT_EXTERNAL_URL") -Name "STOCK_AGENT_EXTERNAL_URL"
    $resolvedStockAgentExternalBaseUrl = Resolve-DeploySetting -ExplicitValue $StockAgentExternalBaseUrl -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_BASE_URL", "STOCK_AGENT_EXTERNAL_BASE_URL") -Name "STOCK_AGENT_EXTERNAL_BASE_URL"
    $resolvedStockAgentExternalEndpointPath = Resolve-DeploySetting -ExplicitValue $StockAgentExternalEndpointPath -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_ENDPOINT_PATH", "STOCK_AGENT_EXTERNAL_ENDPOINT_PATH") -DefaultValue "/ask" -Name "STOCK_AGENT_EXTERNAL_ENDPOINT_PATH"
    $resolvedStockAgentExternalAuthToken = Resolve-DeploySetting -ExplicitValue $StockAgentExternalAuthToken -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_AUTH_TOKEN", "STOCK_AGENT_EXTERNAL_AUTH_TOKEN") -Name "STOCK_AGENT_EXTERNAL_AUTH_TOKEN"
    $resolvedStockAgentExternalModelProvider = Resolve-DeploySetting -ExplicitValue $StockAgentExternalModelProvider -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_MODEL_PROVIDER", "STOCK_AGENT_EXTERNAL_MODEL_PROVIDER") -DefaultValue "bedrock" -Name "STOCK_AGENT_EXTERNAL_MODEL_PROVIDER"
    $resolvedStockAgentExternalModel = Resolve-DeploySetting -ExplicitValue $StockAgentExternalModel -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_MODEL", "STOCK_AGENT_EXTERNAL_MODEL") -DefaultValue "bedrock:us.anthropic.claude-sonnet-4-20250514-v1:0" -Name "STOCK_AGENT_EXTERNAL_MODEL"
    $resolvedStockAgentExternalConnectTimeoutSeconds = Resolve-DeploySetting -ExplicitValue $StockAgentExternalConnectTimeoutSeconds -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS", "STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS") -DefaultValue "2" -Name "STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS"
    $resolvedStockAgentExternalReadTimeoutSeconds = Resolve-DeploySetting -ExplicitValue $StockAgentExternalReadTimeoutSeconds -EnvironmentNames @("DEPLOY_STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS", "STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS") -DefaultValue "8" -Name "STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS"
    $resolvedAppEnv = Resolve-DeploySetting -ExplicitValue "" -EnvironmentNames @("DEPLOY_APP_ENV", "APP_ENV") -DefaultValue ([string]$Settings.appEnv) -Name "APP_ENV" -Required
    $resolvedCognitoUserPoolId = Resolve-DeploySetting -ExplicitValue $CognitoUserPoolId -EnvironmentNames @("DEPLOY_COGNITO_USER_POOL_ID", "COGNITO_USER_POOL_ID") -Name "COGNITO_USER_POOL_ID" -Required
    $resolvedCognitoClientId = Resolve-DeploySetting -ExplicitValue $CognitoClientId -EnvironmentNames @("DEPLOY_COGNITO_CLIENT_ID", "COGNITO_CLIENT_ID") -Name "COGNITO_CLIENT_ID" -Required
    $resolvedCognitoAllowedClientIds = Resolve-DeploySetting -ExplicitValue $CognitoAllowedClientIds -EnvironmentNames @("DEPLOY_COGNITO_ALLOWED_CLIENT_IDS", "COGNITO_ALLOWED_CLIENT_IDS") -DefaultValue $resolvedCognitoClientId -Name "COGNITO_ALLOWED_CLIENT_IDS" -Required
    $resolvedOrchestratorRuntimeRoleArn = Resolve-DeploySetting -ExplicitValue $OrchestratorRuntimeRoleArn -EnvironmentNames @("DEPLOY_ORCHESTRATOR_RUNTIME_ROLE_ARN", "ORCHESTRATOR_RUNTIME_ROLE_ARN") -Name "orchestrator runtime role arn" -Required
    $resolvedCognitoDiscoveryUrl = "https://cognito-idp.$Region.amazonaws.com/$resolvedCognitoUserPoolId/.well-known/openid-configuration"

    return Invoke-RuntimeDeploymentFromManifest -Manifest $manifest -Settings $Settings -Profile $Profile -Region $Region -ImageTag $ImageTag -BindingValues @{
        APP_ENV                    = $resolvedAppEnv
        AWS_REGION                 = $Region
        IMAGE_TAG                  = $ImageTag
        IMAGE_REPO_URI             = [string]$manifest.imageRepoUri
        RUNTIME_ROLE_ARN           = $resolvedOrchestratorRuntimeRoleArn
        CLIENT_TOKEN               = (New-ClientToken -Prefix "orchestrator-runtime")
        BACKEND_API_BASE           = $resolvedBackendApiBase
        GATEWAY_ENDPOINT           = (Get-GatewayEndpointFromId -GatewayId $GatewayId -Region $Region)
        COGNITO_DISCOVERY_URL      = $resolvedCognitoDiscoveryUrl
        COGNITO_ALLOWED_CLIENTS_JSON = (Convert-CsvToJsonArray -Value $resolvedCognitoAllowedClientIds)
        COGNITO_USER_POOL_ID       = $resolvedCognitoUserPoolId
        COGNITO_CLIENT_ID          = $resolvedCognitoClientId
        COGNITO_ALLOWED_CLIENT_IDS = $resolvedCognitoAllowedClientIds
        COGNITO_REGION             = $Region
        POLICY_ALLOWED_TOOLS       = $resolvedPolicyAllowedTools
        GATEWAY_TIMEOUT_SECONDS    = $resolvedGatewayTimeoutSeconds
        STOCK_AGENT_EXTERNAL_ENABLED = $resolvedStockAgentExternalEnabled
        STOCK_AGENT_EXTERNAL_URL = $resolvedStockAgentExternalUrl
        STOCK_AGENT_EXTERNAL_BASE_URL = $resolvedStockAgentExternalBaseUrl
        STOCK_AGENT_EXTERNAL_ENDPOINT_PATH = $resolvedStockAgentExternalEndpointPath
        STOCK_AGENT_EXTERNAL_AUTH_TOKEN = $resolvedStockAgentExternalAuthToken
        STOCK_AGENT_EXTERNAL_MODEL_PROVIDER = $resolvedStockAgentExternalModelProvider
        STOCK_AGENT_EXTERNAL_MODEL = $resolvedStockAgentExternalModel
        STOCK_AGENT_EXTERNAL_CONNECT_TIMEOUT_SECONDS = $resolvedStockAgentExternalConnectTimeoutSeconds
        STOCK_AGENT_EXTERNAL_READ_TIMEOUT_SECONDS = $resolvedStockAgentExternalReadTimeoutSeconds
    }
}

$settings = Get-DeploySettings -SettingsPath $SettingsPath
$resolvedProfile = Resolve-DeploySetting -ExplicitValue $Profile -DefaultValue $settings.profile -Name "AWS profile" -Required
$resolvedRegion = Resolve-DeploySetting -ExplicitValue $Region -DefaultValue $settings.region -Name "AWS region" -Required
$resolvedImageTag = Get-DeployImageTag -ExplicitTag $ImageTag -Suffix $settings.build.defaultImageTagSuffix

Write-Host "Deploy component: $Component"
Write-Host "AWS profile: $resolvedProfile"
Write-Host "AWS region: $resolvedRegion"
Write-Host "Image tag: $resolvedImageTag"

$specialistResult = $null
$gatewayResult = $null
$orchestratorResult = $null
$gatewayId = $settings.gateway.id

switch ($Component) {
    "All" {
        $specialistResult = Deploy-Specialist -Settings $settings -Profile $resolvedProfile -Region $resolvedRegion -ImageTag $resolvedImageTag -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -CognitoServiceClientIds $CognitoServiceClientIds -SpecialistRuntimeRoleArn $SpecialistRuntimeRoleArn -SupabaseUrl $SupabaseUrl -SupabaseServiceRoleKey $SupabaseServiceRoleKey -StockAgentExternalEnabled $StockAgentExternalEnabled -StockAgentExternalUrl $StockAgentExternalUrl -StockAgentExternalBaseUrl $StockAgentExternalBaseUrl -StockAgentExternalEndpointPath $StockAgentExternalEndpointPath -StockAgentExternalModelProvider $StockAgentExternalModelProvider -StockAgentExternalModel $StockAgentExternalModel -StockAgentExternalAuthToken $StockAgentExternalAuthToken -StockAgentExternalTimeoutSeconds $StockAgentExternalTimeoutSeconds -InstallOptionalFinanceExtras:$InstallOptionalFinanceExtras
        Save-RuntimeManifestId -Name "Specialist" -RuntimeId $specialistResult.RuntimeId
        $gatewayResult = & (Join-Path $PSScriptRoot "gateway.ps1") -SettingsPath $SettingsPath -Profile $resolvedProfile -Region $resolvedRegion -GatewayName $GatewayName -GatewayRoleArn $GatewayRoleArn -GatewayOauthProviderArn $GatewayOauthProviderArn -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -SpecialistRuntimeArn $specialistResult.RuntimeArn -CreateGatewayIfMissing:$CreateGatewayIfMissing
        $gatewayId = $gatewayResult.GatewayId
        Save-GatewayId -SettingsPath $SettingsPath -GatewayId $gatewayId
        $orchestratorResult = Deploy-Orchestrator -Settings $settings -Profile $resolvedProfile -Region $resolvedRegion -ImageTag $resolvedImageTag -BackendApiBase $BackendApiBase -PolicyAllowedTools $PolicyAllowedTools -GatewayTimeoutSeconds $GatewayTimeoutSeconds -StockAgentExternalEnabled $StockAgentExternalEnabled -StockAgentExternalUrl $StockAgentExternalUrl -StockAgentExternalBaseUrl $StockAgentExternalBaseUrl -StockAgentExternalEndpointPath $StockAgentExternalEndpointPath -StockAgentExternalAuthToken $StockAgentExternalAuthToken -StockAgentExternalModelProvider $StockAgentExternalModelProvider -StockAgentExternalModel $StockAgentExternalModel -StockAgentExternalConnectTimeoutSeconds $StockAgentExternalConnectTimeoutSeconds -StockAgentExternalReadTimeoutSeconds $StockAgentExternalReadTimeoutSeconds -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -OrchestratorRuntimeRoleArn $OrchestratorRuntimeRoleArn -GatewayId $gatewayId
        Save-RuntimeManifestId -Name "Orchestrator" -RuntimeId $orchestratorResult.RuntimeId
    }
    "Specialist" {
        $specialistResult = Deploy-Specialist -Settings $settings -Profile $resolvedProfile -Region $resolvedRegion -ImageTag $resolvedImageTag -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -CognitoServiceClientIds $CognitoServiceClientIds -SpecialistRuntimeRoleArn $SpecialistRuntimeRoleArn -SupabaseUrl $SupabaseUrl -SupabaseServiceRoleKey $SupabaseServiceRoleKey -StockAgentExternalEnabled $StockAgentExternalEnabled -StockAgentExternalUrl $StockAgentExternalUrl -StockAgentExternalBaseUrl $StockAgentExternalBaseUrl -StockAgentExternalEndpointPath $StockAgentExternalEndpointPath -StockAgentExternalModelProvider $StockAgentExternalModelProvider -StockAgentExternalModel $StockAgentExternalModel -StockAgentExternalAuthToken $StockAgentExternalAuthToken -StockAgentExternalTimeoutSeconds $StockAgentExternalTimeoutSeconds -InstallOptionalFinanceExtras:$InstallOptionalFinanceExtras
        Save-RuntimeManifestId -Name "Specialist" -RuntimeId $specialistResult.RuntimeId
        $gatewayResult = & (Join-Path $PSScriptRoot "gateway.ps1") -SettingsPath $SettingsPath -Profile $resolvedProfile -Region $resolvedRegion -GatewayName $GatewayName -GatewayRoleArn $GatewayRoleArn -GatewayOauthProviderArn $GatewayOauthProviderArn -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -SpecialistRuntimeArn $specialistResult.RuntimeArn -CreateGatewayIfMissing:$CreateGatewayIfMissing
        Save-GatewayId -SettingsPath $SettingsPath -GatewayId $gatewayResult.GatewayId
    }
    "Orchestrator" {
        $gatewayId = Resolve-DeploySetting -ExplicitValue $gatewayId -Name "gateway id" -Required
        $orchestratorResult = Deploy-Orchestrator -Settings $settings -Profile $resolvedProfile -Region $resolvedRegion -ImageTag $resolvedImageTag -BackendApiBase $BackendApiBase -PolicyAllowedTools $PolicyAllowedTools -GatewayTimeoutSeconds $GatewayTimeoutSeconds -StockAgentExternalEnabled $StockAgentExternalEnabled -StockAgentExternalUrl $StockAgentExternalUrl -StockAgentExternalBaseUrl $StockAgentExternalBaseUrl -StockAgentExternalEndpointPath $StockAgentExternalEndpointPath -StockAgentExternalAuthToken $StockAgentExternalAuthToken -StockAgentExternalModelProvider $StockAgentExternalModelProvider -StockAgentExternalModel $StockAgentExternalModel -StockAgentExternalConnectTimeoutSeconds $StockAgentExternalConnectTimeoutSeconds -StockAgentExternalReadTimeoutSeconds $StockAgentExternalReadTimeoutSeconds -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -OrchestratorRuntimeRoleArn $OrchestratorRuntimeRoleArn -GatewayId $gatewayId
        Save-RuntimeManifestId -Name "Orchestrator" -RuntimeId $orchestratorResult.RuntimeId
    }
    "Gateway" {
        $gatewayResult = & (Join-Path $PSScriptRoot "gateway.ps1") -SettingsPath $SettingsPath -Profile $resolvedProfile -Region $resolvedRegion -GatewayName $GatewayName -GatewayRoleArn $GatewayRoleArn -GatewayOauthProviderArn $GatewayOauthProviderArn -CognitoUserPoolId $CognitoUserPoolId -CognitoClientId $CognitoClientId -CognitoAllowedClientIds $CognitoAllowedClientIds -CreateGatewayIfMissing:$CreateGatewayIfMissing
        Save-GatewayId -SettingsPath $SettingsPath -GatewayId $gatewayResult.GatewayId
    }
}

Write-Host ""
Write-Host "Deployment summary"
if ($specialistResult) {
    Write-Host "- Specialist runtime: $($specialistResult.RuntimeId) @ $($specialistResult.ImageUri)"
}
if ($gatewayResult) {
    Write-Host "- Gateway target: $($gatewayResult.TargetId) on gateway $($gatewayResult.GatewayId)"
}
if ($orchestratorResult) {
    Write-Host "- Orchestrator runtime: $($orchestratorResult.RuntimeId) @ $($orchestratorResult.ImageUri)"
    Write-Host "- Backend AGENTCORE_RUNTIME_ARN: $($orchestratorResult.RuntimeArn)"
}
