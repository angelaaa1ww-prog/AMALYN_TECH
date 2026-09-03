# AMALYN TECH
### AI-Driven Audio Intelligence & Predictive Monitoring Ecosystem

AMALYN TECH is a modular audio intelligence system that eliminates human error and technical failure in live sound reinforcement and studio production. It acts as a Digital Co-Pilot — analyzing audio signals in real time, predicting feedback before it happens, and pushing corrections directly to the mixer automatically.

---

## What It Does

- **Real-time FFT Analysis** — listens to your room and maps every frequency live
- **AI Feedback Detection** — detects feedback building before it explodes
- **ML Anomaly Detection** — trained neural network catches problems threshold systems miss
- **Auto-EQ Suggestions** — tells you exactly which frequency to cut and by how much
- **Perfect State System** — loads ideal settings for your exact venue and gear combination
- **Mixer Integration** — pushes corrections directly to Yamaha, Behringer, Allen & Heath via OSC
- **AMALYN Sentinel** — monitors signal health and predicts hardware failure before it happens
- **Three Portals** — Engineer Dashboard, Musician IEM Portal, Producer Analysis Suite

---

## System Architecture

AMALYN Core (Brain)
├── FFT Spectral Analysis
├── ML Anomaly Detection
├── Brand Frequency Library
└── Perfect State Calculator

AMALYN Connect (Bridge)
├── OSC Mixer Integration
├── Dante / AES64 / AVB Support
└── MIDI over Ethernet

AMALYN Interface (Face)
├── Engineer Dashboard (dashboard.html)
├── Musician Portal (musician.html)
└── Producer Portal (producer.html)

AMALYN Sentinel (Shield)
├── Predictive Hardware Failure Detection
├── Signal Stability Monitoring
└── Emergency Safe State


---

## Supported Hardware

| Category | Brands |
|---|---|
| Mixers | Yamaha CL/QL, Behringer X32/M32, Allen & Heath SQ/dLive |
| Speakers | JBL, QSC, RCF, Electro-Voice |
| Microphones | Shure SM58/SM7B, Sennheiser e835, AKG C414, Neumann U87 |
| DAWs | Ableton, FL Studio, Logic, Pro Tools, Cubase |

---

## Installation

### Requirements
- Python 3.11
- Windows / macOS / Linux

### Setup

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/amalyn-tech.git
cd amalyn-tech/AMALYN_TECH

# Create virtual environment
python -m venv amalyn_env

# Activate (Windows)
amalyn_env\Scripts\activate

# Activate (Mac/Linux)
source amalyn_env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start AMALYN
cd AMALYN_AI
python api.py
```

### Open Dashboard
Open `AMALYN_AI/dashboard.html` in Chrome or Edge.

---

## Portals

| Portal | File | Purpose |
|---|---|---|
| Engineer | `dashboard.html` | Live spectrum, feedback alerts, EQ suggestions |
| Musician | `musician.html` | IEM monitor mix control from phone |
| Producer | `producer.html` | Deep analysis, phase correlation, session reports |

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/ws` | WebSocket | Real-time audio stream |
| `/setup` | POST | Load Perfect State for session |
| `/library` | GET | Get available gear library |
| `/musician/channels` | GET | Get IEM channel mix |
| `/musician/mix` | POST | Update channel level or mute |
| `/sentinel/status` | GET | Get signal health report |
| `/health` | GET | API health check |

---

## ML Training

```bash
# Collect training data
python ml_collector.py

# Train the model
python ml_trainer.py
```

---

## Project Structure

AMALYN_TECH/
AMALYN_AI/
api.py # FastAPI backend + WebSocket
config.py # Audio settings
audio_utils.py # FFT engine
alerts.py # Threshold detection
eq_engine.py # Auto EQ suggestions
logger.py # Session logger
mixer.py # OSC mixer integration
simulator.py # Mixer simulator
sentinel.py # Predictive health monitor
library.py # Brand frequency library
library.json # Gear database
ml_collector.py # Training data collector
ml_trainer.py # Neural network trainer
ml_inference.py # Model inference engine
dashboard.html # Engineer portal
musician.html # Musician portal
producer.html # Producer portal
README.md
requirements.txt
.gitignore


---

## Built By

**Angela** — Software Engineer & Sound Engineer, Nairobi, Kenya  
*AMALYN TECH — Because sound should never fail.*