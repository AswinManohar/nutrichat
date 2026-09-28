"""Contract tests for GET /foods/search and GET /foods/{fdc_id} (spec 003).

T002 finding: `resolve_local`/`usda_local.lookup` is a synchronous SQLite
read. The only existing async call site, `_fetch_one` in
`backend/agent/tools/usda.py` (~line 496), already wraps it in
`asyncio.to_thread(usda_local.lookup, entity.food_name, ...)` before
awaiting it -- it is never called directly from an `async def` without that
wrapper. The new `GET /foods/search` and `GET /foods/{fdc_id}` endpoints
(T017-T018) must follow the same pattern: call `usda_local.search_foods`
and `usda_local.get_food` via `asyncio.to_thread`, never directly, per
research R8 and `.claude/CLAUDE.md`'s "never call blocking functions from
async code" rule.
"""

from __future__ import annotations
