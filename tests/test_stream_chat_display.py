from autocoder_nano.chat import stream_chat_display
from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs


def stream_chat_display_test():
    query = "你好, 介绍一下你自己"

    llm = AutoLLM()
    llm.setup_sub_client(
        client_name="ark-deepseek-v3",
        api_key="",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model_name="deepseek-v3-250324"
    )

    args = AutoCoderArgs()
    args.chat_model = "ark-deepseek-v3"

    conversations = [{"role": "user", "content": query}]

    assistant_response = stream_chat_display(chat_llm=llm, args=args, conversations=conversations)

    # print(assistant_response)


if __name__ == '__main__':
    stream_chat_display_test()