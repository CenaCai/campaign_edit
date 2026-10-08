"""鉴权与通用依赖：HS256 JWT（标准库实现）+ 当前用户。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import secrets
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_token(user_id: str, *, ttl: int | None = None) -> tuple[str, int]:
    ttl = ttl or settings.jwt_ttl_seconds
    header = _b64u_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64u_encode(json.dumps({
        "sub": user_id, "iat": int(time.time()), "exp": int(time.time()) + ttl,
    }).encode())
    sig = _b64u_encode(hmac.new(settings.jwt_secret.encode(),
                                 f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}", ttl


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        header, payload, sig = token.split(".")
    except ValueError:
        return None
    expect = _b64u_encode(hmac.new(settings.jwt_secret.encode(),
                                   f"{header}.{payload}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        data = json.loads(_b64u_decode(payload))
    except Exception:
        return None
    if int(data.get("exp", 0)) < int(time.time()):
        return None
    return data


# ---------------------------------------------------------------- 密码

def hash_password(pwd: str, *, iterations: int = 120_000) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"


def verify_password(pwd: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


# ---------------------------------------------------------------- 依赖

def get_current_user(db: Session = Depends(get_db),
                     authorization: str | None = Header(None)) -> User:
    if settings.auth_disabled:
        u = db.execute(select(User).order_by(User.created_at)).scalars().first()
        if u is None:
            raise HTTPException(401, "系统未初始化：请先运行 seed")
        return u
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Authorization: Bearer <token>")
    data = decode_token(authorization.split(" ", 1)[1].strip())
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    u = db.get(User, data.get("sub"))
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return u


def require_roles(*roles: str):
    def _dep(user: User = Depends(get_current_user)) -> User:
        if roles and user.role not in roles and user.role != "admin":
            raise HTTPException(403, f"需要角色：{roles}（当前 {user.role}）")
        return user
    return _dep


def bootstrap_admin(db: Session) -> User:
    """确保至少有一个可用管理员。"""
    u = db.execute(select(User).where(User.email == settings.bootstrap_admin_email)).scalar_one_or_none()
    if u:
        return u
    u = User(email=settings.bootstrap_admin_email, name=settings.bootstrap_admin_name,
             role="admin", password_hash=hash_password(settings.bootstrap_admin_password))
    db.add(u)
    db.commit()
    return u


def ensure_demo_users(db: Session) -> list[User]:
    """示例协作账号：运营 / 设计 / 前端。"""
    from .seed.demo import DEMO_USERS
    out = []
    for spec in DEMO_USERS:
        u = db.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none()
        if u is None:
            u = User(email=spec["email"], name=spec["name"], role=spec["role"],
                     password_hash=hash_password(spec["password"]))
            db.add(u)
        out.append(u)
    db.commit()
    return out