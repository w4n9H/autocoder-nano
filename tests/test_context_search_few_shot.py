import os
import pprint

from autocoder_nano.context import get_context_manager, ContextManagerConfig
from autocoder_nano.utils.file_utils import load_tokenizer


def context_search_few_shot_test():
    load_tokenizer()
    cmc = ContextManagerConfig()
    cmc.storage_path = os.path.join("/Users/moofs/Code/autocoder-nano", ".auto-coder", "context")
    gcm = get_context_manager(config=cmc)

    conv_id = gcm.create_conversation(name="数据科学学习", description="包含Pandas、NumPy和Matplotlib的使用问题与解答")
    gcm.set_current_conversation(conversation_id=conv_id)
    print(f"创建对话成功（ID: {conv_id}）\n")

    gcm.append_message_to_current(role="user", content="如何用Pandas按条件筛选DataFrame？比如筛选'年龄>30'且'城市=北京'的行？")
    gcm.append_message_to_current(role="assistant", content="可以组合布尔条件：\n"
                                                            "import pandas as pd\n"
                                                            "df = pd.DataFrame(...)  # 假设已有数据\n"
                                                            "result = df[(df['年龄'] > 30) & (df['城市'] == '北京')]"
                                  )
    gcm.append_message_to_current(role="user", content="DataFrame中有很多NaN值，怎么高效处理？需要保留大部分数据")
    gcm.append_message_to_current(role="assistant", content="分情况处理：\n"
                                                            "1. 数值列：用均值/中位数填充\n"
                                                            "   df['数值列'].fillna(df['数值列'].median(), inplace=True)\n"
                                                            "2. 类别列：用众数填充\n"
                                                            "   df['类别列'].fillna(df['类别列'].mode()[0], inplace=True)\n"
                                  )
    gcm.append_message_to_current(role="user", content="如何用Matplotlib画一个带误差线的柱状图？需要显示每个柱子的标准差")
    gcm.append_message_to_current(role="assistant", content="示例代码：\n"
                                                            "import matplotlib.pyplot as plt\n"
                                                            "x = ['A', 'B', 'C']\n"
                                                            "y = [20, 35, 30]\n"
                                                            "error = [2, 4, 3]  # 标准差\n"
                                                            "plt.bar(x, y, yerr=error, capsize=5)\n"
                                                            "plt.title('带误差线的柱状图')\n"
                                                            "plt.show()"
                                  )
    print(f"添加多轮消息完成（共{len(gcm.get_current_conversation()['messages'])}条消息）\n")

    def search_message_and_print(_query):
        print(f"=== 搜索语句: '{_query}' ===")
        msg_results = gcm.search_messages(
            conversation_id=gcm.get_current_conversation_id(),
            query=_query,  # 匹配助手回答中"标准差"相关内容
            min_score=0.2
        )
        for m in msg_results:
            print(f"\n消息ID: {m['message']['message_id']}（相关度: {m['score']:.2f}）")
            print(f"角色: {m['message']['role']}")
            print(f"内容: {m['message']['content'][:80]}...")  # 展示部分内容
        print("\n" + "-" * 50)

    search_message_and_print("使用Pandas进行条件筛选")
    search_message_and_print("缺失值使用中位数填充")
    search_message_and_print("Matplotlib 误差线 柱状图")
    search_message_and_print("")

    def filter_message_and_print(_query, _filters):
        print(f"=== 搜索条件: '{_filters}', 语句: '{_query}' ===")
        msg_results = gcm.search_messages(
            conversation_id=gcm.get_current_conversation_id(),
            filters=_filters,
            query=_query,  # 匹配助手回答中"标准差"相关内容
        )
        for m in msg_results:
            print(f"\n消息ID: {m['message']['message_id']}（相关度: {m['score']:.2f}）")
            print(f"角色: {m['message']['role']}")
            print(f"内容: {m['message']['content'][:80]}...")  # 展示部分内容
        print("\n" + "-" * 50)

    filter_message_and_print(
        _query="如何用Pandas按条件筛选DataFrame？比如筛选'年龄>30'且'城市=北京'的行？\n"
               "DataFrame中有很多NaN值，怎么高效处理？需要保留大部分数据 \n"
               "如何用Matplotlib画一个带误差线的柱状图？需要显示每个柱子的标准差",
        _filters={"filters": [{"field": "role", "operator": "in", "value": ["user", "assistant"]}], "operator": "and"}
    )

    # 清理测试数据
    gcm.delete_conversation(gcm.get_current_conversation_id())
    print("测试数据清理完毕")


if __name__ == '__main__':
    context_search_few_shot_test()
