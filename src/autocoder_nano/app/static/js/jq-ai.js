$(function() {
    // DOM 元素引用
    const $commandInput = $('.command-input');
    const $sendButton = $('.send-button');
    const $messageList = $('.message-list');
    let currentEventSource = null;
    let aiMessageCounter = 0; // 用于生成唯一ID

    // 示例按钮点击处理
    $('.example-btn').each(function() {
        $(this).on('click', function(e) {
            e.preventDefault();
            $commandInput.val($(this).text()).focus();
        });
    });

    // 发送消息核心逻辑
    const handleSubmit = () => {
        const text = $commandInput.val().trim();
        if (!text) return;

        // 更新任务状态显示
        const shortText = text.substring(0, 20) + (text.length > 20 ? "..." : "");
        $('#current-task-text').text(shortText);
        $('#current-task-loading').show();

        addMessage(text, 'user');
        startAIResponse(text);
        $commandInput.val('').focus();
    };

    // 事件源管理
    const startAIResponse = (prompt) => {
        // 关闭之前的连接
        if (currentEventSource) {
            currentEventSource.close();
        }

        // 创建等待消息
        const { $message: $thinkingMessage } = addMessage('您的提问: ' + prompt, 'thinking');
        const { $message: $aiMessage, aiId } = addMessage('', 'ai');
        const $aiContentDiv = $aiMessage.find('.content');

        // 初始化事件源
        currentEventSource = new EventSource(`/chat?prompt=${encodeURIComponent(prompt)}`);

        // 流式响应处理
        currentEventSource.onmessage = (e) => {
            if (e.data === '[DONE]') { // 假设服务器发送结束标志
                currentEventSource.close();
                // 隐藏加载状态
                $('#current-task-loading').hide();
                convertToMarkdown(aiId, $aiContentDiv.text());
                return;
            }

            const isThinkingChunk = e.data.startsWith('<thinking>');

            if (isThinkingChunk) {
                const cleanData = e.data.replace('<thinking>', '');
                $thinkingMessage.append(
                    $('<div>').addClass('content').text(cleanData)
                );
            } else {
                const data = JSON.parse(e.data);
                if (data.error) {return;}
                $aiContentDiv.html((_, html) => html + data.content);
            }

            $messageList.scrollTop($messageList[0].scrollHeight);
        };

        currentEventSource.onerror = () => {
            currentEventSource.close();
            // 隐藏加载状态
            $('#current-task-loading').hide();
            // 确保最终状态更新
            if (!$aiContentDiv.text()) {
                $aiContentDiv.text('响应中断，请重试');
            }
            //convertToMarkdown(aiId, $aiContentDiv.text());
            // 新增：检查是否已转换
            if (!$aiContentDiv.data('converted')) {
                convertToMarkdown(aiId, $aiContentDiv.text());
                $aiContentDiv.data('converted', true);
            }
            $thinkingMessage.find('.timestamp').text(
                new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            );
        };
    };

    // Markdown转换函数
    const convertToMarkdown = (elementId, content) => {
        const $target = $('#' + elementId);
        if ($target.data('markdown-rendered')) return;

        // 清空原始文本内容
        $target.empty(); // 新增：清除原始纯文本

        const markdownContent = content.replace(/\\n/g, '\n');
        editormd.markdownToHTML(elementId, {
            markdown: markdownContent,
            htmlDecode: "style,script,iframe",
            emoji: true,
            taskList: true,
            tex: true,
            flowChart: true,
            sequenceDiagram: true,
            codeFold: true,
            readOnly: true
        });

        $target.data('markdown-rendered', true);
    };

    // 事件监听器
    $sendButton.on('click', function(e) {
        e.preventDefault();
        handleSubmit();
    });

    $commandInput.on('keydown', function(e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    });

    // 消息创建函数
    const addMessage = (text, type) => {
        const $message = $('<div>').addClass(`message ${type}`);
        const timestamp = type !== 'thinking' ?
            $('<div>').addClass('timestamp').text(
                new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            ) :
            '';

        let aiId;
        if (type === 'ai') {
            aiId = `markdown-viewer-${aiMessageCounter++}`;
            $message.append(
                $('<div>').addClass('content').attr('id', aiId).text(text), // 使用text防止XSS
                timestamp
            );
        } else {
            $message.append(
                $('<div>').addClass('content').text(text),
                timestamp
            );
        }

        $messageList.append($message);
        $messageList.scrollTop($messageList[0].scrollHeight);
        return { $message, aiId };
    };
});