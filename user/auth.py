"""
密码哈希 + JWT 创建/解码 —— 纯函数，无状态。
"""

import os
import time
import bcrypt
import jwt

_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    raise RuntimeError("JWT_SECRET 环境变量未设置，请在 .env 中配置 JWT_SECRET=<随机密钥>")
_JWT_ALGO = "HS256"
_JWT_TTL = 7 * 24 * 3600  # 7 天


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_jwt(user_id: str, name: str) -> str:
    payload = {
        "sub": user_id,
        "name": name,
        "iat": int(time.time()),
        "exp": int(time.time()) + _JWT_TTL,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.PyJWTError:
        return None
