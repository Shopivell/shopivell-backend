#!/usr/bin/env python3
"""
Create Superadmin Script

Creates the first superadmin user for the Shopivell admin dashboard.

Usage:
    python scripts/create_superadmin.py --email admin@company.com --password SecurePass123

    Or interactive mode:
    python scripts/create_superadmin.py
"""

import argparse
import sys
import os
import getpass

# Add parent directory to path to import from the project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from datetime import datetime
from sqlalchemy.orm import Session

from database import SessionLocal, engine, Base
from modules.users.models import User, UserRole
from modules.admin.models import AdminUser, AdminRole


def hash_password(password: str) -> str:
    """Hashes a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')


def create_superadmin(email: str, password: str, first_name: str = "Super", last_name: str = "Admin") -> None:
    """
    Creates a superadmin user.

    Args:
        email: Admin email address
        password: Admin password (min 8 characters)
        first_name: Admin first name
        last_name: Admin last name
    """
    db: Session = SessionLocal()

    try:
        # Check if user with this email already exists
        existing_user = db.query(User).filter(User.email == email).first()

        if existing_user:
            # Check if already an admin
            existing_admin = db.query(AdminUser).filter(AdminUser.user_id == existing_user.id).first()
            if existing_admin:
                print(f"Error: User '{email}' is already an admin with role '{existing_admin.role.value}'")
                return

            # Upgrade existing user to admin
            print(f"User '{email}' exists. Upgrading to superadmin...")
            user = existing_user
        else:
            # Create new user
            print(f"Creating new user '{email}'...")
            user = User(
                email=email,
                name=f"{first_name} {last_name}",
                role=UserRole.ADMIN,
                is_verified=True,
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(user)
            db.flush()  # Get the user ID

        # Create AdminUser record
        admin_user = AdminUser(
            user_id=user.id,
            role=AdminRole.SUPERADMIN,
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

        print("\n" + "="*50)
        print("SUPERADMIN CREATED SUCCESSFULLY!")
        print("="*50)
        print(f"\nEmail:      {email}")
        print(f"Name:       {first_name} {last_name}")
        print(f"Role:       superadmin")
        print(f"User ID:    {user.id}")
        print(f"Admin ID:   {admin_user.id}")
        print("\nYou can now login at the admin dashboard.")
        print("="*50 + "\n")

    except Exception as e:
        db.rollback()
        print(f"\nError creating superadmin: {e}")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Create a superadmin user for the Shopivell admin dashboard"
    )
    parser.add_argument(
        "--email", "-e",
        type=str,
        help="Admin email address"
    )
    parser.add_argument(
        "--password", "-p",
        type=str,
        help="Admin password (min 8 characters)"
    )
    parser.add_argument(
        "--first-name", "-f",
        type=str,
        default="Super",
        help="Admin first name (default: Super)"
    )
    parser.add_argument(
        "--last-name", "-l",
        type=str,
        default="Admin",
        help="Admin last name (default: Admin)"
    )

    args = parser.parse_args()

    # Interactive mode if email/password not provided
    email = args.email
    password = args.password

    if not email:
        email = input("Enter admin email: ").strip()
        if not email:
            print("Error: Email is required")
            sys.exit(1)

    if not password:
        password = getpass.getpass("Enter admin password (min 8 chars): ")
        if len(password) < 8:
            print("Error: Password must be at least 8 characters")
            sys.exit(1)

        confirm_password = getpass.getpass("Confirm password: ")
        if password != confirm_password:
            print("Error: Passwords do not match")
            sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        sys.exit(1)

    # Validate email format (basic check)
    if "@" not in email or "." not in email:
        print("Error: Invalid email format")
        sys.exit(1)

    print(f"\nCreating superadmin for: {email}")
    print("-" * 40)

    create_superadmin(
        email=email,
        password=password,
        first_name=args.first_name,
        last_name=args.last_name
    )


if __name__ == "__main__":
    # Ensure tables exist
    from modules.admin.models import AdminUser, AdminInvitation, AuditLog
    Base.metadata.create_all(bind=engine)

    main()
