# Remote API + Local MCP Adapter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current remote-MCP deployment path with a plain remote HTTPS API plus a thin local MCP adapter, while preserving the existing `jason-kb` skill-driven natural-language workflow.

**Architecture:** The remote host will run a JSON HTTP API that reuses the existing knowledge-base, crawl, and profile logic. The local `jason-kb` MCP server will become a forwarding adapter: it will keep the current tool names and parameter shapes, send authenticated HTTP requests to the remote API, and convert JSON responses back into the string outputs expected by current skills.

**Tech Stack:** Python 3.11, FastMCP, Starlette/FastAPI-style HTTP app, requests, unittest, Docker Compose, bearer-token HTTP auth.

---

### Task 1: Add Remote API Server Skeleton

**Files:**
- Create: `C:\Users\69050\.claude\skills\jason-kb\scripts\api_server.py`
- Modify: `C:\Users\69050\.claude\skills\jason-kb\requirements.txt`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`

**Step 1: Write the failing test**

```python
def test_health_endpoint_returns_ok():
    api_server = _load_module("api_server_health", "scripts/api_server.py")
    client = api_server.create_test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_health_endpoint_returns_ok -v`
Expected: FAIL because `scripts/api_server.py` does not exist yet.

**Step 3: Write minimal implementation**

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"ok": True}
```

Add the minimum dependency required for the HTTP server runtime if it is not already present.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_health_endpoint_returns_ok -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_api_server.py scripts/api_server.py requirements.txt
git commit -m "feat: add remote API server skeleton"
```

### Task 2: Add Shared HTTP Auth and JSON Error Contract

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\api_server.py`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`

**Step 1: Write the failing test**

```python
def test_protected_endpoint_requires_bearer_token():
    client = create_test_client(auth_token="secret")
    response = client.post("/api/kb/search", json={"query": "A股", "top_k": 3})
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Unauthorized"}
```

Add a second test for the success path with the correct `Authorization` header.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_protected_endpoint_requires_bearer_token -v`
Expected: FAIL because auth is not implemented yet.

**Step 3: Write minimal implementation**

Implement:

- environment-backed API token reader, e.g. `JASON_KB_API_TOKEN`
- request auth dependency/middleware
- shared JSON helpers:

```python
def ok(data=None, message=""):
    return {"ok": True, "data": data or {}, "message": message}

def error(message: str):
    return {"ok": False, "error": message}
```

Apply auth to `/api/*` routes, but not `/healthz`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_protected_endpoint_requires_bearer_token -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_api_server.py scripts/api_server.py
git commit -m "feat: add bearer auth and JSON error contract"
```

### Task 3: Implement Knowledge-Base Search API

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\api_server.py`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`

**Step 1: Write the failing test**

```python
def test_search_endpoint_calls_search_knowledge_base_logic():
    client = create_test_client(auth_token="secret")
    response = client.post(
        "/api/kb/search",
        headers={"Authorization": "Bearer secret"},
        json={"query": "A股", "top_k": 2},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["data"]["results"][0]["title"] == "示例"
```

Mock the underlying search function rather than hitting embeddings or Chroma.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_search_endpoint_calls_search_knowledge_base_logic -v`
Expected: FAIL because route does not exist yet.

**Step 3: Write minimal implementation**

Add `POST /api/kb/search` that:

- validates `query`
- defaults `top_k`
- calls existing search logic from `scripts/ingest.py`
- returns:

```json
{
  "ok": true,
  "data": {"results": [...]},
  "message": ""
}
```

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_search_endpoint_calls_search_knowledge_base_logic -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_api_server.py scripts/api_server.py
git commit -m "feat: add knowledge-base search API"
```

### Task 4: Implement Crawl and Ingest API Endpoints

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\api_server.py`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`

**Step 1: Write the failing tests**

Write one failing test each for:

- `POST /api/kb/crawl`
- `POST /api/kb/ingest/article`
- `POST /api/kb/ingest/all`

Example:

```python
def test_crawl_endpoint_returns_saved_file_metadata():
    response = client.post(
        "/api/kb/crawl",
        headers=auth_headers(),
        json={"url": "https://example.com/article", "source": "公众号"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["title"] == "示例文章"
```

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_api_server.ApiServerTests.test_crawl_endpoint_returns_saved_file_metadata -v`
Expected: FAIL because the routes do not exist yet.

**Step 3: Write minimal implementation**

Add the three endpoints and reuse existing logic:

- crawl from `scripts/crawl.py`
- single-article ingest from `scripts/ingest.py`
- bulk ingest from `scripts/ingest.py`

Return JSON only. Do not format multi-line tool strings here.

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_api_server -v`
Expected: PASS for the new endpoint tests.

**Step 5: Commit**

```bash
git add tests/test_api_server.py scripts/api_server.py
git commit -m "feat: add crawl and ingest API endpoints"
```

### Task 5: Implement Profile and Advice API Endpoints

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\api_server.py`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`

**Step 1: Write the failing tests**

Write failing tests for:

- `GET /api/profile`
- `POST /api/profile/update`
- `GET /api/advice/history`
- `POST /api/advice/save`
- `GET /api/kb/recent`

Use mocks or temporary files so tests never touch real user data.

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_api_server -v`
Expected: FAIL for the new routes.

**Step 3: Write minimal implementation**

Expose the remaining business capabilities through JSON routes. Keep data access inside existing helper logic where possible. If shared profile-path helpers need extraction from `mcp_server.py`, extract them once into a reusable module instead of duplicating them.

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_api_server -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_api_server.py scripts/api_server.py scripts/mcp_server.py
git commit -m "feat: add profile and advice API endpoints"
```

### Task 6: Convert Local MCP Server Into HTTP Forwarding Adapter

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\mcp_server.py`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_mcp_adapter.py`
- Reference: `C:\Users\69050\.claude\skills\jason-kb\SKILL.md`

**Step 1: Write the failing test**

```python
def test_search_tool_forwards_to_remote_api():
    mcp_server = _load_module("mcp_adapter_search", "scripts/mcp_server.py")
    with patch.object(mcp_server.requests, "post") as post_mock:
        post_mock.return_value.json.return_value = {
            "ok": True,
            "data": {"results": [{"title": "示例", "date": "2026-03-11", "source": "公众号", "content": "内容", "relevance_score": 0.9}]},
            "message": "",
        }
        result = mcp_server.search_knowledge_base("A股", top_k=1)
    assert "标题: 示例" in result
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_mcp_adapter.McpAdapterTests.test_search_tool_forwards_to_remote_api -v`
Expected: FAIL because `mcp_server.py` still executes local logic.

**Step 3: Write minimal implementation**

Refactor `scripts/mcp_server.py` so each tool:

- reads `JASON_KB_API_BASE_URL`
- reads `JASON_KB_API_TOKEN`
- sends HTTP requests with `Authorization: Bearer ...`
- handles network, auth, and bad-response failures clearly
- formats returned JSON back into the current string output shape

Do not change the tool names or public function signatures unless absolutely necessary.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_mcp_adapter.McpAdapterTests.test_search_tool_forwards_to_remote_api -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_mcp_adapter.py scripts/mcp_server.py
git commit -m "feat: convert local MCP server into remote API adapter"
```

### Task 7: Add Adapter Coverage For All Tool Mappings

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\tests\test_mcp_adapter.py`
- Modify: `C:\Users\69050\.claude\skills\jason-kb\scripts\mcp_server.py`

**Step 1: Write the failing tests**

Add one failing mapping test for each remaining tool:

- `get_financial_profile`
- `update_financial_profile`
- `ingest_article`
- `ingest_all_raw`
- `trigger_crawl`
- `get_recent_articles`
- `get_advice_history`
- `save_advice`

Each test should assert:

- correct HTTP method
- correct route
- correct request body / query params
- correct response formatting

**Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_mcp_adapter -v`
Expected: FAIL for unmapped tools.

**Step 3: Write minimal implementation**

Fill in the missing forwarding logic. Reuse helper functions for:

- auth headers
- POST/GET sending
- JSON decoding
- standard error formatting

Avoid per-tool copy/paste where a small helper suffices.

**Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_mcp_adapter -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_mcp_adapter.py scripts/mcp_server.py
git commit -m "test: cover all MCP adapter tool mappings"
```

### Task 8: Update Deployment Entry Point For Remote API

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\Dockerfile`
- Modify: `C:\Users\69050\.claude\skills\jason-kb\compose.tencent.yml`
- Modify: `C:\Users\69050\.claude\skills\jason-kb\.env.tencent.example`
- Modify: `C:\Users\69050\.claude\skills\jason-kb\docs\deploy-tencent-lighthouse.md`
- Test: `C:\Users\69050\.claude\skills\jason-kb\tests\test_deploy_plan.py`

**Step 1: Write the failing test**

Add a test that asserts the deployed command path starts the remote API server rather than the old SSE server.

Example:

```python
def test_deploy_docs_and_runtime_use_api_server():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python scripts/api_server.py" in dockerfile
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_deploy_plan.DeployPlanTests.test_deploy_docs_and_runtime_use_api_server -v`
Expected: FAIL because deployment still boots `mcp_server.py`.

**Step 3: Write minimal implementation**

Update the deploy path so the server container runs the remote API service. Keep the local MCP adapter as a local-only process, not the public deployment target.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_deploy_plan.DeployPlanTests.test_deploy_docs_and_runtime_use_api_server -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_deploy_plan.py Dockerfile compose.tencent.yml .env.tencent.example docs/deploy-tencent-lighthouse.md
git commit -m "chore: deploy remote API instead of SSE MCP server"
```

### Task 9: Write End-User Setup Documentation

**Files:**
- Modify: `C:\Users\69050\.claude\skills\jason-kb\README.md`
- Create: `C:\Users\69050\.claude\skills\jason-kb\docs\deploy-remote-api.md`
- Create: `C:\Users\69050\.claude\skills\jason-kb\docs\connect-claude-skill.md`

**Step 1: Write the failing test**

Add a simple documentation smoke test that checks the new docs mention:

- `JASON_KB_API_BASE_URL`
- `JASON_KB_API_TOKEN`
- remote API verification with `curl`

If no doc test exists yet, add one in `tests/test_deploy_plan.py`.

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_deploy_plan -v`
Expected: FAIL because the docs do not exist yet.

**Step 3: Write minimal implementation**

Document for a first-time user:

- what to deploy remotely
- how to configure token and base URL
- how to verify remote API health
- how to configure the local adapter environment
- how to confirm the skill works with natural language in Claude

Keep the docs procedural and explicit. Assume the reader has never deployed `jasonAI` skills before.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_deploy_plan -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_deploy_plan.py README.md docs/deploy-remote-api.md docs/connect-claude-skill.md
git commit -m "docs: add remote API deployment and Claude setup guides"
```

### Task 10: Full Verification and Integration Check

**Files:**
- Verify: `C:\Users\69050\.claude\skills\jason-kb\tests\test_api_server.py`
- Verify: `C:\Users\69050\.claude\skills\jason-kb\tests\test_mcp_adapter.py`
- Verify: `C:\Users\69050\.claude\skills\jason-kb\tests\test_deploy_plan.py`

**Step 1: Run the focused test suites**

Run:

```bash
python -m unittest tests.test_api_server -v
python -m unittest tests.test_mcp_adapter -v
python -m unittest tests.test_deploy_plan -v
```

Expected: all PASS

**Step 2: Run the full suite**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all PASS

**Step 3: Perform a manual smoke verification**

Run the remote API locally:

```bash
python scripts/api_server.py
```

Then in another shell:

```bash
curl -i http://127.0.0.1:8080/healthz
curl -i -H "Authorization: Bearer test-token" -H "Content-Type: application/json" -d "{\"query\":\"A股\",\"top_k\":1}" http://127.0.0.1:8080/api/kb/search
```

Run the local adapter with `JASON_KB_API_BASE_URL` and `JASON_KB_API_TOKEN` set, then verify one forwarded tool call works.

**Step 4: Commit final cleanup if needed**

If any documentation or test adjustments were required during verification:

```bash
git add .
git commit -m "chore: finalize remote API adapter verification"
```

Only commit if there were actual changes.
