# 多智能体协作系统 v3.4

<div align="center">

**基于 LangGraph + LangChain 的七角色多智能体协作系统**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![daisyUI](https://img.shields.io/badge/daisyUI-5-purple.svg)](https://daisyui.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## 📖 项目简介

一个由 **7 个专业 AI Agent** 组成的多智能体协作系统。用户用自然语言描述需求，系统自动识别任务意图，通过 **LangGraph 状态图**编排多个 Agent 按流程协作，完成编程开发、报告撰写、数据分析、知识问答等复杂任务。

**核心特色：** Router 自动意图分类 → 快慢双车道 → 7 Agent 协作流水线 → exitcode 确定性分支 → 代码修复循环 → 结构化报告输出 → 用户隔离认证。

---

## ✨ 核心功能

### 🤖 七大专业 Agent

| Agent | 角色 | 能力 |
|:-----:|------|------|
| 📋 **Planner** | 规划师 | 拆解复杂任务为可执行步骤清单 |
| 🤖 **Bot** | 快车道接待 | 轻任务秒级直接回复 |
| 🔍 **Retriever** | 检索员 | 查询 ChromaDB 知识库获取背景信息 |
| 💻 **Coder** | 程序员 | Python 代码编写 + 数据分析 + 图表生成 |
| ✍️ **Writer** | 撰稿人 | 报告/方案/文章撰写，支持引用知识库 |
| ✅ **Tester** | 审查员 | 代码质量评审 + 文档内容检查 |
| 📊 **Summarizer** | 汇总师 | 汇总全流程，输出结构化 Markdown 报告 |

### 🧠 智能任务调度

- **自动意图分类**：Router LLM 识别 5 种任务类型（编程/写作/分析/问答/闲聊）+ 轻/重复杂度
- **快慢双车道**：轻任务 Bot 秒级回复，重任务 7 Agent 完整流水线
- **三层安全网**：关键词正则检测兜底 Router 误判
- **确定性路由**：exitcode 驱动代码修复分支，不受 LLM 幻觉影响
- **自动修复循环**：代码执行失败时自动重试修复（上限 2 轮）

### 🔧 工具链

| 工具 | 功能 |
|------|------|
| `search_knowledge` | ChromaDB 向量语义检索 |
| `read_file` / `write_file` | 文件读写 |
| `calculate` | AST 安全数学表达式计算 |
| `analyze_data` | Pandas 数据分析（CSV/Excel） |
| `visualize_data` | Pillow 图表生成（柱状图/折线图） |
| `ocr_image` | Tesseract 中英文图片 OCR |

### 👤 用户隔离与认证系统

- **注册/登录**：用户名 + 密码注册，bcrypt 哈希存储，UUID Token 鉴权
- **会话隔离**：每个注册用户只能访问自己的对话历史
- **知识库隔离**：每个用户独立的 ChromaDB 向量库和文档目录
- **游客模式**：无需注册即可聊天，对话存浏览器 sessionStorage，关标签页即清除
- **数据迁移**：游客登录后对话自动迁移到数据库，不丢失历史
- **Token 过期与续期**：Token 7 天自动过期，使用中自动续期，兼顾安全与体验
- **登录限流**：同一用户名 5 次失败后 15 分钟禁止登录，防暴力破解

### 🛡️ 安全防护

| 防护层 | 实现方式 |
|--------|----------|
| Docker 沙箱 | 代码执行在 Docker 容器中隔离运行，替代 subprocess |
| 密码哈希 | bcrypt + 随机盐，恒时比较防时序攻击 |
| 登录限流 | 5 次失败 / 15 分钟锁定，防暴力破解 |
| SQL 注入防护 | 100% 参数化查询，无字符串拼接 |
| 路径遍历防护 | `os.path.basename()` 消毒文件名 |
| Docker 降级 | Docker 不可用时自动降级为 subprocess，系统不中断 |

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- DeepSeek API Key
- Tesseract-OCR（可选）

### 安装

```bash
git clone https://github.com/Uruzill/Multi-Agent-System.git
cd Multi-Agent-System
pip install -r requirements.txt
```

### 配置

在项目根目录创建 `.env` 文件：

```bash
DEEPSEEK_API_KEY=你的DeepSeek-API-Key
```

也可设置系统环境变量 `DEEPSEEK_API_KEY`。`.env` 文件优先级更高，已加入 `.gitignore` 避免泄露。

### 启动

```bash
python main.py
```

浏览器打开 **http://localhost:8502** 即可使用。

### 可选：安装 Tesseract-OCR

- **Windows**：[UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
- **macOS**：`brew install tesseract`
- **Linux**：`sudo apt install tesseract-ocr`

---

## 🏗️ 系统架构

```
用户输入（自然语言）
    │
    ▼
┌──────────────────────────────────────────┐
│           Router 意图分类器               │
│  编程/写作/分析/问答/闲聊 + 轻/重          │
│  + 关键词覆写安全网（三层正则检测）         │
└──────────────────────────────────────────┘
    │
    ├─ 轻任务 ──→ Bot 快车道（< 3s 回复）
    │
    └─ 重任务 ──→ 慢车道 7 Agent 流水线
                  │
    ┌─────────────┴─────────────────────────┐
    │  Planner → Retriever → Coder/Writer   │
    │     → Executor → Tester → Summarizer  │
    │         ↑          │                   │
    │         └─ 修复(≤2轮) ← exitcode ≠ 0  │
    └──────────────────────────────────────────┘
                  │
                  ▼
          结构化 Markdown 报告 + 执行日志
```

### 慢车道流水线详解

| 步骤 | Agent | 动作 |
|:----:|-------|------|
| 1 | 📋 Planner | 拆解任务为步骤清单 |
| 2 | 🔍 Retriever | 从 ChromaDB 知识库检索相关资料 |
| 3 | 💻/✍️ Coder/Writer | 根据任务类型编写代码或撰写文稿 |
| 4 | ⚙️ Executor | subprocess 沙箱执行代码 |
| 5 | ✅ Tester | 评审代码/文档质量，输出 ✅ 或 ❌ |
| 6 | 📊 Summarizer | 汇总全流程，生成结构化报告 |

### 用户认证架构

```
游客（无 Token）                    注册用户（Bearer Token）
  │                                     │
  ├─ 会话 → sessionStorage              ├─ 会话 → SQLite（仅自己可见）
  ├─ 知识库 → 不可用（401）              ├─ 知识库 → rag/<user_id>/
  └─ 登录 → 迁移对话 → 获得 Token        └─ 退出 → Token 删除 → 回到游客态
```

---

## 📁 项目结构

```
Multi-Agent-System/
├── main.py                  # FastAPI 入口
├── config.py                # LLM 模型配置
├── router.py                # Router 意图分类器
├── workflow.py              # LangGraph 工作流编排
├── executor.py              # Docker/subprocess 代码执行沙箱
├── agents.py                # 7 个 Agent System Prompt 定义
├── tools.py                 # 7 个 LangChain 工具
├── config.py                # 模型池 & 角色映射（ROLES / MODEL_POOL / ROLE_MODEL）
├── requirements.txt         # Python 依赖清单
├── .env.example             # 环境变量模板
├── LICENSE                  # MIT 开源许可
│
├── user/                    # 用户管理模块
│   ├── __init__.py          # 包标识
│   ├── auth.py              # bcrypt 密码哈希 + JWT 创建/解码
│   ├── db.py                # SQLite CRUD（users/sessions/user_configs）+ FTS5 全文索引 + schema 迁移
│   ├── helpers.py           # require_auth 依赖 + _get_db
│   └── routes.py            # 认证 / 会话 / 用户配置 / 会话搜索 API 路由
│
├── app/
│   ├── __init__.py          # 包标识
│   ├── chat.py              # 聊天管道（Router + 关键词覆写 + 90s 超时）
│   ├── knowledge.py         # 知识库管理 API（Token 鉴权）
│   └── ocr.py               # Tesseract OCR 模块
│
├── templates/               # Jinja2 模板（daisyUI + Tailwind CSS）
│   ├── base.html            # 布局骨架
│   ├── index.html           # 聊天主页面
│   └── components/
│       └── sidebar.html     # 侧边栏（含注册/登录/知识库/历史）
│
├── static/
│   ├── css/custom.css       # 自定义样式
│   └── js/chat.js           # 前端交互逻辑（Token 管理 + 会话）
│
├── rag/
│   ├── knowledge_base.py    # ChromaDB 向量数据库（按用户物理隔离）
│   ├── documents/           # 知识文档（按 user_id 分目录）
│   └── chroma_db/           # 向量数据库（按 user_id 分目录）
│
├── tests/
│   ├── test_knowledge_routes.py  # 9 个知识库 API 测试
│   └── test_fts5.py              # 17 个 FTS5 全文检索 + 迁移 + WAL 测试
│
├── docs/
│   ├── api.md               # API 文档
│   ├── user.md              # 用户管理体系设计
│   ├── 答辩报告.md           # 项目答辩报告
│   ├── 项目要求.txt          # 实训项目要求
│   └── superpowers/         # 设计文档与实现计划
│
└── README.md                # 本文件
```

---

## 🌐 API 接口

### 聊天与报告
*
| 方法 | 路径 | 鉴权 | 说明 |
|------|------|:----:|------|
| `GET` | `/` | 无 | 聊天页面 |
| `POST` | `/api/chat` | 无 | 发送消息 |
| `POST` | `/api/report` | 无 | 生成 Markdown 报告 |

### 认证系统

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|:----:|------|
| `POST` | `/api/auth/register` | 无 | 注册 → 返回 Token |
| `POST` | `/api/auth/login` | 无 | 登录 → 返回 Token |
| `POST` | `/api/auth/logout` | 需 | 退出 → 删除 Token |
| `GET` | `/api/auth/me` | 需 | 获取当前用户信息 |

### 知识库管理（需 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/knowledge/stats` | 文档数 + 切片数统计 |
| `POST` | `/api/knowledge/rebuild` | 重建索引 |
| `POST` | `/api/knowledge/upload` | 上传文档（PDF/TXT/PNG/JPG） |
| `DELETE` | `/api/knowledge/{filename}` | 删除文档 |

### 会话管理（需 Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 列出用户会话 |
| `GET` | `/api/sessions/search?q=xxx` | **全文检索会话消息**（FTS5，带高亮片段） |
| `POST` | `/api/sessions` | 保存/创建会话 |
| `GET` | `/api/sessions/{id}` | 获取会话（校验归属） |
| `DELETE` | `/api/sessions/{id}` | 删除会话（校验归属） |

### 配置管理

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|:----:|------|
| `GET` | `/api/auth/system-config` | 无 | 系统默认模型配置 |
| `GET` | `/api/user/config` | 需 | 获取用户角色映射 |
| `PUT` | `/api/user/config` | 需 | 保存用户角色映射 |
| `POST` | `/api/user/custom-models` | 需 | 添加自定义模型 |
| `DELETE` | `/api/user/custom-models/{key}` | 需 | 删除自定义模型 |

---

## 🧪 运行测试

```bash
pytest tests/ -v
```

26 个测试用例覆盖认证 + 知识库 + FTS5 全文检索 + 迁移：

**认证 & 知识库 (9):**
- ✅ 用户注册 / 登录 / Token 获取
- ✅ 知识库统计 / 索引重建 / 文件上传 / 非法类型拦截
- ✅ 文档删除 / 删除不存在的文档

**FTS5 全文检索 & 迁移 (17):**
- ✅ Schema 版本管理（空白库 → v2 / 版本超前拒绝 / 幂等）
- ✅ FTS5 同步（创建 / 更新 / 删除 / 空消息过滤 / 回填）
- ✅ 全文搜索（中文匹配 / 高亮片段 / 用户隔离 / 特殊字符 / 空查询 / API 端点 / 鉴权）
- ✅ WAL checkpoint 执行

---

## 📊 版本历史

| 版本 | 日期 | 关键变化 |
|------|------|---------|
| v1.0 | 06-11 | 4 Agent AG2，仅编程任务，控制台交互 |
| v2.0 | 06-14 | 8 Agent + Router，Streamlit 前端，ChromaDB RAG |
| v2.1 | 06-17 | UI/UX 优化，非 Python 语言拦截，90s 软超时 |
| v3.0 | 06-22 | AG2 → LangGraph 迁移，Tesseract OCR，手动快慢车道 |
| v3.1 | 06-23 | Streamlit → FastAPI Web，Router 恢复，5 任务类型，exitcode 分支 |
| v3.2 | 06-24 | daisyUI 前端重构，SQLite 用户/会话持久化，lifespan 启动 |
| **v3.3** | **06-24** | **用户认证系统（bcrypt + Token），知识库/会话用户隔离，游客 sessionStorage** |
| **v3.4** | **06-24** | **Docker 沙箱隔离，Token 7 天过期+续期，登录限流，安全防护升级至 10 层** |
| **v3.5** | **06-26** | **FTS5 全文检索 + Schema 版本自动迁移 + WAL checkpoint + config.py 重构** |
| **v3.3** | **06-24** | **用户认证系统（bcrypt + Token），知识库/会话用户隔离，游客 sessionStorage** |
| **v3.4** | **06-24** | **Docker 沙箱隔离，Token 7 天过期+续期，登录限流，安全防护升级至 10 层** |

---

## 🛠️ 技术栈

| 领域 | 技术 |
|------|------|
| Agent 编排 | LangGraph ≥0.2（StateGraph + 条件路由） |
| Agent 实现 | LangChain ≥0.3（ChatDeepSeek + @tool） |
| 大语言模型 | DeepSeek V4 Flash |
| Web 框架 | FastAPI ≥0.115 + Jinja2 ≥3.1 |
| CSS 框架 | daisyUI 5 + Tailwind CSS 4 |
| 前端交互 | 原生 JavaScript（fetch + DOM） |
| 数据库 | SQLite（WAL 模式 + FTS5 全文索引 + Schema 版本自动迁移） |
| 密码哈希 | bcrypt ≥4.0 |
| 容器沙箱 | Docker |
| 向量数据库 | ChromaDB ≥1.5 |
| 嵌入模型 | BAAI/bge-small-zh-v1.5（33MB，离线加载） |
| OCR | Tesseract + Pillow |
| 测试 | pytest + FastAPI TestClient |

---

## 📝 许可

MIT License

---

*西北农林科技大学 · 2026 人工智能实训 · 独立拓展项目*
