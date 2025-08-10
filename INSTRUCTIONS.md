# Instructions

This document expands on setup and usage. Refer to the reference files for protocol details:

- MQTT command reference: [MQTT_COMMANDS_REFERENCE.md](MQTT_COMMANDS_REFERENCE.md)
- UDP command reference: [UDP_COMMANDS_REFERENCE.md](UDP_COMMANDS_REFERENCE.md)

## Prerequisites
- Install Python 3.10+ and dependencies:
```
pip install -r requirements.txt
```
- Install an MQTT broker (Mosquitto recommended) reachable from the bulb. TLS is required by most bulbs; this tool assumes TLS.
  - Download Mosquitto and place `mosquitto.conf` from this repo next to `ca.crt`, `server.crt`, `server.key`.
  - Start Mosquitto with the bundled config:
    - Windows (PowerShell): `mosquitto.exe -c .\mosquitto.conf -v`
    - Linux/macOS: `mosquitto -c ./mosquitto.conf -v`
  - TLS certificate generation (OpenSSL quickstart):
    ```
    # Create a local CA
    openssl genrsa -out ca.key 2048
    openssl req -x509 -new -key ca.key -days 3650 -out ca.crt -subj "/CN=Local-CA"

    # Create server key + CSR (use your broker IP as CN)
    set BROKER_IP=192.168.0.100
    openssl genrsa -out server.key 2048
    openssl req -new -key server.key -out server.csr -subj "/CN=%BROKER_IP%"

    # Sign server cert
    openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 3650 -sha256
    ```
- Connect your computer to the bulb AP `Sengled_Wi‑Fi Bulb_XXXXXX` before pairing

## Start a broker (Windows example)
```
mosquitto.exe -c path\to\mosquitto.conf -v
```

## Wi‑Fi pairing (quick)
- Interactive
```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100
```
- Non‑interactive
```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100 --ssid "YourSSID" --password "YourWifiPassword"
```

The tool starts an embedded HTTP server, waits for the bulb to call `/life2/device/accessCloud.json` and `/jbalancer/new/bimqtt`, then (if it detects the bulb’s LAN IP) attempts a UDP ON/OFF test and prints follow‑up command examples.

If ports 80/8080 are busy, the tool assumes you run your own HTTP server and will not wait for endpoint hits or run the UDP test.

## Control (MQTT)
Examples:
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
- TLS may be required by bulbs; use self‑signed certs if necessary
- After power loss, bulb may need to re‑query the HTTP endpoints; make sure the broker is running and, if needed, re‑run pairing to bring up the embedded HTTP server
- Factory reset: rapid power toggle ~5–10 times, then connect to `Sengled_Wi‑Fi_Bulb_...`

### .gitignore (create this in the repo root)
```
# local artifacts
__pycache__/
*.pyc
*.pyo
*.pyd
*.log

# certs/keys (do NOT push)
*.crt
*.key
*.csr
*.srl

# local-only tools
extras/
```

- Optional: sanitize `mosquitto.conf` before pushing (replace your absolute paths with relative):
```
cafile ca.crt
certfile server.crt
keyfile server.key
```

### Init, commit, push to shazamza/sengled_tools
```powershell
<code_block_to_apply_changes_from>
cd C:\Users\Hamza\Desktop\TMP\SengledTools

git init
# create .gitignore with the content above before add
git add .
git commit -m "initial commit"
git branch -M main

# ensure remote is set to account B repo
git remote remove origin 2>$null
git remote add origin https://github.com/shazamza/sengled_tools.git

# clear cached creds for account A if needed (Windows Credential Manager)
# or: git credential-manager reject https://github.com

git push -u origin main
# Username: shazamza
# Password: <Personal Access Token from account B>
```

- Repo already created on GitHub is fine; don’t delete it. Just set the remote and push as above.

