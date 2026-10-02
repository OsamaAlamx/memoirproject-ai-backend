"""
@file integrations/search_repository.py
@description Executes full-text search queries against PostgreSQL search vectors.
"""

from src.integrations.supabase_client import supabase_admin

def search_memoir_content(memoir_id: str, query_text: str):
    """
    Calls a Postgres RPC function to perform a full-text search
    across memories, transcripts, and media captions filtered by memoir_id.
    Falls back to ILIKE search when the RPC is missing from the schema cache.
    """
    try:
        response = supabase_admin.rpc(
            "search_memoirs_fts",
            {
                "target_memoir_id": memoir_id,
                "search_query": query_text
            }
        ).execute()

        return response.data if response.data else []
    except Exception as e:
        if "PGRST202" not in str(e) and "schema cache" not in str(e):
            raise
        # Fallback: plain ILIKE over memory text (no RPC in staging).
        # Only alphanumeric tokens reach PostgREST, and any backend/WAF
        # rejection degrades to empty results instead of a 500.
        import re
        words = re.findall(r"[A-Za-z0-9]+", query_text)[:10]
        if not words:
            return []
        pattern = "%{}%".format(" ".join(words)[:200])
        try:
            mems = supabase_admin.table("memory")\
                .select("id, title, body_text, occurred_start")\
                .eq("memoir_id", memoir_id)\
                .is_("deleted_at", "null")\
                .or_("title.ilike.{0},body_text.ilike.{0}".format(pattern))\
                .limit(50)\
                .execute()
        except Exception:
            return []
        return [{**m, "source": "memory"} for m in (mems.data or [])]