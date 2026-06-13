#!/bin/bash

# Stelle sicher, dass DISPLAY und PATH für PyQt6-GUI und ADB korrekt geladen sind
export DISPLAY=${DISPLAY:-:0}
export PATH="/usr/bin:/usr/local/bin:/opt/android-sdk/platform-tools:$PATH"

# Projekt-Verzeichnis definieren
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VENV="$PROJECT_DIR/venv/bin/python"
APP_SCRIPT="$PROJECT_DIR/app.py"

# Prüfen, ob die venv existiert
if [ ! -f "$PYTHON_VENV" ]; then
    echo "Fehler: Virtuelle Umgebung (venv) wurde unter $PYTHON_VENV nicht gefunden."
    echo "Bitte erstelle sie mit: python3 -m venv venv && source venv/bin/activate && pip install PyQt6"
    exit 1
fi

# App mit dem venv-Python starten und alle eventuellen Argumente weitergeben
$PYTHON_VENV $APP_SCRIPT "$@"
