#!/bin/bash

# Pfad zum Projekt-Ordner definieren
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IP_FILE="$PROJECT_DIR/device_ip.txt"

# 1. Prüfen, ob Argumente übergeben wurden
if [ $# -lt 2 ]; then
    echo "Nutzung: $0 <Telefonnummer> \"<Deine Nachricht>\""
    echo "Beispiel: $0 +491701234567 \"Hallo Welt\""
    exit 1
fi

NUMBER="$1"
MESSAGE="$2"

# 2. Prüfen, ob ADB-Verbindung steht, ansonsten verbinden
if ! adb devices | grep -q -E "device$"; then
    if [ -f "$IP_FILE" ]; then
        IP_PORT=$(cat "$IP_FILE" | tr -d '\r\n ')
        echo "Keine aktive ADB-Verbindung gefunden. Verbinde mit $IP_PORT..."
        adb connect "$IP_PORT"
        sleep 2
    else
        echo "Fehler: Keine aktive ADB-Verbindung und $IP_FILE nicht gefunden!"
        exit 1
    fi
fi

# 3. SMS über Termux senden (via stdin gepipet, um Shell-Escaping-Fehler mit Sonderzeichen wie Klammern zu vermeiden)
echo "Sende SMS an $NUMBER..."
echo "$MESSAGE" | adb shell run-as com.termux env PATH=/data/data/com.termux/files/usr/bin LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec.so /data/data/com.termux/files/usr/bin/termux-sms-send -n "$NUMBER"

if [ $? -eq 0 ]; then
    echo "Befehl erfolgreich an das Handy gesendet!"
else
    echo "Fehler beim Senden des Befehls."
fi
