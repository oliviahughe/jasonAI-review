# Jason-KB Reverse Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose remote `jason-kb` through a Caddy-managed HTTPS endpoint and update Codex to use that endpoint instead of the public IP on port `8080`.

**Architecture:** Keep the MCP container private on `127.0.0.1:8080`, let Caddy publish `https://<domain>/mcp`, and preserve Bearer auth enforcement inside `jason-kb`. Update the local Codex MCP config only after the proxy path is verified from the server and from the client machine.

**Tech Stack:** Docker Compose, Caddy, OpenSSH, PowerShell, Codex MCP config

---

### Task 1: Inspect server reverse-proxy state

**Files:**
- Check: server Caddy service status
- Check: server Caddy config files

**Step 1: Check whether Caddy is installed and running**

Run:

```bash
systemctl status caddy --no-pager
```

Expected: service exists and shows `active (running)` or a clear missing-service error.

**Step 2: Inspect active Caddy configuration**

Run:

```bash
sudo cat /etc/caddy/Caddyfile
sudo ls -la /etc/caddy
```

Expected: identify whether a site block already exists for the desired domain.

**Step 3: Check current DNS target from the client side**

Run:

```powershell
nslookup <domain>
```

Expected: the domain resolves to `101.32.219.232`.

**Step 4: Commit**

Do not commit. This task is inspection only.

### Task 2: Add or update the Caddy site block

**Files:**
- Modify: `/etc/caddy/Caddyfile` on the server

**Step 1: Prepare the desired site block**

Use this minimal structure:

```caddy
<domain> {
    encode gzip
    reverse_proxy 127.0.0.1:8080
}
```

**Step 2: Validate configuration before reload**

Run:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

Expected: validation succeeds with no syntax errors.

**Step 3: Reload Caddy**

Run:

```bash
sudo systemctl reload caddy
```

Expected: reload succeeds without downtime.

**Step 4: Verify HTTPS route from the server**

Run:

```bash
curl -i https://<domain>/mcp
curl -i -H "Authorization: Bearer <AUTH_TOKEN>" https://<domain>/mcp
```

Expected:
- first call returns `401 Unauthorized`
- second call reaches the MCP app and no longer fails at the TCP layer

**Step 5: Commit**

No git commit required because the server config is outside the repo.

### Task 3: Update local Codex MCP configuration

**Files:**
- Modify: `C:\Users\69050\.codex\config.toml`

**Step 1: Write the config change**

Change:

```toml
[mcp_servers.jason-kb]
url = "http://101.32.219.232:8080/mcp"
```

to:

```toml
[mcp_servers.jason-kb]
url = "https://<domain>/mcp"
```

Leave the `Authorization` header unchanged.

**Step 2: Verify the file was updated correctly**

Run:

```powershell
Get-Content C:\Users\69050\.codex\config.toml
```

Expected: `jason-kb` points to the HTTPS domain URL.

**Step 3: Restart or reload the Codex client**

Expected: the client re-reads MCP configuration.

**Step 4: Verify MCP startup**

Expected: `jason-kb` no longer fails with a connection reset during startup.

**Step 5: Commit**

No git commit required because the file is user-local configuration.

### Task 4: Diagnose any remaining MCP negotiation issue

**Files:**
- Check: server Caddy access/error logs
- Check: `docker compose -f compose.tencent.yml logs -f jason-kb`

**Step 1: Reproduce one MCP startup attempt after switching to HTTPS**

Expected: one matching request appears in Caddy and container logs.

**Step 2: If startup still fails, capture HTTP response semantics**

Check whether the server returns `401`, `406`, or `400`, and whether the client is sending the expected `Accept` headers.

**Step 3: Only after evidence, decide next fix**

Expected: the next change targets a confirmed protocol/header issue rather than networking.

**Step 4: Commit**

Do not commit. This task is investigation only.
