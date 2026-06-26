# 会话 FTS5 全文索引 & Lifespan 迁移校验 / WAL 检查点 — 设计文档

**日期**: 2026-06-26
**分支**: Fahaxik1oxxx
**状态**: 已确认

---

## 1. 概述

本次优化包含两个独立但相关的子任务，均在数据库层实现：

1. **会话内容 FTS5 全文索引** — 对 `sessions.messages` JSON 中的对话内容建立 SQLite FTS5 虚拟表，支持消息粒度的全文检索，实现语义级搜索。
2. **Lifespan 启动迁移校验 + 关闭 WAL 检查点** — 启动时执行 schema 版本比对与自动迁移；关闭时强制执行 `PRAGMA wal_checkpoint(TRUNCATE)`，确保 WAL 文件内容写入主数据库。

两处改动共享 `user/db.py` 中的 `Database` 类，保持统一的数据访问入口。

---

## 2. 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| FTS5 索引粒度 | **消息粒度** — 每条消息一个 FTS5 行 | 精确定位到具体消息，前端可高亮匹配片段 |
| 检索权限 | **仅当前用户** — `require_auth` 隔离 | 与现有 `/api/sessions` 风格一致 |
| 迁移校验程度 | **轻量校验** — `schema_version` 表 + 版本比对 | 当前项目体量（4 张表）不需要完整迁移框架 |

---

## 3. 架构

```
main.py  ─── lifespan (启动/关闭钩子)
                │
                ▼
user/db.py ─── Database 类
                ├── schema_version 表 (新增)
                ├── messages_fts 表 (新增 FTS5)
                ├── migrate()            (新增)
                ├── _sync_fts()          (新增)
                ├── search_messages()    (新增)
                └── _init_db()           (改造：版本驱动建表)
                │
                ▼
user/routes.py ── GET /api/sessions/search?q=xxx  (新增)
```

**数据流 — FTS5 同步:**
```
POST /api/sessions (保存会话)
        │
        ▼
upsert_session()
        │
        ├── 1. INSERT/UPDATE sessions 表
        └── 2. DELETE + INSERT messages_fts  ← _sync_fts()
```

**数据流 — 启动迁移:**
```
uvicorn 启动 → lifespan 进入 → Database.__init__()
                                    │
                                    ├── PRAGMA journal_mode=WAL
                                    ├── 建 schema_version 表（如无）
                                    ├── 读当前版本 → 比对 TARGET
                                    ├── 执行缺失迁移（幂等 DDL）
                                    └── 回填已有 sessions 到 FTS5（v2 迁移）
```

---

## 4. FTS5 全文索引

### 4.1 虚拟表结构

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    session_id,
    user_id,
    msg_index,
    role,
    content,
    tokenize='unicode61'
);
```

### 4.2 同步策略

手动同步，不放触发器。同步点：

- **`upsert_session()`** — 保存/更新会话后立即调用 `_sync_fts()`。
- **`delete_session()`** — 删除会话后同步清理 FTS5 行。
- **数据迁移 (v2)** — 对已有 `sessions` 做一次性回填。

`_sync_fts(conn, session_id, user_id, messages)` 接收外层传入的连接对象，在 `upsert_session` / `delete_session` 的 `with self._conn()` 块内调用，确保与 `sessions` 表操作共享同一事务。采用"先删后插"模式：

1. `DELETE FROM messages_fts WHERE session_id = ?`
2. 遍历 `messages` JSON 数组，逐条 `INSERT`

共用事务保证 `sessions` 和 `messages_fts` 的原子性——写 sessions 失败则 FTS5 也不会变更，反之亦然。

### 4.3 检索方法

```python
def search_messages(
    self, user_id: str, query: str, limit: int = 20, offset: int = 0
) -> list[dict]:
    """返回 [{session_id, msg_index, role, snippet}, ...]"""
```

- 使用 FTS5 `snippet()` 函数生成高亮片段（`<mark>...</mark>`）。
- `WHERE user_id = ?` 保证用户隔离。
- `ORDER BY rank` — FTS5 内置相关度排序。
- 对用户输入做 FTS5 转义（`"` → `""`），防止语法错误。
- 空查询/纯空白返回空列表。

### 4.4 API 端点

```
GET /api/sessions/search?q=<query>&limit=20&offset=0
Authorization: Bearer <token>
```

**响应:**
```json
[
  {
    "session_id": "abc123",
    "msg_index": 3,
    "role": "assistant",
    "snippet": "...用<mark>python爬虫</mark>抓取数据..."
  }
]
```

前端可用 `session_id` 加载对应会话，用 `msg_index` 滚动到匹配消息。

---

## 5. Schema 版本管理与迁移

### 5.1 版本表

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT DEFAULT (datetime('now', 'localtime'))
);
```

### 5.2 版本常量

```python
TARGET_SCHEMA_VERSION = 2
# 0 → 无数据库 / 未初始化
# 1 → 初始表: users, sessions, user_configs
# 2 → 新增: messages_fts (FTS5)
```

### 5.3 迁移流程

`_init_db()` 启动时：

1. 执行 `PRAGMA journal_mode=WAL` 和 `PRAGMA foreign_keys=ON`
2. 确保 `schema_version` 表存在
3. 读取 `MAX(version)` 作为当前版本（无记录则为 0）
4. **版本 > TARGET** → 抛出 `RuntimeError`，拒绝启动
5. **版本 < TARGET** → 循环执行 `_run_migration(v)`，每步成功后写入 `schema_version`
6. 迁移全部在同一连接/事务内

### 5.4 迁移函数

```python
def _run_migration(self, conn, version: int):
    if version == 1:
        # 初始建表（幂等 — 全部使用 IF NOT EXISTS）
        ...
    elif version == 2:
        # 创建 FTS5 虚拟表 + 回填已有数据
        ...
```

后续 schema 变更只需增加 `elif version == 3` 分支并递增 `TARGET_SCHEMA_VERSION`。

---

## 6. WAL 检查点

### 6.1 shutdown 处理

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = Database(db_path)
    app.state.db = db
    yield
    # 强制 WAL checkpoint
    try:
        with db._conn() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        pass
```

`TRUNCATE` 模式：checkpoint 成功后将 `-wal` 文件截零，确保关闭后无残留。对容器化部署和文件备份友好。

checkpoint 失败时静默处理——WAL 文件在下次启动时由 SQLite 自动恢复，不影响数据完整性。

---

## 7. 错误处理与边界情况

| 场景 | 处理 |
|------|------|
| 搜索含 FTS5 特殊字符（`"`, `*` 等） | 转义：`query.replace('"', '""')` |
| 空查询 / 纯空白 | 直接返回 `[]`，不查数据库 |
| FTS5 同步失败 | 与 `upsert_session` 在同一事务，自动回滚 |
| 迁移回填大量数据 | 单事务；当前数据量级足够 |
| 数据库版本超前 | `RuntimeError` → uvicorn 启动失败，日志明确提示 |
| WAL checkpoint 失败 | 静默 pass，SQLite 下次启动自动恢复 |
| 数据库文件不存在 | `sqlite3.connect()` 自动创建；`schema_version` 为空 → 从 v1 开始迁移 |

---

## 8. 测试策略

### 8.1 FTS5 同步

- `upsert_session` 后 FTS5 可检索到新消息
- 更新会话后旧消息在 FTS5 中被替换
- `delete_session` 后 FTS5 记录同步删除
- 空消息（`content` 为空或纯空白）不被写入 FTS5

### 8.2 搜索

- 中文关键词匹配正确
- `snippet()` 片段包含 `<mark>` 高亮

<｜｜DSML｜｜parameter name="content" string="true">- user_id 隔离生效
- 特殊字符（`"`, `*`）不导致 SQL 错误
- 无匹配结果时返回空列表

### 8.3 迁移

- 空白数据库 → 直接到 v2，所有表创建正确
- v1 数据库 → 迁移到 v2，已有会话回填到 FTS5
- 版本超前 → `RuntimeError` 拒绝启动
- 幂等：重复运行不报错

### 8.4 WAL checkpoint

- 正常关闭后 `data.db-wal` 文件被截零或删除
- checkpoint 异常不阻塞进程退出

---

## 9. 改动范围

| 文件 | 改动 |
|------|------|
| `user/db.py` | `+schema_version` 表, `+messages_fts` 表, `+_sync_fts()`, `+search_messages()`, `+_run_migration()`, 改造 `_init_db()` |
| `user/routes.py` | `+GET /api/sessions/search` 端点 |
| `main.py` | lifespan shutdown 加 `wal_checkpoint(TRUNCATE)` |

- 无新依赖
- 无配置项变更
- 向后兼容（FTS5 为空时搜索返回空列表）
