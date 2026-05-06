"""Patch graphiti_core falkordb edge/episode fulltext search Cypher.

Background
----------
The shipped Cypher for edge_fulltext_search and episode_fulltext_search
applies WHERE/MATCH/RETURN before LIMIT, so all fulltext hits pay endpoint
lookup cost before LIMIT trims to top-N. On a graph with ~7k RELATES_TO
edges, even single-token queries time out at 15s.

Measurement on the live flowmesh graph (2023 nodes / 7339 rels):
- shipped pattern (MATCH then ORDER BY/LIMIT)         -> 15s timeout
- LIMIT-before-MATCH                                  -> ~378ms
- skip MATCH entirely (use rel.source/target_node_uuid) -> ~2.6ms

This patch rewrites both functions to:
  1. Use rel/episode directly (rebind to `e`) without MATCH.
  2. Apply WHERE/ORDER BY/LIMIT before RETURN.
  3. For edge_fulltext_search, return source_node_uuid/target_node_uuid
     from edge attributes (the edge has these fields persisted).
  4. Fall back to the original MATCH-based path only when node_labels
     filter is set (which requires endpoint label inspection).
"""

from pathlib import Path

PATH = Path(
    '/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/driver/falkordb/operations/search_ops.py'
)
text = PATH.read_text()

if 'GRAPHITI_FAST_FULLTEXT_PATCH' in text:
    print('search_ops.py already patched')
    raise SystemExit(0)

# ---------- Patch edge_fulltext_search ----------
edge_old = """        cypher = (
            get_relationships_query(
                'edge_name_and_fact', limit=limit, provider=GraphProvider.FALKORDB
            )
            + \"\"\"
            YIELD relationship AS rel, score
            MATCH (n:Entity)-[e:RELATES_TO {uuid: rel.uuid}]->(m:Entity)
            \"\"\"
            + filter_query
            + \"\"\"
            WITH e, score, n, m
            RETURN
            \"\"\"
            + get_entity_edge_return_query(GraphProvider.FALKORDB)
            + \"\"\"
            ORDER BY score DESC
            LIMIT $limit
            \"\"\"
        )"""

edge_new = """        # GRAPHITI_FAST_FULLTEXT_PATCH: avoid MATCH on every hit; rely on
        # source_node_uuid/target_node_uuid stored on the edge. Falls back
        # to original MATCH path only when node_labels filter is present
        # (label predicates require endpoint nodes).
        _needs_endpoints = any(
            ('n:' in fq) or ('m:' in fq) or ('n.labels' in fq) or ('m.labels' in fq)
            for fq in filter_queries
        )
        if _needs_endpoints:
            cypher = (
                get_relationships_query(
                    'edge_name_and_fact', limit=limit, provider=GraphProvider.FALKORDB
                )
                + \"\"\"
                YIELD relationship AS rel, score
                WITH rel, score
                ORDER BY score DESC
                LIMIT $limit
                MATCH (n:Entity)-[e:RELATES_TO {uuid: rel.uuid}]->(m:Entity)
                \"\"\"
                + filter_query
                + \"\"\"
                WITH e, score, n, m
                RETURN
                \"\"\"
                + get_entity_edge_return_query(GraphProvider.FALKORDB)
            )
        else:
            cypher = (
                get_relationships_query(
                    'edge_name_and_fact', limit=limit, provider=GraphProvider.FALKORDB
                )
                + \"\"\"
                YIELD relationship AS e, score
                \"\"\"
                + filter_query
                + \"\"\"
                WITH e, score
                ORDER BY score DESC
                LIMIT $limit
                RETURN
                    e.uuid AS uuid,
                    e.source_node_uuid AS source_node_uuid,
                    e.target_node_uuid AS target_node_uuid,
                    e.group_id AS group_id,
                    e.created_at AS created_at,
                    e.name AS name,
                    e.fact AS fact,
                    e.episodes AS episodes,
                    e.expired_at AS expired_at,
                    e.valid_at AS valid_at,
                    e.invalid_at AS invalid_at,
                    properties(e) AS attributes
                \"\"\"
            )"""

if edge_old not in text:
    raise SystemExit('edge_fulltext_search anchor not found')
text = text.replace(edge_old, edge_new, 1)

# ---------- Patch episode_fulltext_search ----------
episode_old = """        filter_params: dict[str, Any] = {}
        group_filter_query = ''
        if group_ids is not None:
            group_filter_query += '\\nAND e.group_id IN $group_ids'
            filter_params['group_ids'] = group_ids

        cypher = (
            get_nodes_query(
                'episode_content', '$query', limit=limit, provider=GraphProvider.FALKORDB
            )
            + \"\"\"
            YIELD node AS episode, score
            MATCH (e:Episodic)
            WHERE e.uuid = episode.uuid
            \"\"\"
            + group_filter_query
            + \"\"\"
            RETURN
            \"\"\"
            + EPISODIC_NODE_RETURN
            + \"\"\"
            ORDER BY score DESC
            LIMIT $limit
            \"\"\"
        )"""

episode_new = """        # GRAPHITI_FAST_FULLTEXT_PATCH: drop redundant MATCH, apply
        # WHERE / ORDER BY / LIMIT before RETURN.
        filter_params: dict[str, Any] = {}
        group_filter_query = ''
        if group_ids is not None:
            group_filter_query += 'WHERE e.group_id IN $group_ids'
            filter_params['group_ids'] = group_ids

        cypher = (
            get_nodes_query(
                'episode_content', '$query', limit=limit, provider=GraphProvider.FALKORDB
            )
            + \"\"\"
            YIELD node AS e, score
            \"\"\"
            + group_filter_query
            + \"\"\"
            WITH e, score
            ORDER BY score DESC
            LIMIT $limit
            RETURN
            \"\"\"
            + EPISODIC_NODE_RETURN
        )"""

if episode_old not in text:
    raise SystemExit('episode_fulltext_search anchor not found')
text = text.replace(episode_old, episode_new, 1)

PATH.write_text(text)
print('Patched edge_fulltext_search and episode_fulltext_search in search_ops.py')
