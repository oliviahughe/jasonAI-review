# 腾讯云 Lighthouse 部署方案

## 目标

将 `jason-kb` 作为远程 MCP streamable HTTP 服务部署到腾讯云轻量应用服务器，保留本地文件型数据结构：

- `profile/`
- `raw/`
- `chroma_db/`

运行形态采用单机 Docker 容器，数据落在服务器本地目录 `runtime-data/`，不依赖 Fly volume 或外部数据库。

## 推荐规格

- 平台：腾讯云 Lighthouse
- 地域：`中国香港`
- 系统：`Ubuntu 22.04 LTS` 或 `Docker CE` 应用模板
- 套餐建议：`2核2G` 起步

选择中国香港是为了减少额外合规门槛，并且更适合做一个面向你个人使用的远程工具服务。

## 目录说明

部署时使用以下文件：

- `Dockerfile`
- `compose.tencent.yml`
- `.env.tencent.example`
- `deploy/caddy/Caddyfile`

## 第 1 步：购买并初始化服务器

1. 在腾讯云购买 Lighthouse 实例。
2. 如果购买的是普通 Ubuntu 镜像，先安装 Docker 与 Docker Compose 插件。
3. 在防火墙里放行端口：
   - `22`
   - `80`
   - `443`

如果你直接买的是腾讯云 `Docker CE` 应用模板，这一步会更省事。

参考腾讯云官方文档：

- 腾讯云轻量应用服务器产品页：https://cloud.tencent.com/product/lighthouse
- Docker CE 应用模板：https://cloud.tencent.com/document/product/1207/60423
- 搭建 Docker：https://cloud.tencent.com/document/practice/213/46000

## 第 2 步：上传代码

在服务器上执行：

```bash
git clone <YOUR_REPO_URL> jason-kb
cd jason-kb
cp .env.tencent.example .env.tencent
mkdir -p runtime-data/profile runtime-data/raw runtime-data/chroma_db
```

如果你的知识库现有数据在本地 Windows 机器上，先把这些目录同步到服务器：

```text
本地 D:\claudecode\jasonAI\jason-kb\profile  -> 服务器 ./runtime-data/profile
本地 D:\claudecode\jasonAI\jason-kb\raw      -> 服务器 ./runtime-data/raw
本地 D:\claudecode\jasonAI\jason-kb\chroma_db -> 服务器 ./runtime-data/chroma_db
```

如果不想直接复制现有 `chroma_db`，也可以只传 `profile/` 与 `raw/`，然后在服务器上重新 ingest。

## 第 3 步：配置环境变量

编辑 `.env.tencent`：

```dotenv
MCP_TRANSPORT=streamable_http
PORT=8080
DATA_DIR=/data
AUTH_TOKEN=替换成随机长 token
OPENAI_API_KEY=你的 key
OPENAI_BASE_URL=https://api.ofox.ai/v1
DEEPSEEK_API_KEY=如需保留建议脚本则填写
DEEPSEEK_BASE_URL=https://api.siliconflow.cn/v1
```

说明：

- `AUTH_TOKEN` 用于 Claude Code 远程访问时的 Bearer 鉴权
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` 用于知识库 embedding 与检索
- `DEEPSEEK_*` 仅影响本仓库里本地建议脚本，不影响 MCP 基础能力

## 第 4 步：启动服务

```bash
docker compose -f compose.tencent.yml up -d --build
docker compose -f compose.tencent.yml logs -f
```

容器会：

1. 先执行 `python scripts/migrate_data.py`
2. 如果 `/data` 为空，就把镜像里的 `profile/` 与 `raw/` 种子数据复制过去
3. 启动 `python scripts/mcp_server.py`

服务实际监听在容器内 `8080`。如果你已经有域名，建议宿主机只配合反代对外暴露 `/mcp`；如果你还没有域名，也可以临时把 `compose.tencent.yml` 改成直接暴露 `8080`，再通过 IP 反代到 `127.0.0.1:8080`。

## 第 5 步：配置 HTTPS 反向代理

推荐使用 Caddy：

```bash
sudo apt-get update
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update
sudo apt-get install -y caddy
```

把 `deploy/caddy/Caddyfile` 放到 `/etc/caddy/Caddyfile`，并把 `DOMAIN` 替换成你的域名：

```caddyfile
kb.example.com {
    encode gzip
    reverse_proxy /mcp 127.0.0.1:8080 {
        header_up Host 127.0.0.1:8080
    }
}
```

`header_up Host 127.0.0.1:8080` 很关键。`jason-kb` 的 streamable HTTP 服务在公网直连 `:8080` 时可能返回：

```text
421 Invalid Host header
```

通过反代把上游 `Host` 固定为 `127.0.0.1:8080` 后，请求才能正常进入 MCP 协议层。

如果你暂时没有域名，也可以先用一个基于 IP 的临时 Caddy 配置：

```caddyfile
:80 {
    reverse_proxy /mcp 127.0.0.1:8080 {
        header_up Host 127.0.0.1:8080
    }
}
```

然后：

```bash
sudo systemctl reload caddy
```

## 第 6 步：验证服务

未带 token 时应返回 `401`：

```bash
curl -i https://kb.example.com/mcp
```

带 token 时应能到达 MCP HTTP 入口：

```bash
curl -i \
  -H "Authorization: Bearer <AUTH_TOKEN>" \
  https://kb.example.com/mcp
```

如果你还没有域名，临时 IP 版验证命令是：

```bash
curl -i http://101.32.219.232/mcp

curl -i \
  -H "Authorization: Bearer <AUTH_TOKEN>" \
  http://101.32.219.232/mcp
```

预期：

- 不带 token：`401 Unauthorized`
- 带 token：不再出现 `421 Invalid Host header`
- 普通 `curl` 带 token 时返回 `406 Not Acceptable` 也是正常的，因为 `curl` 不是完整的 MCP 客户端

## 第 7 步：Claude Code 配置

把本地 MCP 配置改成：

```json
{
  "mcpServers": {
    "jason-kb": {
      "url": "https://kb.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <AUTH_TOKEN>"
      }
    }
  }
}
```

如果还没有域名，可暂时改为：

```json
{
  "mcpServers": {
    "jason-kb": {
      "url": "http://101.32.219.232/mcp",
      "headers": {
        "Authorization": "Bearer <AUTH_TOKEN>"
      }
    }
  }
}
```

## 数据迁移策略

推荐顺序：

1. 先同步 `profile/`
2. 再同步 `raw/`
3. `chroma_db/` 可选

如果不复制现有向量库，可在服务器容器里重新 ingest：

```bash
docker compose -f compose.tencent.yml exec jason-kb python scripts/ingest.py
```

## 运维命令

查看日志：

```bash
docker compose -f compose.tencent.yml logs -f
```

重启：

```bash
docker compose -f compose.tencent.yml restart
```

重新构建：

```bash
docker compose -f compose.tencent.yml up -d --build
```

停止：

```bash
docker compose -f compose.tencent.yml down
```

## 当前限制

- 这套方案默认是单机部署，不做多副本高可用
- 最佳长期方案仍然是 `域名 + HTTPS + 反向代理`
- 没有域名时，可先用 `IP + Caddy(:80) + /mcp 反代` 的临时方案
- 不建议客户端直连 `http://公网IP:8080/mcp`，否则可能遇到 `421 Invalid Host header`
- `runtime-data/` 在服务器本地磁盘上，备份需要你自己做
