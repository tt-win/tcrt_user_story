# Portable App Token client for Windows. Requires only Windows PowerShell 5.1
# (preinstalled on Windows 10/11) or PowerShell 7+; no Python, curl, or modules.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 check
#   powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 <METHOD> <PATH> [--data '<json>'] [--query 'k=v&k2=v2']
#   powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 POST <PATH> --file field=@C:\path\to\file [--file ...]
#
# Same interface and output contract as scripts/tcrt_api.sh: response body to
# stdout, "HTTP <status>" to stderr, nonzero exit on 4xx/5xx or network failure.
# The raw token is never printed.

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillDir = Split-Path -Parent $ScriptDir
$DefaultEnvFile = Join-Path $SkillDir '.env'

function Fail($Message) {
    [Console]::Error.WriteLine("[tcrt-app] $Message")
    exit 2
}

function Show-Usage {
    [Console]::Error.WriteLine(@'
Usage:
  powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 check
  powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 <METHOD> <PATH> [--data '<json>'] [--query 'k=v&k2=v2']
  powershell -ExecutionPolicy Bypass -File scripts/tcrt_api.ps1 POST <PATH> --file field=@C:\path\to\file [--file ...]
'@)
    exit 2
}

function Strip-OuterQuotes($Value) {
    if ($Value.Length -ge 2 -and $Value[0] -eq $Value[$Value.Length - 1] -and ($Value[0] -eq '"' -or $Value[0] -eq "'")) {
        return $Value.Substring(1, $Value.Length - 2)
    }
    return $Value
}

# Read only the two exact keys from the env file; treat it as data, never
# evaluate it.
function Load-EnvFile($Path) {
    $values = @{ TCRT_BASE_URL = ''; TCRT_APP_TOKEN = '' }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $values }
    foreach ($rawLine in [IO.File]::ReadAllLines($Path)) {
        $line = $rawLine.TrimStart(' ', "`t")
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('TCRT_BASE_URL=')) {
            $values.TCRT_BASE_URL = Strip-OuterQuotes ($line.Substring('TCRT_BASE_URL='.Length).Trim())
        }
        elseif ($line.StartsWith('TCRT_APP_TOKEN=')) {
            $values.TCRT_APP_TOKEN = Strip-OuterQuotes ($line.Substring('TCRT_APP_TOKEN='.Length).Trim())
        }
    }
    return $values
}

if ($args.Count -lt 1) { Show-Usage }

$method = [string]$args[0]
$path = ''
$data = $null
$query = ''
$files = @()

if ($method -ieq 'check') {
    if ($args.Count -ne 1) { Show-Usage }
    $method = 'GET'
    $path = '/api/app/teams'
}
else {
    if ($args.Count -lt 2) { Show-Usage }
    $path = [string]$args[1]
    $i = 2
    while ($i -lt $args.Count) {
        switch ([string]$args[$i]) {
            '--data' {
                if ($i + 1 -ge $args.Count) { Fail '--data requires a JSON value' }
                $data = [string]$args[$i + 1]
                $i += 2
            }
            '--query' {
                if ($i + 1 -ge $args.Count) { Fail '--query requires a query string' }
                $query = [string]$args[$i + 1]
                $i += 2
            }
            '--file' {
                if ($i + 1 -ge $args.Count) { Fail '--file requires a value like field=@C:\path\to\file' }
                $spec = [string]$args[$i + 1]
                $eqIdx = $spec.IndexOf('=@')
                if ($eqIdx -lt 1) { Fail "--file must look like field=@/path/to/file, got: $spec" }
                $filePath = $spec.Substring($eqIdx + 2)
                if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { Fail "--file path not found: $filePath" }
                $files += ,@($spec.Substring(0, $eqIdx), $filePath)
                $i += 2
            }
            default { Fail "unknown argument: $($args[$i])" }
        }
    }
}

if ($null -ne $data -and $files.Count -gt 0) {
    Fail '--data and --file are mutually exclusive'
}
if (-not $path.StartsWith('/')) { $path = '/' + $path }

$envFile = if (-not [string]::IsNullOrEmpty($env:TCRT_ENV_FILE)) { $env:TCRT_ENV_FILE } else { $DefaultEnvFile }
$fileValues = Load-EnvFile $envFile
$baseUrl = if (-not [string]::IsNullOrEmpty($env:TCRT_BASE_URL)) { $env:TCRT_BASE_URL } else { $fileValues.TCRT_BASE_URL }
$token = if (-not [string]::IsNullOrEmpty($env:TCRT_APP_TOKEN)) { $env:TCRT_APP_TOKEN } else { $fileValues.TCRT_APP_TOKEN }

$missing = @()
if ([string]::IsNullOrEmpty($baseUrl)) { $missing += 'TCRT_BASE_URL' }
if ([string]::IsNullOrEmpty($token)) { $missing += 'TCRT_APP_TOKEN' }
if ($missing.Count -gt 0) {
    Fail "Missing: $($missing -join ' '). Set exported variables or a local env file; never paste a token into chat."
}

$url = $baseUrl.TrimEnd('/') + $path
if ($query -ne '') { $url = "$url`?$query" }

try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }
Add-Type -AssemblyName System.Net.Http

$client = [System.Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromSeconds(30)
$request = [System.Net.Http.HttpRequestMessage]::new(
    [System.Net.Http.HttpMethod]::new($method.ToUpperInvariant()), $url)
$request.Headers.TryAddWithoutValidation('Authorization', "Bearer $token") | Out-Null

if ($null -ne $data) {
    $request.Content = [System.Net.Http.StringContent]::new($data, [Text.Encoding]::UTF8, 'application/json')
}
elseif ($files.Count -gt 0) {
    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    foreach ($pair in $files) {
        $fieldName = $pair[0]
        $filePath = (Resolve-Path -LiteralPath $pair[1]).ProviderPath
        $bytes = [IO.File]::ReadAllBytes($filePath)
        $content = [System.Net.Http.ByteArrayContent]::new($bytes)
        $content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/octet-stream')
        $multipart.Add($content, $fieldName, [IO.Path]::GetFileName($filePath))
    }
    $request.Content = $multipart
}

try {
    $response = $client.SendAsync($request).GetAwaiter().GetResult()
}
catch {
    $reason = $_.Exception.GetBaseException().Message
    [Console]::Error.WriteLine("[tcrt-app] Could not reach $($baseUrl.TrimEnd('/')): $reason")
    exit 1
}

$status = [int]$response.StatusCode
$body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
$client.Dispose()

if ($body -ne '') { [Console]::Out.WriteLine($body) }
[Console]::Error.WriteLine("HTTP $status")

if ($status -ge 400) { exit 1 }
exit 0
