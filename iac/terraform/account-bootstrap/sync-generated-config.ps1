[CmdletBinding()]
param(
    [string]$GeneratedDir = "generated",
    [string]$RepoRoot = "",
    [switch]$NoBackup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
    param([string]$ExplicitRepoRoot)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitRepoRoot)) {
        return [System.IO.Path]::GetFullPath($ExplicitRepoRoot)
    }

    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
}

function Assert-UnderRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd("\") + "\"
    if (-not $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to write outside repo root: $fullPath"
    }
    return $fullPath
}

function Copy-GeneratedFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,
        [Parameter(Mandatory = $true)]
        [string]$BackupSuffix,
        [switch]$NoBackup
    )

    $resolvedSource = [System.IO.Path]::GetFullPath($Source)
    if (-not (Test-Path -LiteralPath $resolvedSource)) {
        throw "Generated file not found: $resolvedSource. Run terraform apply first."
    }

    $resolvedDestination = Assert-UnderRoot -Path $Destination -Root $RepoRoot
    $destinationDirectory = Split-Path -Path $resolvedDestination -Parent
    if (-not (Test-Path -LiteralPath $destinationDirectory)) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
    }

    if ((Test-Path -LiteralPath $resolvedDestination) -and -not $NoBackup) {
        $backupPath = "$resolvedDestination.$BackupSuffix.bak"
        Copy-Item -LiteralPath $resolvedDestination -Destination $backupPath -Force
        Write-Host "Backed up $resolvedDestination -> $backupPath"
    }

    Copy-Item -LiteralPath $resolvedSource -Destination $resolvedDestination -Force
    Write-Host "Synced $resolvedSource -> $resolvedDestination"
}

$repo = Resolve-RepoRoot -ExplicitRepoRoot $RepoRoot
$generated = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $GeneratedDir))
$backupSuffix = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")

Copy-GeneratedFile -Source (Join-Path $generated "deploy.settings.json") -Destination (Join-Path $repo "ops\aws\deploy.settings.terraform.json") -RepoRoot $repo -BackupSuffix $backupSuffix -NoBackup:$NoBackup
Copy-GeneratedFile -Source (Join-Path $generated "orchestrator.runtime.manifest.json") -Destination (Join-Path $repo "ops\aws\orchestrator.runtime.manifest.json") -RepoRoot $repo -BackupSuffix $backupSuffix -NoBackup:$NoBackup
Copy-GeneratedFile -Source (Join-Path $generated "specialist.runtime.manifest.json") -Destination (Join-Path $repo "ops\aws\specialist.runtime.manifest.json") -RepoRoot $repo -BackupSuffix $backupSuffix -NoBackup:$NoBackup
Copy-GeneratedFile -Source (Join-Path $generated "backend.ecs.manifest.json") -Destination (Join-Path $repo "ops\aws\backend.ecs.manifest.terraform.json") -RepoRoot $repo -BackupSuffix $backupSuffix -NoBackup:$NoBackup

Write-Host ""
Write-Host "Terraform-generated config is synced."
Write-Host "Next from repo root:"
Write-Host "  . iac\terraform\account-bootstrap\generated\deploy.env.ps1"
Write-Host "  `$env:DEPLOY_SUPABASE_URL = 'https://...'"
Write-Host "  `$env:DEPLOY_SUPABASE_SERVICE_ROLE_KEY = '...'"
Write-Host "  `$env:DEPLOY_GATEWAY_OAUTH_PROVIDER_ARN = 'arn:aws:bedrock-agentcore:...'"
Write-Host "  .\ops\aws\deploy_full_aws.ps1 -SettingsPath ops/aws/deploy.settings.terraform.json -CreateGatewayIfMissing"
