# FTS5 全文索引 & WAL 检查点 & 迁移校验 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对会话内容建立 FTS5 全文索引实现语义级检索；Lifespan 启动做迁移校验，关闭时强制执行 WAL 检查点。

**Architecture:** 所有改动集中在 `user/db.py` 的 `Database` 类（新增 schema_version 表、messages_fts 虚拟表、同步/检索/迁移方法）和 `user/routes.py`（新增搜索 API），`main.py` 的 lifespan shutdown 加 WAL checkpoint。不改动 config、templates、前端。

**Tech Stack:** Python 3.x, SQLite3 (FTS5), FastAPI, pytest + TestClient

## Global Constraints

- 无新 PyPI 依赖
- 无配置项变更
- 向后兼容：FTS5 为空时搜索返回空列表
- 用户隔离：搜索/索引均按 `user_id` 过滤
- `_conn()` 上下文管理器每次返回新连接，事务边界即连接边界

---

## File Structure

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `user/db.py` | 所有数据库操作：建表、迁移、FTS5 同步、全文检索 | 修改（核心） |
| `user/routes.py` | 新增 `GET /api/sessions/search` 端点 | 修改 |
| `main.py` | lifespan shutdown 加 WAL checkpoint | 修改 |
| `tests/test_fts5.py` | FTS5 同步、搜索、迁移、WAL 测试 | 新建 |

---

### Task 1: Schema 版本管理 + _init_db 重写

**Files:**
- Modify: `user/db.py:16-46`（`__init__` + `_init_db`）
- 新增类常量、`_run_migration` 方法

**Interfaces:**
- Consumes: 无（第一任务）
- Produces:
  - `Database.TARGET_SCHEMA_VERSION = 2`（类常量）
  - `Database._init_db()`（重写：版本驱动）
  - `Database._run_migration(conn: sqlite3.Connection, version: int) -> None`

- [ ] **Step 1: 添加类常量 `TARGET_SCHEMA_VERSION`**

在 `user/db.py` 的 `class Database:` 内，在所有方法之前添加：

```python
class Database:
    """SQLite 数据库封装，纯增删改查，不包含业务校验。"""

    TARGET_SCHEMA_VERSION = 2
    # 0 → 无数据库 / 未初始化
    # 1 → 初始表: users, sessions, user_configs
    # 2 → 新增: messages_fts (FTS5)
```

- [ ] **Step 2: 重写 `_init_db()` 方法**

替换现有的 `_init_db()`（第20-46行）为版本驱动版本：

```python
    def _init_db(self):
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")

            # 1. 确保 schema_version 表存在
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version     INTEGER PRIMARY KEY,
                    applied_at  TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)

            # 2. 读取当前数据库版本（无记录则为 0）
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            current = row[0] if row[0] is not None else 0

            # 3. 版本超前检查
            if current > self.TARGET_SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库 schema 版本 {current} 高于代码版本 "
                    f"{self.TARGET_SCHEMA_VERSION}，请升级代码或回滚数据库。"
                )

            # 4. 执行缺失的迁移
            for v in range(current + 1, self.TARGET_SCHEMA_VERSION + 1):
                self._run_migration(conn, v)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (v,)
                )
```

- [ ] **Step 3: 添加 `_run_migration()` 方法**

在 `_init_db()` 之后添加：

```python
    def _run_migration(self, conn, version: int):
        """执行指定版本的数据库迁移（幂等 — 全部使用 IF NOT EXISTS）"""
        if version == 1:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL UNIQUE,
                    password   TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now', 'localtime'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id         TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    title      TEXT DEFAULT '',
                    messages   TEXT DEFAULT '[]',
                    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS user_configs (
                    user_id    TEXT PRIMARY KEY,
                    roles      TEXT DEFAULT '{}',
                    models     TEXT DEFAULT '[]',
                    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)
        elif version == 2:
            # 将在 Task 2 中实现 messages_fts 创建和回填
            pass
        else:
            raise ValueError(f"未知的迁移版本: {version}")
```

- [ ] **Step 4: 编写迁移测试**

创建 `tests/test_fts5.py`：

```python
import io
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import pytest
import sqlite3
from fastapi.testclient import TestClient
from main import app


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, suffix: str = ""):
    """注册测试用户，返回 (token, user_id)"""
    name = f"test_{suffix}_{uuid.uuid4().hex[:6]}"
    resp = client.post("/api/auth/register", json={
        "name": name, "email": f"{name}@t.com", "password": "test1234"
    })
    assert resp.status_code == 200, f"注册失败 ({name}): {resp.json()}"
    data = resp.json()
    return data["token"], data["user_id"]


class TestMigration:
    def test_fresh_db_creates_all_tables(self):
        """空白数据库 → 直接到 v2，所有表创建正确"""
        with TestClient(app) as client:
            token, _ = _register(client, "mig_fresh")
            db = app.state.db
            with db._conn() as conn:
                # 验证版本表
                v = conn.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()[0]
                assert v == db.TARGET_SCHEMA_VERSION

                # 验证业务表存在
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                table_names = [t[0] for t in tables]
                for expected in ["users", "sessions", "user_configs",
                                 "schema_version"]:
                    assert expected in table_names, \
                        f"表 {expected} 缺失"

    def test_version_ahead_rejected(self, tmp_path):
        """版本超前 → RuntimeError 拒绝启动"""
        db_path = os.path.join(tmp_path, "test_future.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (99)")
        conn.commit()
        conn.close()

        from user.db import Database
        with pytest.raises(RuntimeError, match="版本.*高于代码版本"):
            Database(db_path)

    def test_migration_idempotent(self):
        """幂等：重复运行不报错"""
        with TestClient(app) as client:
            _register(client, "mig_idem")
            db = app.state.db
            # 二次调用 _init_db 不应报错
            db._init_db()
            with db._conn() as conn:
                v = conn.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()[0]
                assert v == db.TARGET_SCHEMA_VERSION
```

- [ ] **Step 5: 运行测试确认**

```bash
pytest tests/test_fts5.py::TestMigration -v
```

预期：3 passed（含一个 RuntimeError 断言）

- [ ] **Step 6: 提交**

```bash
git add user/db.py tests/test_fts5.py
git commit -m "feat: schema 版本管理 — schema_version 表 + 版本驱动 _init_db"
```

---

### Task 2: FTS5 虚拟表 + 同步逻辑 + v2 迁移回填

**Files:**
- Modify: `user/db.py`（`_run_migration` v2、新增 `_sync_fts`、修改 `upsert_session`、修改 `delete_session`）
- Modify: `tests/test_fts5.py`（新增 FTS5 同步测试）

**Interfaces:**
- Consumes:
  - `Database._run_migration(conn, version)` from Task 1
  - `Database._conn()` context manager from existing code
- Produces:
  - `Database._sync_fts(conn, session_id, user_id, messages) -> None`
  - `upsert_session` 内部调用 `_sync_fts`
  - `delete_session` 内部清理 FTS5 行

- [ ] **Step 1: 实现 v2 迁移（创建 messages_fts + 回填）**

替换 `_run_migration` 中 `elif version == 2:` 的 `pass`：

```python
        elif version == 2:
            conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                    session_id,
                    user_id,
                    msg_index,
                    role,
                    content,
                    tokenize='unicode61'
                );
            """)
            # 回填已有会话
            import json as _json
            rows = conn.execute(
                "SELECT id, user_id, messages FROM sessions"
            ).fetchall()
            for r in rows:
                try:
                    msgs = _json.loads(r["messages"])
                except (_json.JSONDecodeError, TypeError):
                    continue
                for i, msg in enumerate(msgs):
                    content = (msg.get("content", "") or "").strip()
                    role = (msg.get("role", "") or "")
                    if content:
                        conn.execute(
                            "INSERT INTO messages_fts"
                            "(session_id, user_id, msg_index, role, content) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (r["id"], r["user_id"], i, role, content),
                        )
```

- [ ] **Step 2: 添加 `_sync_fts()` 方法**

在 `_run_migration` 方法之后添加：

```python
    def _sync_fts(self, conn, session_id: str, user_id: str,
                  messages: list[dict]) -> None:
        """先删后插，将 messages 同步到 messages_fts。
        调用方必须在同一个 with self._conn() 事务内传入 conn。"""
        conn.execute(
            "DELETE FROM messages_fts WHERE session_id = ?", (session_id,)
        )
        for i, msg in enumerate(messages):
            content = (msg.get("content", "") or "").strip()
            role = (msg.get("role", "") or "")
            if content:
                conn.execute(
                    "INSERT INTO messages_fts"
                    "(session_id, user_id, msg_index, role, content) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (session_id, user_id, i, role, content),
                )
```

- [ ] **Step 3: 修改 `upsert_session()` 调用 `_sync_fts`**

修改 `upsert_session` 方法（第124-143行），在 sessions 表操作后、事务结束前调用 `_sync_fts`：

```python
    def upsert_session(self, session_id: str, user_id: str,
                       messages: list[dict], title: str = "") -> str:
        msgs_json = json.dumps(messages, ensure_ascii=False)
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE sessions SET user_id=?, title=?, messages=?, "
                    "updated_at=datetime('now','localtime') WHERE id=?",
                    (user_id, title, msgs_json, session_id),
                )
            else:
                conn.execute(
                    "INSERT INTO sessions (id, user_id, title, messages) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, user_id, title, msgs_json),
                )
            # 同步 FTS5（同一事务内）
            self._sync_fts(conn, session_id, user_id, messages)
        return session_id
```

- [ ] **Step 4: 修改 `delete_session()` 清理 FTS5**

修改 `delete_session` 方法（第145-148行）：

```python
    def delete_session(self, session_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            if cur.rowcount > 0:
                conn.execute(
                    "DELETE FROM messages_fts WHERE session_id = ?",
                    (session_id,),
                )
                return True
            return False
```

- [ ] **Step 5: 编写 FTS5 同步测试**

在 `tests/test_fts5.py` 中新增：

```python
class TestFts5Sync:
    def test_upsert_creates_fts_entries(self):
        """upsert_session 后 FTS5 可检索到新消息"""
        with TestClient(app) as client:
            token, user_id = _register(client, "fts_up")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [
                {"role": "user", "content": "帮我写一个 Python 爬虫"},
                {"role": "assistant", "content": "好的，这里是一个爬虫示例..."},
                {"role": "user", "content": ""},  # 空消息不应入库
            ]
            db.upsert_session(sid, user_id, msgs, "爬虫教程")

            with db._conn() as conn:
                rows = conn.execute(
                    "SELECT msg_index, role FROM messages_fts "
                    "WHERE session_id = ? ORDER BY msg_index",
                    (sid,),
                ).fetchall()
            # 只有 2 条有效内容入库
            assert len(rows) == 2
            assert rows[0]["msg_index"] == 0
            assert rows[0]["role"] == "user"
            assert rows[1]["msg_index"] == 1
            assert rows[1]["role"] == "assistant"

    def test_upsert_replaces_old_fts_entries(self):
        """更新会话后旧消息在 FTS5 中被替换"""
        with TestClient(app) as client:
            token, user_id = _register(client, "fts_up2")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs_v1 = [{"role": "user", "content": "原来的消息"}]
            db.upsert_session(sid, user_id, msgs_v1, "旧标题")

            msgs_v2 = [{"role": "user", "content": "更新后的消息"}
                      ]
            db.upsert_session(sid, user_id, msgs_v2, "新标题")

            with db._conn() as conn:
                rows = conn.execute(
                    "SELECT content FROM messages_fts WHERE session_id = ?",
                    (sid,),
                ).fetchall()
            assert len(rows) == 1
            assert "更新后" in rows[0]["content"]

    def test_delete_removes_fts_entries(self):
        """delete_session 后 FTS5 记录同步删除"""
        with TestClient(app) as client:
            token, user_id = _register(client, "fts_del")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [{"role": "user", "content": "会被删除的消息"}]
            db.upsert_session(sid, user_id, msgs)

            result = db.delete_session(sid)
            assert result is True

            with db._conn() as conn:
                rows = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM messages_fts "
                    "WHERE session_id = ?",
                    (sid,),
                ).fetchone()
            assert rows["cnt"] == 0

    def test_empty_messages_not_indexed(self):
        """空消息（content 为空或纯空白）不被写入 FTS5"""
        with TestClient(app) as client:
            token, user_id = _register(client, "fts_empty")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [
                {"role": "user", "content": ""},
                {"role": "user", "content": "   "},
                {"role": "assistant", "content": "唯一有效消息"},
            ]
            db.upsert_session(sid, user_id, msgs)

            with db._conn() as conn:
                rows = conn.execute(
                    "SELECT content FROM messages_fts WHERE session_id = ?",
                    (sid,),
                ).fetchall()
            assert len(rows) == 1
            assert "唯一有效消息" in rows[0]["content"]

    def test_backfill_on_v2_migration(self, tmp_path):
        """v1 数据库迁移到 v2，已有会话回填到 FTS5"""
        import json as _json
        db_path = os.path.join(tmp_path, "test_backfill.db")

        # 手动创建 v1 数据库
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                title TEXT DEFAULT '', messages TEXT DEFAULT '[]',
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS user_configs (
                user_id TEXT PRIMARY KEY, roles TEXT DEFAULT '{}',
                models TEXT DEFAULT '[]',
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)
        uid = "backfill_user"
        sid = "backfill_session"
        conn.execute("INSERT INTO users (id, name) VALUES (?, ?)", (uid, "test"))
        messages = [
            {"role": "user", "content": "回填测试消息"},
            {"role": "assistant", "content": "收到，这条应该进 FTS5"},
        ]
        conn.execute(
            "INSERT INTO sessions (id, user_id, messages) VALUES (?, ?, ?)",
            (sid, uid, _json.dumps(messages, ensure_ascii=False)),
        )
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")
        conn.commit()
        conn.close()

        # 用 Database 打开，应触发 v2 迁移并回填
        from user.db import Database
        db = Database(db_path)
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT content FROM messages_fts WHERE session_id = ? "
                "ORDER BY msg_index",
                (sid,),
            ).fetchall()
        assert len(rows) == 2
        assert "回填测试" in rows[0]["content"]
        assert "这条应该进" in rows[1]["content"]
```

- [ ] **Step 6: 运行测试确认**

```bash
pytest tests/test_fts5.py::TestFts5Sync -v
```

预期：5 passed

- [ ] **Step 7: 提交**

```bash
git add user/db.py tests/test_fts5.py
git commit -m "feat: FTS5 虚拟表 + _sync_fts 同步 + v2 迁移回填"
```

---

### Task 3: search_messages 检索方法 + API 端点

**Files:**
- Modify: `user/db.py`（新增 `search_messages`）
- Modify: `user/routes.py`（新增 `GET /api/sessions/search`）
- Modify: `tests/test_fts5.py`（新增搜索测试）

**Interfaces:**
- Consumes:
  - `Database._conn()` from existing code
  - `session_router` from `user/routes.py` (Task 3 adds to it)
  - `_get_db(request)` and `require_auth` from `user/helpers.py`
- Produces:
  - `Database.search_messages(user_id, query, limit, offset) -> list[dict]`
  - `GET /api/sessions/search?q=...&limit=20&offset=0` → JSON

- [ ] **Step 1: 添加 `search_messages()` 方法**

在 `user/db.py` 的 `_sync_fts` 方法之后添加：

```python
    def search_messages(
        self, user_id: str, query: str,
        limit: int = 20, offset: int = 0,
    ) -> list[dict]:
        """全文检索用户会话消息。
        返回 [{session_id, msg_index, role, snippet}, ...]，按 FTS5 rank 排序。
        空查询 / 纯空白返回 []。"""
        q = (query or "").strip()
        if not q:
            return []
        # FTS5 转义：双引号是 FTS5 短语语法，需转义
        q = q.replace('"', '""')
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT session_id, msg_index, role, "
                "snippet(messages_fts, 4, '<mark>', '</mark>', '...', 40) "
                "AS snippet "
                "FROM messages_fts "
                "WHERE user_id = ? AND messages_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ? OFFSET ?",
                (user_id, q, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 2: 添加 `GET /api/sessions/search` 端点**

**重要：** `/search` 是静态路径，必须注册在 `/{session_id}` 动态路径之前，否则 FastAPI 会把 `"search"` 当作 `session_id` 参数匹配到错误的 handler。

在 `user/routes.py` 中，将新路由插入到 `list_sessions` (行83) 和 `save_session` (行108) 之间：

```python
# ─── 放在 GET "" (list_sessions) 之后，GET "/{session_id}" 之前 ───

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
```

同时在 `save_session` 的 `@session_router.post("")` 之前加回注释分隔：

```python
# ─── 以下为原有的 C(R)UD 路由 ───
```

- [ ] **Step 3: 编写搜索测试**

在 `tests/test_fts5.py` 中新增：

```python
class TestSearch:
    def test_chinese_keyword_match(self):
        """中文关键词匹配正确"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_cn")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [
                {"role": "user", "content": "如何用 Python 写网络爬虫"},
                {"role": "assistant",
                 "content": "你可以使用 requests + BeautifulSoup 来构建爬虫"},
                {"role": "user", "content": "请给我一个完整示例"},
            ]
            db.upsert_session(sid, user_id, msgs)

            results = db.search_messages(user_id, "爬虫")
            assert len(results) >= 1
            # 应该匹配到包含"爬虫"的那条
            snippets = [r["snippet"] for r in results]
            assert any("爬虫" in s for s in snippets)

    def test_snippet_has_highlight(self):
        """snippet() 片段包含 <mark> 高亮"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_hl")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [{"role": "user", "content": "如何部署 FastAPI 应用到生产环境"}]
            db.upsert_session(sid, user_id, msgs)

            results = db.search_messages(user_id, "FastAPI")
            assert len(results) >= 1
            assert "<mark>" in results[0]["snippet"]
            assert "FastAPI" in results[0]["snippet"]

    def test_user_isolation(self):
        """user_id 隔离生效：用户 A 搜不到用户 B 的消息"""
        with TestClient(app) as client:
            token_a, uid_a = _register(client, "iso_a")
            token_b, uid_b = _register(client, "iso_b")
            db = app.state.db

            sid_a = f"test_{uuid.uuid4().hex[:8]}"
            db.upsert_session(sid_a, uid_a, [
                {"role": "user", "content": "用户A的秘密消息"}
            ])

            # 用户 B 搜索用户 A 的内容
            results = db.search_messages(uid_b, "秘密消息")
            assert len(results) == 0

    def test_special_characters_safe(self):
        """特殊字符不导致 SQL 错误"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_sp")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [{"role": "user", "content": '包含"双引号"的查询'}]
            db.upsert_session(sid, user_id, msgs)

            # 不应抛出异常
            results = db.search_messages(user_id, '"双引号"')
            assert isinstance(results, list)

    def test_empty_query_returns_empty(self):
        """空查询 / 纯空白返回空列表"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_emp")
            db = app.state.db

            assert db.search_messages(user_id, "") == []
            assert db.search_messages(user_id, "   ") == []

    def test_no_match_returns_empty(self):
        """无匹配结果时返回空列表"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_nom")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [{"role": "user", "content": "天气真好"}]
            db.upsert_session(sid, user_id, msgs)

            results = db.search_messages(user_id, "量子力学")
            assert results == []

    def test_search_api_endpoint(self):
        """GET /api/sessions/search API 端点正常工作"""
        with TestClient(app) as client:
            token, user_id = _register(client, "srch_api")
            db = app.state.db

            sid = f"test_{uuid.uuid4().hex[:8]}"
            msgs = [{"role": "user", "content": "端到端测试消息内容"}]
            db.upsert_session(sid, user_id, msgs)

            resp = client.get(
                "/api/sessions/search?q=端到端测试",
                headers=_auth(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1
            assert data[0]["session_id"] == sid

    def test_search_api_requires_auth(self):
        """搜索 API 需要认证"""
        with TestClient(app) as client:
            resp = client.get("/api/sessions/search?q=test")
            assert resp.status_code == 401
```

- [ ] **Step 4: 运行测试确认**

```bash
pytest tests/test_fts5.py::TestSearch -v
```

预期：8 passed

- [ ] **Step 5: 提交**

```bash
git add user/db.py user/routes.py tests/test_fts5.py
git commit -m "feat: search_messages 全文检索 + GET /api/sessions/search 端点"
```

---

### Task 4: Lifespan 关闭时 WAL 检查点

**Files:**
- Modify: `main.py:52-57`（lifespan 函数）
- Modify: `tests/test_fts5.py`（新增 WAL checkpoint 测试）

**Interfaces:**
- Consumes: `Database._conn()` from existing code
- Produces: lifespan shutdown 执行 `PRAGMA wal_checkpoint(TRUNCATE)`

- [ ] **Step 1: 更新 lifespan 函数**

替换 `main.py` 第52-57行的 `lifespan`：

```python
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
        pass
```

- [ ] **Step 2: 验证既有测试未破坏**

```bash
pytest tests/test_knowledge_routes.py tests/test_fts5.py -v
```

预期：所有已有测试 + 新测试全部通过

- [ ] **Step 3: 提交**

```bash
git add main.py
git commit -m "feat: lifespan shutdown 强制执行 PRAGMA wal_checkpoint(TRUNCATE)"
```

---

### Task 5: 全量回归测试

**Files:**
- Modify: `tests/test_fts5.py`（无新增，仅验证）

**Interfaces:**
- Consumes: 所有前序任务的产物

- [ ] **Step 1: 运行全部测试**

```bash
pytest tests/ -v
```

预期：所有测试通过（约 19+ 个）

- [ ] **Step 2: 手动验证应用启动**

```bash
timeout 5 python -c "from user.db import Database; print('DB init OK')"
```

预期：输出 `DB init OK`，无 RuntimeError

- [ ] **Step 3: 验证向后兼容**

```bash
python -c "
import os, sys
sys.path.insert(0, '.')
from user.db import Database
db = Database('data.db')
# 已有数据不变
print('Users:', len(db.get_user_by_id('nonexistent') or {}))
print('WAL OK')
"
```

预期：运行成功，无异常

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "test: 全量回归验证通过 — FTS5 + WAL checkpoint + 迁移校验"
```
