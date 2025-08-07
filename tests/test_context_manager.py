from autocoder_nano.context import get_context_manager, ContextManagerConfig, get_context_manager_config
import os


def context_manager_test():
    # 1. 获取管理器实例（使用默认配置）
    manager = get_context_manager()
    # 2. 创建对话
    conversation_id = manager.create_conversation(
        name="AI助手对话",
        description="与AI助手的日常对话"
    )
    print(conversation_id)
    # 3. 添加消息
    message_id = manager.append_message(
        conversation_id=conversation_id,
        role="user",
        content="请帮我写一个Python函数"
    )
    print(message_id)
    # 4. 设置当前对话并添加消息
    manager.set_current_conversation(conversation_id)
    manager.append_message_to_current(
        role="assistant",
        content="我来帮您写Python函数。请告诉我具体需求。"
    )


def context_manager_list_conversations_test():
    cmc = ContextManagerConfig()
    cmc.storage_path = os.path.join("/Users/moofs/Code/xxxxx", ".auto-coder", "context")
    manager = get_context_manager(config=cmc)
    print(manager.list_conversations(limit=5))
    # print(manager.get_current_conversation_id())
    # print(manager.delete_conversation("a49866c6-1bc1-45cf-bcf1-94d428426600"))


if __name__ == '__main__':
    context_manager_list_conversations_test()
