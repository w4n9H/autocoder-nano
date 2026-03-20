import glob
import os
import time
import xml.sax.saxutils
import subprocess
from enum import Enum
from pathlib import Path
from typing import Generator, Union
from datetime import datetime
from copy import deepcopy

import yaml
from rich.text import Text

from autocoder_nano.agent.agentic_edit_types import *
from autocoder_nano.agent.agent_base import BaseAgent, ToolResolverFactory, PromptManager
from autocoder_nano.actypes import AutoCoderArgs, SingleOutputMeta
from autocoder_nano.context import ConversationsPruner
from autocoder_nano.context.cache import MemoryCache
from autocoder_nano.core import AutoLLM, prompt, stream_chat_with_continue
from autocoder_nano.utils.printer_utils import (
    Printer, COLOR_SYSTEM, COLOR_INFO, COLOR_SUCCESS, COLOR_ERROR)


printer = Printer()


class SkillLevel(str, Enum):
    """技能加载级别"""
    METADATA = "metadata"  # Level 1: 元数据 (~100 words)
    BODY = "body"  # Level 2: SKILL.md 主体 (~500 lines)
    RESOURCES = "resources"  # Level 3: 资源文件 (按需)


class SkillPermission(str, Enum):
    """技能权限级别"""
    READ_ONLY = "read_only"
    WRITE_LIMITED = "write_limited"
    WRITE_ANY = "write_any"
    NETWORK_ACCESS = "network_access"


class SkillMetadata(BaseModel):
    """技能元数据 (Level 1)"""
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., description="技能描述，必须说明 WHEN 和 WHAT")
    version: str = "1.0.0"
    authors: List[str] = []
    tags: List[str] = []
    allowed_tools: List[str] = []
    context_budget: int = 8000
    permissions: List[SkillPermission] = [SkillPermission.READ_ONLY]
    triggers: Dict[str, List[str]] = {}
    dependencies: Dict[str, str] = {}


class SkillContent(BaseModel):
    """技能内容 (Level 2+)"""
    metadata: SkillMetadata
    body: str = ""  # SKILL.md 的 Markdown 主体
    scripts: Dict[str, str] = {}  # scripts/ 目录内容
    references: Dict[str, str] = {}  # references/ 目录内容
    assets: Dict[str, str] = {}  # assets/ 目录内容


class SkillCommands(BaseModel):
    commands: List[str] = Field([], description="命令行工具/脚本工具 的组合使用")
    reason: str


class SkillRegistry:
    def __init__(self, args: AutoCoderArgs, skill_paths: List[str] = None):
        self.args = args
        self.skill_paths = skill_paths or self._default_skill_paths()
        self._metadata_index: Dict[str, SkillMetadata] = {}  # skill_name -> metadata
        self._path_to_skills: Dict[str, str] = {}  # skill_path -> skill_name

    def _default_skill_paths(self) -> List[str]:
        """ 默认技能搜索路径 """
        paths = [
            os.path.expanduser("~/.auto-coder/skills"),  # 用户级
            Path(self.args.source_dir) / ".auto-coder" / "skills",  # 项目级
        ]
        return [p for p in paths if os.path.exists(p)]

    def scan_skills(self) -> int:
        """ 扫描所有技能目录并建立索引 """
        count = 0
        for skill_path in self.skill_paths:
            count += self._scan_directory(skill_path)
        return count

    def _scan_directory(self, path: str) -> int:
        """扫描单个目录"""
        count = 0
        for skill_dir in glob.glob(os.path.join(path, "*/SKILL.md")):
            skill_path = os.path.dirname(skill_dir)
            skill_name = os.path.basename(skill_path)

            try:
                metadata = self._load_metadata(skill_path)
                self._metadata_index[skill_name] = metadata
                self._path_to_skills[skill_path] = skill_name
                count += 1
            except Exception as e:
                print(f"Failed to load skill {skill_path}: {e}")

        return count

    @staticmethod
    def _load_metadata(skill_path: str) -> SkillMetadata:
        """加载技能元数据（Level 1）"""
        skill_md_path = os.path.join(skill_path, "SKILL.md")

        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 解析 YAML Frontmatter
        yaml_end = content.find('---', 3)
        if yaml_end == -1:
            raise ValueError("Invalid SKILL.md: missing YAML frontmatter")

        yaml_content = content[3:yaml_end].strip()
        metadata_dict = yaml.safe_load(yaml_content)

        return SkillMetadata(**metadata_dict)

    def get_skill_path(self, skill_name: str) -> Optional[str]:
        """获取技能的路径"""
        for path, name in self._path_to_skills.items():
            if name == skill_name:
                return path
        return None

    def get_metadata_index(self):
        return self._metadata_index

    def list_all_skills(self) -> Dict[str, SkillMetadata]:
        """列出所有已注册的技能"""
        return self._metadata_index.copy()

    def get_skills_summary(self):
        _skill_content_list = ["## Skills List"]
        for _skill_name, _skill_metadata in self._metadata_index.items():
            _skill_content_list.append(f"{_skill_name}: {_skill_metadata.description}")
        return "\n".join(_skill_content_list)


class SkillLoader:
    """ 技能加载器 - 按需加载不同层级的内容 """

    def __init__(self, max_cache_size: int = 100):
        self.cache = MemoryCache(max_size=max_cache_size)

    def load_skill(self, skill_path: str, level: SkillLevel = SkillLevel.METADATA) -> SkillContent:
        """
        按层级加载技能内容

        参数：
            skill_path: 技能目录路径
            level: 加载级别
            context_budget: 可用的 token 预算

        返回：技能内容对象
        """
        cache_key = f"{skill_path}:{level.value}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # 加载基础元数据
        skill_md_path = os.path.join(skill_path, "SKILL.md")
        with open(skill_md_path, 'r', encoding='utf-8') as f:
            content = f.read()

        yaml_end = content.find('---', 3)
        yaml_content = content[3:yaml_end].strip()
        body = content[yaml_end + 3:].strip()

        metadata_dict = yaml.safe_load(yaml_content)
        metadata = SkillMetadata(**metadata_dict)

        skill_content = SkillContent(
            metadata=metadata,
            body=body
        )

        # 根据级别加载额外内容
        if level == SkillLevel.BODY:
            # Body metadata 已经在上一步加载
            pass

        if level == SkillLevel.RESOURCES:
            # 加载资源目录
            skill_content.scripts = self._load_directory(skill_path, "scripts")

        # 缓存结果
        self.cache.set(cache_key, skill_content)
        return skill_content

    @staticmethod
    def _load_directory(skill_path: str, dirname: str) -> Dict[str, str]:
        """加载目录中的所有文件"""
        result = {}
        dir_path = os.path.join(skill_path, dirname)

        if not os.path.exists(dir_path):
            return result

        for root, _, files in os.walk(dir_path):
            for filename in files:
                file_path = os.path.join(root, filename)
                # rel_path = os.path.relpath(file_path, dir_path)
                with open(file_path, 'r', encoding='utf-8') as f:
                    result[file_path] = f.read()

        return result

    def preload_skill(self, skill_path: str) -> SkillContent:
        """预加载技能到缓存"""
        return self.load_skill(skill_path, SkillLevel.BODY)

    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()


class SkillExecutor:
    """
    Skill 执行器
    - 构建包含 Skill 上下文的提示
    - 执行 Skill 并返回结果
    - 管理 Skill 的生命周期（初始化、执行、清理）
    """

    def __init__(self, registry: SkillRegistry, loader: SkillLoader, llm: AutoLLM):
        self.registry = registry
        self.loader = loader
        self.llm = llm

    @staticmethod
    def _build_skill_prompt(skill_content: SkillContent) -> str:
        """ 构建包含技能上下文的提示 """
        # 初始化及添加技能概述
        parts = [
            f"# Skill: {skill_content.metadata.name}",
            f"**Description**: {skill_content.metadata.description}\n"]

        # 添加技能主体
        if skill_content.body:
            parts.append(skill_content.body)
            parts.append("")

        # 添加 script 列表
        if skill_content.scripts:
            parts.append("## Script")
            for script_name, script_content in skill_content.scripts.items():
                parts.append(f"- {script_name}")

        # 添加参考文档（如果有）
        if skill_content.references:
            parts.append("## References")
            for ref_name, ref_content in skill_content.references.items():
                parts.append(f"\n### {ref_name}")
                parts.append(ref_content)
            parts.append("")

        return "\n".join(parts)

    @prompt()
    def _build_skill_commands(self, skills_content: str, query: str):
        """
        请使用下面的 Agent Skills 解决用户问题:

        Agent Skills 详细内容:
        {{ skills_content }}

        用户问题:
        {{ query }}

        ----------

        你需要使用这个 Agent Skills 提供的说明，编写命令行(command)或者使用已经存在的脚本(script)，解决用户的问题。
        并且给出使用该命令行(command)/脚本(script)的原因，并结合用户问题，理由控制在20字以内，并且使用中文。
        如果需要使用多个命令/脚本组合完成，则使用列表组合多条命令/脚本。

        请严格按格式要求返回结果，格式如下:

        ```json
        {
            "commands":
                [
                    "ls -al src/",
                    "ls -al src/",
                    "ls -al src/"
                ],
            "reason": "这是使用该command的原因..."
        }
        ```
        """

    def _skills_commands(self, _skills_content: str, _query: str):
        _result: SkillCommands = self._build_skill_commands.with_llm(self.llm).with_return_type(
            SkillCommands).run(_skills_content, _query)
        return _result

    def execute_skill(self, skill_name: str, request: str) -> Dict[str, Any]:
        """
        执行 Skill
        - skill_name: 技能名称
        - request: 用户请求
        - context: 上下文信息

        return：{}
        """
        # 获取技能路径
        skill_path = self.registry.get_skill_path(skill_name)
        if not skill_path:
            raise ValueError(f"Skill not found: {skill_name}")

        # 加载技能内容（渐进式）
        metadata = self.registry.get_metadata_index().get(skill_name)
        if not metadata:
            raise ValueError(f"Skill metadata not found: {skill_name}")

        # 加载级别(默认加载全部资源)
        level = SkillLevel.RESOURCES
        skill_content = self.loader.load_skill(skill_path, level)

        # 给模型的上下文
        llm_skill_content = self._build_skill_prompt(skill_content)
        skill_commands = self._skills_commands(llm_skill_content, request)

        # 执行技能逻辑
        result = {
            "skill_name": skill_name,
            "metadata": metadata.model_dump(),
            "execution": []
        }

        # 按顺序执行命令行/脚本
        if skill_commands.commands:
            script_result = self._execute_scripts(skill_commands.commands, skill_path)
            result["execution"] = script_result
        # print(f"技能 '{skill_name}' 执行成功。\n\n{json.dumps(result['execution'], indent=2)}")

        return result

    @staticmethod
    def _execute_scripts(commands: List[str], skill_path: str) -> List[Dict[str, Any]]:
        """执行技能脚本"""
        results = []
        scripts_dir = os.path.join(skill_path, "scripts")

        for _commands in commands:
            _commands_list = _commands.split(" ")
            # 根据扩展名选择执行方式
            if '.py' in _commands:
                result = subprocess.run(
                    ["python"] + _commands_list,
                    capture_output=True,
                    text=True,
                    cwd=scripts_dir
                )
            elif '.sh' in _commands:
                result = subprocess.run(
                    ["bash"] + _commands_list,
                    capture_output=True,
                    text=True,
                    cwd=scripts_dir
                )
            else:
                # 命令行工具
                result = subprocess.run(
                    _commands_list,
                    capture_output=True,
                    text=True
                )

            results.append({
                "name": _commands,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            })

        return results


class SkillAgent(BaseAgent):
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM, agent_define: dict):
        super().__init__(args, llm)
        self.agent_define = agent_define
        self.agent_type = "skills"
        self.current_conversations = []

        # Agentic 对话修剪器
        self.agentic_pruner = ConversationsPruner(args=args, llm=self.llm)

        # Tools 管理
        self.tool_resolver_factory = ToolResolverFactory(self.agent_define)
        self.tool_resolver_factory.register_dynamic_resolver(self.agent_type)

        # prompt 管理
        self.prompt_manager = PromptManager(args=self.args, agent_define=self.agent_define)

        # skills agent printer prefix
        self.sapp = f"* (sub:{self.agent_type}) "

    def _reinforce_guidelines(self, interval=5):
        """ 每N轮对话强化指导原则 """
        if len(self.current_conversations) % interval == 0:
            printer.print_text(f"强化工具使用规则(间隔{interval})", style=COLOR_SYSTEM, prefix=self.sapp)
            self.current_conversations.append(
                {"role": "user", "content": self._get_tools_prompt()}
            )

    def _get_tools_prompt(self) -> str:
        if self.tool_resolver_factory.get_registered_size() <= 0:
            raise Exception(f"未注册任何工具")
        guides = ""
        resolvers = self.tool_resolver_factory.get_resolvers()
        for t, resolver_cls in resolvers.items():
            resolver = resolver_cls(agent=self, tool=t, args=self.args)
            tool_guide: str = resolver.guide()
            guides += f"{tool_guide}\n\n"
        return f"""
        # 工具使用说明

        1. 你可使用一系列工具，部分工具需经用户批准才能执行。
        2. 每条消息中仅能使用一个工具，用户回复中会包含该工具的执行结果。
        3. 你要借助工具逐步完成给定任务，每个工具的使用都需依据前一个工具的使用结果。
        4. 使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败

        ## 工具使用格式

        工具使用采用 XML 风格标签进行格式化。工具名称包含在开始和结束标签内，每个参数同样包含在各自的标签中。其结构如下：

        <tool_name>
        <parameter1_name>value1</parameter1_name>
        <parameter2_name>value2</parameter2_name>
        ...
        </tool_name>

        例如：

        <read_file>
        <path>src/main.js</path>
        </read_file>

        一定要严格遵循此工具使用格式，以确保正确解析和执行。

        ## 工具列表

        {guides}

        ## 错误处理

        - 如果工具调用失败，你需要分析错误信息，并重新尝试，或者向用户报告错误并请求帮助

        ## 工具熔断机制

        - 工具连续失败3次时启动备选方案或直接结束任务
        - 自动标注行业惯例方案供用户确认

        ## 工具调用规范

        - 调用前必须在 <think></think> 内分析：
            * 分析系统环境及目录结构
            * 根据目标选择合适工具
            * 必填参数检查（用户提供或可推断，否则用 `ask_followup_question` 询问）
        - 当所有必填参数齐备或可明确推断后，才关闭思考标签并调用工具

        ## 工具使用指南

        1. 开始任务前务必进行全面搜索和探索
        2. 在 <think> 标签中评估已有和继续完成任务所需信息
        3. 根据任务选择合适工具，思考是否需其他信息来推进，以及用哪个工具收集
        4. 逐步执行，禁止预判：
            * 单次仅使用一个工具
            * 后续操作必须基于前次结果
            * 严禁假设任何工具的执行结果
        5. 按工具指定的 XML 格式使用
        6. 重视用户反馈，某些时候，工具使用后，用户会回复为你提供继续任务或做出进一步决策所需的信息，可能包括：
            * 工具是否成功的信息
            * 触发的 Linter 错误（需修复）
            * 相关终端输出
            * 其他关键信息
        """

    def _get_system_prompt(self) -> str:
        return self.prompt_manager.system_prompt(self.agent_type)

    def _get_sysinfo_prompt(self) -> str:
        return self.prompt_manager.sysinfo_prompt.prompt()

    def _build_system_prompt(self) -> List[Dict[str, Any]]:
        """ 构建初始对话消息 """
        _system_prompt = (
            f""
            f"{self._get_system_prompt()}\n"
            f"----------\n"
            f"{self._get_tools_prompt()}\n"
            f"----------\n"
            f"{self._get_sysinfo_prompt()}")
        system_prompt = [
            {"role": "system", "content": _system_prompt}
        ]

        printer.print_text(f"系统提示词长度(token): {self._count_conversations_tokens(system_prompt)}",
                           style=COLOR_INFO, prefix=self.sapp)

        return system_prompt

    def analyze(self, request: str) -> Generator[Union[Any] | None, None, None]:
        self.current_conversations.extend(self._build_system_prompt())
        self.current_conversations.append({
            "role": "user",
            "content": f"{request} \n Current Time:{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        })

        iteration_count = 0
        should_yield_completion_event = False
        completion_event = None

        while True:
            self._reinforce_guidelines(interval=10)
            iteration_count += 1
            tool_executed = False
            last_message = self.current_conversations[-1]
            printer.print_text(f"当前为第{iteration_count}轮对话", style=COLOR_INFO, prefix=self.sapp)

            if last_message["role"] == "assistant":
                if should_yield_completion_event:
                    if completion_event is None:
                        yield CompletionEvent(completion=AttemptCompletionTool(
                            result=last_message["content"],
                            command=""
                        ), completion_xml="")
                    else:
                        yield completion_event
                break

            assistant_buffer = ""

            llm_response_gen = stream_chat_with_continue(
                llm=self.llm,
                conversations=self.agentic_pruner.prune_conversations(deepcopy(self.current_conversations)),
                llm_config={},  # Placeholder for future LLM configs
                args=self.args
            )

            parsed_events = self.stream_and_parse_llm_response(llm_response_gen)

            mark_event_should_finish = False
            for event in parsed_events:
                if mark_event_should_finish:
                    if isinstance(event, TokenUsageEvent):
                        yield event
                    continue

                if isinstance(event, (LLMOutputEvent, LLMThinkingEvent)):
                    assistant_buffer += event.text
                    yield event

                elif isinstance(event, ToolCallEvent):
                    tool_executed = True
                    tool_obj = event.tool
                    tool_xml = event.tool_xml

                    # 记录当前对话的token数量
                    self.current_conversations.append({
                        "role": "assistant",
                        "content": assistant_buffer + tool_xml
                    })
                    assistant_buffer = ""  # Reset buffer after tool call

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))
                    yield event  # Yield the ToolCallEvent for display

                    if isinstance(tool_obj, AttemptCompletionTool):
                        printer.print_text(f"正在准备结束会话 ...", style=COLOR_INFO, prefix=self.sapp)
                        completion_event = CompletionEvent(completion=tool_obj, completion_xml=tool_xml)
                        mark_event_should_finish = True
                        should_yield_completion_event = True
                        continue

                    resolver_cls = self.tool_resolver_factory.get_resolver(type(tool_obj))
                    if not resolver_cls:
                        tool_result = ToolResult(success=False, message="错误：工具解析器未实现.", content=None)
                        result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)
                        error_xml = (f"<tool_result tool_name='{type(tool_obj).__name__}' success='false'>"
                                     f"<message>Error: Tool resolver not implemented.</message>"
                                     f"<content></content></tool_result>")
                    else:
                        try:
                            resolver = resolver_cls(agent=self, tool=tool_obj, args=self.args)
                            tool_result: ToolResult = resolver.resolve()
                            result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)

                            # Prepare XML for conversation history
                            escaped_message = xml.sax.saxutils.escape(tool_result.message)
                            content_str = str(tool_result.content) if tool_result.content is not None else ""
                            escaped_content = xml.sax.saxutils.escape(content_str)
                            error_xml = (
                                f"<tool_result tool_name='{type(tool_obj).__name__}' "
                                f"success='{str(tool_result.success).lower()}'>"
                                f"<message>{escaped_message}</message>"
                                f"<content>{escaped_content}</content>"
                                f"</tool_result>"
                            )
                        except Exception as e:
                            error_message = f"Critical Error during tool execution: {e}"
                            tool_result = ToolResult(success=False, message=error_message, content=None)
                            result_event = ToolResultEvent(tool_name=type(tool_obj).__name__, result=tool_result)
                            escaped_error = xml.sax.saxutils.escape(error_message)
                            error_xml = (f"<tool_result tool_name='{type(tool_obj).__name__}' success='false'>"
                                         f"<message>{escaped_error}</message>"
                                         f"<content></content></tool_result>")

                    yield result_event  # Yield the ToolResultEvent for display
                    # 添加工具结果到对话历史
                    self.current_conversations.append({
                        "role": "user",
                        "content": error_xml
                    })

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))

                    # 一次交互只能有一次工具，剩下的其实就没有用了，但是如果不让流式处理完，我们就无法获取服务端
                    # 返回的token消耗和计费，所以通过此标记来完成进入空转，直到流式走完，获取到最后的token消耗和计费
                    mark_event_should_finish = True

                elif isinstance(event, ErrorEvent):
                    if event.message.startswith("Stream ended with unterminated"):
                        printer.print_text(f"LLM Response 流以未闭合的标签块结束, 即将强化记忆",
                                           style=COLOR_ERROR, prefix=self.sapp)
                        self.current_conversations.append(
                            {"role": "user",
                             "content": "使用工具时需要包含 开始和结束标签, 缺失结束标签会导致工具调用失败"}
                        )
                    yield event
                elif isinstance(event, TokenUsageEvent):
                    yield event

            if not tool_executed:
                # printer.print_text("LLM 响应完成, 未执行任何工具, 将 Assistant Buffer 内容写入会话历史",
                #                    style=COLOR_WARNING, prefix=self.spp)
                if assistant_buffer:
                    last_message = self.current_conversations[-1]
                    if last_message["role"] != "assistant":
                        self.current_conversations.append({"role": "assistant", "content": assistant_buffer})
                    elif last_message["role"] == "assistant":
                        last_message["content"] += assistant_buffer

                    yield WindowLengthChangeEvent(
                        tokens_used=self._count_conversations_tokens(self.current_conversations))

                # 添加系统提示，要求LLM必须使用工具或明确结束，而不是直接退出
                # printer.print_text("正在添加系统提示: 请使用工具或尝试直接生成结果", style=COLOR_INFO, prefix=self.spp)

                self.current_conversations.append({
                    "role": "user",
                    "content": "注意：您必须使用适当的工具或使用 attempt_completion 明确完成任务,"
                               "不要在不采取具体行动的情况下提供文本回复。请根据用户的任务选择合适的工具继续操作."
                })
                yield WindowLengthChangeEvent(tokens_used=self._count_conversations_tokens(self.current_conversations))
                # 继续循环，让 LLM 再思考，而不是 break
                # printer.print_text("🔄 SubAgent 持续运行 LLM 交互循环（保持不中断）", style=COLOR_ITERATION)
                continue

        printer.print_text(f"分析循环已完成，共执行 {iteration_count} 次迭代.", style=COLOR_SUCCESS, prefix=self.sapp)

    def run_skills_agent(self, skill_name: str, request: str):
        project_name = os.path.basename(os.path.abspath(self.args.source_dir))
        printer.print_text(f"开始执行技能: {skill_name}, 用户目标: {request[:50]}...",
                           style=COLOR_SYSTEM, prefix=self.sapp)
        completion_text = ""
        completion_status = False
        try:
            # self._apply_pre_changes()  # 在开始 Agentic 之前先判断是否有未提交变更,有变更则直接退出
            event_stream = self.analyze(request)
            for event in event_stream:
                if isinstance(event, TokenUsageEvent):
                    last_meta: SingleOutputMeta = event.usage
                    printer.print_text(
                        Text.assemble(
                            ("本次调用模型 Token 使用: ", COLOR_SYSTEM),
                            (f"Input({last_meta.input_tokens_count})", COLOR_INFO),
                            (f"/", COLOR_SYSTEM),
                            (f"Output({last_meta.generated_tokens_count})", COLOR_INFO)
                        ),
                        prefix=self.sapp
                    )
                elif isinstance(event, WindowLengthChangeEvent):
                    pass
                elif isinstance(event, LLMThinkingEvent):
                    # 以不太显眼的样式（比如灰色）呈现思考内容
                    printer.print_text(f"LLM Thinking: ", style=COLOR_SYSTEM, prefix=self.sapp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, LLMOutputEvent):
                    printer.print_text(f"LLM Output: ", style=COLOR_SYSTEM, prefix=self.sapp)
                    printer.print_llm_output(f"{event.text}")
                elif isinstance(event, ToolCallEvent):
                    printer.print_text(
                        Text.assemble(
                            (f"{type(event.tool).__name__}: ", COLOR_SYSTEM),
                            (f"{self.get_tool_display_message(event.tool)}", COLOR_INFO)
                        ),
                        prefix=self.sapp
                    )
                elif isinstance(event, ToolResultEvent):
                    result = event.result
                    printer.print_text(
                        Text.assemble(
                            (f"{event.tool_name} Result: ", COLOR_SYSTEM),
                            (f"{result.message}", COLOR_SUCCESS if result.success else COLOR_ERROR)
                        ),
                        prefix=self.sapp
                    )
                elif isinstance(event, CompletionEvent):
                    completion_text = event.completion.result
                    completion_status = True
                    if event.completion.command:
                        printer.print_text(f"建议命令: {event.completion.command}", style=COLOR_INFO, prefix=self.sapp)
                    printer.print_text(f"任务完成", style=COLOR_SUCCESS, prefix=self.sapp)
                    printer.print_llm_output(f"{completion_text}")
                elif isinstance(event, ErrorEvent):
                    printer.print_text(f"任务失败", style=COLOR_ERROR, prefix=self.sapp)
                    printer.print_llm_output(f"{event.message}")

                time.sleep(self.args.anti_quota_limit)

                # 如果已经获得完成结果，可以提前结束事件处理
                if completion_text:
                    break
        except Exception as err:
            printer.print_text(f"SkillAgent {skill_name} 执行失败", style=COLOR_ERROR, prefix=self.sapp)
            printer.print_llm_output(f"{err}")
            completion_text = f"SkillAgent {skill_name} 执行失败: {str(err)}"

        return completion_status, completion_text