param(
    [string]$BaseUrl = "http://127.0.0.1:8010",
    [string]$Token = "",
    [switch]$NoAuthHeader
)

$env:PYTHONIOENCODING = "utf-8"

$arguments = @("run_qa_tests.py", "--base-url", $BaseUrl)
if ($Token) {
    $arguments += @("--token", $Token)
}
if ($NoAuthHeader) {
    $arguments += "--no-auth-header"
}

python @arguments
exit $LASTEXITCODE
