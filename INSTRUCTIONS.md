# Instructions

This document expands on setup and usage. Refer to the reference files for protocol details:

* MQTT command reference: [MQTT\_COMMANDS\_REFERENCE.md](MQTT_COMMANDS_REFERENCE.md)
* UDP command reference: [UDP\_COMMANDS\_REFERENCE.md](UDP_COMMANDS_REFERENCE.md)

## Prerequisites

* Install Python 3.10+ and dependencies:

```
pip install -r requirements.txt
```

* Install an MQTT broker ([Mosquitto download link](https://mosquitto.org/download/)) reachable from the bulb.
* Connect your computer to the bulb AP `Sengled_Wi‑Fi Bulb_XXXXXX` before pairing.

## Broker setup (TLS required)

The bulb requires an MQTT broker that accepts TLS connections.

### Example broker: Mosquitto

1. Download and install Mosquitto from the [official site](https://mosquitto.org/download/).
2. Install OpenSSL ([Windows builds here](https://slproweb.com/products/Win32OpenSSL.html)).
3. Generate a self‑signed TLS certificate:

```
# Create a local CA
"C:\Program Files\OpenSSL-Win64\bin\openssl.exe" genrsa -out ca.key 2048
"C:\Program Files\OpenSSL-Win64\bin\openssl.exe" req -x509 -new -key ca.key -days 3650 -out ca.crt -subj "/CN=Local-CA"

# Create server key + CSR (use any descriptive CN, e.g., broker.local)
"C:\Program Files\OpenSSL-Win64\bin\openssl.exe" genrsa -out server.key 2048
"C:\Program Files\OpenSSL-Win64\bin\openssl.exe" req -new -key server.key -out server.csr -subj "/CN=broker.local"

# Sign server cert
"C:\Program Files\OpenSSL-Win64\bin\openssl.exe" x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256
```

4. Place the `mosquitto.conf` configuration file from this repo in the same directory as your generated certificate and key files (`ca.crt`, `server.crt`, `server.key`), adjusting file names if you used different names during certificate generation.
5. Start Mosquitto with the bundled config:

   * Windows (PowerShell):

     ```
     # Ideally cd to the project root first
     "C:\Program Files\mosquitto\mosquitto.exe" -c .\mosquitto.conf -v
     ```
   * Linux/macOS:

     ```
     mosquitto -c ./mosquitto.conf -v
     ```

## Wi‑Fi pairing (quick)

* Interactive:
  In interactive mode, the bulb will return a list of surrounding Wi‑Fi networks (SSIDs) it detects. The script will prompt you to choose which network it should connect to, and you will need to provide the corresponding Wi‑Fi password.
  **Note:** Replace `192.168.0.100` in the examples with the local IP address of the device running the broker (most likely your PC).

```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100
```

* Non‑interactive:

```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100 --ssid "YourSSID" --password "YourWifiPassword"
```

The tool starts an embedded HTTP server, waits for the bulb to call `/life2/device/accessCloud.json` and `/jbalancer/new/bimqtt`, then (if it detects the bulb’s LAN IP) attempts a UDP ON/OFF test and prints follow‑up command examples.

If ports 80/8080 are busy, the tool assumes you run your own HTTP server and will not wait for endpoint hits or run the UDP test.

## Control (MQTT)

**Note:** Replace `192.168.0.100` with the local IP of the broker host.

```
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --on
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --off
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --brightness 50
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --color 255 0 0
```

## Control (UDP)

```
python sengled_tool.py --ip 192.168.0.247 --udp-on
python sengled_tool.py --ip 192.168.0.247 --udp-off
```

## Notes

* TLS may be required by bulbs; use self‑signed certs if necessary.
* **After power loss, the bulb may need to re‑query the HTTP endpoints. Make sure the broker is running. Once the bulb successfully contacts these endpoints, it will become responsive again because it retrieves the MQTT broker address from them. You can start the embedded HTTP server without re‑pairing by running:**

```
python fake_sengled_server.py
```
