import typing
from typing import Optional, Union

from autocoder_nano.agent.agentic_edit_tools.base_tool_resolver import BaseToolResolver
from autocoder_nano.agent.agentic_edit_types import ExecuteCommandTool, ToolResult
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer
from autocoder_nano.utils.shell_utils import run_cmd_subprocess

if typing.TYPE_CHECKING:
    from autocoder_nano.agent.agentic_runtime import AgenticRuntime
    from autocoder_nano.agent.agentic_sub import SubAgents


printer = Printer()


class ExecuteCommandToolResolver(BaseToolResolver):
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SubAgents']], tool: ExecuteCommandTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: ExecuteCommandTool = tool  # For type hinting

    @staticmethod
    def _prune_file_content(content: str, file_path: str) -> str:
        """
        该函数主要目的是对命令行执行后的结果内容进行剪枝处理
        因为执行的命令可能包含
        - 读取大量文件
        等操作
        todo: 该函数目前暂时未实现，直接返回全部结果
        """
        return content

    def resolve(self) -> ToolResult:
        command = self.tool.command
        requires_approval = self.tool.requires_approval
        source_dir = self.args.source_dir or "."

        try:
            exit_code, output = run_cmd_subprocess(command, verbose=False, cwd=source_dir)

            printer.print_key_value(
                items={"执行命令": f"{command}", "返回 Code": f"{exit_code}", "输出大小": f"{len(output)} chars"},
                title="使用 run_cmd_subprocess 执行命令工具"
            )

            final_output = self._prune_file_content(output, "command_output")

            if exit_code == 0:
                return ToolResult(success=True, message="Command executed successfully.", content=final_output)
            else:
                # For the human-readable error message, we might prefer the original full output.
                # For the agent-consumable content, we provide the (potentially pruned) final_output.
                error_message_for_human = f"Command failed with return code {exit_code}.\nOutput:\n{output}"
                return ToolResult(success=False, message=error_message_for_human,
                                  content={"output": final_output, "returncode": exit_code})

        except FileNotFoundError:
            return ToolResult(success=False,
                              message=f"Error: The command '{command.split()[0]}' was not found. Please ensure it is "
                                      f"installed and in the system's PATH.")
        except PermissionError:
            return ToolResult(success=False, message=f"Error: Permission denied when trying to execute '{command}'.")
        except Exception as e:
            return ToolResult(success=False,
                              message=f"An unexpected error occurred while executing the command: {str(e)}")
