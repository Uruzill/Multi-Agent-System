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
let _streamSessionId = null;   // 当前活跃的流式会话 ID，用于中断
let _streamReader = null;      // 当前活跃的 ReadableStream reader，用于中断

// ===== 鉴权工具 =====
function getAuthHeaders() {
    const token = localStorage.getItem("auth_token");
    const headers = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = "Bearer " + token;
    return headers;
}

// ===== 初始化 =====
document.addEventListener("DOMContentLoaded", async () => {
    loadKnowledgeStats();
    setupLaneMode();
    setupChatForm();
    setupKnowledgeUI();
    if (typeof loadSessionHistory === 'function') {
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
        r.addEventListener('change', updateStatus);
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

// ===== 中断流式请求 =====
async function abortStream() {
    // 关闭 reader
    if (_streamReader) {
        try { _streamReader.cancel(); } catch(e) {}
        _streamReader = null;
    }
    // 通知后端
    if (_streamSessionId) {
        try {
            await fetch("/api/chat/cancel/" + _streamSessionId, { method: "POST" });
        } catch(e) {}
        _streamSessionId = null;
    }
    // 移除骨架屏
    document.querySelectorAll('.message-assistant .bubble:empty').forEach(function(el) {
        var parent = el.closest('.message-assistant');
        if (parent) {
            var bubble = parent.querySelector('.bubble');
            if (bubble && !bubble.textContent.trim()) {
                bubble.textContent = '已中断';
                bubble.style.color = 'var(--text-secondary)';
                bubble.style.fontStyle = 'italic';
            }
        }
    });
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
            // 流式进行中 → 中断
            if (_streamSessionId) {
                abortStream();
                return;
            }
            const message = input.value.trim();
            if (!message) return;
            sendMessage(message);
            input.value = "";
        }
    });

    // 全局 Esc 中断
    document.addEventListener("keydown", function(e) {
        if (e.key === "Escape" && _streamSessionId) {
            abortStream();
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        // 流式进行中 → 中断
        if (_streamSessionId) {
            abortStream();
            return;
        }
        const message = input.value.trim();
        if (!message) return;
        await sendMessage(message);
        input.value = "";
    });
}

// ===== 发送消息（流式：start → SSE → done） =====
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

    // 中断上一次仍活跃的流
    await abortStream();

    try {
        // 1. 启动工作流，获取 session_id
        const startResp = await fetch("/api/chat/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                lane_mode: laneMode,
                history: messageHistory,
            }),
        });
        if (!startResp.ok) {
            const errData = await startResp.json().catch(() => ({}));
            throw new Error(errData.error || `启动失败 (${startResp.status})`);
        }
        const { session_id } = await startResp.json();
        _streamSessionId = session_id;

        // 2. 移除骨架屏，创建实时助手消息容器
        removeLoadingMessage(loadingId);
        const assistantDiv = createAssistantSkeleton(session_id);
        assistantDiv.dataset.laneMode = laneMode;

        // 3. 连接 SSE（fetch + ReadableStream，支持中断和未来鉴权）
        const ctrl = new AbortController();
        const streamResp = await fetch("/api/chat/stream/" + session_id, {
            signal: ctrl.signal,
        });
        if (!streamResp.ok) throw new Error("流式连接失败");

        const reader = streamResp.body.getReader();
        _streamReader = reader;
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            // 按 SSE 标准分割：data: {...}\n\n
            var parts = buffer.split("\n\n");
            buffer = parts.pop() || "";

            for (var i = 0; i < parts.length; i++) {
                var part = parts[i];
                var dataLine = "";
                var lines2 = part.split("\n");
                for (var j = 0; j < lines2.length; j++) {
                    var l = lines2[j];
                    if (l.startsWith("data: ")) {
                        dataLine = l.slice(6);
                        break;
                    }
                }
                if (!dataLine) continue;
                try {
                    var event = JSON.parse(dataLine);
                    handleStreamEvent(assistantDiv, event);
                } catch (e) {
                    console.warn("SSE 解析错误:", e);
                }
            }
        }

        // 4. 流结束
        _streamReader = null;
        _streamSessionId = null;
        messageHistory.push({ role: "user", content: message });
        saveCurrentSession();

    } catch (err) {
        removeLoadingMessage(loadingId);
        _streamReader = null;
        _streamSessionId = null;
        if (err.name === 'AbortError') return;
        appendErrorMessage(err.message);
    }
}

// ===== 重新生成（流式） =====
function regenerate() {
    // 找到最后一条用户消息
    var lastUserMsg = null;
    for (var i = messageHistory.length - 1; i >= 0; i--) {
        if (messageHistory[i].role === 'user') {
            lastUserMsg = messageHistory[i].content;
            break;
        }
    }
    if (!lastUserMsg) return;

    // 移除最后一条助手回复（DOM）
    var msgs = document.querySelectorAll('#chat-messages .message-assistant');
    var last = msgs[msgs.length - 1];
    if (last) last.remove();
    // 从 history 弹出最后一条 assistant 记录
    if (messageHistory.length > 0 && messageHistory[messageHistory.length - 1].role === 'assistant') {
        messageHistory.pop();
    }

    // 复用发送消息逻辑
    sendMessage(lastUserMsg);
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

    // Report 按钮（非闲聊时显示）
    let reportHtml = "";
    if (data.thinking && data.thinking.length > 0 && data.task_type && data.task_type !== "闲聊" && data.task_type !== "问答") {
        reportHtml = `<button class="btn btn-sm btn-outline-secondary mt-2 report-btn">📥 生成详细报告</button>`;
    }

    div.innerHTML = `
        ${thinkingHtml}
                <div class="bubble">${markdownToHtml(data.reply)}</div>
        ${filesHtml}
        ${reportHtml}
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
            this.textContent = "生成失败，重试";
            this.disabled = false;
        }
    });

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ===== 流式 SSE 辅助函数 =====

function createAssistantSkeleton(sessionId) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = "message-assistant";
    div.dataset.streamSession = sessionId;

    var ts = "s-" + Date.now();
    div.innerHTML = '\
        <div class="thinking-section" id="think-' + ts + '">\
            <button class="thinking-toggle" onclick="toggleThinkingPanel(\'think-body-' + ts + '\',this)">\
                <span class="toggle-arrow">\
                    <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>\
                </span>\
                🧠 <span class="thinking-flow">准备中...</span>\
            </button>\
            <div id="think-body-' + ts + '" class="thinking-collapse"></div>\
        </div>\
        <div class="bubble" id="bubble-' + ts + '"></div>';

    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

function handleStreamEvent(div, event) {
    var thinkingBody = div.querySelector('.thinking-collapse');
    var bubble = div.querySelector('.bubble');
    var flowEl = div.querySelector('.thinking-flow');

    switch (event.type) {
        case 'agent_start':
            // 新增 agent 卡片
            var name = event.name || 'Agent';
            var color = COLORS[name] || '#6b7280';
            var icon = ICONS[name] || '🔹';
            var card = document.createElement('div');
            card.className = 'agent-card';
            card.dataset.agentName = name;
            card.innerHTML = '\
                <div class="agent-header" style="border-left-color:' + color + ';">\
                    <span class="agent-badge" style="background:' + color + '18; color:' + color + ';">' + icon + ' ' + escapeHtml(name) + '</span>\
                </div>\
                <div class="agent-body"></div>';
            thinkingBody.appendChild(card);
            // 更新流程指示
            var agents = thinkingBody.querySelectorAll('.agent-card');
            var names = Array.from(agents).map(function(c) { return c.dataset.agentName; });
            flowEl.textContent = names.map(function(n) { return (ICONS[n] || '🔹') + ' ' + n; }).join(' → ');
            // 新卡片展开
            if (agents.length === 1) {
                var toggle = div.querySelector('.thinking-toggle');
                if (toggle) toggle.click();
            }
            break;

        case 'token':
            // 追加到当前 agent 的正文
            var cards = thinkingBody.querySelectorAll('.agent-card');
            var lastCard = cards[cards.length - 1];
            if (lastCard) {
                var body = lastCard.querySelector('.agent-body');
                body.textContent += event.content || '';
            }
            break;

        case 'agent_end':
            // agent 完成——内容已通过 token 逐步写入，无需额外操作
            break;

        case 'done':
            // 最终回复
            bubble.innerHTML = markdownToHtml(event.reply || '');
            div.dataset.thinking = JSON.stringify(event.thinking || []);
            div.dataset.taskType = event.task_type || '';

            // 添加报告按钮（非闲聊/问答）
            if (event.thinking && event.thinking.length > 0 && event.task_type !== '闲聊' && event.task_type !== '问答') {
                var reportBtn = document.createElement('button');
                reportBtn.className = 'btn btn-sm btn-outline-secondary mt-2 report-btn';
                reportBtn.textContent = '📥 生成详细报告';
                reportBtn.addEventListener('click', async function() {
                    this.disabled = true;
                    this.textContent = '生成中...';
                    try {
                        var r = await fetch('/api/report', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ thinking: event.thinking }),
                        });
                        var report = await r.json();
                        var rd = document.createElement('div');
                        rd.className = 'mt-2 p-3 border rounded bg-white';
                        rd.innerHTML = '<strong>📊 详细报告</strong><hr>' + markdownToHtml(report.content);
                        this.replaceWith(rd);
                    } catch (e) {
                        this.textContent = '生成失败，重试';
                        this.disabled = false;
                    }
                });
                div.querySelector('.bubble').after(reportBtn);
            }

            // 更新历史
            messageHistory.push({ role: 'assistant', content: event.reply || '' });
            break;

        case 'error':
            bubble.innerHTML = '<div class="bubble" style="background:#fef2f2;color:#991b1b;border:1px solid #fecaca;">⚠️ ' + escapeHtml(event.content || '未知错误') + '</div>';
            break;

        case 'cancelled':
            bubble.innerHTML = '<div class="bubble" style="color:var(--text-secondary);font-style:italic;">已中断</div>';
            break;
    }

    // 滚动到底部
    var container = document.getElementById('chat-messages');
    if (container) container.scrollTop = container.scrollHeight;
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
    div.innerHTML = '<div class="bubble loading-bubble">思考中<span class="loading-dots"></span></div>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeLoadingMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// ===== 知识库 UI =====
async function loadKnowledgeStats() {
    try {
        const resp = await fetch("/api/knowledge/stats", {
            headers: { "Authorization": "Bearer " + (localStorage.getItem("auth_token") || "") }
        });
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
            const resp = await fetch("/api/knowledge/rebuild", {
                method: "POST",
                headers: { "Authorization": "Bearer " + (localStorage.getItem("auth_token") || "") }
            });
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
            const resp = await fetch("/api/knowledge/upload", {
                method: "POST",
                headers: { "Authorization": "Bearer " + (localStorage.getItem("auth_token") || "") },
                body: formData
            });
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

    // 游客 → sessionStorage
    if (isGuest()) {
        const sessions = loadGuestSessions();
        const sid = _currentSessionId || String(Date.now());
        const title = messageHistory[0]?.content?.slice(0, 50) || "新对话";
        const existing = sessions.findIndex(s => s.id === sid);
        const entry = {
            id: sid,
            title: title,
            messages: [...messageHistory],
            updated: new Date().toISOString(),
        };
        if (existing >= 0) {
            sessions[existing] = entry;
        } else {
            sessions.unshift(entry);
        }
        saveGuestSessions(sessions);
        _currentSessionId = sid;
        if (typeof loadSessionHistory === 'function') loadSessionHistory();
        return;
    }

    // 注册用户 → 带 Token
    try {
        const sid = _currentSessionId || String(Date.now());
        const title = messageHistory[0]?.content?.slice(0, 50) || "新对话";
        await fetch("/api/sessions", {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ id: sid, messages: messageHistory, title: title }),
        });
        _currentSessionId = sid;
        if (typeof loadSessionHistory === 'function') loadSessionHistory();
    } catch (e) {
        console.error("保存会话失败:", e);
    }
}

// ===== 用户工具函数 =====
function getUserName() {
    return localStorage.getItem("mc_uname") || "";
}

// ===== 覆盖 sidebar.html 中的 newChat =====
const _origNewChat = window.newChat;
window.newChat = function() {
    if (_origNewChat) _origNewChat();
    messageHistory = [];
    _currentSessionId = null;
};

// ===== 游客会话（sessionStorage） =====
function isGuest() {
    return !localStorage.getItem("auth_token");
}

function loadGuestSessions() {
    try {
        return JSON.parse(sessionStorage.getItem("guest_sessions") || "[]");
    } catch (e) {
        return [];
    }
}

function saveGuestSessions(sessions) {
    try {
        sessionStorage.setItem("guest_sessions", JSON.stringify(sessions));
    } catch (e) {
        console.warn("sessionStorage 写入失败（可能超出容量）:", e);
    }
}
