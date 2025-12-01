import requests
from urllib.parse import urlencode

# YOUR VALUES
APP_ID = "882284284358539"
APP_SECRET = "fcee7fff9d7feddffb453f6722213657"  # Paste it!
REDIRECT_URI = "http://localhost:8000/v1/api/social/facebook/callback"
API_VERSION = "v24.0"
USER_ID = "803299836037442"

# Get FRESH CODE from browser first (after removing app from Facebook settings)
CODE = "PASTE_FRESH_CODE_HERE"

print("🔄 Step 1: Exchange CODE → User Access Token")
token_url = f"https://graph.facebook.com/{API_VERSION}/oauth/access_token"
token_params = {
    "client_id": APP_ID,
    "client_secret": APP_SECRET,
    "redirect_uri": REDIRECT_URI,
    "code": CODE
}

token_resp = requests.get(token_url, params=token_params)
token_data = token_resp.json()
print("📦 Token exchange:", token_data)

if "access_token" not in token_data:
    print("❌ FAILED to exchange code!")
    exit()

user_token = token_data["access_token"]
print(f"✅ REAL User Token: {user_token[:30]}...")

print("\n🔄 Step 2: Test /me/accounts with REAL token")
pages_url = f"https://graph.facebook.com/{API_VERSION}/{USER_ID}/accounts"
pages_params = {
    "access_token": user_token,
    "fields": "id,name,access_token,category,tasks"
}

pages_resp = requests.get(pages_url, params=pages_params)
pages_data = pages_resp.json()

print("\n📦 FINAL /accounts response:")
print(pages_data)
