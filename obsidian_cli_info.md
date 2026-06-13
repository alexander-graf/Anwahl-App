# Hinweise zur Nutzung von `obsidian-cli` (für nachfolgende Gemini-Instanzen)

Dieses Dokument enthält wichtige Erkenntnisse über die Nutzung des CLI-Tools `obsidian-cli` (auch bekannt als `notesmd-cli`), die während dieser Session gesammelt wurden, um nachfolgenden KI-Assistenten die Einarbeitung zu ersparen.

---

## 🔍 Befehlsname & Pfade
*   Auf dem System ist das Tool unter `/usr/bin/obsidian-cli` installiert.
*   **Wichtig:** In den internen Hilfe-Texten und Fehlermeldungen bezeichnet sich das Tool selbst oft als `notesmd-cli`. In Shell-Skripten und im Terminal **muss** jedoch `obsidian-cli` aufgerufen werden.
*   Die Konfiguration liegt im Verzeichnis des Benutzers unter: `~/.config/notesmd-cli/`

---

## 📂 Vault-Konfiguration & Defaults
Wenn das Tool den Fehler ausgibt:
> *Cannot find vault config, please use set-default-vault command to set default vault or use --vault flag*

...dann wurde ein Vault zwar registriert, aber noch kein Standard-Vault definiert. Das wird wie folgt gelöst:

1.  **Registrierte Vaults auflisten:**
    ```bash
    obsidian-cli list-vaults
    ```
2.  **Standard-Vault setzen (zwingend erforderlich für pfadlose Befehle):**
    ```bash
    obsidian-cli set-default-vault <Vault-Name>
    ```
    *Beispiel für dieses System:*
    ```bash
    obsidian-cli set-default-vault ObsidianVault_ITBusiness
    ```

---

## 📝 Wichtige Befehle & Flags

### 1. Notiz erstellen / bearbeiten (`create` bzw. `c`)
Erstellt eine neue Notiz oder hängt Text an eine bestehende an.
```bash
obsidian-cli create "Notiz_Name" --content "Inhalt" [Flags]
```
*   **`--append` (oder `-a`):** Hängt den Inhalt an die bestehende Notiz an (fügt ihn am Ende hinzu). Wenn die Notiz noch nicht existiert, wird sie neu erstellt.
*   **`--overwrite` (oder `-o`):** Überschreibt die Notiz vollständig.
*   **`--open`:** Öffnet die Notiz nach dem Erstellen/Bearbeiten direkt in der grafischen Obsidian-App.

### 2. Notiz öffnen (`open` bzw. `o`)
Öffnet eine Notiz in Obsidian.
```bash
obsidian-cli open "Notiz_Name"
```
*   **`--editor` (oder `-e`):** Öffnet die Datei im Standard-Texteditor des Systems (z. B. Nano/Vim) statt in Obsidian.
*   **`--section "Überschrift"` (oder `-s`):** Springt direkt zu einer bestimmten Überschrift (Case-Sensitive).

### 3. Notiz anzeigen (`print`)
Gibt den Inhalt einer Notiz auf der Standardausgabe (stdout) aus.
```bash
obsidian-cli print "Notiz_Name"
```

### 4. Notiz löschen (`delete` bzw. `d`)
Löscht eine Notiz dauerhaft aus dem aktiven Vault.
```bash
obsidian-cli delete "Notiz_Name"
```
