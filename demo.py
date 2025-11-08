import paho.mqtt.client as mqtt

# MQTT broker details
broker = "159.65.77.162"  # Same as ESP32
port = 1883
topic = "innovation_hub/spot/3"

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

# # include <WiFi.h>
# # include <WiFiClientSecure.h>
# # include <PubSubClient.h>

# // WiFi credentials
# const char* ssid = "Cloud";
# const char* password = "cloud2024";

# // MQTT broker settings
# const char* mqtt_server = "159.65.77.162";  // your VM IP
# const int mqtt_port = 1883;                 // non-TLS for now
# const char* topic = "innovation_hub/spot/1";

# // Ultrasonic pins
# #define TRIG_PIN 5
# #define ECHO_PIN 18

# // Parameters
# const float THRESHOLD_CM = 100.0;   // 1 meter
# const unsigned long MIN_TRACK_TIME = 100; // 10 sec

# bool vehiclePresent = false;
# unsigned long trackStartTime = 0;
# bool vehicleConfirmed = false;

# // WiFi & MQTT clients
# WiFiClient espClient;
# PubSubClient client(espClient);

# // Reliable publish with retry using QoS 2
# bool publishWithRetry(const char* topic, const char* payload) {
#   bool success = false;
#   int attempts = 0;

#   while (!success && attempts < 5) {
#     success = client.publish(topic, payload, true);  // retained true, QoS 2 handled automatically by PubSubClient
#     if (!success) {
#       Serial.println("⚠️ Publish failed, retrying...");
#       delay(500);
#       client.loop();
#     }
#     attempts++;
#   }
#   return success;
# }

# void setup_wifi() {
#   Serial.print("Connecting to WiFi: ");
#   Serial.println(ssid);
#   WiFi.begin(ssid, password);

#   while (WiFi.status() != WL_CONNECTED) {
#     delay(500);
#     Serial.print(".");
#   }
#   Serial.println("\n✅ WiFi connected!");
# }

# void reconnect() {
#   while (!client.connected()) {
#     Serial.print("Connecting to MQTT...");
#     if (client.connect("ESP32Client")) {  // no username/password needed for now
#       Serial.println("✅ Connected to broker");
#     } else {
#       Serial.print("❌ Failed, rc=");
#       Serial.print(client.state());
#       Serial.println(" retrying in 5s");
#       delay(5000);
#     }
#   }
# }

# float getDistance() {
#   digitalWrite(TRIG_PIN, LOW);
#   delayMicroseconds(2);
#   digitalWrite(TRIG_PIN, HIGH);
#   delayMicroseconds(10);
#   digitalWrite(TRIG_PIN, LOW);

#   long duration = pulseIn(ECHO_PIN, HIGH, 30000); // timeout ~5m
#   if (duration == 0) return -1;
#   return (duration * 0.0343) / 2; // cm
# }

# void setup() {
#   Serial.begin(9600);
#   pinMode(TRIG_PIN, OUTPUT);
#   pinMode(ECHO_PIN, INPUT);

#   setup_wifi();

#   client.setServer(mqtt_server, mqtt_port);
#   client.setBufferSize(1024);
# }

# void loop() {
#   if (!client.connected()) {
#     reconnect();
#   }
#   client.loop();

#   float distance = getDistance();
#   unsigned long now = millis();

#   if (distance > 0) {
#     Serial.print("Distance: ");
#     Serial.print(distance);
#     Serial.println(" cm");
#   }

#   if (distance > 0 && distance <= THRESHOLD_CM) {
#     if (!vehiclePresent) {
#       vehiclePresent = true;
#       trackStartTime = now;
#     } else {
#       if (!vehicleConfirmed && (now - trackStartTime >= MIN_TRACK_TIME)) {
#         vehicleConfirmed = true;
#         Serial.println("🚗 Vehicle Entered");
#         if (publishWithRetry(topic, "Vehicle Entered")) {
#           Serial.println("✅ Vehicle Entered message sent");
#         } else {
#           Serial.println("❌ Failed to send Vehicle Entered message");
#         }
#       }
#     }
#   } else {
#     if (vehicleConfirmed) {
#       Serial.println("🚗 Vehicle Left");
#       if (publishWithRetry(topic, "Vehicle Left")) {
#         Serial.println("✅ Vehicle Left message sent");
#       } else {                                    
#         Serial.println("❌ Failed to send Vehicle Left message");
#       }
#     }
#     vehiclePresent = false;
#     vehicleConfirmed = false;
#   }

#   delay(500);
# }