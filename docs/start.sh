#!/usr/bin/env bash
# VU EA Conversational AI - startscript voor macOS en Linux.
#
# Gebruik:
#   curl -fsSL https://jorngithub.github.io/VU-EA-Conversational-AI/start.sh | bash
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
#   VUEA_DIR       andere doelmap   (standaard ~/VU-EA-Conversational-AI)
#   VUEA_BRANCH    andere branch    (standaard main)

set -euo pipefail

REPO_URL="${VUEA_REPO_URL:-https://github.com/JornGitHub/VU-EA-Conversational-AI.git}"
TARGET_DIR="${VUEA_DIR:-$HOME/VU-EA-Conversational-AI}"
BRANCH="${VUEA_BRANCH:-main}"

info() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33m!  %s\033[0m\n' "$1"; }
fail() { printf '\033[31m✗  %s\033[0m\n' "$1" >&2; exit 1; }

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
    echo "Geen Python 3.10 of nieuwer gevonden."
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "Installeer Python via https://www.python.org/downloads/ of met: brew install python"
    else
        echo "Installeer Python via je pakketbeheerder, bijvoorbeeld: sudo apt install python3 python3-venv"
    fi
    fail "Python ontbreekt"
fi
echo "Gevonden: $($PYTHON --version) ($(command -v "$PYTHON"))"

# ------------------------------------------------------------------ code ----
if [ -d "$TARGET_DIR/.git" ]; then
    info "Bestaande installatie bijwerken in $TARGET_DIR"
    git -C "$TARGET_DIR" fetch --quiet origin "$BRANCH" || warn "Bijwerken mislukt; verder met de huidige versie."
    git -C "$TARGET_DIR" checkout --quiet "$BRANCH" 2>/dev/null || true
    git -C "$TARGET_DIR" pull --quiet --ff-only origin "$BRANCH" || warn "Kon niet bijwerken (lokale wijzigingen?); verder met de huidige versie."
elif [ -d "$TARGET_DIR" ] && [ -f "$TARGET_DIR/main.py" ]; then
    info "Bestaande map gevonden in $TARGET_DIR (geen git-kopie); die wordt gebruikt zoals hij is"
else
    info "Code ophalen naar $TARGET_DIR"
    command -v git >/dev/null 2>&1 || fail "git is niet geïnstalleerd. Installeer git en probeer opnieuw."
    git clone --quiet --branch "$BRANCH" "$REPO_URL" "$TARGET_DIR" || fail "Clonen van $REPO_URL is mislukt."
fi

cd "$TARGET_DIR"
[ -f main.py ] || fail "main.py niet gevonden in $TARGET_DIR."

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
