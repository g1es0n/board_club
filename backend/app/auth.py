import hashlib
import hmac
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import fetch_one, get_db
from .schemas import LoginIn

TOKEN_TTL = 12 * 3600
_tokens: dict[str, dict] = {}
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api", tags=["Авторизация"])


def hash_password(password: str, iterations: int = 100_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    return hmac.compare_digest(check, digest)


def require(*roles: str):
    def dependency(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
        user = _tokens.get(creds.credentials) if creds else None
        if not user or user["expires"] < time.time():
            raise HTTPException(401, "Требуется вход в систему")
        if user["role"] not in roles:
            raise HTTPException(403, "Недостаточно прав для этой операции")
        return user
    return dependency


admin_user = require("admin")
staff_user = require("admin", "host")


def admin_db(user: dict = Depends(admin_user)):
    with get_db("admin") as conn:
        yield conn


def staff_db(user: dict = Depends(staff_user)):
    with get_db(user["role"]) as conn:
        yield conn


def public_db():
    with get_db("viewer") as conn:
        yield conn


@router.post("/login")
def login(data: LoginIn):
    with get_db("admin") as conn:
        row = fetch_one(conn, "SELECT id, full_name, role, password_hash FROM staff WHERE login = %s", [data.login])
    if not row or not verify_password(data.password, row["password_hash"]):
        raise HTTPException(401, "Неверный логин или пароль")
    token = secrets.token_urlsafe(32)
    user = {"id": row["id"], "full_name": row["full_name"], "role": row["role"]}
    _tokens[token] = {**user, "expires": time.time() + TOKEN_TTL}
    return {"token": token, **user}


@router.post("/logout", status_code=204)
def logout(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if creds:
        _tokens.pop(creds.credentials, None)


@router.get("/me")
def me(user: dict = Depends(staff_user)):
    return {k: user[k] for k in ("id", "full_name", "role")}