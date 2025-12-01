from prompt_toolkit.lexers import Lexer

from autocoder_nano.utils.completer_utils import flatten_commands


class SimpleAutoCoderLexer(Lexer):
    def lex_document(self, document):
        lines = document.lines

        def get_line(lineno: int):
            line = lines[lineno]
            style_and_text_tuples = []

            # 简单的关键词高亮示例
            code_keywords = ['def', 'class', 'if', 'else', 'for', 'while', 'return', 'import', 'from']
            nano_keywords = flatten_commands()
            nano_keywords.extend(["/exit", "/list_files", "/shell"])    # 补充
            for word in line.split():
                if word in code_keywords:
                    style_and_text_tuples.append(('class:keyword', word))
                    style_and_text_tuples.append(('', ' '))
                elif word in nano_keywords:
                    style_and_text_tuples.append(('class:keyword2', word))
                    style_and_text_tuples.append(('', ' '))
                else:
                    style_and_text_tuples.append(('class:other', word))
                    style_and_text_tuples.append(('', ' '))

            return style_and_text_tuples

        return get_line