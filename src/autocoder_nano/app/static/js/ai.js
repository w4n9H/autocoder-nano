document.addEventListener('DOMContentLoaded', () => {
    // DOM 元素引用
    const commandInput = document.querySelector('.command-input');
    const sendButton = document.querySelector('.send-button');
    const messageList = document.querySelector('.message-list');
    let currentEventSource = null;

    // 示例按钮点击处理
    document.querySelectorAll('.example-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            commandInput.value = e.target.textContent;
            commandInput.focus();
        });
    });

    // 发送消息核心逻辑
    const handleSubmit = () => {
        const text = commandInput.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        startAIResponse(text);
        commandInput.value = '';
        commandInput.focus();
    };

    // 事件源管理
    const startAIResponse = (prompt) => {
        // 关闭之前的连接
        if (currentEventSource) {
            currentEventSource.close();
        }

        // 创建等待消息
        const thinkingMessage = addMessage('您的提问: ' + prompt, 'thinking');
        const aiMessage = addMessage('', 'ai');
        const aiContentDiv = aiMessage.querySelector('.content');

        // 初始化事件源
        currentEventSource = new EventSource(`/chat?prompt=${encodeURIComponent(prompt)}`);

        // 流式响应处理
        currentEventSource.onmessage = (e) => {
            const isThinkingChunk = e.data.startsWith('<thinking>');

            if (isThinkingChunk) {
                const cleanData = e.data.replace('<thinking>', '')
                thinkingMessage.innerHTML += `
                    <div class="content">${cleanData}</div>
                `;
            } else {
                aiContentDiv.innerHTML += e.data;
            }

            messageList.scrollTop = messageList.scrollHeight;
        };

        currentEventSource.onerror = () => {
            currentEventSource.close();
            // 确保最终状态更新
            if (!aiContentDiv.textContent) {
                aiContentDiv.textContent = '响应中断，请重试';
            }
            thinkingMessage.querySelector('.timestamp').textContent =
                new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        };
    };

    // 事件监听器
    sendButton.addEventListener('click', (e) => {
        e.preventDefault();
        handleSubmit();
    });

    commandInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    });

    // 消息创建函数
    // 消息创建函数
    const addMessage = (text, type) => {
        const message = document.createElement('div');
        message.className = `message ${type}`;

        // 条件化时间戳
        const timestampHtml = type !== 'thinking'
            ? `<div class="timestamp">${new Date().toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit'
              })}</div>`
            : '';

        if (type == 'ai') {
            message.innerHTML = `
                <div class="content" id="markdown-viewer">${text}</div>
                ${timestampHtml}
            `;
        } else {
            message.innerHTML = `
            <div class="content">${text}</div>
            ${timestampHtml}
        `;
        }

        messageList.appendChild(message);
        messageList.scrollTop = messageList.scrollHeight;
        return message;
    };
});