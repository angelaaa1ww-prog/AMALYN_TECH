import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from database import users_col
from auth import send_verification_code

TOKEN_SECRET = os.getenv("AMALYN_TOKEN_SECRET", "local-development-secret")


def _hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return "pbkdf2_sha256$310000${}${}".format(
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )


def _check_password(password, stored):
    try:
        _, iterations, encoded_salt, encoded_digest = stored.split("$")
        salt = base64.urlsafe_b64decode(encoded_salt)
        expected = base64.urlsafe_b64decode(encoded_digest)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _public_user(user):
    return {
        "id": str(user["_id"]),
        "name": user["name"],
        "email": user["email"],
        "role": user.get("role", "engineer"),
        "avatar": user.get("avatar", user["name"][:1].upper()),
        "email_verified": user.get("email_verified", False),
    }


def create_token(user_id):
    payload = f"{user_id}:{int(time.time())}"
    signature = hmac.new(
        TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()


def decode_token(token):
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        user_id, issued_at, signature = decoded.rsplit(":", 2)
        payload = f"{user_id}:{issued_at}"
        expected = hmac.new(
            TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return user_id
    except (ValueError, TypeError):
        return None


async def create_user(name, email, password, role="engineer", confirm_password=None):
    clean_email = email.strip().lower()
    if len(password) < 8 or not any(c.isupper() for c in password):
        return None, "Password must be at least 8 characters and include an uppercase letter"
    if not any(c.islower() for c in password) or not any(c.isdigit() for c in password):
        return None, "Password must include a lowercase letter and a number"
    if not any(not c.isalnum() for c in password):
        return None, "Password must include a special character"
    if confirm_password is not None and password != confirm_password:
        return None, "Passwords do not match"
    if await users_col.find_one({"email": clean_email}):
        return None, "Email already exists"
    user = {
        "name": name.strip(),
        "email": clean_email,
        "password": _hash_password(password),
        "role": role,
        "avatar": name.strip()[:1].upper() or "U",
        "email_verified": False,
        "verification_code": f"{secrets.randbelow(1_000_000):06d}",
        "verification_expires_at": (
            datetime.now(timezone.utc) + timedelta(minutes=15)
        ).isoformat(),
        "verification_attempts": 0,
        "verification_sent_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await users_col.insert_one(user)
    user["_id"] = result.inserted_id
    if not send_verification_code(user):
        await users_col.delete_one({"_id": user["_id"]})
        return None, "Email verification is not configured on the server"
    return _public_user(user), "verification_required"


async def authenticate_user(email, password):
    user = await users_col.find_one({"email": email.strip().lower()})
    if not user or not _check_password(password, user.get("password", "")):
        return None, "Invalid email or password"
    if not user.get("email_verified", False):
        return None, "verification_required"
    return {"user": _public_user(user), "token": create_token(user["_id"])}, None


async def get_user_by_id(user_id):
    from bson import ObjectId
    try:
        user = await users_col.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None
    return _public_user(user) if user else None


async def get_all_users():
    return [_public_user(user) async for user in users_col.find({})]


async def verify_user(email, code):
    user = await users_col.find_one({"email": email.strip().lower()})
    if user is None:
        return None, "Account not found"
    try:
        expires = datetime.fromisoformat(user["verification_expires_at"])
    except (KeyError, ValueError) as error:
        raise ValueError("Invalid verification record") from error
    if expires < datetime.now(timezone.utc):
        return None, "Verification code has expired. Request a new code."
    attempts = int(user.get("verification_attempts", 0))
    if attempts >= 5:
        return None, "Too many incorrect attempts. Request a new code."
    if not secrets.compare_digest(user.get("verification_code", ""), code.strip()):
        await users_col.update_one(
            {"_id": user["_id"]}, {"$inc": {"verification_attempts": 1}}
        )
        return None, "Invalid or expired verification code"
    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$set": {"email_verified": True},
            "$unset": {
                "verification_code": "",
                "verification_expires_at": "",
                "verification_attempts": "",
                "verification_sent_at": "",
            },
        },
    )
    user["email_verified"] = True
    return _public_user(user), None


async def resend_verification_code(email):
    user = await users_col.find_one({"email": email.strip().lower()})
    if user is None:
        return None, "If that account exists, a verification code can be requested"
    sent_at = user.get("verification_sent_at")
    if sent_at:
        elapsed = (
            datetime.now(timezone.utc) - datetime.fromisoformat(sent_at)
        ).total_seconds()
        if elapsed < 60:
            return None, f"Please wait {max(1, int(60 - elapsed))} seconds before requesting another code"
    now = datetime.now(timezone.utc)
    user["verification_code"] = f"{secrets.randbelow(1_000_000):06d}"
    user["verification_expires_at"] = (now + timedelta(minutes=15)).isoformat()
    user["verification_attempts"] = 0
    user["verification_sent_at"] = now.isoformat()
    await users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "verification_code": user["verification_code"],
            "verification_expires_at": user["verification_expires_at"],
            "verification_attempts": 0,
            "verification_sent_at": user["verification_sent_at"],
        }},
    )
    if not send_verification_code(user):
        return None, "Email verification is not configured on the server"
    return user, None


async def start_oauth_verification(name, email, role):
    """Create or update a local profile for an already verified Supabase user."""
    clean_email = email.strip().lower()
    clean_name = name.strip()
    if not clean_name:
        return None, "Name is required"
    if not clean_email:
        return None, "Email is required"

    user = await users_col.find_one({"email": clean_email})
    if user is None:
        user = {
            "name": clean_name,
            "email": clean_email,
            "password": _hash_password(secrets.token_urlsafe(32)),
            "role": role or "musician",
            "avatar": clean_name[:1].upper(),
            "email_verified": True,
            "oauth": True,
        }
        result = await users_col.insert_one(user)
        user["_id"] = result.inserted_id
    else:
        await users_col.update_one(
            {"_id": user["_id"]},
            {"$set": {"name": clean_name, "role": role or user.get("role", "musician")}},
        )
        user["name"] = clean_name
        user["role"] = role or user.get("role", "musician")

    return _public_user(user), None


async def verify_oauth_user(email, code):
    user = await users_col.find_one({"email": email.strip().lower()})
    if user is None:
        return None, "Account not found"
    try:
        expires = datetime.fromisoformat(user["oauth_verification_expires_at"])
    except (KeyError, ValueError) as error:
        raise ValueError("Invalid OAuth verification record") from error
    if expires < datetime.now(timezone.utc):
        return None, "Verification code has expired. Request a new code."
    attempts = int(user.get("oauth_verification_attempts", 0))
    if attempts >= 5:
        return None, "Too many incorrect attempts. Request a new code."
    if not secrets.compare_digest(user.get("oauth_verification_code", ""), code.strip()):
        await users_col.update_one(
            {"_id": user["_id"]}, {"$inc": {"oauth_verification_attempts": 1}}
        )
        return None, "Invalid or expired verification code"
    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$unset": {
                "oauth_verification_code": "",
                "oauth_verification_expires_at": "",
                "oauth_verification_attempts": "",
                "oauth_verification_sent_at": "",
            }
        },
    )
    return _public_user(user), None


async def resend_oauth_verification_code(email):
    user = await users_col.find_one({"email": email.strip().lower()})
    if user is None:
        return None, "If that account exists, a verification code can be requested"
    sent_at = user.get("oauth_verification_sent_at")
    if sent_at:
        elapsed = (
            datetime.now(timezone.utc) - datetime.fromisoformat(sent_at)
        ).total_seconds()
        if elapsed < 60:
            return None, f"Please wait {max(1, int(60 - elapsed))} seconds before requesting another code"
    now = datetime.now(timezone.utc)
    user["oauth_verification_code"] = f"{secrets.randbelow(1_000_000):06d}"
    user["oauth_verification_expires_at"] = (
        now + timedelta(minutes=15)
    ).isoformat()
    user["oauth_verification_attempts"] = 0
    user["oauth_verification_sent_at"] = now.isoformat()
    await users_col.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "oauth_verification_code": user["oauth_verification_code"],
                "oauth_verification_expires_at": user["oauth_verification_expires_at"],
                "oauth_verification_attempts": 0,
                "oauth_verification_sent_at": user["oauth_verification_sent_at"],
            }
        },
    )
    if not send_verification_code(user, oauth=True):
        return None, "Email verification is not configured on the server"
    return user, None
