// ===== Data =====
let conversations = []

let currentConversationId = '1';
let selectedModel = 'k2.5';
let selectedAgentType = 'general';
let autoScroll = true;

// WebSocket 相关
let socket = null;
// 全局状态
let isGenerating = false;
let reconnectTimer = null;
const WS_RECONNECT_INTERVAL = 3000; // 重连间隔（毫秒）

// ===== DOM Elements =====
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebarOverlay');
const sidebarClose = document.getElementById('sidebarClose');
const menuBtn = document.getElementById('menuBtn');
const newChatBtn = document.getElementById('newChatBtn');
const chatList = document.getElementById('chatList');
const chatOutput = document.getElementById('chatOutput');
chatOutput.addEventListener("scroll", () => {
    const threshold = 40;
    const atBottom =
        chatOutput.scrollHeight -
        chatOutput.scrollTop -
        chatOutput.clientHeight
        < threshold;
    autoScroll = atBottom;
});
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const voiceBtn = document.getElementById('voiceBtn');
const scrollBtn = document.getElementById("scrollBtn");
scrollBtn.style.opacity = "0";
scrollBtn.style.pointerEvents = "none";
chatOutput.addEventListener("scroll", () => {
    const atBottom =
        chatOutput.scrollHeight -
        chatOutput.scrollTop -
        chatOutput.clientHeight < 40;
    autoScroll = atBottom;
    scrollBtn.style.opacity = atBottom ? "0" : "1";
    scrollBtn.style.pointerEvents = atBottom ? "none" : "auto";
});

scrollBtn.onclick = () => {
    autoScroll = true;
    smartScroll();
};

marked.setOptions({
    breaks: true,      // 支持换行
    gfm: true,         // GitHub 风格
});

// ===== Initialization =====
function init() {
    renderChatList();
    renderMessages();
    setupEventListeners();
    initWebSocket(); // 建立 WebSocket 连接
}

// ===== WebSocket 相关函数 =====
function initWebSocket() {
    // 如果已有连接，先关闭
    if (socket) {
        socket.close();
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('WebSocket 连接已建立');
        // 可以显示连接成功的提示（可选）
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingMessage(data);
        } catch (e) {
            console.error('解析 WebSocket 消息失败', e);
        }
    };

    socket.onerror = (error) => {
        console.error('WebSocket 错误', error);
    };

    socket.onclose = () => {
        console.log('WebSocket 连接关闭，尝试重连...');
        // 设置重连定时器
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(() => {
            initWebSocket();
        }, WS_RECONNECT_INTERVAL);
    };
}

// 处理从后端推送的消息
function handleIncomingMessage(data) {
    // 确保消息属于当前会话
    if (data.conversationId && data.conversationId !== currentConversationId) return;

    const conversation = conversations.find(c => c.id === currentConversationId);
    if (!conversation) return;

    // 查找对应的助理消息
    let targetMsg = null;
    if (data.messageId) {
        targetMsg = conversation.messages.find(m => m.id === data.messageId);
    }

    // 如果找不到且类型为 final/error，则创建新消息
    if (!targetMsg && (data.type === 'final' || data.type === 'error')) {
        targetMsg = {
            id: data.messageId || ('assistant-' + Date.now()),
            role: 'assistant',
            timestamp: new Date(),
            steps: [] // 初始化步骤数组
        };
        conversation.messages.push(targetMsg);
    }

    if (!targetMsg) return; // 其他中间消息若找不到对应消息，直接忽略

    // 构造步骤对象
    const step = {
        type: data.type,
        content: data.content,
        timestamp: new Date()
    };

    // 追加到 steps 数组
    step.status = "running";
    targetMsg.steps.push(step);

    const steps = targetMsg.steps;

    if (steps.length > 1) {
        steps[steps.length - 2].status = "done";
    }

    // 更新会话时间
    conversation.updatedAt = new Date();

    if (data.type === 'final' || data.type === 'error') {
        targetMsg.steps.forEach(s => s.status = "done");

        isGenerating = false;
        sendBtn.disabled = false;
        sendBtn?.classList.remove('disabled');

        if (targetMsg) {
            targetMsg.generating = false;
        }
    }

    // 重新渲染
    renderMessages();
    renderChatList();
}

// ===== Event Listeners =====
function setupEventListeners() {
    // Sidebar toggle
    menuBtn?.addEventListener('click', openSidebar);
    sidebarClose?.addEventListener('click', closeSidebar);
    sidebarOverlay?.addEventListener('click', closeSidebar);

    // New chat
    newChatBtn?.addEventListener('click', createNewConversation);

    // Input
    chatInput?.addEventListener('input', autoResizeTextarea);
    chatInput?.addEventListener('keydown', handleInputKeydown);
    sendBtn?.addEventListener('click', sendMessage);
}

// ===== Sidebar Functions =====
function openSidebar() {
    sidebar?.classList.add('open');
    sidebarOverlay?.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeSidebar() {
    sidebar?.classList.remove('open');
    sidebarOverlay?.classList.remove('active');
    document.body.style.overflow = '';
}

// ===== Chat List Functions =====
function renderChatList() {
    if (!chatList) return;
    chatList.innerHTML = conversations.map(conv => `
        <div class="chat-item ${conv.id === currentConversationId ? 'active' : ''}" data-id="${conv.id}">
            <div class="chat-item-icon">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
                </svg>
            </div>
            <div class="chat-item-content">
                <div class="chat-item-title">${escapeHtml(conv.title)}</div>
                <div class="chat-item-time">${formatTime(conv.updatedAt)}</div>
            </div>
            <button class="chat-item-menu" data-id="${conv.id}" title="更多操作">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>
                </svg>
            </button>
        </div>
    `).join('');

    chatList.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (!e.target.closest('.chat-item-menu')) selectConversation(item.dataset.id);
        });
    });
    chatList.querySelectorAll('.chat-item-menu').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteConversation(btn.dataset.id);
        });
    });
}

function selectConversation(id) {
    currentConversationId = id;
    renderChatList();
    renderMessages();
    closeSidebar();
}

function createNewConversation() {
    const newConv = {
        id: Date.now().toString(),
        title: '新会话',
        messages: [{
            id: 'welcome-' + Date.now(),
            role: 'assistant',
            timestamp: new Date(),
            steps: [{
                type: 'final',
                content: '你好！我是你的专属 AI 助手(Agent)，有什么可以帮助你的吗？',
                timestamp: new Date()
            }]
        }],
        updatedAt: new Date()
    };
    conversations.unshift(newConv);
    currentConversationId = newConv.id;
    renderChatList();
    renderMessages();
    closeSidebar();
}

function deleteConversation(id) {
    if (confirm('确定要删除这个会话吗？')) {
        conversations = conversations.filter(c => c.id !== id);
        if (currentConversationId === id && conversations.length > 0) {
            currentConversationId = conversations[0].id;
        }
        renderChatList();
        renderMessages();
    }
}

// ===== Message Functions =====
function renderMessages() {
    if (!chatOutput) return;
    const conversation = conversations.find(c => c.id === currentConversationId);
    if (!conversation) return;

    const messagesHtml = conversation.messages.map(msg => {
        if (msg.role === 'user') {
            return renderUserMessage(msg);
        } else {
            return renderAssistantMessage(msg);
        }
    }).join('');

    chatOutput.innerHTML = `<div class="messages-container">${messagesHtml}</div>`;

    wrapExecutionBlocks();

    smartScroll();
}

function wrapExecutionBlocks() {

    document.querySelectorAll('.message-content').forEach(container => {

        const rows = Array.from(
            container.querySelectorAll(':scope > .timeline-row')
        );

        if (rows.length === 0) return;

        const isGenerating = container.dataset.generating === "true";

        const panel = document.createElement('div');
        panel.className = 'execution-panel';

        const header = document.createElement('div');
        header.className = 'execution-header';

        header.innerHTML = `
            <span class="execution-title">
                ${isGenerating ? '- 执行中...' : '✓ 执行完成'}
                (${rows.length} steps)
            </span>
            <span class="arrow">▼</span>
        `;

        const body = document.createElement('div');
        body.className = 'execution-body';

        rows.forEach(r => body.appendChild(r));

        // 点击折叠
        header.onclick = () => {
            body.classList.toggle('collapsed');
            header.querySelector('.arrow').classList.toggle('rotated');
        };

        panel.appendChild(header);
        panel.appendChild(body);

        const final = container.querySelector('.final-step-wrapper');

        if (final) {
            container.insertBefore(panel, final);
        } else {
            container.appendChild(panel);
        }

        // 🔥 自动折叠逻辑
        if (!isGenerating) {
            body.classList.add('collapsed');
            header.querySelector('.arrow').classList.add('rotated');
        }
    });
}

function renderUserMessage(msg) {
    return `
        <div class="message">
            <div class="message-avatar user">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>
                </svg>
            </div>
            <div class="message-content">
                <div class="message-header">
                    <span class="message-name">你</span>
                    <span class="message-time">${formatTime(msg.timestamp)}</span>
                </div>
                <div class="message-bubble user">
                    ${escapeHtml(msg.content.trim())}
                </div>
            </div>
        </div>
    `;
}

function renderAssistantMessage(msg) {
    let html = `
        <div class="message">
            <div class="message-avatar assistant">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
                </svg>
            </div>
            <div class="message-content" data-generating="${msg.generating ? 'true' : 'false'}">
                <div class="message-header">
                    <span class="message-name">AI Agent</span>
                    <span class="message-time">${formatTime(msg.timestamp)}</span>
                </div>
    `;

    // 按顺序渲染每一步
    if (msg.steps && msg.steps.length > 0) {
        msg.steps.forEach((step, index) => {
            const isLast = index === msg.steps.length - 1;
            html += renderStep(step, index, isLast);
        });
    }
    const hasFinal = msg.steps?.some(s => s.type === 'final');
    if (msg.generating && !hasFinal) {
        html += renderFinalPlaceholder();
    }

    html += `</div></div>`;
    return html;
}

// 根据步骤类型渲染不同的块
function renderStep(step, index, isLast) {
    let label = "";
    let detail = "";
    let statusIcon = "";
    if (step.status === "running") {
        statusIcon = `<span class="step-running"></span>`;
    } else if (step.status === "done") {
        statusIcon = `<span class="step-done">✓</span>`;
    }
    const branch = isLast ? "`--" : "|--";

    switch (step.type) {
        case 'thinking':
            label = "Thinking";
            detail = step.content || "";
            break;
        case 'output':
            label = "Output";
            detail = step.content || "";
            break;
        case 'tool_call':
            label = "Tool Call";
            detail = typeof step.content === "string"
                ? step.content
                : JSON.stringify(step.content, null, 2);
            break;
        case 'tool_result':
            label = "Tool Finished";
            detail = typeof step.content === "string"
                ? step.content
                : JSON.stringify(step.content, null, 2);
            break;
        case 'error':
            label = "Error";
            detail = step.content || "";
            break;
        case 'final':
            return renderFinalStep(step, index);
        default:
            return '';
    }

    return `
        <div class="timeline-row ${step.status}" onclick="toggleStep(${index}, this)">
            <div class="timeline-tree">
                <span class="tree-branch">${branch}</span>
            </div>

            <div class="timeline-main">
                <div class="timeline-label">${statusIcon} ${label}</div>

                <div class="timeline-detail">
                    <pre>${escapeHtml(detail)}</pre>
                </div>
            </div>
        </div>
    `;
}

function renderFinalPlaceholder() {
    return `
        <div class="final-step-wrapper final-placeholder">正在生成最终回答...</div>
    `;
}

function renderFinalStep(step, index) {
    const rawContent = Array.isArray(step.content)
        ? step.content.join("\n")
        : step.content;

    return `
        <div class="final-step-wrapper">${marked.parse(rawContent)}</div>
    `;
}

// ===== Input Functions =====
function autoResizeTextarea() {
    if (!chatInput) return;

    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
}

function handleInputKeydown(e) {
    if (isGenerating) return;   // 防止回车发送
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function sendMessage() {
    const content = chatInput?.value.trim();
    if (!content) return;

    const conversation = conversations.find(c => c.id === currentConversationId);
    if (!conversation) return;

    const assistantMessageId = 'assistant-' + Date.now();

    const userMessage = {
        id: 'user-' + Date.now(),
        role: 'user',
        content: content,
        timestamp: new Date()
    };

    const assistantMessage = {
        id: assistantMessageId,
        role: 'assistant',
        timestamp: new Date(),
        steps: []  // 初始为空
    };

    conversation.messages.push(userMessage);

    assistantMessage.generating = true; // 新增
    conversation.messages.push(assistantMessage);

    isGenerating = true;
    sendBtn.disabled = true;
    sendBtn?.classList.add('disabled');

    conversation.updatedAt = new Date();

    chatInput.value = '';
    chatInput.style.height = 'auto';

    if (conversation.messages.length === 2) {
        conversation.title = content.slice(0, 20) + (content.length > 20 ? '...' : '');
    }

    renderChatList();
    renderMessages();

    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
            type: 'user_message',
            conversationId: currentConversationId,
            messageId: assistantMessageId,
            content: content
        }));
    } else {
        alert('WebSocket 未连接，请刷新页面重试。');
        conversation.messages.pop(); // 移除助理占位
        conversation.messages.pop(); // 移除用户消息
        renderChatList();
        renderMessages();
    }
}

// ===== Utility Functions =====
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(date) {
    const now = new Date();
    const diff = now - new Date(date);
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;
    if (days < 7) return `${days}天前`;

    return new Date(date).toLocaleDateString('zh-CN', {
        month: 'short',
        day: 'numeric',
    });
}

function copyCode(btn) {
    const code = btn.closest('.code-block').querySelector('code').textContent;
    navigator.clipboard.writeText(code).then(() => {
        btn.textContent = '已复制';
        setTimeout(() => btn.textContent = '复制', 2000);
    });
}

function toggleStep(index, el) {

    const detail = el.querySelector(".timeline-detail");

    if (!detail) return;

    detail.classList.toggle("open");
}

function smartScroll() {

    if (!autoScroll) return;

    requestAnimationFrame(() => {
        chatOutput.scrollTop =
            chatOutput.scrollHeight;
    });
}

// ===== Start =====
document.addEventListener('DOMContentLoaded', init);

