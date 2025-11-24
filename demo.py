import requests
import json

# Webhook URL
webhook_url = "http://localhost:5678/webhook/prompt"

# Data to send
data = {
    "prompt": "create an image of a futuristic cityscape at sunset",
}

# Send POST request
try:
    response = requests.post(webhook_url, json=data)
    
    # Check if the request was successful
    if response.status_code == 200:
        print("✅ POST request sent successfully!")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
    else:
        print(f"❌ Request failed with status code: {response.status_code}")
        print(f"Response: {response.text}")
        
except requests.exceptions.RequestException as e:
    print(f"❌ Error sending request: {e}")