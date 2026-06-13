import sys
import os
import sqlite3
import subprocess
import time
import re
import threading
from datetime import datetime
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QDialog, QTextEdit, QMessageBox,
    QMenu
)

# Pfade und Umgebungsdaten einrichten
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "app.db")
HOME_DIR = os.path.expanduser("~")
VAULT_PATH = os.path.join(HOME_DIR, "Nextcloud/ObsidianVault_ITBusiness")
os.environ["PATH"] += ":/opt/android-sdk/platform-tools:/usr/local/bin"

def get_db_connection():
    return sqlite3.connect(DB_PATH, timeout=20.0)

# ----------------- HILFSFUNKTIONEN -----------------

def format_phone_number(num):
    if not num:
        return ""
    # Bereinigen
    num = "".join(c for c in num if c.isdigit() or c == '+')
    
    # Formatierung für deutsche Nummern
    if num.startswith("+49"):
        if len(num) >= 7:
            # Mobilfunk-Prefixe (+49 15x, +49 16x, +49 17x)
            if num.startswith("+4915") or num.startswith("+4916") or num.startswith("+4917"):
                return f"+49 {num[3:6]} {num[6:]}"
            # Festnetz-Prefixe (+49 30, +49 89 etc., ca. 3-4 Ziffern)
            return f"+49 {num[3:7]} {num[7:]}"
        return num
    elif num.startswith("0049"):
        if len(num) >= 8:
            if num.startswith("004915") or num.startswith("004916") or num.startswith("004917"):
                return f"+49 {num[4:7]} {num[7:]}"
            return f"+49 {num[4:8]} {num[8:]}"
        return num
    elif num.startswith("0"):
        if len(num) >= 5:
            # Mobilfunk (015x, 016x, 017x)
            if num.startswith("015") or num.startswith("016") or num.startswith("017"):
                return f"{num[0:4]} {num[4:]}"
            # Festnetz (z. B. 05251, 089)
            return f"{num[0:5]} {num[5:]}"
        return num
    return num

# ----------------- DATENBANK FUNKTIONEN -----------------

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            phone_number TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS deleted_contacts (
            phone_number TEXT PRIMARY KEY
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL,
            note TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS sms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            body TEXT NOT NULL,
            type INTEGER NOT NULL,
            imported INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    try:
        c.execute("ALTER TABLE contacts ADD COLUMN telegram_username TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

def db_get_setting(key, default=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else default

def db_set_setting(key, value):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def db_add_sms(phone_number, timestamp, body, type_val, imported=1):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM sms WHERE phone_number = ? AND timestamp = ? AND body = ?", (phone_number, timestamp, body))
    if not c.fetchone():
        c.execute("INSERT INTO sms (phone_number, timestamp, body, type, imported) VALUES (?, ?, ?, ?, ?)", (phone_number, timestamp, body, type_val, imported))
        conn.commit()
        success = True
    else:
        success = False
    conn.close()
    return success

def db_add_contact(number, name, telegram_username=None):
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM deleted_contacts WHERE phone_number = ?", (number,))
        c.execute("INSERT OR REPLACE INTO contacts (phone_number, name, telegram_username) VALUES (?, ?, ?)", (number, name, telegram_username))
        conn.commit()
        success = True
    except Exception:
        success = False
    conn.close()
    return success

def db_delete_contact(number):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO deleted_contacts (phone_number) VALUES (?)", (number,))
    c.execute("DELETE FROM contacts WHERE phone_number = ?", (number,))
    conn.commit()
    conn.close()

def db_get_all_contacts():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name, phone_number, telegram_username FROM contacts ORDER BY name ASC")
    rows = c.fetchall()
    conn.close()
    return rows

def db_get_contact_name(number):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM contacts WHERE phone_number = ?", (number,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def db_get_contact_telegram_username(number):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT telegram_username FROM contacts WHERE phone_number = ?", (number,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def db_add_call_start(number):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO calls (phone_number, status, note) VALUES (?, 'initiated', '')", (number,))
    call_id = c.lastrowid
    conn.commit()
    conn.close()
    return call_id

def db_update_call_end(call_id, status, note):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE calls SET status = ?, note = ? WHERE id = ?", (status, note, call_id))
    conn.commit()
    conn.close()

def db_get_call_history():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT c.id, c.phone_number, co.name, c.timestamp, c.status, c.note 
        FROM calls c
        LEFT JOIN contacts co ON c.phone_number = co.phone_number
        ORDER BY c.timestamp DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return rows

# ----------------- ADB TELEFONIE -----------------

def ensure_adb_connected():
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        if len(lines) <= 1:
            ip_file = os.path.join(SCRIPT_DIR, "device_ip.txt")
            if os.path.exists(ip_file):
                with open(ip_file, "r") as f:
                    ip_port = f.read().strip()
                if ip_port:
                    print(f"ADB nicht verbunden. Verbinde mit {ip_port}...")
                    subprocess.run(["adb", "connect", ip_port], check=True)
    except Exception as e:
        print(f"Fehler bei ADB Connect: {e}")

def adb_dial(number):
    ensure_adb_connected()
    try:
        subprocess.run(["adb", "shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{number}"], check=True)
    except Exception as e:
        print(f"ADB Dial Fehler: {e}")

def adb_hang_up():
    ensure_adb_connected()
    try:
        subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_ENDCALL"], check=True)
    except Exception as e:
        print(f"ADB Hangup Fehler: {e}")

def adb_send_sms(number, message):
    ensure_adb_connected()
    try:
        cmd = [
            "adb", "shell", "run-as", "com.termux",
            "env", "PATH=/data/data/com.termux/files/usr/bin",
            "LD_PRELOAD=/data/data/com.termux/files/usr/lib/libtermux-exec.so",
            "/data/data/com.termux/files/usr/bin/termux-sms-send", "-n", number
        ]
        subprocess.run(cmd, input=message, text=True, check=True)
        return True
    except Exception as e:
        print(f"ADB SMS Fehler: {e}")
        return False

def adb_import_contacts():
    ensure_adb_connected()
    try:
        res = subprocess.run([
            "adb", "shell", "content", "query", 
            "--uri", "content://contacts/phones", 
            "--projection", "display_name:number"
        ], capture_output=True, text=True, check=True)
        
        imported_count = 0
        conn = get_db_connection()
        c = conn.cursor()
        
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                parts = line.split(" display_name=", 1)
                if len(parts) < 2:
                    continue
                rem = parts[1]
                rparts = rem.rsplit(", number=", 1)
                if len(rparts) < 2:
                    continue
                name = rparts[0].strip()
                number = rparts[1].strip()
                cleaned_number = "".join(ch for ch in number if ch.isdigit() or ch == '+')
                if cleaned_number and name:
                    # Prüfen, ob der Kontakt lokal gelöscht wurde
                    c.execute("SELECT 1 FROM deleted_contacts WHERE phone_number = ?", (cleaned_number,))
                    if c.fetchone():
                        continue
                    c.execute("INSERT INTO contacts (phone_number, name) VALUES (?, ?) ON CONFLICT(phone_number) DO UPDATE SET name=excluded.name", (cleaned_number, name))
                    imported_count += 1
                    
        conn.commit()
        conn.close()
        return True, imported_count
    except Exception as e:
        print(f"ADB Import Fehler: {e}")
        return False, 0

def adb_import_call_log():
    ensure_adb_connected()
    try:
        res = subprocess.run([
            "adb", "shell", "content", "query", 
            "--uri", "content://call_log/calls", 
            "--projection", "number:date:type:duration"
        ], capture_output=True, text=True, check=True)
        
        imported_count = 0
        conn = get_db_connection()
        c = conn.cursor()
        
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                parts = line.split(" number=", 1)
                if len(parts) < 2:
                    continue
                rem = parts[1]
                fields = rem.split(", ")
                if len(fields) < 4:
                    continue
                number = fields[0].strip()
                date_val = fields[1].split("=")[1].strip()
                type_val = fields[2].split("=")[1].strip()
                duration_val = fields[3].split("=")[1].strip()
                
                try:
                    epoch_seconds = int(date_val) / 1000.0
                    timestamp = datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                
                status = "connected"
                if type_val in ["3", "5"]:
                    status = "no_answer"
                
                cleaned_number = "".join(ch for ch in number if ch.isdigit() or ch == '+')
                if not cleaned_number or cleaned_number == "NULL":
                    continue
                    
                c.execute("SELECT id FROM calls WHERE phone_number = ? AND timestamp = ?", (cleaned_number, timestamp))
                if not c.fetchone():
                    c.execute(
                        "INSERT INTO calls (phone_number, timestamp, status, note) VALUES (?, ?, ?, ?)",
                        (cleaned_number, timestamp, status, f"Importiert (Dauer: {duration_val}s)")
                    )
                    imported_count += 1
                    
        conn.commit()
        conn.close()
        return True, imported_count
    except Exception as e:
        print(f"ADB Call Log Import Fehler: {e}")
        return False, 0

def adb_import_sms():
    ensure_adb_connected()
    try:
        res = subprocess.run([
            "adb", "shell", "content", "query",
            "--uri", "content://sms/",
            "--projection", "address:body:date:type"
        ], capture_output=True, text=True, check=True)
        
        imported_count = 0
        conn = get_db_connection()
        c = conn.cursor()
        
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                parts = line.split(" address=", 1)
                if len(parts) < 2:
                    continue
                rem = parts[1]
                
                bparts = rem.split(", body=", 1)
                if len(bparts) < 2:
                    continue
                address = bparts[0].strip()
                rem2 = bparts[1]
                
                dparts = rem2.rsplit(", date=", 1)
                if len(dparts) < 2:
                    continue
                body = dparts[0]
                rem3 = dparts[1]
                
                tparts = rem3.split(", type=", 1)
                if len(tparts) < 2:
                    continue
                date_val = tparts[0].strip()
                type_val = tparts[1].strip()
                
                try:
                    epoch_seconds = int(date_val) / 1000.0
                    timestamp = datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                
                cleaned_number = "".join(ch for ch in address if ch.isdigit() or ch == '+')
                if not cleaned_number or cleaned_number == "NULL":
                    continue
                    
                c.execute("SELECT id FROM sms WHERE phone_number = ? AND timestamp = ? AND body = ?", (cleaned_number, timestamp, body))
                if not c.fetchone():
                    c.execute(
                        "INSERT INTO sms (phone_number, timestamp, body, type, imported) VALUES (?, ?, ?, ?, 1)",
                        (cleaned_number, timestamp, body, int(type_val))
                    )
                    imported_count += 1
                    
        conn.commit()
        conn.close()
        return True, imported_count
    except Exception as e:
        print(f"ADB SMS Import Fehler: {e}")
        return False, 0

def adb_add_contact_to_phone(number, name):
    ensure_adb_connected()
    try:
        # 1. Maximale ID holen
        res = subprocess.run(
            'adb shell "content query --uri content://com.android.contacts/raw_contacts --projection _id"',
            shell=True, capture_output=True, text=True, timeout=3
        )
        pre_max = -1
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                match = re.search(r"_id=(\d+)", line)
                if match:
                    val = int(match.group(1))
                    if val > pre_max:
                        pre_max = val
                        
        # 2. Raw Contact erstellen
        subprocess.run(
            'adb shell "content insert --uri content://com.android.contacts/raw_contacts --bind account_type:s:null --bind account_name:s:null"',
            shell=True, timeout=3
        )
        
        # 3. Neue maximale ID holen
        res = subprocess.run(
            'adb shell "content query --uri content://com.android.contacts/raw_contacts --projection _id"',
            shell=True, capture_output=True, text=True, timeout=3
        )
        post_max = -1
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                match = re.search(r"_id=(\d+)", line)
                if match:
                    val = int(match.group(1))
                    if val > post_max:
                        post_max = val
                        
        if post_max > pre_max and post_max != -1:
            raw_contact_id = str(post_max)
            # 4. Namen einfügen
            subprocess.run(
                f'adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:{raw_contact_id} --bind mimetype:s:vnd.android.cursor.item/name --bind data1:s:\'{name}\'"',
                shell=True, timeout=3
            )
            # 5. Telefonnummer einfügen
            subprocess.run(
                f'adb shell "content insert --uri content://com.android.contacts/data --bind raw_contact_id:i:{raw_contact_id} --bind mimetype:s:vnd.android.cursor.item/phone_v2 --bind data1:s:\'{number}\' --bind data2:i:2"',
                shell=True, timeout=3
            )
            return True
    except Exception as e:
        print(f"Fehler bei adb_add_contact_to_phone: {e}")
    return False

def adb_delete_contact_from_phone(number):
    ensure_adb_connected()
    try:
        # Finde raw_contact_ids
        cmd_query = f'adb shell "content query --uri content://com.android.contacts/data --projection raw_contact_id --where \\"data1=\'{number}\'\\""'
        res = subprocess.run(cmd_query, shell=True, capture_output=True, text=True, timeout=3)
        ids = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Row:"):
                match = re.search(r"raw_contact_id=(\d+)", line)
                if match:
                    ids.append(match.group(1))
        
        if ids:
            for cid in set(ids):
                subprocess.run(
                    f'adb shell "content delete --uri content://com.android.contacts/raw_contacts --where \\"_id={cid}\\""',
                    shell=True, timeout=3
                )
            return True
    except Exception as e:
        print(f"Fehler bei adb_delete_contact_from_phone: {e}")
    return False

def db_get_sms_history():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT s.id, s.phone_number, co.name, s.timestamp, s.body, s.type 
        FROM sms s
        LEFT JOIN contacts co ON s.phone_number = co.phone_number
        ORDER BY s.timestamp DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return rows

# ----------------- OBSIDIAN INTEGRATION -----------------

def get_obsidian_note_name(phone_number):
    return f"Anruf_{phone_number}"

def write_obsidian_call_start(phone_number):
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    note_name = get_obsidian_note_name(phone_number)
    note_file = os.path.join(VAULT_PATH, f"{note_name}.md")
    
    formatted_content = f"\\n\\n## Anruf am {date_str}"
    
    try:
        if not os.path.exists(note_file):
            content = f"# Anruf-Protokoll: {format_phone_number(phone_number)}{formatted_content}"
            subprocess.run(["obsidian-cli", "create", note_name, "--content", content], check=True)
        else:
            subprocess.run(["obsidian-cli", "create", note_name, "--content", formatted_content, "--append"], check=True)
    except Exception as e:
        print(f"Obsidian Note Start Fehler: {e}")

def write_obsidian_call_end(phone_number, status, note_content=""):
    note_name = get_obsidian_note_name(phone_number)
    
    if status == "connected":
        if note_content:
            formatted_content = f"\\n{note_content}"
        else:
            formatted_content = f"\\n- Gespräch geführt (keine Notiz)"
    else:
        formatted_content = f"\\n- Nicht erreicht (aufgelegt)"
        
    try:
        subprocess.run(["obsidian-cli", "create", note_name, "--content", formatted_content, "--append"], check=True)
    except Exception as e:
        print(f"Obsidian Note End Fehler: {e}")

def open_obsidian_note(phone_number):
    note_name = get_obsidian_note_name(phone_number)
    try:
        subprocess.run(["obsidian-cli", "open", note_name], check=True)
    except Exception as e:
        print(f"Obsidian Note Open Fehler: {e}")

# ----------------- DESIGN STYLESHEET (DARK MODE) -----------------

DARK_STYLE = """
QMainWindow, QDialog {
    background-color: #1a1a1a;
    color: #e0e0e0;
}
QTabWidget::pane {
    border: 1px solid #333333;
    background-color: #242424;
    border-radius: 8px;
}
QTabBar::tab {
    background-color: #1a1a1a;
    color: #aaaaaa;
    padding: 10px 20px;
    border: 1px solid #333333;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #242424;
    color: #00a8ff;
    border-color: #333333;
}
QLabel {
    font-size: 13px;
    color: #e0e0e0;
}
QLineEdit, QTextEdit {
    background-color: #2d2d2d;
    color: #ffffff;
    border: 1px solid #444444;
    border-radius: 4px;
    padding: 6px;
    font-size: 14px;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #00a8ff;
}
QPushButton {
    background-color: #00a8ff;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #008fdb;
}
QPushButton:pressed {
    background-color: #0077b8;
}
QPushButton#hangUpBtn {
    background-color: #ff3b30;
}
QPushButton#hangUpBtn:hover {
    background-color: #e03228;
}
QPushButton#hangUpBtn:pressed {
    background-color: #c42a20;
}
QPushButton#secondaryBtn {
    background-color: #444444;
}
QPushButton#secondaryBtn:hover {
    background-color: #555555;
}
QTableWidget {
    background-color: #242424;
    color: #ffffff;
    gridline-color: #333333;
    border: 1px solid #333333;
    border-radius: 6px;
}
QTableWidget::item {
    padding: 6px;
}
QTableWidget::item:selected {
    background-color: #00a8ff;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #2d2d2d;
    color: #aaaaaa;
    padding: 6px;
    border: 1px solid #333333;
    font-weight: bold;
}
"""

# ----------------- GUI-KOMPONENTEN -----------------

class ActiveCallDialog(QDialog):
    def __init__(self, number, parent=None, is_incoming=False):
        super().__init__(parent)
        self.number = number
        self.is_incoming = is_incoming
        self.call_id = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Anwahl-App - Aktiver Anruf")
        self.setObjectName("activeCallDialog")
        self.setWindowIcon(QIcon(os.path.join(SCRIPT_DIR, "icon.png")))
        self.setFixedSize(600, 480)
        
        layout = QVBoxLayout()
        
        lbl_info = QLabel("Anruf läuft...")
        lbl_info.setStyleSheet("font-size: 16px; font-weight: bold; color: #00a8ff;")
        layout.addWidget(lbl_info)
        
        # Feld zum Speichern/Anzeigen des Kontaktnamens während des Anrufs
        layout.addWidget(QLabel("<b>Name des Kontakts:</b> (Wird beim Auflegen gespeichert)"))
        self.txt_contact_name = QLineEdit()
        existing_name = db_get_contact_name(self.number)
        if existing_name:
            self.txt_contact_name.setText(existing_name)
        self.txt_contact_name.setPlaceholderText("Unbekannter Kontakt (Name eingeben...)")
        layout.addWidget(self.txt_contact_name)
        
        layout.addWidget(QLabel("<b>Nummer:</b>"))
        lbl_num = QLabel(format_phone_number(self.number))
        lbl_num.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(lbl_num)
        
        layout.addWidget(QLabel("<b>Gesprächsnotiz:</b>"))
        self.txt_note = QTextEdit()
        self.txt_note.setPlaceholderText("Schreibe hier deine Notizen während des Gesprächs...")
        layout.addWidget(self.txt_note)
        
        btn_layout = QHBoxLayout()
        
        btn_save = QPushButton("Auflegen und Notiz speichern")
        btn_save.clicked.connect(self.action_save_note)
        btn_layout.addWidget(btn_save)
        
        btn_no_note = QPushButton("Ohne Notiz auflegen")
        btn_no_note.setObjectName("hangUpBtn")
        btn_no_note.clicked.connect(self.action_no_note)
        btn_layout.addWidget(btn_no_note)
        
        btn_no_answer = QPushButton("Nicht erreicht")
        btn_no_answer.setObjectName("secondaryBtn")
        btn_no_answer.clicked.connect(self.action_no_answer)
        btn_layout.addWidget(btn_no_answer)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        # 1. Anrufversuch sofort in DB und Obsidian einloggen (bevor abgehoben wird)
        self.call_id = db_add_call_start(self.number)
        write_obsidian_call_start(self.number)
        
        # 2. Anruf auf dem Handy starten (nur bei ausgehenden Anrufen!)
        if not self.is_incoming:
            adb_dial(self.number)
        
    def check_and_save_contact(self):
        # Überprüfen, ob ein Name eingegeben wurde und den Kontakt speichern/aktualisieren
        name = self.txt_contact_name.text().strip()
        if name:
            db_add_contact(self.number, name)
        
    def action_save_note(self):
        note_text = self.txt_note.toPlainText().strip()
        adb_hang_up()
        self.check_and_save_contact()
        db_update_call_end(self.call_id, "connected", note_text)
        write_obsidian_call_end(self.number, "connected", note_text)
        self.accept()
        
    def action_no_note(self):
        adb_hang_up()
        self.check_and_save_contact()
        db_update_call_end(self.call_id, "connected", "Gespräch geführt (keine Notiz)")
        write_obsidian_call_end(self.number, "connected", "")
        self.accept()
        
    def action_no_answer(self):
        adb_hang_up()
        self.check_and_save_contact()
        db_update_call_end(self.call_id, "no_answer", "Nicht erreicht (aufgelegt)")
        write_obsidian_call_end(self.number, "no_answer")
        self.accept()

    def reject(self):
        # Wenn der Nutzer das Fenster einfach schließt (X oder ESC)
        adb_hang_up()
        self.check_and_save_contact()
        db_update_call_end(self.call_id, "connected", "Gespräch beendet (Fenster geschlossen)")
        write_obsidian_call_end(self.number, "connected", "")
        super().reject()


class CallMonitorThread(QThread):
    incoming_call = pyqtSignal(str)
    call_ended = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True
        self.was_ringing = False
        
    def run(self):
        while self.running:
            try:
                # We do dumpsys telephony.registry to check call state
                res = subprocess.run(
                    ["adb", "shell", "dumpsys", "telephony.registry"],
                    capture_output=True, text=True, timeout=2
                )
                if res.returncode == 0:
                    state = "0"
                    number = ""
                    for line in res.stdout.splitlines():
                        line = line.strip()
                        if line.startswith("mCallState="):
                            curr_state = line.split("=")[1].strip()
                            if curr_state == "1":
                                state = "1"
                        elif line.startswith("mCallIncomingNumber="):
                            curr_number = line.split("=")[1].strip()
                            if curr_number:
                                number = curr_number
                    
                    if state == "1":
                        if not self.was_ringing:
                            self.was_ringing = True
                            self.incoming_call.emit(number)
                    elif state in ["0", "2"]:
                        if self.was_ringing:
                            self.was_ringing = False
                            self.call_ended.emit()
            except Exception as e:
                pass
            time.sleep(1.5)
            
    def stop(self):
        self.running = False


class StartupSyncThread(QThread):
    sync_step_finished = pyqtSignal(str, int)  # "contacts"|"calls"|"sms", count
    sync_finished = pyqtSignal()
    
    def run(self):
        # 1. Kontakte importieren
        try:
            success, count = adb_import_contacts()
            if success:
                self.sync_step_finished.emit("contacts", count)
        except Exception as e:
            print(f"Hintergrund-Sync (Kontakte) Fehler: {e}")

        # 2. Anrufe importieren
        try:
            success, count = adb_import_call_log()
            if success:
                self.sync_step_finished.emit("calls", count)
        except Exception as e:
            print(f"Hintergrund-Sync (Anrufe) Fehler: {e}")

        # 3. SMS importieren
        try:
            success, count = adb_import_sms()
            if success:
                self.sync_step_finished.emit("sms", count)
        except Exception as e:
            print(f"Hintergrund-Sync (SMS) Fehler: {e}")
            
        self.sync_finished.emit()


class IncomingCallDialog(QDialog):
    def __init__(self, number, parent=None):
        super().__init__(parent)
        self.number = number
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Eingehender Anruf!")
        self.setFixedSize(350, 180)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        
        layout = QVBoxLayout()
        
        name = db_get_contact_name(self.number) or "Unbekannter Anrufer"
        
        lbl_info = QLabel("<b>Eingehender Anruf auf dem Handy!</b>")
        lbl_info.setStyleSheet("font-size: 14px; color: #00a8ff;")
        layout.addWidget(lbl_info)
        
        layout.addWidget(QLabel(f"<b>Anrufer:</b> {name}"))
        layout.addWidget(QLabel(f"<b>Nummer:</b> {format_phone_number(self.number)}"))
        
        btn_layout = QHBoxLayout()
        
        btn_accept = QPushButton("Annehmen")
        btn_accept.setStyleSheet("background-color: #28a745; font-weight: bold;")
        btn_accept.clicked.connect(self.accept_call)
        btn_layout.addWidget(btn_accept)
        
        btn_reject = QPushButton("Ablehnen")
        btn_reject.setStyleSheet("background-color: #ff3b30; font-weight: bold;")
        btn_reject.clicked.connect(self.reject_call)
        btn_layout.addWidget(btn_reject)
        
        btn_ignore = QPushButton("Ignorieren")
        btn_ignore.setObjectName("secondaryBtn")
        btn_ignore.clicked.connect(self.reject)
        btn_layout.addWidget(btn_ignore)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
    def accept_call(self):
        try:
            subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_CALL"], check=True)
            self.done(1)
        except Exception as e:
            print(f"Fehler beim Annehmen: {e}")
            self.reject()
            
    def reject_call(self):
        try:
            subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_ENDCALL"], check=True)
            self.done(2)
        except Exception as e:
            print(f"Fehler beim Ablehnen: {e}")
            self.reject()


class SendSMSDialog(QDialog):
    def __init__(self, number, name="Unbekannt", parent=None):
        super().__init__(parent)
        self.number = number
        self.name = name
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(f"SMS senden an {self.name}")
        self.setFixedSize(450, 250)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel(f"<b>Empfänger:</b> {format_phone_number(self.number)} ({self.name})"))
        
        layout.addWidget(QLabel("<b>Nachricht:</b>"))
        self.txt_message = QTextEdit()
        self.txt_message.setPlaceholderText("Schreibe hier deine SMS...")
        layout.addWidget(self.txt_message)
        
        btn_layout = QHBoxLayout()
        btn_send = QPushButton("Senden")
        btn_send.clicked.connect(self.send_sms)
        btn_layout.addWidget(btn_send)
        
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
    def send_sms(self):
        msg = self.txt_message.toPlainText().strip()
        if not msg:
            QMessageBox.critical(self, "Fehler", "Bitte eine Nachricht eingeben!")
            return
            
        self.setEnabled(False)
        success = adb_send_sms(self.number, msg)
        self.setEnabled(True)
        
        if success:
            db_add_sms(self.number, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg, 2, imported=0)
            QMessageBox.information(self, "Erfolg", "SMS wurde erfolgreich gesendet!")
            self.accept()
        else:
            QMessageBox.critical(self, "Fehler", "SMS konnte nicht gesendet werden. Prüfe die ADB-Verbindung.")


class AddContactDialog(QDialog):
    def __init__(self, prefilled_number="", prefilled_name="", parent=None, prefilled_telegram=""):
        super().__init__(parent)
        self.prefilled_number = prefilled_number
        self.prefilled_name = prefilled_name
        self.prefilled_telegram = prefilled_telegram
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Kontakt bearbeiten")
        self.setFixedSize(350, 240)
        
        layout = QVBoxLayout()
        
        layout.addWidget(QLabel("Name des Kontakts:"))
        self.txt_name = QLineEdit(self.prefilled_name)
        layout.addWidget(self.txt_name)
        
        layout.addWidget(QLabel("Telefonnummer:"))
        self.txt_number = QLineEdit(self.prefilled_number)
        layout.addWidget(self.txt_number)

        layout.addWidget(QLabel("Telegram Username (optional, z.B. @name):"))
        self.txt_telegram = QLineEdit(self.prefilled_telegram)
        layout.addWidget(self.txt_telegram)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("Speichern")
        btn_ok.clicked.connect(self.save)
        btn_layout.addWidget(btn_ok)
        
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setObjectName("secondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
    def save(self):
        name = self.txt_name.text().strip()
        number = self.txt_number.text().strip()
        telegram = self.txt_telegram.text().strip()
        cleaned_number = "".join(c for c in number if c.isdigit() or c == '+')
        
        if telegram.startswith("@"):
            telegram = telegram[1:]
            
        if not name or not cleaned_number:
            QMessageBox.critical(self, "Fehler", "Bitte Name und eine gültige Nummer eingeben!")
            return
            
        if db_add_contact(cleaned_number, name, telegram if telegram else None):
            def do_sync():
                adb_delete_contact_from_phone(cleaned_number)
                adb_add_contact_to_phone(cleaned_number, name)
            threading.Thread(target=do_sync, daemon=True).start()
            self.accept()
        else:
            QMessageBox.critical(self, "Fehler", "Fehler beim Speichern in der Datenbank!")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
        self.incoming_call_dlg = None
        self.monitor_thread = CallMonitorThread(self)
        self.monitor_thread.incoming_call.connect(self.handle_incoming_call)
        self.monitor_thread.call_ended.connect(self.handle_call_ended)
        self.monitor_thread.start()
        
        # Hintergrund-Sync beim Starten ausführen
        self.sync_thread = StartupSyncThread(self)
        self.sync_thread.sync_step_finished.connect(self.handle_sync_step)
        self.sync_thread.sync_finished.connect(self.handle_sync_finished)
        self.sync_thread.start()
        
    def init_ui(self):
        self.setWindowTitle("Anwahl-App (KDE Telefonzentrale)")
        self.setWindowIcon(QIcon(os.path.join(SCRIPT_DIR, "icon.png")))
        self.setMinimumSize(1300, 600)
        
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Tabs erstellen
        self.tabs = QTabWidget()
        self.tab_dial = QWidget()
        self.tab_contacts = QWidget()
        self.tab_sms = QWidget()
        
        self.tabs.addTab(self.tab_dial, "Wählen & Verlauf")
        self.tabs.addTab(self.tab_contacts, "Kontakte verwalten")
        self.tabs.addTab(self.tab_sms, "SMS-Verlauf")
        
        self.setup_dial_tab()
        self.setup_contacts_tab()
        self.setup_sms_tab()
        
        main_layout.addWidget(self.tabs)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
    # ----------------- WÄHL- & VERLAUF-TAB -----------------
    
    def setup_dial_tab(self):
        layout = QVBoxLayout()
        
        # Wahlzeile oben
        dial_layout = QHBoxLayout()
        self.txt_number = QLineEdit()
        self.txt_number.setPlaceholderText("Telefonnummer eingeben...")
        self.txt_number.setStyleSheet("font-size: 18px; padding: 10px;")
        
        # Zwischenablage prüfen und ggf. vorausfüllen
        clip_text = QApplication.clipboard().text().strip()
        cleaned_clip = "".join(c for c in clip_text if c.isdigit() or c == '+')
        if len(cleaned_clip) >= 5:
            self.txt_number.setText(cleaned_clip)
            
        dial_layout.addWidget(self.txt_number)
        
        btn_dial = QPushButton("Wählen")
        btn_dial.setStyleSheet("font-size: 16px; padding: 10px 25px;")
        btn_dial.clicked.connect(self.action_dial_input)
        dial_layout.addWidget(btn_dial)

        btn_sms = QPushButton("SMS senden")
        btn_sms.setStyleSheet("font-size: 16px; padding: 10px 25px; background-color: #007bff;")
        btn_sms.clicked.connect(self.action_sms_input)
        dial_layout.addWidget(btn_sms)
        
        layout.addLayout(dial_layout)
        
        # Verlaufstabelle Header Layout mit Löschen-Button
        hist_header_layout = QHBoxLayout()
        hist_header_layout.addWidget(QLabel("<b>Letzte Anrufe:</b> (Doppelklick zum Wählen, Rechtsklick für Optionen)"))
        
        btn_clear_hist = QPushButton("Verlauf löschen")
        btn_clear_hist.setStyleSheet("background-color: #ff3b30; padding: 4px 12px; font-weight: normal; max-width: 150px;")
        btn_clear_hist.clicked.connect(self.clear_history)
        hist_header_layout.addWidget(btn_clear_hist)

        btn_import_calls = QPushButton("Handy-Anrufe importieren")
        btn_import_calls.setStyleSheet("background-color: #17a2b8; padding: 4px 12px; font-weight: normal; max-width: 180px;")
        btn_import_calls.clicked.connect(self.action_import_call_log)
        hist_header_layout.addWidget(btn_import_calls)
        
        layout.addLayout(hist_header_layout)
        
        # Suchzeile für den Verlauf
        search_hist_layout = QHBoxLayout()
        self.txt_search_history = QLineEdit()
        self.txt_search_history.setPlaceholderText("Im Verlauf suchen (Name, Nummer, Notiz, Status, Zeitstempel)...")
        self.txt_search_history.setClearButtonEnabled(True)
        self.txt_search_history.textChanged.connect(self.search_history)
        search_hist_layout.addWidget(self.txt_search_history)
        layout.addLayout(search_hist_layout)
        
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Zeitstempel", "Nummer (Formatiert)", "Name", "Status", "Notiz"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.doubleClicked.connect(self.action_dial_history)
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.show_history_context_menu)
        self.history_table.verticalHeader().setDefaultSectionSize(38)
        self.history_table.setSortingEnabled(True)
        
        layout.addWidget(self.history_table)
        self.tab_dial.setLayout(layout)
        
        self.refresh_history()
        
    def refresh_history(self):
        rows = db_get_call_history()
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(0)
        for i, row in enumerate(rows):
            self.history_table.insertRow(i)
            # Zeitstempel
            self.history_table.setItem(i, 0, QTableWidgetItem(row[3]))
            # Nummer (Formatiert)
            formatted_num = format_phone_number(row[1])
            item_num = QTableWidgetItem(formatted_num)
            # Speichere die rohe Nummer als Custom-Data im Item, damit wir sie sauber extrahieren können
            item_num.setData(Qt.ItemDataRole.UserRole, row[1])
            self.history_table.setItem(i, 1, item_num)
            # Name
            self.history_table.setItem(i, 2, QTableWidgetItem(row[2] or "Unbekannt"))
            # Status
            status_text = "Verbunden" if row[4] == "connected" else ("Nicht erreicht" if row[4] == "no_answer" else "Wählend...")
            self.history_table.setItem(i, 3, QTableWidgetItem(status_text))
            # Notiz
            self.history_table.setItem(i, 4, QTableWidgetItem(row[5] or ""))
        self.history_table.setSortingEnabled(True)
        if hasattr(self, "txt_search_history"):
            self.search_history(self.txt_search_history.text())

    def search_history(self, text):
        search_text = text.strip().lower()
        self.history_table.setSortingEnabled(False)
        for i in range(self.history_table.rowCount()):
            row_match = False
            for col in range(self.history_table.columnCount()):
                item = self.history_table.item(i, col)
                if item:
                    item_text = item.text().lower()
                    if col == 1:
                        raw_num = item.data(Qt.ItemDataRole.UserRole)
                        if raw_num and search_text in raw_num.lower():
                            row_match = True
                            break
                    if search_text in item_text:
                        row_match = True
                        break
            
            if not search_text or row_match:
                self.history_table.setRowHidden(i, False)
            else:
                self.history_table.setRowHidden(i, True)
        self.history_table.setSortingEnabled(True)
            
    def clear_history(self):
        reply = QMessageBox.question(
            self, "Verlauf löschen",
            "Möchtest du wirklich den gesamten Anrufverlauf löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("DELETE FROM calls")
            conn.commit()
            conn.close()
            self.refresh_history()

    def action_import_call_log(self):
        reply = QMessageBox.question(
            self, "Anrufe importieren",
            "Möchtest du die Anrufliste von deinem S20 importieren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            success, count = adb_import_call_log()
            self.setEnabled(True)
            if success:
                QMessageBox.information(self, "Erfolg", f"{count} neue Anrufe erfolgreich importiert!")
                self.refresh_history()
            else:
                QMessageBox.critical(self, "Fehler", "Anrufe konnten nicht importiert werden. Prüfe die ADB-Verbindung.")

    def action_import_contacts(self):
        reply = QMessageBox.question(
            self, "Kontakte importieren",
            "Möchtest du alle Kontakte von deinem S20 importieren?\nBestehende Kontakte werden aktualisiert.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            success, count = adb_import_contacts()
            self.setEnabled(True)
            if success:
                QMessageBox.information(self, "Erfolg", f"{count} Kontakte erfolgreich importiert!")
                self.refresh_contacts()
                self.refresh_history()
            else:
                QMessageBox.critical(self, "Fehler", "Kontakte konnten nicht importiert werden. Prüfe die ADB-Verbindung.")
            
    def action_dial_input(self):
        number = self.txt_number.text().strip()
        cleaned_number = "".join(c for c in number if c.isdigit() or c == '+')
        if cleaned_number:
            self.start_call(cleaned_number)
            self.txt_number.clear()

    def action_sms_input(self):
        number = self.txt_number.text().strip()
        cleaned_number = "".join(c for c in number if c.isdigit() or c == '+')
        if cleaned_number:
            name = db_get_contact_name(cleaned_number) or "Unbekannt"
            self.send_sms_dialog(cleaned_number, name)
            self.txt_number.clear()
            
    def action_dial_history(self, index):
        row = index.row()
        item_num = self.history_table.item(row, 1)
        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
        self.start_call(cleaned_number)
        
    def start_call(self, number):
        dlg = ActiveCallDialog(number, self)
        dlg.exec()
        self.refresh_history()

    def send_sms_dialog(self, number, name="Unbekannt"):
        dlg = SendSMSDialog(number, name, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if hasattr(self, "refresh_sms"):
                self.refresh_sms()
        
    def show_history_context_menu(self, pos):
        item = self.history_table.itemAt(pos)
        if not item:
            return
        row = self.history_table.row(item)
        item_num = self.history_table.item(row, 1)
        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
        name = self.history_table.item(row, 2).text()
        
        menu = QMenu()
        
        act_call = QAction("Anrufen", self)
        act_call.triggered.connect(lambda: self.start_call(cleaned_number))
        menu.addAction(act_call)

        act_sms = QAction("SMS senden", self)
        act_sms.triggered.connect(lambda: self.send_sms_dialog(cleaned_number, name))
        menu.addAction(act_sms)
        
        telegram = db_get_contact_telegram_username(cleaned_number) or ""
        act_tg = QAction("Telegram-Chat öffnen", self)
        act_tg.triggered.connect(lambda: self.open_telegram_chat(cleaned_number, telegram))
        menu.addAction(act_tg)
        
        # Neues Feature: Obsidian-Notiz öffnen
        act_open_obsidian = QAction("Notiz in Obsidian öffnen", self)
        act_open_obsidian.triggered.connect(lambda: open_obsidian_note(cleaned_number))
        menu.addAction(act_open_obsidian)
        
        if name == "Unbekannt":
            act_add = QAction("Zu Kontakten hinzufügen", self)
            act_add.triggered.connect(lambda: self.add_history_to_contacts(cleaned_number))
            menu.addAction(act_add)
            
        menu.exec(self.history_table.viewport().mapToGlobal(pos))
        
    def add_history_to_contacts(self, number):
        dlg = AddContactDialog(number, "", self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_history()
            self.refresh_contacts()

    # ----------------- KONTAKTE-TAB -----------------
    
    def setup_contacts_tab(self):
        layout = QVBoxLayout()
        
        # Steuerzeile oben
        ctrl_layout = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Nach Kontakten suchen...")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.search_contacts)
        ctrl_layout.addWidget(self.txt_search)
        
        btn_add = QPushButton("Neuer Kontakt")
        btn_add.clicked.connect(self.add_contact)
        ctrl_layout.addWidget(btn_add)

        btn_import = QPushButton("Handy-Kontakte importieren")
        btn_import.setStyleSheet("background-color: #17a2b8; padding: 8px 16px;")
        btn_import.clicked.connect(self.action_import_contacts)
        ctrl_layout.addWidget(btn_import)
        
        layout.addLayout(ctrl_layout)
        
        # Kontakt-Tabelle
        self.contacts_table = QTableWidget(0, 3)
        self.contacts_table.setHorizontalHeaderLabels(["Name", "Nummer (Formatiert)", "Aktionen"])
        self.contacts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.contacts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.contacts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.contacts_table.doubleClicked.connect(self.action_dial_contact)
        self.contacts_table.verticalHeader().setDefaultSectionSize(38)
        self.contacts_table.setSortingEnabled(True)
        self.contacts_table.horizontalHeader().sortIndicatorChanged.connect(self.save_contacts_sort_state)
        
        # EventFilter für Tastatur-Navigation und Shortcuts installieren
        self.txt_search.installEventFilter(self)
        self.contacts_table.installEventFilter(self)
        
        layout.addWidget(self.contacts_table)
        self.tab_contacts.setLayout(layout)
        
        self.refresh_contacts()
        
    def refresh_contacts(self):
        rows = db_get_all_contacts()
        self.all_contacts = rows  # Cache für lokale Suche
        self.populate_contacts_table(rows)
        self.search_contacts(self.txt_search.text())
        
        # Sortierzustand wiederherstellen
        sort_column = int(db_get_setting("contacts_sort_column", 0))
        sort_order_val = int(db_get_setting("contacts_sort_order", 0))
        sort_order = Qt.SortOrder(sort_order_val)
        
        self.contacts_table.horizontalHeader().blockSignals(True)
        self.contacts_table.sortItems(sort_column, sort_order)
        self.contacts_table.horizontalHeader().setSortIndicator(sort_column, sort_order)
        self.contacts_table.horizontalHeader().blockSignals(False)

    def save_contacts_sort_state(self, logical_index, order):
        db_set_setting("contacts_sort_column", logical_index)
        db_set_setting("contacts_sort_order", int(order))
        
    def populate_contacts_table(self, rows):
        self.contacts_table.setSortingEnabled(False)
        self.contacts_table.setRowCount(0)
        for i, row in enumerate(rows):
            self.contacts_table.insertRow(i)
            # Name
            self.contacts_table.setItem(i, 0, QTableWidgetItem(row[0]))
            # Nummer (Formatiert)
            formatted_num = format_phone_number(row[1])
            item_num = QTableWidgetItem(formatted_num)
            item_num.setData(Qt.ItemDataRole.UserRole, row[1])
            self.contacts_table.setItem(i, 1, item_num)
            
            # Action Buttons Layout (CRUD & Call)
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(6)
            
            btn_call = QPushButton("Anrufen")
            btn_call.setStyleSheet("background-color: #28a745; padding: 4px 12px; font-weight: normal;")
            btn_call.clicked.connect(lambda checked, num=row[1]: self.start_call(num))
            btn_layout.addWidget(btn_call)
 
            btn_sms = QPushButton("SMS")
            btn_sms.setStyleSheet("background-color: #007bff; padding: 4px 12px; font-weight: normal;")
            btn_sms.clicked.connect(lambda checked, num=row[1], name=row[0]: self.send_sms_dialog(num, name))
            btn_layout.addWidget(btn_sms)

            btn_tg = QPushButton("Telegram")
            btn_tg.setStyleSheet("background-color: #0088cc; padding: 4px 12px; font-weight: normal;")
            btn_tg.clicked.connect(lambda checked, num=row[1], tg=row[2]: self.open_telegram_chat(num, tg))
            btn_layout.addWidget(btn_tg)
            
            # Neues Feature: Bearbeiten (U in CRUD)
            btn_edit = QPushButton("Bearbeiten")
            btn_edit.setStyleSheet("background-color: #444444; padding: 4px 12px; font-weight: normal;")
            btn_edit.clicked.connect(lambda checked, num=row[1], name=row[0], tg=row[2]: self.edit_contact(num, name, tg))
            btn_layout.addWidget(btn_edit)
            
            btn_delete = QPushButton("Löschen")
            btn_delete.setStyleSheet("background-color: #ff3b30; padding: 4px 12px; font-weight: normal;")
            btn_delete.clicked.connect(lambda checked, num=row[1], name=row[0]: self.delete_contact(num, name))
            btn_layout.addWidget(btn_delete)
            
            self.contacts_table.setCellWidget(i, 2, btn_widget)
        self.contacts_table.setSortingEnabled(True)
            
    def action_dial_contact(self, index):
        row = index.row()
        item_num = self.contacts_table.item(row, 1)
        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
        self.start_call(cleaned_number)
        
    def add_contact(self):
        dlg = AddContactDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_contacts()
            self.refresh_history()
            
    def edit_contact(self, number, name, telegram=""):
        dlg = AddContactDialog(prefilled_number=number, prefilled_name=name, parent=self, prefilled_telegram=telegram)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_contacts()
            self.refresh_history()

    def open_telegram_chat(self, number, telegram_username=""):
        import webbrowser
        if telegram_username:
            url = f"https://t.me/{telegram_username}"
        else:
            cleaned = "".join(c for c in number if c.isdigit() or c == '+')
            if cleaned.startswith("00"):
                cleaned = "+" + cleaned[2:]
            elif cleaned.startswith("0"):
                cleaned = "+49" + cleaned[1:]
            url = f"https://t.me/{cleaned}"
        
        webbrowser.open(url)
            
    def delete_contact(self, number, name):
        reply = QMessageBox.question(
            self, "Kontakt löschen",
            f"Bist du sicher, dass du {name} ({format_phone_number(number)}) löschen möchtest?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            db_delete_contact(number)
            threading.Thread(target=adb_delete_contact_from_phone, args=(number,), daemon=True).start()
            self.refresh_contacts()
            self.refresh_history()
            
    def search_contacts(self, text):
        search_text = text.strip().lower()
        self.contacts_table.setSortingEnabled(False)
        for i in range(self.contacts_table.rowCount()):
            name_item = self.contacts_table.item(i, 0)
            num_item = self.contacts_table.item(i, 1)
            name = name_item.text().lower() if name_item else ""
            
            raw_number = ""
            if num_item:
                raw_number = num_item.data(Qt.ItemDataRole.UserRole) or num_item.text()
                raw_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
                
            display_num = num_item.text() if num_item else ""
            
            if not search_text or search_text in name or search_text in raw_number or search_text in display_num:
                self.contacts_table.setRowHidden(i, False)
            else:
                self.contacts_table.setRowHidden(i, True)
        self.contacts_table.setSortingEnabled(True)

    def handle_incoming_call(self, number):
        self.incoming_call_dlg = IncomingCallDialog(number, self)
        res = self.incoming_call_dlg.exec()
        self.incoming_call_dlg = None
        
        if res == 1:
            active_dlg = ActiveCallDialog(number, parent=self, is_incoming=True)
            active_dlg.exec()
            self.refresh_history()

    def handle_call_ended(self):
        if hasattr(self, "incoming_call_dlg") and self.incoming_call_dlg:
            self.incoming_call_dlg.reject()

    def handle_sync_step(self, step_type, count):
        if step_type == "contacts":
            self.refresh_contacts()
            self.refresh_history()
        elif step_type == "calls":
            self.refresh_history()
        elif step_type == "sms":
            self.refresh_sms()
        print(f"Hintergrund-Sync: {step_type} synchronisiert ({count} neue Einträge).")

    def handle_sync_finished(self):
        print("Hintergrund-Sync: Vollständige Synchronisierung abgeschlossen.")

    def closeEvent(self, event):
        self.monitor_thread.stop()
        self.monitor_thread.wait()
        if hasattr(self, "sync_thread") and self.sync_thread.isRunning():
            self.sync_thread.terminate()
            self.sync_thread.wait()
        super().closeEvent(event)

    def setup_sms_tab(self):
        layout = QVBoxLayout()
        
        ctrl_layout = QHBoxLayout()
        self.txt_search_sms = QLineEdit()
        self.txt_search_sms.setPlaceholderText("Nach SMS suchen...")
        self.txt_search_sms.setClearButtonEnabled(True)
        self.txt_search_sms.textChanged.connect(self.search_sms)
        ctrl_layout.addWidget(self.txt_search_sms)
        
        btn_import_sms = QPushButton("Handy-SMS importieren")
        btn_import_sms.setStyleSheet("background-color: #17a2b8; padding: 8px 16px;")
        btn_import_sms.clicked.connect(self.action_import_sms)
        ctrl_layout.addWidget(btn_import_sms)
        
        layout.addLayout(ctrl_layout)
        
        self.sms_table = QTableWidget(0, 5)
        self.sms_table.setHorizontalHeaderLabels(["Zeitstempel", "Nummer (Formatiert)", "Name", "Richtung", "Inhalt"])
        self.sms_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.sms_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sms_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sms_table.doubleClicked.connect(self.action_reply_sms)
        self.sms_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sms_table.customContextMenuRequested.connect(self.show_sms_context_menu)
        self.sms_table.verticalHeader().setDefaultSectionSize(45)
        self.sms_table.setSortingEnabled(True)
        
        layout.addWidget(self.sms_table)
        self.sms_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        
        self.tab_sms.setLayout(layout)
        self.refresh_sms()

    def refresh_sms(self):
        rows = db_get_sms_history()
        self.sms_table.setSortingEnabled(False)
        self.sms_table.setRowCount(0)
        for i, row in enumerate(rows):
            self.sms_table.insertRow(i)
            self.sms_table.setItem(i, 0, QTableWidgetItem(row[3]))
            
            formatted_num = format_phone_number(row[1])
            item_num = QTableWidgetItem(formatted_num)
            item_num.setData(Qt.ItemDataRole.UserRole, row[1])
            self.sms_table.setItem(i, 1, item_num)
            
            self.sms_table.setItem(i, 2, QTableWidgetItem(row[2] or "Unbekannt"))
            
            direction = "Gesendet" if row[5] == 2 else "Empfangen"
            self.sms_table.setItem(i, 3, QTableWidgetItem(direction))
            
            self.sms_table.setItem(i, 4, QTableWidgetItem(row[4]))
        self.sms_table.setSortingEnabled(True)
        self.search_sms(self.txt_search_sms.text())

    def action_import_sms(self):
        reply = QMessageBox.question(
            self, "SMS importieren",
            "Möchtest du alle SMS von deinem S20 importieren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)
            success, count = adb_import_sms()
            self.setEnabled(True)
            if success:
                QMessageBox.information(self, "Erfolg", f"{count} neue SMS erfolgreich importiert!")
                self.refresh_sms()
            else:
                QMessageBox.critical(self, "Fehler", "SMS konnten nicht importiert werden. Prüfe die ADB-Verbindung.")

    def action_reply_sms(self, index):
        row = index.row()
        item_num = self.sms_table.item(row, 1)
        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
        name = self.sms_table.item(row, 2).text()
        self.send_sms_dialog(cleaned_number, name)

    def search_sms(self, text):
        search_text = text.strip().lower()
        self.sms_table.setSortingEnabled(False)
        for i in range(self.sms_table.rowCount()):
            name_item = self.sms_table.item(i, 2)
            num_item = self.sms_table.item(i, 1)
            body_item = self.sms_table.item(i, 4)
            name = name_item.text().lower() if name_item else ""
            body = body_item.text().lower() if body_item else ""
            
            raw_number = ""
            if num_item:
                raw_number = num_item.data(Qt.ItemDataRole.UserRole) or num_item.text()
                raw_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
                
            display_num = num_item.text() if num_item else ""
            
            if not search_text or search_text in name or search_text in body or search_text in raw_number or search_text in display_num:
                self.sms_table.setRowHidden(i, False)
            else:
                self.sms_table.setRowHidden(i, True)
        self.sms_table.setSortingEnabled(True)

    def show_sms_context_menu(self, pos):
        item = self.sms_table.itemAt(pos)
        if not item:
            return
        row = self.sms_table.row(item)
        item_num = self.sms_table.item(row, 1)
        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
        name = self.sms_table.item(row, 2).text()
        
        menu = QMenu()
        
        act_reply = QAction("Antworten (SMS senden)", self)
        act_reply.triggered.connect(lambda: self.send_sms_dialog(cleaned_number, name))
        menu.addAction(act_reply)
        
        act_call = QAction("Anrufen", self)
        act_call.triggered.connect(lambda: self.start_call(cleaned_number))
        menu.addAction(act_call)
        
        telegram = db_get_contact_telegram_username(cleaned_number) or ""
        act_tg = QAction("Telegram-Chat öffnen", self)
        act_tg.triggered.connect(lambda: self.open_telegram_chat(cleaned_number, telegram))
        menu.addAction(act_tg)
        
        act_open_obsidian = QAction("Notiz in Obsidian öffnen", self)
        act_open_obsidian.triggered.connect(lambda: open_obsidian_note(cleaned_number))
        menu.addAction(act_open_obsidian)
        
        if name == "Unbekannt":
            act_add = QAction("Zu Kontakten hinzufügen", self)
            act_add.triggered.connect(lambda: self.add_sms_to_contacts(cleaned_number))
            menu.addAction(act_add)
            
        menu.exec(self.sms_table.viewport().mapToGlobal(pos))

    def add_sms_to_contacts(self, number):
        dlg = AddContactDialog(number, "", self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh_sms()
            self.refresh_contacts()
            self.refresh_history()

    def eventFilter(self, source, event):
        # 1. Von der Suche mit Pfeiltaste Runter in die Tabelle springen
        if source == self.txt_search and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                if self.contacts_table.rowCount() > 0:
                    self.contacts_table.setFocus()
                    self.contacts_table.selectRow(0)
                    return True
                    
        # 2. Key-Handling für die Kontakte-Tabelle
        elif source == self.contacts_table and event.type() == event.Type.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            
            selected_ranges = self.contacts_table.selectedRanges()
            if selected_ranges:
                current_row = self.contacts_table.currentRow()
                if current_row >= 0:
                    # Daten des ausgewählten Kontakts holen
                    item_name = self.contacts_table.item(current_row, 0)
                    item_num = self.contacts_table.item(current_row, 1)
                    if item_name and item_num:
                        name = item_name.text()
                        raw_number = item_num.data(Qt.ItemDataRole.UserRole) or item_num.text()
                        cleaned_number = "".join(c for c in raw_number if c.isdigit() or c == '+')
                        
                        # ENTF -> Löschen
                        if key == Qt.Key.Key_Delete:
                            self.delete_contact(cleaned_number, name)
                            return True
                            
                        # Strg + W -> Anrufen (Wählen)
                        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_W:
                            self.start_call(cleaned_number)
                            return True
                            
                        # Strg + S -> SMS
                        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_S:
                            self.send_sms_dialog(cleaned_number, name)
                            return True
                            
                        # Strg + T -> Telegram
                        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_T:
                            telegram = db_get_contact_telegram_username(cleaned_number) or ""
                            self.open_telegram_chat(cleaned_number, telegram)
                            return True
                            
                        # Strg + B -> Bearbeiten
                        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_B:
                            telegram = db_get_contact_telegram_username(cleaned_number) or ""
                            self.edit_contact(cleaned_number, name, telegram)
                            return True
                            
            # Strg + N -> Neuer Kontakt (immer verfügbar, wenn Fokus in der Tabelle)
            if modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_N:
                self.add_contact()
                return True
                
        return super().eventFilter(source, event)

# ----------------- MAIN RUNNER -----------------

if __name__ == "__main__":
    init_db()
    
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)
    
    # Prüfen, ob CLI Argumente vorliegen (z. B. dial <nummer> oder tel:<nummer>)
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        target_number = None
        if arg == "dial" and len(sys.argv) > 2:
            target_number = sys.argv[2]
        elif arg.startswith("tel:"):
            target_number = arg[4:]
            
        if target_number:
            cleaned_target = "".join(c for c in target_number if c.isdigit() or c == '+')
            if cleaned_target:
                dlg = ActiveCallDialog(cleaned_target)
                dlg.exec()
                sys.exit(0)
            
    # Andernfalls: Hauptanwendung starten
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
