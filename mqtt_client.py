import paho.mqtt.client as mqtt
from typing import Optional
import time
import ssl
import threading

class MQTTClient:
    def __init__(self, broker: str, port: int = 1883, keepalive: int = 60, use_tls: bool = True,
                 ca_certs: str | None = None, certfile: str | None = None, keyfile: str | None = None):
        self.broker = broker
        self.port = port
        self.keepalive = keepalive
        self.use_tls = use_tls
        # Default certificate paths can be overridden via constructor
        self.ca_certs = ca_certs or "ca.crt"
        self.certfile = certfile or "server.crt"
        self.keyfile = keyfile or "server.key"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self.received_messages = []
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self._connected_event = threading.Event()
        self._connect_rc = None  # Store result code for inspection

    def _on_connect(self, client, userdata, flags, rc):
        self._connect_rc = rc
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker}:{self.port}")
        else:
            print(f"Failed to connect to MQTT broker, return code: {rc}")
        self._connected_event.set()

    def _on_message(self, client, userdata, msg):
        """Callback when message is received"""
        message = {
            'topic': msg.topic,
            'payload': msg.payload.decode('utf-8'),
            'qos': msg.qos,
            'retain': msg.retain
        }
        self.received_messages.append(message)
        print(f"Received message on {msg.topic}: {msg.payload.decode('utf-8')}")

    def connect(self, timeout: float = 10.0) -> bool:
        """Connects to the MQTT broker and waits until connection is established or fails."""
        try:
            self._connected_event.clear()
            if self.use_tls:
                self.client.tls_set(
                    ca_certs=self.ca_certs,
                    certfile=self.certfile,
                    keyfile=self.keyfile,
                    cert_reqs=ssl.CERT_NONE,
                    tls_version=ssl.PROTOCOL_TLSv1_2
                )
                self.client.tls_insecure_set(True)
            self.client.connect(self.broker, self.port, self.keepalive)
            self.client.loop_start()
            connected = self._connected_event.wait(timeout)
            if not connected:
                print(f"Timed out waiting for MQTT connection to {self.broker}:{self.port}")
                return False
            return self._connect_rc == 0
        except (ConnectionRefusedError, OSError) as e:
            print(f"MQTT connection to {self.broker}:{self.port} failed: {e}")
            return False

    def subscribe(self, topic: str, qos: int = 0) -> bool:
        """Subscribes to a topic."""
        if not self.client.is_connected():
            print("MQTT client is not connected.")
            return False
        
        result = self.client.subscribe(topic, qos)
        if result[0] == mqtt.MQTT_ERR_SUCCESS:
            print(f"Subscribed to {topic}")
            return True
        else:
            print(f"Failed to subscribe to {topic}")
            return False

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        """Publishes a message to a given topic."""
        if not self.client.is_connected():
            print("MQTT client is not connected.")
            return False
        
        result = self.client.publish(topic, payload, qos, retain)
        result.wait_for_publish(timeout=5)
        
        if result.is_published():
            return True
        else:
            print(f"Failed to publish message to topic: {topic}")
            return False

    def has_message(self) -> bool:
        """Check if any messages have been received."""
        return len(self.received_messages) > 0

    def get_message(self) -> Optional[dict]:
        """Get the next received message."""
        if self.received_messages:
            return self.received_messages.pop(0)
        return None

    def clear_messages(self):
        """Clear all received messages."""
        self.received_messages.clear()

    def disconnect(self):
        """Disconnects from the MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
