"""
用户管理 API 路由 —— 认证、会话、用户配置。
所有业务校验集中在此层。
"""

import json
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from user.auth import hash_password, verify_password, create_jwt
from user.helpers import _get_db, require_auth

auth_router = APIRouter()
session_router = APIRouter()
user_router = APIRouter()


# ──── 认证 ────

@auth_router.post("/register")
async def register(request: Request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    password = data.get("password", "")

    if not name or not password:
        return JSONResponse({"error": "用户名和密码不能为空"}, status_code=400)

    db = _get_db(request)
    if db.get_user(name):
        return JSONResponse({"error": f"用户名已存在: {name}"}, status_code=409)

    hashed = hash_password(password)
    uid = db.insert_user(name, hashed)
    token = create_jwt(uid, name)
    return JSONResponse({"token": token, "user_id": uid, "name": name})


@auth_router.post("/login")
async def login(request: Request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    password = data.get("password", "")

    if not name or not password:
        return JSONResponse({"error": "用户名和密码不能为空"}, status_code=400)

    db = _get_db(request)
    user = db.get_user(name)
    if not user or not verify_password(password, user["password"]):
        return JSONResponse({"error": "用户名或密码错误"}, status_code=401)

    token = create_jwt(user["id"], user["name"])
    return JSONResponse({"token": token, "user_id": user["id"], "name": user["name"]})


@auth_router.post("/logout")
async def logout(request: Request):
    return JSONResponse({"status": "ok"})


@auth_router.get("/me")
async def me(request: Request, user: dict = Depends(require_auth)):
    return JSONResponse({"user_id": user["user_id"], "user_name": user["user_name"]})


@auth_router.get("/verify")
async def verify(request: Request, user: dict = Depends(require_auth)):
    return JSONResponse({"valid": True, "user_id": user["user_id"], "user_name": user["user_name"]})


@auth_router.get("/system-config")
async def get_system_config():
    import config as _cfg
    return JSONResponse({
        "default_roles": _cfg.ROLE_MODEL,
        "model_pool": _cfg.MODEL_POOL,
    })


# ──── 会话 ────

@session_router.get("")
async def list_sessions(request: Request, user: dict = Depends(require_auth)):
    db = _get_db(request)
    rows = db.list_sessions(user["user_id"])
    result = []
    for r in rows:
        try:
            msgs = json.loads(r["messages"])
        except (json.JSONDecodeError, TypeError):
            msgs = []
        first = ""
        for m in msgs:
            c = m.get("content", "")
            if c:
                first = c[:50]
                break
        result.append({
            "id": r["id"],
            "title": first or r["title"] or "空对话",
            "count": len(msgs),
            "updated": r["updated_at"] or "",
        })
    return JSONResponse(result)


@session_router.get("/search")
async def search_sessions(
    request: Request,
    q: str = "",
    limit: int = 20,
    offset: int = 0,
    user: dict = Depends(require_auth),
):
    """全文检索当前用户的会话消息"""
    db = _get_db(request)
    results = db.search_messages(user["user_id"], q, limit, offset)
    return JSONResponse(results)


# ─── 以下为原有的 C(R)UD 路由 ───

@session_router.post("")
async def save_session(request: Request, user: dict = Depends(require_auth)):
    db = _get_db(request)
    data = await request.json()
    sid = data.get("id") or str(int(__import__("time").time() * 1000))
    title = data.get("title", "")
    db.upsert_session(sid, user["user_id"], data.get("messages", []), title)
    return JSONResponse({"id": sid, "status": "ok"})


@session_router.get("/{session_id}")
async def get_session(request: Request, session_id: str, user: dict = Depends(require_auth)):
    db = _get_db(request)
    s = db.get_session(session_id)
    if not s:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    if s["user_id"] != user["user_id"]:
        return JSONResponse({"error": "无权访问"}, status_code=403)
    return JSONResponse({"messages": s["messages"], "updated": s["updated"]})


@session_router.delete("/{session_id}")
async def delete_session(request: Request, session_id: str, user: dict = Depends(require_auth)):
    db = _get_db(request)
    s = db.get_session(session_id)
    if not s:
        return JSONResponse({"error": "会话不存在"}, status_code=404)
    if s["user_id"] != user["user_id"]:
        return JSONResponse({"error": "无权访问"}, status_code=403)
    db.delete_session(session_id)
    return JSONResponse({"status": "ok"})


# ──── 用户配置 ────

@user_router.get("/config")
async def get_config(request: Request, user: dict = Depends(require_auth)):
    import config as _cfg
    roles = dict(_cfg.ROLE_MODEL)
    db = _get_db(request)
    cfg = db.get_user_config(user["user_id"])
    if cfg:
        roles.update(cfg.get("roles", {}))
    return JSONResponse({
        "roles": roles,
        "models": cfg["models"] if cfg else [],
        "system_models": _cfg.MODEL_POOL,
    })


@user_router.put("/config")
async def save_config(request: Request, user: dict = Depends(require_auth)):
    db = _get_db(request)
    data = await request.json()
    roles = data.get("roles", {})
    cfg = db.get_user_config(user["user_id"])
    models = cfg["models"] if cfg else []
    db.upsert_user_config(user["user_id"], roles, models)
    return JSONResponse({"status": "ok"})


@user_router.post("/custom-models")
async def add_custom_model(request: Request, user: dict = Depends(require_auth)):
    data = await request.json()
    key = (data.get("key") or "").strip()
    model = (data.get("model") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    api_key = (data.get("api_key") or "").strip()

    if not key:
        return JSONResponse({"error": "模型标识不能为空"}, status_code=400)
    if not model:
        return JSONResponse({"error": "模型名称不能为空"}, status_code=400)
    if not api_key:
        return JSONResponse({"error": "API Key 不能为空"}, status_code=400)

    import config as _cfg
    if key in _cfg.MODEL_POOL:
        return JSONResponse({"error": f"标识 \"{key}\" 与系统模型冲突"}, status_code=409)

    db = _get_db(request)
    cfg = db.get_user_config(user["user_id"])
    models = cfg["models"] if cfg else []
    for m in models:
        if m["key"] == key:
            return JSONResponse({"error": f"自定义模型标识 \"{key}\" 已存在"}, status_code=409)

    models.append({"key": key, "model": model, "base_url": base_url, "api_key": api_key})
    roles = cfg["roles"] if cfg else {}
    db.upsert_user_config(user["user_id"], roles, models)
    return JSONResponse({"status": "ok"})


@user_router.delete("/custom-models/{model_key}")
async def delete_custom_model(request: Request, model_key: str, user: dict = Depends(require_auth)):
    db = _get_db(request)
    cfg = db.get_user_config(user["user_id"])
    if not cfg:
        return JSONResponse({"error": "无配置"}, status_code=404)
    original = len(cfg["models"])
    cfg["models"] = [m for m in cfg["models"] if m["key"] != model_key]
    if len(cfg["models"]) == original:
        return JSONResponse({"error": f"自定义模型 \"{model_key}\" 不存在"}, status_code=404)

    db.upsert_user_config(user["user_id"], cfg["roles"], cfg["models"])
    return JSONResponse({"status": "ok"})
