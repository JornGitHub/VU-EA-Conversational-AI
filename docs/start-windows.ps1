# VU EA Conversational AI - startscript voor Windows (PowerShell).
#
# Gebruik (download eerst, draai daarna - dat voorkomt dat virusscanners een
# script blokkeren dat rechtstreeks vanaf internet wordt uitgevoerd):
#
#   irm https://jorngithub.github.io/VU-EA-Conversational-AI/start-windows.ps1 -OutFile start.ps1
#   powershell -ExecutionPolicy Bypass -File .\start.ps1
#
# Werkt dit niet, gebruik dan de losse commando's op de projectpagina. Die
# hebben geen script nodig en worden nooit door een virusscanner geblokkeerd.
#
# Het script controleert Python, haalt de code op (of werkt een bestaande kopie
# bij), maakt een virtual environment en start `python main.py`. Dat commando
# doet de rest: dependencies installeren, Ollama-modellen ophalen, de
# semantische index bouwen en de app in je browser openen.
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
$MinimumPython = [version]'3.10'

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "!  $message" -ForegroundColor Yellow }
function Stop-WithError($message) { Write-Host "X  $message" -ForegroundColor Red; exit 1 }

# --------------------------------------------------------------- Python ----
# Eén absoluut pad naar python.exe, niet een commando plus losse vlaggen: dat
# laatste liep stuk zodra de `py`-launcher wel bestond maar geen 3.x-runtime had.
function Get-PythonVersion([string]$exe) {
    # Vraag de interpreter zelf om zijn versie. De uitvoer is de test, niet de
    # exitcode: die is per PowerShell-versie onbetrouwbaar bij native commando's.
    try {
        $output = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $null
    }
    $line = ($output | Select-Object -First 1)
    if ($line -and ("$line".Trim() -match '^\d+\.\d+$')) { return [version]("$line".Trim()) }
    return $null
}

# Onthoudt of we alleen de Microsoft Store-stub tegenkwamen: dat is de meest
# voorkomende oorzaak van "Program 'python.exe' failed to run" en verdient een
# eigen uitleg in plaats van "geen Python gevonden".
$script:SawStoreStub = $false

function Resolve-PythonExe {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($name in @('python', 'python3')) {
        foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($command.Source) { $candidates.Add([string]$command.Source) }
        }
    }

    # De py-launcher weet vaak waar de echte interpreter staat; vraag het pad op
    # in plaats van er vlaggen aan door te geven.
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        try {
            $viaLauncher = & py -3 -c "import sys; print(sys.executable)" 2>$null
            $line = ($viaLauncher | Select-Object -First 1)
            if ($line) { $candidates.Add("$line".Trim()) }
        } catch {
            # py bestaat, maar heeft geen bruikbare runtime: gewoon overslaan.
        }
    }

    foreach ($exe in $candidates) {
        if ([string]::IsNullOrWhiteSpace($exe)) { continue }
        # De Microsoft Store-stub opent de Store in plaats van Python te draaien.
        if ($exe -match '[\\/]WindowsApps[\\/]') { $script:SawStoreStub = $true; continue }
        $version = Get-PythonVersion $exe
        if ($version -and $version -ge $MinimumPython) { return $exe }
    }
    return $null
}

Write-Step 'Python controleren'
$pythonExe = Resolve-PythonExe
if (-not $pythonExe) {
    Write-Host "Geen Python $MinimumPython of nieuwer gevonden."
    if ($script:SawStoreStub) {
        Write-Host ''
        Write-Warn 'De enige python.exe op dit systeem is de Microsoft Store-alias.'
        Write-Host 'Die doet niets en geeft: "Program ''python.exe'' failed to run: The system cannot find the path specified".'
        Write-Host 'Zet hem uit via Instellingen > Apps > Geavanceerde app-instellingen > App-uitvoeringsaliassen'
        Write-Host '(schakel python.exe en python3.exe uit) en installeer daarna een echte Python.'
        Write-Host ''
    }
    Write-Host 'Installeer Python met:  winget install -e --id Python.Python.3.12'
    Write-Host 'of download het van https://www.python.org/downloads/windows/'
    Write-Host 'Let op: vink tijdens installatie "Add python.exe to PATH" aan en open daarna een nieuwe PowerShell.'
    Stop-WithError 'Python ontbreekt'
}
Write-Host "Gevonden: $pythonExe (Python $(Get-PythonVersion $pythonExe))"

# ------------------------------------------------------------------ code ----
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)

if (Test-Path (Join-Path $TargetDir '.git')) {
    Write-Step "Bestaande installatie bijwerken in $TargetDir"
    if ($hasGit) {
        try {
            git -C $TargetDir fetch --quiet origin $Branch
            git -C $TargetDir checkout --quiet $Branch 2>$null
            git -C $TargetDir pull --quiet --ff-only origin $Branch
        } catch {
            Write-Warn 'Kon niet bijwerken (lokale wijzigingen?); verder met de huidige versie.'
        }
    } else {
        Write-Warn 'git niet gevonden; verder met de huidige versie.'
    }
} elseif (Test-Path (Join-Path $TargetDir 'main.py')) {
    Write-Step "Bestaande map gevonden in $TargetDir; die wordt gebruikt zoals hij is"
} elseif ($hasGit) {
    Write-Step "Code ophalen naar $TargetDir"
    git clone --quiet --branch $Branch $RepoUrl $TargetDir
    if (-not (Test-Path (Join-Path $TargetDir 'main.py'))) { Stop-WithError "Clonen van $RepoUrl is mislukt." }
} else {
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
$venvPython = Join-Path $TargetDir '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    & $pythonExe -m venv .venv
}
if (-not (Test-Path $venvPython)) {
    Stop-WithError "Kon geen virtual environment maken met $pythonExe."
}
Write-Host "Actief: $(& $venvPython --version)"

# ---------------------------------------------------------------- start ----
Write-Step 'App starten (installeren, modellen, index en daarna je browser)'
Write-Host 'Stoppen doe je met Ctrl+C. Volgende keer sneller starten?'
Write-Host "  cd `"$TargetDir`"; .\.venv\Scripts\python.exe main.py"
& $venvPython main.py
