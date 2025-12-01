def easy_help():
    print(f"\033[1m支持的命令：\033[0m")
    print(f"  \033[94m命令\033[0m - \033[93m描述\033[0m")
    print(f"  \033[94m/add_files\033[0m \033[93m<file1> <file2> ...\033[0m - \033[92m将文件添加到当前会话\033[0m")
    print(f"  \033[94m/list_files\033[0m - \033[92m列出当前会话中的所有活动文件\033[0m")
    print(f"  \033[94m/remove_files\033[0m \033[93m<file1>,<file2> ...\033[0m - \033[92m从当前会话中移除文件\033[0m")
    print(f"  \033[94m/conf\033[0m \033[93m<key>:<value>\033[0m - \033[92m使用/conf <args>:<type>设置你的AutoCoder配置")
    print(f"  \033[94m/chat\033[0m \033[93m<query>\033[0m - \033[92m与AI聊天，获取关于当前活动文件的见解\033[0m")
    print(f"  \033[94m/coding\033[0m \033[93m<query>\033[0m - \033[92m根据需求请求AI修改代码\033[0m")
    print(f"  \033[94m/auto\033[0m \033[93m<query>\033[0m - \033[92m使用Agentic完成你的任务\033[0m")
    print(f"  \033[94m/revert\033[0m - \033[92m撤销上次代码聊天的提交\033[0m")
    print(f"  \033[94m/commit\033[0m - \033[92m根据用户人工修改的代码自动生成yaml文件并提交更改\033[0m")
    print(f"  \033[94m/index/build\033[0m - \033[92m触发构建项目索引\033[0m")
    print(f"  \033[94m/index/query\033[0m \033[93m<query>\033[0m - \033[92m查询项目索引进行查询\033[0m")
    print(f"  \033[94m/rag/build\033[0m - \033[92m为/conf rag_url:<local_path> 设置的目录构建RAG索引\033[0m")
    print(f"  \033[94m/rag/query\033[0m \033[93m<query>\033[0m - \033[92m在/conf rag_url设置的RAG目录中检索文档\033[0m")
    print(f"  \033[94m/rules\033[0m - \033[92m基于当前活动文件或者Commit变更生成功能模式和设计模式\033[0m")
    print(f"  \033[94m/context\033[0m \033[93m<subcommand>\033[0m - \033[92m管理会话上下文(/context /list查看,/context /remove删除)\033[0m")
    print(f"  \033[94m/editor\033[0m \033[93m<file_path>\033[0m - \033[92m打开文件编辑器\033[0m")
    print(f"  \033[94m/help\033[0m - \033[92m显示此帮助消息\033[0m")
    print(f"  \033[94m/exclude_dirs\033[0m \033[93m<dir1>,<dir2> ...\033[0m - \033[92m添加要从项目中排除的目录\033[0m")
    print(f"  \033[94m/exclude_files\033[0m \033[93m<pattern>/<subcommand>\033[0m - \033[92m排除文件(/exclude_files /list查看,/exclude_files /drop删除)\033[0m")
    print(f"  \033[94m/shell\033[0m \033[93m<command>\033[0m - \033[92m执行shell命令\033[0m")
    print(f"  \033[94m/mode\033[0m - \033[92m切换输入模式(normal/auto_detect)\033[0m")
    print(f"  \033[94m/models\033[0m \033[93m<subcommand>\033[0m - \033[92m管理LLM模型(/models /list查看,/models /add添加)\033[0m")
    print(f"  \033[94m/exit\033[0m - \033[92m退出程序\033[0m")
    print()


def show_help(query: str):
    if not query:
        easy_help()

    if query == "/add_files" or query == "add_files":
        print(f"\033[94m/add_files\033[0m \033[93m<file1> <file2> ...\033[0m - \033[92m将单个/多个文件添加到当前会话\033[0m")
        print(f"\033[94m/add_files /group\033[0m \033[93m<groupname>\033[0m - \033[92m显示当前所有组\033[0m")
        print(f"\033[94m/add_files /group /add\033[0m \033[93m<groupname>\033[0m - "
              f"\033[92m将当前活跃文件设置为组<groupname>\033[0m")
        print(f"\033[94m/add_files /group /drop\033[0m \033[93m<groupname>\033[0m - "
              f"\033[92m删除组<groupname>\033[0m")
        print(f"\033[94m/add_files /group\033[0m \033[93m<groupname1>,<groupname2>\033[0m - "
              f"\033[92m合并组<groupname1>和<groupname2>\033[0m")
        print(f"\033[94m/add_files /refresh\033[0m - \033[92m文件刷新\033[0m")
        print()

    if query == "/remove_files" or query == "remove_files":
        print(f"\033[94m/remove_files\033[0m \033[93m<file1>,<file2> ...\033[0m - \033[92m从当前会话中移除文件\033[0m")
        print(f"\033[94m/remove_files /all\033[0m - \033[92m清空当前会话所有文件\033[0m")
        print()

    elif query == "/chat" or query == "chat":
        print(f"\033[94m/chat\033[0m \033[93m<query>\033[0m - \033[92m与AI聊天,获取关于当前活动文件的见解\033[0m")
        print(f"\033[94m/chat /history\033[0m - \033[92m显示你与AI最近5条沟通记录\033[0m")
        print(f"\033[94m/chat /new\033[0m - \033[92m会开启一个新的AI会话,此时历史沟通记录会备份,不会通过/history显示\033[0m")
        print(f"\033[94m/chat /review\033[0m \033[93m<query>\033[0m - \033[92m对当前会话文件以及@关联的文件进行Review\033[0m")
        print()

    elif query == "/coding" or query == "coding":
        print(f"\033[94m/coding\033[0m \033[93m<query>\033[0m - \033[92m根据需求请求AI修改代码\033[0m")
        print(f"\033[94m/coding /apply\033[0m \033[93m<query>\033[0m - \033[92m会带上历史记录与AI沟通,会被/chat /new重置\033[0m")
        print()

    elif query == "/commit" or query == "commit":
        print(f"\033[94m/commit\033[0m - \033[92m根据用户人工修改的代码自动生成yaml文件并提交更改\033[0m")
        print()

    elif query == "/conf" or query == "conf":
        print(
            f"\033[94m/conf\033[0m \033[93m<key>:<value>\033[0m  - \033[92m设置配置。使用 /conf project_type:<type> "
            f"设置索引的项目类型\033[0m"
        )
        print(f"\033[94m常见参数如下:\033[0m")
        print(f"\033[94mproject_type\033[0m - \033[92m项目的类型(支持 py 等项目类型以及 .py,.js 等后缀类型)\033[0m")
        print(f"\033[94mskip_build_index\033[0m - \033[92m是否跳过索引构建(索引可以帮助您通过查询找到相关文件)\033[0m")
        print(f"\033[94mskip_filter_index\033[0m - \033[92m是否跳过使用索引过滤文件\033[0m")
        print(f"\033[94mindex_filter_level\033[0m - \033[92m用于查找相关文件的过滤级别\033[0m")
        print(f"    \033[94m0\033[0m - \033[92m仅过滤 <query> 中提到的文件名\033[0m")
        print(f"    \033[94m1\033[0m - \033[92m过滤 <query> 中提到的文件名以及可能会隐含使用的文件\033[0m")
        print(f"    \033[94m2\033[0m - \033[92m从 0,1 中获得的文件,再寻找这些文件相关的文件\033[0m")
        print(f"\033[94mskip_commit\033[0m - \033[92m是否跳过Commit,默认为False\033[0m")
        print()

    elif query == "/mode" or query == "mode":
        print(f"\033[94m/mode\033[0m - \033[92m切换输入模式\033[0m")
        print(f"\033[94m/mode normal\033[0m - \033[92m切换到正常模式,即编码模式\033[0m")
        print(f"\033[94m/mode auto_detect\033[0m - \033[92m切换到自然语言模式,可直接输入自然语言生成shell脚本\033[0m")
        print()

    elif query == "/models" or query == "models":
        print(f"\033[94m/models\033[0m - \033[92m管理模型配置,新增/删除/测试模型\033[0m")
        print(f"\033[94m/models /list\033[0m - \033[92m列出所有部署模型\033[0m")
        print(f"\033[94m/models /check\033[0m - \033[92m检查所有部署模型的可用性\033[0m")
        print(f"\033[94m/models /add_model\033[0m \033[93m<model_info>\033[0m - \033[92m新增模型\033[0m")
        print(f"    \033[94m<model_info>\033[0m - \033[92mname=模型在Auto中的别名 base_url=https://xx api_key=xx "
              f"model=模型在供应商的别名\033[0m")
        print(f"\033[94m/models /remove\033[0m \033[93m<model_name>\033[0m - \033[92m删除模型\033[0m")
        print()