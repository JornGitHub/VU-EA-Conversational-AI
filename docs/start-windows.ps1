# VU EA Conversational AI - startscript voor Windows (PowerShell).
#
# Dit script doet alles zelf: het zoekt Python (ook als PATH kapot is),
# installeert Python en git als ze ontbreken, haalt de code op, maakt een
# virtual environment en start `python main.py`. Dat commando installeert
# vervolgens de dependencies, haalt de Ollama-modellen op, bouwt de semantische
# index en opent de app in je browser.
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
# Alles draait lokaal op je eigen machine; er gaat geen data naar buiten.
#
# Aanpasbaar via omgevingsvariabelen:
#   VUEA_REPO_URL   andere repository (standaard de publieke GitHub-repo)
#   VUEA_DIR        andere doelmap   (standaard %USERPROFILE%\VU-EA-Conversational-AI)
#   VUEA_BRANCH     andere branch    (standaard main)
#   VUEA_NO_INSTALL zet op 1 om niets te installeren; het script meldt dan
#                   alleen wat er ontbreekt

$ErrorActionPreference = 'Stop'

$RepoUrl   = if ($env:VUEA_REPO_URL) { $env:VUEA_REPO_URL } else { 'https://github.com/JornGitHub/VU-EA-Conversational-AI.git' }
$TargetDir = if ($env:VUEA_DIR)      { $env:VUEA_DIR }      else { Join-Path $env:USERPROFILE 'VU-EA-Conversational-AI' }
$Branch    = if ($env:VUEA_BRANCH)   { $env:VUEA_BRANCH }   else { 'main' }
$ZipUrl    = ($RepoUrl -replace '\.git$', '') + "/archive/refs/heads/$Branch.zip"
$MinimumPython = [version]'3.10'
$MayInstall = ($env:VUEA_NO_INSTALL -ne '1')

# Valt terug op de officiële installer als winget ontbreekt of geblokkeerd is.
$PythonVersion    = '3.12.10'
$PythonInstaller  = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"

function Write-Step($message) { Write-Host "`n==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "!  $message" -ForegroundColor Yellow }
function Stop-WithError($message) { Write-Host "X  $message" -ForegroundColor Red; exit 1 }

# Na een installatie kent dit venster de nieuwe PATH nog niet; die staat wel al
# in het register. Zonder deze stap zou je een nieuwe PowerShell moeten openen.
function Update-PathFromRegistry {
    $machine = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('PATH', 'User')
    $combined = (@($machine, $user) | Where-Object { $_ }) -join ';'
    # Buiten Windows bestaan deze registersleutels niet; dan PATH met rust laten
    # in plaats van hem leeg te maken.
    if ($combined) { $env:PATH = $combined }
}

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

    # Standaard installatiemappen. Hierdoor werkt het script ook als PATH kapot
    # is, of net na een installatie waarvan dit venster nog niets weet - precies
    # de gevallen waarvoor je anders handmatig `where.exe python` zou draaien.
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        'C:\'
    ) | Where-Object { $_ -and (Test-Path $_) }
    foreach ($root in $roots) {
        foreach ($dir in @(Get-ChildItem -Path $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue)) {
            $exe = Join-Path $dir.FullName 'python.exe'
            if (Test-Path $exe) { $candidates.Add($exe) }
        }
    }

    $best = $null
    $bestVersion = $null
    foreach ($exe in $candidates) {
        if ([string]::IsNullOrWhiteSpace($exe)) { continue }
        # De Microsoft Store-stub opent de Store in plaats van Python te draaien.
        if ($exe -match '[\\/]WindowsApps[\\/]') { $script:SawStoreStub = $true; continue }
        $version = Get-PythonVersion $exe
        if (-not $version -or $version -lt $MinimumPython) { continue }
        if (-not $bestVersion -or $version -gt $bestVersion) { $best = $exe; $bestVersion = $version }
    }
    return $best
}

function Invoke-Winget([string[]]$packageArguments, [string]$label) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Write-Host "Installeren met winget: $label"
    try {
        & winget install @packageArguments --silent --accept-package-agreements --accept-source-agreements | Out-Null
    } catch {
        Write-Warn "winget kon $label niet installeren: $($_.Exception.Message)"
        return $false
    }
    Update-PathFromRegistry
    return $true
}

function Install-Python {
    Write-Step "Python installeren (dat ontbreekt nog)"
    if (Invoke-Winget @('-e', '--id', 'Python.Python.3.12', '--scope', 'user') 'Python 3.12') {
        $found = Resolve-PythonExe
        if ($found) { return $found }
        Write-Warn 'winget meldde succes, maar er is nog geen werkende Python gevonden; ik probeer de officiële installer.'
    } else {
        Write-Host 'winget is hier niet beschikbaar; ik gebruik de officiële installer van python.org.'
    }

    $installer = Join-Path $env:TEMP "python-$PythonVersion-amd64.exe"
    Write-Host "Downloaden: $PythonInstaller"
    try {
        Invoke-WebRequest -Uri $PythonInstaller -OutFile $installer -UseBasicParsing
    } catch {
        Write-Warn "Downloaden van de Python-installer is mislukt: $($_.Exception.Message)"
        return $null
    }

    # Installatie voor deze gebruiker: geen beheerdersrechten nodig, en
    # PrependPath zorgt dat `python` daarna gewoon werkt in een nieuw venster.
    Write-Host 'Installeren (dit duurt een halve minuut; er verschijnt geen venster)...'
    try {
        Start-Process -FilePath $installer -Wait -ArgumentList @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0'
        )
    } catch {
        Write-Warn "De Python-installer kon niet worden gestart: $($_.Exception.Message)"
        return $null
    } finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }

    Update-PathFromRegistry
    return Resolve-PythonExe
}

Write-Step 'Python controleren'
$pythonExe = Resolve-PythonExe
if (-not $pythonExe -and $MayInstall) {
    if ($script:SawStoreStub) {
        Write-Host 'De enige python.exe hier is de Microsoft Store-alias; die doet niets.'
    }
    $pythonExe = Install-Python
}
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
if (-not $hasGit -and $MayInstall) {
    Write-Step 'git installeren (nodig om later automatisch bij te werken)'
    if (Invoke-Winget @('-e', '--id', 'Git.Git') 'git') {
        $hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
    }
    if (-not $hasGit) { Write-Warn 'git installeren is niet gelukt; ik gebruik de ZIP-download.' }
}

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
    Write-Warn 'Zonder git kan dit script later niet automatisch bijwerken.'
}

Set-Location $TargetDir
if (-not (Test-Path 'main.py')) { Stop-WithError "main.py niet gevonden in $TargetDir." }

# --------------------------------------------------------------- Ollama ----
# Optioneel: zonder Ollama werkt de app gewoon, alleen zonder LLM-formuleerlaag
# en semantisch zoeken. Nooit fataal.
if (-not (Get-Command ollama -ErrorAction SilentlyContinue) -and $MayInstall) {
    Write-Step 'Ollama installeren (voor de LLM-laag; de app werkt ook zonder)'
    if (-not (Invoke-Winget @('-e', '--id', 'Ollama.Ollama') 'Ollama')) {
        Write-Warn 'Ollama niet geïnstalleerd. Wil je de LLM-laag, haal het dan van https://ollama.com/download'
    }
}

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
