[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackagePath
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$package = (Resolve-Path -LiteralPath $PackagePath).Path
$exe = Join-Path $package 'fluidgateway-native.exe'
$manifest = Get-Content -LiteralPath (Join-Path $package 'manifest.json') -Raw | ConvertFrom-Json
$sha = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($sha -ne $manifest.executable_sha256 -or $manifest.python_required) {
    throw 'Package manifest identity mismatch.'
}
if ($manifest.PSObject.Properties.Name -contains 'library_sha256') {
    $dll = Join-Path $package 'FluidGatewayNative.dll'
    if ((Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.library_sha256 -or
        $manifest.abi_version -ne 65536 -or
        -not (Test-Path -LiteralPath (Join-Path $package 'include/fluidgateway_native.h')) -or
        -not (Test-Path -LiteralPath (Join-Path $package 'lib/FluidGatewayNative.lib'))) {
        throw 'Package DLL/ABI manifest identity mismatch.'
    }
}

function Convert-Hex([string]$Hex) {
    $bytes = New-Object byte[] ($Hex.Length / 2)
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        $bytes[$i] = [Convert]::ToByte($Hex.Substring($i * 2, 2), 16)
    }
    return ,$bytes
}

function Read-Exactly($Stream, [int]$Count) {
    $bytes = New-Object byte[] $Count
    $offset = 0
    while ($offset -lt $Count) {
        $read = $Stream.Read($bytes, $offset, $Count - $offset)
        if ($read -eq 0) {
            throw 'Unexpected end of native response.'
        }
        $offset += $read
    }
    return ,$bytes
}

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $exe
$start.Arguments = "serve-events --host 127.0.0.1 --port $port"
$start.WorkingDirectory = $package
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.EnvironmentVariables['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot"
$start.EnvironmentVariables.Remove('PYTHONPATH')
$start.EnvironmentVariables.Remove('PYTHONHOME')
$process = [Diagnostics.Process]::Start($start)
$client = $null
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ($true) {
        if ($process.HasExited) {
            throw "Packaged server exited: $($process.ExitCode)"
        }
        $client = [Net.Sockets.TcpClient]::new()
        try {
            $client.Connect('127.0.0.1', $port)
            break
        }
        catch {
            $client.Dispose()
            if ([DateTime]::UtcNow -gt $deadline) {
                throw
            }
            Start-Sleep -Milliseconds 25
        }
    }
    $client.ReceiveTimeout = 5000
    $client.SendTimeout = 5000
    $stream = $client.GetStream()
    $vectors = Get-Content -LiteralPath (Join-Path $root 'contracts/fluidlink-v2.golden.json') -Raw | ConvertFrom-Json
    $session = $null
    $count = 0
    foreach ($vector in $vectors.vectors | Where-Object { $_.name.EndsWith('_request') }) {
        $request = Convert-Hex $vector.wire_hex
        if ($session) {
            [Array]::Copy($session, 0, $request, 36, 16)
        }
        $stream.Write($request, 0, $request.Length)
        $header = Read-Exactly $stream 56
        $size = [BitConverter]::ToUInt32($header, 52)
        if ($size -gt 65535) {
            throw 'Invalid response length.'
        }
        $payload = Read-Exactly $stream $size
        $expectedOpcode = switch ($request[6]) {
            1 { 2 }
            10 { 11 }
            20 { 21 }
            30 { 30 }
        }
        if ($header[6] -ne $expectedOpcode -or ($header[9] -band 1) -ne 1 -or
            [BitConverter]::ToUInt64($header, 12) -ne [BitConverter]::ToUInt64($request, 12) -or
            [Convert]::ToBase64String($header[20..35]) -ne [Convert]::ToBase64String($request[20..35])) {
            throw "Invalid response to $($vector.name)."
        }
        if (-not $session) {
            $session = [byte[]]$header[36..51]
            $welcome = [Text.Encoding]::UTF8.GetString($payload)
            if (-not $welcome.EndsWith([string]$manifest.version)) {
                throw 'Package version mismatch.'
            }
        }
        elseif ([Convert]::ToBase64String($header[36..51]) -ne [Convert]::ToBase64String($session)) {
            throw 'Session identity changed.'
        }
        $count++
    }
    $process.Refresh()
    $modules = @($process.Modules | ForEach-Object { $_.ModuleName })
    # msvcp_win.dll is an OS component, not the MSVC redistributable (msvcp140.dll).
    if ($modules | Where-Object { $_ -match '(?i)^python|^clang_rt\.asan|^vcruntime|^msvcp\d' }) {
        throw 'Release loaded a Python, ASAN or dynamic C++ runtime module.'
    }
    [pscustomobject]@{
        executable_sha256 = $sha
        restricted_path = $start.EnvironmentVariables['PATH']
        verified_round_trips = $count
        modules = $modules
        python_required = $false
    } | ConvertTo-Json -Depth 4
}
finally {
    if ($client) {
        $client.Dispose()
    }
    if (-not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit()
    }
    $process.Dispose()
}
