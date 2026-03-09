# Jason AI 理财助手

基于财经博主「Jason 不跪」内容构建的私有知识库系统，集成在 Claude Code 中使用。通过 MCP Server 提供知识检索、理财建议、财务档案管理等功能，所有数据存储在本地。

---

## 功能概览

### 文章入库
- 发送公众号或知识星球文章 URL，自动爬取正文并入库
- 支持批量处理 `raw/` 目录下的本地 Markdown 文章
- 可查看最近入库文章列表

### 理财建议
- 结合 Jason 的知识库观点、用户财务档案、近 30 天市场动态，生成可执行建议
- 调用 DeepSeek API 生成建议，内置硬约束校验（止损线、仓位上限等），防止 AI 编造数据
- 自动记录每次建议历史，保持建议连贯性，避免自相矛盾

### 财务档案管理
- 维护用户资产、收入、风险偏好等信息
- 仓位变动时可随时更新，建议自动基于最新财务状态生成

### 知识库查询
- 向量检索，快速找到 Jason 在特定话题上的观点
- 查询结果附带来源文章标题和日期

---

## 项目结构

```
jason-kb/
├── SKILL.md              # Claude Code Skill 主文件（工作流定义）
├── config.example.json   # API 配置模板
├── config.json           # 本地配置（含 API Key，已 gitignore）
└── scripts/
    ├── build_temp_input.py   # 结构化输入构建脚本（支持持仓 CSV 解析）
    └── call_deepseek.py      # DeepSeek API 调用脚本（含硬约束校验与自动重试）
```

---

## 快速开始

### 1. 配置 API Key

复制 `config.example.json` 为 `config.json`，填入你的 API Key：

```json
{
    "deepseek_api_key": "sk-xxx",
    "deepseek_base_url": "https://api.siliconflow.cn/v1",
    "deepseek_model": "Pro/deepseek-ai/DeepSeek-V3.2"
}
```

也可以通过环境变量配置（优先级高于 config.json）：

```bash
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.siliconflow.cn/v1
```

### 2. 安装依赖

```bash
pip install openai
```

### 3. 配置 MCP Server

本项目依赖名为 `jason-kb` 的本地 MCP Server 提供 9 个工具（知识库检索、财务档案读写、文章入库等）。MCP Server 需单独部署，配置方式参考 Claude Code 文档。

---

## 使用方式

在 Claude Code 中直接用自然语言触发：

| 场景 | 示例说法 |
|------|---------|
| 文章入库 | `入库这篇 https://...` |
| 批量入库 | `把 raw 目录下的文章都处理一下` |
| 理财建议 | `我有 5 万闲钱怎么配？` |
| 仓位更新 | `我把恒生科技加仓到 2 万了` |
| 知识库查询 | `Jason 怎么看 A 股现在的位置？` |
| 历史建议 | `之前给我的建议是什么？` |

---

## 注意事项

- `config.json`（含 API Key）已加入 `.gitignore`，不会提交到 Git
- 知识库向量数据存储在本地，不会上传到外部服务器（Embedding API 调用除外）
- 建议生成内置硬约束校验，若 AI 输出与结构化财务数据冲突会自动重试，最多重试 2 次；仍不通过则拒绝返回，防止错误建议流出


