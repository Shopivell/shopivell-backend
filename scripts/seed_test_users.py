#!/usr/bin/env python3
"""
Seed Test Users Script

Creates test users for development and testing purposes.

Reads credentials from environment variables:
    SEED_USER_EMAIL     (default: testuser@shopivell.com)
    SEED_USER_PASSWORD  (required)
    SEED_ADMIN_EMAIL    (default: admin@shopivell.com)
    SEED_ADMIN_PASSWORD (required)

Usage:
    SEED_USER_PASSWORD=xxx SEED_ADMIN_PASSWORD=yyy python scripts/seed_test_users.py
"""

import sys
import os

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal, engine, Base, init_db
from modules.users.models import User, UserRole
from modules.admin.models import AdminUser, AdminRole


def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')


def create_test_user(db: Session, email: str, password: str, name: str, role: UserRole) -> User:
    """Creates a test user with proper password hash."""
    existing_user = db.query(User).filter(User.email == email).first()

    if existing_user:
        print(f"User '{email}' already exists. Updating password...")
        existing_user.password_hash = hash_password(password)
        db.commit()
        return existing_user

    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        role=role,
        is_verified=True,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_admin_profile(db: Session, user: User, admin_role: AdminRole) -> AdminUser:
    """Creates an admin profile for a user."""
    existing_admin = db.query(AdminUser).filter(AdminUser.user_id == user.id).first()

    if existing_admin:
        print(f"Admin profile already exists for user '{user.email}'")
        return existing_admin

    admin_user = AdminUser(
        user_id=user.id,
        role=admin_role,
        permissions={
            "all": True,
            "manage_admins": True,
            "manage_agencies": True,
            "manage_stores": True,
            "manage_payments": True,
            "view_analytics": True
        },
        is_active=True,
        created_at=datetime.utcnow()
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    return admin_user


def main():
    """Seed test users into the database."""
    seed_user_email = os.environ.get("SEED_USER_EMAIL", "testuser@shopivell.com")
    seed_user_password = os.environ.get("SEED_USER_PASSWORD")
    seed_admin_email = os.environ.get("SEED_ADMIN_EMAIL", "admin@shopivell.com")
    seed_admin_password = os.environ.get("SEED_ADMIN_PASSWORD")

    if not seed_user_password or not seed_admin_password:
        print("ERROR: SEED_USER_PASSWORD and SEED_ADMIN_PASSWORD environment variables are required")
        sys.exit(1)

    db: Session = SessionLocal()

    try:
        print("\n" + "="*50)
        print("SEEDING TEST USERS")
        print("="*50 + "\n")

        # Create regular test user
        print("Creating regular test user...")
        test_user = create_test_user(
            db=db,
            email=seed_user_email,
            password=seed_user_password,
            name="Test User",
            role=UserRole.OWNER
        )
        print(f"  Email: {seed_user_email}")
        print(f"  User ID: {test_user.id}")
        print()

        # Create admin user
        print("Creating admin user...")
        admin_user = create_test_user(
            db=db,
            email=seed_admin_email,
            password=seed_admin_password,
            name="Admin User",
            role=UserRole.ADMIN
        )

        # Create admin profile
        admin_profile = create_admin_profile(
            db=db,
            user=admin_user,
            admin_role=AdminRole.SUPERADMIN
        )

        print(f"  Email: {seed_admin_email}")
        print(f"  User ID: {admin_user.id}")
        print(f"  Admin ID: {admin_profile.id}")
        print(f"  Admin Role: superadmin")
        print()

        print("="*50)
        print("TEST USERS CREATED SUCCESSFULLY!")
        print("="*50)
        print("\nSeeded accounts:")
        print("-"*50)
        print(f"Regular User: {seed_user_email}")
        print(f"Admin User:   {seed_admin_email}")
        print("="*50 + "\n")

    except Exception as e:
        db.rollback()
        print(f"\nError seeding test users: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    # Ensure all models are loaded and tables exist
    init_db()
    main()
