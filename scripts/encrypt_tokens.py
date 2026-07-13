"""One-time backfill: encrypt existing plaintext tokens in place.

Idempotent — only rows whose value is not already encrypted (no `enc::` prefix)
are touched. Uses raw SQL so it reads/writes the stored value directly, bypassing
the EncryptedString type. Run inside the backend container:

    python scripts/encrypt_tokens.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from database import SessionLocal
from utils.crypto import encrypt_value, _PREFIX, _get_fernet

TARGETS = [
    ("meta_ad_accounts", "access_token"),
    ("facebook_business_accounts", "access_token"),
    ("facebook_pages", "page_access_token"),
    ("instagram_accounts", "page_access_token"),
    ("whatsapp_accounts", "permanent_access_token"),
    ("whatsapp_accounts", "capi_access_token"),
]


def main():
    if _get_fernet() is None:
        print("[encrypt_tokens] Encryption is OFF (no real SECRET_KEY). Aborting — nothing changed.")
        return
    db = SessionLocal()
    try:
        for table, col in TARGETS:
            try:
                rows = db.execute(
                    text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL")
                ).fetchall()
            except Exception as e:
                print(f"[encrypt_tokens] skip {table}.{col}: {e}")
                continue
            n = 0
            for rid, val in rows:
                if isinstance(val, str) and not val.startswith(_PREFIX):
                    db.execute(
                        text(f"UPDATE {table} SET {col} = :v WHERE id = :id"),
                        {"v": encrypt_value(val), "id": rid},
                    )
                    n += 1
            db.commit()
            print(f"[encrypt_tokens] {table}.{col}: encrypted {n} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
