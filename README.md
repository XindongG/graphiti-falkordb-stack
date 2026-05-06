# graphiti-falkordb-stack

A drop-in MCP knowledge-graph stack:

- **FalkorDB** as the graph store (Redis-protocol, persistent)
- **3 isolated Graphiti instances** on ports 8001 / 8002 / 8003 (`flowmesh`,
  `company`, `personal_kb` — pick names that fit your workflow)
- **Patched `graphiti-core` 0.28.2** that fixes a 15-second timeout bug in
  upstream `edge_fulltext_search` on FalkorDB. See [PATCHES.md](PATCHES.md).

End-to-end search latency on a graph with ~7000 edges drops from "every
call times out at 15 s" to under 100 ms.

## Quick start

```bash
git clone https://github.com/XindongG/graphiti-falkordb-stack
cd graphiti-falkordb-stack

cp .env.example .env
# Edit .env. At minimum set:
#   FALKORDB_PASSWORD              (openssl rand -hex 32)
#   FALKORDB_BROWSER_ENCRYPTION_KEY (openssl rand -hex 16)
#   OPENAI_API_KEY / OPENAI_API_URL                  (your LLM endpoint)
#   OPENAI_EMBEDDING_API_KEY / OPENAI_EMBEDDING_API_URL  (your embedding endpoint)

docker compose up -d
sleep 30
for p in 8001 8002 8003; do curl -s -w '%{http_code}\n' http://127.0.0.1:$p/health; done
# Should print 200 three times.
```

## What you get

| Endpoint                | Service                                                |
| ----------------------- | ------------------------------------------------------ |
| `http://BIND_HOST:8001` | Graphiti MCP for the `flowmesh` graph                  |
| `http://BIND_HOST:8002` | Graphiti MCP for the `company_project` graph           |
| `http://BIND_HOST:8003` | Graphiti MCP for the `personal_kb` graph               |
| `http://BIND_HOST:8300` | FalkorDB Browser web UI (optional, password-protected) |

`BIND_HOST` defaults to `127.0.0.1` (local only). To expose on a private
LAN or Tailscale interface, set `BIND_HOST` in `.env`.

## MCP client configuration

Point your MCP client at `http://BIND_HOST:8001/mcp`,
`http://BIND_HOST:8002/mcp`, `http://BIND_HOST:8003/mcp`.

For Claude Code, an example `~/.claude/settings.json` snippet:

```json
{
  "mcpServers": {
    "graphiti-flowmesh": {
      "type": "http",
      "url": "http://127.0.0.1:8001/mcp"
    },
    "graphiti-company": {
      "type": "http",
      "url": "http://127.0.0.1:8002/mcp"
    },
    "graphiti-personal-kb": {
      "type": "http",
      "url": "http://127.0.0.1:8003/mcp"
    }
  }
}
```

## System requirements

- Docker 24+ with the `compose` plugin (v2)
- 4 cores / 8 GB RAM minimum (the FalkorDB container is allowed up to
  3 cores / 3 GB, each Graphiti up to 0.7 cores / 768 MB)
- Outbound network access to your LLM and embedding API endpoints
- Recommended: 8 GB swap and `vm.swappiness=10` (FalkorDB doesn't swap
  itself but other tenants on the box might OOM otherwise):
  ```bash
  fallocate -l 8G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  ```

## Data, persistence, and backup

The FalkorDB container persists to `./data/falkordb-live/` on the host
(RDB + AOF, AOF flushed every second). Everything else is stateless.

To back up:

```bash
# 1) ask the daemon to flush
docker exec agent-memory-falkordb redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning BGREWRITEAOF
docker exec agent-memory-falkordb redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning BGSAVE
sleep 5
# 2) tar the on-disk state
mkdir -p backups
tar -czf "backups/falkordb-$(date +%Y%m%d-%H%M%S).tar.gz" -C data falkordb-live
```

To restore: stop the stack, replace `./data/falkordb-live/` with the
extracted tarball contents, start the stack.

## Building from source instead of pulling

If you want to verify or modify the patches:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d
```

This builds the image locally from `docker/graphiti-ark/` instead of
pulling `xindongg/graphiti-falkordb-fast` from Docker Hub.

## What was fixed vs. upstream graphiti-core

See [PATCHES.md](PATCHES.md). Three patches:

1. Cap fulltext OR-term count (`FALKORDB_FULLTEXT_MAX_TERMS`, default 6)
2. Skip / reorder the `MATCH` in `edge_fulltext_search` and
   `episode_fulltext_search`
3. Bind `FalkorDriver.search_interface` to the patched
   `FalkorSearchOperations` so the high-level dispatcher actually uses
   patch #2 (without this one, the other patches are dead code at the
   `client.search()` level)

## License

Apache-2.0. The patches are derivative work on `graphiti-core` (Apache-2.0).
See [LICENSE](LICENSE) and [NOTICE](NOTICE).
