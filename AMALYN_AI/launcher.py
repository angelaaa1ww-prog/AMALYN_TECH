import subprocess
import sys
import os
import time
import webbrowser
import threading

BASE = os.path.dirname(__file__)

def open_login():
    time.sleep(3)
    webbrowser.open('http://localhost:8000/')
    print("[LAUNCHER] AMALYN Login Portal opened at http://localhost:8000/")

def main():
    print("\n" + "="*50)
    print("   AMALYN TECH — Starting...")
    print("="*50)
    threading.Thread(target=open_login, daemon=True).start()
    api_path = os.path.join(BASE, 'api.py')
    subprocess.run([sys.executable, api_path])

if __name__ == "__main__":
    main()