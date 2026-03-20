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
    def __init__(self, agent: Optional[Union['AgenticRuntime', 'SkillAgent']], tool: CallSkillsTool,
                 args: AutoCoderArgs):
        super().__init__(agent, tool, args)
        self.tool: CallSkillsTool = tool

    def resolve(self) -> ToolResult:
        try:
            from autocoder_nano.agent.agentic_skills import SkillRegistry, SkillLoader, SkillAgent, SkillLevel
            skill_name = self.tool.skill_name
            request = self.tool.request

            _registry = SkillRegistry(args=self.agent.args)
            _registry.scan_skills()
            _skill_path = _registry.get_skill_path(skill_name)
            _loader = SkillLoader()
            _level = SkillLevel.RESOURCES
            _skill_content = _loader.load_skill(_skill_path, _level)

            # 初始化及添加技能概述
            skill_prompt = [
                f"# Skill: {_skill_content.metadata.name}",
                f"**Description**: {_skill_content.metadata.description}\n"
            ]
            # 添加技能主体
            if _skill_content.body:
                skill_prompt.append(_skill_content.body)
                skill_prompt.append("")
            # 添加 script 列表
            if _skill_content.scripts:
                skill_prompt.append("## Script")
                for script_name, script_content in _skill_content.scripts.items():
                    skill_prompt.append(f"- {script_name}")
            # 添加参考文档（如果有）
            if _skill_content.references:
                skill_prompt.append("## References")
                for ref_name, ref_content in _skill_content.references.items():
                    skill_prompt.append(f"\n### {ref_name}")
                    skill_prompt.append(ref_content)
                skill_prompt.append("")

            skills_agent_define = {
                "skills": {
                    "type": "sub",
                    "description": "",
                    "call": "",
                    "prompt": skill_prompt,
                    "tools": [
                        "search_files",
                        "list_files",
                        "read_file",
                        "execute_command",
                        "write_to_file",
                        "attempt_completion",
                    ]
                }
            }

            skill_agent = SkillAgent(
                self.agent.args,
                self.agent.llm,
                skills_agent_define)
            completion_status, completion_text = skill_agent.run_skills_agent(request)

            if completion_status:
                if completion_text:
                    return ToolResult(success=True,
                                      message=f"技能 '{skill_name}' 执行成功",
                                      content=completion_text)
                else:
                    return ToolResult(success=False,
                                      message=f"技能 '{skill_name}' 执行成功, 但未返回任何内容",
                                      content=None)
            else:
                return ToolResult(success=False,
                                  message=f"技能 '{skill_name}' 执行失败",
                                  content=completion_text)
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