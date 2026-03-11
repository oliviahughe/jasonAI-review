# Jason-KB Codex HTTP Headers Troubleshooting

Date: 2026-03-11
Topic: Codex remote MCP startup fails with `Unauthorized` during `initialize`
Status: Resolved

## Background

The remote `jason-kb` service had already advanced past the earlier networking problems:

- public endpoint: `http://101.32.219.232/mcp`
- Caddy reverse proxy installed and active
- `421 Invalid Host header` already resolved by rewriting upstream `Host` to `127.0.0.1:8080`

At this stage, the remaining symptom was:

```text
Unauthorized"), when send initialize request
```

## Evidence Collected

### 1. Plain curl with Bearer reached protocol layer

Request:

```bash
curl -i -H "Authorization: Bearer <AUTH_TOKEN>" http://101.32.219.232/mcp
```

Response:

- `406 Not Acceptable`

Interpretation:

- network path is working
- Caddy is forwarding correctly
- Bearer token is accepted
- failure has moved into MCP protocol negotiation

### 2. Manual initialize succeeds when Authorization is present

Manual `POST /mcp` with:

- `Authorization: Bearer <AUTH_TOKEN>`
- `Accept: application/json, text/event-stream`
- `Content-Type: application/json`
- JSON-RPC `initialize` payload

returned a valid MCP initialize response.

The same request without `Authorization` returned `401 Unauthorized`.

Interpretation:

- service-side auth middleware is working correctly
- Caddy is not stripping `Authorization`
- root cause is on the Codex client side, not on the server side

## Root Cause

The local Codex configuration used:

```toml
[mcp_servers.jason-kb.headers]
Authorization = "Bearer <AUTH_TOKEN>"
```

But Codex expects:

```toml
[mcp_servers.jason-kb.http_headers]
Authorization = "Bearer <AUTH_TOKEN>"
```

Because the key name was wrong, Codex silently failed to attach the Bearer token to the remote MCP initialize request.

## Fix Applied

Updated local file:

- `C:\Users\69050\.codex\config.toml`

from:

```toml
[mcp_servers.jason-kb.headers]
Authorization = "Bearer <AUTH_TOKEN>"
```

to:

```toml
[mcp_servers.jason-kb.http_headers]
Authorization = "Bearer <AUTH_TOKEN>"
```

## Practical Troubleshooting Rules

When debugging remote `streamable_http` access for `jason-kb`, interpret these responses as follows:

- `421 Invalid Host header`
  - reverse proxy / upstream `Host` rewrite problem
- `406 Not Acceptable`
  - request has reached MCP protocol layer; `Accept` negotiation is the current issue
- `401 Unauthorized` on Codex `initialize`
  - first check whether Codex is actually sending the Bearer token
  - in Codex CLI config, verify `http_headers`, not `headers`

## Next Step if It Still Fails

If Codex still fails after switching to `http_headers`:

1. restart Codex so it reloads `~/.codex/config.toml`
2. capture the latest `C:\Users\69050\.codex\log\codex-tui.log`
3. continue from client-side request construction and version compatibility, not from server networking
