from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable


class BaseTool:
    """工具基类抽象"""
    def __init__(self,  name: str,  description: str, parameters: Dict[str, type]):
        self.name = name
        self.description = description
        self.parameters = parameters

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """工具执行方法（伪代码）"""
        pass


class BaseAgent(ABC):
    """Agent基类抽象"""
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}  # 可用工具注册表
        self.memory = []  # 记忆存储
        self.history = []  # 交互历史

    def register_tool(self, tool: BaseTool):
        """注册工具到Agent"""
        self.tools[tool.name] = tool

    @abstractmethod
    def decide_next_action(self, user_input: str, available_tools: List[BaseTool]) -> Dict:
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

    def execute_tool(self, tool_name: str, parameters: Dict) -> str:
        """执行工具并处理异常"""
        try:
            tool = self.tools.get(tool_name)
            if not tool:
                return f"Error: Tool {tool_name} not found"
            return tool.execute(**parameters)
        except Exception as e:
            return f"Error executing {tool_name}: {str(e)}"

    def process_request(self, user_input: str) -> str:
        """
        处理请求的主流程：
        1. 接收用户输入
        2. 决策循环
        3. 执行工具
        4. 整合结果
        """
        self.history.append(("user", user_input))

        # 决策循环（可能包含多步工具调用）
        final_response = None
        max_steps = 5  # 防止无限循环

        for _ in range(max_steps):
            # 获取决策（由大模型实现）
            decision = self.decide_next_action(
                user_input=user_input,
                available_tools=list(self.tools.values())
            )

            # 记录到历史
            self.history.append(("system", decision))

            if decision["action"] == "final_answer":
                final_response = decision["parameters"]["answer"]
                break

            # 执行工具
            tool_result = self.execute_tool(
                decision["action"],
                decision["parameters"]
            )

            # 将结果加入上下文
            self.memory.append({
                "action": decision["action"],
                "result": tool_result
            })

        return final_response or "Unable to generate valid response"


class ExampleAgent(BaseAgent):
    """示例实现（需要开发者完善大模型交互部分）"""
    def decide_next_action(self, user_input, available_tools):
        """
        伪代码实现：
        - 调用大模型API
        - 解析返回的JSON
        - 返回决策字典
        """
        # 这里用伪代码代替实际的大模型调用
        return {
            "action": "search_tool",
            "parameters": {"query": user_input},
            "reasoning": "用户需要实时信息查询"
        }


# 使用示例
if __name__ == "__main__":
    # 创建Agent
    agent = ExampleAgent()

    # 注册工具（示例）
    search_tool = BaseTool(
        name="search_tool",
        description="网络搜索工具",
        parameters={"query": str}
    )
    agent.register_tool(search_tool)

    # 处理请求
    response = agent.process_request("今天北京的天气如何？")
    print(response)