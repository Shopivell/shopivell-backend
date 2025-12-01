import requests

APP_ID = "1341556783617722"  # or the app ID you actually used for this login
APP_SECRET = "44affbfefdf9b2575efd3b970f950db0"  # same app's secret
REDIRECT_URI = "http://localhost:8000/v1/api/social/facebook/callback"
CODE = "AQBSsbGDXzNoe55H2nIu7ipY2GRm49wYAim9dFOTJ84SDWMr3xWB9WLsTFlzHJ2og_FLAQcZu9QTVDQNajQDIX4EM1dAOxMno9-q1H74sBNweGoMv0YZVtz3IU5hO6AaVp1NebAV7tYdLZtSPa0Y8tYqxSAlDPbGzgGDGzMC2ZIn06MQMjK5y-4zgUUwoZ4fpxzMqWmkVPKOrRjvAK6_3e6jSAC4hgy95YgV2YrtAbLfEKl-HNukeEKTXtRjoxHBRuH3dqBrBYkipqXZkYHiISJXfABEftr7ArhrNH4QDRf8H7xkf0r0vPWftFyjD0JslnnV7QGCW_X-oWfy7Q5vMD55dmpvZJ3S7nPay2rKRk49rJZMIwbLf78WU5lgcNXrKyWfyQDKomzo70GSHEKJ5iQmzBG8EzWZAz07h1ZBvx1M_gX0U5Nx2P2Rdzi8SUqEWKjk3dLXS3NbX1IQxWUpPg5F"

resp = requests.get(
    "https://graph.facebook.com/v18.0/oauth/access_token",
    params={
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": CODE,
    },
)
print(resp.status_code, resp.json())
