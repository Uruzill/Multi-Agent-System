// ===== 常量 =====
const ICONS = {
    "Planner": "📋", "Retriever": "🔍",
    "Coder": "💻", "Writer": "✍️",
    "Tester": "✅", "Summarizer": "📊",
    "Bot": "🤖", "Executor": "⚙️",
};

const COLORS = {
    "Planner": "#4f8cff", "Retriever": "#8b5cf6",
    "Coder": "#10b981", "Writer": "#f59e0b",
    "Tester": "#ef4444", "Summarizer": "#4f8cff",
    "Bot": "#10b981", "Executor": "#8b5cf6",
};

let messageHistory = [];
let _currentSessionId = null;

// ===== 初始化 =====
document.addEventListener("DOMContentLoaded", () => {
    loadKnowledgeStats();
    setupLaneMode();
    setupChatForm();
    setupKnowledgeUI();
    setupFileUpload();
    setupDragUpload();
    // 如果已登录，加载会话历史
    const uid = getUserId();
    if (uid && typeof loadSessionHistory === 'function') {
        loadSessionHistory();
    }
});

// ===== 车道模式 =====
function setupLaneMode() {
    const updateStatus = () => {
        const mode = document.querySelector("input[name='lane_mode']:checked")?.value;
        const el = document.getElementById("lane-status");
        if (el) {
            if (mode === "fast") {
                el.innerHTML = '<span class="text-primary fw-bold">快速（直接回复）</span>';
            } else if (mode === "slow") {
                el.innerHTML = '<span class="text-success fw-bold">协作（多Agent协作）</span>';
            } else {
                el.innerHTML = '<span class="text-info fw-bold">自动（AI 判断）</span>';
            }
        }
        // 更新胶囊按钮 active 状态
        document.querySelectorAll('.mode-toggle-item').forEach(l => {
            l.classList.toggle('active', l.getAttribute('data-value') === mode);
        });
        // 更新悬浮弹窗 active 状态
        document.querySelectorAll('.lane-option').forEach(o => {
            o.classList.toggle('active', o.getAttribute('data-value') === mode);
        });
    };
    document.querySelectorAll("input[name='lane_mode']").forEach(r => {
        r.addEventListener('change', function() {
            updateStatus();
            // 同步欢迎页模式高亮
            var val = this.value;
            var label = document.getElementById('welcome-mode-label');
            if (label) {
                var names = { auto: '自动', fast: '快速', slow: '协作' };
                label.innerHTML = '使用 <strong>' + (names[val] || val) + '</strong> 模式进行对话';
            }
            document.querySelectorAll('.welcome-mode').forEach(function(m) {
                m.classList.toggle('active', m.getAttribute('data-value') === val);
            });
        });
    });
    updateStatus();
}

// ===== 思考面板展开/收起（CSS transition 动画） =====
function toggleThinkingPanel(id, btn) {
    var el = document.getElementById(id);
    var arrow = btn.querySelector('.toggle-arrow');
    if (!el || !arrow) return;
    if (el.classList.contains('open')) {
        el.classList.remove('open');
        arrow.classList.remove('open');
        el.style.maxHeight = '0';
    } else {
        el.classList.add('open');
        arrow.classList.add('open');
        el.style.maxHeight = 'none';
        var h = el.scrollHeight;
        el.style.maxHeight = '0';
        void el.offsetHeight;
        el.style.maxHeight = h + 'px';
        var onEnd = function() {
            el.style.maxHeight = 'none';
            el.removeEventListener('transitionend', onEnd);
        };
        el.addEventListener('transitionend', onEnd);
    }
}

// ===== 聊天表单 =====
function setupChatForm() {
    const form = document.getElementById("chat-form");
    if (!form) return;
    const input = document.getElementById("chat-input");

    // Enter 发送，Shift+Enter 换行
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const message = input.value.trim();
            if (!message) return;
            sendMessage(message);
            input.value = "";
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const message = input.value.trim();
        if (!message) return;
        await sendMessage(message);
        input.value = "";
    });
}

// ===== 发送消息 =====
async function sendMessage(message) {
    const laneMode = document.querySelector("input[name='lane_mode']:checked")?.value || "auto";

    // 首次发送时取消整体居中 + 移除引导页
    var layout = document.getElementById('chat-layout');
    if (layout && layout.classList.contains('welcome-active')) {
        layout.classList.remove('welcome-active');
    }
    var welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    appendUserMessage(message);

    const loadingId = appendLoadingMessage();

    try {
        // 读取当前模型配置
        let modelConfig = {};
        try { modelConfig = JSON.parse(localStorage.getItem("mc_roles") || "{}"); } catch(e) {}

        var body = {
            message: message,
            lane_mode: laneMode,
            history: messageHistory,
            model_config: modelConfig,
        };
        if (pendingFiles.length > 0) {
            body.file_ids = pendingFiles.slice();
        }

        const resp = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        removeLoadingMessage(loadingId);
        clearFileTags();

        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            throw new Error(errData.error || `服务器错误 (${resp.status})`);
        }

        const data = await resp.json();
        appendAssistantMessage(data);
        messageHistory.push({ role: "user", content: message });
        messageHistory.push({ role: "assistant", content: data.reply });
        // 自动保存会话
        saveCurrentSession();
    } catch (err) {
        removeLoadingMessage(loadingId);
        appendErrorMessage(err.message);
    }
}

// ===== 消息渲染 =====
function appendUserMessage(message) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = "message-user";
    div.innerHTML = `<div class="bubble">${escapeHtml(message)}</div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendAssistantMessage(data) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = "message-assistant";

    // Thinking 区域（可折叠）
    let thinkingHtml = "";
    if (data.thinking && data.thinking.length > 0) {
        const flow = data.thinking
            .filter(m => m.name)
            .map(m => `${ICONS[m.name] || "🔹"} ${m.name}`)
            .join(" → ");
        const cardsHtml = data.thinking
            .filter(m => m.content)
            .map(m => renderAgentCard(m))
            .join("");

        const collapseId = "thinking-" + Date.now();
        thinkingHtml = `
            <div class="thinking-section">
                <button class="thinking-toggle" onclick="toggleThinkingPanel('${collapseId}',this)">
                    <span class="toggle-arrow">
                        <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>
                    </span>
                    🧠 ${flow}
                </button>
                <div id="${collapseId}" class="thinking-collapse">
                    ${cardsHtml}
                </div>
            </div>
        `;
    }

    // 文件展示
    let filesHtml = "";
    if (data.generated_files && data.generated_files.length > 0) {
        filesHtml = '<div class="mb-2">' +
            data.generated_files.map(f => renderFileBadge(f)).join("") +
            '</div>';
    }

    // 操作工具栏（复制 / 重新生成 / 报告）
    let toolbarHtml = `<div class="msg-toolbar">`;
    toolbarHtml += `<button class="toolbar-btn" onclick="copyReply(this)" data-text="${escapeAttr(data.reply)}" title="复制回复">复制</button>`;
    toolbarHtml += `<button class="toolbar-btn" onclick="regenerate()" title="重新回答">重新回答</button>`;
    if (data.thinking && data.thinking.length > 0 && data.task_type && data.task_type !== "闲聊" && data.task_type !== "问答") {
        toolbarHtml += `<button class="toolbar-btn report-btn" title="生成报告">生成报告</button>`;
    }
    toolbarHtml += `</div>`;

    div.innerHTML = `
        ${thinkingHtml}
                <div class="bubble">${markdownToHtml(data.reply)}</div>
        ${filesHtml}
        ${toolbarHtml}
    `;

    // 绑定报告按钮
    div.querySelector(".report-btn")?.addEventListener("click", async function () {
        this.disabled = true;
            this.textContent = "生成中...";
        try {
            const resp = await fetch("/api/report", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ thinking: data.thinking }),
            });
            const report = await resp.json();
            const reportDiv = document.createElement("div");
            reportDiv.className = "mt-2 p-3 border rounded bg-white";
            reportDiv.innerHTML = `<strong>📊 详细报告</strong><hr>${markdownToHtml(report.content)}`;
            this.replaceWith(reportDiv);
        } catch {
            this.textContent = "报告";
            this.disabled = false;
        }
    });

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ===== 复制回复 =====
function copyReply(btn) {
    const text = btn.getAttribute("data-text");
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = "✅ 已复制";
        setTimeout(() => { btn.textContent = orig; }, 2000);
    }).catch(() => {
        btn.textContent = "复制失败";
        setTimeout(() => { btn.textContent = "复制"; }, 2000);
    });
}

// ===== 重新生成 =====
function regenerate() {
    // 找到最后一条用户消息
    let lastUserMsg = null;
    for (let i = messageHistory.length - 1; i >= 0; i--) {
        if (messageHistory[i].role === "user") {
            lastUserMsg = messageHistory[i].content;
            break;
        }
    }
    if (!lastUserMsg) return;

    // 移除最后一条助手回复（DOM）
    const msgs = document.querySelectorAll("#chat-messages .message-assistant");
    const last = msgs[msgs.length - 1];
    if (last) last.remove();
    // 从 history 弹出最后一条 assistant 记录
    if (messageHistory.length > 0 && messageHistory[messageHistory.length - 1].role === "assistant") {
        messageHistory.pop();
    }

    const laneMode = document.querySelector("input[name='lane_mode']:checked")?.value || "auto";
    const loadingId = appendLoadingMessage();

    let modelConfig = {};
    try { modelConfig = JSON.parse(localStorage.getItem("mc_roles") || "{}"); } catch(e) {}

    fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            message: lastUserMsg,
            lane_mode: laneMode,
            history: messageHistory,
            model_config: modelConfig,
        }),
    })
    .then(resp => {
        removeLoadingMessage(loadingId);
        if (!resp.ok) throw new Error(`服务器错误 (${resp.status})`);
        return resp.json();
    })
    .then(data => {
        appendAssistantMessage(data);
        messageHistory.push({ role: "assistant", content: data.reply });
        saveCurrentSession();
    })
    .catch(err => {
        removeLoadingMessage(loadingId);
        appendErrorMessage(err.message);
    });
}

function renderAgentCard(msg) {
    const color = COLORS[msg.name] || "#6b7280";
    const icon = ICONS[msg.name] || "🔹";
    return `
        <div class="agent-card">
            <div class="agent-header" style="border-left-color:${color};">
                <span class="agent-badge" style="background:${color}18; color:${color};">${icon} ${escapeHtml(msg.name)}</span>
            </div>
            <div class="agent-body">${escapeHtml(msg.content).replace(/\n/g, "<br>")}</div>
        </div>
    `;
}

function renderFileBadge(file) {
    const ext = (file.ext || "").toLowerCase();
    if (["png", "jpg", "jpeg", "gif", "bmp"].includes(ext)) {
        return `<span class="file-badge">🖼 <a href="/coding/${escapeHtml(file.name)}" target="_blank">${escapeHtml(file.name)}</a></span>`;
    }
    return `<span class="file-badge">📄 <a href="/coding/${escapeHtml(file.name)}" target="_blank">${escapeHtml(file.name)}</a></span>`;
}

function appendErrorMessage(errMsg) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = "message-assistant message-error";
    div.innerHTML = `<div class="bubble">⚠️ 请求失败，请重试<br><small>${escapeHtml(errMsg)}</small></div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendLoadingMessage() {
    const id = "loading-" + Date.now();
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.id = id;
    div.className = "message-assistant";
    div.innerHTML = `
        <div class="skeleton-bubble">
            <div class="skeleton-line w-60"></div>
            <div class="skeleton-line w-80"></div>
            <div class="skeleton-line w-45"></div>
        </div>`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeLoadingMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ===== 文件上传 =====
let pendingFiles = [];

function setupFileUpload() {
    var btn = document.getElementById('attach-btn');
    var input = document.getElementById('file-input');
    if (!btn || !input) return;

    btn.addEventListener('click', function() { input.click(); });

    input.addEventListener('change', async function() {
        var files = Array.from(this.files);
        if (!files.length) return;
        this.value = '';
        for (var f of files) {
            await uploadFile(f);
        }
    });
}

async function uploadFile(file) {
    var tagId = 'ft-' + Date.now();
    addFileTag(tagId, file.name, '上传中...');

    var formData = new FormData();
    formData.append('file', file);

    try {
        var resp = await fetch('/api/upload', { method: 'POST', body: formData });
        if (!resp.ok) {
            var err = await resp.json().catch(function() { return { error: '上传失败' }; });
            updateFileTag(tagId, file.name, '❌ ' + (err.error || '失败'), true);
            return;
        }
        var data = await resp.json();
        updateFileTag(tagId, file.name, '✅ ' + file.name, false);
        pendingFiles.push(data.file_id);
    } catch (e) {
        updateFileTag(tagId, file.name, '❌ 网络错误', true);
    }
}

function addFileTag(id, name, status) {
    var el = document.getElementById('file-tags');
    if (!el) return;
    var tag = document.createElement('span');
    tag.id = id;
    tag.className = 'file-tag';
    tag.innerHTML = '<span class="ft-name">' + escapeHtml(name) + '</span> <span class="ft-status">' + escapeHtml(status) + '</span>';
    el.appendChild(tag);
}

function updateFileTag(id, name, status, isError) {
    var el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = '<span class="ft-name">' + escapeHtml(name) + '</span> <span class="ft-status">' + escapeHtml(status) + '</span>';
    if (isError) {
        el.classList.add('ft-error');
        setTimeout(function() { el.remove(); }, 4000);
    }
}

// ===== 拖拽上传 =====
function setupDragUpload() {
    var zone = document.getElementById('drop-zone');
    var overlay = document.getElementById('drag-overlay');
    if (!zone || !overlay) return;

    var dragCount = 0;

    zone.addEventListener('dragenter', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dragCount++;
        overlay.classList.add('show');
    });

    zone.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
    });

    zone.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dragCount--;
        if (dragCount <= 0) {
            dragCount = 0;
            overlay.classList.remove('show');
        }
    });

    zone.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dragCount = 0;
        overlay.classList.remove('show');
        var files = Array.from(e.dataTransfer.files);
        if (!files.length) return;
        for (var f of files) {
            uploadFile(f);
        }
    });
}

function clearFileTags() {
    pendingFiles = [];
    var el = document.getElementById('file-tags');
    if (el) el.innerHTML = '';
}

// ===== 知识库 UI =====
async function loadKnowledgeStats() {
    try {
        const resp = await fetch("/api/knowledge/stats");
        if (!resp.ok) return;
        const data = await resp.json();
        const docEl = document.getElementById("kb-doc-count");
        const chunkEl = document.getElementById("kb-chunk-count");
        if (docEl) docEl.textContent = data["文档数"] || 0;
        if (chunkEl) chunkEl.textContent = data["切片数"] || 0;
    } catch { /* 静默失败 */ }
}

function setupKnowledgeUI() {
    // 重建索引
    document.getElementById("kb-rebuild-btn")?.addEventListener("click", async function () {
        this.disabled = true;
        this.textContent = "重建中...";
        try {
            const resp = await fetch("/api/knowledge/rebuild", { method: "POST" });
            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(text.slice(0, 200));
            }
            const data = await resp.json();
            if (data.success) {
                alert(`索引重建完成，新增 ${data.added} 条切片`);
            }
        } catch (err) {
            alert("重建失败: " + err.message);
        }
        this.disabled = false;
        this.textContent = "重建索引";
        loadKnowledgeStats();
        if (typeof loadKnowledgeFiles === 'function') loadKnowledgeFiles();
    });

    // 上传文件
    document.getElementById("kb-upload-input")?.addEventListener("change", async function () {
        const file = this.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append("file", file);
        try {
            const resp = await fetch("/api/knowledge/upload", { method: "POST", body: formData });
            const data = await resp.json();
            if (data.success) {
                alert(`已上传: ${data.filename}`);
            } else {
                alert("上传失败: " + (data.error || "未知错误"));
            }
        } catch (err) {
            alert("上传失败: " + err.message);
        }
        this.value = "";
        loadKnowledgeStats();
        if (typeof loadKnowledgeFiles === 'function') loadKnowledgeFiles();
    });
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(str) {
    return str.replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ===== Markdown → HTML（代码块带复制按钮 + 语言标签） =====
function markdownToHtml(md) {
    let html = escapeHtml(md);
    // 代码块（带语言标签 + 复制按钮）
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function(match, lang, code) {
        var id = 'cb-' + Math.random().toString(36).slice(2, 8);
        var label = lang || 'code';
        return '<div class="code-block" id="' + id + '">' +
            '<div class="code-lang">' + label + '</div>' +
            '<button class="code-copy" onclick="var p=document.getElementById(\'' + id + '\');var t=p.querySelector(\'code\').textContent;navigator.clipboard.writeText(t).then(function(){var b=p.querySelector(\'.code-copy\');b.textContent=\'已复制\';setTimeout(function(){b.textContent=\'复制\'},2000)})">复制</button>' +
            '<pre><code>' + code.trim() + '</code></pre>' +
            '</div>';
    });
    html = html.replace(/^### (.+)$/gm, "<h6>$1</h6>");
    html = html.replace(/^## (.+)$/gm, "<h5>$1</h5>");
    html = html.replace(/^# (.+)$/gm, "<h4>$1</h4>");
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    return html;
}

// ===== 会话保存（适配 db.py 后端） =====
async function saveCurrentSession() {
    if (!messageHistory.length) return;
    const uid = getUserId();
    if (!uid) return;
    try {
        const sid = _currentSessionId || String(Date.now());
        const title = messageHistory[0]?.content?.slice(0, 50) || "新对话";
        await fetch("/api/sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: sid, user_id: uid, messages: messageHistory, title: title }),
        });
        _currentSessionId = sid;
        // 刷新侧栏会话列表
        if (typeof loadSessionHistory === 'function') loadSessionHistory();
    } catch (e) {
        console.error("保存会话失败:", e);
    }
}

// ===== 用户工具函数 =====
function getUserId() {
    return localStorage.getItem("mc_uid") || "";
}

function getUserName() {
    return localStorage.getItem("mc_uname") || "";
}

// ===== 覆盖 sidebar.html 中的 newChat =====
const _origNewChat = window.newChat;
window.newChat = function() {
    if (_origNewChat) _origNewChat();
    messageHistory = [];
    _currentSessionId = null;
    clearFileTags();
};
