"""Local OSC mixer simulator used to test AMALYN corrections."""

from datetime import datetime


def _address_parts(address):
    parts = address.split("/")
    return parts[2] if len(parts) > 2 else "?", parts[4] if len(parts) > 4 else "?"


def main():
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import BlockingOSCUDPServer

    def handle_eq_gain(address, *args):
        channel, band = _address_parts(address)
        value = args[0] if args else 0
        print(f"[{datetime.now():%H:%M:%S}] EQ GAIN | Ch:{channel} Band:{band} | {value:+.1f}dB")

    def handle_eq_frequency(address, *args):
        channel, band = _address_parts(address)
        value = args[0] if args else 0
        print(f"[{datetime.now():%H:%M:%S}] EQ FREQ | Ch:{channel} Band:{band} | {value:.1f}Hz")

    def handle_eq_q(address, *args):
        channel, band = _address_parts(address)
        value = args[0] if args else 0
        print(f"[{datetime.now():%H:%M:%S}] EQ Q | Ch:{channel} Band:{band} | Q:{value}")

    def handle_default(address, *args):
        print(f"[{datetime.now():%H:%M:%S}] OSC MSG | {address} | {args}")

    dispatcher = Dispatcher()
    dispatcher.map("/ch/*/eq/*/g", handle_eq_gain)
    dispatcher.map("/ch/*/eq/*/f", handle_eq_frequency)
    dispatcher.map("/ch/*/eq/*/q", handle_eq_q)
    dispatcher.set_default_handler(handle_default)
    server = BlockingOSCUDPServer(("127.0.0.1", 9000), dispatcher)

    print("AMALYN TECH Mixer Simulator listening on port 9000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSimulator stopped.")


if __name__ == "__main__":
    main()
