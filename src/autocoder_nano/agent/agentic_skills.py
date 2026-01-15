import glob
import json
import os
import pprint
import subprocess
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Any

import yaml
from pydantic import BaseModel, Field

from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.context.cache import MemoryCache
from autocoder_nano.core import AutoLLM, prompt


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


class SkillMatch(BaseModel):
    """技能匹配结果"""
    skill_name: str
    similarity: float = Field(ge=0.0, le=1.0)
    metadata: SkillMetadata


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
                rel_path = os.path.relpath(file_path, dir_path)

                with open(file_path, 'r', encoding='utf-8') as f:
                    result[rel_path] = f.read()

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


if __name__ == '__main__':
    _args = AutoCoderArgs(source_dir="/Users/moofs/Code/autocoder-nano")
    _args.chat_model = "minimax-m2.1"
    _llm = AutoLLM()
    _llm.setup_sub_client(
        client_name="minimax-m2.1",
        api_key="sk-cp-b-q0ilQQeIi0Q2CR22NQN9PlRhsLYtLFn4DyJ7KM4gc1Z6uEsx0XvwnQ5kijWjxIjo8wb3nYz2wvflxeILPE8J8RdKd8tXg-uBlSax_N3OOYfwhJA0fnWzg",
        base_url="https://api.minimaxi.com/v1",
        model_name="MiniMax-M2.1"
    )
    _llm.setup_default_model_name("minimax-m2.1")
    _registry = SkillRegistry(args=_args)
    _registry.scan_skills()
    _loader = SkillLoader()
    _executor = SkillExecutor(_registry, _loader, _llm)
    print(_executor.execute_skill(
        skill_name="wttr", request="我想查询上海,深圳,北京的简化天气"
    ))