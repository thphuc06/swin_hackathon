Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-RepoRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Join-RepoPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    return [System.IO.Path]::GetFullPath((Join-Path (Get-RepoRoot) $RelativePath))
}

function Get-DeploySettings {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SettingsPath
    )

    $fullPath = Join-RepoPath $SettingsPath
    return Get-Content -LiteralPath $fullPath -Raw | ConvertFrom-Json
}

function Get-RuntimeManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath
    )

    $fullPath = Join-RepoPath $ManifestPath
    return Get-Content -LiteralPath $fullPath -Raw | ConvertFrom-Json
}

function Get-RuntimeManifestPath {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Specialist", "Orchestrator")]
        [string]$Name
    )

    switch ($Name) {
        "Specialist" { return "ops/aws/specialist.runtime.manifest.json" }
        "Orchestrator" { return "ops/aws/orchestrator.runtime.manifest.json" }
    }
}

function Resolve-DeploySetting {
    param(
        [AllowEmptyString()]
        [string]$ExplicitValue,
        [AllowEmptyCollection()]
        [string[]]$EnvironmentNames = @(),
        [AllowEmptyString()]
        [string]$DefaultValue = "",
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [switch]$Required
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitValue)) {
        return $ExplicitValue.Trim()
    }

    foreach ($envName in $EnvironmentNames) {
        $value = [Environment]::GetEnvironmentVariable($envName)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($DefaultValue)) {
        return $DefaultValue.Trim()
    }

    if ($Required) {
        throw "Missing required value for $Name. Pass it as a script parameter or set one of: $($EnvironmentNames -join ', ')"
    }

    return ""
}

function New-DeployTempDirectory {
    $path = Join-Path ([System.IO.Path]::GetTempPath()) ("agentcore-deploy-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $path -Force | Out-Null
    return $path
}

function Should-SkipBuildContextFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $normalized = ($RelativePath -replace "\\", "/").TrimStart("./")
    $segments = $normalized -split "/"
    $leaf = Split-Path -Path $normalized -Leaf

    $blockedSegments = @(".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache")
    foreach ($segment in $segments) {
        if ($blockedSegments -contains $segment) {
            return $true
        }
    }

    if ($leaf -like ".env*" -or $leaf -like "*.pyc" -or $leaf -like "*.pyo") {
        return $true
    }

    return $false
}

function New-BuildSourceArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceRoot,
        [Parameter(Mandatory = $true)]
        [string]$BuildspecPath,
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath
    )

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $sourceRootFull = Join-RepoPath $SourceRoot
    $buildspecFull = Join-RepoPath $BuildspecPath
    $stageRoot = New-DeployTempDirectory

    try {
        Get-ChildItem -LiteralPath $sourceRootFull -Recurse -File -Force | ForEach-Object {
            $relativePath = $_.FullName.Substring($sourceRootFull.TrimEnd("\").Length + 1)
            if (Should-SkipBuildContextFile -RelativePath $relativePath) {
                return
            }

            $destinationPath = Join-Path $stageRoot $relativePath
            $destinationDirectory = Split-Path -Path $destinationPath -Parent
            if (-not (Test-Path -LiteralPath $destinationDirectory)) {
                New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
            }
            Copy-Item -LiteralPath $_.FullName -Destination $destinationPath -Force
        }

        Copy-Item -LiteralPath $buildspecFull -Destination (Join-Path $stageRoot "buildspec.yml") -Force

        if (Test-Path -LiteralPath $ArchivePath) {
            Remove-Item -LiteralPath $ArchivePath -Force
        }

        $archive = [System.IO.Compression.ZipFile]::Open($ArchivePath, [System.IO.Compression.ZipArchiveMode]::Create)
        try {
            Get-ChildItem -LiteralPath $stageRoot -Recurse -File | ForEach-Object {
                $entryName = $_.FullName.Substring($stageRoot.TrimEnd("\").Length + 1).Replace("\", "/")
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $archive,
                    $_.FullName,
                    $entryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        if (Test-Path -LiteralPath $stageRoot) {
            Remove-Item -LiteralPath $stageRoot -Recurse -Force
        }
    }
}

function Invoke-AwsCliRaw {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [switch]$JsonOutput
    )

    $command = @($Arguments)
    $command += @("--profile", $Profile, "--region", $Region, "--no-cli-pager")
    if ($JsonOutput) {
        $command += @("--output", "json")
    }

    $priorErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = & aws @command 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $priorErrorActionPreference
    }

    $text = (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output   = $text
    }
}

function Invoke-AwsCliJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    $result = Invoke-AwsCliRaw -Arguments $Arguments -Profile $Profile -Region $Region -JsonOutput
    if ($result.ExitCode -ne 0) {
        throw "AWS CLI failed:`naws $($Arguments -join ' ')`n$($result.Output)"
    }

    if ([string]::IsNullOrWhiteSpace($result.Output)) {
        return $null
    }

    return $result.Output | ConvertFrom-Json
}

function New-ClientToken {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prefix
    )

    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddHHmmss")
    $suffix = [guid]::NewGuid().ToString("N")
    return "$Prefix-$timestamp-$suffix"
}

function Get-DeployImageTag {
    param(
        [AllowEmptyString()]
        [string]$ExplicitTag,
        [AllowEmptyString()]
        [string]$Suffix = "arm64"
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitTag)) {
        return $ExplicitTag.Trim()
    }

    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
    return "$timestamp-$Suffix"
}

function Wait-CodeBuildBuild {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BuildId,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    while ($true) {
        Start-Sleep -Seconds 10
        $statusResponse = Invoke-AwsCliJson -Arguments @("codebuild", "batch-get-builds", "--ids", $BuildId) -Profile $Profile -Region $Region
        if (-not $statusResponse.builds -or $statusResponse.builds.Count -eq 0) {
            throw "Unable to find CodeBuild build '$BuildId'."
        }

        $build = $statusResponse.builds[0]
        $phase = $build.currentPhase
        $status = $build.buildStatus
        Write-Host "CodeBuild $BuildId -> $status ($phase)"

        switch ($status) {
            "SUCCEEDED" { return $build }
            "FAILED" { throw "CodeBuild failed for '$BuildId'." }
            "FAULT" { throw "CodeBuild faulted for '$BuildId'." }
            "TIMED_OUT" { throw "CodeBuild timed out for '$BuildId'." }
            "STOPPED" { throw "CodeBuild was stopped for '$BuildId'." }
        }
    }
}

function Invoke-CodeBuildImageBuild {
    param(
        [Parameter(Mandatory = $true)]
        $Manifest,
        [Parameter(Mandatory = $true)]
        $Settings,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [Parameter(Mandatory = $true)]
        [string]$ImageTag,
        [AllowEmptyString()]
        [string]$DockerBuildArgs = ""
    )

    $tempRoot = New-DeployTempDirectory
    $archivePath = Join-Path $tempRoot "source.zip"

    try {
        Write-Host "Packaging $($Manifest.name) build context..."
        New-BuildSourceArchive -SourceRoot $Manifest.sourceRoot -BuildspecPath $Manifest.buildspecPath -ArchivePath $archivePath

        $s3Uri = "s3://$($Settings.sourceBucket)/$($Manifest.sourceBundleKey)"
        Write-Host "Uploading build context to $s3Uri"
        $upload = Invoke-AwsCliRaw -Arguments @("s3", "cp", $archivePath, $s3Uri) -Profile $Profile -Region $Region
        if ($upload.ExitCode -ne 0) {
            throw "Failed to upload build context for $($Manifest.name):`n$($upload.Output)"
        }

        $startArgs = @("codebuild", "start-build", "--project-name", $Manifest.codebuildProjectName, "--environment-variables-override")
        $startArgs += "name=IMAGE_TAG,value=$ImageTag,type=PLAINTEXT"
        if (-not [string]::IsNullOrWhiteSpace($DockerBuildArgs)) {
            $startArgs += "name=DOCKER_BUILD_ARGS,value=$DockerBuildArgs,type=PLAINTEXT"
        }

        Write-Host "Starting CodeBuild project $($Manifest.codebuildProjectName) with image tag $ImageTag"
        $startResponse = Invoke-AwsCliJson -Arguments $startArgs -Profile $Profile -Region $Region
        $buildId = $startResponse.build.id
        $build = Wait-CodeBuildBuild -BuildId $buildId -Profile $Profile -Region $Region

        return [pscustomobject]@{
            BuildId  = $buildId
            ImageUri = "$($Manifest.imageRepoUri):$ImageTag"
        }
    }
    finally {
        if (Test-Path -LiteralPath $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

function Render-TemplateText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TemplatePath,
        [Parameter(Mandatory = $true)]
        [hashtable]$Replacements
    )

    $templateFull = Join-RepoPath $TemplatePath
    $text = Get-Content -LiteralPath $templateFull -Raw
    foreach ($key in $Replacements.Keys) {
        $text = $text.Replace($key, [string]$Replacements[$key])
    }

    if ($text -match "REPLACE_ME_[A-Z0-9_]+") {
        throw "Template '$TemplatePath' still contains unresolved placeholders."
    }

    return $text
}

function New-RenderedRuntimeInputFile {
    param(
        [Parameter(Mandatory = $true)]
        $Manifest,
        [Parameter(Mandatory = $true)]
        [hashtable]$BindingValues
    )

    $replacements = @{}
    foreach ($property in $Manifest.templateBindings.PSObject.Properties) {
        $bindingName = $property.Name
        if (-not $BindingValues.ContainsKey($bindingName)) {
            throw "Missing template value '$bindingName' for manifest '$($Manifest.name)'."
        }
        $replacements[$property.Value] = [string]$BindingValues[$bindingName]
    }

    $renderedText = Render-TemplateText -TemplatePath $Manifest.runtimeTemplatePath -Replacements $replacements
    $tempRoot = New-DeployTempDirectory
    $outputPath = Join-Path $tempRoot "$($Manifest.name)-runtime.json"
    [System.IO.File]::WriteAllText($outputPath, $renderedText, $script:Utf8NoBom)
    return $outputPath
}

function Get-AgentRuntimeIfExists {
    param(
        [AllowEmptyString()]
        [string]$RuntimeId,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    if ([string]::IsNullOrWhiteSpace($RuntimeId)) {
        return $null
    }

    $result = Invoke-AwsCliRaw -Arguments @("bedrock-agentcore-control", "get-agent-runtime", "--agent-runtime-id", $RuntimeId) -Profile $Profile -Region $Region -JsonOutput
    if ($result.ExitCode -ne 0) {
        if ($result.Output -match "ResourceNotFoundException" -or $result.Output -match "ValidationException") {
            return $null
        }
        throw "Failed to query runtime '$RuntimeId':`n$($result.Output)"
    }

    return $result.Output | ConvertFrom-Json
}

function Write-JsonTempFile {
    param(
        [Parameter(Mandatory = $true)]
        $Object,
        [Parameter(Mandatory = $true)]
        [string]$FileStem
    )

    $tempRoot = New-DeployTempDirectory
    $outputPath = Join-Path $tempRoot "$FileStem.json"
    $json = $Object | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText($outputPath, $json, $script:Utf8NoBom)
    return $outputPath
}

function Wait-AgentRuntimeReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeId,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    while ($true) {
        Start-Sleep -Seconds 10
        $runtime = Invoke-AwsCliJson -Arguments @("bedrock-agentcore-control", "get-agent-runtime", "--agent-runtime-id", $RuntimeId) -Profile $Profile -Region $Region
        Write-Host "Runtime $RuntimeId -> $($runtime.status)"

        switch ($runtime.status) {
            "READY" { return $runtime }
            "CREATE_FAILED" { throw "Runtime '$RuntimeId' creation failed." }
            "UPDATE_FAILED" { throw "Runtime '$RuntimeId' update failed." }
        }
    }
}

function Publish-AgentRuntime {
    param(
        [Parameter(Mandatory = $true)]
        $Manifest,
        [Parameter(Mandatory = $true)]
        [string]$RenderedCreateInputPath,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    $existingRuntime = Get-AgentRuntimeIfExists -RuntimeId $Manifest.runtimeId -Profile $Profile -Region $Region
    $createInput = Get-Content -LiteralPath $RenderedCreateInputPath -Raw | ConvertFrom-Json

    if ($existingRuntime) {
        $updateInput = [ordered]@{
            agentRuntimeArtifact = $createInput.agentRuntimeArtifact
            roleArn              = $createInput.roleArn
            networkConfiguration = $createInput.networkConfiguration
            description          = $createInput.description
        }

        foreach ($field in @("authorizerConfiguration", "requestHeaderConfiguration", "protocolConfiguration", "lifecycleConfiguration", "environmentVariables", "clientToken")) {
            if ($null -ne $createInput.$field) {
                $updateInput[$field] = $createInput.$field
            }
        }

        $updatePath = Write-JsonTempFile -Object $updateInput -FileStem "$($Manifest.name)-runtime-update"
        try {
            Write-Host "Updating runtime $($Manifest.runtimeId) from image $($createInput.agentRuntimeArtifact.containerConfiguration.containerUri)"
            $updateResponse = Invoke-AwsCliJson -Arguments @(
                "bedrock-agentcore-control",
                "update-agent-runtime",
                "--agent-runtime-id",
                $Manifest.runtimeId,
                "--cli-input-json",
                "file://$updatePath"
            ) -Profile $Profile -Region $Region

            return Wait-AgentRuntimeReady -RuntimeId $updateResponse.agentRuntimeId -Profile $Profile -Region $Region
        }
        finally {
            $updateRoot = Split-Path -Path $updatePath -Parent
            if (Test-Path -LiteralPath $updateRoot) {
                Remove-Item -LiteralPath $updateRoot -Recurse -Force
            }
        }
    }

    Write-Host "Creating runtime $($Manifest.runtimeName) from image $($createInput.agentRuntimeArtifact.containerConfiguration.containerUri)"
    $createResponse = Invoke-AwsCliJson -Arguments @(
        "bedrock-agentcore-control",
        "create-agent-runtime",
        "--cli-input-json",
        "file://$RenderedCreateInputPath"
    ) -Profile $Profile -Region $Region

    $runtime = Wait-AgentRuntimeReady -RuntimeId $createResponse.agentRuntimeId -Profile $Profile -Region $Region
    Write-Warning "Runtime '$($Manifest.runtimeName)' was created with id '$($runtime.agentRuntimeId)'. Update $($Manifest.name).runtime.manifest.json to keep future updates pinned."
    return $runtime
}

function Get-GatewayEndpointFromId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$GatewayId,
        [Parameter(Mandatory = $true)]
        [string]$Region
    )

    return "https://$GatewayId.gateway.bedrock-agentcore.$Region.amazonaws.com/mcp"
}

function Invoke-RuntimeDeploymentFromManifest {
    param(
        [Parameter(Mandatory = $true)]
        $Manifest,
        [Parameter(Mandatory = $true)]
        $Settings,
        [Parameter(Mandatory = $true)]
        [string]$Profile,
        [Parameter(Mandatory = $true)]
        [string]$Region,
        [Parameter(Mandatory = $true)]
        [string]$ImageTag,
        [Parameter(Mandatory = $true)]
        [hashtable]$BindingValues,
        [AllowEmptyString()]
        [string]$DockerBuildArgs = ""
    )

    $build = Invoke-CodeBuildImageBuild -Manifest $Manifest -Settings $Settings -Profile $Profile -Region $Region -ImageTag $ImageTag -DockerBuildArgs $DockerBuildArgs
    $renderedInput = New-RenderedRuntimeInputFile -Manifest $Manifest -BindingValues $BindingValues

    try {
        $runtime = Publish-AgentRuntime -Manifest $Manifest -RenderedCreateInputPath $renderedInput -Profile $Profile -Region $Region
        return [pscustomobject]@{
            Name              = $Manifest.name
            ImageUri          = $build.ImageUri
            RuntimeId         = $runtime.agentRuntimeId
            RuntimeArn        = $runtime.agentRuntimeArn
            RuntimeVersion    = $runtime.agentRuntimeVersion
            RuntimeStatus     = $runtime.status
            CodeBuildId       = $build.BuildId
            SuggestedEnvValue = $runtime.agentRuntimeArn
        }
    }
    finally {
        $renderRoot = Split-Path -Path $renderedInput -Parent
        if (Test-Path -LiteralPath $renderRoot) {
            Remove-Item -LiteralPath $renderRoot -Recurse -Force
        }
    }
}
