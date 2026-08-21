# VU EA Conversational AI - startscript voor Windows (PowerShell).
#
# Gebruik:
#   irm https://jorngithub.github.io/VU-EA-Conversational-AI/start-windows.ps1 | iex
#
# Het script haalt de code op (of werkt een bestaande kopie bij), maakt een
# virtual environment en start `python main.py`. Dat commando doet de rest:
# dependencies installeren, Ollama-modellen ophalen, de semantische index
# bouwen en de app in je browser openen.
#
# Alles draait lokaal op je eigen machine; er gaat geen data naar buiten.
#
# Aanpasbaar via omgevingsvariabelen:
#   VUEA_REPO_URL  andere repository (standaard de publieke GitHub-repo)
#   VUEA_DIR       andere doelmap   (standaard %USERPROFILE%\VU-EA-Conversational-AI)
#   VUEA_BRANCH    andere branch    (standaard main)

$ErrorActionPreference = 'Stop'

$RepoUrl   = if ($env:VUEA_REPO_URL) { $env:VUEA_REPO_URL } else { 'https://github.com/JornGitHub/VU-EA-Conversational-AI.git' }
$TargetDir = if ($env:VUEA_DIR)      { $env:VUEA_DIR }      else { Join-Path $env:USERPROFILE 'VU-EA-Conversational-AI' }
$Branch    = if ($env:VUEA_BRANCH)   { $env:VUEA_BRANCH }   else { 'main' }
$ZipUrl    = ($RepoUrl -replace '\.git$', '') + "/archive/refs/heads/$Branch.zip"

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "!  $message" -ForegroundColor Yellow }
function Stop-WithError($message) { Write-Host "X  $message" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- Python ----
function Find-Python {
    foreach ($candidate in @('py', 'python', 'python3')) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $arguments = if ($candidate -eq 'py') { @('-3', '-c') } else { @('-c') }
        & $candidate @arguments 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Command = $candidate; Arguments = $(if ($candidate -eq 'py') { @('-3') } else { @() }) }
        }
    }
    return $null
}

Write-Step 'Python controleren'
$python = Find-Python
if (-not $python) {
    Write-Host 'Geen Python 3.10 of nieuwer gevonden.'
    Write-Host 'Installeer Python met:  winget install -e --id Python.Python.3.12'
    Write-Host 'of download het van https://www.python.org/downloads/windows/'
    Write-Host 'Let op: vink tijdens installatie "Add python.exe to PATH" aan.'
    Stop-WithError 'Python ontbreekt'
}
Write-Host ("Gevonden: " + (& $python.Command @($python.Arguments + '--version')))

# ------------------------------------------------------------------ code ----
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)

if (Test-Path (Join-Path $TargetDir '.git')) {
    Write-Step "Bestaande installatie bijwerken in $TargetDir"
    if ($hasGit) {
        git -C $TargetDir fetch --quiet origin $Branch
        git -C $TargetDir checkout --quiet $Branch 2>$null
        git -C $TargetDir pull --quiet --ff-only origin $Branch
        if ($LASTEXITCODE -ne 0) { Write-Warn 'Kon niet bijwerken (lokale wijzigingen?); verder met de huidige versie.' }
    } else {
        Write-Warn 'git niet gevonden; verder met de huidige versie.'
    }
} elseif (Test-Path (Join-Path $TargetDir 'main.py')) {
    Write-Step "Bestaande map gevonden in $TargetDir; die wordt gebruikt zoals hij is"
} elseif ($hasGit) {
    Write-Step "Code ophalen naar $TargetDir"
    git clone --quiet --branch $Branch $RepoUrl $TargetDir
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Clonen van $RepoUrl is mislukt." }
} else {
    # Zonder git: download de ZIP van de publieke repo.
    Write-Step "Code downloaden naar $TargetDir (git niet gevonden, ZIP gebruikt)"
    $zipPath = Join-Path $env:TEMP 'vu-ea-conversational-ai.zip'
    $unpackDir = Join-Path $env:TEMP 'vu-ea-conversational-ai-unpack'
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath
    if (Test-Path $unpackDir) { Remove-Item $unpackDir -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $unpackDir -Force
    $extracted = Get-ChildItem $unpackDir -Directory | Select-Object -First 1
    if (-not $extracted) { Stop-WithError 'Het gedownloade archief bevatte geen projectmap.' }
    Move-Item $extracted.FullName $TargetDir
    Remove-Item $zipPath -Force
    Remove-Item $unpackDir -Recurse -Force
    Write-Warn 'Zonder git kan dit script later niet automatisch bijwerken. Installeer git voor updates: winget install -e --id Git.Git'
}

Set-Location $TargetDir
if (-not (Test-Path 'main.py')) { Stop-WithError "main.py niet gevonden in $TargetDir." }

# --------------------------------------------------------------- venv ------
Write-Step 'Virtual environment klaarzetten'
if (-not (Test-Path '.venv')) {
    & $python.Command @($python.Arguments + @('-m', 'venv', '.venv'))
    if ($LASTEXITCODE -ne 0) { Stop-WithError 'Kon geen virtual environment maken.' }
}
$venvPython = Join-Path $TargetDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { Stop-WithError 'Virtual environment lijkt onvolledig.' }
Write-Host ("Actief: " + (& $venvPython '--version'))

# ---------------------------------------------------------------- start ----
Write-Step 'App starten (installeren, modellen, index en daarna je browser)'
Write-Host 'Stoppen doe je met Ctrl+C. Volgende keer sneller starten?'
Write-Host "  cd `"$TargetDir`"; .\.venv\Scripts\python.exe main.py"
& $venvPython 'main.py'
