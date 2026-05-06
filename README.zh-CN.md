<!-- markdownlint-disable MD041 -->

[English](README.md) | **简体中文**

# graphiti-falkordb-stack

开箱即用的 MCP 知识图谱栈：

- **FalkorDB** 作为底层图存储（Redis 协议，自带持久化）
- **3 个独立 Graphiti 实例** 监听 8001 / 8002 / 8003 端口（默认命名 `flowmesh`、
  `company_project`、`personal_kb`，可按你自己的工作流改）
- **打过补丁的 `graphiti-core` 0.28.2**，修复了上游 `edge_fulltext_search`
  在 FalkorDB 上 15 秒超时的硬伤。详见 [PATCHES.md](PATCHES.md)。

在一张 7000 条边规模的真实图上，端到端搜索延迟从"每次都 15 秒超时"降到了 100 ms 以内。

## 快速开始

```bash
git clone https://github.com/XindongG/graphiti-falkordb-stack
cd graphiti-falkordb-stack

cp .env.example .env
# 至少要在 .env 里填这些：
#   FALKORDB_PASSWORD              （生成: openssl rand -hex 32）
#   FALKORDB_BROWSER_ENCRYPTION_KEY（生成: openssl rand -hex 16）
#   OPENAI_API_KEY / OPENAI_API_URL                       （你的 LLM 端点）
#   OPENAI_EMBEDDING_API_KEY / OPENAI_EMBEDDING_API_URL   （你的 embedding 端点）

docker compose up -d
sleep 30
for p in 8001 8002 8003; do curl -s -w '%{http_code}\n' http://127.0.0.1:$p/health; done
# 应该输出三个 200。
```

## 启动后你拥有什么

| 端点                    | 服务                                    |
| ----------------------- | --------------------------------------- |
| `http://BIND_HOST:8001` | Graphiti MCP，对应 `flowmesh` 图        |
| `http://BIND_HOST:8002` | Graphiti MCP，对应 `company_project` 图 |
| `http://BIND_HOST:8003` | Graphiti MCP，对应 `personal_kb` 图     |
| `http://BIND_HOST:8300` | FalkorDB Browser 网页端 UI（可选）      |

`BIND_HOST` 默认 `127.0.0.1`（仅本机访问）。如果想暴露给局域网或 Tailscale，
直接在 `.env` 里改 `BIND_HOST`。

## MCP 客户端配置

把 MCP 客户端指向 `http://BIND_HOST:8001/mcp`、`http://BIND_HOST:8002/mcp`、
`http://BIND_HOST:8003/mcp` 即可。

以 Claude Code 为例，`~/.claude/settings.json` 里这样写：

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

## 系统要求

- Docker 24+ 含 `compose` 插件（v2）
- 本地全新启动最低需要 Docker 分配 1 个 CPU / 8 GB 内存。生产环境或更大的图
  建议 4 核以上。
- 资源限制在 `.env` 中配置。默认值刻意偏保守，方便低配 Docker Desktop / CI
  环境也能启动：FalkorDB 最多 1 CPU / 3 GB，每个 Graphiti 最多
  0.7 CPU / 768 MB。更高配置机器可以调大 `FALKORDB_CPUS`、
  `GRAPHITI_CPUS` 以及对应内存变量。
- 能访问你的 LLM 和 embedding API 出口
- 推荐配置 8 GB swap + `vm.swappiness=10`（FalkorDB 自己不会进 swap，
  但同机其他容器/服务可能需要 swap 兜底防 OOM）：

  ```bash
  fallocate -l 8G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  ```

## 数据持久化与备份

FalkorDB 容器把状态持久到宿主目录 `./data/falkordb-live/`（RDB + AOF，
AOF 每秒 flush）。其他容器都是无状态的。

备份：

```bash
# 1) 先让 daemon 把内存状态落盘
docker exec agent-memory-falkordb redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning BGREWRITEAOF
docker exec agent-memory-falkordb redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning BGSAVE
sleep 5
# 2) 打 tar 包
mkdir -p backups
tar -czf "backups/falkordb-$(date +%Y%m%d-%H%M%S).tar.gz" -C data falkordb-live
```

恢复：先 `docker compose down`，把 `./data/falkordb-live/` 替换成解开的 tar
内容，再 `docker compose up -d`。

## 不想拉镜像，想从源码 build

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d
```

这样会用 `docker/graphiti-ark/` 下的 Dockerfile 在本地 build，不再从
Docker Hub 拉 `xindongg/graphiti-falkordb-fast`。适合你想 review 或者改 patch
的场景。

## 相比上游 graphiti-core 改了什么

详见 [PATCHES.md](PATCHES.md)。一共 3 个补丁：

1. 限制 fulltext 查询的 OR-term 数量（环境变量 `FALKORDB_FULLTEXT_MAX_TERMS`，
   默认 6）
2. `edge_fulltext_search` 和 `episode_fulltext_search` 里把 `MATCH` 从 ORDER BY
   之前移到之后，or 直接跳过 `MATCH` 改用边的属性字段
3. 在 `FalkorDriver.__init__` 里把 `search_interface` 绑到已经修好的
   `FalkorSearchOperations`——上游忘绑了这一行，导致 `client.search()` 高层
   调度直接绕过补丁，跑了 search_utils.py 里另一份 inline 的 broken Cypher

## License

Apache-2.0。补丁是对 `graphiti-core`（Apache-2.0）的衍生修改。
详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
