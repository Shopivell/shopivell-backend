import paho.mqtt.client as mqtt

# MQTT broker details
broker = "159.65.77.162"  # Same as ESP32
port = 1883
topic = "innovation_hub/spot/2"

# Callback when message arrives
def on_message(client, userdata, msg):
    print(f"📩 Received on {msg.topic}: {msg.payload.decode()}")

# Setup client
client = mqtt.Client()
client.on_message = on_message

print("Connecting to broker...")
client.connect(broker, port, 60)

# Subscribe to topic
client.subscribe(topic)

print(f"Subscribed to {topic}. Waiting for messages...")
client.loop_forever()