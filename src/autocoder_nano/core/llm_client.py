from typing import List, Generator, Any, Optional, Dict, Union

# from loguru import logger
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletionChunk, ChatCompletion

from autocoder_nano.actypes import LLMRequest, LLMResponse, AutoCoderArgs, SingleOutputMeta
from autocoder_nano.utils.printer_utils import Printer, COLOR_INFO, COLOR_WARNING


printer = Printer()


class AutoLLM:
    def __init__(self):
        self.default_model_name = None
        self.sub_clients = {}

        # llm printer prefix
        self.lpp = f"* (waiting for llm) "

    def setup_sub_client(self, client_name: str, api_key: str, base_url: str, model_name=""):
        self.sub_clients[client_name] = {
            "client": OpenAI(api_key=api_key, base_url=base_url),
            "model_name": model_name
        }
        return self

    def remove_sub_client(self, client_name: str):
        if client_name in self.sub_clients:
            del self.sub_clients[client_name]

    def get_sub_client(self, client_name: str):
        return self.sub_clients.get(client_name, None)

    def setup_default_model_name(self, model_name: str):
        self.default_model_name = model_name

    def stream_chat_ai(self, conversations, model=None) -> Stream[ChatCompletionChunk]:
        if not model and not self.default_model_name:
            raise Exception("model name is required")

        if not model:
            model = self.default_model_name

        model_name = self.sub_clients[model]["model_name"]
        # printer.print_text(f"模型调用[{model}], 模型名称[{model_name}], 调用函数[stream_chat_ai]",
        #                    style=COLOR_INFO, prefix=self.lpp)
        request = LLMRequest(
            model=model_name,
            messages=conversations
        )
        res = self._query(model, request, stream=True)
        return res

    def stream_chat_ai_ex(
            self, conversations, model: Optional[str] = None, role_mapping=None, delta_mode: bool = False,
            is_reasoning: bool = False, llm_config: dict | None = None
    ):
        if llm_config is None:
            llm_config = {}
        if not model:
            model = self.default_model_name

        client: OpenAI = self.sub_clients[model]["client"]
        model_name = self.sub_clients[model]["model_name"]

        # printer.print_text(f"模型调用[{model}], 模型名称[{model_name}], 调用函数[stream_chat_ai_ex]",
        #                    style=COLOR_INFO, prefix=self.lpp)

        request = LLMRequest(
            model=model_name,
            messages=conversations,
            stream=True
        )

        if is_reasoning:
            response = client.chat.completions.create(
                messages=request.messages,
                model=request.model,
                stream=request.stream,
                stream_options={"include_usage": True},
                extra_headers={
                    "HTTP-Referer": "https://auto-coder.chat",
                    "X-Title": "auto-coder-nano"
                },
                **llm_config
            )
        else:
            response = client.chat.completions.create(
                messages=conversations,
                model=model_name,
                temperature=llm_config.get("temperature", request.temperature),
                max_tokens=llm_config.get("max_tokens", request.max_tokens),
                top_p=llm_config.get("top_p", request.top_p),
                stream=request.stream,
                stream_options={"include_usage": True},
                **llm_config
            )

        last_meta = None

        if delta_mode:
            for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tokens_count = chunk.usage.prompt_tokens
                    generated_tokens_count = chunk.usage.completion_tokens
                else:
                    input_tokens_count = 0
                    generated_tokens_count = 0

                if not chunk.choices:
                    if last_meta:
                        yield (
                            "",
                            SingleOutputMeta(
                                input_tokens_count=input_tokens_count,
                                generated_tokens_count=generated_tokens_count,
                                reasoning_content="",
                                finish_reason=last_meta.finish_reason,
                            ),
                        )
                    continue

                content = chunk.choices[0].delta.content or ""

                reasoning_text = ""
                if hasattr(chunk.choices[0].delta, "reasoning_content"):
                    reasoning_text = chunk.choices[0].delta.reasoning_content or ""

                last_meta = SingleOutputMeta(
                    input_tokens_count=input_tokens_count,
                    generated_tokens_count=generated_tokens_count,
                    reasoning_content=reasoning_text,
                    finish_reason=chunk.choices[0].finish_reason,
                )
                yield content, last_meta
        else:
            s = ""
            all_reasoning_text = ""
            for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage:
                    input_tokens_count = chunk.usage.prompt_tokens
                    generated_tokens_count = chunk.usage.completion_tokens
                else:
                    input_tokens_count = 0
                    generated_tokens_count = 0

                if not chunk.choices:
                    if last_meta:
                        yield (
                            s,
                            SingleOutputMeta(
                                input_tokens_count=input_tokens_count,
                                generated_tokens_count=generated_tokens_count,
                                reasoning_content=all_reasoning_text,
                                finish_reason=last_meta.finish_reason,
                            ),
                        )
                    continue

                content = chunk.choices[0].delta.content or ""
                reasoning_text = ""
                if hasattr(chunk.choices[0].delta, "reasoning_content"):
                    reasoning_text = chunk.choices[0].delta.reasoning_content or ""

                s += content
                all_reasoning_text += reasoning_text
                yield (
                    s,
                    SingleOutputMeta(
                        input_tokens_count=input_tokens_count,
                        generated_tokens_count=generated_tokens_count,
                        reasoning_content=all_reasoning_text,
                        finish_reason=chunk.choices[0].finish_reason,
                    ),
                )

    def chat_ai(self, conversations, model=None) -> LLMResponse:
        # conversations = [{"role": "user", "content": prompt_str}]  deepseek-chat
        if not model and not self.default_model_name:
            raise Exception("model name is required")

        if not model:
            model = self.default_model_name

        if isinstance(conversations, str):
            conversations = [{"role": "user", "content": conversations}]

        model_name = self.sub_clients[model]["model_name"]
        # printer.print_text(f"模型调用[{model}], 模型名称[{model_name}], 调用函数[chat_ai]",
        #                    style=COLOR_INFO, prefix=self.lpp)
        request = LLMRequest(
            model=model_name,
            messages=conversations
        )

        res = self._query(model, request)
        return LLMResponse(
            output=res.choices[0].message.content,
            input="",
            metadata={
                "id": res.id,
                "model": res.model,
                "created": res.created
            }
        )

    def _query(self, model_name: str, request: LLMRequest, stream=False) -> ChatCompletion | Stream[ChatCompletionChunk]:
        """ 与 LLM 交互 """
        response = self.sub_clients[model_name]["client"].chat.completions.create(
            model=request.model,
            messages=request.messages,
            stream=stream,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            n=request.n,
            stop=request.stop,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
        )
        return response

    def embedding(self, text: List, model=None):
        if not model and not self.default_model_name:
            raise Exception("model name is required")

        if not model:
            model = self.default_model_name

        model_name = self.sub_clients[model]["model_name"]

        res = self.sub_clients[model]["client"].embeddings.create(
            model=model_name,
            input=text,
            encoding_format="float"
        )
        return LLMResponse(
            output=res.data[0].embedding,
            input="",
            metadata={
                "id": res.id,
                "model": res.model,
                "created": res.created
            }
        )


def stream_chat_with_continue(
        llm: AutoLLM, conversations: List[dict], llm_config: dict, args: AutoCoderArgs
) -> Generator[Any, None, None]:
    """ 流式处理并继续生成内容，直到完成 """
    count = 0
    temp_conversations = [] + conversations
    current_metadata = None
    metadatas = {}
    while True:
        # 使用流式接口获取生成内容
        stream_generator = llm.stream_chat_ai_ex(
            conversations=temp_conversations,
            model=args.chat_model,
            delta_mode=True,
            llm_config={**llm_config}
        )

        current_content = ""

        for res in stream_generator:
            content = res[0]
            current_content += content
            if current_metadata is None:
                current_metadata = res[1]
                metadatas[count] = res[1]
            else:
                metadatas[count] = res[1]
                current_metadata.finish_reason = res[1].finish_reason
                current_metadata.reasoning_content = res[1].reasoning_content

            # Yield 当前的 StreamChatWithContinueResult
            current_metadata.generated_tokens_count = sum([v.generated_tokens_count for _, v in metadatas.items()])
            current_metadata.input_tokens_count = sum([v.input_tokens_count for _, v in metadatas.items()])
            yield content, current_metadata

        # 更新对话历史
        temp_conversations.append({"role": "assistant", "content": current_content})

        # 检查是否需要继续生成
        if current_metadata.finish_reason != "length" or count >= args.generate_max_rounds:
            if count >= args.generate_max_rounds:
                printer.print_text(f"LLM生成达到的最大次数, 当前次数:{count}, 最大次数: {args.generate_max_rounds}, "
                                   f"Tokens: {current_metadata.generated_tokens_count}", style=COLOR_WARNING)
            break
        count += 1