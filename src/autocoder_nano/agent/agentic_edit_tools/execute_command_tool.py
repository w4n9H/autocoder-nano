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
        source_dir = self.agent.args.source_dir or "."

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

    def guide(self) -> str:
        doc = """
        ## execute_command（执行命令）
        描述：
        - 用于在系统上执行 CLI 命令，根据用户操作系统调整命令，并解释命令作用，
        - 对于命令链，使用适合用户操作系统及shell类型的链式语法，相较于创建可执行脚本，优先执行复杂的 CLI 命令，因为它们更灵活且易于运行。
        - 命令将在当前工作目录中执行。
        参数：
        - command（必填）：要执行的 CLI 命令。该命令应适用于当前操作系统，且需正确格式化，不得包含任何有害指令。
        - requires_approval（必填）：
            * 布尔值，此命令表示在用户启用自动批准模式的情况下是否还需要明确的用户批准。
            * 对于可能产生影响的操作，如安装/卸载软件包，删除/覆盖文件，系统配置更改，网络操作或任何可能产生影响的命令，设置为 'true'。
            * 对于安全操作，如读取文件/目录、运行开发服务器、构建项目和其他非破坏性操作，设置为 'false'。
        用法说明：
        <execute_command>
        <command>需要运行的命令</command>
        <requires_approval>true 或 false</requires_approval>
        </execute_command>
        用法示例：
        场景一：安全操作（无需批准）
        目标：查看当前项目目录下的文件列表。
        思维过程：这是一个非破坏性操作，requires_approval设置为false。我们需要使用 ls -al 命令，它能提供详细的文件信息。
        <execute_command>
        <command>ls -al</command>
        <requires_approval>false</requires_approval>
        </execute_command>
        场景二：复杂命令链（无需批准）
        目标：查看当前项目目录下包含特定关键词的文件列表
        思维过程：
            - 只读操作，不会修改任何文件，requires_approval设置为false。
            - 为了在项目文件中递归查找关键词，我们可以使用 grep -Rn 命令。
            - 同时为了避免搜索无关的目录（如 .git 或 .auto-coder），需要使用--exclude-dir参数进行排除。
            - 最后通过管道将结果传递给head -10，只显示前10个结果，以确保输出简洁可读
        <execute_command>
        <command>grep -Rn --exclude-dir={.auto-coder,.git} "*FunctionName" . | head -10</command>
        <requires_approval>false</requires_approval>
        </execute_command>
        场景三：可能产生影响的操作（需要批准）
        目标：在项目中安装一个新的npm包axios。
        思维过程：这是一个安装软件包的操作，会修改node_modules目录和package.json文件。为了安全起见，requires_approval必须设置为true。
        <execute_command>
        <command>npm install axios</command>
        <requires_approval>true</requires_approval>
        </execute_command>
        """
        return doc
