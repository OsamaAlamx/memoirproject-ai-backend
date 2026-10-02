# src/domain/chapter_service.py
import json
import os
import httpx
from fastapi import HTTPException
from src.core.config import settings
from src.integrations import memoir_repository
from src.integrations.chapter_repository import (
    get_memories_for_organization,
    get_existing_chapters,
    apply_chapters_to_db,
)


def _ensure_memoir_editable(memoir_id: str) -> None:
    """AI Organizer is locked once the memoir is published.

    Publishing freezes the chapter layout served on the single live link,
    so propose/refine/apply must stop serving published memoirs (403)
    instead of silently rewriting the live book.
    """
    memoir = memoir_repository.fetch_memoir_record(str(memoir_id))
    if memoir and memoir.get("status") == "published":
        raise HTTPException(
            status_code=403,
            detail="Memoir is published and can no longer be reorganized. "
            "Unpublish it to organize chapters again.",
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


def _call_llm_json(prompt: str, max_tokens: int = 8000) -> dict | None:
    api_key = settings.llm_api_key or os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("🚨 LLM Error: No API key found (LLM_API_KEY / GROQ_API_KEY / OPENAI_API_KEY missing).")
        return None

    base_url = (settings.llm_base_url or "https://api.groq.com/openai/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    candidate_models = [
        settings.llm_model,
        "openai/gpt-oss-120b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "qwen/qwen3-32b",
        "moonshotai/kimi-k2-instruct",
        "llama-3.1-8b-instant",
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
                        "You are a professional biographer and narrative nonfiction "
                        "ghostwriter. Always respond with valid, COMPLETE JSON only. "
                        "No markdown, no code fences, no trailing commentary. "
                        "Never truncate — if you are running low on space, write "
                        "shorter paragraphs, but always close every JSON bracket."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.75,
            "max_tokens": max_tokens,
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
                timeout=90.0,
            )
            if response.status_code == 200:
                body = response.json()
                content = body["choices"][0]["message"]["content"].strip()
                finish_reason = body["choices"][0].get("finish_reason")

                if finish_reason == "length":
                    print(f"⚠️  LLM response for model '{model}' was TRUNCATED "
                          f"(finish_reason=length). Trying next model / retry with more tokens.")
                    continue

                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]

                try:
                    return json.loads(content.strip())
                except json.JSONDecodeError as parse_err:
                    print(f"⚠️  LLM model '{model}' returned invalid JSON "
                          f"({parse_err}). First 300 chars: {content[:300]!r}")
                    continue

            print(f"LLM API Warning ({response.status_code}) model='{model}': {response.text[:300]}")
        except Exception as err:
            print(f"LLM Call error for model '{model}': {err}")

    print("🚨 ALL LLM MODELS FAILED — falling back to naive local synthesis. "
          "Output quality WILL be degraded (near-verbatim excerpts, date-only grouping). "
          "Check LLM_API_KEY / GROQ_API_KEY, model availability, and network access.")
    return None


def _fallback_summary(facts: list) -> str:
    snippets = []
    for f in facts:
        text = (f.get("full_text") or f.get("story_content") or f.get("title") or "").strip()
        if text:
            cut = text.replace("\n", " ")
            if len(cut) > 200:
                cut = cut[:200].rsplit(" ", 1)[0] + "…"
            snippets.append(cut)
    if not snippets:
        return ("[AI synthesis unavailable] A collection of treasured moments from this "
                "period of life.")
    joined = " ".join(snippets)
    if len(joined) > 800:
        joined = joined[:800].rsplit(" ", 1)[0] + "…"
    return "[AI synthesis unavailable — raw excerpts shown] " + joined


def _fallback_title(era: str, facts: list) -> str:
    if facts:
        t = (facts[0].get("title") or "").strip()
        if t and len(t) < 60:
            return t.title() if t.islower() else t
    clean = (era or "Memories").replace("The ", "").strip()
    return f"Memories of the {clean}" if clean[:1].isdigit() else clean


class ReaderAgent:
    """
    Loads raw memories and passes FULL text forward. Now also includes
    audio transcripts so the AI can understand spoken memories too.
    """
    def __init__(self, client: MCPClient):
        self.client = client

    def extract_facts(self):
        memories = self.client.read_resource("memories")
        memories = sorted(memories, key=lambda x: x.get("occurred_start") or "9999-12-31")

        facts = []
        for m in memories:
            date_val = m.get("occurred_start")
            era_guess = "Undated"
            if date_val and len(str(date_val)) >= 4:
                year_str = str(date_val)[:4]
                if year_str.isdigit():
                    era_guess = f"{year_str[:3]}0s"

            # Combine written body_text + audio transcripts into the AI's context
            text_parts = []
            if m.get("body_text"):
                text_parts.append(str(m["body_text"]).strip())

            transcripts = m.get("transcripts") or []
            for tr in transcripts:
                if tr and str(tr).strip():
                    text_parts.append(f"[AUDIO TRANSCRIPT]\n{str(tr).strip()}")

            full_text = "\n\n".join([p for p in text_parts if p]).strip()

            facts.append({
                "id": m["id"],
                "title": m.get("title") or "Untitled Entry",
                "date": m.get("occurred_start"),
                "era_guess": era_guess,
                "chapter_id": m.get("chapter_id"),
                "full_text": full_text,
            })
        return facts


class OrganizerAgent:
    def __init__(self, client: MCPClient):
        self.client = client

    def propose(self, facts):
        existing_chapters = {c["id"]: c for c in self.client.read_resource("chapters")}

        source_material = "\n\n".join([
            f"[MEMORY ID: {f['id']}]\n"
            f"Contributor's Title: {f['title']}\n"
            f"Date: {f['date'] or 'Unknown'}\n"
            f"Raw Account:\n{f['full_text'] or '(No written text — media only, use title/date as context.)'}"
            for f in facts
        ])

        prompt = f"""
You are ghostwriting a published-quality narrative biography, in the style of
"Unbroken" or Walter Isaacson's biographies. You have been handed raw oral-history
style contributions from people who knew the subject — think of these as
unedited interview transcripts, not finished prose.

RAW SOURCE MATERIAL (interview transcripts / contributor accounts):
{source_material}

EXISTING CHAPTERS (optional — you may keep, rename, merge, or discard entirely):
{json.dumps(list(existing_chapters.values()), indent=2)}

================================================================================
NON-NEGOTIABLE RULES:

1. NEVER COPY THE SOURCE TEXT. Do not lift sentences or distinctive phrases
   verbatim from the raw accounts. Paraphrase and rewrite everything into your
   own original narrative prose.

2. ORGANIZE BY MEANING AND LIFE-STAGE, NOT JUST BY DATE. Read every account
   first, understand the arc of this person's life, then decide chapter
   boundaries around themes.

3. CREATE 3 TO 6 CHAPTERS spanning the subject's full story arc, in ascending
   chronological/narrative order (earliest life stage first).

4. EACH CHAPTER MUST HAVE:
   - "title": an original, evocative, literary chapter title.
   - "summary": 3 to 6 paragraphs of ORIGINAL narrative prose.
   - "memories": array of {{ "id", "title", "date" }} for every raw memory
     used in this chapter.

5. Every memory id from the source material must appear in EXACTLY ONE chapter.

Return ONLY valid, complete JSON, exactly in this shape:
{{
  "chapters": [
    {{
      "title": "Original Chapter Title",
      "summary": "Paragraph 1...\\n\\nParagraph 2...\\n\\nParagraph 3...",
      "memories": [
        {{ "id": "memory_id", "title": "entry title", "date": "date or null" }}
      ]
    }}
  ]
}}
"""
        llm_res = _call_llm_json(prompt, max_tokens=8000)
        if llm_res and "chapters" in llm_res:
            return self.client.call_tool("propose_chapter_set", {"chapters": llm_res["chapters"]})

        print("⚠️  OrganizerAgent falling back to naive chronological grouping.")

        buckets: dict[str, list] = {}
        for f in facts:
            key = f.get("era_guess") or "Timeless Reflections"
            buckets.setdefault(key, []).append(f)

        MAX_CHAPTERS = 6
        if len(facts) > MAX_CHAPTERS and len(buckets) > MAX_CHAPTERS:
            all_sorted = sorted(facts, key=lambda x: x.get("date") or "9999-12-31")
            chunk_size = max(2, -(-len(all_sorted) // MAX_CHAPTERS))
            buckets = {}
            for i in range(0, len(all_sorted), chunk_size):
                chunk = all_sorted[i:i + chunk_size]
                if not chunk:
                    continue
                label = chunk[0].get("era_guess") or f"Chapter {i // chunk_size + 1}"
                buckets[f"{label}__{i}"] = chunk

        proposal = []
        for era, items in buckets.items():
            proposal.append({
                "title": _fallback_title(era, items),
                "summary": _fallback_summary(items),
                "memories": [
                    {"id": it["id"], "title": it.get("title") or "Untitled Entry", "date": it.get("date")}
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
You are refining a biography's chapter breakdown based on the owner's request.
Follow the same non-negotiable rules as the original synthesis pass: never copy
source text verbatim, organize by life-stage/theme, write original prose.

CURRENT PROPOSAL:
{json.dumps(current_proposal, indent=2)}

OWNER REQUEST:
"{user_prompt}"

RAW SOURCE MATERIAL (reference only):
{json.dumps(memories, indent=2)}

RULES:
1. Apply the owner's request.
2. Keep chapters in ascending chronological/narrative order.
3. Each chapter needs an original title and 3-6 paragraphs of original summary.
4. Every memory id stays assigned to exactly one chapter.

Return ONLY valid JSON in this shape:
{{
  "chapters": [
    {{
      "title": "Chapter Title",
      "summary": "Paragraph 1...\\n\\nParagraph 2...",
      "memories": [
        {{ "id": "memory_id", "title": "entry title", "date": "date or null" }}
      ]
    }}
  ]
}}
"""
        llm_res = _call_llm_json(prompt, max_tokens=8000)
        if llm_res and "chapters" in llm_res:
            return self.client.call_tool("propose_chapter_set", {"chapters": llm_res["chapters"]})

        print("⚠️  RefinerAgent: LLM refinement failed, returning proposal unchanged.")
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
                        {"full_text": m.get("title", "")} for m in clean
                    ]),
                    "memories": clean,
                })
        return {"chapters": valid}


class ChapterService:
    @staticmethod
    def generate_proposal(memoir_id: str):
        _ensure_memoir_editable(memoir_id)
        server = MCPServer(memoir_id)
        client = MCPClient(server)

        facts = ReaderAgent(client).extract_facts()
        proposal = OrganizerAgent(client).propose(facts)
        return ReviewerAgent(client).review(proposal)

    @staticmethod
    def refine_proposal(memoir_id: str, current_proposal: dict, user_prompt: str):
        _ensure_memoir_editable(memoir_id)
        server = MCPServer(memoir_id)
        client = MCPClient(server)

        refined = RefinerAgent(client).refine(current_proposal, user_prompt)
        return ReviewerAgent(client).review(refined)

    @staticmethod
    def apply_proposal(memoir_id: str, proposal: dict):
        _ensure_memoir_editable(memoir_id)
        if "chapters" not in proposal:
            raise HTTPException(status_code=400, detail="Invalid proposal structure.")
        apply_chapters_to_db(memoir_id, proposal["chapters"])
        return {"success": True}