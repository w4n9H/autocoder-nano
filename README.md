## 概述

AutoCoder Nano 是一款轻量级的编码助手, 利用大型语言模型（LLMs）帮助开发者编写, 理解和修改代码。

它提供了一个功能丰富的交互式命令行界面，支持在软件开发场景中与LLMs互动，具备代码生成、Agent模式、文件管理、索引检索、RAG知识库、规则系统、Git集成等全方位功能。

本概述介绍了 AutoCoder Nano 的用途, 架构和核心组件。如需了解更多子系统的详细信息，请参阅相关页面，例如

- 命令行界面
- LLM集成
- Agent系统
- 索引与检索系统
- RAG知识库系统

### 1.什么是 AutoCoder Nano？

AutoCoder Nano 是 Auto-Coder 生态系统的简化版本，设计轻量且依赖极少。它旨在通过提供增强AI功能的命令行界面，弥合自然语言指令与代码修改之间的鸿沟，为开发者提供全方位的AI辅助编程体验。
 
Auto-Coder 主社区[点击跳转](https://github.com/allwefantasy/auto-coder)

**AutoCoder Nano 的主要特点：**

- **轻量级**：依赖极少，代码库精简，部署简单
- **交互式CLI**：支持自动补全、历史记录、快捷键的智能命令行界面
- **AI驱动**：集成多种大型语言模型，支持模型管理和切换
- **上下文感知**：利用文件索引和RAG检索实现精准的上下文理解
- **Agent模式**：智能Agent支持复杂任务的自动化处理
- **多功能集成**：文件管理、代码生成、Git操作、规则系统一体化
- **多语言支持**：支持Python、TypeScript/JavaScript等多种编程语言
- **会话管理**：支持会话持久化、上下文切换和长文本处理
- **知识库集成**：RAG文档检索增强代码理解和生成能力
- **规则引擎**：基于代码分析自动生成设计模式和最佳实践

**nano/lite/pro 有什么区别？**

- **Pro**：分布式架构，支持分布式部署模型，支持开源/SaaS模型管理，独特的 `human_as_model` 模式，完整的RAG支持，Design设计支持，MCP支持，联网搜索支持，全局记忆支持，适合企业级和深度使用各种大模型的用户。
- **Lite**：单机架构，简化部分高级功能，主要针对Windows用户（第三方库兼容问题优化），以及需要快速启动并使用auto-coder.chat的用户。
- **Nano**：极致轻量的单机架构，auto-coder.chat的移植版本，支持完整的`/chat`、`/coding`、`文件管理`、`索引管理`、`Agent模式`、`RAG检索`、`规则系统`、`Git集成`等功能，依赖及代码极致精简，适合想要了解大模型辅助编程原理，以及想要实现自己辅助编程框架的开发者。

**autocoder-nano 的核心竞争力：**

- **完整功能栈**：在轻量级设计中提供了企业级工具的核心功能
- **Agent智能**：内置智能Agent系统，支持复杂任务的自动分解和执行
- **知识增强**：RAG文档检索与代码索引双重知识源
- **规则引擎**：自动识别和生成项目的设计模式和最佳实践
- **Git集成**：无缝的版本控制集成，支持智能提交和回滚
- **多模型支持**：灵活的模型管理系统，支持多供应商和故障切换
- **会话持久化**：智能的上下文管理和长文本处理能力

**autocoder-nano 的迭代方向：**

- 代码结构优化，便于后续维护及二次开发
- 并发支持，支持大型项目和并行处理
- 多语言优化，深度优化Python、Java、Go等其他语言支持
- 候选模型支持，实现模型故障自动切换和负载均衡
- RAG能力增强，支持更丰富的知识库类型和检索策略
- Agent能力扩展，支持更复杂的任务规划和执行
- 插件系统，支持第三方功能扩展

### 2.系统架构

AutoCoder Nano 采用模块化架构，以命令行界面为核心，连接多个功能子系统，形成一个完整的AI辅助开发生态。

#### 2.1.系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    AutoCoder Nano 架构                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────┐    │
│  │  命令行界面   │◄──►│   内存系统     │◄──►│  配置管理     │    │
│  │    (CLI)    │    │  (Memory)    │    │ (Config)    │    │
│  └─────────────┘    └──────────────┘    └─────────────┘    │
│         │                   │                   │           │
│         ▼                   ▼                   ▼           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    核心功能层                        │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │ 文件管理  │ │ 对话系统  │ │ 代码生成  │ │Agent系统│ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │ 索引检索  │ │ RAG知识库 │ │ 规则引擎  │ │Git集成 │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │    │
│  └─────────────────────────────────────────────────────┘    │
│         │                   │                   │           │
│         ▼                   ▼                   ▼           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                    LLM集成层                         │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │ 模型管理  │ │ API通信  │ │ 响应处理  │ │ Token管理│ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │    │
│  └─────────────────────────────────────────────────────┘    │
│                             │                           │
│                             ▼                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                   外部服务层                         │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │OpenAI API│ │本地模型   │ │ 文档存储  │ │Git仓库 │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

#### 2.2.数据流架构

```
用户输入 → CLI解析 → 功能路由 → 上下文收集 → LLM处理 → 响应生成 → 结果应用
    │           │          │           │          │           │          │
    ▼           ▼          ▼           ▼          ▼           ▼          ▼
命令识别 → 参数解析 → 模块调用 → 文件/索引/RAG → AI推理 → 代码/文本 → 文件修改/显示
```

### 3.核心组件

#### 3.1.命令行界面（CLI）

CLI 是用户与 AutoCoder Nano 交互的主要入口，负责解析用户命令, 提供自动补全并显示响应。

主要功能：

- 命令解析与补全 
- 文件和符号建议 
- 响应内容的富文本渲染 
- 交互式会话管理

CLI 支持多种命令类别：

| 命令类别     | 示例命令                                         | 用途                  |
|----------|----------------------------------------------|---------------------|
| **核心功能** | `/auto`, `/coding`, `/chat`                  | Agent模式、代码生成、AI对话 |
| **文件管理** | `/add_files`, `/remove_files`, `/list_files` | 管理当前上下文中的活动文件       |
| **配置**   | `/conf`                                      | 配置系统设置和行为           |
| **模型管理** | `/models /list`, `/models /add`, `/models /check` | 管理LLM集成设置           |
| **索引**   | `/index /code`, `/index /rag`                | 构建代码索引和RAG索引         |
| **规则**   | `/rules`                                     | 生成和管理项目规则           |
| **Git**   | `/git /commit`, `/git /revert`               | 代码提交和撤销             |
| **帮助**   | `/help`, `/exit`                             | 获取帮助或退出应用           |

**完整命令列表：**

```
支持的命令：
  命令                - 描述
  /auto <query>       - 使用Agent完成你的任务
      /auto /new <query>      - 创建一个新的会话来完成任务
      /auto /resume <query>   - 使用历史会话来继续完成任务
  /chat <query>       - 与AI聊天，获取关于当前活动文件的见解
      /chat /new <query>      - 开启一个新的AI会话,此时历史沟通记录会移除
      /chat /history          - 显示你与AI最近几条沟通记录
  /coding <query>     - 根据需求请求AI修改当前活动文件代码
      /coding /apply <query>  - 会带上/chat历史记录与AI沟通
  /help               - 显示此帮助消息
  /models <subcommand> - 管理LLM模型(/models /list查看,/models /add添加)
      /models /list           - 列出所有部署模型
      /models /add            - 添加新的模型
      /models /check          - 检查所有部署模型的可用性
  /conf <key>:<value> - 使用/conf <args>:<type>设置你的AutoCoder配置
  /index              - 与索引相关的操作
      /index /code            - 触发构建项目代码索引
      /index /rag             - 为/conf rag_url:<local_path> 设置的目录构建RAG索引
  /git                - 与Git相关的操作
      /git /revert            - 撤销上次由 /auto 或 /coding 提交的代码
      /git /commit            - 根据用户人工修改的代码自动生成yaml文件并提交更改
  /rules              - 基于当前活动文件或者Commit变更生成功能模式和设计模式
  /add_files <file1> <file2> ... - 将文件添加到当前会话
      /add_files /refresh     - 刷新文件，用于新增文件后但是通过/add_files无法添加时
  /list_files         - 列出当前会话中的所有活跃文件
  /remove_files <file1>,<file2> ... - 从当前会话中移除文件
      /remove_files /all      - 移除当前会话中的全部活跃文件
  /exclude_dirs <dir1>,<dir2> ... - 添加要从项目中排除的目录
  /exclude_files <pattern>/<subcommand> - 排除文件(/exclude_files /list查看,/exclude_files /drop删除)
  /exit               - 退出程序
```

**命令精简说明：**

> **版本更新说明：** 为简化命令体系，近期对命令进行了以下精简：
> - 移除 `/mode`、`/shell`、`/editor`、`/context` 命令
> - `/rag/build`、`/index/build` 合并为 `/index`
> - `/revert`、`/commit` 合并为 `/git`
> - 新增 `/auto /new`、`/auto /resume` 用于Agent会话管理
> - 新增 `/index /code`、`/index /rag` 分别处理代码索引和RAG索引
> - 新增 `/chat /history` 用于查看聊天记录


#### 3.2.内存系统

AutoCoder Nano 使用内存字典存储以下状态：

- 对话历史, 即与大模型 `/chat` 的历史
- 活动文件及文件组 
- 配置设置 
- 模型配置 
- 目录排除设置

```python
memory = {
    "conversation": [],  # 对话历史
    "current_files": {"files": [], "groups": {}},  # 文件管理
    "conf": {  # 配置设置
        "auto_merge": "editblock",
        "chat_model": "",
        "code_model": "",
    },
    "exclude_dirs": [],  # 目录排除设置
    "mode": "normal",  # 新增mode字段,默认为normal模式
    "models": {}  # 模型配置 
}
```

内存系统支持会话间持久化，确保复杂项目的连续性。


#### 3.3.项目管理

AutoCoder Nano 支持多种项目类型, 并提供针对性支持:

- Python项目: 处理模块、导入和结构 
- TypeScript项目: 支持TypeScript/JavaScript文件及依赖 
- 自定义项目: 基于文件扩展名的通用支持

项目管理子系统负责理解代码库结构, 识别相关文件, 并为LLM提供适当的上下文。

#### 3.4.LLM集成

LLM集成子系统通过以下方式连接 AutoCoder Nano 与多种大型语言模型：

- 模型配置与选择 
- API通信 
- 响应处理 
- Token管理

AutoCoder Nano 支持为聊天/索引和代码生成配置不同模型，以优化任务性能。


### 4.用户工作流

#### 4.1.项目初始化与配置

1. 通过 `/chat` 询问有关代码的问题。 
2. 对于现有项目，配置项目语言（`/conf project_type:py`） 
3. 配置大语言模型（`/models /add_model`）后 
4. 即可使用 `/coding` 生成修改代码
5. `/coding /apply` 使用聊天历史记录
6. `/index` 管理代码索引和RAG索引
7. `/models` 配置模型。

#### 4.2.代码生成流程

AutoCoder Nano 的代码生成流程如下：

- 用户通过 `/coding` [请求] 发起代码生成请求 
- 系统从活动文件中收集上下文 or 通过索引自动获取上下文
- 将上下文和请求发送至配置的LLM 
- 生成的代码呈现给用户 
- 修改可应用于代码库 
- 可选的Git集成支持版本控制

### 5.关键特性

#### 5.1.文件管理

文件管理包括：

- 查找符合特定模式的文件 
- 从处理中排除指定目录和文件 
- 计算文件哈希以检测变更

AutoCoder Nano 提供两种文件管理方式：

- 自动模式: 系统根据查询自动识别相关文件 
- 手动模式: 用户显式管理活动文件

文件分组功能允许用户为特定任务组织相关文件:

```bash
coding@auto-coder.nano:~$ /add_files /group /add frontend  
coding@auto-coder.nano:~$ /add_files /group /add backend  
coding@auto-coder.nano:~$ /add_files /group frontend  
```

排除目录和文件：

```bash
# 排除目录
/exclude_dirs node_modules,build,dist

# 排除文件模式
/exclude_files "*.log,*.tmp"

# 查看排除的文件列表
/exclude_files /list

# 删除排除模式
/exclude_files /drop "*.log"
```

#### 5.2.代码索引与检索

AutoCoder Nano 构建并维护项目中代码实体的索引：

- 提取函数、类和变量并建立索引 
- 查询可以检索相关的代码实体 
- 识别相关文件以提供更好的上下文 
- 索引系统有助于更有针对性和高效地理解和生成代码

```bash
# 构建项目代码索引
/index /code

# 构建RAG文档索引
/conf rag_url:/path/to/docs
/index /rag
```

#### 5.3.RAG文档检索

支持本地文档的检索增强生成：

```bash
# 配置RAG文档目录
/conf rag_url:/path/to/docs

# 构建RAG索引
/index /rag

# 查询RAG文档（通过/chat命令配合使用）
/chat 基于RAG文档回答我的问题
```

#### 5.4.Agent模式

提供智能Agent模式处理复杂任务：

```bash
# 使用Agent完成任务
/auto <query>

# 创建新Agent会话
/auto /new <query>

# 恢复Agent会话
/auto /resume <query>
```

#### 5.5.Git集成

无缝的版本控制集成：

```bash
# 撤销上次由 /auto 或 /coding 提交的代码
/git /revert

# 根据用户人工修改的代码自动生成yaml文件并提交更改
/git /commit
```

#### 5.6.规则系统

基于代码分析生成功能模式和设计模式：

```bash
# 分析当前文件生成规则
/rules /analyze

# 查看规则文件
/rules /show

# 重置规则文件
/rules /clear
```

### 6.安装与设置

#### 6.1.系统要求

在安装 AutoCoder Nano 之前，请确保你的系统满足以下条件：
 
- Python 3.10 或更高版本（推荐 Python 3.11.9 ）
- 操作系统：Windows、macOS 或 Linux
- 至少能访问一个与 OpenAI API 格式兼容的大语言模型服务

#### 6.2.安装方法

使用 pip(推荐): 推荐的安装方式是在专用虚拟环境中使用 pip 进行安装

```shell
# 创建conda环境
conda create --name autocoder python=3.11.9
# 激活环境
conda activate autocoder
# 安装AutoCoder Nano
pip install -U autocoder-nano
```

从源代码安装

```shell
# 克隆仓库  
git clone https://github.com/w4n9H/autocoder-nano.git 
# 进入项目目录  
cd autocoder-nano  
# 安装依赖  
pip install -r requirements.txt
# 以开发模式安装  
pip install -e .
```

安装完成后，AutoCoder Nano 提供以下主要命令行工具：  

| 命令                  | 描述                           |  
|---------------------|------------------------------|  
| auto-coder.nano     | 代码生成和聊天交互的主界面                |  


#### 6.3.项目初始化  

安装完成后，需要为项目初始化 AutoCoder Nano。设置过程包括项目初始化、语言配置和 LLM 模型配置。  
进入项目目录并运行 AutoCoder Nano：  

```bash  
cd your-project  
auto-coder.nano
```  

首次运行时，系统会检测到当前目录未初始化，并提示初始化：  

```  
! 正在初始化系统...  
! 当前目录未初始化为 auto-coder 项目。  
  是否现在初始化项目？(y/n)：y  
✓ 项目初始化成功。  
✓ 创建目录：/your-project/.auto-coder/plugins/chat-auto-coder  
```

> 这将在项目文件夹中创建一个 `.auto-coder` 目录，用于存储配置和索引文件。


#### 6.4.项目类型配置  

初始化后，系统会提示配置项目类型：  

```  
=== 项目类型配置 ===  

项目类型支持：  
- 语言后缀（例如：.py, .java, .ts）  
- 预定义类型：py (Python)，ts (TypeScript/JavaScript)  
对于混合语言项目，使用逗号分隔的值。  
示例：'.java, .scala' 或 '.py, .ts'  
如果留空，默认为 'py'。  

请输入项目类型：py  

项目类型设置为：py  

您可以稍后使用以下命令更改此设置：  
/conf project_type:=new_type>  
```

支持的项目类型包括：  

* `py` - Python 项目  
* `ts` - TypeScript/JavaScript 项目  
* 自定义文件扩展名（例如 `.py,.ts,.go` 用于混合项目）

#### 6.5.LLM 配置

#### 6.6.配置管理  

初始设置完成后，可以使用 `/conf` 命令查看和修改配置：

```bash  
coding@auto-coder.nano:~$ /conf  
    使用 /conf <key>:<value> 修改这些设置  

| 键                | 值            |  
|-------------------|---------------|  
| auto_merge        | editblock     |  
| chat_model        | model-name    |  
| code_model        | model-name    |  
| project_type      | py            |  
| skip_build_index  | false         |  
```

**常用配置项：**

```bash
# 更改项目类型为 TypeScript  
/conf project_type:ts  

# 更改代码生成模型  
/conf code_model:deepseek-r1

# 设置RAG文档路径
/conf rag_url:/path/to/docs

# 删除配置项
/conf /drop <key>
```

#### 6.7.LLM 管理  

AutoCoder Nano 需要至少一个配置好的 LLM 才能运行。可以使用 `/models` 命令管理 LLM：  

**列出可用模型**

```bash  
/models /list  
```  

**添加新模型**

```bash  
/models /add_model name=model-alias base_url=https://api.provider.com api_key=sk-xxxx model=provider-model-name  
```

参数：

- `name`：模型的别名（例如 `deepseek-r1`）  
- `base_url`：API 端点（例如 `https://api.deepseek.com`）  
- `api_key`：API 密钥  
- `model`：服务商指定的具体模型名称

**移除模型**  

```bash  
/models /remove model-alias  
```  

**测试模型连接**  

```bash  
/models /check  
```  

测试所有配置的模型并报告状态：  

```  
模型状态检测  
模型         | 状态  | 延迟   |  
deepseek-v3 | ✓     | 1.36s  |  
```

#### 6.8.验证与下一步  

安装和设置完成后，会看到以下消息：  

```  
✓ 初始化完成。  
AutoCoder Nano v0.1.5  
输入 /help 可以查看可用的命令。  

coding@auto-coder.nano:~$  
```  

此时可以：  

1. 使用 `/chat` 提问关于代码库的问题  
2. 使用 `/coding` 生成或修改代码  
3. 使用 `/add_files`、`/remove_files` 等命令管理文件  
4. 使用 `/help` 获取帮助


### 7.使用示例

#### 7.1 基本使用流程

```bash
# 1. 启动AutoCoder Nano
auto-coder.nano

# 2. 配置模型
/models /add_model name=deepseek base_url=https://api.deepseek.com api_key=sk-xxx model=deepseek-coder

# 3. 设置首选模型
/conf chat_model:deepseek
/conf code_model:deepseek

# 4. 添加文件到会话
/add_files src/main.py

# 5. 聊天询问
/chat 这个文件的主要功能是什么？

# 6. 代码修改
/coding 添加错误处理逻辑

# 7. 提交更改
/git /commit
```

#### 7.2 文件组和排除管理

```bash
# 创建文件组
/add_files src/utils.py src/config.py
/add_files /group /add utils

# 使用文件组
/add_files /group utils

# 排除目录
/exclude_dirs __pycache__,node_modules,.git

# 排除文件
/exclude_files "*.log,*.tmp"
```

#### 7.3 Agent模式使用

```bash
# 使用Agent完成复杂任务
/auto 重构这个模块，使其支持异步操作

# 创建新的Agent会话
/auto /new 重构用户认证模块

# 恢复之前的Agent会话
/auto /resume 继续上次的重构任务
```

#### 7.4 索引和RAG使用

```bash
# 构建项目代码索引
/index /code

# 配置和构建RAG
/conf rag_url:/path/to/docs
/index /rag

# 查看聊天记录
/chat /history

# 使用聊天历史记录进行代码修改
/coding /apply 基于之前的讨论添加日志
```

#### 7.5 规则系统使用

```bash
# 生成项目规则
/rules /analyze

# 查看规则
/rules /show

# 重置规则文件
/rules /clear
```

### 8.故障排除

#### 8.1 常见问题

**1. 模型连接失败**
```bash
# 检查模型状态
/models /check

# 重新配置模型
/models /add_model name=<name> base_url=<url> api_key=<key> model=<model>
```

**2. 索引构建失败**
```bash
# 跳过索引构建
/conf skip_build_index:true
```

**3. 文件未找到**
```bash
# 检查排除列表
/exclude_dirs  # 查看排除的目录
/exclude_files /list  # 查看排除的文件模式

# 刷新文件列表
/add_files /refresh
```

#### 8.2 调试模式与启动选项

```bash
# 启用调试模式
auto-coder.nano --debug

# 跳过系统初始化（快速启动）
auto-coder.nano --quick

# 直接执行Agent指令
auto-coder.nano --agent "你的任务描述"
```

**启动选项说明：**

- `--debug`: 启用调试模式，在出现异常时会显示详细的错误堆栈信息，便于问题排查

- `--quick`: 快速启动模式，跳过项目初始化检查。适用于：
  - 已知项目已正确初始化
  - 需要快速启动工具
  - 在CI/CD等自动化场景中使用

- `--agent`: 直接执行Agent模式，无需进入交互界面。适用于：
  - 自动化脚本集成
  - 批量任务处理
  - 定时任务执行

**使用示例：**

```bash
# 快速启动并进入交互模式
auto-coder.nano --quick

# 直接使用Agent完成代码重构
auto-coder.nano --agent "重构用户认证模块，添加日志记录"

# 在脚本中使用Agent
#!/bin/bash
auto-coder.nano --agent "更新API文档" --quick
```

### 9.总结

AutoCoder Nano 通过命令行界面提供轻量级, 多功能的AI辅助编码工具。通过将LLM与文件管理, 代码索引和上下文理解相结合, 它实现了自然语言指令与代码修改的无缝衔接。

主要优势:

- 安装简便, 依赖极少 
- 支持多种编程语言和项目类型 
- 灵活的配置和模型管理 
- 上下文感知的代码理解与生成 
- Agent模式支持复杂任务处理
- 规则系统辅助代码设计
- RAG文档检索增强
- 完整的会话管理
- Git集成支持版本控制
