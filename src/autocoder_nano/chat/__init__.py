from rich.live import Live
from rich.panel import Panel
from rich.markdown import Markdown
from rich.text import Text

from autocoder_nano.core import AutoLLM
from autocoder_nano.actypes import AutoCoderArgs
from autocoder_nano.utils.printer_utils import Printer


printer = Printer


def stream_chat_display(
        chat_llm: AutoLLM, args: AutoCoderArgs, conversations: list[dict], max_history_lines: int = 15, max_height: int = 25
) -> str:
    v = chat_llm.stream_chat_ai(conversations=conversations, model=args.chat_model)

    lines_buffer = []
    assistant_response = ""
    current_line = ""

    try:
        with Live(Panel("", title="Response", style="cyan"), refresh_per_second=12) as live:
            for chunk in v:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    assistant_response += content

                    # 处理换行符分割
                    parts = (current_line + content).split('\n')

                    # 最后一部分是未完成的新行
                    if len(parts) > 1:
                        # 将完整行加入缓冲区
                        lines_buffer.extend(parts[:-1])
                        # 保留最近N行历史
                        if len(lines_buffer) > max_history_lines:
                            del lines_buffer[0: len(lines_buffer) - max_history_lines]
                    # 更新当前行（最后未完成的部分）
                    current_line = parts[-1]
                    # 构建显示内容 = 历史行 + 当前行
                    display_content = '\n'.join(lines_buffer[-max_history_lines:] + [current_line])

                    live.update(
                        Panel(Markdown(display_content), title="模型返回", border_style="cyan",
                              height=min(max_height, live.console.height - 4))
                    )

            # 处理最后未换行的内容
            if current_line:
                lines_buffer.append(current_line)

            # 最终完整渲染
            live.update(
                Panel(Markdown(assistant_response), title="模型返回", border_style="dim blue")
            )
    except Exception as e:
        printer.print_panel(Text(f"{str(e)}", style="red"), title="模型返回", center=True)

    return assistant_response


__all__ = ["stream_chat_display"]
