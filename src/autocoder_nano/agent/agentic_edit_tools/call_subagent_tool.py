import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import CallSubAgentTool, ToolResult, AgenticEditRequest
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime


printer = Printer()


class CallSubAgentToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']], tool: CallSubAgentTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: CallSubAgentTool = tool

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
        ## call_subagent (调用SubAgent)
        描述：
        - 调用子代理执行特定任务
        参数：
        - agent_type: 子代理类型
        - task: 具体任务描述
        - context: 传递给子代理的上下文信息
        用法说明：
        <call_subagent>
        <agent_type>SubAgent类型</agent_type>
        <task>具体任务描述</task>
        <context>传递给子代理的上下文信息(传递代码的相关信息,调研/研究的相关信息)</context>
        </call_subagent>
        """
        return doc
