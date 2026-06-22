# 多智能体协作系统 2.0 (Multi-Agent)

基于 AG2 框架的八角色多智能体协作系统，支持编程/写作/分析/问答/闲聊 5 种任务自动分支路由，集成 RAG 知识库、快慢车道分离与 Streamlit 聊天界面。

---

## 1 项目概述

本系统将任务拆分为 **7 个专业角色**，由 LLM 驱动协作完成。

### 1.1 支持的任务类型

| 类型 | 示例 | Pipeline |
|------|------|----------|
| **编程** | "写一个快排" / "实现 LRU Cache" | coding 慢车道：Planner→RAG→Coder→Tester→User→Summ |
| **写作** | "写一份市场分析报告" / "总结论文" | writing 慢车道：Planner→RAG→Writer→Tester→Summ |
| **分析** | "分析 CSV 数据" / "统计销售趋势" | coding 慢车道：Planner→RAG→Coder→Tester→User→Summ |
| **问答** | "什么是机器学习" / "怎么写冒泡排序" | 快车道：Router→Bot 直达（秒级响应）|
| **闲聊** | "你是谁" / "你好" | 快车道：Router→Bot 直达（秒级响应）|
    
### 1.2 角色列表（8 Agent + 1 Router）

| 角色 | 职责 | 激活条件 |
|------|------|----------|
| **Router** | 意图分类 + 复杂度判定 | 所有任务（入口前置） |
| **Bot** | 快车道响应，唯一用户面客 | 轻量任务（闲聊/问答） |
| **Planner** | 拆解任务，制定步骤清单 | 重量任务 |
| **Retriever** | 查询 ChromaDB 知识库 | 重量任务 |
| **Coder** | 编写 Python 代码 + 测试 | 编程/分析类重任务 |
| **Writer** | 撰写报告/方案/文章 | 写作类重任务 |
| **Tester** | 通用评审（代码+文档） | 重量任务 |
| **Summarizer** | 汇总并输出结构化报告 | 重量任务（或按需触发） |
| **User** | 执行 Python 代码 | 编程/分析类重任务 |

---

## 2 系统架构

### 2.1 角色职责与模型分配

| 角色 | 职责 | 模型 | 原因 |
|------|------|------|------|
| **Router** | 意图分类 | DeepSeek Chat（API直调） | 分类需精准，不进入 GroupChat |
| **Bot** | 快车道回复 | DeepSeek Chat | 唯一面客，需自然流畅 |
| **Planner** | 拆解任务，制定步骤清单 | DeepSeek Chat | 需要强推理能力 |
| **Retriever** | 调用 `search_knowledge` 查询知识库 | Qwen 7B | 检索不依赖模型智力 |
| **Coder** | 编写代码 + 测试代码 | Qwen 7B | 本地免费，弱写足矣 |
| **Writer** | 撰写报告/方案/文章 | DeepSeek Chat | 写作需高质量输出 |
| **Tester** | 审查代码/文档正确性 | DeepSeek Chat | 审查须精准 |
| **Summarizer** | 汇总过程，输出 Markdown 报告 | DeepSeek Chat | 汇总须清晰 |
| **User** | 执行代码，返回 exitcode | — | 无 LLM，纯执行代理 |

### 2.2 技术栈

| 领域 | 技术 | 说明 |
|------|------|------|
| Agent 框架 | AG2 (0.13.3) | 原名 AutoGen，微软多智能体框架 |
| LLM 交互 | OpenAI SDK + httpx | 统一 API 格式接入 Ollama / DeepSeek |
| 前端 | Streamlit 1.58 | 聊天式界面（st.chat_input + thinking cards） |
| 知识库 | ChromaDB | 向量数据库 + 相似度检索 |
| 嵌入模型 | BAAI/bge-small-zh-v1.5 | 中文优化，33MB 轻量 |
| 文档解析 | PyPDF + LangChain TextSplitter | PDF → chunk → 向量 |
| 本地 LLM | Ollama + qwen2.5:7b | 4.7GB，Q4_K_M 量化 |
| 云端 LLM | DeepSeek API | 兼容 OpenAI 接口 |

### 2.3 消息流图

```
┌──────────────────────────────────────────────────────────────────┐
│                         Router 分类                               │
│              用户输入 → 标签|复杂度 → 分流                         │
└──────────┬───────────────────────────────────┬───────────────────┘
           │                                   │
     「轻」快车道                          「重」慢车道
           │                                   │
           ▼                    ┌──────────────┴──────────────┐
       Bot 直达                 │  coding lane    writing lane │
     秒级响应，无卡             │  max_round=15   max_round=10 │
                               └──────────────────────────────┘

  coding lane:
  User → Planner → Retriever → Coder → Tester ⇄ Coder (≤2轮)
                                              ↓ ✅
                                           User (执行)
                                              ↓
                      exitcode=0 → Summarizer → 结束
                      exitcode≠0 → Coder (重试)
                      exitcode超限 → Summarizer

  writing lane:
  User → Planner → Retriever → Writer → Tester ⇄ Writer (≤2轮)
                                                  ↓ ✅
                                             Summarizer → 结束
```

---

## 3 工作流详解

### 3.1 快慢车道 + 双 Lane 状态机

系统通过 Router 分类结果选择车道，再通过自定义 `speaker_selection` 函数控制流程：

**快车道（复杂度=轻）：** Router → Bot 单次对话，秒级响应，无 thinking card。

**慢车道（复杂度=重）— coding lane：**（max_round=15）

| 当前发言者 | 下一发言者 | 条件 |
|-----------|-----------|------|
| **任何** | User | 上一条消息含 `tool_calls`（工具执行） |
| **User（工具）** | 工具调用者 | 工具执行完毕，返回给调用者继续 |
| **User** | Planner | 首次发言（任务输入） |
| **User** | Summarizer | exitcode = 0 或 超限 |
| **User** | Coder | exitcode ≠ 0（重试） |
| **Planner** | Retriever | 无条件 |
| **Retriever** | Coder | 无条件 |
| **Coder** | Tester | 无条件 |
| **Tester** | User | 回复含 "✅" 且有代码 |
| **Tester** | Summarizer | "✅" 但无代码，或修复超限 |
| **Tester** | Coder | 未核准（退回修复） |
| **Summarizer** | 结束 | 无条件 |

**慢车道（复杂度=重）— writing lane：**（max_round=10）

| 当前发言者 | 下一发言者 | 条件 |
|-----------|-----------|------|
**慢车道（复杂度=重）— writing lane：**（max_round=10）

| 当前发言者 | 下一发言者 | 条件 |
|-----------|-----------|------|
| **任何** | User | 上一条消息含 `tool_calls`（工具执行） |
| **User（工具）** | 工具调用者 | 工具执行完毕，返回给调用者继续 |
| **User** | Planner | 首次发言 |
| **User** | Summarizer | 后续发言 |
| **Planner** | Retriever | 无条件 |
| **Retriever** | Writer | 无条件 |
| **Writer** | Tester | 无条件 |
| **Tester** | Summarizer | 回复含 "✅" |
| **Tester** | Writer | 未核准（退回修复） |
| **Tester** | Summarizer | 修复超限 |
| **Summarizer** | 结束 | 无条件 |
| **Writer** | Tester | 无条件 |
| **Tester** | Summarizer | 回复含 "✅" |
| **Tester** | Writer | 未核准（退回修复） |
| **Tester** | Summarizer | 修复超限 |
| **Summarizer** | 结束 | 无条件 |

### 3.2 修复迭代与安全机制

- Tester 发现问题时回复 `❌ 发现以下问题: ...` → 退回 Coder/Writer 修复
- 修复最多 **2 轮**（`_MAX_FIX_CYCLES = 2`）
- 2 轮仍未通过 → 跳过，直接进入 Summarizer 汇总（含错误信息）
- User 执行代码后 exitcode ≠ 0 → 同样退回 Coder 修复，最多 2 轮
- **非 Python 语言拦截**：正则检测 C/Java/Rust/Go/TypeScript 关键词 → 强制降级快车道
- **软超时 90s**：慢车道超时后不 kill 线程，收集已有中间结果返回用户

### 3.3 发言顺序日志

每次执行后显示完整发言链路，格式 `A → B`。例如快排任务的链路：

```
User → Planner → Retriever → Coder → Tester → Coder → Tester
→ Coder → Tester → User → Coder → Tester → Summarizer → 结束
```

共 13 步，其中 Coder↔Tester 循环了 2 轮，User 执行后 Coder 再修 1 轮。

---

## 4 项目结构

```
多智能体协作系统 (Multi-Agent)/
├── main.py                    # Streamlit 聊天入口 + env 配置 + OpenAI create 补丁
├── config.py                  # MODEL_POOL + ROLE_MODEL 可插拔配置
├── router.py                  # 意图分类器（直接 HTTP API，非 AG2 agent）
├── agents.py                  # 8 个 AG2 Agent 定义 + 工具注册 + _function_map
├── groupchat.py               # 双 Lane 自定义状态机 + speaking_log
├── tools.py                   # 5 个工具函数（read/write/search/calc/analyze）
├── 答辩报告.md                 # 项目答辩报告（架构/设计决策/问题排查/功能验证）
│
├── app/
│   ├── __init__.py
│   ├── chat.py                # run_chat_pipeline + 快慢车道 + 软超时 + 非Python降级
│   ├── components.py          # render_thinking_card（折叠卡片）/ 状态标识
│   └── knowledge.py           # 侧边栏知识库 UI（上传/删除/重建索引）
│
├── rag/
│   ├── __init__.py
│   ├── knowledge_base.py      # ChromaDB 封装（建库/检索/统计/管理）
│   ├── documents/             # 上传的知识文档（PDF/TXT）
│   └── chroma_db/             # 向量数据库持久化目录
│
├── .env                       # 环境变量（API Key，不提交 Git）
├── coding/                    # 代码执行工作目录
├── reports/                   # 生成报告输出目录
└── requirements.txt           # 依赖清单
```

### 文件职责速查

| 文件 | 核心类/函数 | 作用 |
|------|-----------|------|
| `main.py` | `st.chat_input` + OpenAI create patch | 聊天入口，环境变量，thinking 补丁 |
| `config.py` | `MODEL_POOL` / `ROLE_MODEL` / `get_config` | LLM 端点、API Key、模型参数 |
| `router.py` | `classify()` | 意图分类（编程/写作/分析/问答/闲聊） |
| `agents.py` | 8 个 `Agent` + `register_function` | 角色定义、工具注册 |
| `groupchat.py` | `_coding_speaker_selection` / `_writing_speaker_selection` | 双 Lane 发言顺序控制 |
| `tools.py` | `read_file` / `write_file` / `search_knowledge` / `calculate` / `analyze_data` / `visualize_data` | 6 个可注册工具函数 |
| `app/chat.py` | `run_chat_pipeline` / `generate_report_from_thinking` | 快慢车道 + 报告生成 |
| `app/components.py` | `render_thinking_card` | 思考卡片组件 |
| `app/knowledge.py` | `render_knowledge_sidebar` | 侧边栏知识库 UI |
| `rag/knowledge_base.py` | `build_index` / `search` / `get_stats` | ChromaDB CRUD |
| `.env` | — | API Key 等环境变量（已 `.gitignore`，不提交） |

---

## 5 环境与配置

### 5.1 前提条件

| 组件 | 要求 | 验证命令 |
|------|------|---------|
| Python | 3.11+ | `python --version` |
| Ollama | 运行中 + qwen2.5:7b（可选） | `ollama list` |
| API Key | `DEEPSEEK_API_KEY` | 项目根目录新建 `.env`：`DEEPSEEK_API_KEY=sk-xxx` |

### 5.2 配置 API Key

项目通过 `.env` 文件管理 API Key（已加入 `.gitignore`，不提交 Git）。
首次使用在项目根目录创建 `.env`：

```
DEEPSEEK_API_KEY=sk-你的key
```

### 5.3 配置模型（只需改一个文件）

编辑 `config.py`：

```python
# 第一步：在 MODEL_POOL 里定义你的模型
MODEL_POOL = {
    "a-deepseek": {"model": "deepseek-chat",
                   "api_key": os.getenv("DEEPSEEK_API_KEY"),
                   "base_url": "https://api.deepseek.com/v1", ...},
    "b-qwen":     {"model": "qwen2.5:7b",
                   "api_key": "ollama",
                   "base_url": "http://localhost:11434/v1", ...},
    # 加你自己的模型：
    # "c-gpt4o": {"model": "gpt-4o-mini", "api_key": os.getenv("OPENAI_KEY"), ...},
}

# 第二步：给每个角色指定用哪个模型（填上面的 key）
ROLE_MODEL = {
    "Planner":    "a-deepseek",
    "Bot":        "a-deepseek",
    "Retriever":  "b-qwen",
    "Coder":      "b-qwen",
    "Writer":     "a-deepseek",
    "Tester":     "a-deepseek",
    "Summarizer": "a-deepseek",
}
```

**不同设备的配置示例：**

```
有 Ollama + API Key → 保持默认
只有 API Key       → ROLE_MODEL 全部改为 "a-deepseek"
只有 Ollama        → ROLE_MODEL 全部改为 "b-qwen"
用 OpenAI          → MODEL_POOL 加 "c-gpt4o"，ROLE_MODEL 引用它
```

---

## 6 使用指南

### 6.1 启动

```bash
cd "多智能体协作系统 (Multi-Agent)"
streamlit run main.py
```

浏览器自动打开 `http://localhost:8501`。

### 6.2 使用流程

```
  1. ──→ 侧边栏知识库管理
         │ 上传 PDF/TXT → 点击「重建索引」（首次需联网下载 bge 模型 33MB）

  2. ──→ 聊天输入框 → 输入任务
         │ "写一个快排" / "实现LRU缓存" / "你好" / "什么是机器学习"

  3. ──→ 系统自动分类
         │ 轻 → Bot 秒回（无 thinking card）
         │ 重 → 慢车道执行 → 展开「🧠 思考过程」查看 Agent 协作过程

  4. ──→ 查看结果
         │ 重要任务点击「📥 生成详细报告」按需生成结构化报告
```

### 6.3 示例任务

- "实现一个带过期时间的 LRU Cache"
- "写一个快速排序算法，带完整测试"
- "实现一个简单的 HTTP 服务器"
- "写一个数据分析脚本，统计 CSV 文件"

---

## 7 运行示例：快速排序

以下是系统完成"带测试的快速排序"任务的完整过程。

### 7.1 发言链路（13 步）

```
1.  User        → Planner       # 用户提交任务
2.  Planner     → Retriever     # 规划师产出 8 步执行计划
3.  Retriever   → Coder         # 检索员搜索知识库
4.  Coder       → Tester        # 程序员提交初版代码
5.  Tester      → Coder         # 测试发现逻辑问题，要求修复
6.  Coder       → Tester        # 程序员修复后重提交
7.  Tester      → Coder         # 仍有测试问题，再修复
8.  Coder       → Tester        # 第三次提交
9.  Tester      → User ✅        # 测试核准，交给执行器
10. User        → Coder         # 执行遇错，退回修复
11. Coder       → Tester        # 修复后重提交
12. Tester      → Summarizer ✅  # 最终核准，进入汇总
13. Summarizer  → （结束）        # 生成结构化报告
```

### 7.2 最终产出

| 功能 | 实现 |
|------|------|
| **算法** | Lomuto 分区方案 + 随机枢轴 |
| **模式** | 新列表返回 / 原地排序双模式 |
| **Key 参数** | 支持自定义键函数，与 Python sorted 保持一致 |
| **类型检查** | 输入必须为 list/tuple，非序列抛出 TypeError |
| **测试覆盖** | 7 个测试用例：空数组、单元素、重复、逆序、已排、全相同、大数组 |

### 7.3 测试结果

```
test_inplace_sorting ............... ok
test_input_types ................... ok
test_key_function .................. ok
test_large_array_inplace ........... ok
test_large_array_new_list .......... ok
test_normal_cases .................. ok
test_original_list_unchanged ....... ok

Ran 7 tests in 0.048s — OK
```

---

## 8 修复记录

### 8.1 系统代理导致 Ollama 502

**现象：** `InternalServerError: Error code: 502`，发生在 Qwen 7B 推理阶段。  
**原因：** Clash/代理（`127.0.0.1:7897`）拦截了到 `localhost:11434` 的 HTTP 请求，返回 502。  
**修复：** 在 `main.py` 和 `agents.py` 头部设置 `NO_PROXY=localhost,127.0.0.1`。

### 8.2 HuggingFace 直连超时

**现象：** `OSError: [WinError 10060]`，`BAAI/bge-small-zh-v1.5` 模型下载卡住。  
**原因：** `knowledge_base.py` 未设国内镜像，HuggingFace 直连被墙。  
**修复：** 在 `knowledge_base.py` 和 `main.py` 添加 `HF_ENDPOINT=https://hf-mirror.com`。

### 8.3 stdout 重定向导致 tqdm OSError

**现象：** `OSError: [Errno 9] 文件描述符有误`，发生在重建索引时的 tqdm 进度条。  
**原因：** AG2 项目的 `sys.stdout = open(...)` 在 Streamlit 中破坏了标准输出。  
**修复：** 删除 `main.py` 中的 `sys.stdout` 替换代码，Streamlit 自行处理编码。

### 8.4 工具函数 "not found"

**现象：** Retriever 调用 `search_knowledge` 返回 `Error: Function search_knowledge not found`。  
**原因：** AG2 的 GroupChat 在**接收方代理**上执行 `execute_function`，而函数仅注册在 Retriever 和 User。  
**修复：** 将 3 个工具函数的 `_function_map` 注册到全部 6 个角色。

### 8.5 DeepSeek thinking 模式 400 错误

**现象：** `BadRequestError: 400 — The reasoning_content ... must be passed back to the API`。  
**原因：** `deepseek-v4-pro` 默认开启 thinking 模式，响应含 `reasoning_content` 字段，AG2 在后续请求中未保留该字段。  
**修复：**
1. 将模型名改为 `deepseek-chat`（无 thinking 模式）
2. 在 `main.py` 添加 OpenAI `create` 方法补丁，对所有 DeepSeek 请求强制 `extra_body: {thinking: {type: disabled}}`。

### 8.6 Tester 响应导致 NoneType.replace 崩溃

**现象：** `'NoneType' object has no attribute 'replace'`，发生在 Tester→User 后。  
**原因：** Tester 的响应 `content` 可能为 `None`，而 User ProxyAgent 提取代码时对其调用 `.replace()`。  
**修复：** 修改 `groupchat.py` 状态机：Tester 仅在回复包含 `✅` 时路由到 User，否则退回 Coder。同时在 `main.py` OpenAI patch 中增加 `tool_calls.arguments` 的 null guard。

### 8.7 C / Java 类请求走慢车道卡死（2.0 新增）

**现象：** 用户输入"写一个完整的 C 程序"，Router 分类为 `编程|重`，进入 coding lane 后不断重试直到超时。  
**根因链：** Router 未识别非 Python → Coder 写 Python 片段 → User 无法执行 C → exitcode≠0 → 无限重试。  
**修复（两层）：**
1. `app/chat.py` 正则检测 `c语言|java|rust|golang|swift|c\+\+|typescript` → 强制降为 `问答|轻` → Bot 快车道
2. 软超时从 60s 延长到 90s，不 kill 线程而是收集已有结果返回

### 8.8 GroupChat 轮次过大导致无限循环（2.0 新增）

**现象：** encoding/writing 任务中 Agent 反复循环，远超预期轮次。  
**原因：** `max_round` 设置过大（coding=18, writing=14），允许过多 Coder↔Tester 循环。  
**修复：** coding max_round: 18→15，writing: 14→10。仍保留 2 轮修复余量。

### 8.9 GroupChat 工具回调路由错误

**现象：** Retriever 调用 `search_knowledge` 后，User 执行完工具结果被路由到 Coder，导致 Retriever 被跳过、Coder 重复写代码。  
**原因：** speaker selection 中 User 处理器将所有非首次消息视为"代码执行结果"，路由到 Coder。工具执行结果应返回给调用者。  
**修复：** 在 `_coding_speaker_selection` 和 `_writing_speaker_selection` 中增加工具回调检测——检测到上一条消息含 `tool_calls` 时，路由回调用者。

### 8.10 Retriever 越权写代码

**现象：** Retriever 搜索知识库后直接 `write_file` 写代码、试图运行测试，抢 Coder 的职责。  
**原因：** 所有工具（含 `write_file`）统一注册给全部角色，Qwen 7B 弱模型拿工具就乱用。  
**修复：** 工具注册按角色分派——Retriever 仅 `search_knowledge`，Coder 有 `write_file`/`read_file`/`calculate`，Tester 仅 `read_file`。

### 8.11 正文输出截断

**现象：** 编程/分析任务正文只显示 Planner 计划的前 300 字符，完整代码和报告需要点按钮才能看。  
**原因：** `_extract_summary()` 多处硬截断（`[:300]` / `[:500]`）。  
**修复：** 去掉所有截断，改用完整输出。编程/分析任务的正文自动包含 `## 💻 代码实现` + `## 📊 任务报告`。

### 8.12 临时文件污染

**现象：** Coder 每次执行在 `coding/` 下残留 `.py` 脚本，多轮对话后目录混乱。  
**原因：** 缺少自动清理机制。`_scan_generated_files` 不扫描 `.py`，组员看不到代码产出。  
**修复：** 扫描范围加入 `.py` 扩展名；`_cleanup_temp_files` 改为仅清理 `tmp_code_*` 子目录，不删 Coder 产出。

### 8.13 知识库噪音

**现象：** 检索 LRU 缓存返回 TinySAM 论文内容，噪音污染下游输出。  
**原因：** ChromaDB `similarity_search` 无相关性过滤。  
**修复：** 改用 `similarity_search_with_relevance_scores`，`min_score=0.40` 阈值过滤低相关结果。

### 8.14 按钮与 session_state 冲突

**现象：** Streamlit 按钮点击后 UI 不展开。  
**原因：** button widget key（`report_{idx}`）与 `st.session_state` key 同名。  
**修复：** button key 改为 `btn_report_{idx}`，与 session_state 分离。

---

## 9 组员协作指南

### 9.1 环境准备

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 安装 Ollama（可选，仅本地编码角色需要）
#    https://ollama.com/download
ollama pull qwen2.5:7b

# 3. 设置 DeepSeek API Key（必需）
#    方式一（推荐）：项目根目录创建 .env 文件，写入：
#       DEEPSEEK_API_KEY=sk-你的key
#    方式二（环境变量）：
#       Windows: set DEEPSEEK_API_KEY=sk-xxx
#       macOS/Linux: export DEEPSEEK_API_KEY=sk-xxx
#    注意：方式一需依赖 python-dotenv（已在 requirements.txt 中声明 >=1.0）
```

### 9.2 首次运行

```bash
streamlit run main.py
```

浏览器打开 `http://localhost:8501`，侧边栏上传知识库文档 → 点击「重建索引」。

### 9.3 模型配置

编辑 `config.py` 的 `MODEL_POOL` 和 `ROLE_MODEL`：

| 你的情况 | 操作 |
|---------|------|
| 有 API Key + 有 Ollama | 保持默认 |
| 只有 API Key | ROLE_MODEL 全部改为 `"a-deepseek"` |
| 只有 Ollama | ROLE_MODEL 全部改为 `"b-qwen"` |
| 用其他模型 | 在 MODEL_POOL 添加，ROLE_MODEL 引用 |

### 9.4 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 首次启动慢 | 自动下载嵌入模型 bge-small-zh-v1.5（33MB） | 等待即可 |
| ChromaDB 报错 | 向量库未建立 | 重建索引 |
| Ollama 连接失败 | 代理拦截 localhost | 设 `NO_PROXY=localhost,127.0.0.1` 或关代理 |
| DeepSeek 400 | 模型不支持 thinking 模式 | 改模型名为 `deepseek-chat` |

---

## 10 扩展指南

### 10.1 添加新角色

1. 在 `agents.py` 中创建新的 `AssistantAgent`（参照现有角色）
2. 在 `config.py` 的 `ROLE_MODEL` 中分配模型
3. 在 `groupchat.py` 相应 Lane 的 `_speaker_selection` 中添加路由逻辑
4. 将新代理加入对应 Lane 的 `_coding_agents` / `_writing_agents` 列表

### 10.2 更换模型

只需修改 `config.py` 的 `MODEL_POOL` 和 `ROLE_MODEL`：

| 场景 | 修改项 |
|------|--------|
| 换本地模型 | `MODEL_POOL["b-qwen"]["model"] = "llama3:8b"` |
| 换云端模型 | `MODEL_POOL["a-deepseek"]["model"] = "gpt-4o-mini"` + 改 `base_url` |
| 添加新模型 | `MODEL_POOL["c-gpt4o"] = {...}`，`ROLE_MODEL` 中引用 |
| 全部用云端 | `ROLE_MODEL` 所有值改为 `"a-deepseek"` |
| 全部用本地 | `ROLE_MODEL` 所有值改为 `"b-qwen"` |

### 10.3 添加自定义工具

1. 在 `tools.py` 中编写新函数
2. 在 `agents.py` 中导入并加入 `_registry` 列表
3. 在 `groupchat.py` 中导入并加入 `_all_tools` 列表（注册到 Manager）
4. 更新相关 Agent 的 `system_message` 提示有工具可用

```python
# tools.py
def analyze_file(path: str) -> str:
    """分析文件内容并返回统计信息"""
    ...

# agents.py — 加入 _registry
_registry.append((analyze_file, "分析文件内容并返回统计信息"))

# groupchat.py — 注册到 Manager
_all_tools.append(analyze_file)
```

### 10.4 修改状态机

编辑 `groupchat.py` 的 `_coding_speaker_selection` 或 `_writing_speaker_selection` 函数。每个 `if name == "..."` 分支控制特定角色的路由。`_MAX_FIX_CYCLES` 变量控制最大固定循环次数。
