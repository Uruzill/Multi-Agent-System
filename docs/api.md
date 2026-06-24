# 多智能体协作系统 — API 接口文档 v3.1

> 前端（张磊）←→ 后端（曾瑞安）
> 本文件记录所有现有及新增接口，供前后端独立开发。

---

## 目录

1. [聊天接口](#1-聊天接口)
2. [报告生成](#2-报告生成)
3. [模型配置（新增）](#3-模型配置新增)
4. [会话管理（新增）](#4-会话管理新增)
5. [文件上传（新增）](#5-文件上传新增)
6. [知识库](#6-知识库)
7. [静态文件](#7-静态文件)

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
  },
  "file_ids": ["f_1719130000_a1b2c3"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | str | 是 | 用户输入 |
| `lane_mode` | str | 否 | `auto` / `fast` / `slow`，默认 `auto` |
| `history` | list | 否 | 历史消息，用于上下文摘要 |
| `model_config` | dict | 否 | 角色→模型映射 |
| `file_ids` | list[str] | 否 | 已上传的文件 ID 列表，后端读取后注入 Agent 上下文 |

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

## 3. 模型配置（新增）

> 运行时动态管理模型池和角色映射，存内存。

### POST /api/config/roles

保存角色→模型映射。

**请求体：**

```json
{
  "roles": {
    "Planner": "DeepSeek Flash",
    "Coder": "Qwen 7B",
    "Tester": "DeepSeek Pro"
  }
}
```

**响应：**

```json
{"status": "ok"}
```

### GET /api/config/roles

获取当前角色→模型映射。

**响应：**

```json
{
  "roles": {
    "Planner": "DeepSeek Flash",
    "Coder": "Qwen 7B",
    "Tester": "DeepSeek Pro"
  }
}
```

### POST /api/config/models

添加自定义模型到模型池。

**请求体：**

```json
{
  "name": "claude-3-opus",
  "base_url": "https://api.anthropic.com/v1",
  "api_key": "sk-ant-..."
}
```

**响应：**

```json
{"status": "ok"}
```

### DELETE /api/config/models/{model_name}

从模型池删除指定模型。

**响应：**

```json
{"status": "ok"}
```

---

## 4. 会话管理（新增）

> JSON 文件存储（sessions.json），后续可换数据库。

### GET /api/sessions

列出所有会话摘要。

**响应：**

```json
[
  {
    "id": "1719130000000",
    "title": "分析各产品销售额占比",
    "count": 6,
    "updated": "2026-06-23 15:30"
  }
]
```

### POST /api/sessions

保存/创建会话。

**请求体：**

```json
{
  "id": "1719130000000",
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

获取单个会话的完整消息。

**响应：**

```json
{
  "messages": [...],
  "updated": "2026-06-23 15:30"
}
```

### DELETE /api/sessions/{session_id}

删除指定会话。

**响应：**

```json
{"status": "ok"}
```

---

## 5. 文件上传（新增）

> 前端上传附件到后端，返回 file_id 供聊天接口引用。

### POST /api/upload

上传文件。

**请求：** `multipart/form-data`，字段名 `file`

**成功响应 (200)：**
```json
{
  "file_id": "f_1719130000_a1b2c3",
  "name": "数据报告.pdf",
  "size": 204800,
  "ext": "pdf"
}
```

**失败响应 (4xx)：**
```json
{
  "error": "文件大小不能超过 10MB"
}
```

### GET /uploads/{file_id}/{filename}

访问已上传的原始文件（前端预览用）。

### 存储约定

```
uploads/
  f_1719130000_a1b2c3/
    数据报告.pdf       ← 原始文件，保留原名
    meta.json          ← {name, size, ext, original_name}
```

后端收到 `file_ids` 后，根据文件类型处理：
- **图片**（png/jpg/gif）→ 转文字描述，注入 Agent 上下文
- **文档**（pdf/txt/md）→ 提取文本，注入 Agent 上下文
- **代码**（py/js/java）→ 原文注入，供 Agent 分析/修改

---

## 6. 知识库

> 路由注册在 `app/knowledge.py`，前缀 `/api/knowledge`

### GET /api/knowledge/stats

获取知识库统计信息。

### POST /api/knowledge/rebuild

重建知识库索引。

### POST /api/knowledge/upload

上传文档到知识库。

---

## 7. 静态文件

| 路由 | 说明 |
|------|------|
| `/` | 聊天主页 |
| `/static/*` | 静态文件（CSS, JS） |
| `/coding/*` | 生成的代码和图片文件 |
| `/uploads/{file_id}/*` | 用户上传的附件文件 |

---

*更新日期：2026-06-24*
