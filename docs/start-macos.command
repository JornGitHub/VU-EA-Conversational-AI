#!/usr/bin/env bash
# VU EA Conversational AI - dubbelklik dit bestand om de app te starten (macOS).
#
# De eerste keer vraagt macOS toestemming ("kan niet worden geopend omdat het
# van een niet-geverifieerde ontwikkelaar komt"): klik met de rechtermuisknop op
# dit bestand > Open > Open. Daarna volstaat dubbelklikken.
set -euo pipefail
curl -fsSL https://vusaverse.github.io/VU-EA-Conversational-AI/start.sh | bash
