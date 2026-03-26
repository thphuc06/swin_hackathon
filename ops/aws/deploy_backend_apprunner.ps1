[CmdletBinding()]
param(
    [string]$SettingsPath = "ops/aws/deploy.settings.json",
    [string]$ManifestPath = "ops/aws/backend.apprunner.manifest.json",
    [string]$Profile,
    [string]$Region,
    [string]$ImageTag,
    [string]$ServiceName,
    [string]$ServiceArn,
    [string]$ImageRepoUri,
    [string]$CognitoUserPoolId,
    [string]$CognitoClientId,
    [string]$CognitoAllowedClientIds,
    [string]$AgentcoreRuntimeArn,
    [string]$EcrAccessRoleArn,
    [switch]$CreateIfMissing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "Deploy.Common.ps1")

function Get-BackendManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath
    )

    $fullPath = Join-RepoPath $ManifestPath
    return Get-Content -LiteralPath $fullPath -Raw | ConvertFrom-Json
}

function Get-PlaceholderSafeValue {
    param(
        [AllowEmptyString()]
        [string]$Value
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }

    $trimmed = $Value.Trim()
    if ($trimmed -match "^REPLACE_ME_[A-Z0-9_]+$") {
        return ""
    }

    return $trimmed
}

function Get-AppRunnerServiceIfExists {
    param(
        [AllowEmptyString()]
        [string]$ServiceArn,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    if ([string]::IsNullOrWhiteSpace($ServiceArn)) {
        return $null
    }

    $result = Invoke-AwsCliRaw -Arguments @("apprunner", "describe-service", "--service-arn", $ServiceArn) -Profile $Profile -Region $Region -JsonOutput
    if ($result.ExitCode -ne 0) {
        if ($result.Output -match "ResourceNotFoundException" -or $result.Output -match "InvalidRequestException") {
            return $null
        }
        throw "Failed to query App Runner service '$ServiceArn':`n$($result.Output)"
    }

    return $result.Output | ConvertFrom-Json
}

function Wait-AppRunnerServiceRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceArn,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    while ($true) {
        Start-Sleep -Seconds 10
        $service = Invoke-AwsCliJson -Arguments @("apprunner", "describe-service", "--service-arn", $ServiceArn) -Profile $Profile -Region $Region
        $status = $service.Service.Status
        Write-Host "App Runner service $($service.Service.ServiceName) -> $status"

        switch ($status) {
            "RUNNING" { return $service.Service }
            "CREATE_FAILED" { throw "App Runner service '$ServiceArn' creation failed." }
            "DELETE_FAILED" { throw "App Runner service '$ServiceArn' delete failed." }
            "DELETED" { throw "App Runner service '$ServiceArn' was deleted during deployment." }
        }
    }
}

function Invoke-EcrLogin {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ImageRepoUri,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    $registry = ($ImageRepoUri -split "/")[0]
    if ([string]::IsNullOrWhiteSpace($registry)) {
        throw "Unable to resolve ECR registry from '$ImageRepoUri'."
    }

    $login = Invoke-AwsCliRaw -Arguments @("ecr", "get-login-password") -Profile $Profile -Region $Region
    if ($login.ExitCode -ne 0) {
        throw "Failed to obtain ECR login password:`n$($login.Output)"
    }

    $password = $login.Output.Trim()
    if ([string]::IsNullOrWhiteSpace($password)) {
        throw "AWS CLI returned an empty ECR login password."
    }

    $password | docker login --username AWS --password-stdin $registry
    if ($LASTEXITCODE -ne 0) {
        throw "docker login failed for ECR registry '$registry'."
    }
}

function Invoke-DockerBuildAndPush {
    param(
        [Parameter(Mandatory = $true)]
        $Manifest,
        [Parameter(Mandatory = $true)]
        [string]$ResolvedImageRepoUri,
        [Parameter(Mandatory = $true)]
        [string]$ImageUri,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    Invoke-EcrLogin -ImageRepoUri $ResolvedImageRepoUri -Profile $Profile -Region $Region

    $repoRoot = Get-RepoRoot
    $dockerfilePath = Join-RepoPath $Manifest.dockerfilePath
    $dockerPlatform = [string]$Manifest.dockerPlatform

    Write-Host "Building backend image $ImageUri"
    if ([string]::IsNullOrWhiteSpace($dockerPlatform)) {
        & docker build -t $ImageUri -f $dockerfilePath $repoRoot
    }
    else {
        & docker build --platform $dockerPlatform -t $ImageUri -f $dockerfilePath $repoRoot
    }
    if ($LASTEXITCODE -ne 0) {
        throw "docker build failed for backend image '$ImageUri'."
    }

    Write-Host "Pushing backend image $ImageUri"
    & docker push $ImageUri
    if ($LASTEXITCODE -ne 0) {
        throw "docker push failed for backend image '$ImageUri'."
    }
}

function New-AppRunnerInputFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TemplatePath,
        [Parameter(Mandatory = $true)]
        [hashtable]$Replacements,
        [Parameter(Mandatory = $true)]
        [string]$FileStem
    )

    $rendered = Render-TemplateText -TemplatePath $TemplatePath -Replacements $Replacements
    return Write-JsonTempFile -Object ($rendered | ConvertFrom-Json) -FileStem $FileStem
}

$settings = Get-DeploySettings -SettingsPath $SettingsPath
$manifest = Get-BackendManifest -ManifestPath $ManifestPath

$resolvedProfile = Resolve-DeploySetting -ExplicitValue $Profile -DefaultValue $settings.profile -Name "AWS profile" -Required
$resolvedRegion = Resolve-DeploySetting -ExplicitValue $Region -DefaultValue $settings.region -Name "AWS region" -Required
$resolvedImageTag = Get-DeployImageTag -ExplicitTag $ImageTag -Suffix ([string]$manifest.defaultImageTagSuffix)
$resolvedServiceName = Resolve-DeploySetting -ExplicitValue $ServiceName -EnvironmentNames @("DEPLOY_BACKEND_SERVICE_NAME", "BACKEND_SERVICE_NAME") -DefaultValue (Get-PlaceholderSafeValue -Value ([string]$manifest.serviceName)) -Name "backend service name"
$resolvedServiceArn = Resolve-DeploySetting -ExplicitValue $ServiceArn -EnvironmentNames @("DEPLOY_BACKEND_SERVICE_ARN", "BACKEND_SERVICE_ARN") -DefaultValue (Get-PlaceholderSafeValue -Value ([string]$manifest.serviceArn)) -Name "backend service arn"
$resolvedImageRepoUri = Resolve-DeploySetting -ExplicitValue $ImageRepoUri -EnvironmentNames @("DEPLOY_BACKEND_IMAGE_REPO_URI", "BACKEND_IMAGE_REPO_URI") -DefaultValue (Get-PlaceholderSafeValue -Value ([string]$manifest.imageRepoUri)) -Name "backend image repo uri" -Required
$resolvedAppEnv = Resolve-DeploySetting -ExplicitValue "" -EnvironmentNames @("DEPLOY_APP_ENV", "APP_ENV") -DefaultValue ([string]$settings.appEnv) -Name "APP_ENV" -Required
$resolvedCognitoUserPoolId = Resolve-DeploySetting -ExplicitValue $CognitoUserPoolId -EnvironmentNames @("DEPLOY_COGNITO_USER_POOL_ID", "COGNITO_USER_POOL_ID") -Name "COGNITO_USER_POOL_ID" -Required
$resolvedCognitoClientId = Resolve-DeploySetting -ExplicitValue $CognitoClientId -EnvironmentNames @("DEPLOY_COGNITO_CLIENT_ID", "COGNITO_CLIENT_ID") -Name "COGNITO_CLIENT_ID" -Required
$resolvedCognitoAllowedClientIds = Resolve-DeploySetting -ExplicitValue $CognitoAllowedClientIds -EnvironmentNames @("DEPLOY_COGNITO_ALLOWED_CLIENT_IDS", "COGNITO_ALLOWED_CLIENT_IDS") -DefaultValue $resolvedCognitoClientId -Name "COGNITO_ALLOWED_CLIENT_IDS" -Required
$resolvedAgentcoreRuntimeArn = Resolve-DeploySetting -ExplicitValue $AgentcoreRuntimeArn -EnvironmentNames @("DEPLOY_AGENTCORE_RUNTIME_ARN", "AGENTCORE_RUNTIME_ARN") -Name "AGENTCORE_RUNTIME_ARN" -Required
$resolvedEcrAccessRoleArn = Resolve-DeploySetting -ExplicitValue $EcrAccessRoleArn -EnvironmentNames @("DEPLOY_APPRUNNER_ECR_ACCESS_ROLE_ARN", "APPRUNNER_ECR_ACCESS_ROLE_ARN") -Name "App Runner ECR access role ARN" -Required
$imageUri = "${resolvedImageRepoUri}:$resolvedImageTag"

Write-Host "Backend App Runner deploy"
Write-Host "AWS profile: $resolvedProfile"
Write-Host "AWS region: $resolvedRegion"
Write-Host "Image tag: $resolvedImageTag"
Write-Host "Image URI: $imageUri"

Invoke-DockerBuildAndPush -Manifest $manifest -ResolvedImageRepoUri $resolvedImageRepoUri -ImageUri $imageUri -Profile $resolvedProfile -Region $resolvedRegion

$replacements = @{
  "REPLACE_ME_BACKEND_SERVICE_NAME" = $resolvedServiceName
  "REPLACE_ME_BACKEND_SERVICE_ARN" = $resolvedServiceArn
  "REPLACE_ME_BACKEND_IMAGE_REPO_URI" = $resolvedImageRepoUri
  "REPLACE_ME_IMAGE_TAG" = $resolvedImageTag
  "REPLACE_ME_APP_ENV" = $resolvedAppEnv
  "REPLACE_ME_AWS_REGION" = $resolvedRegion
  "REPLACE_ME_COGNITO_USER_POOL_ID" = $resolvedCognitoUserPoolId
  "REPLACE_ME_COGNITO_CLIENT_ID" = $resolvedCognitoClientId
  "REPLACE_ME_COGNITO_ALLOWED_CLIENT_IDS" = $resolvedCognitoAllowedClientIds
  "REPLACE_ME_AGENTCORE_RUNTIME_ARN" = $resolvedAgentcoreRuntimeArn
  "REPLACE_ME_APPRUNNER_ECR_ACCESS_ROLE_ARN" = $resolvedEcrAccessRoleArn
}

$existingService = Get-AppRunnerServiceIfExists -ServiceArn $resolvedServiceArn -Profile $resolvedProfile -Region $resolvedRegion

if ($existingService) {
    $inputPath = New-AppRunnerInputFile -TemplatePath $manifest.updateTemplatePath -Replacements $replacements -FileStem "backend-apprunner-update"
    try {
        Write-Host "Updating App Runner service $resolvedServiceArn"
        $response = Invoke-AwsCliJson -Arguments @(
            "apprunner",
            "update-service",
            "--cli-input-json",
            "file://$inputPath"
        ) -Profile $resolvedProfile -Region $resolvedRegion
        $serviceArnForWait = $response.Service.ServiceArn
    }
    finally {
        $tempRoot = Split-Path -Path $inputPath -Parent
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}
else {
    if (-not $CreateIfMissing) {
        if ([string]::IsNullOrWhiteSpace($resolvedServiceArn)) {
            throw "App Runner service ARN is required for update-only mode. Set DEPLOY_BACKEND_SERVICE_ARN or pass -CreateIfMissing."
        }
        throw "App Runner service '$resolvedServiceArn' was not found. Pass -CreateIfMissing to create it."
    }

    if ([string]::IsNullOrWhiteSpace($resolvedServiceName)) {
        throw "App Runner service name is required for create mode. Set DEPLOY_BACKEND_SERVICE_NAME or pass -ServiceName."
    }

    $inputPath = New-AppRunnerInputFile -TemplatePath $manifest.createTemplatePath -Replacements $replacements -FileStem "backend-apprunner-create"
    try {
        Write-Host "Creating App Runner service $resolvedServiceName"
        $response = Invoke-AwsCliJson -Arguments @(
            "apprunner",
            "create-service",
            "--cli-input-json",
            "file://$inputPath"
        ) -Profile $resolvedProfile -Region $resolvedRegion
        $serviceArnForWait = $response.Service.ServiceArn
    }
    finally {
        $tempRoot = Split-Path -Path $inputPath -Parent
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

$service = Wait-AppRunnerServiceRunning -ServiceArn $serviceArnForWait -Profile $resolvedProfile -Region $resolvedRegion
[pscustomobject]@{
    ServiceArn  = $service.ServiceArn
    ServiceName = $service.ServiceName
    ServiceUrl  = $service.ServiceUrl
    Status      = $service.Status
    ImageUri    = $imageUri
}
