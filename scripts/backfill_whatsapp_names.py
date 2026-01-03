#!/usr/bin/env python3
"""
Backfill WhatsApp conversation customer names from existing customer records.

This script:
1. Finds WhatsApp conversations without customer_name
2. Matches phone numbers with the customers table
3. Updates customer_name from first_name + last_name

Usage:
    python scripts/backfill_whatsapp_names.py

    # Dry run (preview changes without applying):
    python scripts/backfill_whatsapp_names.py --dry-run
"""

import sys
import os
import re
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal
from modules.whatsapp.models import WhatsAppConversation
from modules.customers.models import Customer


def normalize_phone(phone: str) -> str:
    """Remove all non-digit characters from phone number"""
    if not phone:
        return ""
    return re.sub(r'\D', '', phone)


def backfill_names(dry_run: bool = False):
    """
    Backfill customer names for WhatsApp conversations.

    Matches conversations without names to customers by phone number.
    """
    db = SessionLocal()

    try:
        # Get all conversations without customer_name
        conversations_without_name = db.query(WhatsAppConversation).filter(
            (WhatsAppConversation.customer_name == None) |
            (WhatsAppConversation.customer_name == "")
        ).all()

        print(f"Found {len(conversations_without_name)} conversations without customer name")

        if not conversations_without_name:
            print("Nothing to backfill!")
            return

        # Get all customers with phone numbers
        customers_with_phone = db.query(Customer).filter(
            Customer.phone != None,
            Customer.phone != ""
        ).all()

        print(f"Found {len(customers_with_phone)} customers with phone numbers")

        # Build phone -> customer name mapping
        phone_to_name = {}
        for customer in customers_with_phone:
            normalized = normalize_phone(customer.phone)
            if normalized:
                full_name = f"{customer.first_name} {customer.last_name}".strip()
                phone_to_name[normalized] = full_name
                # Also store without country code (last 10 digits)
                if len(normalized) > 10:
                    phone_to_name[normalized[-10:]] = full_name

        print(f"Built phone mapping with {len(phone_to_name)} entries")

        # Match and update conversations
        updated_count = 0
        matched_conversations = []

        for conv in conversations_without_name:
            conv_phone = normalize_phone(conv.phone_number)

            # Try exact match
            customer_name = phone_to_name.get(conv_phone)

            # Try without country code
            if not customer_name and len(conv_phone) > 10:
                customer_name = phone_to_name.get(conv_phone[-10:])

            # Try last 9 digits (some countries)
            if not customer_name and len(conv_phone) > 9:
                customer_name = phone_to_name.get(conv_phone[-9:])

            if customer_name:
                matched_conversations.append({
                    "phone": conv.phone_number,
                    "name": customer_name,
                    "conv_id": str(conv.id)
                })

                if not dry_run:
                    conv.customer_name = customer_name
                    updated_count += 1

        if matched_conversations:
            print(f"\n{'[DRY RUN] Would update' if dry_run else 'Updated'} {len(matched_conversations)} conversations:")
            print("-" * 60)
            for match in matched_conversations[:20]:  # Show first 20
                print(f"  {match['phone']} -> {match['name']}")
            if len(matched_conversations) > 20:
                print(f"  ... and {len(matched_conversations) - 20} more")

        if not dry_run and updated_count > 0:
            db.commit()
            print(f"\n✓ Successfully updated {updated_count} conversations")
        elif dry_run:
            print(f"\n[DRY RUN] Would update {len(matched_conversations)} conversations")
            print("Run without --dry-run to apply changes")
        else:
            print("\nNo matches found between conversations and customers")

        # Show remaining conversations without names
        remaining = len(conversations_without_name) - len(matched_conversations)
        if remaining > 0:
            print(f"\n{remaining} conversations still without names (no matching customer record)")
            print("These will be updated automatically when the customer sends a new message")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Backfill WhatsApp conversation customer names from customer records"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without applying them"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("WhatsApp Customer Name Backfill Script")
    print("=" * 60)

    if args.dry_run:
        print("[DRY RUN MODE - No changes will be made]\n")

    backfill_names(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
