import inspect
import json
import re
from typing import Type, Dict, Any, List, Union, Tuple, Optional


def format_prompt(func, **kargs):
    """
    根据函数的文档字符串生成提示模板，并使用提供的参数格式化该模板。
    参数:
    - func: 目标函数，其文档字符串将用于生成提示模板。
    - **kargs: 用于格式化提示模板的参数。
    返回值:
    - 格式化后的提示字符串。
    步骤:
    1. 获取目标函数的文档字符串。
    2. 将文档字符串按行分割，并去除每行的前导空白字符。
    3. 使用 LangChain 的 PromptTemplate 从处理后的文档字符串生成提示模板。
    4. 使用提供的参数格式化提示模板，返回格式化后的提示字符串。
    """
    # from langchain import PromptTemplate
    from string import Template
    doc = func.__doc__
    lines = doc.splitlines()
    # get the first line to get the whitespace prefix
    first_non_empty_line = next(line for line in lines if line.strip())
    prefix_whitespace_length = len(first_non_empty_line) - len(first_non_empty_line.lstrip())
    _prompt = "\n".join([line[prefix_whitespace_length:] for line in lines])
    # tpl = PromptTemplate.from_template(_prompt)
    tpl = Template(_prompt)
    # return tpl.format(**kargs)
    return tpl.safe_substitute(**kargs)


def format_prompt_jinja2(func, **kargs):
    from jinja2 import Template
    doc = func.__doc__
    lines = doc.splitlines()
    # get the first line to get the whitespace prefix
    first_non_empty_line = next(line for line in lines if line.strip())
    prefix_whitespace_length = len(first_non_empty_line) - len(first_non_empty_line.lstrip())
    _prompt = "\n".join([line[prefix_whitespace_length:] for line in lines])
    tpl = Template(_prompt)
    return tpl.render(kargs)


def format_str_jinja2(s, **kargs):
    from jinja2 import Template
    tpl = Template(s)
    return tpl.render(kargs)


def content_str(content: Union[str, List, None]) -> str:
    """
    将 content 转换为字符串格式。
    此函数处理可能是字符串、混合文本和图像 URL 的列表或 None 的内容，并将其转换为字符串。
    文本直接附加到结果字符串中，而图像 URL 则由占位符图像标记表示。如果内容为 None，则返回空字符串。
    参数:
    - content (Union[str, List, None]): 要处理的内容。可以是字符串、表示文本和图像 URL 的字典列表，或 None。
    返回:
    - str: 输入内容的字符串表示形式。图像 URL 被替换为图像标记。
    注意:
      该函数期望列表中的每个字典都有一个 "type" 键，其值为 "text" 或 "image_url"。对于 "text" 类型，"text" 键的值将附加到结果中。
      对于 "image_url"，将附加一个图像标记。
      此函数适用于处理可能包含文本和图像引用的内容，特别是在需要将图像表示为占位符的上下文中。
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise TypeError(f"content must be None, str, or list, but got {type(content)}")

    rst = ""
    for item in content:
        if not isinstance(item, dict):
            raise TypeError("Wrong content format: every element should be dict if the content is a list.")
        assert "type" in item, "Wrong content format. Missing 'type' key in content's dict."
        if item["type"] == "text":
            rst += item["text"]
        elif item["type"] == "image_url":
            rst += "<image>"
        else:
            raise ValueError(f"Wrong content format: unknown type {item['type']} within the content")
    return rst


def extract_code(
        text: Union[str, List],
        pattern: str = r"```[ \t]*(\w+)?[ \t]*\r?\n(.*?)\r?\n[ \t]*```",
        detect_single_line_code: bool = False
) -> List[Tuple[str, str]]:
    """
    从文本中提取代码。
    参数:
    - text (str 或 List): 要从中提取代码的内容。内容可以是字符串或列表，通常由标准 GPT 或多模态 GPT 返回。
    - pattern (str, 可选): 用于查找代码块的正则表达式模式。默认为 CODE_BLOCK_PATTERN。
    - detect_single_line_code (bool, 可选): 启用提取单行代码的新功能。默认为 False。
    返回:
    - list: 一个包含元组的列表，每个元组包含语言和代码。
      - 如果输入文本中没有代码块，则语言为 "unknown"。
      - 如果有代码块但未指定语言，则语言为 ""。
    """
    text = content_str(text)
    if not detect_single_line_code:
        match = re.findall(pattern, text, flags=re.DOTALL)
        return match if match else [("unknown", text)]

    # Extract both multi-line and single-line code block, separated by the | operator
    # `([^`]+)`: Matches inline code.
    code_pattern = re.compile(pattern + r"|`([^`]+)`")
    code_blocks = code_pattern.findall(text)

    # Extract the individual code blocks and languages from the matched groups
    extracted = []
    for lang, group1, group2 in code_blocks:
        if group1:
            extracted.append((lang.strip(), group1.strip()))
        elif group2:
            extracted.append(("", group2.strip()))

    return extracted


class _PrompRunner:
    def __init__(self, func, instance, llm, render: str, check_result: bool, options: Dict[str, Any]) -> None:
        self.func = func
        self.instance = instance
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self._options = options
        self.response_markers = None
        self.return_prefix = None
        self.extractor = None
        self.model_class = None
        self.max_turns = 10

    def __call__(self, *args, **kwargs) -> Any:
        return self.prompt(*args, **kwargs)

    def options(self, options: Dict[str, Any]):
        self._options = {**self._options, **options}
        return self

    def prompt(self, *args, **kwargs):
        signature = inspect.signature(self.func)
        if self.instance:
            arguments = signature.bind(self.instance, *args, **kwargs)
        else:
            arguments = signature.bind(*args, **kwargs)

        arguments.apply_defaults()
        input_dict = {}
        for param in signature.parameters:
            input_dict.update({param: arguments.arguments[param]})

        new_input_dic = self.func(**input_dict)
        if new_input_dic and not isinstance(new_input_dic, dict):
            raise TypeError(f"Return value of {self.func.__name__} should be a dict")
        if new_input_dic:
            input_dict = {**input_dict, **new_input_dic}

        if "self" in input_dict:
            input_dict.pop("self")

        if self.render == "jinja2" or self.render == "jinja":
            return format_prompt_jinja2(self.func, **input_dict)

        return format_prompt(self.func, **input_dict)

    def with_llm(self, llm):
        self.llm = llm
        return self

    def with_return_type(self, model_class: Type[Any]):
        self.model_class = model_class
        return self

    def with_extractor(self, func):
        self.extractor = func
        return self

    @staticmethod
    def is_instance_of_generator(v):
        from typing import get_origin, get_args
        import collections

        if get_origin(v) is collections.abc.Generator:
            _args = get_args(v)
            if _args == (str, type(None), type(None)):
                return True
        return False

    def to_model(self, result: str):
        json_data = {}
        if not isinstance(result, str):
            raise ValueError("The decorated function must return a string")
        try:
            # quick path for json string
            if result.startswith("```json") and result.endswith("```"):
                json_str = result[len("```json"):-len("```")]
            else:
                json_str = extract_code(result)[0][1]
            json_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"The returned string is not a valid JSON, e: {str(e)} string: {result}")

        try:
            if isinstance(json_data, list):
                return [self.model_class(**item) for item in json_data]
            return self.model_class(**json_data)
        except TypeError:
            raise TypeError("Unable to create model instance from the JSON data")

    def run(self, *args, **kwargs):
        llm = self.llm

        # if isinstance(llm, AutoLLM):
        origin_input = self.prompt(*args, **kwargs)

        conversations = [
            {"role": "system", "content": "You are a programming expert."},
            {"role": "user", "content": origin_input}
        ]

        v = llm.chat_ai(conversations)

        if self.model_class:
            return self.to_model(f"{v.output}")

        return v
        # return None


class _DescriptorPrompt:
    def __init__(self, func, wrapper, llm, render: str, check_result: bool, options: Dict[str, Any]):
        self.func = func
        self.wrapper = wrapper
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self._options = options
        self.prompt_runner = _PrompRunner(self.wrapper, None, self.llm, self.render, self.check_result,
                                          options=self._options)

    def __get__(self, instance, owner):
        if instance is None:
            return self
        else:
            return _PrompRunner(self.wrapper, instance, self.llm, self.render, self.check_result, options=self._options)

    def __call__(self, *args, **kwargs):
        return self.prompt_runner(*args, **kwargs)

    def with_llm(self, llm):
        self.llm = llm
        self.prompt_runner.with_llm(llm)
        return self

    def run(self, *args, **kwargs):
        return self.prompt_runner.run(*args, **kwargs)

    def prompt(self, *args, **kwargs):
        return self.prompt_runner.prompt(*args, **kwargs)


class prompt:
    """
    1.LLM 提示管理: 管理和执行与 LLM 相关的提示操作，提供灵活的配置选项。
    2.结果提取和转换: 支持从 LLM 返回的字符串中提取结果，并将其转换为指定模型实例。
    """
    def __init__(self, llm=None, render: str = "jinja2", check_result: bool = False,
                 options: Optional[Dict[str, Any]] = None):
        self.llm = llm
        self.render = render
        self.check_result = check_result
        self.options = options if options is not None else {}

    def __call__(self, func):
        wrapper = func
        return self._make_wrapper(func, wrapper)

    def _make_wrapper(self, func, wrapper):
        return _DescriptorPrompt(func, wrapper, self.llm, self.render, self.check_result, options=self.options)