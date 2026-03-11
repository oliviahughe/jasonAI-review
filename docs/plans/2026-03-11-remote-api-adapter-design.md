# Remote API + Local MCP Adapter Design

**Date:** 2026-03-11

**Status:** Approved for planning

## Goal

Keep the current natural-language skill workflow in Claude while simplifying remote deployment.

The remote service should stop trying to behave as a Claude-native remote MCP server. Instead, it should expose a plain HTTPS JSON API. A thin local MCP adapter should preserve the existing `jason-kb` tool surface so skills and natural-language usage continue to work.

## Why This Direction

The current remote SSE + custom Bearer approach proved workable with `curl`, but not with Claude Desktop's remote connector flow. The deployment also picked up protocol, auth-discovery, and SSE middleware compatibility issues that are orthogonal to the actual business logic.

The user priority is not "native remote MCP in Claude Desktop". The priority is stable remote usability while preserving skill-driven natural-language usage in Claude. A plain API plus a local adapter meets that goal with lower protocol complexity and easier operations.

## Architecture

### Target shape

The system becomes:

1. Claude skill triggers local `jason-kb` MCP tools
2. Local `jason-kb` adapter receives tool calls
3. Adapter forwards requests to a remote HTTPS JSON API
4. Remote API runs the actual knowledge-base / profile / ingestion logic
5. Adapter converts API responses back into the current tool return shape

### Boundary split

Remote side:

- Owns business logic execution
- Owns filesystem-backed data (`profile/`, `raw/`, `chroma_db/`)
- Owns auth for HTTP API
- Does not expose remote MCP

Local side:

- Owns MCP tool registration
- Owns minimal request validation and HTTP forwarding
- Does not own business logic or durable data

## Compatibility Goals

- Keep the existing `jason-kb` tool names
- Keep the existing parameter shapes where practical
- Preserve skill-driven natural-language use in Claude
- Avoid forcing end users to understand remote MCP, OAuth, or custom connector flows

## Remote API Design

Authentication:

- `Authorization: Bearer <token>`

Response contract:

Successful response:

```json
{
  "ok": true,
  "data": {},
  "message": "..."
}
```

Error response:

```json
{
  "ok": false,
  "error": "..."
}
```

Suggested endpoints:

- `POST /api/kb/search`
  - body: `query`, `top_k`
  - maps to `search_knowledge_base`
- `POST /api/kb/ingest/article`
  - body: `file_path`
  - maps to `ingest_article`
- `POST /api/kb/ingest/all`
  - maps to `ingest_all_raw`
- `POST /api/kb/crawl`
  - body: `url`, `source`
  - maps to `trigger_crawl`
- `GET /api/kb/recent?n=10`
  - maps to `get_recent_articles`
- `GET /api/profile?profile=...`
  - maps to `get_financial_profile`
- `POST /api/profile/update`
  - body: `field`, `value`, `profile`
  - maps to `update_financial_profile`
- `GET /api/advice/history?n=5&profile=...`
  - maps to `get_advice_history`
- `POST /api/advice/save`
  - body: `advice`, `profile`
  - maps to `save_advice`

## Local MCP Adapter Design

The local adapter should keep the current tool contract visible to Claude, but turn each tool implementation into a remote HTTP call.

Adapter responsibilities:

- Read API base URL and token from environment
- Validate required params before sending requests
- Translate HTTP errors into clear user-facing tool messages
- Convert JSON payloads into the string format expected by current skill usage

Adapter non-goals:

- No local crawl, ingest, embedding, or profile storage
- No duplicated business logic
- No attempt to be a remote MCP server

## Error Handling

Remote API:

- `401` for auth failures
- `400` for invalid inputs
- `500` for internal failures
- JSON only, never HTML error pages

Local adapter:

- Return readable errors such as:
  - `远端 API 认证失败`
  - `远端 API 不可达`
  - `远端返回参数错误: ...`
- Do not expose raw tracebacks to end users

## Testing Strategy

### Remote API tests

- Route-level tests for each endpoint
- Auth success / failure coverage
- Parameter validation coverage
- Error code and JSON shape coverage

### Local adapter tests

- Verify each tool maps to the correct API route
- Verify request body / query serialization
- Verify success JSON is converted back into the current tool return format
- Verify auth failure / network failure / bad response handling

### End-to-end smoke test

At least one full path:

- Claude tool call shape
- Local adapter
- Remote `/api/kb/search`
- Successful response formatting

## Documentation Strategy

The project needs onboarding docs for someone who has never deployed `jasonAI` skills before.

Recommended documentation split:

- `README.md`
  - High-level architecture
  - Supported modes
  - Quick orientation
- `docs/deploy-remote-api.md`
  - Server deployment guide
  - Environment variables
  - Docker / HTTPS / token setup
  - `curl` verification
- `docs/connect-claude-skill.md`
  - Local setup for end users
  - Required env vars for adapter
  - How to verify the skill works in Claude
  - Common failure cases and fixes

## Proposed File Impact

Likely additions:

- `scripts/api_server.py`
- remote API tests
- adapter tests
- `docs/deploy-remote-api.md`
- `docs/connect-claude-skill.md`

Likely modifications:

- `scripts/mcp_server.py` to become a local HTTP-forwarding adapter
- `README.md` to describe the new architecture and user paths

Likely reused without major logic changes:

- `scripts/ingest.py`
- `scripts/crawl.py`

## Non-Goals

- Do not implement official Claude remote MCP OAuth in this phase
- Do not keep dual-path remote connector support unless a concrete use case emerges
- Do not redesign the skill workflow before the adapter path is working
- Do not build a UI or management panel

## Recommended Next Step

Write an implementation plan for:

1. Remote API surface
2. Local MCP adapter conversion
3. Tests
4. User-facing docs for deployment and connection
