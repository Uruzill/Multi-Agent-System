"""
多智能体协作系统 — FastAPI Web 入口
运行：uvicorn main:app --reload --port 8501
"""

import os
import sys

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# 加载 .env 文件（优先级高于系统环境变量）
from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_DIR, ".env"), override=True)

os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
os.environ["no_proxy"] = "localhost,127.0.0.1"
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

import logging
logging.getLogger().handlers.clear()

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config as _cfg
from user.db import Database

try:
    get_model_display = _cfg.get_model_display
    ROLE_MODEL = _cfg.ROLE_MODEL
    ROLES = _cfg.ROLES
except AttributeError:
    ROLES = ("Planner", "Retriever", "Coder", "Writer",
             "Tester", "Summarizer", "Bot")
    ROLE_MODEL = {k: "?" for k in ROLES}

    def get_model_display(role: str) -> str:
        return "?"

# ──── FastAPI 应用 ────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化数据库（含迁移校验），关闭时执行 WAL 检查点"""
    db = Database(os.path.join(_PROJECT_DIR, "data.db"))
    app.state.db = db
    yield
    # 关闭时强制 WAL 检查点，将 -wal 文件内容写入主数据库
    try:
        with db._conn() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        logging.getLogger(__name__).warning(
            "WAL checkpoint 执行失败，下次启动时 SQLite 将自动恢复", exc_info=True
        )

app = FastAPI(title="多智能体协作系统", version="3.4", lifespan=lifespan)

# ──── 静态文件 & 模板 ────
app.mount("/static", StaticFiles(directory=os.path.join(_PROJECT_DIR, "static")), name="static")
app.mount("/coding", StaticFiles(directory=os.path.join(_PROJECT_DIR, "coding")), name="coding")
templates = Jinja2Templates(directory=os.path.join(_PROJECT_DIR, "templates"))

# ──── 路由 ────
from app.knowledge import router as knowledge_router
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["知识库"])

from user.routes import auth_router, session_router, user_router
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(session_router, prefix="/api/sessions", tags=["会话"])
app.include_router(user_router, prefix="/api/user", tags=["用户配置"])

from router.router import router as chat_router
app.include_router(chat_router, prefix="/api", tags=["流式聊天"])


@app.get("/", response_class=HTMLResponse, tags=["页面"])
async def index(request: Request):
    """聊天主页"""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "role_model": ROLE_MODEL,
            "get_model_display": get_model_display,
            "model_pool": _cfg.MODEL_POOL,
        },
    )


@app.post("/api/report", tags=["聊天"])
async def generate_report(request: Request):
    """从 thinking 记录生成详细报告"""
    data = await request.json()
    thinking = data.get("thinking", [])

    try:
        from agents import create_llm, SYSTEM_PROMPTS
        llm = create_llm("Summarizer")
        context = "\n\n".join(f"{m.get('name', '')}: {m.get('content', '')[:2000]}" for m in thinking if m.get("content"))
        prompt = (
            f"{SYSTEM_PROMPTS['Summarizer']}\n\n"
            f"以下是一个多智能体协作过程的内部记录。请你据此生成一份结构化的执行报告。\n\n"
            f"协作记录：\n\n{context}"
        )
        response = llm.invoke(prompt)
        report = response.content if hasattr(response, "content") else str(response)
    except Exception:
        report = "# 报告生成失败\n\n请稍后重试。"

    os.makedirs(os.path.join(_PROJECT_DIR, "reports"), exist_ok=True)
    import time
    report_path = os.path.join(_PROJECT_DIR, "reports", f"report_{int(time.time())}.md")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
    except OSError:
        report_path = ""

    return JSONResponse({"content": report, "path": report_path})


# ──── 启动 ────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8502, reload=False)
