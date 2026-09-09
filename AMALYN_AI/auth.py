# auth.py — AMALYN Authentication System
import hashlib
import json
import os
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')
VERIFICATION_TTL_MINUTES = 15
MAX_VERIFICATION_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60

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


def _public_user(user):
    """Return the browser-safe identity shape for an authenticated account."""
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "avatar": user["avatar"],
        "email_verified": True,
        "logged_in_at": datetime.now().isoformat(),
    }


def authenticate_with_status(email, password):
    """Authenticate a local account without allowing an unverified login."""
    users = load_users()
    hashed = hash_password(password)
    user = next((u for u in users if
                 u['email'].lower() == email.lower() and
                 u['password'] == hashed), None)
    if user is None:
        return None, "invalid_credentials"
    if not user.get('verified', True):
        return None, "verification_required"
    return _public_user(user), None


def authenticate(email, password):
    """Backward-compatible local authentication helper."""
    user, _ = authenticate_with_status(email, password)
    return user


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
    }
    _issue_verification_code(new_user)
    users.append(new_user)
    save_users(users)
    return new_user, None


def _issue_verification_code(user):
    """Create a human-enterable six-digit code with a short lifetime."""
    now = datetime.now(timezone.utc)
    user["verification_code"] = f"{secrets.randbelow(1_000_000):06d}"
    user["verification_expires_at"] = (
        now + timedelta(minutes=VERIFICATION_TTL_MINUTES)
    ).isoformat()
    user["verification_attempts"] = 0
    user["verification_sent_at"] = now.isoformat()


def send_verification_code(user):
    """Send the pending account code via the configured SMTP provider.

    Gmail works with SMTP_HOST=smtp.gmail.com, SMTP_PORT=587 and a Google App
    Password in SMTP_PASSWORD. The sender address may differ from the login
    account by setting SMTP_USERNAME.
    """
    code = user["verification_code"]
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip()
    username = os.getenv("SMTP_USERNAME", sender).strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not sender or not username or not password:
        return False
    message = EmailMessage()
    message["Subject"] = "Your AMALYN TECH verification code"
    message["From"] = sender
    message["To"] = user["email"]
    message.set_content(
        f"Your AMALYN TECH verification code is {code}.\n\n"
        "It expires in 15 minutes."
    )
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes"}
    if use_ssl or port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=10) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
    return True


def resend_verification_code(email):
    """Issue a replacement code for an existing, unverified account."""
    users = load_users()
    now = datetime.now(timezone.utc)
    for user in users:
        if user["email"].lower() != email.lower():
            continue
        if user.get("verified", True):
            return None, "Account is already verified"
        last_sent = user.get("verification_sent_at")
        if last_sent:
            try:
                sent_at = datetime.fromisoformat(last_sent)
                elapsed = (now - sent_at).total_seconds()
                if elapsed < RESEND_COOLDOWN_SECONDS:
                    seconds_left = max(1, int(RESEND_COOLDOWN_SECONDS - elapsed))
                    return None, f"Please wait {seconds_left} seconds before requesting another code"
            except ValueError:
                pass
        _issue_verification_code(user)
        save_users(users)
        return user, None
    # Deliberately do not reveal whether an address belongs to a real account.
    return None, "If that account exists, a verification code can be requested from its sign-in screen"


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
        if expires < now:
            return None, "Verification code has expired. Request a new code."
        attempts = int(user.get("verification_attempts", 0))
        if attempts >= MAX_VERIFICATION_ATTEMPTS:
            return None, "Too many incorrect attempts. Request a new code."
        if not secrets.compare_digest(user.get("verification_code", ""), code.strip()):
            user["verification_attempts"] = attempts + 1
            save_users(users)
            return None, "Invalid or expired verification code"
        user["verified"] = True
        user.pop("verification_code", None)
        user.pop("verification_expires_at", None)
        user.pop("verification_attempts", None)
        user.pop("verification_sent_at", None)
        save_users(users)
        return _public_user(user), None
    return None, "Account not found"
