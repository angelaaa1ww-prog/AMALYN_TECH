import subprocess
import sys
import os
import time
import webbrowser
import threading
import urllib.request

BASE = os.path.dirname(__file__)

def open_login():
    url = 'http://localhost:8000/'
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + 'health', timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    print("[LAUNCHER] AMALYN Login Portal opened at " + url)
                    return
        except Exception:
            time.sleep(0.5)
    print("[LAUNCHER] AMALYN did not become ready; open " + url + " manually")

def main():
    print("\n" + "="*50)
    print("   AMALYN TECH — Starting...")
    print("="*50)
    threading.Thread(target=open_login, daemon=True).start()
    api_path = os.path.join(BASE, 'api.py')
    subprocess.run([sys.executable, api_path])

if __name__ == "__main__":
    main()