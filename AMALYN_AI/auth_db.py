import base64
import hashlib
import hmac
import os
import secrets
import time

from database import users_col

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
        "email_verified": True,
    }
    result = await users_col.insert_one(user)
    user["_id"] = result.inserted_id
    return _public_user(user), None


async def authenticate_user(email, password):
    user = await users_col.find_one({"email": email.strip().lower()})
    if not user or not _check_password(password, user.get("password", "")):
        return None, "Invalid email or password"
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
