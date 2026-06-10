# simulator.py — AMALYN Mixer Simulator
# Pretends to be a real mixer receiving OSC commands
# Run this in a separate terminal to test mixer integration

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from datetime import datetime

print("\n" + "=" * 50)
print("   AMALYN TECH -- Mixer Simulator")
print("   Listening on port 9000")
print("   Waiting for corrections from AMALYN...")
print("=" * 50 + "\n")


def handle_eq_gain(address, *args):
    parts = address.split('/')
    channel = parts[2] if len(parts) > 2 else '?'
    band = parts[4] if len(parts) > 4 else '?'
    value = args[0] if args else 0
    time = datetime.now().strftime('%H:%M:%S')
    print(f"[{time}] EQ GAIN   | Ch:{channel} Band:{band} | {value:+.1f}dB")


def handle_eq_freq(address, *args):
    parts = address.split('/')
    channel = parts[2] if len(parts) > 2 else '?'
    band = parts[4] if len(parts) > 4 else '?'
    value = args[0] if args else 0
    time = datetime.now().strftime('%H:%M:%S')
    print(f"[{time}] EQ FREQ   | Ch:{channel} Band:{band} | {value:.1f}Hz")


def handle_eq_q(address, *args):
    parts = address.split('/')
    channel = parts[2] if len(parts) > 2 else '?'
    band = parts[4] if len(parts) > 4 else '?'
    value = args[0] if args else 0
    time = datetime.now().strftime('%H:%M:%S')
    print(f"[{time}] EQ Q      | Ch:{channel} Band:{band} | Q:{value}")


def handle_default(address, *args):
    time = datetime.now().strftime('%H:%M:%S')
    print(f"[{time}] OSC MSG   | {address} | {args}")


dispatcher = Dispatcher()
dispatcher.map("/ch/*/eq/*/g", handle_eq_gain)
dispatcher.map("/ch/*/eq/*/f", handle_eq_freq)
dispatcher.map("/ch/*/eq/*/q", handle_eq_q)
dispatcher.set_default_handler(handle_default)

server = BlockingOSCUDPServer(("127.0.0.1", 9000), dispatcher)

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\n\n--- Simulator stopped ---\n")