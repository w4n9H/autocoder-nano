// ===== Data =====
let conversations = [];

let currentConversationId = '1';
let selectedModel = 'k2.5';
let selectedAgentType = 'general';

// WebSocket 相关
let socket = null;
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
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const voiceBtn = document.getElementById('voiceBtn');

// Model Selector
const modelSelector = document.getElementById('modelSelector');
const modelDropdown = document.getElementById('modelDropdown');
const modelText = document.getElementById('modelText');

// Agent Selector
const agentSelector = document.getElementById('agentSelector');
const agentDropdown = document.getElementById('agentDropdown');
const agentText = document.getElementById('agentText');

// ===== Initialization =====
function init() {
    renderChatList();
    renderMessages();
    setupEventListeners();
    setupSelectors();
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
    console.log(step);

    // 追加到 steps 数组
    targetMsg.steps.push(step);

    // 更新会话时间
    conversation.updatedAt = new Date();

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

    // Close selectors when clicking outside
    document.addEventListener('click', (e) => {
        if (!modelSelector?.contains(e.target)) {
            modelSelector?.classList.remove('active');
        }
        if (!agentSelector?.contains(e.target)) {
            agentSelector?.classList.remove('active');
        }
    });
}

function setupSelectors() {
    // Model selector
    modelSelector?.querySelector('.selector-btn')?.addEventListener('click', () => {
        modelSelector.classList.toggle('active');
        agentSelector?.classList.remove('active');
    });

    modelDropdown?.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', () => {
            const value = item.dataset.value;
            const text = item.querySelector('span').textContent;
            selectedModel = value;
            modelText.textContent = text;

            modelDropdown.querySelectorAll('.dropdown-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            modelSelector.classList.remove('active');
        });
    });

    // Agent selector
    agentSelector?.querySelector('.selector-btn')?.addEventListener('click', () => {
        agentSelector.classList.toggle('active');
        modelSelector?.classList.remove('active');
    });

    agentDropdown?.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', () => {
            const value = item.dataset.value;
            const text = item.querySelector('span').textContent;
            selectedAgentType = value;
            agentText.textContent = text;

            agentDropdown.querySelectorAll('.dropdown-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            agentSelector.classList.remove('active');
        });
    });
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
                content: '你好！我是AI Agent，有什么可以帮助你的吗？',
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

    // 兼容旧数据结构：如果消息没有 steps 但有旧字段，则转换为 steps
    conversation.messages.forEach(msg => {
        if (!msg.steps && msg.role === 'assistant') {
            msg.steps = [];
            // 转换 thinking
            if (Array.isArray(msg.thinking) && msg.thinking.length) {
                msg.thinking.forEach(content => msg.steps.push({ type: 'thinking', content, timestamp: msg.timestamp }));
            }
            // 转换 output
            if (Array.isArray(msg.output) && msg.output.length) {
                msg.output.forEach(content => msg.steps.push({ type: 'output', content, timestamp: msg.timestamp }));
            }
            // 转换 toolCalls
            if (Array.isArray(msg.toolCalls)) {
                msg.toolCalls.forEach(content => msg.steps.push({ type: 'tool_call', content, timestamp: msg.timestamp }));
            }
            // 转换 toolResults
            if (Array.isArray(msg.toolResults)) {
                msg.toolResults.forEach(content => msg.steps.push({ type: 'tool_result', content, timestamp: msg.timestamp }));
            }
            // 转换 final
            if (msg.finalContent) {
                msg.steps.push({ type: 'final', content: msg.finalContent, timestamp: msg.timestamp });
            } else if (msg.content) {
                msg.steps.push({ type: 'final', content: msg.content, timestamp: msg.timestamp });
            }
        }
    });

    const messagesHtml = conversation.messages.map(msg => {
        if (msg.role === 'user') {
            return renderUserMessage(msg);
        } else {
            return renderAssistantMessage(msg);
        }
    }).join('');

    chatOutput.innerHTML = `<div class="messages-container">${messagesHtml}</div>`;

    // 为所有步骤块绑定展开/折叠事件（使用事件委托或直接绑定，这里采用直接绑定）
    chatOutput.querySelectorAll('.step-header').forEach(header => {
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.step-toggle');
            content.classList.toggle('hidden');
            toggle.classList.toggle('expanded');
        });
    });

    chatOutput.scrollTop = chatOutput.scrollHeight;
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
                    ${escapeHtml(msg.content)}
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
            <div class="message-content">
                <div class="message-header">
                    <span class="message-name">AI Agent</span>
                    <span class="message-time">${formatTime(msg.timestamp)}</span>
                </div>
    `;

    // 按顺序渲染每一步
    if (msg.steps && msg.steps.length > 0) {
        msg.steps.forEach((step, index) => {
            console.log(step)
            html += renderStep(step, index);
        });
    }

    html += `</div></div>`;
    return html;
}

// 根据步骤类型渲染不同的块
function renderStep(step, index) {
    switch (step.type) {
        case 'thinking':
            return renderThinkingStep(step, index);
        case 'output':
            return renderOutputStep(step, index);
        case 'tool_call':
            return renderToolCallStep(step, index);
        case 'tool_result':
            return renderToolResultStep(step, index);
        case 'final':
            return renderFinalStep(step, index);
        case 'error':
            return renderErrorStep(step, index);
        default:
            return '';
    }
}

function renderThinkingStep(step, index) {
    return `
        <div class="step-block thinking-step">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>
                    </svg>
                    <span>LLM 思考过程(Thinking)</span>
                </div>
                <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
            </div>
            <div class="step-content hidden">
                <div class="step-text">${escapeHtml(step.content)}</div>
            </div>
        </div>
    `;
}

function renderOutputStep(step, index) {
    return `
        <div class="step-block output-step">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/><path d="M12 8v8"/>
                    </svg>
                    <span>LLM 输出(Output)</span>
                </div>
                <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
            </div>
            <div class="step-content hidden">
                <div class="step-text">${escapeHtml(step.content)}</div>
            </div>
        </div>
    `;
}

function renderToolCallStep(step, index) {
    const tool = step.content; // 假设 content 包含 { name, params }
    return `
        <div class="step-block tool-call">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>
                    </svg>
                    <span>工具调用: ${tool?.name || '未知'}</span>
                </div>
                <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
            </div>
            <div class="step-content hidden">
                <div class="tool-section">
                    <div class="tool-section-label">调用参数</div>
                    <pre class="tool-code">${escapeHtml(tool?.params || '')}</pre>
                </div>
            </div>
        </div>
    `;
}

function renderToolResultStep(step, index) {
    const tool = step.content; // 假设 content 包含 { name, status, result }
    return `
        <div class="step-block tool-result">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/>
                    </svg>
                    <span>工具返回: ${tool?.name || '未知'}</span>
                </div>
                <div class="step-status">
                    <span class="status-badge ${tool?.status === 'success' ? 'success' : 'error'}">${tool?.status || ''}</span>
                    <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M6 9l6 6 6-6"/>
                    </svg>
                </div>
            </div>
            <div class="step-content hidden">
                <div class="tool-section">
                    <div class="tool-section-label">返回消息</div>
                    <pre class="tool-code">${escapeHtml(tool?.params || '')}</pre>
                </div>
                <div class="tool-section">
                    <div class="tool-section-label">返回结果</div>
                    <div class="tool-result-text">${escapeHtml(tool?.result || '')}</div>
                </div>
            </div>
        </div>
    `;
}

function renderFinalStepOld(step, index) {
    return `
        <div class="step-block final-step">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 6L9 17l-5-5"/>
                    </svg>
                    <span></span>
                </div>
                <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
            </div>
            <div class="step-content hidden">
                <div class="message-bubble">${escapeHtml(step.content)}</div>
            </div>
        </div>
    `;
}

function renderFinalStep(step, index) {
    return `
        <div class="final-step-wrapper">
            <div class="message-bubble">${escapeHtml(step.content)}</div>
        </div>
    `;
}

function renderErrorStep(step, index) {
    return `
        <div class="step-block error-step">
            <div class="step-header">
                <div class="step-title">
                    <svg class="step-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>
                    </svg>
                    <span>错误</span>
                </div>
                <svg class="step-toggle" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 9l6 6 6-6"/>
                </svg>
            </div>
            <div class="step-content hidden">
                <div class="message-bubble error">${escapeHtml(step.content)}</div>
            </div>
        </div>
    `;
}

function formatContent(content) {
    return content
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`(.+?)`/g, '<code style="background:#e5e7eb;padding:2px 6px;border-radius:4px;">$1</code>')
        .replace(/\n/g, '<br>');
}

// ===== Input Functions =====
function autoResizeTextarea() {
    if (!chatInput) return;

    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
}

function handleInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function autoResizeTextarea() {
    if (!chatInput) return;
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 200) + 'px';
}

function handleInputKeydown(e) {
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
    conversation.messages.push(assistantMessage);
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

// ===== Start =====
document.addEventListener('DOMContentLoaded', init);

