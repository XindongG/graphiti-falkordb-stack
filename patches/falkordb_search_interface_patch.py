"""Wire FalkorDriver.search_interface to FalkorSearchOperations.

The shipped FalkorDriver instantiates FalkorSearchOperations but doesn't
assign it to self.search_interface, so search_utils.edge_fulltext_search
(and friends) never see it and fall through to inline Cypher with the
slow MATCH-before-LIMIT pattern. This patch binds the existing instance
so all high-level search routes through the patched implementation.
"""
from pathlib import Path

PATH = Path('/app/mcp/.venv/lib/python3.11/site-packages/graphiti_core/driver/falkordb_driver.py')
text = PATH.read_text()

if 'self.search_interface = self._search_ops' in text:
    print('FalkorDriver.search_interface already bound')
    raise SystemExit(0)

anchor = '        self._search_ops = FalkorSearchOperations()\n'
replacement = (
    '        self._search_ops = FalkorSearchOperations()\n'
    '        # GRAPHITI_FAST_FULLTEXT_PATCH: bind search_interface so\n'
    '        # search_utils dispatchers route through the patched class.\n'
    '        self.search_interface = self._search_ops\n'
)

if anchor not in text:
    raise SystemExit('FalkorSearchOperations() init line not found')

text = text.replace(anchor, replacement, 1)
PATH.write_text(text)
print('Bound FalkorDriver.search_interface to _search_ops')
