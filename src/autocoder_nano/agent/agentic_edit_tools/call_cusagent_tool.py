import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import CallCusAgentTool, ToolResult, AgenticEditRequest
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime


printer = Printer()


class CallCusAgentToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']], tool: CallCusAgentTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: CallCusAgentTool = tool

    def resolve(self) -> ToolResult:
        try:
            from autocoder_nano.agent.agentic_sub import SubAgents
            subagent = SubAgents(
                args=self.agent.args,
                llm=self.agent.llm,  # 复用父代理的LLM
                agent_type=self.tool.agent_type,
                files=self.agent.files,  # 共享文件列表
                history_conversation=[],  # 子代理使用干净的历史
            )
            task_info = f"{self.tool.task} \n传递上下文: {self.tool.context}"
            request = AgenticEditRequest(user_input=task_info)
            completion_status, completion_text = subagent.run_subagent(request)
            if completion_status:
                if completion_text:
                    return ToolResult(success=True,
                                      message=f"SubAgent({self.tool.agent_type.title()}) 执行成功",
                                      content=completion_text)
                else:
                    return ToolResult(success=False,
                                      message=f"SubAgent({self.tool.agent_type.title()}) 未返回任何内容",
                                      content=None)
            else:
                return ToolResult(success=False,
                                  message=f"SubAgent({self.tool.agent_type.title()}) 执行失败",
                                  content=completion_text)

        except Exception as e:
            return ToolResult(success=False, message=f"SubAgent 执行失败: {str(e)}",
                              content=f"错误信息: {str(e)}")

    def guide(self) -> str:
        doc = """
        ## call_cusagent (调用定制Agent)
        描述：
        - 调用定制子代理执行任务
        参数：
        - task: 具体任务描述
        - prompt: 传递给定制子代理的系统提示词以及相关上下文信息
        - tools: 该定制子代理可以调用的工具列表
        用法说明：
        <call_cusagent>
        <task>具体任务描述</task>
        <prompt>传递给定制子代理的系统提示词(角色信息,工作流程,规则等信息)，上下文信息(传递代码的相关信息,调研/研究的相关信息)</context>
        <tools>Array of tools here , e.g. ["execute_command", "read_file", "list_files"]</tools>
        </call_cusagent>
        用法示例：
        """
        return doc