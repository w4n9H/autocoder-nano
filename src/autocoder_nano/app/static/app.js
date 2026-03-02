// ===== Data =====
let conversationsX = []
let conversations = [
    {
        id: '1',
        title: '示例对话 - 多步骤演示',
        updatedAt: new Date(),
        messages: [
            {
                id: 'user-example-1',
                role: 'user',
                content: '请帮我分析一下今天的天气，并推荐出行方案。',
                timestamp: new Date(Date.now() - 3600000) // 1小时前
            },
            {
                id: 'assistant-example-1',
                role: 'assistant',
                timestamp: new Date(Date.now() - 3500000),
                steps: [
                    {
                        type: 'thinking',
                        content: ['用户询问天气和出行建议，需要先获取实时天气数据。'],
                        timestamp: new Date(Date.now() - 3490000),
                        status: "running"
                    },
                    {
                        type: 'thinking',
                        content: '考虑调用天气API，参数需要城市名称，默认为用户所在城市。',
                        timestamp: new Date(Date.now() - 3480000),
                        status: "running"
                    },
                    {
                        type: 'output',
                        content: '正在连接天气服务...',
                        timestamp: new Date(Date.now() - 3470000),
                        status: "running"
                    },
                    {
                        type: 'tool_call',
                        content: {
                            name: 'get_weather',
                            params: JSON.stringify({ city: '北京', units: 'metric' }, null, 2)
                        },
                        timestamp: new Date(Date.now() - 3460000),
                        status: "running"
                    },
                    {
                        type: 'tool_result',
                        content: {
                            name: 'get_weather',
                            status: 'success',
                            params: JSON.stringify({ city: '北京', units: 'metric' }, null, 2),
                            result: JSON.stringify({
                                temperature: 22,
                                condition: '晴',
                                humidity: 45,
                                wind: '3级'
                            }, null, 2)
                        },
                        timestamp: new Date(Date.now() - 3450000),
                        status: "running"
                    },
                    {
                        type: 'thinking',
                        content: '根据天气数据，建议用户适合户外活动，但注意防晒。',
                        timestamp: new Date(Date.now() - 3440000),
                        status: "running"
                    },
                    {
                        type: 'output',
                        content: '天气晴朗，温度22°C，适合出行。',
                        timestamp: new Date(Date.now() - 3430000),
                        status: "running"
                    },
                    {
                        type: 'final',
                        content: '北京今天天气晴朗，温度22°C，湿度45%，风力3级。非常适合户外活动，建议您带上遮阳帽和太阳镜。如果计划长时间在户外，记得涂抹防晒霜。',
                        timestamp: new Date(Date.now() - 3420000),
                        status: "running"
                    }
                ]
            },
            {
                id: 'user-example-2',
                role: 'user',
                content: '那明天呢？',
                timestamp: new Date(Date.now() - 3400000)
            },
            {
                id: 'assistant-example-2',
                role: 'assistant',
                timestamp: new Date(Date.now() - 3300000),
                steps: [
                    {
                        type: 'thinking',
                        content: '用户询问明天的天气，需要重新调用API。',
                        timestamp: new Date(Date.now() - 3290000),
                        status: "running"
                    },
                    {
                        type: 'tool_call',
                        content: {
                            name: 'get_weather_forecast',
                            params: JSON.stringify({ city: '北京', days: 1 }, null, 2)
                        },
                        timestamp: new Date(Date.now() - 3280000),
                        status: "running"
                    },
                    {
                        type: 'tool_result',
                        content: {
                            name: 'get_weather_forecast',
                            status: 'error',
                            params: JSON.stringify({ city: '北京', days: 1 }, null, 2),
                            result: 'API 调用失败，服务暂时不可用'
                        },
                        timestamp: new Date(Date.now() - 3270000),
                        status: "running"
                    },
                    {
                        type: 'error',
                        content: '抱歉，获取明日天气数据失败，请稍后重试。',
                        timestamp: new Date(Date.now() - 3260000),
                        status: "running"
                    }
                ]
            }
        ]
    }
];

let currentConversationId = '1';
let selectedModel = 'k2.5';
let selectedAgentType = 'general';

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
                content: '你好！我是专属 AI 助手(Agent)，有什么可以帮助你的吗？',
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

    // 为所有步骤块绑定展开/折叠事件（使用事件委托或直接绑定，这里采用直接绑定）
    chatOutput.querySelectorAll('.step-header').forEach(header => {
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.step-toggle');
            content.classList.toggle('hidden');
            toggle.classList.toggle('expanded');
        });
    });

    requestAnimationFrame(() => {
        chatOutput.scrollTop = chatOutput.scrollHeight;
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
    if (msg.generating) {
        html += `
            <div class="message-bubble generating">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
            </div>
        `;
    }

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
    let label = "";
    let detail = "";
    let statusIcon = "";
    if (step.status === "running") {
        statusIcon = `<span class="step-running"></span>`;
    } else if (step.status === "done") {
        statusIcon = `<span class="step-done">✓</span>`;
    }

    switch (step.type) {
        case 'thinking':
            // return renderThinkingStep(step, index);
            label = "Thinking";
            detail = step.content || "";
            break;
        case 'output':
            // return renderOutputStep(step, index);
            label = "Output";
            detail = step.content || "";
            break;
        case 'tool_call':
            // return renderToolCallStep(step, index);
            label = "Tool Call";
            detail = typeof step.content === "string"
                ? step.content
                : JSON.stringify(step.content, null, 2);
            break;
        case 'tool_result':
            // return renderToolResultStep(step, index);
            label = "Tool Finished";
            detail = typeof step.content === "string"
                ? step.content
                : JSON.stringify(step.content, null, 2);
            break;
        case 'final':
            return renderFinalStep(step, index);
        case 'error':
            // return renderErrorStep(step, index);
            label = "Error";
            detail = step.content || "";
            break;
        default:
            return '';
    }

    return `
        <div class="timeline-row" onclick="toggleStep(${index}, this)">
            <div class="timeline-dot"></div>

            <div class="timeline-main">
                <div class="timeline-label">${statusIcon} ${label}</div>

                <div class="timeline-detail">
                    <pre>${escapeHtml(detail)}</pre>
                </div>
            </div>
        </div>
    `;
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

// ===== Start =====
document.addEventListener('DOMContentLoaded', init);

