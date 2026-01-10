# Claude Code Skills 系统技术分析报告

> 调研日期: 2025年12月
> 主题: Claude Code Skills 动态加载方案参考

## 摘要

Claude Code Skills 是 Anthropic 推出的能力封装标准化方案，通过"能力装箱"和"渐进式加载"机制，将 AI 智能体的任务流程、脚本、参考文档和模板资源封装为可复用、可版本化的模块。本报告深入分析其系统架构、配置文件格式、动态加载机制和工具集成方式，为设计 agent 的 skills 动态加载方案提供参考。

---

## 1. Skills 系统架构概述

### 1.1 核心设计理念

Claude Code Skills 的核心创新在于**渐进式披露(Progressive Disclosure)**机制：

```
┌─────────────────────────────────────────────────────────────────┐
│                      上下文窗口 (稀缺资源)                         │
├─────────────────────────────────────────────────────────────────┤
│  Level 1 - Metadata (始终加载 ~100 words)                        │
│  ├── name: 技能名称                                               │
│  └── description: 用途描述 + 触发条件                               │
├─────────────────────────────────────────────────────────────────┤
│  Level 2 - SKILL.md Body (触发时加载 ~500 lines max)             │
│  ├── 工作流程指南                                                 │
│  ├── 核心指令                                                    │
│  └── 示例                                                        │
├─────────────────────────────────────────────────────────────────┤
│  Level 3 - 资源文件 (按需加载)                                    │
│  ├── scripts/ - 可执行代码                                        │
│  ├── references/ - 参考文档                                       │
│  └── assets/ - 模板资源                                          │
└─────────────────────────────────────────────────────────────────┘
```

**设计优势**：
- 避免上下文窗口溢出
- 降低 token 成本
- 提升执行准确性（减少信息过载导致的"跑偏"）

### 1.2 与其他机制的区别

| 特性 | Skills | MCP | CLAUDE.md | Prompts |
|------|--------|-----|-----------|---------|
| **目的** | 封装专业知识和工作流 | 连接外部工具和数据源 | 项目级上下文 | 通用偏好设置 |
| **触发方式** | 模型自动识别 | 工具调用 | 始终加载 | 所有对话生效 |
| **持久性** | 跨会话持久化 | 状态无关 | 项目内持久化 | 持久化 |
| **复杂度** | 低 | 中-高 | 低 | 低 |
| **可执行代码** | ✅ | ❌ | ❌ | ❌ |
| **适用场景** | 3+ 次/周 的重复任务 | 外部 API 集成 | 项目编码规范 | 通用风格偏好 |

### 1.3 Skills vs MCP 的关系

```
Skills (怎么做) + MCP (怎么连) = 完整的能力闭环

┌─────────────────────────────────────────────┐
│              用户请求                         │
└────────────────────┬────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│  Skills: 决定执行步骤和工作流程                │
│  └── "如何完成数据仓库查询？"                  │
└────────────────────┬────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│  MCP: 提供外部工具和数据访问                   │
│  └── "连接数据库，执行 SQL"                   │
└─────────────────────────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│              执行结果                         │
└─────────────────────────────────────────────┘
```

---

## 2. Skills 目录结构与配置文件格式

### 2.1 标准目录结构

```
your-skill/
├── SKILL.md              # 【必需】核心配置文件
├── skill.meta.json       # 【可选】元数据文件
├── scripts/              # 【可选】可执行脚本
│   ├── main.py          # 主要执行逻辑
│   └── utils.py         # 工具函数
├── references/           # 【可选】参考文档
│   ├── schema.md        # 数据模式定义
│   └── patterns.md      # 最佳实践
├── assets/               # 【可选】模板资源
│   ├── template.docx    # 文档模板
│   └── config.yaml      # 配置模板
├── tests/                # 【可选】测试用例
│   └── replay_case.md   # 回放测试
└── CHANGELOG.md          # 【可选】变更记录
```

### 2.2 SKILL.md 核心格式

SKILL.md 是技能的"说明书"，包含 YAML 前言部分和 Markdown 主体。

#### YAML 前言 (Frontmatter)

```yaml
---
name: data-warehouse-analyst
description: |
  Use when analyzing business data: revenue, ARR, customer segments,
  product usage, or sales pipeline. Provides table schemas, metric
  definitions, required filters, and query patterns specific to
  ACME's data warehouse.
version: 1.0.0
authors: ["data-team@acme.com"]
tags: [data-analysis, sql, business-metrics]
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
context-budget: 8000
dependencies:
  - python>=3.8
  - pandas>=1.5.0
---
```

**必填字段**：
- `name`: 小写字母、连字符，最大 64 字符
- `description`: 最大 1024 字符，必须说明 "WHAT" 和 "WHEN"

**可选字段**：
- `version`: 语义化版本 (如 1.0.0)
- `allowed-tools`: 允许使用的工具列表
- `context-budget`: 上下文预算 (token)
- `dependencies`: 外部依赖

#### Markdown 主体结构

```markdown
# Data Warehouse Analyst

## Overview
提供 ACME 数据仓库的专业分析能力，包括指标定义、查询模式和业务逻辑。

## When to Use
- 用户询问收入、ARR、客户细分等业务指标
- 需要生成 SQL 查询进行分析
- 需要验证数据质量或异常检测

## Quick Start Workflow
1. **Clarify the request**
   - 时间范围？（默认当前年度）
   - 客户细分？（明确是账户还是组织）
   - 业务决策是什么？

2. **Check for existing dashboards**
   - 查看 `references/dashboards.md` 是否有预置报表

3. **Identify the data source**
   - 优先使用聚合表而非原始事件数据

4. **Execute the analysis**
   - 应用必要过滤条件
   - 验证结果

## Core Instructions

### Standard Query Filters
所有收入查询必须排除测试账户：
```sql
WHERE account != 'Test'
WHERE month <= DATE_TRUNC(CURRENT_DATE(), MONTH)
```

### ARR Calculations
- 月度到年度: `monthly_revenue * 12`
- 7日滚动: `rolling_7d * 52`

## Knowledge Base
详细文档按需加载：
- **财务指标** → `references/finance.md`
- **产品使用** → `references/product.md`
- **销售管道** → `references/sales.md`

## Examples

**Input**: "What was our revenue last quarter?"

**Output**:
```sql
SELECT
  DATE_TRUNC(quarter, created_at) as quarter,
  SUM(amount) as revenue
FROM revenue_events
WHERE account != 'Test'
  AND created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 QUARTER)
GROUP BY 1
ORDER BY 1
```

## Error Handling
- 验证参数完整性
- 提供可操作的错误信息
- 记录失败到 `~/.claude/skill-errors.log`
```

### 2.3 skill.meta.json 元数据文件

```json
{
  "name": "data-warehouse-analyst",
  "version": "1.0.0",
  "authors": ["data-team@acme.com"],
  "tags": ["data-analysis", "sql", "business-metrics"],
  "context-budget": 8000,
  "permissions": {
    "read": ["/data/**/*", "references/**/*"],
    "write": ["/outputs/**/*"],
    "network": ["internal-db.acme.com"]
  },
  "dependencies": {
    "python": ">=3.8",
    "packages": ["pandas>=1.5.0"]
  },
  "lifecycle": {
    "init": "scripts/init.py",
    "cleanup": "scripts/cleanup.py"
  }
}
```

---

## 3. 工具集成机制

### 3.1 工具声明与授权

在 SKILL.md 中通过 `allowed-tools` 字段声明需要使用的工具：

```yaml
allowed-tools:
  - Bash      # 执行 Shell 命令
  - Read      # 读取文件
  - Write     # 写入文件
  - Edit      # 编辑文件
  - Grep      # 搜索文件内容
  - Glob      # 文件模式匹配
  - WebFetch  # 获取网页内容
  - ToolName  # MCP 工具
```

### 3.2 MCP (Model Context Protocol) 集成

Skills 可以通过 MCP 协议集成外部工具和数据源：

#### MCP 服务配置 (.mcp.json)

```json
{
  "mcpServers": [
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    },
    {
      "name": "database",
      "transport": "streamable_http",
      "url": "https://mcp-db.acme.com/mcp"
    }
  ]
}
```

#### 在 Skills 中使用 MCP 工具

```markdown
## MCP Tools Available
- `db.query(sql, conn)`: 执行数据库查询（限制：最多 50k 行）
- `fs.write(path, content)`: 写入文件
- `fs.read(path)`: 读取文件

## Usage
```python
# 执行查询
result = mcp__db__query("SELECT * FROM revenue LIMIT 100")
```
```

### 3.3 可执行脚本集成

Skills 可以包含可执行脚本，提供确定性执行能力：

#### scripts/rotate_pdf.py

```python
#!/usr/bin/env python3
"""Rotate PDF pages by specified degrees."""

import argparse
from pypdf import PdfReader, PdfWriter

def rotate_pdf(input_path, output_path, degrees):
    reader = PdfReader(input_path)
    writer = PdfWriter()
    for page in reader.pages:
        page.rotate(degrees)
        writer.add_page(page)
    with open(output_path, "wb") as f:
        writer.write(f)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input PDF path")
    parser.add_argument("output", help="Output PDF path")
    parser.add_argument("--degrees", type=int, default=90)
    args = parser.parse_args()
    rotate_pdf(args.input, args.output, args.degrees)
```

#### 在 SKILL.md 中引用脚本

```markdown
## Scripts Usage

### PDF 旋转
使用 `scripts/rotate_pdf.py` 旋转 PDF 页面：

```bash
python scripts/rotate_pdf.py input.pdf output.pdf --degrees 90
```

### 参数说明
- `input`: 输入 PDF 路径
- `output`: 输出 PDF 路径  
- `--degrees`: 旋转角度（默认 90°）
```

---

## 4. 动态加载机制

### 4.1 技能存储位置

Skills 可以存储在多个位置，Claude 会自动扫描：

| 位置 | 范围 | 用途 |
|------|------|------|
| `~/.claude/skills/` | 用户级 | 跨项目共享的个人技能 |
| `.claude/skills/` | 项目级 | 团队共享的技能（纳入版本控制） |
| `plugins/*/skills/` | 插件级 | 插件打包的技能 |

### 4.2 自动发现与索引

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code 启动流程                       │
├─────────────────────────────────────────────────────────────┤
│  1. 扫描 ~/.claude/skills/ 目录                              │
│  2. 扫描项目 .claude/skills/ 目录                            │
│  3. 扫描插件 skills/ 目录                                    │
│  4. 解析 SKILL.md 前言提取元数据                             │
│  5. 构建 Skills 索引（name + description）                   │
│  6. 注入系统提示词                                           │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 触发匹配机制

当用户发起请求时，Claude 执行以下匹配流程：

```
用户请求: "帮我分析本月的收入数据"

┌─────────────────────────────────────────────────────────────┐
│  Step 1: 匹配 Skills 索引                                    │
│  检查所有 Skills 的 description 字段                         │
├─────────────────────────────────────────────────────────────┤
│  Step 2: 相似度计算                                          │
│  - data-warehouse-analyst: 匹配度 0.85                       │
│  - sql-expert: 匹配度 0.65                                   │
│  - code-reviewer: 匹配度 0.15                                │
├─────────────────────────────────────────────────────────────┤
│  Step 3: 选择最优 Skills                                     │
│  选取 top-k 匹配的 Skills（通常 k=3）                        │
├─────────────────────────────────────────────────────────────┤
│  Step 4: 渐进式加载                                          │
│  1. 加载 selected skills 的元数据                            │
│  2. 加载 SKILL.md 主体                                       │
│  3. 执行过程中按需加载 references/ 和 scripts/               │
├─────────────────────────────────────────────────────────────┤
│  Step 5: 执行并返回结果                                      │
└─────────────────────────────────────────────────────────────┘
```

### 4.4 版本管理与更新

```
# 查看已安装的 Skills
claude skills list

# 检查 Skills 更新
claude skills update

# 手动重新加载 Skills
claude skills refresh

# 验证 Skills 配置
claude skills validate
```

---

## 5. 高级特性与最佳实践

### 5.1 组合 Skills 使用

Claude 可以同时使用多个 Skills：

```markdown
**User Request**: "Review this PR and generate test cases"

**Claude Execution**:
1. Load SECURITY_REVIEWER skill
2. Load CODE_REVIEWER skill  
3. Load TEST_GENERATOR skill
4. Execute combined workflow
```

### 5.2 分层文档组织

对于复杂的 Skills，按域组织 references：

```
bigquery-skill/
├── SKILL.md
└── references/
    ├── finance.md      # 收入、计费指标
    ├── sales.md        # 机会、管道
    ├── product.md      # API 使用、功能
    └── marketing.md    # 活动、归因
```

### 5.3 代码签名与安全

企业部署时可以启用代码签名：

```bash
# 生成 GPG 密钥对
gpg --gen-key

# 签名 SKILL.md
gpg --detach-sign --armor SKILL.md

# 配置验证签名
claude config set require-signatures true
claude config add-trusted-key team@company.com
```

### 5.4 审计日志

所有 Skills 执行都会生成结构化日志：

```json
{
  "timestamp": "2025-12-02T14:32:11Z",
  "skill": "data-warehouse-analyst",
  "user": "analyst@company.com",
  "files_accessed": ["/data/revenue.csv"],
  "files_modified": ["/outputs/report.md"],
  "network_requests": [],
  "mcp_tools_used": ["db.query"],
  "exit_code": 0,
  "duration_ms": 2341,
  "tokens_used": 5200
}
```

---

## 6. 社区示例解析

### 6.1 官方示例仓库

Anthropic 官方提供了 20+ 示例 Skills：

| Skill | 功能 | 目录结构 |
|-------|------|----------|
| `playwright-testing` | Web 应用测试 | SKILL.md + scripts/ |
| `docx-processor` | Word 文档处理 | SKILL.md + assets/ |
| `code-reviewer` | 代码审查 | SKILL.md + references/ |
| `pdf-editor` | PDF 编辑 | SKILL.md + scripts/ |

### 6.2 创建工具: skill-creator

```bash
# 初始化新 Skill
skill-creator init my-new-skill

# 验证 Skill
skill-creator validate ./my-new-skill

# 打包为 .skill 文件
skill-creator package ./my-new-skill

# 发布到市场
skill-creator publish
```

---

## 7. 设计建议：Agent Skills 动态加载方案

基于 Claude Code Skills 的设计，为你的 agent 设计动态加载方案：

### 7.1 推荐架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent Skills System                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Skills/     │    │  Index/      │    │  Loader/     │      │
│  │  Registry    │───▶│  Scanner     │───▶│  Executor    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ skills.json  │    │ SkillParser  │    │ ToolRunner   │      │
│  │ metadata.db  │    │ (YAML/MD)    │    │ ScriptExec   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 核心组件设计

#### Skill Registry

```python
class SkillRegistry:
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.index: Dict[str, SkillMetadata] = {}
        self.cache_dir = Path(base_path) / ".skill-cache"
    
    def scan(self) -> List[SkillMetadata]:
        """扫描并索引所有 Skills"""
        skills = []
        for skill_dir in self.cache_dir.iterdir():
            if skill_dir.is_dir():
                skill = self._load_skill(skill_dir)
                skills.append(skill)
                self.index[skill.name] = skill
        return skills
    
    def match(self, request: str) -> List[SkillMetadata]:
        """基于描述匹配 Skills"""
        embeddings = self._get_embeddings(request)
        scores = []
        for name, skill in self.index.items():
            score = self._cosine_similarity(
                embeddings, 
                skill.description_embedding
            )
            scores.append((name, score, skill))
        return sorted(scores, key=lambda x: x[1], reverse=True)[:5]
```

#### Skill Loader (渐进式加载)

```python
class SkillLoader:
    def __init__(self):
        self.cache = LRUCache(maxsize=100)
    
    def load_metadata(self, skill_path: Path) -> SkillMetadata:
        """加载 Level 1: 元数据"""
        skill = self._parse_frontmatter(skill_path / "SKILL.md")
        return skill.metadata
    
    def load_body(self, skill_path: Path) -> str:
        """加载 Level 2: SKILL.md 主体"""
        cache_key = f"{skill_path}:body"
        if cache_key not in self.cache:
            content = (skill_path / "SKILL.md").read_text()
            self.cache[cache_key] = self._extract_body(content)
        return self.cache[cache_key]
    
    def load_resources(self, skill_path: Path, needed: List[str]) -> Dict:
        """加载 Level 3: 按需加载资源"""
        resources = {}
        for ref in needed:
            if ref.startswith("scripts/"):
                resources[ref] = (skill_path / ref).read_text()
            elif ref.startswith("references/"):
                resources[ref] = self._load_markdown(skill_path / ref)
        return resources
```

### 7.3 配置文件格式设计

```yaml
# skill.yaml
apiVersion: v1
kind: Skill
metadata:
  name: code-reviewer
  version: 1.0.0
  description: |
    Perform comprehensive code reviews focusing on security,
    performance, and maintainability.
  tags: [security, quality, review]
  
spec:
  allowedTools:
    - name: Read
      scope: ["**/*.{js,ts,py}"]
    - name: Write
      scope: ["./reports/**/*"]
  
  contextBudget: 8000
  
  dependencies:
    - node>=16.0.0
    - eslint>=8.0.0
  
  resources:
    scripts:
      - scripts/review.js
      - scripts/utils.js
    references:
      - references/security-checklist.md
      - references/js-patterns.md
    assets:
      - assets/report-template.md
  
  triggers:
    - keywords: ["review", "pr", "pull request", "audit"]
    - filePatterns: ["**/*.{js,ts,py,java}"]
  
  lifecycle:
    init: scripts/init.js
    cleanup: scripts/cleanup.js
```

### 7.4 动态加载流程

```python
async def execute_with_skills(
    agent: Agent,
    request: str,
    skill_dir: Path
) -> ExecutionResult:
    
    # 1. 扫描 Skills
    registry = SkillRegistry(skill_dir)
    skills = registry.scan()
    
    # 2. 匹配相关 Skills
    matched = registry.match(request)
    
    # 3. 渐进式加载
    loader = SkillLoader()
    context = {
        "skills_metadata": [s.metadata for s in matched],
        "skills_body": {},
        "skills_resources": {}
    }
    
    for name, score, skill in matched:
        if score > 0.7:  # 阈值
            context["skills_body"][name] = loader.load_body(skill.path)
    
    # 4. 构建执行上下文
    prompt = self._build_prompt(request, context)
    
    # 5. 执行
    result = await agent.run(prompt)
    
    # 6. 清理资源
    loader.cleanup()
    
    return result
```

---

## 8. 参考资料

### 官方资源
- **Claude Code Skills 官方文档**: https://docs.claude.com/docs/claude-code/skills
- **Anthropic Skills GitHub**: https://github.com/anthropics/skills
- **MCP 官方文档**: https://modelcontextprotocol.io

### 技术博客
- **Building Skills for Claude Code**: https://www.claude.com/blog/building-skills-for-claude-code
- **Claude Code Skills Complete Guide**: https://www.cursor-ide.com/blog/claude-code-skills
- **腾讯云开发者: Claude Skills 详解**: https://cloud.tencent.com/developer/news/3146525

### 开源实现
- **Mini Claude Code**: https://github.com/scipenai/mini-claude-code
- **Claude-meta-skill**: https://github.com/YYH211/Claude-meta-skill
- **Claude Code Development Kit**: https://github.com/pie-rs/Claude-Code-Development-Kit

### 社区资源
- **Skills Marketplace**: Claude Code 内置市场
- **Awesome Claude Skills**: 社区精选技能集合

---

## 9. 总结

Claude Code Skills 通过以下核心机制实现动态能力扩展：

1. **渐进式披露架构**：分层加载避免上下文溢出
2. **标准化目录结构**：`SKILL.md + scripts/ + references/ + assets/`
3. **声明式配置**：YAML frontmatter 定义元数据和工具权限
4. **自动发现机制**：扫描多个目录并构建索引
5. **描述驱动匹配**：基于自然语言描述自动选择相关 Skills
6. **MCP 集成**：通过协议接入外部工具和数据源

这套方案为设计 agent 的 skills 动态加载系统提供了成熟的参考架构，特别适合需要封装专业领域知识、流程规范和可执行工具的 AI 应用场景。

---

*报告生成时间: 2025年12月*
