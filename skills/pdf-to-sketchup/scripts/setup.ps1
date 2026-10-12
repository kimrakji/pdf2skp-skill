# Bootstrap without a preinstalled Python or an administrator shell.
$ErrorActionPreference = 'Stop'
$skillRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = $env:PDF2SKP_RUNTIME_DIR
if (-not $runtimeRoot) {
    $runtimeRoot = Join-Path $env:LOCALAPPDATA 'pdf2skp-skill'
}
$toolsRoot = Join-Path $runtimeRoot 'tools'
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
$uvPath = Join-Path $toolsRoot 'uv.exe'
if (-not (Test-Path $uvPath)) {
    $existingUv = Get-Command uv -ErrorAction SilentlyContinue
    if ($existingUv) {
        $uvPath = $existingUv.Source
    } else {
        $installer = Join-Path $toolsRoot 'uv-install.ps1'
        $previousInstall = $env:UV_UNMANAGED_INSTALL
        try {
            Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
            $env:UV_UNMANAGED_INSTALL = $toolsRoot
            & $installer
            if (-not (Test-Path $uvPath)) { throw 'uv installation failed.' }
        } finally {
            $env:UV_UNMANAGED_INSTALL = $previousInstall
            Remove-Item -Force -ErrorAction SilentlyContinue $installer
        }
    }
}
$env:UV_CACHE_DIR = Join-Path $runtimeRoot 'cache'
$env:UV_PYTHON_CACHE_DIR = Join-Path $runtimeRoot 'python-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeRoot 'python'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$pythonPath = Join-Path $runtimeRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonPath)) {
    if (Test-Path (Join-Path $runtimeRoot '.venv')) {
        throw "Existing runtime is incomplete: $runtimeRoot\.venv"
    }
    $pythonRequest = $env:PDF2SKP_PYTHON
    if (-not $pythonRequest) { $pythonRequest = '3.12' }
    & $uvPath --no-config venv --python $pythonRequest (Join-Path $runtimeRoot '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $uvPath --no-config pip install --python $pythonPath -r (Join-Path $skillRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $pythonPath (Join-Path $PSScriptRoot 'check_runtime.py') --runtime-root $runtimeRoot @args
exit $LASTEXITCODE
