"""One-off: apply WhatsApp consent columns to the local SQLite dev database."""
import sqlite3
from pathlib import Path

db_path = Path(__file__).resolve().parent.parent / "shopivell.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='whatsapp_leads'")
if not cur.fetchone():
    print("whatsapp_leads table does not exist yet (init_db will create it with the new columns)")
else:
    existing = {row[1] for row in cur.execute("PRAGMA table_info(whatsapp_leads)")}
    cols = [
        ("marketing_opt_in", "BOOLEAN NOT NULL DEFAULT 0"),
        ("opt_in_source", "VARCHAR(100)"),
        ("opt_in_at", "TIMESTAMP"),
        ("opted_out_at", "TIMESTAMP"),
    ]
    for name, ddl in cols:
        if name in existing:
            print(f"[SKIP] {name} already exists")
        else:
            cur.execute(f"ALTER TABLE whatsapp_leads ADD COLUMN {name} {ddl}")
            print(f"[OK] added {name}")
    conn.commit()
    final = [row[1] for row in cur.execute("PRAGMA table_info(whatsapp_leads)")]
    print("Final columns:", ", ".join(final))

conn.close()
