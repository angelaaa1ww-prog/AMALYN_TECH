# discovery.py — AMALYN Auto Mixer Discovery
# Scans the local network and finds all supported mixers automatically

import socket
import json
import os
import threading
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed
from mixer import MIXER_PROFILES

PROFILES_PATH = os.path.join(os.path.dirname(__file__), 'mixer_profiles.json')

with open(PROFILES_PATH, 'r') as f:
    PROFILES = json.load(f)

# All ports to scan for digital mixers
DIGITAL_PORTS = list(set(
    p['port'] for p in PROFILES['digital'].values()
))


def get_local_network():
    """Detect the local network subnet automatically."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
        network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
        return str(network.network_address).rsplit(".", 1)[0], local_ip
    except OSError as error:
        raise RuntimeError("Could not determine the local network") from error
    finally:
        if sock is not None:
            sock.close()


def probe_host(ip, port, timeout=0.5):
    """Check if a port is open on a host."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def identify_mixer(ip, open_ports):
    """Match open ports to known mixer profiles."""
    found = []
    for key, profile in PROFILES['digital'].items():
        if profile['port'] in open_ports:
            bridge_type = {
                "yamaha_cl5": "yamaha_cl",
                "yamaha_ql": "yamaha_cl",
            }.get(key, key)
            found.append({
                "key": key,
                "brand": profile['brand'],
                "model": profile['model'],
                "ip": ip,
                "port": profile['port'],
                "protocol": profile['protocol'],
                "type": "digital",
                "connectable": bridge_type in MIXER_PROFILES,
                "status": "found"
            })
    return found


def scan_host(ip, ports):
    """Scan a single host for all mixer ports."""
    open_ports = []
    for port in ports:
        if probe_host(ip, port):
            open_ports.append(port)
    if open_ports:
        return identify_mixer(ip, open_ports)
    return []


def scan_network(progress_callback=None, cidr=None):
    """
    Scan the entire local network for mixers.
    Returns list of found mixers.
    Uses threading for speed — scans 254 hosts in parallel.
    """
    subnet, local_ip = get_local_network()
    try:
        network = ipaddress.ip_network(cidr or f"{subnet}.0/24", strict=False)
    except ValueError as error:
        raise ValueError(f"Invalid scan network '{cidr}'") from error
    hosts = [str(host) for host in network.hosts()]
    if len(hosts) > 1024:
        raise ValueError("Scan network is too large; use a network with at most 1024 hosts")
    print(f"[DISCOVERY] Scanning network {network}")
    print(f"[DISCOVERY] Looking for {len(DIGITAL_PORTS)} mixer port types")

    found_mixers = []
    total = len(hosts)
    scanned = 0

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {
            executor.submit(scan_host, ip, DIGITAL_PORTS): ip
            for ip in hosts
        }

        for future in as_completed(futures):
            scanned += 1
            result = future.result()
            if result:
                found_mixers.extend(result)
                for mixer in result:
                    print(f"[DISCOVERY] Found: {mixer['brand']} {mixer['model']} at {mixer['ip']}")

            if progress_callback:
                progress_callback(scanned, total, found_mixers)

    print(f"[DISCOVERY] Scan complete — found {len(found_mixers)} mixer(s)")
    return found_mixers


def get_analog_options():
    """Return all supported analog mixer options."""
    return [
        {
            "key": key,
            "brand": p['brand'],
            "model": p['model'],
            "protocol": p['protocol'],
            "description": p['description'],
            "type": "analog",
            "status": "manual"
        }
        for key, p in PROFILES['analog'].items()
    ]


def get_audio_interfaces():
    """
    List available audio input devices on this machine.
    For analog mixers — user picks which interface to use.
    """
    import pyaudio
    p = pyaudio.PyAudio()
    devices = []
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            devices.append({
                "index": i,
                "name": info['name'],
                "channels": info['maxInputChannels'],
                "sample_rate": int(info['defaultSampleRate'])
            })
    p.terminate()
    return devices