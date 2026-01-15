import json
import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import CallSkillsTool, ToolResult, AgenticEditRequest
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime


printer = Printer()


class CallSkillsToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']], tool: CallSkillsTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: CallSkillsTool = tool

    def resolve(self) -> ToolResult:
        try:
            from autocoder_nano.agent.agentic_skills import SkillRegistry, SkillLoader, SkillExecutor
            skill_name = self.tool.skill_name
            request = self.tool.request

            _registry = SkillRegistry(args=self.agent.args)
            _registry.scan_skills()
            _loader = SkillLoader()
            _executor = SkillExecutor(_registry, _loader, self.agent.llm)

            results = _executor.execute_skill(
                skill_name=skill_name, request=request
            )

            return ToolResult(
                success=True, message=f"技能 '{skill_name}' 执行成功",
                content=f"{json.dumps(results, indent=2)}"
            )
        except Exception as e:
            return ToolResult(success=False, message=f"CallSkills 执行失败: {str(e)}",
                              content=f"错误信息: {str(e)}")

    def guide(self) -> str:
        doc = f"""
        ## call_skill (调用Skills技能)
        描述: 
        - 调用特定的技能来完成任务。技能封装了专业知识和工作流程。
        参数:
        - skill_name (必需): 要调用的技能名称。
        - request (必需): 用户的请求描述，详细说明要完成的任务。
        用法说明：
        自动匹配技能
        <call_skill>
        <skill_name>wttr</skill_name>
        <request>帮我查询武汉，上海，长沙的天气情况</request>
        </call_skill>
        """
        return doc