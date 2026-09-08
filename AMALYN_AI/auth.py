# auth.py — AMALYN Authentication System
import hashlib
import json
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')

# Default users — in production replace with a real database
DEFAULT_USERS = [
    {
        "id": 1,
        "name": "Angela",
        "email": "angela@amalyn.tech",
        "password": hashlib.sha256("amalyn2024".encode()).hexdigest(),
        "role": "engineer",
        "avatar": "A"
    },
    {
        "id": 2,
        "name": "Producer",
        "email": "producer@amalyn.tech",
        "password": hashlib.sha256("producer2024".encode()).hexdigest(),
        "role": "producer",
        "avatar": "P"
    },
    {
        "id": 3,
        "name": "Musician",
        "email": "musician@amalyn.tech",
        "password": hashlib.sha256("musician2024".encode()).hexdigest(),
        "role": "musician",
        "avatar": "M"
    }
]


def load_users():
    if not os.path.exists(USERS_FILE):
        save_users(DEFAULT_USERS)
        return DEFAULT_USERS
    with open(USERS_FILE, 'r') as f:
        return json.load(f)


def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate(email, password):
    users = load_users()
    hashed = hash_password(password)
    user = next((u for u in users if
                 u['email'].lower() == email.lower() and
                 u['password'] == hashed and
                 u.get('verified', True)), None)
    if user:
        return {
            "id": user['id'],
            "name": user['name'],
            "email": user['email'],
            "role": user['role'],
            "avatar": user['avatar'],
            "logged_in_at": datetime.now().isoformat()
        }
    return None


def get_all_users():
    users = load_users()
    return [{"id": u['id'], "name": u['name'],
             "email": u['email'], "role": u['role'],
             "avatar": u['avatar']} for u in users]


def add_user(name, email, password, role):
    users = load_users()
    if any(u['email'].lower() == email.lower() for u in users):
        return None, "Email already exists"
    next_id = max((u['id'] for u in users), default=0) + 1
    clean_name = name.strip() if name else ""
    avatar = clean_name[0].upper() if clean_name else "U"
    new_user = {
        "id": next_id,
        "name": name,
        "email": email,
        "password": hash_password(password),
        "role": role,
        "avatar": avatar,
        "verified": False,
        "verification_code": secrets.token_hex(3).upper(),
        "verification_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    }
    users.append(new_user)
    save_users(users)
    return new_user, None


def send_verification_code(user):
    """Send the pending account code when SMTP is configured."""
    code = user["verification_code"]
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    if not host or not sender:
        return False
    message = EmailMessage()
    message["Subject"] = "Your AMALYN TECH verification code"
    message["From"] = sender
    message["To"] = user["email"]
    message.set_content(
        f"Your AMALYN TECH verification code is {code}.\n\n"
        "It expires in 15 minutes."
    )
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=10) as smtp:
        smtp.starttls()
        smtp.login(sender, os.getenv("SMTP_PASSWORD", ""))
        smtp.send_message(message)
    return True


def verify_user(email, code):
    users = load_users()
    now = datetime.now(timezone.utc)
    for user in users:
        if user["email"].lower() != email.lower():
            continue
        if user.get("verified", True):
            return None, "Account is already verified"
        try:
            expires = datetime.fromisoformat(user["verification_expires_at"])
        except (KeyError, ValueError) as error:
            raise ValueError("Invalid verification record") from error
        if expires < now or not secrets.compare_digest(user.get("verification_code", ""), code.strip().upper()):
            return None, "Invalid or expired verification code"
        user["verified"] = True
        user.pop("verification_code", None)
        user.pop("verification_expires_at", None)
        save_users(users)
        return user, None
    return None, "Account not found"