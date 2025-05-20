## 概述

AutoCoder Nano 是一款轻量级的编码助手, 利用大型语言模型（LLMs）帮助开发者编写, 理解和修改代码。

它提供了一个交互式命令行界面，支持在软件开发场景中与LLMs互动，具备代码生成, 文件管理和上下文代码理解等功能。

本概述介绍了 AutoCoder Nano 的用途, 架构和核心组件。如需了解更多子系统的详细信息，请参阅相关页面，例如

- 命令行界面
- LLM集成
- RAG系统

### 1.什么是 AutoCoder Nano？

AutoCoder Nano 是 Auto-Coder 生态系统的简化版本，设计轻量且依赖极少。它旨在通过提供增强AI功能的命令行界面，弥合自然语言指令与代码修改之间的鸿沟。
 
Auto-Coder 主社区[点击跳转](https://github.com/allwefantasy/auto-coder)

**AutoCoder Nano 的主要特点：**

- 轻量级：依赖极少，代码库精简 
- 交互式：支持丰富补全和建议的命令行界面 
- AI驱动：集成多种大型语言模型 
- 上下文感知：利用文件索引和检索实现上下文理解 
- 多功能：支持多种项目类型和编程语言

**nano/lite/pro 有什么区别？**

- Pro：分布式架构，支持分布式部署模型，支持开源/SaaS模型管理，独特的 `human_as_model` 模式，RAG 支持，Design 设计支持，MCP支持，联网搜索支持，全局记忆支持，适合深度使用各种大模型的用户。
- Lite：放弃分布式架构，部分功能无法使用，主要针对 Windows 用户（第三方库兼容问题），以及需要快速启动并使用 auto-coder.chat 的用户。
- Nano：同样放弃分布式架构，为 auto-coder.chat 的移植版本，支持 `/chat`，`/coding`， `/文件管理`，`/索引管理` 等功能，依赖及代码极致精简，适合想要了解大模型辅助编程原理，以及想要实现自己辅助编程框架的用户

**autocoder-nano 的迭代方向：**

- 代码结构优化，便于后续维护及其他开发者魔改
- 并发支持，开发更大的项目
- 多语言优化，深度优化 Python 外的其他语言
- 候选模型支持，首选模型异常时进行切换
- RAG能力，支持一个简化的知识库，增强代码能力

### 2.系统架构

AutoCoder Nano 采用模块化架构，以命令行界面为核心，连接多个子系统。

#### 2.1.高级架构图

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
| **对话**   | `/chat`, `/coding`                           | 与LLM交互，处理通用查询或代码生成  |
| **文件管理** | `/add_files`, `/remove_files`, `/list_files` | 管理当前上下文中的活动文件       |
| **配置**   | `/conf`, `/mode`                             | 配置系统设置和行为           |
| **模型管理** | `/models /add_model`, `/models /list`        | 管理LLM集成设置           |
| **索引**   | `/index/build`, `/index/query`               | 构建和查询代码索引           |
| **工具**   | `/help`, `/shell`, `/exit`                   | 获取帮助、执行Shell命令或退出应用 |


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
5. `/coding/apply` 使用聊天历史记录
6. `/index` 管理代码索引
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
- 从处理中排除指定目录 
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

#### 5.2.自然语言编程

AutoCoder Nano 提供自然语言模式以生成和执行脚本：

1. 通过 /mode auto_detect 或 Ctrl+K 切换模式 
2. 输入自然语言指令 
3. 系统生成对应脚本 
4. 用户可审核并执行脚本

此功能弥合了自然语言指令与可执行命令之间的差距。


#### 5.3.代码索引与检索

AutoCoder Nano 构建并维护项目中代码实体的索引：

- 提取函数、类和变量并建立索引 
- 查询可以检索相关的代码实体 
- 识别相关文件以提供更好的上下文 
- 索引系统有助于更有针对性和高效地理解和生成代码。

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

安装完成后，AutoCoder Nano 提供以下三个主要命令行工具：  

| 命令                  | 描述                           |  
|---------------------|------------------------------|  
| auto-coder.nano     | 代码生成和聊天交互的主界面                |  
| auto-coder.nano.rag | 基于检索增强生成的上下文感知响应系统           |  
| auto-coder.nano.ui  | AutoCoder Nano 的基于 Web 的用户界面 |  


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
| chat_model| model-name    |  
| code_model| model-name    |  
| project_type      | py            |  
| skip_build_index  | false         |  
```

### 关键配置选项  

| 选项               | 描述         | 示例值              |  
|------------------|------------|------------------|  
| auto_merge       | 代码更改的合并策略  | editblock        |  
| chat_model       | 用于聊天和索引的模型 | deepseek-v3      |  
| code_model       | 用于代码生成的模型  | deepseek-v3      |  
| project_type     | 项目语言类型     | py, ts, .py, .ts |  
| skip_build_index | 跳过自动索引构建   | true, false      |  

修改配置的示例：  

```bash  
# 更改项目类型为 TypeScript  
/conf project_type:ts  

# 更改代码生成模型  
/conf code_model:deepseek-r1
```

#### 6.7.LLM 管理  

AutoCoder Nano 需要至少一个配置好的 LLM 才能运行。可以使用 `/models` 命令管理 LLM：  

**列出可用模型**

```bash  
/models /list  
```  

**显示已配置模型的表格：**

```  
模型  
Name         | Model Name      | Base URL  
------------------------------------------  
| deepseek-v3 | deepseek-coder  | https://api.deepseek.com |  
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


### 7.总结

AutoCoder Nano 通过命令行界面提供轻量级, 多功能的AI辅助编码工具。通过将LLM与文件管理, 代码索引和上下文理解相结合, 它实现了自然语言指令与代码修改的无缝衔接。

主要优势:

- 安装简便, 依赖极少 
- 支持多种编程语言和项目类型 
- 灵活的配置和模型管理 
- 上下文感知的代码理解与生成 
- 自然语言编程能力