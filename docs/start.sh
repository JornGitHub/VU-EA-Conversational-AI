#!/usr/bin/env bash
# VU EA Conversational AI - startscript voor macOS en Linux.
#
# Gebruik:
#   curl -fsSL https://vusaverse.github.io/VU-EA-Conversational-AI/start.sh | bash
#
# Dit script doet alles zelf: het zoekt Python, installeert Python en git als ze
# ontbreken, haalt de code op (of werkt een bestaande kopie bij), maakt een
# virtual environment en start `python main.py`. Dat commando doet de rest:
# dependencies installeren, Ollama-modellen ophalen, de semantische index
# bouwen en de app in je browser openen.
#
# Alles draait lokaal op je eigen machine; er gaat geen data naar buiten.
#
# Aanpasbaar via omgevingsvariabelen:
#   VUEA_REPO_URL   andere repository (standaard de publieke GitHub-repo)
#   VUEA_DIR        andere doelmap   (standaard ~/VU-EA-Conversational-AI)
#   VUEA_BRANCH     andere branch    (standaard main)
#   VUEA_NO_INSTALL zet op 1 om niets te installeren; het script meldt dan
#                   alleen wat er ontbreekt

set -euo pipefail

REPO_URL="${VUEA_REPO_URL:-https://github.com/vusaverse/VU-EA-Conversational-AI.git}"
TARGET_DIR="${VUEA_DIR:-$HOME/VU-EA-Conversational-AI}"
BRANCH="${VUEA_BRANCH:-main}"
MAY_INSTALL=1
[ "${VUEA_NO_INSTALL:-0}" = "1" ] && MAY_INSTALL=0

info() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!  %s\033[0m\n' "$1"; }
fail() { printf '\033[31mX  %s\033[0m\n' "$1" >&2; exit 1; }

IS_MACOS=0
[ "$(uname -s)" = "Darwin" ] && IS_MACOS=1

# ------------------------------------------------------- pakketbeheerder ----
# Eén plek die weet hoe je op dit systeem iets installeert. Ontbreekt sudo of
# een bekende pakketbeheerder, dan geeft dit niets terug en valt de aanroeper
# terug op een uitleg in plaats van een half commando.
package_install() {
    if [ "$MAY_INSTALL" -eq 0 ]; then
        return 1
    fi
    if [ "$IS_MACOS" -eq 1 ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install "$@" && return 0
        fi
        return 1
    fi

    local sudo_cmd=""
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || return 1
        sudo_cmd="sudo"
    fi
    if command -v apt-get >/dev/null 2>&1; then
        $sudo_cmd apt-get update -qq && $sudo_cmd apt-get install -y "$@" && return 0
    elif command -v dnf >/dev/null 2>&1; then
        $sudo_cmd dnf install -y "$@" && return 0
    elif command -v pacman >/dev/null 2>&1; then
        $sudo_cmd pacman -Sy --noconfirm "$@" && return 0
    elif command -v zypper >/dev/null 2>&1; then
        $sudo_cmd zypper install -y "$@" && return 0
    fi
    return 1
}

# --------------------------------------------------------------- Python ----
find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

info "Python controleren"
if ! PYTHON="$(find_python)"; then
    if [ "$MAY_INSTALL" -eq 1 ]; then
        info "Python installeren (dat ontbreekt nog)"
        if [ "$IS_MACOS" -eq 1 ]; then
            package_install python@3.12 || warn "Automatisch installeren is niet gelukt."
        else
            # python3-venv zit op Debian/Ubuntu in een apart pakket; zonder dat
            # pakket lukt de virtual environment verderop niet.
            package_install python3 python3-venv || warn "Automatisch installeren is niet gelukt."
        fi
        PYTHON="$(find_python || true)"
    fi
fi
if [ -z "${PYTHON:-}" ]; then
    echo "Geen Python 3.10 of nieuwer gevonden en automatisch installeren lukte niet."
    if [ "$IS_MACOS" -eq 1 ]; then
        echo "Installeer Python via https://www.python.org/downloads/ of met: brew install python@3.12"
    else
        echo "Installeer Python via je pakketbeheerder, bijvoorbeeld: sudo apt install python3 python3-venv"
    fi
    fail "Python ontbreekt"
fi
echo "Gevonden: $($PYTHON --version) ($(command -v "$PYTHON"))"

# ------------------------------------------------------------------ code ----
if ! command -v git >/dev/null 2>&1 && [ "$MAY_INSTALL" -eq 1 ]; then
    info "git installeren (nodig om de code op te halen en later bij te werken)"
    package_install git || warn "git installeren is niet gelukt."
fi

if [ -d "$TARGET_DIR/.git" ]; then
    info "Bestaande installatie bijwerken in $TARGET_DIR"
    git -C "$TARGET_DIR" fetch --quiet origin "$BRANCH" || warn "Bijwerken mislukt; verder met de huidige versie."
    git -C "$TARGET_DIR" checkout --quiet "$BRANCH" 2>/dev/null || true
    git -C "$TARGET_DIR" pull --quiet --ff-only origin "$BRANCH" || warn "Kon niet bijwerken (lokale wijzigingen?); verder met de huidige versie."
elif [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/main.py" ]; then
    info "Bestaande map gevonden in $TARGET_DIR (geen git-kopie); die wordt gebruikt zoals hij is"
else
    info "Code ophalen naar $TARGET_DIR"
    command -v git >/dev/null 2>&1 || fail "git is niet geïnstalleerd en kon niet worden geïnstalleerd."
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR" || fail "Clonen van $REPO_URL is mislukt."
fi

cd "$TARGET_DIR"
[ -f main.py ] || fail "main.py niet gevonden in $TARGET_DIR."

# --------------------------------------------------------------- Ollama ----
# Optioneel: zonder Ollama werkt de app gewoon, alleen zonder LLM-formuleerlaag
# en semantisch zoeken. Nooit fataal.
if ! command -v ollama >/dev/null 2>&1 && [ "$MAY_INSTALL" -eq 1 ]; then
    info "Ollama installeren (voor de LLM-laag; de app werkt ook zonder)"
    if [ "$IS_MACOS" -eq 1 ]; then
        if command -v brew >/dev/null 2>&1; then
            brew install --cask ollama || warn "Ollama installeren is niet gelukt; haal het van https://ollama.com/download"
        else
            warn "Geen Homebrew gevonden; haal Ollama van https://ollama.com/download"
        fi
    else
        curl -fsSL https://ollama.com/install.sh | sh || warn "Ollama installeren is niet gelukt; zie https://ollama.com/download"
    fi
fi

# --------------------------------------------------------------- venv ------
info "Virtual environment klaarzetten"
if [ ! -d .venv ]; then
    "$PYTHON" -m venv .venv || fail "Kon geen virtual environment maken. Op Debian/Ubuntu: sudo apt install python3-venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Actief: $(python --version)"

# ---------------------------------------------------------------- start ----
info "App starten (installeren, modellen, index en daarna je browser)"
echo "Stoppen doe je met Ctrl+C. Volgende keer sneller starten?"
echo "  cd $TARGET_DIR && source .venv/bin/activate && python main.py"
exec python main.py
