import os
from typing import List, Tuple, Dict

from autocoder_nano.utils.git_utils import get_commit_changes
from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import AutoCoderArgs, SourceCodeList
from autocoder_nano.utils.printer_utils import Printer


printer = Printer()


class AutoRulesLearn:

    def __init__(self, args: AutoCoderArgs, llm: AutoLLM):
        self.args = args
        self.llm = llm

    @prompt()
    def _analyze_commit_changes(
        self, querie_with_urls_and_changes: List[Tuple[str, List[str], Dict[str, Tuple[str, str]]]]
    ):
        """
        下面是用户一次提交的代码变更：
        <changes>
        {% for query,urls,changes in querie_with_urls_and_changes %}
        ## 原始的任务需求
        {{ query }}

        修改的文件:
        {% for url in urls %}
        - {{ url }}
        {% endfor %}

        代码变更:
        {% for file_path, (before, after) in changes.items() %}
        ##File: {{ file_path }}
        ##修改前:

        {{ before or "New file" }}

        ##File: {{ file_path }}
        ##修改后:

        {{ after or "File deleted" }}

        {% endfor %}
        {% endfor %}
        </changes>

        请对根据上面的代码变更进行深入分析，提取具有通用价值的功能模式和设计模式，转化为可在其他项目中复用的代码规则（rules）。

        - 识别代码变更中具有普遍应用价值的功能点和模式
        - 将这些功能点提炼为结构化规则，便于在其他项目中快速复用
        - 生成清晰的使用示例，包含完整依赖和调用方式

        最后，新生成的文件格式要是这种形态的：

        <example_rules>
        ---
        description: [简明描述规则的功能，20字以内]
        globs: [匹配应用此规则的文件路径，如"src/services/*.py"]
        alwaysApply: [是否总是应用，通常为false]
        ---

        # [规则主标题]

        ## 简要说明
        [该规则的功能、适用场景和价值，100字以内]

        ## 典型用法
        ```python
        # 完整的代码示例，包含:
        # 1. 必要的import语句
        # 2. 类/函数定义
        # 3. 参数说明
        # 4. 调用方式
        # 5. 关键注释
        ```

        ## 依赖说明
        - [必要的依赖库及版本]
        - [环境要求]
        - [初始化流程(如有)]

        ## 学习来源
        [从哪个提交变更的哪部分代码中提取的该功能点]
        </example_rules>
        """

    @prompt()
    def _analyze_modules(self, sources: SourceCodeList):
        """
        下面是用户提供的需要抽取规则的代码：
        <files>
        {% for source in sources.sources %}
        ##File: {{ source.module_name }}
        {{ source.source_code }}
        {% endfor %}
        </files>

        以上内容分为旧rules，以及待分析的代码内容，
        请对对上面待分析的代码进行深入分析，提取具有通用价值的功能模式和设计模式，转化为可在其他项目中复用的代码规则（rules），
        然后与旧rules进行更新合并，相同模块以最新的为主。

        - 识别代码变更中具有普遍应用价值的功能点和模式
        - 将这些功能点提炼为结构化规则，便于在其他项目中快速复用
        - 生成清晰的使用示例，包含完整依赖和调用方式

        最后，新生成的文件格式要是这种形态的：

        <example_rules>
        ---
        description: [简明描述规则的功能，20字以内]
        globs: [匹配应用此规则的文件路径，如"src/services/*.py"]
        alwaysApply: [是否总是应用，通常为false]
        ---

        # [规则主标题]

        ## 简要说明
        [该规则的功能、适用场景和价值，100字以内]

        ## 典型用法
        ```python
        # 完整的代码示例，包含:
        # 1. 必要的import语句
        # 2. 类/函数定义
        # 3. 参数说明
        # 4. 调用方式
        # 5. 关键注释
        ```

        ## 依赖说明
        - [必要的依赖库及版本]
        - [环境要求]
        - [初始化流程(如有)]

        ## 学习来源
        [从哪个提交变更的哪部分代码中提取的该功能点]
        </example_rules>
        """

    def analyze_commit_changes(
        self, commit_id: str, conversations=None
    ) -> str:
        """ 分析指定commit的代码变更 """
        if conversations is None:
            conversations = []

        changes, _ = get_commit_changes(self.args.source_dir, commit_id)

        if not changes:
            printer.print_text("未发现代码变更(Commit)", style="yellow")
            return ""

        try:
            # 获取prompt内容
            prompt_content = self._analyze_commit_changes.prompt(
                querie_with_urls_and_changes=changes
            )

            # 准备对话历史
            if conversations:
                new_conversations = conversations[:-1]
            else:
                new_conversations = []
            new_conversations.append({"role": "user", "content": prompt_content})

            self.llm.setup_default_model_name(self.args.chat_model)
            v = self.llm.chat_ai(new_conversations, self.args.chat_model)
            return v.output
        except Exception as e:
            printer.print_text(f"代码变更分析失败: {e}", style="red")
            return ""

    def analyze_modules(
        self, sources: SourceCodeList, conversations=None
    ) -> str:
        """ 分析给定的模块文件，根据用户需求生成可复用功能点的总结。 """

        if conversations is None:
            conversations = []

        if not sources or not sources.sources:
            printer.print_text("没有提供有效的模块文件进行分析.", style="red")
            return ""

        try:
            # 准备 Prompt
            prompt_content = self._analyze_modules.prompt(
                sources=sources
            )

            # 准备对话历史
            # 如果提供了 conversations，我们假设最后一个是用户的原始查询，替换它
            if conversations:
                new_conversations = conversations[:-1]
            else:
                new_conversations = []
            new_conversations.append({"role": "user", "content": prompt_content})

            self.llm.setup_default_model_name(self.args.chat_model)
            v = self.llm.chat_ai(new_conversations, self.args.chat_model)
            return v.output
        except Exception as e:
            printer.print_text(f"代码模块分析失败: {e}", style="red")
            return ""

    def _get_index_file_content(self) -> str:
        """获取索引文件内容"""
        index_file_path = os.path.join(os.path.abspath(self.args.source_dir), ".autocoderrules", "index.md")
        index_file_content = ""

        try:
            if os.path.exists(index_file_path):
                with open(index_file_path, 'r', encoding='utf-8') as f:
                    index_file_content = f.read()
        except Exception as e:
            printer.print_text(f"读取索引文件时出错: {str(e)}", style="yellow")

        return index_file_content