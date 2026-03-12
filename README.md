# Jason AI 理财助手

基于财经博主「Jason 不跪」内容构建的私有知识库系统，集成在 Claude Code 中使用。通过 MCP Server 提供知识检索、理财建议、财务档案管理等功能。数据存储位置取决于你当前连接的 MCP 服务部署位置：连本地服务时写本机，连远程服务时写远程服务器本地磁盘。

---

## 功能概览

### 文章入库
- 发送公众号或知识星球文章 URL，自动爬取正文并入库
- 支持批量处理 `raw/` 目录下的本地 Markdown 文章
- 可查看最近入库文章列表

### 问答与建议
- 支持 `research / advice / record / history` 四种回答模式，不再把所有问题都当成基金建议处理
- 常识性问题、观点咨询可走 `知识库 + last30days + 补充检索 + DeepSeek` 的轻量链路
- 投资建议、调仓、分批计划等问题才会附加财务档案、持仓事实和硬约束校验
- 建议历史会压缩成“最近仍有效的主线摘要”，不会无限原文累加进上下文

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

远程服务启动后，streamable HTTP 入口通常为：

```text
https://你的域名/mcp
```

如果你暂时没有域名，也可以先用 Caddy 做一个基于 IP 的临时反代：

```text
http://服务器公网IP/mcp
```

注意：不要直接把客户端指向 `http://服务器公网IP:8080/mcp`。`jason-kb` 的 streamable HTTP 服务会对 `Host` 做校验，公网直连常见结果是：

```text
421 Invalid Host header
```

正确做法是通过反向代理把外部请求转发到 `127.0.0.1:8080`，并把上游 `Host` 改写为 `127.0.0.1:8080`。

如果服务端配置了 `AUTH_TOKEN`，客户端请求时还需要带上：

```text
Authorization: Bearer <你的 AUTH_TOKEN>
```

#### Claude Desktop / Claude Code / Codex

在客户端的 MCP 配置中注册一个远程 `streamable_http` 服务即可。可参考下面的结构：

```json
{
  "mcpServers": {
    "jason-kb": {
      "url": "https://你的域名/mcp",
      "headers": {
        "Authorization": "Bearer <你的 AUTH_TOKEN>"
      }
    }
  }
}
```

没有域名时，可暂时改为：

```json
{
  "mcpServers": {
    "jason-kb": {
      "url": "http://101.32.219.232/mcp",
      "headers": {
        "Authorization": "Bearer <你的 AUTH_TOKEN>"
      }
    }
  }
}
```

如果服务端没有配置 `AUTH_TOKEN`，可以去掉 `headers`。

如果你使用的是 **Codex CLI**，本地配置文件是 `~/.codex/config.toml`，Bearer 头要写在 `http_headers` 下，而不是 `headers`。示例：

```toml
[mcp_servers.jason-kb]
url = "http://101.32.219.232/mcp"

[mcp_servers.jason-kb.http_headers]
Authorization = "Bearer <你的 AUTH_TOKEN>"
```

排障经验：

- `401 Unauthorized`：通常表示客户端初始化请求没有真正带上 `Authorization`
- 如果你已经确认手工 `POST /mcp` 带 Bearer 可以成功 `initialize`，但 Codex 仍报 `Unauthorized`，优先检查是否把 `http_headers` 误写成了 `headers`
- 普通 `curl` 带 token 返回 `406 Not Acceptable` 仍然是正常现象，说明请求已经穿过网络和 Host 校验，进入了 MCP 协议协商层

#### 其他 AI CLI / MCP 客户端

只要客户端支持 MCP over streamable HTTP，都可以接入这个服务。最少需要提供以下信息：

- Server name: `jason-kb`
- Transport: `streamable_http`
- URL: `https://你的域名/mcp`
- Header: `Authorization: Bearer <你的 AUTH_TOKEN>`（如果服务端启用了鉴权）

临时无域名时：

- URL: `http://服务器公网IP/mcp`
- 仍然建议走 Caddy / Nginx 之类的反代，不要直连 `:8080`

工具列表会由 MCP Server 自动暴露，客户端无需手动维护工具 schema。

---

## 回答模式

### `research`

适合：

- 常识问答
- Jason 对某主题的观点咨询
- 原理解释
- 宏观/市场方向讨论

上下文默认包含：

- 用户问题
- 知识库结果
- 近 30 天市场信息
- 补充检索结果

默认不带：

- 持仓事实
- 建议历史
- 仓位硬校验

### `advice`

适合：

- 资产配置
- 买不买 / 卖不卖
- 调仓
- 分批计划
- 持仓风险分析

在 `research` 的基础上，额外带：

- 财务档案关键字段
- 当前持仓事实
- 压缩后的建议历史主线
- 硬约束校验

### `record`

适合：

- 更新资产
- 更新收入
- 更新持仓
- 更新风险偏好

默认只做资料更新，不触发完整 DeepSeek 建议链路。

### `history`

适合：

- 查看过去建议
- 回顾最近几次操作主线

默认直接读取建议历史，不生成新的综合建议。

---

## 使用方式

在 Claude Code 中直接用自然语言触发：

| 场景 | 示例说法 |
|------|---------|
| 文章入库 | `入库这篇 https://...` |
| 批量入库 | `把 raw 目录下的文章都处理一下` |
| 咨询问答 | `Jason 怎么看黄金现在的位置？` |
| 理财建议 | `我有 5 万闲钱怎么配？` |
| 仓位更新 | `我把恒生科技加仓到 2 万了` |
| 知识库查询 | `Jason 怎么看 A 股现在的位置？` |
| 历史建议 | `之前给我的建议是什么？` |

---

## 注意事项

- `config.json`（含 API Key）已加入 `.gitignore`，不会提交到 Git
- 知识库向量数据写到当前 MCP 服务所在机器的本地磁盘；如果客户端配置的是远程 `jason-kb`，那就是远程服务器本地磁盘，不是当前客户端机器
- 硬约束校验只在 `advice` 模式启用；普通咨询默认不会强行走持仓校验链路
- 建议历史会先压缩成短摘要再注入上下文，不会无限按原文累加，避免超时和 prompt 臃肿
- 如果你要发给完全没接触过 `jason-kb` 的朋友，直接看 `docs/remote-mcp-quickstart-for-friends.md`


