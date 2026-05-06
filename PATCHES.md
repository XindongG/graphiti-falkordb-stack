# Patches applied on top of graphiti-core 0.28.2

The pre-built image `xindongg/graphiti-falkordb-fast:0.28.2-anthropic`
applies three small Python patches to `graphiti_core` at image build time.
Each patch is in `docker/graphiti-ark/`. They address real bugs / pathological
behaviour in upstream graphiti's FalkorDB integration.

If you build from source (`docker-compose.build.yml`), the same patches are
applied. If you bypass the image and `pip install graphiti-core` directly,
none of these fixes apply and you will hit the bugs described below.

## 1. `falkordb_driver_patch.py` — cap fulltext OR-term count

**File patched:** `graphiti_core/driver/falkordb_driver.py` →
`FalkorDriver.build_fulltext_query`

**Bug:** Graphiti's hybrid search constructs queries like
`(@group_id:"X") (term1 | term2 | ... | term12)`. RedisSearch on FalkorDB
becomes very expensive past ~6 OR terms; even on small graphs the latency
goes from milliseconds to tens of seconds.

**Fix:** Drop one-character noise tokens, then cap the OR-term list to
`FALKORDB_FULLTEXT_MAX_TERMS` (default 6, set to 0 to disable). The cap
is read at query-build time, not baked in.

## 2. `falkordb_search_patch.py` — limit before match in fulltext search

**File patched:** `graphiti_core/driver/falkordb/operations/search_ops.py` →
`FalkorSearchOperations.edge_fulltext_search` and
`FalkorSearchOperations.episode_fulltext_search`

**Bug (edge):** the shipped Cypher does `MATCH (n)-[e:RELATES_TO]->(m)`
on every fulltext hit _before_ `ORDER BY score DESC LIMIT N`. With ~7000
edges in a graph this times out at any LIMIT or token count. Even a
single-token query did not return within 15 s in our measurements.

**Fix (edge):** when no `node_labels` filter is set, skip the MATCH
entirely and read `source_node_uuid` / `target_node_uuid` directly from
the edge attributes (which Graphiti already persists). Result:
`edge_fulltext_search` drops from "always 15 s timeout" to ~3 ms at the
FalkorDB layer (~50 ms end-to-end including the Python driver overhead).
When `node_labels` is set, fall back to a MATCH path with `LIMIT` placed
before `MATCH` so we only do endpoint lookups for the top-N rows.

**Fix (episode):** drop the redundant `MATCH (e:Episodic) WHERE
e.uuid = episode.uuid` rebind and apply `WHERE / ORDER BY / LIMIT`
before `RETURN`. Dropped from ~0.9 ms to ~0.3 ms (small graph; the saved
work scales with node count).

## 3. `falkordb_search_interface_patch.py` — wire the patched class in

**File patched:** `graphiti_core/driver/falkordb_driver.py` →
`FalkorDriver.__init__`

**Bug:** Upstream `FalkorDriver` instantiates `FalkorSearchOperations`
into `self._search_ops` but never assigns it to
`self.search_interface`. The high-level dispatcher in
`graphiti_core/search/search_utils.py::edge_fulltext_search` checks
`if driver.search_interface:` first, falls through when it is `None`,
and runs an _inline copy_ of the same broken Cypher pattern. This means
patch #2 alone has no effect at the application level — every search
path through `client.search(...)` (which is what the MCP `search_memory_facts`
tool calls) bypasses it.

**Fix:** one line — `self.search_interface = self._search_ops` after the
existing instantiation. With this, all high-level search paths route
through patch #2 above.

---

## End-to-end measurement (real-world graph: ~2000 nodes, ~7300 edges)

| call                                | upstream       | this image |
| ----------------------------------- | -------------- | ---------- |
| `edge_fulltext_search` (raw Cypher) | 15 s timeout   | ~3 ms      |
| `search_memory_facts` (MCP)         | 15 s timeout   | <100 ms    |
| `search_nodes` (MCP)                | already OK     | unchanged  |
| `add_memory` (MCP)                  | OK (LLM-bound) | unchanged  |

The bottleneck shifts from FalkorDB query planning back to the LLM call
that extracts entities/relationships, which is where it should be.

## Upstream PR

These are real upstream bugs. If you find this useful, consider opening
a PR against [zepai/graphiti](https://github.com/getzep/graphiti) so this
fork doesn't have to live forever. The patches are isolated and the test
data above is straightforward to reproduce.
