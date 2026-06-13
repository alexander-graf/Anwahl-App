#!/bin/bash

# Stelle sicher, dass DISPLAY und PATH für die GUI korrekt geladen sind
export DISPLAY=${DISPLAY:-:0}
export PATH="/usr/bin:/usr/local/bin:/opt/android-sdk/platform-tools:$PATH"

# Projekt-Verzeichnisse definieren
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VENV="$PROJECT_DIR/venv/bin/python"
APP_SCRIPT="$PROJECT_DIR/app.py"

# Wenn ein Parameter übergeben wurde (z. B. durch Klipper/Zwischenablage), direkt im Wählmodus starten
if [ -n "$1" ]; then
    $PYTHON_VENV $APP_SCRIPT dial "$1"
else
    # Andernfalls die Hauptanwendung (KDE Telefonzentrale) starten
    $PYTHON_VENV $APP_SCRIPT
fi
