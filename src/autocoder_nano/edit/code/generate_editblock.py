from autocoder_nano.core import AutoLLM
from autocoder_nano.core import prompt
from autocoder_nano.actypes import AutoCoderArgs, CodeGenerateResult


class CodeAutoGenerateEditBlock:
    def __init__(self, args: AutoCoderArgs, llm: AutoLLM, action=None):
        self.llm = llm
        self.args = args
        self.action = action
        if not self.llm:
            raise ValueError("Please provide a valid model instance to use for code generation.")
        self.llms = [self.llm]

    @prompt()
    def single_round_instruction(self, instruction: str, content: str, context: str = ""):
        """
        如果你需要生成代码，对于每个需要更改的文件,你需要按 *SEARCH/REPLACE block* 的格式进行生成。

        # *SEARCH/REPLACE block* Rules:

        Every *SEARCH/REPLACE block* must use this format:
        1. The opening fence and code language, eg: ```python
        2. The file path alone on a line, starting with "##File:" and verbatim. No bold asterisks, no quotes around it,
        no escaping of characters, etc.
        3. The start of search block: <<<<<<< SEARCH
        4. A contiguous chunk of lines to search for in the existing source code
        5. The dividing line: =======
        6. The lines to replace into the source code
        7. The end of the replacement block: >>>>>>> REPLACE
        8. The closing fence: ```

        Every *SEARCH* section must *EXACTLY MATCH* the existing source code, character for character,
        including all comments, docstrings, etc.

        *SEARCH/REPLACE* blocks will replace *all* matching occurrences.
        Include enough lines to make the SEARCH blocks unique.

        Include *ALL* the code being searched and replaced!

        To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it from its current location,
        1 to insert it in the new location.

        If you want to put code in a new file, use a *SEARCH/REPLACE block* with:
        - A new file path, including dir name if needed
        - An empty `SEARCH` section
        - The new file's contents in the `REPLACE` section

        ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

        下面我们来看一个例子：

        当前项目目录结构：
        1. 项目根目录： /tmp/projects/mathweb
        2. 项目子目录/文件列表(类似tree 命令输出)
        flask/
            app.py
            templates/
                index.html
            static/
                style.css

        用户需求： Change get_factorial() to use math.factorial

        回答： To make this change we need to modify `/tmp/projects/mathweb/flask/app.py` to:

        1. Import the math package.
        2. Remove the existing factorial() function.
        3. Update get_factorial() to call math.factorial instead.

        Here are the *SEARCH/REPLACE* blocks:

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        from flask import Flask
        =======
        import math
        from flask import Flask
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        def factorial(n):
            "compute factorial"

            if n == 0:
                return 1
            else:
                return n * factorial(n-1)

        =======
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
            return str(factorial(n))
        =======
            return str(math.factorial(n))
        >>>>>>> REPLACE
        ```

        用户需求： Refactor hello() into its own file.

        回答：To make this change we need to modify `main.py` and make a new file `hello.py`:

        1. Make a new hello.py file with hello() in it.
        2. Remove hello() from main.py and replace it with an import.

        Here are the *SEARCH/REPLACE* blocks:

        ```python
        ##File: /tmp/projects/mathweb/hello.py
        <<<<<<< SEARCH
        =======
        def hello():
            "print a greeting"

            print("hello")
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/main.py
        <<<<<<< SEARCH
        def hello():
            "print a greeting"

            print("hello")
        =======
        from hello import hello
        >>>>>>> REPLACE
        ```

        现在让我们开始一个新的任务:

        {%- if structure %}
        {{ structure }}
        {%- endif %}

        {%- if content %}
        下面是一些文件路径以及每个文件对应的源码：
        <files>
        {{ content }}
        </files>
        {%- endif %}

        {%- if context %}
        <extra_context>
        {{ context }}
        </extra_context>
        {%- endif %}

        下面是用户的需求：

        {{ instruction }}

        """

    @prompt()
    def auto_implement_function(self, instruction: str, content: str) -> str:
        """
        下面是一些文件路径以及每个文件对应的源码：

        {{ content }}

        请参考上面的内容，重新实现所有文件下方法体标记了如下内容的方法：

        ```python
        raise NotImplementedError("This function should be implemented by the model.")
        ```

        {{ instruction }}

        """

    def single_round_run(self, query: str, source_content: str) -> CodeGenerateResult:
        init_prompt = ''
        if self.args.template == "common":
            init_prompt = self.single_round_instruction.prompt(
                instruction=query, content=source_content, context=self.args.context
            )
        elif self.args.template == "auto_implement":
            init_prompt = self.auto_implement_function.prompt(
                instruction=query, content=source_content
            )

        with open(self.args.target_file, "w") as file:
            file.write(init_prompt)

        conversations = [{"role": "user", "content": init_prompt}]

        conversations_list = []
        results = []

        for llm in self.llms:
            v = llm.chat_ai(conversations=conversations, model=self.args.code_model)
            results.append(v.output)
        for result in results:
            conversations_list.append(conversations + [{"role": "assistant", "content": result}])

        return CodeGenerateResult(contents=results, conversations=conversations_list)

    @prompt()
    def multi_round_instruction(self, instruction: str, content: str, context: str = "") -> str:
        """
        如果你需要生成代码，对于每个需要更改的文件,你需要按 *SEARCH/REPLACE block* 的格式进行生成。

        # *SEARCH/REPLACE block* Rules:

        Every *SEARCH/REPLACE block* must use this format:
        1. The opening fence and code language, eg: ```python
        2. The file path alone on a line, starting with "##File:" and verbatim. No bold asterisks, no quotes around it,
        no escaping of characters, etc.
        3. The start of search block: <<<<<<< SEARCH
        4. A contiguous chunk of lines to search for in the existing source code
        5. The dividing line: =======
        6. The lines to replace into the source code
        7. The end of the replacement block: >>>>>>> REPLACE
        8. The closing fence: ```

        Every *SEARCH* section must *EXACTLY MATCH* the existing source code, character for character,
        including all comments, docstrings, etc.

        *SEARCH/REPLACE* blocks will replace *all* matching occurrences.
        Include enough lines to make the SEARCH blocks unique.

        Include *ALL* the code being searched and replaced!

        To move code within a file, use 2 *SEARCH/REPLACE* blocks: 1 to delete it from its current location,
        1 to insert it in the new location.

        If you want to put code in a new file, use a *SEARCH/REPLACE block* with:
        - A new file path, including dir name if needed
        - An empty `SEARCH` section
        - The new file's contents in the `REPLACE` section

        ONLY EVER RETURN CODE IN A *SEARCH/REPLACE BLOCK*!

        下面我们来看一个例子：

        当前项目目录结构：
        1. 项目根目录： /tmp/projects/mathweb
        2. 项目子目录/文件列表(类似tree 命令输出)
        flask/
            app.py
            templates/
                index.html
            static/
                style.css

        用户需求： Change get_factorial() to use math.factorial

        回答： To make this change we need to modify `/tmp/projects/mathweb/flask/app.py` to:

        1. Import the math package.
        2. Remove the existing factorial() function.
        3. Update get_factorial() to call math.factorial instead.

        Here are the *SEARCH/REPLACE* blocks:

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        from flask import Flask
        =======
        import math
        from flask import Flask
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
        def factorial(n):
            "compute factorial"

            if n == 0:
                return 1
            else:
                return n * factorial(n-1)

        =======
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/flask/app.py
        <<<<<<< SEARCH
            return str(factorial(n))
        =======
            return str(math.factorial(n))
        >>>>>>> REPLACE
        ```

        用户需求： Refactor hello() into its own file.

        回答：To make this change we need to modify `main.py` and make a new file `hello.py`:

        1. Make a new hello.py file with hello() in it.
        2. Remove hello() from main.py and replace it with an import.

        Here are the *SEARCH/REPLACE* blocks:


        ```python
        ##File: /tmp/projects/mathweb/hello.py
        <<<<<<< SEARCH
        =======
        def hello():
            "print a greeting"

            print("hello")
        >>>>>>> REPLACE
        ```

        ```python
        ##File: /tmp/projects/mathweb/main.py
        <<<<<<< SEARCH
        def hello():
            "print a greeting"

            print("hello")
        =======
        from hello import hello
        >>>>>>> REPLACE
        ```

        现在让我们开始一个新的任务:

        {%- if structure %}
        {{ structure }}
        {%- endif %}

        {%- if content %}
        下面是一些文件路径以及每个文件对应的源码：
        <files>
        {{ content }}
        </files>
        {%- endif %}

        {%- if context %}
        <extra_context>
        {{ context }}
        </extra_context>
        {%- endif %}

        下面是用户的需求：

        {{ instruction }}

        每次生成一个文件的*SEARCH/REPLACE* blocks，然后询问我是否继续，当我回复继续，
        继续生成下一个文件的*SEARCH/REPLACE* blocks。当没有后续任务时，请回复 "__完成__" 或者 "__EOF__"。
        """

    def multi_round_run(self, query: str, source_content: str, max_steps: int = 3) -> CodeGenerateResult:
        init_prompt = ''
        if self.args.template == "common":
            init_prompt = self.multi_round_instruction.prompt(
                instruction=query, content=source_content, context=self.args.context
            )
        elif self.args.template == "auto_implement":
            init_prompt = self.auto_implement_function.prompt(
                instruction=query, content=source_content
            )

        with open(self.args.target_file, "w") as file:
            file.write(init_prompt)

        results = []
        conversations = [{"role": "user", "content": init_prompt}]

        code_llm = self.llms[0]
        v = code_llm.chat_ai(conversations=conversations, model=self.args.code_model)
        results.append(v.output)

        conversations.append({"role": "assistant", "content": v.output})

        if "__完成__" in v.output or "/done" in v.output or "__EOF__" in v.output:
            return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])

        current_step = 0

        while current_step < max_steps:
            conversations.append({"role": "user", "content": "继续"})

            with open(self.args.target_file, "w") as file:
                file.write("继续")

            t = code_llm.chat_ai(conversations=conversations, model=self.args.code_model)

            results.append(t.output)
            conversations.append({"role": "assistant", "content": t.output})
            current_step += 1

            if "__完成__" in t.output or "/done" in t.output or "__EOF__" in t.output:
                return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])

        return CodeGenerateResult(contents=["\n\n".join(results)], conversations=[conversations])