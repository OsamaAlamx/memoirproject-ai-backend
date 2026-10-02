"""Shared helper to attach media assets to memories without PostgREST embeds.

The staging schema cache has no FK relationship between `memory` and
`memory_media` (PGRST200), so `memory_media(media_asset(...))` embeds fail.
These helpers fetch the junction + asset rows separately and join in Python,
returning the same `memory_media: [{..., media_asset: {...}}]` shape the
domain services already consume.
"""

from typing import List, Dict, Any

from src.integrations.supabase_client import supabase_admin


def attach_media_assets(memories: List[Dict[str, Any]], memoir_id: str) -> List[Dict[str, Any]]:
    """Populate `memory_media` (with nested `media_asset`) for each memory."""
    ids = [m.get("id") for m in memories if m.get("id")]
    if not ids:
        for m in memories:
            m["memory_media"] = []
        return memories

    links_res = (
        supabase_admin.table("memory_media")
        .select("*")
        .eq("memoir_id", str(memoir_id))
        .in_("memory_id", ids)
        .execute()
    )
    links = links_res.data or []

    asset_ids = list({l.get("media_asset_id") for l in links if l.get("media_asset_id")})
    assets: Dict[str, Dict[str, Any]] = {}
    if asset_ids:
        assets_res = supabase_admin.table("media_asset").select("*").in_("id", asset_ids).execute()
        assets = {a["id"]: a for a in (assets_res.data or [])}

    by_memory: Dict[str, List[Dict[str, Any]]] = {}
    for link in links:
        by_memory.setdefault(link.get("memory_id"), []).append(
            {**link, "media_asset": assets.get(link.get("media_asset_id"))}
        )

    for m in memories:
        m["memory_media"] = by_memory.get(m.get("id"), [])
    return memories
