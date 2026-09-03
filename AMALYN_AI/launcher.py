# launcher.py — AMALYN TECH One-Click Launcher
import subprocess
import sys
import os
import time
import webbrowser
import threading

def open_dashboard():
    time.sleep(3)
    dashboard = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    webbrowser.open(f'file:///{dashboard}')
    print("[LAUNCHER] Dashboard opened in browser")

def main():
    print("\n" + "="*50)
    print("   AMALYN TECH — Starting...")
    print("="*50)

    # Open dashboard after delay
    threading.Thread(target=open_dashboard, daemon=True).start()

    # Start the API
    api_path = os.path.join(os.path.dirname(__file__), 'api.py')
    subprocess.run([sys.executable, api_path])

if __name__ == "__main__":
    main()