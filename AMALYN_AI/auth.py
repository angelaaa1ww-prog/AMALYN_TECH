# auth.py — AMALYN Authentication System
import hashlib
import json
import os
from datetime import datetime

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
                 u['password'] == hashed), None)
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
    new_user = {
        "id": max(u['id'] for u in users) + 1,
        "name": name,
        "email": email,
        "password": hash_password(password),
        "role": role,
        "avatar": name[0].upper()
    }
    users.append(new_user)
    save_users(users)
    return new_user, None