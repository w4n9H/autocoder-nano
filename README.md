# autocoder-nano

AutoCoder 社区是一个致力于简化开发者代码开发流程，提升开发效率的社区，开发有 auto-coder.chat (lite/pro), byzerllm 等项目，
autocoder-nano 是 AutoCoder 社区的全新成员，基于 auto-coder.chat 功能简化，可以理解成 auto-coder.chat 的轻量级版本。

#### nano/lite/pro 有什么区别？

- Pro：分布式架构，支持分布式部署模型，支持开源/SaaS模型管理，独特的 `human_as_model` 模式，RAG 支持，Design 设计支持，MCP支持，联网搜索支持，全局记忆支持，适合深度使用各种大模型的用户。
- Lite：放弃分布式架构，部分功能无法使用，主要针对 Windows 用户（第三方库兼容问题），以及需要快速启动并使用 auto-coder.chat 的用户。
- Nano：同样放弃分布式架构，为 auto-coder.chat 的移植版本，支持 `/chat`，`/coding`， `/文件管理`，`/索引管理` 等功能，依赖及代码极致精简，适合想要了解大模型辅助编程原理，以及想要实现自己辅助编程框架的用户

#### 为何选择 autocoder-nano？

- 轻量高效：无需复杂部署，极致精简，即装即用，使用 auto-coder 前可以先通过 autocoder-nano 熟悉相关功能。
- 灵活扩展：第三方依赖及代码精简，非常适合学习及魔改，同时兼容主流大模型，开发者可定制私有化模型链路。
- 场景全覆盖：从代码生成到运维脚本，一站式解决开发需求。
- 开源友好：持续迭代中，欢迎贡献代码与反馈！

#### autocoder-nano 的迭代方向

- 代码结构优化，便于后续维护及其他开发者魔改
- 并发支持，开发更大的项目
- 多语言优化，深度优化 Python 外的其他语言
- 候选模型支持，首选模型异常时进行切换
- RAG能力，支持一个简化的知识库，增强代码能力

---

## 核心功能

#### 配置即服务

- 开箱即用：项目初始化向导引导配置，5 分钟即可上手。
- 动态配置：通过 `/conf` 命令实时调整项目类型，模型选择，索引策略等参数。

#### 智能代码生成

- 精准控制：通过 `/coding` 命令结合 `@文件` 或 `@@符号`，实现函数级代码生成与修改。
- 多语言支持：原生支持 Python、TypeScript/JavaScript 等语言，灵活适配混合语言项目。
- 历史上下文：使用 `/coding /apply` 将对话历史融入代码生成，确保逻辑连贯性。

#### 大模型交互与配置

- 灵活模型管理：支持 OpenAI 格式的模型接入，一键添加、删除、检测模型状态。
- 双模型策略：独立配置对话/索引模型（current_chat_model）与代码生成模型（current_code_model），满足不同场景需求。

#### 智能文件管理

- 自动/手动模式：支持自动索引构建或手动管理活动文件。
- 文件组管理：通过分组快速切换上下文，提升多模块协作效率，轻松实现前后端配合开发。

#### 自然语言编程

- 指令即代码：直接输入自然语言，自动生成并执行 Shell/Python 脚本。
- 模式切换：快捷键 Ctrl+K 快速进入自然语言模式，无缝衔接开发与运维任务。

---

## 使用场景

1. 代码维护：快速理解项目结构，生成函数级注释或单元测试。
2. 效率提升：通过自然语言指令完成文件清理、批量重命名等重复任务。
3. 混合开发：管理多语言项目，智能分析文件依赖关系。
4. 模型实验：灵活切换不同大模型，对比生成效果，找到最优配置。

---

* [安装](#安装)
* [快速开始](#快速开始)
* [模型管理](#模型管理)
* [配置管理](#配置管理)
* [文件管理](#文件管理)
* [索引管理](#索引管理)
* [Chat和Coding](#Chat和Coding)
* [自然语言模式](#自然语言模式)

---

## 安装

```shell
$ conda create --name autocoder python=3.11.9
$ conda activate autocoder
$ pip install -U autocoder_nano
```

## 快速开始

```shell
$ cd your-project
$ auto-coder.nano
```

#### step 1: 项目初始化

```
! 正在初始化系统...
! 当前目录未初始化为auto-coder项目。
  是否现在初始化项目？(y/n): y
✓ 项目初始化成功。
✓ 创建目录：/user/x/code/you-project/.auto-coder/plugins/chat-auto-coder
```

#### step 2: 配置项目语言类型

```
=== 项目类型配置 ===

项目类型支持：
  - 语言后缀（例如：.py, .java, .ts）
  - 预定义类型：py（Python）, ts（TypeScript/JavaScript）
对于混合语言项目，使用逗号分隔的值。
示例：'.java,.scala' 或 '.py,.ts'
如果留空，默认为 'py'。

请输入项目类型：py

项目类型设置为： py

您可以稍后使用以下命令更改此设置:
/conf project_type:<new_type>
```

#### step 3: 配置大模型

```
! 正在配置模型...
  设置你的首选模型名称(例如: deepseek-v3/r1, ark-deepseek-v3/r1): your-user-first-llm-custom-name
  请输入你使用模型的 Model Name: your-llm-model_name
  请输入你使用模型的 Base URL: your-llm-base-url
  请输入您的API密钥: your-llm-api-key
! 正在更新缓存...
! 正在部署 your-user-first-llm 模型...
```

#### step 4: 初始化完成, 开始与大模型交流

```
✓ 初始化完成。
AutoCoder Nano   v0.1.5
输入 /help 可以查看可用的命令.

coding@auto-coder.nano:~$ /chat 描述一下这个项目的主要功能
```


## 模型管理

#### 列出模型

```
coding@auto-coder.nano:~$ /models /list
                                  模型                                                               
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name                         ┃ Model Name          ┃ Base URL                   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ xxx-deepseek-v3              │ xxxxxxxxxxxx        │ https://xxxxx.com/api/v3   │
└──────────────────────────────┴─────────────────────┴────────────────────────────┘
```

#### 新增模型

兼容所有 OpenAI 格式的模型

- name=deepseek-r1，为新增的模型取的一个别名，可以精简，便于后续使用
- base_url=https://api.deepseek.com， 模型厂商提供的 saas api 接口
- api_key=sk-xx， 访问模型所需的key
- model=deepseek-reasoner， 模型厂商内部可能会提供多种可选的能力模型，比如 r1 / v3

```
coding@auto-coder.nano:~$ /models /add_model name=deepseek-r1 base_url=https://api.deepseek.com api_key=sk-xx model=deepseek-reasoner
2025-02-11 10:11:22.124 | INFO     | autocoder_nano.auto_coder_nano:manage_models:3788 - 正在为 deepseek-r1 更新缓存信息
2025-02-11 10:11:22.125 | INFO     | autocoder_nano.auto_coder_nano:manage_models:3797 - 正在部署 deepseek-r1 模型
coding@auto-coder.nano:~$ /models /list
                                  模型                                                               
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Name                         ┃ Model Name          ┃ Base URL                   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ xxx-deepseek-v3              │ xxxxxxxxxxxx        │ https://xxxxx.com/api/v3   │
├──────────────────────────────┼─────────────────────┼────────────────────────────┤
│ deepseek-r1                  │ deepseek-reasoner   │ https://api.deepseek.com   │
└──────────────────────────────┴─────────────────────┴────────────────────────────┘
```

#### 删除模型

```
coding@auto-coder.nano:~$ /models /remove deepseek-r1
2025-02-11 10:17:59.930 | INFO     | autocoder_nano.auto_coder_nano:manage_models:3801 - 正在清理 deepseek-r1 缓存信息
2025-02-11 10:17:59.930 | INFO     | autocoder_nano.auto_coder_nano:manage_models:3804 - 正在卸载 deepseek-r1 模型
```

#### 模型状态检测

```
coding@auto-coder.nano:~$ /models /check
2025-02-11 10:19:23.494 | INFO     | autocoder_nano.auto_coder_nano:check_models:3757 - 正在测试 xxx-deepseek-v3 模型
2025-02-11 10:19:23.495 | INFO     | autocoder_nano.auto_coder_nano:stream_chat_ai:1037 - 正在使用 xxx-deepseek-v3 模型, 模型名称 xxxxxxxxxxxx
           模型状态检测           
┏━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━┓
┃ 模型             ┃ 状态  ┃  延迟 ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━┩
│ xxx-deepseek-v3 │  ✓   │ 1.36s │
└─────────────────┴──────┴───────┘
```

## 配置管理

#### 列出配置

```
coding@auto-coder.nano:~$ /conf
             使用 /conf <key>:<value> 修改这些设置                                              
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                            键 ┃ 值                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│                    auto_merge │ editblock                    │
├───────────────────────────────┼──────────────────────────────┤
│            current_chat_model │ xxx-deepseek-v3              │
├───────────────────────────────┼──────────────────────────────┤
│            current_code_model │ xxx-deepseek-v3              │
├───────────────────────────────┼──────────────────────────────┤
│                  project_type │ py                           │
├───────────────────────────────┼──────────────────────────────┤
│              skip_build_index │ false                        │
└───────────────────────────────┴──────────────────────────────┘
```

#### 更改配置

```
coding@auto-coder.nano:~$ /conf skip_filter_index:false
Set skip_filter_index to false
coding@auto-coder.nano:~$ /conf index_filter_level:2
Set index_filter_level to 2
```

#### 配置当前使用模型

当你新增某个模型后，想要进行替换使用，假设你的模型别名为 _t-deepseek-r1_ ， 使用以下命令进行模型配置更改：

```shell
coding@auto-coder.nano:~$ /conf current_chat_model:t-deepseek-r1
Set current_chat_model to t-deepseek-r1
coding@auto-coder.nano:~$ /conf current_code_model:t-deepseek-r1
Set current_code_model to t-deepseek-r1
```

- current_chat_model ：配置与大模型聊天以及索引生成所使用的模型
- current_code_model ：配置代码生成使用的模型


## 文件管理

Auto-coder 里有两种方式管理你的项目上下文：

1. 设置 `/conf skip_index_build:false` 后，系统会自动根据你的需求自动查找相关文件。即自动管理模式。
2. 当你设置 `/conf skip_index_build:true` 后，则通过活动文件来管理，我们提供了 `/add_files /remove_files /list_files` 来组合。即手动管理模式。

Auto-coder 文件组概念：

1. Auto-coder 系列提供了一个活动文件组的概念。 你可以通过 `/add_files /group /add app`  来添加一个叫 app的组，这个组会复制当前的所有活动文件。
2. 通过手动切换文件组来完成上下文的管理，是手动管理文件的高级方法


#### /list_files 命令

```shell
# 列出当前活跃文件
coding@auto-coder.nano:~$ /list_files
```

#### /add_files 命令

```shell
# 添加单个/多个文件为活跃文件
coding@auto-coder.nano:~$ /add_files file1 file2 file3
coding@auto-coder.nano:~$ /add_files /path/abc/file4 /path/abc/file5

# 查看当前所有的文件组
coding@auto-coder.nano:~$ /add_files /group

# 将当前活跃文件添加进 app 文件组
coding@auto-coder.nano:~$ /add_files /group /add app

# 设置活跃文件组
coding@auto-coder.nano:~$ /add_files /group app

# 删除文件组
coding@auto-coder.nano:~$ /add_files /group /drop app

# 合并两个文件组的文件为当前活跃文件
coding@auto-coder.nano:~$ /add_files /group <groupname>,<groupname>

# 当目录中新增一个文件后，自动补全无法获取该文件，可执行一次刷新
coding@auto-coder.nano:~$ /add_files /refresh
```

- `/add_files` 支持文件匹配符，比如可以通过 `/add_files ./**/*.py` 把当前目录下所有的python文件加到活动文件里去(如果你项目很大，不能这么做，会超出大模型上线文限制)。


#### /remove_files 命令

```shell
# 将 file1 移出当前活跃文件
coding@auto-coder.nano:~$ /remove_files file1

# 清空当前所有活跃文件
coding@auto-coder.nano:~$ /remove_files /all
```


## 索引管理


## Chat和Coding

Chat与大模型沟通

- 当你设置了活跃文件和 `/conf skip_index_build:true` ， `/chat` 可以方便的针对当前活跃文件进行提问
- 当你设置了 `/conf skip_index_build:false` ， `/chat` 会根据所有代码文件来回答问题

```shell
coding@auto-coder.nano:~$ /add_files ./**/*.py

coding@auto-coder.nano:~$ /list_files

coding@auto-coder.nano:~$ /chat 请问这些文件之间的关系是什么
coding@auto-coder.nano:~$ /chat 给我描述一下这个项目的用途
```


Coding使用大模型进行编码

- `/coding` 可以根据需求，对当前活跃文件，或者自行匹配候选文件，进行修改
- `/coding /apply` 此时 Autocoder 会把我们与大模型之间的历史对话记录加入到代码生成的 Prompt 里

```shell
coding@auto-coder.nano:~$ /coding /apply 新增一个命令行参数 --chat_model
```

#### 精准控制代码生成

Autocoder 提供了两个机制：
1. 使用 `@` 自动补全文件
2. 使用 `@@` 自动补全符号（类或者函数）

在 `/coding` 或者 `/chat` 的时候，用户可以通过上述两个语法快速定位到某个文件，类或者函数，然后最小粒度是函数级别，
让 Autocoder 帮你做修改。比如你 @@函数A， 然后让大模型自动实现该函数或者让大模型给该函数生成测试


## 自然语言模式

场景：实际编程的过程中，程序员会大量使用命令行来完成一些工作

- 比如启动一个服务，发现服务端口被占用，这个时候你可能想查看这个端口到底被哪个其他服务占用
- 想要对目录中的 .jpg 文件进行批量改名
- 再或者突然忘记某个命令的参数

切换自然语言模式

使用 Ctrl + k 快捷键，或者以下方式可切换模式

```shell
coding@auto-coder.nano:~$ /mode auto_detect
```

放终端最下方显示 `当前模式: 自然语言模式 (ctl+k 切换模式)` 即切换成功

```
coding@auto-coder.nano:~$ 递归删除当前项目所有 __pycache__ 目录
╭────────────────────────────────────────────────────────── 命令生成 ─────────╮
│ 正在根据用户输入 递归删除当前项目所有 __pycache__ 目录 生成 Shell 脚本...          │
╰────────────────────────────────────────────────────────────────────────────╯
2025-02-11 15:02:31.305 | INFO     | autocoder_nano.auto_coder_nano:chat_ai:1057 - 正在使用 ark-deepseek-v3 模型, 模型名称 ep-20250205104003-d8hqb
╭───────────────────────────────────────────────────────── Shell 脚本 ──────────────────────╮
│ #!/bin/bash                                                                              │
│                                                                                          │
│ # 递归删除当前项目所有 __pycache__ 目录的脚本                                                 │
│                                                                                          │
│ # 使用 find 命令查找当前目录及其子目录中的所有 __pycache__ 目录                                  │
│ # -type d: 只查找目录                                                                      │
│ # -name "__pycache__": 匹配名为 __pycache__ 的目录                                          │
│ # -exec rm -rf {} +: 对找到的每个目录执行 rm -rf 命令，递归删除目录及其内容                      │
│ # 使用 {} + 而不是 {} \; 是为了将多个结果一次性传递给 rm 命令，提高效率                           │
│                                                                                          │
│ find . -type d -name "__pycache__" -exec rm -rf {} +                                      │
│                                                                                          │
│ # 提示用户操作完成                                                                          │
│ echo "所有 __pycache__ 目录已成功删除。"                                                     │
╰───────────────────────────────────────────────────────────────────────────────────────────╯
是否要执行此脚本? (y/n) n
```




