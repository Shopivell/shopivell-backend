# modules/referral/constants.py
"""
Referral system configuration constants.
"""

# Token rewards
TOKENS_PER_REFERRAL = 10      # Tokens awarded when referred user signs up
TOKEN_VALUE_USD = 1.00        # Each token = $1 discount
MAX_TOKENS_PER_PAYMENT = 50   # Max $50 discount per payment

# Referral code settings
REFERRAL_CODE_LENGTH = 8      # Length of generated referral codes
REFERRAL_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excluding similar chars (0/O, 1/I)

# Frontend URL for referral links
FRONTEND_BASE_URL = "https://shopivell.com"  # Update with actual domain
REFERRAL_SIGNUP_PATH = "/signup"
