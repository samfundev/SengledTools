# Sengled Bulb UDP Command Reference

## **How to Send UDP Commands**

### **Using `extras/udp_commander.py` (Recommended)**
```bash
# Basic syntax
python extras/udp_commander.py --ip <BULB_IP> <COMMAND> [PARAMETERS]

# Examples
python extras/udp_commander.py --ip 192.168.8.1 set_device_switch --switch 1
python extras/udp_commander.py --ip 192.168.8.1 set_device_brightness --brightness 50
python extras/udp_commander.py --ip 192.168.8.1 get_device_info
```

### **Using `sengled_tool.py`**
```bash
# Basic syntax
python sengled_tool.py --ip <BULB_IP> --udp-<COMMAND> [PARAMETERS]

# Examples
python sengled_tool.py --ip 192.168.8.1 --udp-on
python sengled_tool.py --ip 192.168.8.1 --udp-off
python sengled_tool.py --ip 192.168.8.1 --udp-brightness 50
python sengled_tool.py --ip 192.168.8.1 --udp-color 255 0 0
```

### **Custom JSON Payload**
```bash
python extras/udp_commander.py --ip 192.168.8.1 --payload '{"func":"set_device_switch","param":{"switch":1}}'
```

### **Test All Commands**
```bash
python extras/udp_commander.py --ip 192.168.8.1 --tryall
```

---

## **Available Commands**

| **Command** | **Tool Syntax** | **Parameters** | **Example** |
|-------------|-----------------|----------------|-------------|
| **Power Control** |
| `set_device_switch` | `set_device_switch --switch 1\|0` | `switch`: 0=off, 1=on | `set_device_switch --switch 1` |
| **Brightness Control** |
| `set_device_brightness` | `set_device_brightness --brightness 0-100` | `brightness`: 0-100 | `set_device_brightness --brightness 50` |
| **Color Control** |
| `set_device_color` | `--udp-color R G B` | `color`: RGB hex string | `--udp-color 255 0 0` |
| **Device Info** |
| `get_device_info` | `get_device_info` | None | `get_device_info` |
| `get_brightness` | `get_brightness` | None | `get_brightness` |
| `get_power` | `get_power` | None | `get_power` |
| `get_device_runtime_info` | `get_device_runtime_info` | None | `get_device_runtime_info` |
| **Advanced Control** |
| `set_device_info` | `set_device_info --onoff 1\|0 --brightness 0-100` | `onoff`, `brightness` | `set_device_info --onoff 1 --brightness 75` |
| `set_param` | `set_param --key <key> --value <value>` | `key`, `value` | `set_param --key power --value 1` |
| `get_param` | `get_param --key <key>` | `key` | `get_param --key brightness` |
| `set_config` | `set_config --config '{"onoff":1,"brightness":50}'` | `config`: JSON string | `set_config --config '{"onoff":1,"brightness":50}'` |
| `set_timer` | `set_timer --timers '[{"on":1,"time":"22:00","repeat":127}]'` | `timers`: JSON string | `set_timer --timers '[{"on":1,"time":"22:00","repeat":127}]'` |

---

## **Command Payloads & Responses**

| **Command** | **Request Payload** | **Response Payload** |
|-------------|-------------------|-------------------|
| `set_device_switch` | `{"func":"set_device_switch","param":{"switch":1}}` | `{"func":"set_device_switch","result":{"ret":0,"msg":"success"}}` |
| `set_device_brightness` | `{"func":"set_device_brightness","param":{"brightness":50}}` | `{"func":"set_device_brightness","result":{"ret":0,"msg":"success"}}` |
| `set_device_color` | `{"func":"set_device_color","param":{"color":"FF0000"}}` | `{"func":"set_device_color","result":{"ret":0,"msg":"success"}}` |
| `get_device_info` | `{"func":"get_device_info","param":{}}` | `{"func":"get_device_info","result":{"ret":0,"onoff":1,"brightness":100,"mode":1,"rssi":-41}}` |
| `get_brightness` | `{"func":"get_brightness","param":{}}` | `{"func":"get_brightness","result":{"ret":0,"value":50}}` |
| `get_power` | `{"func":"get_power","param":{}}` | `{"func":"get_power","result":{"ret":0,"power":1}}` |
| `get_device_runtime_info` | `{"func":"get_device_runtime_info","param":{}}` | `{"func":"get_device_runtime_info","result":{"ret":0,"onoff":1,"power":0.0,"energy":23.9,"voltage":227.9,"current":0.07}}` |

---

## **Quick Examples**

### **Power Control**
```bash
# Turn on
python udp_commander.py --ip 192.168.8.1 set_device_switch --switch 1

# Turn off  
python udp_commander.py --ip 192.168.8.1 set_device_switch --switch 0

# Using sengled_tool.py
python sengled_tool.py --ip 192.168.8.1 --udp-on
python sengled_tool.py --ip 192.168.8.1 --udp-off
```

### **Brightness Control**
```bash
# Set brightness to 50%
python udp_commander.py --ip 192.168.8.1 set_device_brightness --brightness 50

# Using sengled_tool.py
python sengled_tool.py --ip 192.168.8.1 --udp-brightness 50
```

### **Color Control**
```bash
# Set to red (255, 0, 0)
python sengled_tool.py --ip 192.168.8.1 --udp-color 255 0 0

# Set to green (0, 255, 0)  
python sengled_tool.py --ip 192.168.8.1 --udp-color 0 255 0

# Set to blue (0, 0, 255)
python sengled_tool.py --ip 192.168.8.1 --udp-color 0 0 255
```

### **Device Status**
```bash
# Get device info
python udp_commander.py --ip 192.168.8.1 get_device_info

# Get brightness
python udp_commander.py --ip 192.168.8.1 get_brightness

# Get power status
python udp_commander.py --ip 192.168.8.1 get_power
```

### **Advanced Commands**
```bash
# Set both power and brightness
python udp_commander.py --ip 192.168.8.1 set_device_info --onoff 1 --brightness 75

# Set custom parameter
python udp_commander.py --ip 192.168.8.1 set_param --key power --value 1

# Get custom parameter
python udp_commander.py --ip 192.168.8.1 get_param --key brightness

# Set timer (turn on at 10 PM daily)
python udp_commander.py --ip 192.168.8.1 set_timer --timers '[{"on":1,"time":"22:00","repeat":127}]'
```

---

## **Notes**

- **Default IP**: `192.168.8.1` (bulb's AP mode IP)
- **Port**: `9080` (UDP)
- **Timeout**: 3 seconds (configurable with `--timeout`)
- **Color values**: RGB 0-255 for each component
- **Brightness**: 0-100 percentage
- **Power**: 0=off, 1=on

**Pro tip**: Use `--tryall` to test which commands work with your specific bulb model!
