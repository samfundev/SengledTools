import json
import socket
import time
from pathlib import Path
from typing import Dict, Optional

def get_local_ip() -> str:
    """Get the local IP address of this computer."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except OSError:
        return "127.0.0.1"

def get_config_dir() -> Path:
    """Gets the configuration directory for the application."""
    return Path.home() / ".sengled"

def load_bulbs() -> Dict[str, Dict]:
    """Loads bulb information from the configuration file."""
    config_dir = get_config_dir()
    bulbs_file = config_dir / "bulbs.json"
    if not bulbs_file.exists():
        return {}
    with open(bulbs_file, "r") as f:
        return json.load(f)

def save_bulb(mac: str, broker_ip: str):
    """Saves a bulb's MAC address and broker IP to the configuration file."""
    config_dir = get_config_dir()
    config_dir.mkdir(exist_ok=True)
    bulbs_file = config_dir / "bulbs.json"
    bulbs = load_bulbs()
    bulbs[mac] = {"broker": broker_ip}
    with open(bulbs_file, "w") as f:
        json.dump(bulbs, f, indent=2)

def get_bulb_broker(mac: str) -> Optional[str]:
    """Retrieves the broker IP for a given bulb MAC address."""
    bulbs = load_bulbs()
    return bulbs.get(mac, {}).get("broker")

def get_current_epoch_ms() -> int:
    """Returns the current time in milliseconds since the epoch."""
    return int(time.time() * 1000)
