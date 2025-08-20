#!/usr/bin/env python3
"""
Sengled Local Control & Crypto Tool
A comprehensive, self-contained tool for local interaction with Sengled Wi-Fi bulbs.
"""

import argparse
import json
import os
import sys
import shutil
import time
import socket
from urllib.parse import urlparse
import warnings
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from getmac import get_mac_address

# Suppress SSL and certificate warnings
warnings.filterwarnings("ignore", message=".*SSL.*", category=Warning)
warnings.filterwarnings("ignore", message=".*certificate.*",category=Warning)

from sengled_wifi_crypto import SengledWiFiCrypto, encrypt_wifi_payload, decrypt_wifi_payload
from mqtt_client import MQTTClient
from utils import get_local_ip, save_bulb, load_bulbs, get_current_epoch_ms, get_bulb_broker

# MQTT Configuration
BROKER_IP = "192.168.0.100"
BROKER_PORT = 1883

# UDP Configuration
BULB_IP = "192.168.8.1"

BULB_PORT = 9080


class Console:
    SEP = "=" * 64

    @staticmethod
    def section(title: str) -> None:
        print(f"\n{Console.SEP}\n{title}\n{Console.SEP}")

    @staticmethod
    def info(msg: str) -> None:
        print(f"[INFO] {msg}")

    @staticmethod
    def ok(msg: str) -> None:
        print(f"[OK]   {msg}")

    @staticmethod
    def warn(msg: str) -> None:
        print(f"[WARN] {msg}")

    @staticmethod
    def error(msg: str) -> None:
        print(f"[ERR]  {msg}")

    @staticmethod
    def step(msg: str) -> None:
        print(f"  -> {msg}")


class _SetupHTTPServer:
    """Lightweight HTTP server used during Wi‑Fi setup.

    - Serves two endpoints the bulb calls:
      • /life2/device/accessCloud.json
      • /jbalancer/new/bimqtt
    - Stops after both endpoints have been hit at least once (any method).
    """

    def __init__(self, mqtt_host: str, mqtt_port: int, preferred_port: int = 80):
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.preferred_port = preferred_port
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: Optional[int] = None

        # Endpoint hit tracking
        self._hit_access_cloud = threading.Event()
        self._hit_bimqtt = threading.Event()
        self.last_client_ip: Optional[str] = None
        self.active: bool = False

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send_json(self, data: dict):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                payload = json.dumps(data).encode("utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):  # noqa: N802 (stdlib signature)
                length = int(self.headers.get("Content-Length", 0) or 0)
                _ = self.rfile.read(length) if length > 0 else b""

                print(f"DEBUG: Received PUT request on {self.path} from {self.client_address[0]}")
                parsed_url = urlparse(self.path)

                if parsed_url.path == "/life2/device/accessCloud.json":
                    outer.last_client_ip = self.client_address[0]
                    outer._hit_access_cloud.set()
                    self._send_json({
                        "messageCode": "200",
                        "info": "OK",
                        "description": "正常",
                        "success": True,
                    })
                    return

                if parsed_url.path == "/jbalancer/new/bimqtt":
                    outer.last_client_ip = self.client_address[0]
                    outer._hit_bimqtt.set()
                    self._send_json({
                        "protocal": "mqtt",
                        "host": outer.mqtt_host,
                        "port": outer.mqtt_port,
                    })
                    return

                self.send_error(404, "Not Found")

            def do_GET(self):  # noqa: N802 (stdlib signature)
                print(f"DEBUG: Received GET request on {self.path} from {self.client_address[0]}")
                parsed_url = urlparse(self.path)

                # Treat GET the same for robustness
                if parsed_url.path == "/life2/device/accessCloud.json":
                    outer.last_client_ip = self.client_address[0]
                    outer._hit_access_cloud.set()
                    self._send_json({
                        "messageCode": "200",
                        "info": "OK",
                        "description": "正常",
                        "success": True,
                    })
                    return

                if parsed_url.path == "/jbalancer/new/bimqtt":
                    outer.last_client_ip = self.client_address[0]
                    outer._hit_bimqtt.set()
                    self._send_json({
                        "protocal": "mqtt",
                        "host": outer.mqtt_host,
                        "port": outer.mqtt_port,
                    })
                    return
                # Firmware download handler
                if parsed_url.path.endswith(".bin"):
                    requested = os.path.basename(parsed_url.path)
                    # Only allow direct root requests, not any path structure
                    if "/" in parsed_url.path.strip("/").replace(requested, ""):
                        print(f"❌ Refused firmware download with path component: {parsed_url.path}")
                        self.send_error(400, "Invalid firmware path")
                        return
                    # Prevent dangerous names and empty
                    if not requested or requested in (".", ".."):
                        print(f"❌ Refused firmware download with dangerous name: {requested}")
                        self.send_error(400, "Invalid firmware filename")
                        return
                    local_file = os.path.join(os.path.dirname(__file__), requested)
                    if not os.path.isfile(local_file):
                        print(f"❌ Firmware file not found: {requested}")
                        self.send_error(404, "Firmware file not found")
                        return
                    try:
                        with open(local_file, "rb") as fw:
                            data = fw.read()
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/octet-stream')
                        self.send_header('Content-Disposition', f'attachment; filename="{requested}"')
                        self.send_header('Content-Length', str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        print(f"📤 Served firmware file: {requested} ({len(data)} bytes)")
                    except Exception as e:
                        print(f"❌ Error sending firmware: {e}")
                        self.send_error(500, "Error sending firmware file")
                    return

                self.send_error(404, "Not Found")

            def log_message(self, fmt, *args):  # silence stdlib noisy logger
                return

        return Handler

    def start(self) -> bool:
        # Try preferred port, then fallback to 8080 automatically
        print("HTTP Server starting.... ", end="", flush=True)
        for port in [self.preferred_port, 8080] if self.preferred_port != 8080 else [self.preferred_port, 80]:
            try:
                self.server = HTTPServer(("0.0.0.0", port), self._make_handler())
                self.port = port
                break
            except OSError:
                continue

        if not self.server:
            # Could not bind; another server likely running
            print("Failed")
            Console.warn("Embedded setup HTTP server not started (ports 80/8080 busy).")
            Console.warn("Another HTTP server is likely running. The tool will NOT wait for endpoint hits or run the UDP test.")
            Console.warn("Stop the other server or set SENGLED_HTTP_PORT to a free port, then rerun pairing.")
            self.active = False
            return False

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"Success (port {self.port})")
        self.active = True
        return True

    def wait_until_both_endpoints_hit(self, timeout_seconds: int = 120) -> bool:
        start = time.time()
        # Wait for both flags with overall timeout
        while time.time() - start < timeout_seconds:
            if self._hit_access_cloud.is_set() and self._hit_bimqtt.is_set():
                return True
            time.sleep(0.25)
        return self._hit_access_cloud.is_set() and self._hit_bimqtt.is_set()

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
                self.server.server_close()
            finally:
                self.server = None
                Console.info("Setup HTTP server stopped.")


def _check_mqtt_broker_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            Console.ok(f"MQTT broker reachable at {host}:{port}")
            return True
    except OSError:
        Console.warn(f"MQTT broker not reachable at {host}:{port}. Start it before pairing.")
        return False


def send_udp_command(bulb_ip: str, payload_dict: dict, timeout: int = 3):
    """
    Send a UDP command to the bulb using the simple JSON protocol.
    
    Args:
        bulb_ip: IP address of the bulb
        payload_dict: Python dictionary to send as JSON
        timeout: Socket timeout in seconds
    
    Returns:
        dict: Response from bulb, or None if failed
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            
            # Serialize the dictionary to JSON string
            json_payload = json.dumps(payload_dict)
            encoded_payload = json_payload.encode('utf-8')
            
            print(f"> Sent UDP command: {json_payload}")
            
            # Send to bulb using configured UDP port
            s.sendto(encoded_payload, (bulb_ip, BULB_PORT))
            
            # Wait for response
            try:
                data, addr = s.recvfrom(4096)
                response_str = data.decode('utf-8')
                print(f"< Received UDP response: {response_str}")
                
                # Parse response as JSON
                try:
                    response_dict = json.loads(response_str)
                    return response_dict
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse response as JSON: {response_str}")
                    return None
                    
            except socket.timeout:
                print("Timeout: No response received from bulb... trying again")
                return None

    except Exception as e:
        print(f"Error sending UDP command: {e}")
        return None


def _udp_toggle_until_success(bulb_ip: str, max_wait_seconds: int = 60) -> bool:
    """Try ON/OFF via UDP until any request is acknowledged or timeout.

    Returns True on first success, False otherwise.
    """
    print("Will try sending a UDP request to toggle the bulb...")
    attempts = 0
    start_time = time.time()

    desired_states_cycle = [1, 0]
    cycle_index = 0

    while time.time() - start_time < max_wait_seconds:
        next_state = desired_states_cycle[cycle_index]
        cycle_index = (cycle_index + 1) % len(desired_states_cycle)
        payload = {"func": "set_device_switch", "param": {"switch": next_state}}
        attempts += 1
        response = send_udp_command(bulb_ip, payload)
        if response and isinstance(response, dict):
            result = response.get("result", {})
            if isinstance(result, dict) and result.get("ret") == 0:
                print("UDP control succeeded")
                return True
        time.sleep(1)

    print("UDP control did not succeed within the timeout.")
    return False

def send_update_command(client: MQTTClient, mac_address: str, command_list: list):
    """
    Sends a command to the bulb's update topic using a "fire-and-forget" approach.
    """
    update_topic = f"wifielement/{mac_address}/update"
    payload = json.dumps(command_list)
    
    print(f"Publishing command with QoS=1...")
    print(f"  Topic: {update_topic}")
    print(f"  Payload: {payload}")
    
    # Just publish the command. Do not subscribe or wait.
    success = client.publish(update_topic, payload, qos=1)
    
    if success:
        print("Command sent successfully.")
        # Brief pause to ensure the message is sent before the script potentially exits
        time.sleep(0.5) 
        return payload
    else:
        print("Failed to send command.")
        return None

def get_bulb_status(client: MQTTClient, mac_address: str):
    """
    Requests bulb status by publishing an EMPTY payload to the /status topic,
    which appears to trigger the bulb to report its full state. This matches
    the behavior observed in broker logs for a successful status query.
    """
    status_topic = f"wifielement/{mac_address}/status"

    # Make sure the network loop is running
    if hasattr(client, "loop_start"):
        client.loop_start()

    # Subscribe and wait a beat for SUBACK
    print(f"Subscribing to {status_topic} to listen for the response...")
    rc = client.subscribe(status_topic, qos=1)
    # if your subscribe returns (rc, mid), handle that:
    if isinstance(rc, tuple):
        rc, _mid = rc
# debug
#    if rc != 0:
#        print("Failed to subscribe to status topic.")
#        return None
    time.sleep(0.2)  # small cushion for SUBACK, or use on_subscribe

    # Clear any stale messages
    client.clear_messages()

    # Publish an EMPTY payload to the status topic. This is the trigger.
    print(f"Requesting status by publishing an empty payload to {status_topic}...")
    if not client.publish(status_topic, "", qos=1):
        print("Failed to publish status request.")
        return None

    print(f"Waiting for status report from the bulb ({status_topic})...")
    start_time = time.time()
    timeout = 10  # 10 second timeout

    # We will receive our own empty message back. We need to ignore it and wait for the real one.
    while time.time() - start_time < timeout:
        if hasattr(client, "loop"):
            client.loop(timeout=0.1)
        message = client.get_message() if hasattr(client, "get_message") else None
        if not message:
            time.sleep(0.05)
            continue

        received_topic_str = getattr(message, "topic", message.get("topic"))
        received_payload_str = getattr(message, "payload", message.get("payload"))
            
        # The echo of our own message will be empty or None. The real status is a JSON list.
        if received_topic_str != status_topic or not received_payload_str:
            print("Ignoring self-echoed empty message...")
            continue

            try:
                received_data = json.loads(payload if isinstance(payload, str) else payload.decode())
                if not isinstance(received_data, list):
                    print("Received something, but not the format we want")
                    continue # Not the format we expect

                # This is it! We got a non-empty JSON payload.
                print("\n--- Bulb Status Report ---")
                for item in received_data:
                    print(f"  {item.get('type', 'Unknown Type'):<20}: {item.get('value', 'N/A')}")
                print("--------------------------\n")
                
                # It's possible the bulb sends multiple status messages.
                # We can either return the first one or try to collect them all.
                # For now, returning after the first valid report is sufficient.
                return received_data

            except json.JSONDecodeError:
                print(f"Warning: Received non-JSON message on status topic: {received_payload_str}")
                
        time.sleep(0.3)

    print("Timeout: No status response from the bulb. Please ensure the bulb is online and connected to the broker.")
    return None

class SengledTool():
    def __init__(self, args):
        self.wifi_crypto = SengledWiFiCrypto()
        self.args = args

    def _perform_wifi_setup(
        self, broker_ip: str, broker_port: int, wifi_ssid: str, wifi_pass: str, wifi_bssid: str = None,
        interactive: bool = True, udp_bulb_ip: str = BULB_IP
    ):
        """Private helper method to perform Wi-Fi setup with given credentials."""
        # 0) Discover and log system WiFi IP address for HTTP endpoint
        local_wifi_ip = get_local_ip()
        Console.section("Setup Preparation")
        Console.info(f"Detected local Wi-Fi IP address: {local_wifi_ip}")
        # Prompt for MQTT broker address to be configured
        if interactive:
            user_broker_ip = input(f"Enter MQTT broker IP to configure bulb [{broker_ip or local_wifi_ip}]: ").strip()
            if user_broker_ip:
                broker_ip = user_broker_ip
            else:
                # If user presses enter, default to passed argument or detected IP
                broker_ip = broker_ip or local_wifi_ip
        else:
            broker_ip = broker_ip or local_wifi_ip
        # Save for later HTTP server binding
        http_endpoint_ip = local_wifi_ip
        Console.info("Before continuing, connect your computer to the Sengled bulb's Wi-Fi network (usually named 'Sengled_Wi-Fi Bulb_XXXXXX').")
        input("Press Enter when you have connected to the bulb's Wi-Fi...")

        # 0) Start local HTTP server first (use remembered WiFi IP as endpoint)
        preferred_http_port = int(os.environ.get("SENGLED_HTTP_PORT", "80") or 80)
        setup_server = _SetupHTTPServer(mqtt_host=broker_ip, mqtt_port=broker_port, preferred_port=preferred_http_port)
        server_started = setup_server.start()

        # 0.1) Check broker reachability
        _check_mqtt_broker_reachable(broker_ip, broker_port)

        Console.section("Wi‑Fi Pairing")
        Console.step("Connecting to bulb")
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(15)

                # Step 1: Initial Handshake
                start_req = {"name": "startConfigRequest", "totalStep": 1, "curStep": 1, "payload": {"protocol": 1}}
                s.sendto(json.dumps(start_req).encode('utf-8'), (BULB_IP, BULB_PORT))
                data, _ = s.recvfrom(4096)
                handshake_resp = json.loads(data.decode('utf-8'))

                if "mac" not in handshake_resp["payload"] and self.args.mac:
                    print("MAC address not provided by bulb, using command line option --mac")
                    # set mac address from command line option --mac
                    handshake_resp["payload"]["mac"] = self.args.mac

                if "payload" not in handshake_resp or "mac" not in handshake_resp["payload"]:
                    bulb_mac = get_mac_address(ip=BULB_IP)
                else:
                    bulb_mac = handshake_resp["payload"]["mac"]
                
                if len(bulb_mac) != 17: #length of a valid Mac Address
                    print(f"Connection failed: {handshake_resp}", file=sys.stderr)
                    return

                Console.ok(f"Connected to bulb. MAC: {bulb_mac}")

                if interactive:
                    # Step 2: Trigger Wi-Fi Scan (interactive only)
                    Console.step("Requesting the bulb to scan for nearby Wi‑Fi networks")
                    scan_req = {"name": "scanWifiRequest", "totalStep": 1, "curStep": 1, "payload": {}}
                    s.sendto(json.dumps(scan_req).encode('utf-8'), (BULB_IP, BULB_PORT))
                    time.sleep(5)

                    # Step 3: Get AP List (interactive only)
                    Console.step("Requesting the bulb to return the scanned network list")
                    ap_req = {"name": "getAPListRequest", "totalStep": 1, "curStep": 1, "payload": {}}
                    s.sendto(json.dumps(ap_req).encode('utf-8'), (BULB_IP, BULB_PORT))
                    data, _ = s.recvfrom(4096)
                    ap_list_resp = json.loads(data.decode('utf-8'))
                    routers = ap_list_resp.get("payload", {}).get("routers", [])

                    if not routers:
                        print("No networks found.")
                        return

                    print("\nAvailable networks:")
                    for i, router in enumerate(routers):
                        signal_bars = "▂▄▆█"[min(int(router['signal']), 3)]
                        print(f"   [{i+1}] {router['ssid']} {signal_bars}")

                    choice = -1
                    while choice < 1 or choice > len(routers):
                        try:
                            choice_input = input(f"\nSelect network (1-{len(routers)}): ")
                            choice = int(choice_input)
                        except (ValueError, IndexError):
                            pass

                    chosen_router = routers[choice-1]
                    wifi_ssid = chosen_router['ssid']
                    wifi_bssid = chosen_router['bssid']
                    Console.info(f"Selected network: {wifi_ssid}")
                    
                    # Get password interactively
                    wifi_pass = input(f"Password for '{wifi_ssid}': ").strip()

                # Re-Handshake for configuration
                rehandshake_step = "[4/6]" if interactive else "[2/4]"
                Console.step("Preparing configuration")
                s.sendto(json.dumps(start_req).encode('utf-8'), (BULB_IP, BULB_PORT))
                data, addr = s.recvfrom(4096)
                re_handshake_resp = json.loads(data.decode('utf-8'))
                if not re_handshake_resp.get("payload", {}).get("result"):
                    print("Configuration prep failed")
                    return

                # Configure Network
                config_step = "[5/6]" if interactive else "[3/4]"
                Console.step("Sending network credentials to bulb")
                
                # Build router config based on SSID content
                ascii_only = all(ord(c) < 128 for c in wifi_ssid)
                if ascii_only:
                    router_info = {"ssid": wifi_ssid, "password": wifi_pass}
                else:
                    router_info = {"ssid": "", "bssid": wifi_bssid.upper(), "password": wifi_pass}
                
                # Use the actual HTTP setup server port we bound and the remembered WiFi IP address
                http_port = str(setup_server.port)
                http_host = http_endpoint_ip
                params_payload = {
                    "name": "setParamsRequest", "totalStep": 1, "curStep": 1,
                   "payload": {
                        "userID": "618",
                        "appServerDomain": f"http://{http_host}:{http_port}/life2/device/accessCloud.json",
                        "jbalancerDomain": f"http://{http_host}:{http_port}/jbalancer/new/bimqtt",
                        "timeZone": "America/Chicago",
                        "routerInfo": router_info,
                    },
                }

                if interactive:
                    print(f"DEBUG: Sending unencrypted payload:\n{json.dumps(params_payload, indent=2)}")
                encrypted_params = encrypt_wifi_payload(params_payload)
                s.sendto(encrypted_params.encode('utf-8'), (BULB_IP, BULB_PORT))

                try:
                    data, _ = s.recvfrom(4096)
                    response_str = data.decode('utf-8')
                    if interactive:
                        print(f"DEBUG: Received raw response from bulb:\n{response_str}")

                    try:
                        # First, try to parse as JSON (plaintext response)
                        response_json = json.loads(response_str)
                        if interactive:
                            print("DEBUG: Parsed response as plaintext JSON.")
                        if response_json.get("payload", {}).get("result") is not True:
                            Console.error("Bulb rejected credentials (plaintext error).")
                            return
                    except json.JSONDecodeError:
                        # If JSON parsing fails, assume it's encrypted
                        if interactive:
                            print("DEBUG: Could not parse as JSON, attempting decryption...")
                        decrypted_resp = decrypt_wifi_payload(response_str)
                        if interactive:
                            print(f"DEBUG: Decrypted response:\n{json.dumps(decrypted_resp, indent=2)}")
                        if not isinstance(decrypted_resp, dict) or not decrypted_resp.get("payload", {}).get("result"):
                            Console.error("Bulb rejected credentials (decryption failed).")
                            return
                except socket.timeout:
                    pass # Timeout is expected here

                Console.ok("Credentials accepted by bulb")

                # End Configuration
                end_step = "[6/6]" if interactive else "[4/4]"
                Console.step("Finalizing configuration")
                end_req = {"name": "endConfigRequest", "totalStep": 1, "curStep": 1, "payload": {}}
                s.sendto(json.dumps(end_req).encode('utf-8'), (BULB_IP, BULB_PORT))

                try:
                    s.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    pass # Also expected
                
                if interactive:
                # Step 7: Wait for device to connect to local setup (interactive only)
                    Console.step("Waiting for device to join your Wi‑Fi and call local endpoints")
                    
                    save_bulb(bulb_mac, broker_ip)
                    Console.ok(f"Setup complete for {bulb_mac}. Target MQTT broker: {broker_ip}")
                    Console.info("The bulb will now: 1) connect to your Wi‑Fi, 2) call local HTTP endpoints, 3) get MQTT settings, 4) connect to your broker")
                    
                    # Print example commands
                    script_name = sys.argv[0] if sys.argv else "sengled_tool.py"
                    print(f"\nExample commands for controlling your bulb:")
                    print(f"  python {script_name} --mac {bulb_mac} --on")
                    print(f"  python {script_name} --mac {bulb_mac} --off")
                    print(f"  python {script_name} --mac {bulb_mac} --brightness 50")
                    print(f"  python {script_name} --mac {bulb_mac} --color 255 0 0")
                else:
                    save_bulb(bulb_mac, broker_ip)
                    Console.ok(f"Setup complete for {bulb_mac}. Target MQTT broker: {broker_ip}")

                # 8) Wait for the bulb to contact both endpoints, then stop server
                Console.section("Finalize")
                Console.info("Waiting for bulb to contact both endpoints: /life2/device/accessCloud.json and /jbalancer/new/bimqtt ...")
                Console.info("On success, the bulb should flash a few times and then connect to your MQTT broker.")
                both_hit = setup_server.wait_until_both_endpoints_hit(timeout_seconds=180)
                if both_hit:
                    Console.ok("Bulb contacted both endpoints. Stopping HTTP server...")
                else:
                    Console.warn("Timeout waiting for endpoints. Stopping HTTP server...")

                if setup_server.active:
                    setup_server.stop()

                if both_hit:
                    Console.ok("Bulb contacted both endpoints. Proceeding to UDP test")
                else:
                    Console.warn("Proceeding to UDP test anyway")

                # 9) Try UDP until both ON and OFF succeed or timeout; report elapsed time
                if server_started:
                    try:
                        udp_target_ip = setup_server.last_client_ip or udp_bulb_ip
                        if setup_server.last_client_ip:
                            Console.info(f"Detected bulb IP from HTTP requests: {udp_target_ip}")
                            if _udp_toggle_until_success(udp_target_ip, max_wait_seconds=60):
                                Console.section("Examples you can run next")
                                print(f"UDP OFF:         python {sys.argv[0]} --ip {udp_target_ip} --udp-off")
                                print(f"UDP ON:          python {sys.argv[0]} --ip {udp_target_ip} --udp-on")
                                print(f"UDP BRIGHTNESS:  python {sys.argv[0]} --ip {udp_target_ip} --udp-brightness 50")
                                print(f"UDP COLOR:       python {sys.argv[0]} --ip {udp_target_ip} --udp-color 255 0 0")
                                print(f"MQTT ON:         python {sys.argv[0]} --broker-ip {broker_ip} --mac {bulb_mac} --on")
                                print(f"MQTT OFF:        python {sys.argv[0]} --broker-ip {broker_ip} --mac {bulb_mac} --off")
                                print(f"MQTT BRIGHTNESS: python {sys.argv[0]} --broker-ip {broker_ip} --mac {bulb_mac} --brightness 50")
                                print(f"MQTT COLOR:      python {sys.argv[0]} --broker-ip {broker_ip} --mac {bulb_mac} --color 255 0 0")
                                print(f"MQTT COLOR-TEMP: python {sys.argv[0]} --broker-ip {broker_ip} --mac {bulb_mac} --color-temp 3000")
                        else:
                            Console.warn("Could not detect bulb LAN IP from HTTP requests; skipping UDP test. Start your MQTT broker before pairing.")
                    except Exception:
                        Console.warn("UDP test failed (non-fatal). Start your MQTT broker before pairing.")
                else:
                    Console.warn("Embedded HTTP server was not started (port busy). Skipping UDP test.")

        except KeyboardInterrupt:
            if server_started and setup_server.active:
                setup_server.stop()
            Console.warn("Interrupted by user. Exiting setup.")
            return
        except (socket.timeout, ConnectionResetError):
            Console.error("Connection lost during setup. Ensure you are connected to the bulb's Wi‑Fi.")
        except Exception as e:
            Console.error(f"Setup failed: {e}")

    def interactive_wifi_setup(self, broker_ip: str):
        print("Sengled Wi-Fi Setup")
        print("Ensure you are connected to the bulb's 'Sengled_Wi-Fi Bulb_XXXXXX' network.")
        print("Make sure your MQTT broker is running and reachable before pairing.")
        
        # Call the helper method with None credentials (will be obtained interactively)
        self._perform_wifi_setup(broker_ip, BROKER_PORT, "", "", interactive=True)
            
    def non_interactive_wifi_setup(self, broker_ip: str, ssid: str, password: str):
        print("Sengled Wi-Fi Setup (Non-interactive)")
        print("Ensure you are connected to the bulb's 'Sengled_Wi-Fi Bulb_XXXXXX' network.")
        print("Make sure your MQTT broker is running and reachable before pairing.")
        
        # Call the helper method with provided credentials
        self._perform_wifi_setup(broker_ip, BROKER_PORT, ssid, password, interactive=False)

    # FIX: Removed redundant and unused get_bulb_status method from this class.
    # The global, corrected function will be used instead.

def startLocalServer():
    print("Starting Sengled local server...")
    server = _SetupHTTPServer(
        mqtt_host=args.broker_ip or get_local_ip(),
        mqtt_port=args.mqtt_port,
        preferred_port=args.http_port
    )
    started = server.start()
    if not started:
        print("Could not start HTTP server, exiting.")
        return

    print(f"Sengled local server running on port {server.port}.")
    print("Endpoints:")
    print("  /life2/device/accessCloud.json")
    print("  /jbalancer/new/bimqtt")
    print("  GET  /firmware.bin (or any .bin in script's directory)")
    print("Press Ctrl+C to stop.")

def prepare_firmware_bin(user_path):
    # Expand ~ and resolve absolute path
    user_path = os.path.expanduser(user_path)
    if not os.path.isfile(user_path):
        print(f"Error: File does not exist: {user_path}")
        return None

    basename = os.path.basename(user_path)
    if not basename.lower().endswith('.bin'):
        print("Error: Firmware file must have a .bin extension.")
        return None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    dest_path = os.path.join(script_dir, basename)

    if os.path.isfile(dest_path):
        print(f"Firmware file already present at: {dest_path}")
        return basename  # Ready for HTTP server

    try:
        shutil.copy2(user_path, dest_path)
        print(f"Firmware file copied to: {dest_path}")
        return basename  # What the HTTP server expects
    except Exception as e:
        print(f"Error copying firmware file: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Sengled Local Control Tool", formatter_class=argparse.RawTextHelpFormatter)

    parser.add_argument("--setup-wifi", action="store_true", help="Start interactive Wi-Fi setup.")
    parser.add_argument("--broker-ip", default=None, help="IP address of your MQTT broker (defaults to this PC's local IP if omitted).")
    parser.add_argument("--mqtt-port", type=int, default=BROKER_PORT, help="MQTT broker port (default: 1883).")
    parser.add_argument("--ca-crt", help="Path to CA certificate (default: ca.crt)")
    parser.add_argument("--server-crt", help="Path to server certificate (default: server.crt)")
    parser.add_argument("--server-key", help="Path to server private key (default: server.key)")
    parser.add_argument("--ssid", help="Wi-Fi SSID for non-interactive setup.")
    parser.add_argument("--password", help="Wi-Fi password for non-interactive setup.")
    
    control_group = parser.add_argument_group('Bulb Control (MQTT)')
    control_group.add_argument("--mac", help="MAC address of the bulb to control.")
    control_group.add_argument("--on", action="store_true", help="Turn the bulb on.")
    control_group.add_argument("--off", action="store_true", help="Turn the bulb off.")
    control_group.add_argument("--toggle", action="store_true", help="Toggle the bulb's power state.")
    control_group.add_argument("--brightness", type=int, help="Set brightness (0-100).")
    control_group.add_argument("--color", nargs=3, metavar=("R", "G", "B"), help="Set color (0-255 for each).")
    control_group.add_argument("--color-temp", type=int, help="Set color temperature (2700-6500K).")
    control_group.add_argument("--color-mode", type=int, choices=[1, 2], help="Set color mode (1=RGB, 2=white/temperature).")
    control_group.add_argument("--effect-status", type=int, help="Set effect status (0=off, 7=audio sync, 100=video sync, 101=game sync).")
    control_group.add_argument("--status", action="store_true", help="Query bulb status.")
    control_group.add_argument("--reset", action="store_true", help="Reset the bulb.")
    control_group.add_argument("--custom-payload", help="Send custom JSON payload to bulb.")
    control_group.add_argument("--update", action="store_true", help="Send info update command with Os$ prefix.")
    control_group.add_argument("--upgrade", help="Send firmware upgrade command with URL.")
    
    # Group control arguments
    control_group.add_argument("--group-macs", nargs="+", help="List of MAC addresses for group control.")
    control_group.add_argument("--group-switch", choices=["on", "off"], help="Control multiple bulbs on/off.")
    control_group.add_argument("--group-brightness", type=int, help="Set brightness for multiple bulbs (0-100).")
    control_group.add_argument("--group-color-temp", type=int, help="Set color temperature for multiple bulbs (2700-6500K).")
    control_group.add_argument("--gradient-time", type=int, default=10, help="Transition time for group commands (default: 10).")
    
    udp_group = parser.add_argument_group('UDP Control (Local Network)')
    udp_group.add_argument("--ip", help="IP address of the bulb for UDP control.")
    udp_group.add_argument("--udp-on", action="store_true", help="Turn the bulb on via UDP.")
    udp_group.add_argument("--udp-off", action="store_true", help="Turn the bulb off via UDP.")
    udp_group.add_argument("--udp-brightness", type=int, help="Set brightness via UDP (0-100).")
    udp_group.add_argument("--udp-color", nargs=3, metavar=("R", "G", "B"), help="Set color via UDP (0-255 for each).")
    udp_group.add_argument("--udp-json", help="Send a custom JSON payload via UDP.")

    control_group.add_argument("--topic", help="Custom MQTT topic to publish to.")
    control_group.add_argument("--payload", help="Custom payload to send (raw string, not JSON).")

    parser.add_argument("--run-http-server", action="store_true", help="Run the Sengled local server only (for firmware update testing).")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP server port (default: 80, falls back to 8080 if unavailable).")

    args = parser.parse_args()
    # Resolve broker IP: use provided value or fall back to local IP
    resolved_broker_ip = args.broker_ip or get_local_ip()
    tool = SengledTool(args)

    if args.run_http_server:
        startLocalServer()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping HTTP server...")
            server.stop()
            print("Server stopped.")
        return

    # Handle UDP commands first (they take precedence)
    if args.ip:
        if args.udp_on:
            payload = {"func": "set_device_switch", "param": {"switch": 1}}
            send_udp_command(args.ip, payload)
        elif args.udp_off:
            payload = {"func": "set_device_switch", "param": {"switch": 0}}
            send_udp_command(args.ip, payload)
        elif args.udp_brightness is not None:
            if 0 <= args.udp_brightness <= 100:
                payload = {"func": "set_device_brightness", "param": {"brightness": args.udp_brightness}}
                send_udp_command(args.ip, payload)
            else:
                print("Error: Brightness must be between 0 and 100")
        elif args.udp_color:
            try:
                r, g, b = args.udp_color
                r, g, b = int(r), int(g), int(b)
                if all(0 <= val <= 255 for val in [r, g, b]):
                    color_dec = f"{r:d}:{g:d}:{b:d}"
                    payload = {"func": "set_device_color", "param": {"color": color_dec}}
                    send_udp_command(args.ip, payload)
                else:
                    print("Error: Color values must be between 0 and 255")
            except TypeError as ve:
                print(f"Error: Could not convert input to integer for --udp-color: {args.udp_color}. Exception: {ve}")
            except TypeError as te:
                    print(f"TypeError: Bad type in color arguments {args.udp_color}: {te}")

        elif args.udp_json:
            try:
                custom = json.loads(args.udp_json)
                if not isinstance(custom, dict):
                    print("Error: --udp-json must be a JSON object")
                else:
                    send_udp_command(args.ip, custom)
            except json.JSONDecodeError:
                print("Error: Invalid JSON for --udp-json")
        else:
            print("Error: --ip requires a UDP command (--udp-on, --udp-off, --udp-brightness, --udp-color, or --udp-json)")
    elif args.setup_wifi:
        if args.ssid and args.password:
            tool.non_interactive_wifi_setup(resolved_broker_ip, args.ssid, args.password)
        else:
            tool.interactive_wifi_setup(resolved_broker_ip)
    elif args.group_macs:
        # Handle group commands (including single MAC)
        if not (args.group_switch or args.group_brightness or args.group_color_temp):
            print("Error: --group-macs requires a group command (--group-switch, --group-brightness, or --group-color-temp)")
            return
        
        # Initialize MQTT client for group control
        client = MQTTClient(
            resolved_broker_ip,
            port=args.mqtt_port,
            use_tls=True,
            ca_certs=args.ca_crt,
            certfile=args.server_crt,
            keyfile=args.server_key,
        )
        if not client.connect():
            print("Failed to connect to MQTT broker. Make sure your MQTT broker is running and reachable (see README).")
            return

        try:
            # Use first MAC as group ID (like the app does)
            group_id = args.group_macs[0]
            ts = get_current_epoch_ms()
            
            if args.group_switch:
                switch_value = "1" if args.group_switch == "on" else "0"
                command = [{
                    "dn": group_id,
                    "type": "groupSwitch", 
                    "value": {
                        "switch": switch_value,
                        "gradientTime": args.gradient_time,
                        "deviceUuidList": args.group_macs
                    },
                    "time": ts
                }]
                send_update_command(client, group_id, command)
                
            elif args.group_brightness is not None:
                if 0 <= args.group_brightness <= 100:
                    command = [{
                        "dn": group_id,
                        "type": "groupBrightness",
                        "value": {
                            "brightness": str(args.group_brightness),
                            "gradientTime": args.gradient_time,
                            "deviceUuidList": args.group_macs
                        },
                        "time": ts
                    }]
                    send_update_command(client, group_id, command)
                else:
                    print("Error: Group brightness must be between 0 and 100")
                    
            elif args.group_color_temp is not None:
                if 2700 <= args.group_color_temp <= 6500:
                    command = [{
                        "dn": group_id,
                        "type": "groupColorTemperature",
                        "value": {
                            "colorTemperature": str(args.group_color_temp),
                            "gradientTime": args.gradient_time,
                            "deviceUuidList": args.group_macs
                        },
                        "time": ts
                    }]
                    send_update_command(client, group_id, command)
                else:
                    print("Error: Group color temperature must be between 2700 and 6500K")
        finally:
            client.disconnect()
    elif args.mac:
        # Initialize MQTT client for bulb control
        client = MQTTClient(
            resolved_broker_ip,
            port=args.mqtt_port,
            use_tls=True,
            ca_certs=args.ca_crt,
            certfile=args.server_crt,
            keyfile=args.server_key,
        )
        if not client.connect():
            print("Failed to connect to MQTT broker. Make sure your MQTT broker is running and reachable (see README).")
            return

        try:
            # Handle custom topic/payload first
            if args.topic and args.payload:
                print(f"Publishing custom message...")
                print(f"  Topic: {args.topic}")
                print(f"  Payload: {args.payload}")
                
                success = client.publish(args.topic, args.payload, qos=1)
                if success:
                    print("Custom message sent successfully.")
                else:
                    print("Failed to send custom message.")
                return

            # Handle MQTT commands using the new modular approach
            if args.on:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "switch", "value": "1", "time": ts}]
                send_update_command(client, args.mac, command)

            elif args.off:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "switch", "value": "0", "time": ts}]
                send_update_command(client, args.mac, command)

            elif args.brightness is not None:
                if 0 <= args.brightness <= 100:
                    ts = get_current_epoch_ms()
                    command = [{"dn": args.mac, "type": "brightness", "value": str(args.brightness), "time": ts}]
                    send_update_command(client, args.mac, command)
                else:
                    print("Error: Brightness must be between 0 and 100")

            elif args.color:
                print(f"DEBUG: args.color = {args.color} (type: {type(args.color)})")
                try:
                    r, g, b = args.color
                    r, g, b = int(r), int(g), int(b)
                    if all(0 <= val <= 255 for val in [r, g, b]):
                        color_dec = f"{r:d}:{g:d}:{b:d}"
                        ts = get_current_epoch_ms()
                        commands = [
                            {"dn": args.mac, "type": "color", "value": color_dec, "time": ts}
                        ]
                        send_update_command(client, args.mac, commands)
                    else:
                        print("Error: Color values must be between 0 and 255")
                except ValueError as ve:
                    print(f"Error: Could not convert input to integer for --color: {args.color}. Exception: {ve}")
                except TypeError as te:
                    print(f"TypeError: Bad type in color arguments {args.color}: {te}")

            elif args.color_temp is not None:
                if 0 <= args.color_temp <= 100:
                    ts = get_current_epoch_ms()
                    # This command is a list of two actions
                    commands = [
                        {"dn": args.mac, "type": "colorTemperature", "value": str(args.color_temp), "time": ts},
                        {"dn": args.mac, "type": "switch", "value": "1", "time": ts},
                    ]
                    send_update_command(client, args.mac, commands)
                else:
                    print("Error: Color temperature must be between 0 (2700K) and 100 (6500K)")

            elif args.color_mode is not None:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "colorMode", "value": str(args.color_mode), "time": ts}]
                send_update_command(client, args.mac, command)

            elif args.effect_status is not None:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "effectStatus", "value": str(args.effect_status), "time": ts}]
                send_update_command(client, args.mac, command)

            elif args.upgrade:
                # 1) Stern safety warning
                print("=" * 72)
                print("WARNING: Firmware upgrades are DANGEROUS!")
                print("The file you specify MUST exist and MUST be a compatible ESP RTOS SDK")
                print("application image designed for the 'ota_1' slot at Flash address 0x110000.")
                print("Uploading a standard ESP8266 firmware will likely brick your bulb!")
                print("That is to say, if you upload tasmota.bin here, your bulb will be bricked.")
                print("Use ONLY tested shim images or official Sengled firmware.")
                print("=" * 72)
                input("Press Enter if you are sure, or Ctrl+C to cancel...")
                # 2) Accept file path, not URL
                firmware_path = os.path.expanduser(args.upgrade)
                # 3) Validate file existence
                if not os.path.isfile(firmware_path):
                    print(f"Error: Firmware file '{firmware_path}' does not exist.")
                    return
                firmware_bin = prepare_firmware_bin(args.upgrade)
                if not firmware_bin:
                    return  # Abort if validation or copy fails
                # 4) Set up HTTP server
                preferred_http_port = int(os.environ.get("SENGLED_HTTP_PORT", "80") or 80)
                upgrade_server = _SetupHTTPServer(mqtt_host=args.broker_ip or get_local_ip(), mqtt_port=args.mqtt_port or 1883 , preferred_port=preferred_http_port)

                # Launch the HTTP server to serve the file
                server_started = upgrade_server.start()

                local_ip = get_local_ip()
                http_port = str(upgrade_server.port)
                firmware_filename = os.path.basename(firmware_path)
                firmware_url = f"http://{local_ip}:{http_port}/{firmware_filename}"
                print(f"Firmware will be served at: {firmware_url} - let's get that started.")

                print("")
                print("\"This is your last chance. After this, there is no turning back.")
                print("You take the blue pill – the story ends, you wake up in your bed and")
                print(" believe whatever you want to believe.")
                print("You take the red pill – you stay in Wonderland, and I show you how deep")
                print(" the rabbit hole goes.")
                print("Remember, all I'm offering is the truth – nothing more.\"")
                print("― Morpheus")
                print("After upload, there is no going back to Sengled. THIS IS YOUR LAST CHANCE.")
                input("Press Enter if you're ready to send the update, or Ctrl+C to cancel...")
                # 5) Issue MQTT update command with URL
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "update", "value": firmware_url, "time": ts}]
                send_update_command(client, args.mac, command)
                print("Upgrade command sent! If you uploaded a standard shim, look for WiFi SSID")
                print("called Sengled-Rescue. Connect to it, and browse to http://192.168.4.1 to")
                print("finish uploading your third-party firmware.")
                print("")
                print("There's no going back now - your bulb only knows the shim firmware now.")
                print("")
                print("Press Ctrl+C after you see your firmware downloaded below, then your")
                print("device should be running the uploaded code.")
                print("")
                print("Look for this message:")
                print("###")
                print("Served firmware file: shim.bin (XXXX bytes)")
                print("###")
                print("")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\nStopping HTTP server...")
                    upgrade_server.stop()
                    print("Server stopped. Good luck!")

            elif args.status:
                get_bulb_status(client, args.mac)

            elif args.reset:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "reset", "value": "1", "time": ts}]
                send_update_command(client, args.mac, command)

            elif args.custom_payload:
                try:
                    # Validate JSON first
                    payload_list = json.loads(args.custom_payload)
                    # Ensure it's a list, as expected by send_update_command
                    if not isinstance(payload_list, list):
                        print("Error: Custom payload must be a JSON array (a list of objects).")
                        return

                    print(f"Sending custom payload: {args.custom_payload}")
                    send_update_command(client, args.mac, payload_list)
                    
                except json.JSONDecodeError:
                    print("Error: Invalid JSON payload for --custom-payload.")
                    return

            elif args.update:
                ts = get_current_epoch_ms()
                command = [{"dn": args.mac, "type": "info", "value": "", "time": ts}]
                send_update_command(client, args.mac, command)

            else:
                print("No command specified. Use --on, --off, --brightness, --color, --color-temp, --reset, or --status")

        finally:
            client.disconnect()
    else:
        # Interactive REPL
        print("Entering interactive mode. Type 'help' for commands.")
        bulbs = load_bulbs()
        if not bulbs:
            print("No bulbs configured. Run --setup-wifi first.")
            return
        
        target_mac = list(bulbs.keys())[0]
        print(f"Controlling bulb: {target_mac}")
        
        # Establish persistent MQTT connection for REPL
        broker_ip = get_bulb_broker(target_mac)
        if not broker_ip:
            print(f"Broker IP for bulb {target_mac} not found. Please run setup first.")
            return
            
        client = MQTTClient(
            broker_ip,
            port=args.mqtt_port if hasattr(args, 'mqtt_port') else 1883,
            use_tls=True,
            ca_certs=args.ca_crt if hasattr(args, 'ca_crt') else None,
            certfile=args.server_crt if hasattr(args, 'server_crt') else None,
            keyfile=args.server_key if hasattr(args, 'server_key') else None,
        )
        if not client.connect():
            print("Failed to connect to MQTT broker. Make sure your MQTT broker is running and reachable (see README). Exiting.")
            return
            
        print("Connected to MQTT broker. Commands will now wait for bulb responses.")

        try:
            while True:
                try:
                    cmd_input = input(f"({target_mac})> ").strip().lower()
                    if not cmd_input:
                        continue
                    
                    parts = cmd_input.split()
                    command = parts[0]

                    if command in ["quit", "exit"]:
                        break
                    elif command == "help":
                        print("Commands: on, off, toggle, brightness <0-100>, color <r g b>, color-temp <2700-6500>, color-mode <1|2>, effect-status <0|7|100|101>, reset, mac <mac>, quit")
                    elif command == "mac":
                        if len(parts) > 1:
                            if parts[1] in bulbs:
                                target_mac = parts[1]
                                print(f"Switched to bulb: {target_mac}")
                                # Reconnect for new bulb
                                client.disconnect()
                                broker_ip = get_bulb_broker(target_mac)
                                if broker_ip:
                                    client = MQTTClient(broker_ip, port=1883, use_tls=True)
                                    if not client.connect():
                                        print("Failed to connect to new bulb's broker. Make sure your MQTT broker is running and reachable (see README).")
                                        return
                                else:
                                    print(f"Broker IP for bulb {target_mac} not found.")
                                    return
                            else:
                                print("Unknown MAC address.")
                        else:
                            print(f"Current bulb: {target_mac}. Known bulbs: {list(bulbs.keys())}")
                    elif command == "on":
                        ts = get_current_epoch_ms()
                        command_data = [{"dn": target_mac, "type": "switch", "value": "1", "time": ts}]
                        send_update_command(client, target_mac, command_data)
                    elif command == "off":
                        ts = get_current_epoch_ms()
                        command_data = [{"dn": target_mac, "type": "switch", "value": "0", "time": ts}]
                        send_update_command(client, target_mac, command_data)
                    elif command == "toggle":
                        # Note: toggle logic is now simplified; we don't track state here
                        print("Toggle command is not stateful. Sending ON/OFF might be more reliable.")
                    elif command == "brightness":
                        if len(parts) > 1:
                            try:
                                brightness = int(parts[1])
                                if 0 <= brightness <= 100:
                                    ts = get_current_epoch_ms()
                                    command_data = [{"dn": target_mac, "type": "brightness", "value": str(brightness), "time": ts}]
                                    send_update_command(client, target_mac, command_data)
                                else:
                                    print("Brightness must be between 0 and 100")
                            except ValueError:
                                print("Usage: brightness <0-100>")
                        else:
                            print("Usage: brightness <0-100>")
                    elif command == "color":
                        if len(parts) == 4:
                            try:
                                r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                                if all(0 <= val <= 255 for val in [r, g, b]):
                                    color_dec = f"{r:d}:{g:d}:{b:d}"
                                    ts = get_current_epoch_ms()
                                    command_data = [{"dn": target_mac, "type": "color", "value": color_dec, "time": ts}]
                                    send_update_command(client, target_mac, command_data)
                                else:
                                    print("Color values must be between 0 and 255")
                            except ValueError:
                                print("Usage: color <r> <g> <b>")
                        else:
                            print("Usage: color <r> <g> <b>")
                    elif command == "color-temp":
                        if len(parts) > 1:
                            try:
                                temp = int(parts[1])
                                if 2700 <= temp <= 6500:
                                    ts = get_current_epoch_ms()
                                    command_data = [{"dn": target_mac, "type": "colorTemperature", "value": str(temp), "time": ts}]
                                    send_update_command(client, target_mac, command_data)
                                else:
                                    print("Color temperature must be between 2700 and 6500K")
                            except ValueError:
                                print("Usage: color-temp <2700-6500>")
                        else:
                            print("Usage: color-temp <2700-6500>")
                    elif command == "color-mode":
                        if len(parts) > 1:
                            try:
                                mode = int(parts[1])
                                if mode in [1, 2]:
                                    ts = get_current_epoch_ms()
                                    command_data = [{"dn": target_mac, "type": "colorMode", "value": str(mode), "time": ts}]
                                    send_update_command(client, target_mac, command_data)
                                else:
                                    print("Color mode must be 1 (RGB) or 2 (white/temperature)")
                            except ValueError:
                                print("Usage: color-mode <1|2>")
                        else:
                            print("Usage: color-mode <1|2>")
                    elif command == "effect-status":
                        if len(parts) > 1:
                            try:
                                status = int(parts[1])
                                if status in [0, 7, 100, 101]:
                                    ts = get_current_epoch_ms()
                                    command_data = [{"dn": target_mac, "type": "effectStatus", "value": str(status), "time": ts}]
                                    send_update_command(client, target_mac, command_data)
                                else:
                                    print("Effect status must be 0 (off), 7 (audio sync), 100 (video sync), or 101 (game sync)")
                            except ValueError:
                                print("Usage: effect-status <0|7|100|101>")
                        else:
                            print("Usage: effect-status <0|7|100|101>")
                    elif command == "reset":
                        ts = get_current_epoch_ms()
                        command_data = [{"dn": target_mac, "type": "reset", "value": "1", "time": ts}]
                        send_update_command(client, target_mac, command_data)
                    else:
                        print(f"Unknown command: {command}")

                except (KeyboardInterrupt, EOFError):
                    break
        finally:
            client.disconnect()
        print("\nExiting interactive mode.")

if __name__ == "__main__":
    main()
