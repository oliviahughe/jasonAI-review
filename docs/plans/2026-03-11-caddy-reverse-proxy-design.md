# Jason-KB Reverse Proxy Design

Date: 2026-03-11
Topic: Expose remote `jason-kb` through Caddy instead of public port `8080`
Status: Approved

## Context

The remote `jason-kb` container is healthy and listening on `127.0.0.1:8080` via Docker port mapping. External access to `http://101.32.219.232:8080/mcp` fails because that port is intentionally bound to localhost on the server.

The service itself is reachable from the server host and responds as an authenticated streamable HTTP MCP endpoint. The remaining gap is external routing, not container startup.

## Goal

Provide a stable external MCP endpoint for Codex without exposing container port `8080` directly to the public internet.

## Recommended Approach

Use Caddy as the public reverse proxy:

- Keep Docker mapping as `127.0.0.1:8080:8080`
- Expose `https://<domain>/mcp` through Caddy
- Proxy requests to `127.0.0.1:8080`
- Keep Bearer token auth enforced by `jason-kb`
- Update local Codex MCP config to the HTTPS domain URL

## Alternatives Considered

### 1. Publicly expose `8080`

Pros:
- Fastest temporary connectivity test

Cons:
- Weakens network exposure
- Deviates from existing deployment docs
- Not preferred for long-term operation

### 2. Switch to Nginx

Pros:
- Common reverse proxy choice

Cons:
- Adds unnecessary divergence from current repo guidance
- No benefit over Caddy for this deployment

## Architecture

### Internal path

- Docker container listens on `0.0.0.0:8080`
- Host maps it to `127.0.0.1:8080`

### External path

- Caddy listens on `80/443`
- Requests to `https://<domain>/mcp` are proxied to `http://127.0.0.1:8080/mcp`

### Authentication

- Caddy does not terminate or replace Bearer auth semantics
- `jason-kb` continues to validate `Authorization: Bearer <AUTH_TOKEN>`

## Implementation Scope

- Inspect server Caddy installation and active site config
- Add or update the site block for the chosen domain
- Reload Caddy
- Update local Codex MCP URL from public IP to HTTPS domain

## Verification

Success means:

- `jason-kb` remains private on host loopback
- `https://<domain>/mcp` is externally reachable
- Codex points to the HTTPS URL instead of `http://101.32.219.232:8080/mcp`
- MCP startup no longer fails due to connection resets

## Risks

### Missing domain or DNS

If no domain resolves to the server, Caddy cannot provide the intended HTTPS endpoint.

### Proxy header compatibility

If the client still fails after reverse proxying, the next issue to inspect is HTTP header compatibility around MCP stream negotiation.
