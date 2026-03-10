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
├── SKILL.md                  # Claude Code Skill 主文件（工作流定义）
├── config/
│   └── settings.yaml         # MCP / ingest / crawl 配置
├── Dockerfile                # 远程部署镜像
├── compose.tencent.yml       # 腾讯云部署示例
└── scripts/
    ├── crawl.py              # 文章抓取并保存到 raw/
    ├── ingest.py             # Markdown 切片、embedding、入库
    ├── mcp_server.py         # MCP Server 入口
    └── migrate_data.py       # 首次部署时同步种子数据到 DATA_DIR
```

---

## 快速开始

### 1. 配置 OpenAI / 兼容接口

编辑 `config/settings.yaml`，填入 embedding 所需配置：

```yaml
openai:
  api_key: "sk-xxx"
  base_url: "https://api.openai.com/v1"
  embedding_model: "text-embedding-3-small"
```

也可以通过环境变量覆盖：

```bash
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

远程部署时如果启用 Bearer 鉴权，还需要额外设置：

```bash
AUTH_TOKEN=your-secret-token
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 MCP Server

本项目依赖名为 `jason-kb` 的本地 MCP Server 提供 9 个工具（知识库检索、财务档案读写、文章入库等）。MCP Server 需单独部署，配置方式参考 Claude Code 文档。

本地直接运行时可使用：

```bash
python scripts/mcp_server.py
```

### 4. 远程部署

如果你要把 MCP Server 部署到腾讯云轻量应用服务器，请直接看：

- `docs/deploy-tencent-lighthouse.md`

仓库内已提供：

- `Dockerfile`
- `compose.tencent.yml`
- `.env.tencent.example`
- `deploy/caddy/Caddyfile`

### 5. 连接远程 MCP

远程服务启动后，SSE 入口通常为：

```text
https://你的域名/sse
```

如果服务端配置了 `AUTH_TOKEN`，客户端请求时还需要带上：

```text
Authorization: Bearer <你的 AUTH_TOKEN>
```

#### Claude Desktop

在 Claude Desktop 的 MCP 配置中注册一个远程 `sse` 服务即可。可参考下面的结构：

```json
{
  "mcpServers": {
    "jason-kb": {
      "transport": {
        "type": "sse",
        "url": "https://你的域名/sse",
        "headers": {
          "Authorization": "Bearer <你的 AUTH_TOKEN>"
        }
      }
    }
  }
}
```

如果服务端没有配置 `AUTH_TOKEN`，可以去掉 `headers`。

#### Claude Code

在 Claude Code 的 MCP 配置里注册同一个远程服务，服务名仍建议使用 `jason-kb`。核心信息与上面一致：

- 传输方式：`sse`
- 地址：`https://你的域名/sse`
- 鉴权头：`Authorization: Bearer <你的 AUTH_TOKEN>`（如果启用了鉴权）

#### 其他 AI CLI / MCP 客户端

只要客户端支持 MCP over SSE，都可以接入这个服务。最少需要提供以下信息：

- Server name: `jason-kb`
- Transport: `sse`
- URL: `https://你的域名/sse`
- Header: `Authorization: Bearer <你的 AUTH_TOKEN>`（如果服务端启用了鉴权）

工具列表会由 MCP Server 自动暴露，客户端无需手动维护工具 schema。

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


