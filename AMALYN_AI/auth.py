# auth.py — AMALYN Authentication System
import hashlib
import json
import os
import re
import secrets
import smtplib
import base64
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

USERS_FILE = os.path.join(os.path.dirname(__file__), 'users.json')
VERIFICATION_TTL_MINUTES = 15
MAX_VERIFICATION_ATTEMPTS = 5
RESEND_COOLDOWN_SECONDS = 60
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_REQUIREMENTS = {
    "min_length": PASSWORD_MIN_LENGTH,
    "uppercase": True,
    "lowercase": True,
    "number": True,
    "special": True,
}
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$"
)
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "amalyn").strip()
MONGODB_USERS_COLLECTION = os.getenv("MONGODB_USERS_COLLECTION", "users").strip()
_mongo_client = None
_mongo_collection = None
_mongo_uri = None

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
    collection = _get_mongo_collection()
    if collection is not None:
        users = [_without_mongo_fields(user) for user in collection.find({})]
        if not users:
            save_users(DEFAULT_USERS)
            return [dict(user) for user in DEFAULT_USERS]
        return users
    if not os.path.exists(USERS_FILE):
        save_users(DEFAULT_USERS)
        return DEFAULT_USERS
    with open(USERS_FILE, 'r', encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    collection = _get_mongo_collection()
    if collection is not None:
        collection.delete_many({})
        if users:
            collection.insert_many([
                {**user, "email_lower": user["email"].lower()}
                for user in users
            ])
        return
    temporary_file = f"{USERS_FILE}.tmp"
    with open(temporary_file, 'w', encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    os.replace(temporary_file, USERS_FILE)


def _without_mongo_fields(user):
    return {key: value for key, value in user.items() if key != "_id" and key != "email_lower"}


def _get_mongo_collection():
    """Return the configured MongoDB collection, or None for local development."""
    global _mongo_client, _mongo_collection, _mongo_uri
    uri = os.getenv("MONGODB_URI", MONGODB_URI).strip()
    if not uri:
        return None
    if _mongo_collection is not None and _mongo_uri == uri:
        return _mongo_collection
    try:
        from pymongo import MongoClient
    except ImportError as error:
        raise RuntimeError(
            "MONGODB_URI is configured but pymongo is not installed"
        ) from error
    _mongo_client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    _mongo_client.admin.command("ping")
    database_name = os.getenv("MONGODB_DATABASE", MONGODB_DATABASE).strip()
    collection_name = os.getenv(
        "MONGODB_USERS_COLLECTION", MONGODB_USERS_COLLECTION
    ).strip()
    _mongo_collection = _mongo_client[database_name][collection_name]
    _mongo_collection.create_index("email_lower", unique=True)
    _mongo_uri = uri
    return _mongo_collection


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 310_000
    )
    return "pbkdf2_sha256$310000${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def validate_email(email):
    clean_email = email.strip().lower() if email else ""
    if len(clean_email) > 254 or not EMAIL_PATTERN.fullmatch(clean_email):
        return None
    return clean_email


def password_errors(password, confirmation=None):
    errors = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        errors.append(f"Password must be no more than {PASSWORD_MAX_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must include an uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must include a lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must include a number")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("Password must include a special character")
    if confirmation is not None and password != confirmation:
        errors.append("Passwords do not match")
    return errors


def _verify_password(password, stored_password):
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, encoded_salt, encoded_digest = stored_password.split("$")
            salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
            expected = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
            return secrets.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    return secrets.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored_password)


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
    user = next((u for u in users if
                 u['email'].lower() == email.lower() and
                 _verify_password(password, u['password'])), None)
    if user is None:
        return None, "invalid_credentials"
    if not user.get('verified', True):
        return None, "verification_required"
    if not user["password"].startswith("pbkdf2_sha256$"):
        user["password"] = hash_password(password)
        save_users(users)
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
    clean_name = name.strip() if name else ""
    clean_email = validate_email(email)
    if not clean_name:
        return None, "Name is required"
    if not clean_email:
        return None, "Enter a valid email address"
    errors = password_errors(password)
    if errors:
        return None, errors[0]
    if any(u['email'].lower() == clean_email for u in users):
        return None, "Email already exists"
    next_id = max((u['id'] for u in users), default=0) + 1
    avatar = clean_name[0].upper() if clean_name else "U"
    new_user = {
        "id": next_id,
        "name": clean_name,
        "email": clean_email,
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


def send_verification_code(user, oauth=False):
    """Send the pending account code via the configured SMTP provider.

    Gmail works with SMTP_HOST=smtp.gmail.com, SMTP_PORT=587 and a Google App
    Password in SMTP_PASSWORD. The sender address may differ from the login
    account by setting SMTP_USERNAME.
    """
    code = user["oauth_verification_code"] if oauth else user["verification_code"]
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


def start_oauth_verification(name, email, role):
    """Create or update an OAuth profile and issue AMALYN's second email check."""
    users = load_users()
    clean_email = validate_email(email)
    clean_name = name.strip() if name else ""
    if not clean_email:
        return None, "Enter a valid email address"
    if not clean_name:
        return None, "Name is required"
    user = next((item for item in users if item["email"].lower() == clean_email), None)
    if user is None:
        user = {
            "id": max((item["id"] for item in users), default=0) + 1,
            "name": clean_name,
            "email": clean_email,
            "password": hash_password(secrets.token_urlsafe(32)),
            "role": role,
            "avatar": clean_name[0].upper(),
            "verified": True,
            "oauth": True,
        }
        users.append(user)
    else:
        user["name"] = clean_name
        user["role"] = role
    _issue_oauth_verification_code(user)
    save_users(users)
    return user, None


def _issue_oauth_verification_code(user):
    now = datetime.now(timezone.utc)
    user["oauth_verification_code"] = f"{secrets.randbelow(1_000_000):06d}"
    user["oauth_verification_expires_at"] = (
        now + timedelta(minutes=VERIFICATION_TTL_MINUTES)
    ).isoformat()
    user["oauth_verification_attempts"] = 0
    user["oauth_verification_sent_at"] = now.isoformat()


def verify_oauth_user(email, code):
    users = load_users()
    now = datetime.now(timezone.utc)
    clean_email = validate_email(email)
    for user in users:
        if user["email"].lower() != clean_email:
            continue
        try:
            expires = datetime.fromisoformat(user["oauth_verification_expires_at"])
        except (KeyError, ValueError) as error:
            raise ValueError("Invalid OAuth verification record") from error
        if expires < now:
            return None, "Verification code has expired. Request a new code."
        attempts = int(user.get("oauth_verification_attempts", 0))
        if attempts >= MAX_VERIFICATION_ATTEMPTS:
            return None, "Too many incorrect attempts. Request a new code."
        if not secrets.compare_digest(
            user.get("oauth_verification_code", ""), code.strip()
        ):
            user["oauth_verification_attempts"] = attempts + 1
            save_users(users)
            return None, "Invalid or expired verification code"
        for key in (
            "oauth_verification_code",
            "oauth_verification_expires_at",
            "oauth_verification_attempts",
            "oauth_verification_sent_at",
        ):
            user.pop(key, None)
        save_users(users)
        return _public_user(user), None
    return None, "Account not found"


def resend_oauth_verification_code(email):
    users = load_users()
    now = datetime.now(timezone.utc)
    clean_email = validate_email(email)
    for user in users:
        if user["email"].lower() != clean_email:
            continue
        last_sent = user.get("oauth_verification_sent_at")
        if last_sent:
            sent_at = datetime.fromisoformat(last_sent)
            elapsed = (now - sent_at).total_seconds()
            if elapsed < RESEND_COOLDOWN_SECONDS:
                seconds_left = max(1, int(RESEND_COOLDOWN_SECONDS - elapsed))
                return None, f"Please wait {seconds_left} seconds before requesting another code"
        _issue_oauth_verification_code(user)
        save_users(users)
        return user, None
    return None, "If that account exists, a verification code can be requested"


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
