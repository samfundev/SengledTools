#!/usr/bin/env python3
"""
Fake Sengled HTTP Server
Simulates the Sengled cloud endpoints for local testing.
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import json
import logging
import argparse
import sys

from utils import get_local_ip

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

BROKER_HOST = get_local_ip()

class SengledRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        client_ip = self.client_address[0]
        logging.info(f"🌐 POST {self.path} from {client_ip}")
        logging.info(f"📦 Request Body: {post_data}")
        
        parsed_url = urlparse(self.path)

        if  parsed_url.path == "/jbalancer/new/bimqtt":
            response = {
                "protocal": "mqtt",
                "host": BROKER_HOST,
                "port": 1883
            }
            logging.info(f"📤 Response: {json.dumps(response, indent=2)}")
            self._send_json_response(response)
            
        elif parsed_url.path == "/life2/device/accessCloud.json":
            try:
                request_data = json.loads(post_data)
                device_uuid = request_data.get("deviceUuid", "")
                
                response = {
                    "messageCode": "200",
                    "info": "OK",
                    "description": "正常",
                    "success": True
                }
                logging.info(f"📤 Response: {json.dumps(response, indent=2)}")
                self._send_json_response(response)
            except json.JSONDecodeError:
                logging.error(f"❌ Invalid JSON: {post_data}")
                self.send_error(400, "Invalid JSON in request")
            
        else:
            logging.warning(f"❌ 404 Not Found: {self.path}")
            self.send_error(404, "Not Found")
    
    def do_GET(self):
        client_ip = self.client_address[0]
        logging.info(f"🌐 GET {self.path} from {client_ip}")
        
        parsed_url = urlparse(self.path)

        if parsed_url.path == "/jbalancer/new/bimqtt":
            response = {
                "protocal": "mqtt",
                "host": BROKER_HOST,
                "port": 1883
            }
            logging.info(f"📤 Response: {json.dumps(response, indent=2)}")
            self._send_json_response(response)
        else:
            logging.warning(f"❌ 404 Not Found: {self.path}")
            self.send_error(404, "Not Found")
    
    def _send_json_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps(data).encode('utf-8')
        self.wfile.write(response)

def run_server(port=80, broker_host=None):
    global BROKER_HOST
    if broker_host:
        BROKER_HOST = broker_host
    logging.info(f"Using broker host: {BROKER_HOST}")

    try:
        server = HTTPServer(('', port), SengledRequestHandler)
        logging.info(f"Starting fake Sengled server on port {port}")
        logging.info("Endpoints available:")
        logging.info("  - POST /jbalancer/new/bimqtt")
        logging.info("  - POST /life2/device/accessCloud.json")
        server.serve_forever()
    except PermissionError:
        # Try a non-privileged port on Windows
        alt_port = 8080
        logging.warning(f"Failed to bind to port {port}. Trying alternate port {alt_port}...")
        logging.warning("NOTE: You'll need to update the port in sengled_tool.py setup URLs!")
        server = HTTPServer(('', alt_port), SengledRequestHandler)
        logging.info(f"Server started on port {alt_port}")
        server.serve_forever()
    except Exception as e:
        logging.error(f"Server error: {e}")

if __name__ == "__main__":
    # Check if we're on Windows
    if sys.platform == 'win32':
        logging.warning("Running on Windows:")
        logging.warning("1. Run Command Prompt as Administrator")
        logging.warning("2. Or server will fallback to port 8080")

    parser = argparse.ArgumentParser(description="Fake Sengled HTTP server")
    parser.add_argument("--http-port", type=int, default=80, help="HTTP port to bind (default: 80; falls back to 8080 on permission error)")
    parser.add_argument("--broker-ip", type=str, help="MQTT broker IP to return from /jbalancer/new/bimqtt (default: this machine's local IP)")
    args = parser.parse_args()

    chosen_broker = args.broker_ip or get_local_ip()
    run_server(port=args.http_port, broker_host=chosen_broker)