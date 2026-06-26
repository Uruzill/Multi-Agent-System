# 多智能体协作系统 — API 接口文档 v3.5

> 前端（张磊）←→ 后端（曾瑞安，高晟然，张耘赫）
> 本文件记录所有接口，供前后端独立开发。

---

## 目录

1. [聊天接口](#1-聊天接口)
2. [报告生成](#2-报告生成)
3. [认证与用户配置](#3-认证与用户配置)
4. [会话管理](#4-会话管理)
5. [知识库](#5-知识库)
6. [静态文件](#6-静态文件)

---

## 1. 聊天接口

### POST /api/chat

处理用户消息，返回 Agent 协作结果。

**请求体：**

```json
{
  "message": "分析各产品销售额占比",
  "lane_mode": "auto",
  "history": [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你？"}
  ],
  "model_config": {
    "Planner": "DeepSeek Flash",
    "Coder": "Qwen 7B",
    "Tester": "DeepSeek Flash"
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | str | 是 | 用户输入 |
| `lane_mode` | str | 否 | `auto` / `fast` / `slow`，默认 `auto` |
| `history` | list | 否 | 历史消息，用于上下文摘要 |
| `model_config` | dict | 否 | 角色→模型映射 |

**响应：**

```json
{
  "reply": "分析完成！已生成柱状图和详细报告。",
  "thinking": [
    {"name": "Planner", "content": "## 执行计划\n1. 读取数据..."},
    {"name": "Coder", "content": "```python\nimport pandas...```"},
    {"name": "Tester", "content": "✅ 代码正确"},
    {"name": "Summarizer", "content": "## 分析报告..."}
  ],
  "task_type": "分析",
  "speaking_log": [
    {"from": "User", "to": "Planner"},
    {"from": "Planner", "to": "Coder"}
  ],
  "generated_files": [
    {"name": "sales_chart.png", "path": "coding/sales_chart.png", "ext": "png"}
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `reply` | str | 最终回复文本 |
| `thinking` | list[dict] | Agent 发言列表（name + content） |
| `task_type` | str | 编程 / 写作 / 分析 / 问答 / 闲聊 |
| `speaking_log` | list[dict] | 发言顺序记录 |
| `generated_files` | list[dict] | 生成的文件列表（name + path + ext） |

---

## 2. 报告生成

### POST /api/report

从 thinking 记录生成结构化报告。

**请求体：**

```json
{
  "thinking": [
    {"name": "Planner", "content": "..."},
    {"name": "Coder", "content": "..."}
  ]
}
```

**响应：**

```json
{
  "content": "# 报告标题\n## ...",
  "path": "reports/report_1719130000.md"
}
```

---

## 3. 认证与用户配置

### POST /api/auth/register

注册新用户。

**请求体：**
```json
{"name": "alice", "password": "secret123"}
```

**响应：**
```json
{"token": "<jwt>", "user_id": "abc12345", "name": "alice"}
```

### POST /api/auth/login

登录。

**请求体：**
```json
{"name": "alice", "password": "secret123"}
```

**响应：** 同 register

### GET /api/auth/me

获取当前用户信息（需 Authorization: Bearer \<token\>）。

### GET /api/auth/system-config

获取系统默认模型配置（无需认证）。

**响应：**
```json
{
  "default_roles": {"Planner": "a-deepseek", ...},
  "model_pool": {"a-deepseek": {"model": "deepseek-v4-flash", ...}}
}
```

### GET /api/user/config

获取当前用户角色配置（需认证）。

### PUT /api/user/config

保存当前用户角色配置（需认证）。

### POST /api/user/custom-models

添加自定义模型（需认证）。

### DELETE /api/user/custom-models/{key}

删除自定义模型（需认证）。

---

## 4. 会话管理（需认证）

> SQLite 持久化 + FTS5 全文索引，按用户隔离。

### GET /api/sessions

列出当前用户的所有会话摘要。

**响应：**
```json
[
  {
    "id": "1719130000000",
    "title": "分析各产品销售额占比",
    "count": 6,
    "updated": "2026-06-26 15:30"
  }
]
```

### GET /api/sessions/search?q=xxx&limit=20&offset=0

**FTS5 全文检索**当前用户的会话消息，按相关度排序。返回带高亮片段的匹配结果。

**响应：**
```json
[
  {
    "session_id": "1719130000000",
    "msg_index": 3,
    "role": "assistant",
    "snippet": "...用<mark>爬虫</mark>抓取数据..."
  }
]
```
> 前端用 `session_id` 加载对应会话，`msg_index` 滚动到匹配消息。

### POST /api/sessions

保存/创建会话（同步写入 FTS5 索引）。

**请求体：**
```json
{
  "id": "1719130000000",
  "title": "会话标题",
  "messages": [
    {"role": "user", "content": "分析数据"},
    {"role": "assistant", "content": "分析完成..."}
  ]
}
```

**响应：**
```json
{"id": "1719130000000", "status": "ok"}
```

### GET /api/sessions/{session_id}

获取单个会话的完整消息（校验归属）。

### DELETE /api/sessions/{session_id}

删除指定会话（同步清理 FTS5 索引）。

---

## 5. 知识库

> 路由注册在 `app/knowledge.py`，前缀 `/api/knowledge`

### GET /api/knowledge/stats

获取知识库统计信息。

### POST /api/knowledge/rebuild

重建知识库索引。

### POST /api/knowledge/upload

上传文档到知识库。

---

## 6. 静态文件

| 路由 | 说明 |
|------|------|
| `/` | 聊天主页 |
| `/static/*` | 静态文件（CSS, JS） |
| `/coding/*` | 生成的代码和图片文件 |

---

*更新日期：2026-06-23*
