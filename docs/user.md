# 用户管理体系 — 设计文档

## 一、设计思路

**核心原则：用户身份与会话分离，前端信任逐级降级**

```
用户状态分层:
  1. JWT 本地存在 → 信任标记
  2. JWT 本地解码 → 校验是否过期
  3. JWT 后端验证 → 校验用户是否在 DB 中存在
  4. 降级 → 游客模式
```

**游客与注册用户双轨制：**
- **游客**：所有会话和数据存储在浏览器 `sessionStorage`，关闭标签即清除，不涉及后端
- **注册用户**：会话和配置存储在 SQLite 后端，通过 JWT 鉴权

**配置归属：**
- 系统模型（`config.py` 的 `MODEL_POOL`）— 全局共享，所有人可见
- 角色分配（`ROLE_MODEL`）— 全局默认值，登录用户可覆盖（存 `user_configs`）
- 自定义模型（用户添加的 API 模型）— 仅登录用户可管理，通过 `/api/user/custom-models` 校验身份后存入 `user_configs`

## 二、后端架构

**文件结构：**
```
user/
├── __init__.py           # 包标识
├── auth.py               # 密码哈希 + JWT 创建/解码（纯函数，无状态）
├── db.py                 # Database 类：users / sessions / user_configs 三张表的 CRUD
├── helpers.py            # 请求辅助：_resolve_user_id, _get_db, _log_db
└── routes.py             # APIRouter：全部用户 API 路由
```

**API 端点一览：**

| 端点 | 方法 | 功能 | 身份要求 |
|------|------|------|---------|
| `/api/auth/register` | POST | 注册 | 无 |
| `/api/auth/login` | POST | 登录 | 无 |
| `/api/auth/verify` | GET | 验证 token 对应用户是否在 DB 中 | JWT |
| `/api/sessions` | GET | 列出当前用户会话 | JWT/temp |
| `/api/sessions` | POST | 保存当前会话 | JWT/temp |
| `/api/sessions/{id}` | GET | 获取单个会话消息 | JWT/temp |
| `/api/sessions/{id}` | DELETE | 删除会话 | JWT/temp |
| `/api/user/config` | GET | 读取用户配置（角色分配+自定义模型） | JWT |
| `/api/user/config` | PUT | 保存用户配置（仅角色分配） | JWT |
| `/api/user/custom-models` | POST | 添加自定义模型（后端统一校验） | JWT |
| `/api/user/custom-models/{name}` | DELETE | 删除自定义模型 | JWT |

**身份解析流程（`_resolve_user_id`）：**
1. 检查 `Authorization: Bearer <token>` → decode JWT → 取 `payload["sub"]`
2. 若无 JWT，检查 `X-Temp-Id` header → 取 `temp_xxx` 作为临时 ID
3. 两者都没有 → 返回 `None`

**校验架构变迁：**
- **最初**：前端全部校验（重名、URL 格式、系统冲突、身份）
- **当前**：前端负责基础非空校验，后端统一做所有业务校验（身份、重名、系统冲突、URL 格式）。前端调后端 API，后端统一返回 `{"error": "..."}` 及对应 HTTP 状态码

**密码存储：**
```
password → salt(16 hex) + hash = salt$sha256(salt + password)
```

**JWT：**
```
HS256, 7天过期, payload: {sub, name, iat, exp}
```

## 三、前端架构

**关键文件：**

| 文件 | 职责 |
|------|------|
| `static/js/chat.js` | 认证函数（login/register/logout）、API 封装、会话保存、游客会话管理 |
| `templates/components/sidebar.html` | 登录/注册弹窗、系统配置弹窗、添加模型弹窗、会话列表、身份切换 UI |
| `templates/base.html` | 传递后端 `systemStatus` 和 `modelPool` 到前端 |

**前端认证函数：**

| 函数 | 用途 |
|------|------|
| `getToken()` | 从 `localStorage` 取 `mc_token` |
| `getTempId()` | 取/生成 `temp_xxx` 存 `localStorage` |
| `isGuest()` | `return !getToken()` — 快速判断 |
| `verifyToken()` | 页面加载时调 `/api/auth/verify`，无效则 `_clearAuth()` |
| `_clearAuth()` | 清理 `mc_token`、`mc_uid`、`mc_uname`、`mc_custom`、`mc_roles` |
| `apiFetch()` | 统一 fetch 封装，自动注入 `Authorization` 或 `X-Temp-Id` |
| `syncConfigToServer()` | 将 `mc_roles` 同步到后端 `PUT /api/user/config` |
| `saveCurrentSession()` | 游客存 `sessionStorage`，注册用户调 `POST /api/sessions` |

**页面初始化流程（`DOMContentLoaded`）：**
```
getTempId() → verifyToken() → 加载知识库 → 设置模式 → 加载会话列表
```

## 四、前端缓存与身份切换刷新

**identity 相关 localStorage key：**

| key | 用途 | 登出清理 |
|-----|------|---------|
| `mc_token` | JWT token | ✅ |
| `mc_uid` | 用户 ID | ✅ |
| `mc_uname` | 用户名 | ✅ |
| `mc_custom` | 自定义模型列表 | ✅ |
| `mc_roles` | 角色分配 | ✅ |

**身份切换时的 UI 刷新：**

| 场景 | 触发函数 | 清理 localStorage | 清理内存变量 | 刷新 UI |
|------|---------|-----------------|-------------|---------|
| **登录/注册** | `submitAuth()` | — | ✅ 重载 `customModels`, `currentRoles` | ✅ `renderModelList()` + `renderDropdowns()` + `loadSessionHistory()` + 清空聊天区 |
| **登出** | `handleLogout()` | ✅ `_clearAuth()` 清理全部 5 项 | ✅ `customModels = []`, `currentRoles` 重置为系统默认 | ✅ `renderModelList()` + `renderDropdowns()` + `loadSessionHistory()` + 清空聊天区 |

**累计修复的缓存/刷新问题：**

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | 首次进入显示已登录"1" | `isGuest()` 不校验 JWT 过期，不检查用户是否存在 | `verifyToken()` + `/api/auth/verify` 后端确认 |
| 2 | 登录/注册切换不消输入框 | `switchAuthTab()` 只切可见性不消值 | 清空 username/password/confirm |
| 3 | 登出弹窗不关闭 | `confirm()` 原生模态干扰 `<dialog>` | 去掉 `confirm()`，直接登出 |
| 4 | 登出后会话显示旧数据 | `logout()` 写死空列表 | 调 `loadSessionHistory()` |
| 5 | 登出后系统配置显示上一个人的模型 | `_clearAuth()` 未清 `mc_custom`/`mc_roles`，未重置内存变量 | 清理 5 项 + 重置 `customModels` + 刷新列表 |
| 6 | 登录后系统配置仍是初始状态 | `submitAuth()` 成功后未从 localStorage 重载 | 加重载 + `renderModelList()` |
| 7 | 注册按钮无反应 | `renderDropdowns()` 调用已删除的函数导致脚本中断 | 改为 `renderModelList()` |
| 8 | 添加模型弹窗不关 | `close()` 在最后，前面抛异常则跳过 | `close()` 提前到保存后立即执行 |

## 五、会话生命周期

```
游客模式：
  sessionStorage.guest_sessions = [...]
  发消息 → saveCurrentSession() → sessionStorage
  切换会话 → switchSession() → 从 sessionStorage 加载
  关闭标签 → 数据清除

注册用户模式：
  SQLite.sessions 表
  发消息 → saveCurrentSession() → POST /api/sessions → SQLite
  切换会话 → switchSession() → GET /api/sessions/{id} → SQLite
  登录成功 → 清空 sessionStorage.guest_sessions
```

## 六、自定义模型管理流程

```
用户点击"添加模型" → 弹窗输入 name/url/key
  → submitNewModel()
    → 前端校验：name/url/key 非空
    → POST /api/user/custom-models
      → 后端校验：
        - 身份：游客 → 401 "请先登录"
        - name 非空：空 → 400 "不能为空"
        - URL 格式：不以 http/https 开头 → 400 "地址必须..."
        - key 非空：空 → 400 "不能为空"
        - 系统模型冲突：name = 系统模型名 → 409 "冲突"
        - 重名：已有同名自定义 → 409 "已存在"
        → 通过：存入 user_configs → 返回 200
    → 响应 200：更新 localStorage → 关闭弹窗 → 刷新列表
    → 响应 4xx：弹窗显示错误信息，不关闭
```
