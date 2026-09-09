[CmdletBinding()]
param(
    [string]$BuildDirectory = 'native/build',
    [string]$OutputDirectory = 'tmp/native-v0.69.0',
    [string]$CMake = 'cmake'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$build = (Resolve-Path -LiteralPath $BuildDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) {
    throw 'Use a new output directory; existing packages are not overwritten.'
}
& $CMake --install $build --config Release --prefix $output
if ($LASTEXITCODE) { throw "Install failed: $LASTEXITCODE" }
$exe = Join-Path $output 'fluidgateway-native.exe'
$dll = Join-Path $output 'FluidGatewayNative.dll'
$version = & $exe --version
if ($LASTEXITCODE -or $version -notmatch '^fluidgateway-native ([0-9]+\.[0-9]+\.[0-9]+)$') {
    throw 'Packaged version could not be verified.'
}
$versionNumber = $Matches[1]
$manifest = @{
    version = $versionNumber
    executable_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    library_sha256 = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
    abi_version = 65536
    python_required = $false
    default_backend = 'server'
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'manifest.json') -Encoding UTF8
Copy-Item -LiteralPath (Join-Path $root 'docs/native-gateway.md') -Destination (Join-Path $output 'README.md')
Copy-Item -LiteralPath (Join-Path $root 'docs/inprocess-gateway.md') -Destination (Join-Path $output 'INPROCESS.md')
& (Join-Path $PSScriptRoot 'Test-NativePackage.ps1') -PackagePath $output
if ($LASTEXITCODE) { throw 'Package verification failed.' }
$zip = Join-Path (Split-Path $output -Parent) "fluidgateway-native-v$versionNumber-win-x64.zip"
if (Test-Path -LiteralPath $zip) { throw 'The target archive already exists.' }
Compress-Archive -Path (Join-Path $output '*') -DestinationPath $zip
Write-Output "Verified package: $zip"
