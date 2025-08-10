# Sengled WiFi Bulb Local Control / Setup Tool

A small reverse‑engineering and local‑control toolkit for Sengled Wi‑Fi bulbs. It pairs bulbs to your own MQTT broker (no cloud), provides UDP control, and includes an optional (untested) firmware‑upgrade publish.

A comprehensive tool for local control and protocol research of Sengled Wi‑Fi bulbs. It can pair bulbs to your own MQTT broker (no cloud), provides UDP control, and optionally publishes a firmware URL for advanced users (e.g., Tasmota/ESPHome) for testing on your own devices.

## Quick usage (current flow)

For a fuller, step‑by‑step guide, see [Instructions](INSTRUCTIONS.md).

The tool can perform Wi‑Fi pairing and basic UDP control. The HTTP server used during pairing is now embedded and auto‑managed by the tool.

### Install

* Python 3.10+ recommended
* Install dependencies:

```
pip install -r requirements.txt
```

### Wi‑Fi pairing steps

1. Start your MQTT broker (e.g., Mosquitto). See more information and examples in [INSTRUCTIONS.md](INSTRUCTIONS.md).

   * Windows example:

     ```
     mosquitto.exe -c path\to\mosquitto.conf -v
     ```
2. Factory reset the bulb to enter AP mode.

   * Rapidly toggle power 5–10 times until it broadcasts `Sengled_Wi‑Fi_Bulb_...`.
3. Connect your computer to the bulb’s AP: `Sengled_Wi‑Fi_Bulb_...`.
4. Run the Wi‑Fi setup:

   * Interactive:

     ```
     python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100
     ```
   * Non‑interactive:

     ```
     python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100 --ssid "YourSSID" --password "YourWifiPassword"
     ```
5. If the embedded HTTP server can’t bind to 80/8080, stop whatever is on those ports or set `SENGLED_HTTP_PORT`.
6. The bulb will hit:

   * `POST/GET /life2/device/accessCloud.json`
   * `POST/GET /jbalancer/new/bimqtt`
     Then it connects to your MQTT broker.

### Interactive Wi‑Fi setup (prompts for SSID/password)

```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100
```

### Non‑interactive Wi‑Fi setup

```
python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100 --ssid "YourSSID" --password "YourWifiPassword"
```

What happens:

* The tool starts a local HTTP server automatically on port 80 (falls back to 8080 if needed; override with env `SENGLED_HTTP_PORT`).
* It performs the Wi‑Fi setup handshake with the bulb and sends config that points to your MQTT broker.
* It waits until the bulb hits both endpoints, then shuts down the HTTP server automatically:

  * `POST/GET /life2/device/accessCloud.json` (returns success JSON)
  * `POST/GET /jbalancer/new/bimqtt` (returns `{ protocal: "mqtt", host: <broker-ip>, port: 1883 }`)
* After that, it blinks the bulb via UDP (ON → 3s → OFF) as a quick success indicator.

### MQTT control (via broker)

Use these after the bulb is paired and connected to your broker.

```
# Turn on
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --on

# Turn off
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --off

# Set brightness (0-100)
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --brightness 50

# Set color (R G B; 0-255 each)
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --color 255 0 0

# Set color temperature (2700-6500K)
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --color-temp 3000

# Query status
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --status

# Factory reset
python sengled_tool.py --mac E8:DB:8A:AA:BB:CC --reset

# Custom payload (JSON array of command objects)
# Example: turn on via raw publish
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC \
  --custom-payload "[{\"dn\":\"E8:DB:8A:AA:BB:CC\",\"type\":\"switch\",\"value\":\"1\",\"time\":1690000000000}]"

# Custom publish (raw topic/payload)
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC \
  --topic wifielement/E8:DB:8A:AA:BB:CC/update \
  --payload "[{\"dn\":\"E8:DB:8A:AA:BB:CC\",\"type\":\"switch\",\"value\":\"1\",\"time\":1690000000000}]"

# Firmware upgrade (untested)
# Topic requires raw URL string (not JSON). This path is inferred from logs and code, but not validated end-to-end.
python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC \
  --topic wifibulb/E8:DB:8A:AA:BB:CC/update \
  --payload "http://192.168.0.100/firmware.bin"

# Group control (example: switch ON for a list of MACs)
python sengled_tool.py --broker-ip 192.168.0.100 \
  --group-macs E8:DB:8A:AA:BB:CC E8:DB:8A:11:22:33 \
  --group-switch on
```

### UDP control (direct local commands)

```
# Turn on
python sengled_tool.py --ip 192.168.8.1 --udp-on

# Turn off
python sengled_tool.py --ip 192.168.8.1 --udp-off

# Set brightness (0-100)
python sengled_tool.py --ip 192.168.8.1 --udp-brightness 50

# Set color (R G B; 0-255 each)
python sengled_tool.py --ip 192.168.8.1 --udp-color 255 0 0
```

Note: UDP control does not require the MQTT broker or HTTP setup server once the bulb is paired and on your LAN.

<!-- Broker setup details moved to INSTRUCTIONS.md -->

Power loss behavior:

* After a power cycle, some bulbs re‑query the HTTP endpoints (`/life2/device/accessCloud.json` and `/jbalancer/new/bimqtt`) to fetch MQTT settings before connecting. Make sure your MQTT broker is already running. If the bulb doesn’t reconnect, re‑run Wi‑Fi setup to spin up the embedded HTTP server again so the endpoints are reachable.

<!-- TLS/SSL details moved to INSTRUCTIONS.md -->

### Troubleshooting quick actions

* Factory reset options:

  * Hardware: rapidly toggle power 5–10 times until the bulb flashes and broadcasts `Sengled_Wi‑Fi Bulb_XXXXXX`.
  * Software: if the bulb is online on your broker, you can send a reset:

    ```
    python sengled_tool.py --broker-ip 192.168.0.100 --mac E8:DB:8A:AA:BB:CC --reset
    ```
* Ensure broker is running (Windows example):

  ```
  mosquitto.exe -c path\to\mosquitto.conf -v
  ```
* If the bulb isn’t reconnecting to your broker after power loss/reset:

  * Re‑run pairing to bring up the embedded HTTP server:

    ```
    python sengled_tool.py --setup-wifi --broker-ip 192.168.0.100
    ```
  * Or run a minimal local HTTP server that serves the two endpoints expected by the bulb:

    ```
    python fake_sengled_server.py
    ```

    This attempts port 80 and falls back to 8080. If you use a non‑default port, ensure pairing pointed the bulb to that port.

<!-- Mosquitto start example moved to INSTRUCTIONS.md -->

---

## FAQ

* How do I use this with Home Assistant?

  * This repo contains the protocol details (MQTT topics/payloads and UDP commands) that enable creating a Home Assistant integration. It does not include one.

* Will this make my bulbs work with Google Home?

  * If a bulb was already paired with Sengled cloud, it should continue to work with Google Home as before. You can still control it locally via UDP.
  * Bulbs newly paired with this tool are redirected to your local broker and do not register with Sengled cloud; they will not work with the official Sengled Google Home integration.

* I don’t use Home Assistant. Can I still control bulbs?

  * Yes, but you’ll need a custom solution unless someone publishes an integration. Options: a small Android app, a simple script/service on a PC or server triggered by your phone (shortcuts/webhooks), or any automation that publishes the documented MQTT or UDP commands.
