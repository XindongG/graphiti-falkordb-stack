"""Patch graphiti_core falkordb_driver.build_fulltext_query to cap OR-term count.

FalkorDB/RedisSearch becomes very expensive on long OR queries. Graphiti
dedup/search can produce 10+ keyword OR queries that take 20s+ even on
small graphs. Cap OR-term count via FALKORDB_FULLTEXT_MAX_TERMS env
(default 6) to keep p99 search latency bounded.

Also targets the actual hot-path file (falkordb_driver.py); a previous
patch in this image was applied to falkordb/operations/search_ops.py
which is not on the runtime path and had no effect.
"""
from pathlib import Path

path = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/driver/falkordb_driver.py')
text = path.read_text()

if 'cap OR-term count' in text:
    print('falkordb_driver.py already patched, skipping')
    raise SystemExit(0)

if 'import os\n' not in text:
    text = text.replace('import logging\n', 'import logging\nimport os\n', 1)

old = (
    "        # Remove stopwords and empty tokens from the sanitized query\n"
    "        query_words = sanitized_query.split()\n"
    "        filtered_words = [word for word in query_words if word and word.lower() not in STOPWORDS]\n"
    "        sanitized_query = ' | '.join(filtered_words)\n"
)

new = (
    "        # Remove stopwords/short noise tokens and cap OR-term count.\n"
    "        # FalkorDB/RedisSearch becomes very expensive on long OR queries\n"
    "        # (Graphiti dedup/search can produce 10+ keyword OR queries that\n"
    "        # take 20s+ even on small graphs). Cap to keep p99 bounded.\n"
    "        query_words = sanitized_query.split()\n"
    "        filtered_words = [\n"
    "            word for word in query_words\n"
    "            if word and len(word) > 1 and word.lower() not in STOPWORDS\n"
    "        ]\n"
    "        max_terms = int(os.environ.get('FALKORDB_FULLTEXT_MAX_TERMS', '6'))\n"
    "        if max_terms > 0:\n"
    "            filtered_words = filtered_words[:max_terms]\n"
    "        sanitized_query = ' | '.join(filtered_words)\n"
)

if old not in text:
    raise SystemExit('build_fulltext_query anchor not found in falkordb_driver.py')

text = text.replace(old, new)
path.write_text(text)
print('Patched falkordb_driver.py: capped OR-term count via FALKORDB_FULLTEXT_MAX_TERMS')
