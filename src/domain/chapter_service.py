# src/domain/chapter_service.py
import json
import os
import httpx
from fastapi import HTTPException
from src.core.config import settings
from src.integrations.chapter_repository import (
    get_memories_for_organization,
    get_existing_chapters,
    apply_chapters_to_db,
)


class MCPServer:
    def __init__(self, memoir_id: str):
        self.memoir_id = memoir_id

    def get_resource(self, resource_name: str):
        if resource_name == "memories":
            return get_memories_for_organization(self.memoir_id)
        if resource_name == "chapters":
            return get_existing_chapters(self.memoir_id)
        raise ValueError(f"Unknown resource {resource_name}")

    def execute_tool(self, tool_name: str, payload: dict):
        if tool_name == "propose_chapter_set":
            return payload
        raise ValueError(f"Unknown tool {tool_name}")


class MCPClient:
    def __init__(self, server: MCPServer):
        self.server = server

    def read_resource(self, name: str):
        return self.server.get_resource(name)

    def call_tool(self, name: str, payload: dict):
        return self.server.execute_tool(name, payload)


def _call_llm_json(prompt: str) -> dict | None:
    api_key = settings.llm_api_key or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("LLM Error: No API key found in environment.")
        return None

    base_url = (settings.llm_base_url or "https://api.groq.com/openai/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    candidate_models = [
        settings.llm_model,
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3-32b",
        "moonshotai/kimi-k2-instruct",
    ]
    models_to_try = []
    for m in candidate_models:
        if m and m not in models_to_try:
            models_to_try.append(m)

    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a master biographer and memoir editor. "
                        "Always respond with valid JSON only. No markdown, no code fences."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.6, # Slightly increased for better creative flow
        }
        if "groq" in base_url or "openai" in base_url:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = httpx.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"].strip()
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                return json.loads(content.strip())
            print(f"LLM API Warning ({response.status_code}) model='{model}': {response.text[:300]}")
        except Exception as err:
            print(f"LLM Call error for model '{model}': {err}")

    return None


def _fallback_summary(facts: list) -> str:
    """Build a beautifully flowing fallback paragraph from the actual memory texts."""
    snippets = []
    for f in facts:
        text = (f.get("story_content") or f.get("title") or "").strip()
        if text:
            cut = text.replace("\n", " ")
            if len(cut) > 200:
                cut = cut[:200].rsplit(" ", 1)[0] + "…"
            snippets.append(cut)
    if not snippets:
        return "A collection of treasured family moments from this period of life. Every story preserved here adds a vital piece to the larger, beautiful puzzle of their journey."
    joined = " ".join(snippets)
    if len(joined) > 800:
        joined = joined[:800].rsplit(" ", 1)[0] + "…"
    return joined


def _fallback_title(era: str, facts: list) -> str:
    if facts:
        t = (facts[0].get("title") or "").strip()
        if t and len(t) < 60:
            return t.title() if t.islower() else t
    clean = (era or "Memories").replace("The ", "").strip()
    return f"Memories of the {clean}" if clean[0].isdigit() else clean


class ReaderAgent:
    def __init__(self, client: MCPClient):
        self.client = client

    def extract_facts(self):
        memories = self.client.read_resource("memories")
        
        # Sort chronologically to help the LLM establish a natural, ascending timeline
        memories = sorted(memories, key=lambda x: x.get("occurred_start") or "9999-12-31")

        prompt = f"""
Analyze these memoir entries. For each one extract structured facts.
{json.dumps(memories, indent=2)}

Return JSON exactly as:
{{
  "facts": [
    {{
      "id": "memory_uuid",
      "title": "entry title",
      "date": "YYYY-MM-DD or null",
      "chapter_id": "existing_chapter_id or null",
      "extracted_era": "e.g. 1980s, Childhood, College Years",
      "topic": "main theme",
      "story_content": "3-4 sentence summary of what happened (paraphrase, do not copy full text)"
    }}
  ]
}}
"""
        llm_res = _call_llm_json(prompt)
        if llm_res and "facts" in llm_res:
            return llm_res["facts"]

        facts = []
        for m in memories:
            date_val = m.get("occurred_start")
            extracted_era = "Timeless Memories"
            if date_val and len(str(date_val)) >= 4:
                year = str(date_val)[:4]
                if year.isdigit():
                    extracted_era = f"The {year[:3]}0s"

            body = m.get("body_text") or ""
            facts.append({
                "id": m["id"],
                "title": m.get("title") or "Untitled Entry",
                "date": m.get("occurred_start"),
                "chapter_id": m.get("chapter_id"),
                "extracted_era": extracted_era,
                "topic": m.get("title") or "Memory",
                "story_content": body[:400] if body else (m.get("title") or ""),
            })
        return facts


class OrganizerAgent:
    def __init__(self, client: MCPClient):
        self.client = client

    def propose(self, facts):
        existing_chapters = {c["id"]: c for c in self.client.read_resource("chapters")}

        prompt = f"""
You are a master biographer organizing a family memoir into beautiful, flowing chapters.

MEMORY FACTS:
{json.dumps(facts, indent=2)}

EXISTING CHAPTERS (if any):
{json.dumps(list(existing_chapters.values()), indent=2)}

STRICT RULES:
1. Create 3 to 6 chapters to beautifully cover the subject's life.
2. Order the chapters in STRICT ASCENDING CHRONOLOGICAL ORDER (e.g., Birth, Early Years, School, Adulthood, Later Life). Progress naturally through time.
3. Each chapter MUST have:
   - "title": a short original artistic title (e.g. "First Steps", "The Open Window"). NEVER use a raw memory title.
   - "summary": A rich, beautifully written, highly engaging biographical narrative (2 to 4 paragraphs) that synthesizes all memories in that chapter. Connect the dots into a smooth, flowing story. Do NOT just list memory titles. Make it read like a published biography.
   - "memories": array of {{ "id", "title", "date" }} for every memory placed in the chapter. Order these memories chronologically within the chapter!
4. Every memory id must appear in exactly one chapter.

Return JSON exactly as:
{{
  "chapters": [
    {{
      "title": "Original Chapter Title",
      "summary": "Rich synthesized biographical narrative paragraph 1.\\n\\nParagraph 2...",
      "memories": [
        {{ "id": "memory_id", "title": "entry title", "date": "date or null" }}
      ]
    }}
  ]
}}
"""
        llm_res = _call_llm_json(prompt)
        if llm_res and "chapters" in llm_res:
            return self.client.call_tool("propose_chapter_set", {"chapters": llm_res["chapters"]})

        buckets: dict[str, list] = {}
        for f in facts:
            key = f.get("extracted_era") or "Timeless Reflections"
            buckets.setdefault(key, []).append(f)

        # Guardrail: the fallback path must never produce ~1 chapter per memory.
        MAX_CHAPTERS = 6
        if len(facts) > MAX_CHAPTERS and len(buckets) > MAX_CHAPTERS:
            all_sorted = sorted(facts, key=lambda x: x.get("date") or "9999-12-31")
            chunk_size = max(2, -(-len(all_sorted) // MAX_CHAPTERS))  # ceil division
            buckets = {}
            for i in range(0, len(all_sorted), chunk_size):
                chunk = all_sorted[i:i + chunk_size]
                if not chunk:
                    continue
                label = chunk[0].get("extracted_era") or f"Chapter {i // chunk_size + 1}"
                buckets[f"{label}__{i}"] = chunk

        proposal = []
        for era, items in buckets.items():
            proposal.append({
                "title": _fallback_title(era, items),
                "summary": _fallback_summary(items),
                "memories": [
                    {
                        "id": it["id"],
                        "title": it.get("title") or "Untitled Entry",
                        "date": it.get("date"),
                    }
                    for it in items
                ],
            })
        return self.client.call_tool("propose_chapter_set", {"chapters": proposal})


class RefinerAgent:
    def __init__(self, client: MCPClient):
        self.client = client

    def refine(self, current_proposal, user_prompt):
        memories = self.client.read_resource("memories")

        prompt = f"""
You are refining a memoir chapter proposal based on the owner's chat request.

CURRENT PROPOSAL:
{json.dumps(current_proposal, indent=2)}

OWNER REQUEST:
"{user_prompt}"

RAW MEMORIES (reference only):
{json.dumps(memories, indent=2)}

RULES:
1. Apply the owner's request (merge/split/rename/retone as asked).
2. Ensure chapters remain in strict chronological ascending order.
3. Each chapter needs an original "title" and a rich, beautifully written biographical "summary" (2 to 4 paragraphs) covering all of its memories with smooth narrative flow. Do NOT copy full body text into the summary.
4. Keep every memory id assigned to exactly one chapter.

Return JSON exactly as:
{{
  "chapters": [
    {{
      "title": "Chapter Title",
      "summary": "Rich synthesized biographical paragraph 1.\\n\\nParagraph 2...",
      "memories": [
        {{ "id": "memory_id", "title": "entry title", "date": "date or null" }}
      ]
    }}
  ]
}}
"""
        llm_res = _call_llm_json(prompt)
        if llm_res and "chapters" in llm_res:
            return self.client.call_tool("propose_chapter_set", {"chapters": llm_res["chapters"]})
        return current_proposal


class ReviewerAgent:
    def __init__(self, client: MCPClient):
        self.client = client

    def review(self, proposal):
        seen = set()
        valid = []
        for ch in proposal.get("chapters", []):
            clean = []
            for m in ch.get("memories") or []:
                mid = m.get("id")
                if mid and mid not in seen:
                    clean.append({
                        "id": mid,
                        "title": m.get("title") or "Untitled Entry",
                        "date": m.get("date"),
                    })
                    seen.add(mid)
            if clean:
                valid.append({
                    "title": ch.get("title") or "Untitled Chapter",
                    "summary": ch.get("summary") or _fallback_summary([
                        {"story_content": m.get("title", "")} for m in clean
                    ]),
                    "memories": clean,
                })
        return {"chapters": valid}


class ChapterService:
    @staticmethod
    def generate_proposal(memoir_id: str):
        server = MCPServer(memoir_id)
        client = MCPClient(server)

        facts = ReaderAgent(client).extract_facts()
        proposal = OrganizerAgent(client).propose(facts)
        return ReviewerAgent(client).review(proposal)

    @staticmethod
    def refine_proposal(memoir_id: str, current_proposal: dict, user_prompt: str):
        server = MCPServer(memoir_id)
        client = MCPClient(server)

        refined = RefinerAgent(client).refine(current_proposal, user_prompt)
        return ReviewerAgent(client).review(refined)

    @staticmethod
    def apply_proposal(memoir_id: str, proposal: dict):
        if "chapters" not in proposal:
            raise HTTPException(status_code=400, detail="Invalid proposal structure.")
        apply_chapters_to_db(memoir_id, proposal["chapters"])
        return {"success": True}