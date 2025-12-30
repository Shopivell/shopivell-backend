#!/usr/bin/env python
"""
Cleanup script to delete test campaigns from Facebook and local database.
"""

import os
import sys
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text
from database import SessionLocal

FB_GRAPH_API_BASE = "https://graph.facebook.com/v24.0"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'


def print_success(message):
    print(f"{Colors.GREEN}[OK] {message}{Colors.END}")


def print_error(message):
    print(f"{Colors.RED}[ERROR] {message}{Colors.END}")


def print_info(message):
    print(f"{Colors.YELLOW}[INFO] {message}{Colors.END}")


def get_test_campaigns():
    """Get test campaigns from database."""
    db = SessionLocal()
    try:
        # Get campaigns that start with "Test Campaign"
        results = db.execute(text("""
            SELECT mc.id, mc.campaign_id, mc.name, mc.ad_account_id, ma.access_token
            FROM meta_campaigns mc
            JOIN meta_ad_accounts ma ON mc.ad_account_id = ma.id
            WHERE mc.name LIKE 'Test Campaign%'
            ORDER BY mc.created_at DESC
        """)).fetchall()

        campaigns = []
        for row in results:
            campaigns.append({
                'db_id': str(row[0]),
                'meta_id': row[1],
                'name': row[2],
                'ad_account_id': str(row[3]),
                'access_token': row[4]
            })
        return campaigns
    finally:
        db.close()


def get_test_adsets():
    """Get test ad sets from database."""
    db = SessionLocal()
    try:
        results = db.execute(text("""
            SELECT mas.id, mas.adset_id, mas.name, mas.ad_account_id, ma.access_token
            FROM meta_ad_sets mas
            JOIN meta_ad_accounts ma ON mas.ad_account_id = ma.id
            WHERE mas.name LIKE 'Test Ad Set%'
            ORDER BY mas.created_at DESC
        """)).fetchall()

        adsets = []
        for row in results:
            adsets.append({
                'db_id': str(row[0]),
                'meta_id': row[1],
                'name': row[2],
                'ad_account_id': str(row[3]),
                'access_token': row[4]
            })
        return adsets
    finally:
        db.close()


def get_test_ads():
    """Get test ads from database."""
    db = SessionLocal()
    try:
        results = db.execute(text("""
            SELECT mad.id, mad.ad_id, mad.name, mad.ad_account_id, ma.access_token
            FROM meta_ads mad
            JOIN meta_ad_accounts ma ON mad.ad_account_id = ma.id
            WHERE mad.name LIKE 'Test Ad%'
            ORDER BY mad.created_at DESC
        """)).fetchall()

        ads = []
        for row in results:
            ads.append({
                'db_id': str(row[0]),
                'meta_id': row[1],
                'name': row[2],
                'ad_account_id': str(row[3]),
                'access_token': row[4]
            })
        return ads
    finally:
        db.close()


def delete_from_facebook(object_id: str, access_token: str, object_type: str):
    """Delete an object from Facebook."""
    if object_id.startswith('DRAFT_'):
        print_info(f"  Skipping {object_type} {object_id} (local draft only)")
        return True

    url = f"{FB_GRAPH_API_BASE}/{object_id}"
    params = {"access_token": access_token}

    try:
        response = requests.delete(url, params=params, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print_success(f"  Deleted {object_type} {object_id} from Facebook")
                return True
            else:
                print_error(f"  Failed to delete {object_type} {object_id}: {result}")
                return False
        else:
            error = response.json().get('error', {})
            error_msg = error.get('message', response.text)
            # If already deleted or doesn't exist, consider it success
            if 'does not exist' in error_msg.lower() or error.get('code') == 100:
                print_info(f"  {object_type} {object_id} already deleted or doesn't exist")
                return True
            print_error(f"  Failed to delete {object_type} {object_id}: {error_msg}")
            return False
    except Exception as e:
        print_error(f"  Error deleting {object_type} {object_id}: {str(e)}")
        return False


def delete_from_database(table: str, db_id: str):
    """Delete a record from local database."""
    db = SessionLocal()
    try:
        db.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": db_id})
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        print_error(f"  Failed to delete from DB: {str(e)}")
        return False
    finally:
        db.close()


def main():
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("=" * 60)
    print("  CLEANUP TEST CAMPAIGNS")
    print("=" * 60)
    print(f"{Colors.END}\n")

    # Get all test items
    campaigns = get_test_campaigns()
    adsets = get_test_adsets()
    ads = get_test_ads()

    print_info(f"Found {len(campaigns)} test campaign(s)")
    print_info(f"Found {len(adsets)} test ad set(s)")
    print_info(f"Found {len(ads)} test ad(s)")

    if not campaigns and not adsets and not ads:
        print_info("Nothing to clean up!")
        return

    # Delete ads first (they depend on ad sets)
    if ads:
        print(f"\n{Colors.BOLD}Deleting Ads...{Colors.END}")
        for ad in ads:
            print_info(f"Processing: {ad['name']}")
            delete_from_facebook(ad['meta_id'], ad['access_token'], "Ad")
            delete_from_database("meta_ads", ad['db_id'])

    # Delete ad sets (they depend on campaigns)
    if adsets:
        print(f"\n{Colors.BOLD}Deleting Ad Sets...{Colors.END}")
        for adset in adsets:
            print_info(f"Processing: {adset['name']}")
            delete_from_facebook(adset['meta_id'], adset['access_token'], "Ad Set")
            delete_from_database("meta_ad_sets", adset['db_id'])

    # Delete campaigns
    if campaigns:
        print(f"\n{Colors.BOLD}Deleting Campaigns...{Colors.END}")
        for campaign in campaigns:
            print_info(f"Processing: {campaign['name']}")
            delete_from_facebook(campaign['meta_id'], campaign['access_token'], "Campaign")
            delete_from_database("meta_campaigns", campaign['db_id'])

    print(f"\n{Colors.BOLD}{Colors.GREEN}")
    print("=" * 60)
    print("  CLEANUP COMPLETE")
    print("=" * 60)
    print(f"{Colors.END}\n")


if __name__ == "__main__":
    main()
