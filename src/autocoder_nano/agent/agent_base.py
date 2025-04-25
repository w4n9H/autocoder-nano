import random
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from typing import Dict, List, Any, Deque, Union

from loguru import logger
from pydantic import BaseModel

from autocoder_nano.llm_prompt import prompt
from autocoder_nano.llm_client import AutoLLM


# -------------------- 基础数据模型 --------------------


class AgentMemoryItem(BaseModel):
    step_id: int = 0  # 步骤标识
    action: str
    parameters: Dict[str, Any]
    result: Dict[str, Any]  # 结果改为结构化字典
    output_fields: List[str]  # 改为列表类型, 存储提取的关键字段
    timestamp: datetime = datetime.now()


class DecisionContext(BaseModel):
    """决策上下文数据模型"""
    user_input: str
    history: List[tuple]
    memory: List[AgentMemoryItem]
    context_vars: Dict[str, Any] = {}  # 新增上下文变量存储


class SingleTool(BaseModel):
    """ 单个工具 """
    action: str
    parameters: Dict[str, Union[str, Dict[str, Any]]]  # 修改为支持嵌套结构
    reasoning: str
    output_fields: List[str] = []  # 设置为可选，默认空列表


class ToolChain(BaseModel):
    """ 工具链 """
    tools: List[SingleTool]


# -------------------- 工具基类 --------------------


class BaseTool:
    """ 工具基类抽象 """

    def __init__(self, name: str, description: str, input_parameters: str, output_parameters: str):
        self.name = name  # 工具名称
        self.description = description  # 工具描述
        self.input_parameters = input_parameters
        self.output_parameters = output_parameters
        # self.parameters = parameters  # 工具参数

    @abstractmethod
    def execute(self, **kwargs) -> Dict:
        """ 工具执行方法(由继承类实现) """
        pass


# -------------------- Agent基类 --------------------


class BaseAgent(ABC):
    """ Agent基类抽象 """

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}  # 可用工具注册表
        self.short_term_memory: Deque[AgentMemoryItem] = deque(maxlen=100)  # 短期记忆
        self.long_term_memory: List[AgentMemoryItem] = []  # 长期记忆
        self.history: List[tuple] = []  # 交互历史
        self.step_counter = 0  # 新增步骤计数器

    def register_tool(self, tool: BaseTool):
        """注册工具到Agent"""
        self.tools[tool.name] = tool

    @abstractmethod
    def decide_next_action(self, context: DecisionContext) -> ToolChain:
        """
        决策核心（需要子类实现）
        返回结构示例：
        {
            "action": "tool_name",
            "parameters": {"param1": value},
            "reasoning": "选择该工具的逻辑原因"
        }
        """
        pass

    def execute_tool(self, tool_name: str, parameters: Dict, context_vars: Dict) -> Dict:
        """ 同步执行工具（新增context_vars参数）"""
        return self.execute_tool_async(tool_name, parameters, context_vars)

    def execute_tool_async(self, tool_name: str, parameters: Dict, context_vars: Dict):
        """执行工具并处理异常（新增context_vars参数）"""
        try:
            tool = self.tools.get(tool_name)
            if not tool:
                return {"error": f"Tool {tool_name} not found"}

            # 参数预处理（替换上下文变量）
            processed_params = {}
            for k, v in parameters.items():
                if isinstance(v, str) and v.startswith("ctx."):
                    var_name = v[4:]
                    processed_params[k] = context_vars.get(var_name, v)
                    # processed_params[k] = var_name.format(**context_vars)
                else:
                    processed_params[k] = v

            return tool.execute(**processed_params)
        except Exception as e:
            return {"error": f"Error executing {tool_name}: {str(e)}"}

    @staticmethod
    def should_persist(memory_item: AgentMemoryItem) -> bool:
        """简单判断是否需要持久化到长期记忆"""
        # 这里简单实现：随机决定是否持久化
        return random.random() > 0.7

    def process_request(self, user_input: str) -> str:
        self.history.append(("user", user_input))
        logger.info(f"正在处理需求: {user_input}")

        # 初始化上下文变量
        context_vars = {}
        final_response = None

        # 构建决策上下文
        context = DecisionContext(
            user_input=user_input,
            history=self.history,
            memory=list(self.short_term_memory) + self.long_term_memory,
            context_vars=context_vars
        )

        # 获取完整工具链
        decision_chain = self.decide_next_action(context)
        logger.info(f"工具链总共有 {len(decision_chain.tools)} 步")
        logger.info("依次使用以下工具: ")
        for decision in decision_chain.tools:
            logger.info(f"{decision.action}: {decision.reasoning}")

        # 执行工具链
        for decision in decision_chain.tools:
            self.step_counter += 1
            logger.info(f"正在执行: {self.step_counter}/{len(decision_chain.tools)}")

            if decision.action == "final_answer":
                final_response = decision.parameters["input"]
                # 处理上下文变量引用
                if final_response.startswith("ctx."):
                    final_response = context_vars.get(final_response[4:], final_response)
                break

            # 执行工具
            tool_result = self.execute_tool(
                decision.action,
                decision.parameters,
                context_vars
            )

            # 更新上下文变量
            # if "output_fields" in decision:
            for field in decision.output_fields:
                if field in tool_result:
                    context_vars[field] = tool_result[field]

            # 记录记忆
            memory_item = AgentMemoryItem(
                step_id=self.step_counter,
                action=decision.action,
                parameters=decision.parameters,
                result=tool_result,
                output_fields=decision.output_fields  # 确保传入列表
            )
            self.short_term_memory.append(memory_item)
            if self.should_persist(memory_item):
                self.long_term_memory.append(memory_item)

        logger.info("工具链执行完毕")

        return final_response or "Unable to generate valid response"


# -------------------- 具体工具实现 --------------------


class GenerateSQL(BaseTool):
    def __init__(self):
        super().__init__(
            name="generate_sql",
            description="基于用户的需求生成对应的数据查询sql",
            input_parameters="`input`: str 类型, 用户需求",
            output_parameters="`output`: str 类型，基于用户需求生成对应的数据库查询sql"
            # parameters={"intput": str}
        )

    def execute(self, **kwargs) -> Dict:
        query = kwargs.get("input", "")
        time.sleep(0.2)
        return {"output": f"分析 {query} :select * from table limit 100;"}


class QueryData(BaseTool):
    def __init__(self):
        super().__init__(
            name="query_data",
            description="基于sql去数据库中查询数据",
            input_parameters="`input`: str 类型, 用于查询数据库的 sql 语句",
            output_parameters="`output`: str 类型，基于 sql 查询出来的数据"
            # parameters={"input": str}
        )

    def execute(self, **kwargs) -> Dict:
        sql = kwargs.get("input", "")
        time.sleep(0.2)
        return {"output": f"基于 {sql}, 返回数据: 1234567890"}


class AnalysisData(BaseTool):
    def __init__(self):
        super().__init__(
            name="analysis_data",
            description="分析查询的数据",
            input_parameters="`input`: str 类型, 从数据库中查询到的数据",
            output_parameters="`output`: str 类型，数据分析结果"
            # parameters={"input": str}
        )

    def execute(self, **kwargs) -> Dict:
        data = kwargs.get("input", "")
        time.sleep(0.2)
        return {"output": f"分析 {data} 数据, 该数据正常"}


# -------------------- 示例Agent实现 --------------------


class ExampleAgent(BaseAgent):
    """ 可运行的demo实现，模拟大模型决策 """

    def __init__(self, llm: AutoLLM):
        super().__init__()
        self.llm = llm

    @prompt()
    def _example_prompt(self, context: DecisionContext, tools: Dict[str, BaseTool]):
        """
        ## 角色定义
        您是 Auto-Coder 团队开发的顶级AI助手 Auto-Coder，定位为全能型智能体，需主动思考并综合运用工具链解决复杂问题

        ## 核心能力
        1. 信息处理专家 - 支持多语言文档分析/数据清洗/知识图谱构建
        2. 代码工程师 - 全栈开发/自动化脚本/数据处理程序编写
        3. 研究助手 - 文献综述/数据分析/可视化报告生成
        4. 问题解决专家 - 分步拆解复杂问题，通过工具组合实现目标

        ## 工作流程
        1. 输入解析：
            a. 识别用户真实需求，区分任务类型（查询/计算/编程/研究等）
        2. 上下文查看：
            a. 分析记忆库中的相关记录
            b. 检索历史交互记录
            c. 确认当前执行目标
        3. 工具决策：
            a. 严格遵循工具调用模式, 确保提供所有必要参数, 以及确保参数类型/格式/单位的正确
            b. 绝不调用未列出的工具
            c. 优先选择耗时最短的工具链组合(即仅在必要时调用工具)
            d. 调用工具需向用户说明原因(20字以内说明即可)
        4. 结果处理：
            a. 验证工具返回数据的有效性
            b. 自动修正异常值/格式错误

        ## 工具调用规范 [严格模式]
        1. 参数校验: 缺失参数时直接结束调用链生成，禁止猜测参数值，并且说明具体缺失内容
        2. 工具组合: 单个需求决策最多使用 5 个工具种类，如果 5 个工具种类无法解决这个需求, 直接结束调用链生成, 并且说明原因
        3. 工具链长度: 单个需求的工具链组合最多不超过 10 个, 避免长依赖链, 如果 10 个步骤无法解决这个需求, 直接结束调用链生成, 并且说明原因

        ## 交互协议
        1. 语言策略:
            a. 默认使用中文交互
            b. 代码块/技术参数/工具名称 保持英文
            c. 专业术语首次出现时附加中文注释
        2. 成功响应标准:
            a. 在要求的工具种类数量, 以及工具链长度下, 可以顺利完成用户需求时, 为成功响应, 正常返回工具链即可
        3. 失败响应标准:
            a. 缺失参数时直接结束调用链生成, 为失败响应
            b. 5 个工具种类无法解决这个需求时直接结束调用链生成, 为失败响应
            c. 10 个步骤无法解决这个需求时直接结束调用链生成, 为失败响应
        4. 风格要求：
            a. 保持专业但友好的语气
            b. 避免使用Markdown格式

        ## 以下是一个正常生成工具链的示例需求
        原始需求：我要分析xxx数据

        工具列表
        工具名称: generate_sql
        工具描述: 基于用户的需求生成对应的数据查询sql
        参数说明:
            - `input`: str 类型, 用户的查询需求
        返回值:
            - `output`: str 类型，根据用户需求生成的数据库查询 sql 语句
        ----------------------------------
        工具名称: query_data
        工具描述: 基于sql去数据库中查询数据
        参数说明:
            - `input`: str 类型, 用于查询数据库的 sql 语句
        返回值:
            - `output`: str 类型，基于 sql 查询出来的数据
        ----------------------------------
        工具名称: analysis_data
        工具描述: 分析查询的数据
        参数说明:
            - `input`: str 类型, 用于查询数据库的 sql 语句
        返回值:
            - `output`: str 类型，基于 sql 查询出来的数据

        工具链正常返回示例
        ```
        {
            "tools": [
                {
                    "action": "generate_sql",
                    "parameters": {"input": user_input},
                    "reasoning": "基于用户的需求生成对应的数据查询sql",
                    "output_fields": ["output"]
                },
                {
                    "action": "query_data",
                    "parameters": {"input": "ctx.output"},
                    "reasoning": "基于sql去数据库中查询数据",
                    "output_fields": ["output"]
                },
                {
                    "action": "analysis_data",
                    "parameters": {"input": "ctx.output"},
                    "reasoning": "分析查询的数据",
                    "output_fields": ["output"]
                },
                {
                    "action": "final_answer",
                    "parameters": {"input": "ctx.output"},
                    "reasoning": "输出最终结果",
                    "output_fields": []
                }
            ]
        }
        ```

        工具链异常返回示例
        ```
        {
            "tools": [
                {
                    "action": "final_answer",
                    "parameters": {"input": ""},
                    "reasoning": "工具链生成异常原因",
                    "output_fields": []
                }
            ]
        }
        ```

        返回说明:
        1. 请严格按格式要求返回结果, 无需额外的说明
        2. action 字段表示你决定选用的工具名称, 如果是最后一个步骤, 填写 'final_answer'
        3. parameters 字段表示输入参数, 字段名称固定使用 'input',
            a. 如果是首个工具调用, 直接填充用户需求, 即 {"input": "用户需求"}
            b. 第二个之后的工具调用, 填充 'ctx.output' , 即 {"input": "ctx.output"}
            c. 如果是调用链生成失败, 填充空字符串, 即  {"input": ""}
        2. reasoning 字段表示你选用这个工具的原因 或者 工具链生成异常原因, 20字以内说明即可
        3. output_fields 字段表示输出的字段，字段名称固定使用 'output', 如果 'action' 为 'final_answer', 填写 [] 即可

        ## 正式需求决策上下文

        用户需求: {{ context.user_input }}

        交互历史:
        {% for his in context.history %}
        {{ his }}
        {% endfor %}

        记忆Memory系统: {}

        工具列表:
        {% for key, value in tools.items() %}
        工具名称: {{ key }}
        工具描述: {{ value.description }}
        参数说明:
            - {{ value.input_parameters }}
        返回值:
            - {{ value.output_parameters }}
        ----------------------------------
        {% endfor %}

        接下来请生成工具链
        """

    def decide_next_action(self, context: DecisionContext) -> ToolChain:
        """
        伪代码实现：
        - 调用大模型API
        - 解析返回的JSON
        - 返回决策字典
        """
        llm = self.llm
        llm.setup_default_model_name('chat_model')
        tools = self._example_prompt.with_llm(self.llm).with_return_type(ToolChain).run(context, self.tools)

        return tools


# -------------------- 使用示例 --------------------


# 使用示例
if __name__ == "__main__":
    auto_llm = AutoLLM()
    auto_llm.setup_sub_client(
        "chat_model",
        "",
        "https://ark.cn-beijing.volces.com/api/v3",
        "deepseek-v3-250324"
    )
    agent = ExampleAgent(auto_llm)
    agent.register_tool(GenerateSQL())
    agent.register_tool(QueryData())
    agent.register_tool(AnalysisData())

    response = agent.process_request("我要分析xxx数据")
    # print(f"系统响应：{response}")
