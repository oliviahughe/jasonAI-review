# 远端 MCP 快速上手

适合对象：

- 没有本地 `jason-kb` skill
- 没有配过 MCP
- 只想连上现成的远端 `jason-kb` 服务直接用

## 你需要准备什么

让服务提供方给你这两样：

- MCP 地址，例如 `https://example.com/mcp`
- Bearer Token，例如 `Bearer abcdefg...`

如果对方还没部署好服务，可以先看 [deploy-tencent-lighthouse.md](C:\Users\69050\.claude\skills\jason-kb\docs\deploy-tencent-lighthouse.md)。

## 什么是远端 MCP

你可以把它理解成“远程工具服务”：

- 你的客户端负责发请求
- 远端 `jason-kb` 服务器负责提供知识库检索、档案读写、历史建议等工具
- 你本地不需要复制对方的 `profile/`、`raw/`、`chroma_db/`

## Claude / Claude Code 配置

把下面结构加到客户端的 MCP 配置里：

```json
{
  "mcpServers": {
    "jason-kb": {
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer <AUTH_TOKEN>"
      }
    }
  }
}
```

如果服务端没有启用 `AUTH_TOKEN`，可以去掉 `headers`。

## Codex 配置

如果你用的是 Codex，本地配置通常在 `~/.codex/config.toml`。

写法是：

```toml
[mcp_servers.jason-kb]
url = "https://example.com/mcp"

[mcp_servers.jason-kb.http_headers]
Authorization = "Bearer <AUTH_TOKEN>"
```

注意：

- 这里要写 `http_headers`
- 不要写成 `headers`

## 连通性验证

先试不带 token：

```bash
curl -i https://example.com/mcp
```

预期：

- `401 Unauthorized`

再试带 token：

```bash
curl -i ^
  -H "Authorization: Bearer <AUTH_TOKEN>" ^
  https://example.com/mcp
```

预期：

- 不再是 `401`
- 返回 `406 Not Acceptable` 也可以接受，这通常说明网络、Host 和鉴权都已经通了，只是 `curl` 不是完整 MCP 客户端

## 常见报错

### `401 Unauthorized`

通常表示：

- token 没带上
- token 写错了
- Codex 里把 `http_headers` 误写成了 `headers`

### `421 Invalid Host header`

通常表示：

- 你在直连 `:8080`
- 服务端没有走反向代理
- 反向代理没有把上游 `Host` 改写成 `127.0.0.1:8080`

这类情况一般需要服务端提供方处理。

### `406 Not Acceptable`

这通常不是坏消息，往往表示：

- 你的请求已经通过了网络和 Host 校验
- Bearer Token 也可能是正确的
- 只是当前请求不是完整的 MCP 协议协商请求

## 连上以后怎么判断能不能用

能看到并调用这些工具，基本就说明接成功了：

- `search_knowledge_base`
- `get_financial_profile`
- `get_advice_history`
- `update_financial_profile`
- `save_advice`

如果客户端能列出这些工具，但调用时报认证错误，优先回头检查 `Authorization` 头。

## 一句话排障顺序

按这个顺序排：

1. 地址对不对
2. token 对不对
3. 客户端有没有真的把 `Authorization` 带出去
4. 服务端是不是走了反代而不是裸连 `:8080`
