from typing import List

from pydantic import BaseModel
from loguru import logger

from autocoder_nano.llm_client import AutoLLM
from autocoder_nano.llm_prompt import prompt, extract_code
from autocoder_nano.llm_types import AutoCoderArgs
from autocoder_nano.sys_utils import detect_env


class IndexFilePath(BaseModel):
    file_path: str
    purpose: str
    symbols: str


class ProjectFileList(BaseModel):
    file_list: List[IndexFilePath]


class BuildNewProject:
    """
    步骤一：完善需求，用户可能提出的需求是一个较为简短的需求，需要完善需求
    步骤二：设计架构，
    步骤三：构建索引，
    步骤四：完成代码，
    """

    def __init__(self, args: AutoCoderArgs, llm: AutoLLM, chat_model: str, code_model: str):
        self.args = args
        self.llm = llm
        self.chat_model = chat_model
        self.code_model = code_model

    @prompt()
    def _build_project_information(self, query, env_info, language):
        """
        请根据以下简短需求，逐步进行完善工作：
        这是我的原始需求: {{ query }}

        环境信息如下:
        操作系统: {{ env_info.os_name }} {{ env_info.os_version }}
        编程语言: {{ language }}

        需要你自动执行以下步骤：
        1. 需求补全 - 对简短需求进行描述扩充，诸如程序描述，目标用户，特色功能等。
        2. 核心模块 - 生成5-8个核心功能模块（自动推测缺失环节）。
        3. 技术映射 - 根据所使用的编程语言，以及功能，推荐使用的库并说明选择理由。
        4. 风险预判 - 列出3项最高优先级的实施风险及应对方案。
        5. 交互原型 - 输出关键功能的流程图/状态图(可使用简单易懂的方式诸如 A -> B 表达)。

        说明：
        1. 整体需求补充字数不要超过500，每条补充项不要超过100

        下面是一段示例：
        ## 输入
        这是我的原始需求: 完成一个坦克大战

        环境信息如下:
        操作系统: Linux
        编程语言: Python 3.10

        ## 输出
        1.需求补全：
          开发经典坦克大战复刻版，支持双人本地协作。玩家通过摧毁敌方坦克保护基地，包含随机生成战场、可破坏地形、敌方AI军团、装备强化系统。
          具备关卡难度递增、实时计分板、战场特效，要求保留原版核心操作手感和战术策略要素。
        2. 核心模块:
          - 随机生成地图系统（可破坏障碍/固定墙体）
          - 双人本地操作模式（WASD+方向键控制）
          - 敌方AI自动寻路与攻击模块
          - 碰撞检测系统（子弹/地形/坦克交互）
          - 计分系统与关卡推进机制
          - 坦克能力升级系统（速度/护甲/弹药）
          - 基地保护核心机制
          - 战场音效与爆炸特效
        3. 技术映射
          - Pygame（2D渲染/事件处理/跨平台）
          - Tiled（地图编辑器集成）
          - pathfinding（A*算法实现AI移动）
          - Pygame.mixer（音效管理）
          - json（关卡配置存储）
          - numpy（碰撞矩阵运算加速）
        4. 风险预判
          - 多物体碰撞性能瓶颈 → 采用空间分割优化检测范围
          - 双人输入事件冲突 → 使用独立事件队列处理
          - AI路径finding卡死 → 设置随机方向重置机制
        5. 交互原型
          - 主循环流程：初始化 → 玩家控制 → AI行动 → 碰撞检测 → 渲染更新 → 胜利/失败判断 → 关卡切换
          - 子弹碰撞逻辑：子弹发射 → 碰撞检测 → (墙体: 消失 | 坦克: 扣血 | 基地: 游戏结束)
        """

    def build_project_information(self, query, env_info, language):
        self.llm.setup_default_model_name(self.chat_model)
        try:
            result = self._build_project_information.with_llm(self.llm).run(query, env_info, language)
            information = result.output
            return information
        except Exception as err:
            logger.error(f"完善项目需求错误: {str(err)}")
            return None

    @prompt()
    def _build_project_architecture(self, query, env_info, language, information):
        """
        这是我的原始需求: {{ query }}

        环境信息如下:
        操作系统: {{ env_info.os_name }} {{ env_info.os_version }}
        编程语言: {{ language }}

        补充后的需求：
        {{ information }}

        1. 根据编程语言及需求，首先判断项目项目类型（可能是 Web应用，命令行工具或数据处理管道）
        2. 首先构建一个的基础目录结构（可参考如下结构）
          - src 目录：源代码目录
          - tests 目录： 用于存放测试文件
          - docs 目录：用于存放文档
          - scripts 目录：用于存放实用脚本
        3. 接下来需要考虑 分层架构，比如将核心逻辑，接口，数据层，工具类等分开
        4. 同时还需要考虑各个模块的划分。比如，
          - 核心业务逻辑放在core模块
          - API路由在 api 目录
          - 数据模型在 models 目录
          - 数据库交互在 database 目录
          - 工具函数在 utils 目录
          - 中间件在 middleware 目录（如果是Web应用）
          - 配置加载在 config 目录
          - 错误处理在 errors 目录
          - 日志配置在 logs 等
        5. 还需要考虑依赖管理，比如py项目使用requirements管理依赖（分为开发和生产环境），或者使用Pipenv/Poetry
        6. 测试部分应有单元测试、集成测试，可能使用pytest，并在CI/CD中配置

        根据以上思路，我需要构建一个清晰，分层，模块化的目录结构，每个部分职责明确，方便扩展和维护，同时给出简要说明，让用户了解如何填充和扩展各个模块。
        返回结果按如下格式：

        - path/to/file1.py, 脚本功能描述
        - path/to/file2.py, 脚本功能描述
        - path/to/file3.py, 脚本功能描述

        请严格遵循以下规则：
        1. 脚本路径请使用相对路径（诸如 src/，core/，api/，utils/）
        2. 脚本功能描述说明该脚本的详细用途（控制在50字以内，且使用中文）
        3. 控制代码文件的数量，根据需求的复杂程度，简单需求代码文件控制在 5 个以内，中等需求文件数量控制在 5-10个，复杂项目文件数量控制在 10-20 个
        4. 请严格按格式要求返回结果,无需额外的说明
        """

    def build_project_architecture(self, query, env_info, language, information):
        self.llm.setup_default_model_name(self.chat_model)
        try:
            result = self._build_project_architecture.with_llm(self.llm).run(query, env_info, language, information)
            architecture = result.output
            return architecture
        except Exception as err:
            logger.error(f"完善项目架构错误: {str(err)}")
            return None

    @prompt()
    def _build_project_index(self, query, env_info, language, information, architecture):
        """
        这是我的原始需求: {{ query }}

        环境信息如下:
        操作系统: {{ env_info.os_name }} {{ env_info.os_version }}
        编程语言: {{ language }}

        补充后的需求：
        {{ information }}

        项目结构如下：
        {{ architecture }}

        我提供了以上诸如 '需求信息'，'目录结构' 信息。
        根据用户需求，对目录结构中的文件，依次进行扩充，即我需要完成这个用途的脚本，
        需要导入哪些库，创建哪些类，函数，变量，这些信息在后续可以直接用于生成代码

        扩充信息包括
        1. 函数
        2. 类
        3. 变量
        4. 所有导入语句

        下面是一段示例：

        ## 输入
        - src/core/game_loop.py, 游戏主循环控制器，负责帧率同步和模块调度
        - src/core/shape_generator.py, 七种基础形状生成及预览队列管理

        ## 输出
        ```json
        {
            "file_list": [
                {
                    "file_path": "src/core/game_loop.py",
                    "purpose": "游戏主循环控制器，负责帧率同步和模块调度",
                    "symbols": "\n函数：build_metadata+函数用途,main+函数用途\n变量：loop_time+变量用途\n类：\n导入语句：import csv^^import netaddr"
                },
                {
                    "file_path": "src/core/shape_generator.py",
                    "purpose": "七种基础形状生成及预览队列管理",
                    "symbols": "\n函数：build_metadata+函数用途,main+函数用途\n变量：loop_time+变量用途\n类：\n导入语句：import csv^^import netaddr"
                }
            ]
        }
        ```

        符号信息格式如下:
        ```
        {符号类型}: {符号名称}+{符号用途}, {符号名称}+{符号用途}, ...
        ```

        注意：
        1. 直接输出结果，不要尝试使用任何代码
        2. file_path 字段使用相对路径
        3. purpose 字段的长度不能超过50字
        4. symbols 字段的分隔符为^^
        5. 请严格按格式要求返回结果
        """

    def build_project_index(self, query, env_info, language, information, architecture) -> ProjectFileList:
        self.llm.setup_default_model_name(self.chat_model)
        result = self._build_project_index.with_llm(self.llm).with_return_type(ProjectFileList).run(
            query, env_info, language, information, architecture
        )
        return result

    @prompt()
    def _build_single_code(self, query, env_info, language, information, architecture, fileindex):
        """
        这是我的原始需求: {{ query }}

        环境信息如下:
        操作系统: {{ env_info.os_name }} {{ env_info.os_version }}
        编程语言: {{ language }}

        补充后的需求：
        {{ information }}

        项目结构如下：
        {{ architecture }}

        我提供了以上诸如 '需求信息'，'项目结构' 信息。
        现在需要你基于如下信息生成对应的代码

        路径: {{ fileindex.file_path }}
        用途: {{ fileindex.purpose }}
        符号信息: {{ fileindex.symbols }}

        注意：
        1. 请严格按照语言规范，直接输出代码

        ## 输出
        ```
        import os
        import time
        from loguru import logger
        import byzerllm

        a = ""

        @byzerllm.prompt(render="jinja")
        def auto_implement_function_template(instruction:str, content:str)->str:
            pass
        ```
        """

    def build_single_code(self, query, env_info, language, information, architecture, fileindex: IndexFilePath):
        self.llm.setup_default_model_name(self.code_model)
        try:
            result = self._build_single_code.with_llm(self.llm).run(
                query, env_info, language, information, architecture, fileindex
            )
            code = extract_code(result.output)[0][1]
            return code
        except Exception as err:
            logger.error(f"编写代码 {fileindex.file_path} 错误: {str(err)}")
            return None
