#!/usr/bin/env python
"""Add missing hashtags column to url_ad_sets table."""
from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    db.execute(text("ALTER TABLE url_ad_sets ADD COLUMN IF NOT EXISTS hashtags JSONB DEFAULT '[]'::jsonb"))
    db.commit()
    print("Column 'hashtags' added successfully!")
except Exception as e:
    print(f"Error: {e}")
    db.rollback()
finally:
    db.close()
