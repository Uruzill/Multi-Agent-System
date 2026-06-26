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
            assert len(results) >= 1

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


class TestWalCheckpoint:
    def test_wal_checkpoint_executes_without_error(self):
        """验证 WAL checkpoint SQL 可以正常执行，不抛出异常"""
        with TestClient(app) as client:
            _register(client, "wal_cp")
            db = app.state.db
            # checkpoint 应在不抛出异常的情况下执行
            with db._conn() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            # 测试通过即表示 checkpoint 执行无异常
