"""
@file domain/export_service.py
@description Business logic for compiling memoir exports, PDF generation, and storage management using pure Python (xhtml2pdf).
"""

import html
import io
from fastapi import HTTPException, status
from xhtml2pdf import pisa
from src.domain.authorization import verify_active_participant
from src.integrations.export_repository import ExportRepository
from src.integrations import storage_adapter


def _esc(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


class ExportService:

    @classmethod
    def initiate_export(cls, memoir_id: str, user_id: str, background_tasks=None) -> dict:
        """Validates permissions and queues a new PDF export job."""
        participant = verify_active_participant(
            memoir_id,
            user_id,
            required_roles=["owner", "admin", "contributor"]
        )
        participant_id = participant.get("id")
        job = ExportRepository.create_export_job(memoir_id, participant_id, kind="pdf")

        if background_tasks is not None:
            # Queue background generation here so routers stay thin.
            background_tasks.add_task(
                cls.process_export_background,
                export_id=job["id"],
                memoir_id=memoir_id,
            )

        return {
            "export_id": job["id"],
            "memoir_id": memoir_id,
            "status": "queued",
            "message": "Export job queued successfully. Processing in background.",
            "created_at": job["created_at"]
        }

    @classmethod
    def process_export_background(cls, export_id: str, memoir_id: str) -> None:
        """Background worker method to compile data, generate PDF via xhtml2pdf, and upload to storage."""
        try:
            payload = ExportRepository.fetch_memoir_export_payload(memoir_id)
            html_content = cls._render_memoir_html(
                payload["memoir"], payload["chapters"], payload["memories"]
            )

            pdf_buffer = io.BytesIO()
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_buffer)

            if pisa_status.err:
                raise Exception("Failed to compile HTML into PDF using xhtml2pdf.")

            pdf_bytes = pdf_buffer.getvalue()

            storage_key = f"exports/pdf-archives/{memoir_id}/{export_id}.pdf"
            ExportRepository.upload_pdf_to_storage(storage_key, pdf_bytes)

            ExportRepository.update_job_status(
                export_id=export_id,
                status="ready",
                storage_key=storage_key,
                byte_size=len(pdf_bytes)
            )

        except Exception as e:
            ExportRepository.update_job_status(
                export_id=export_id,
                status="failed",
                error_message=str(e)
            )

    @classmethod
    def get_latest_export_status(cls, memoir_id: str, user_id: str) -> dict:
        """Fetches the latest export job status and signed download URL if ready."""
        verify_active_participant(str(memoir_id), str(user_id))
        job = ExportRepository.get_latest_export(memoir_id)
        if not job:
            return {"status": "none"}

        download_url = None
        if job["status"] == "ready" and job.get("storage_key"):
            download_url = ExportRepository.get_signed_download_url(job["storage_key"])

        return {
            "success": True,
            "status": job["status"],
            "error_message": job.get("error_message"),
            "download_url": download_url,
        }

    @staticmethod
    def _render_memoir_html(memoir: dict, chapters: list, memories: list) -> str:
        """Book layout: cover → owner-confirmed chapters → memories with
        small inline photos. No photo gallery, no transcripts, no audio:
        transcripts feed the AI organizer only and audio cannot play on paper.
        """
        memoir_title = _esc(memoir.get("subject_name") or memoir.get("title", "My Memoir"))
        memoir_description = _esc(memoir.get("description", "A curated collection of life memories."))

        def _memory_photos_html(mem: dict) -> str:
            parts = []
            for link in (mem.get("memory_media") or []):
                asset = link.get("media_asset") or {}
                if asset.get("kind") != "photo" or not asset.get("storage_key"):
                    continue
                img_url = storage_adapter.create_playback_url(asset.get("storage_key"))
                if not img_url:
                    continue
                caption = _esc(asset.get("caption") or "")
                parts.append(
                    f'<div class="photo-thumb">'
                    f'<img src="{_esc(img_url)}" alt="Memory photo" />'
                    f'{f"<p>{caption}</p>" if caption else ""}'
                    f"</div>"
                )
            if not parts:
                return ""
            return '<div class="photo-row">' + "".join(parts) + "</div>"

        def _memory_html(mem: dict) -> str:
            title = _esc(mem.get("title") or "Untitled Entry")
            date = _esc(mem.get("occurred_start") or str(mem.get("created_at", ""))[:10])
            body = _esc(mem.get("body_text") or "")
            return (
                '<div class="memory-entry">'
                f'<div class="memory-meta">{date}</div>'
                f"<h3>{title}</h3>"
                f'<div class="memory-body">{body.replace(chr(10), "<br/>")}</div>'
                f"{_memory_photos_html(mem)}"
                "</div>"
            )

        by_chapter: dict[str, list] = {}
        unassigned: list = []
        chapter_ids = {c.get("id") for c in chapters}
        for mem in memories:
            cid = mem.get("chapter_id")
            if cid and cid in chapter_ids:
                by_chapter.setdefault(cid, []).append(mem)
            else:
                unassigned.append(mem)

        chapters_html = ""
        for ch in chapters:
            mems = by_chapter.get(ch.get("id"), [])
            if not mems:
                continue
            ch_title = _esc(ch.get("title") or "Chapter")
            ch_summary = _esc(ch.get("summary") or "")
            stories = "".join(_memory_html(m) for m in mems)
            summary_html = ""
            if ch_summary:
                summary_html = '<p class="chapter-summary">' + ch_summary + "</p>"
            chapters_html += (
                f'<div class="section-title">{ch_title}</div>'
                f"{summary_html}"
                f"{stories}"
            )
        if unassigned:
            stories = "".join(_memory_html(m) for m in unassigned)
            chapters_html += (
                '<div class="section-title">Memoir Reflections</div>'
                f"{stories}"
            )

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{
                    size: A4;
                    margin: 20mm 15mm;
                }}
                body {{
                    font-family: Helvetica, Arial, sans-serif;
                    color: #2c2c2c;
                    background-color: #fdfbf7;
                    margin: 0;
                    padding: 20px;
                    line-height: 1.6;
                }}
                .cover-page {{
                    text-align: center;
                    padding-top: 100px;
                    page-break-after: always;
                }}
                .cover-page h1 {{
                    font-size: 28pt;
                    color: #1a1a1a;
                    margin-bottom: 10px;
                }}
                .cover-page p {{
                    font-size: 12pt;
                    font-style: italic;
                    color: #555;
                }}
                .memory-entry {{
                    margin-bottom: 30px;
                    border-bottom: 1px solid #e6e2d8;
                    padding-bottom: 25px;
                }}
                .memory-meta {{
                    font-size: 8pt;
                    text-transform: uppercase;
                    letter-spacing: 1.5px;
                    color: #887a64;
                    margin-bottom: 4px;
                }}
                h3 {{
                    font-size: 12pt;
                    color: #222;
                    margin: 0 0 8px 0;
                }}
                .memory-body {{
                    font-size: 10pt;
                    text-align: justify;
                    margin-bottom: 8px;
                }}
                .chapter-summary {{
                    font-size: 10pt;
                    font-style: italic;
                    color: #555;
                    margin-bottom: 20px;
                }}
                .section-title {{
                    font-size: 14pt;
                    color: #222;
                    margin-top: 40px;
                    margin-bottom: 15px;
                    border-bottom: 2px solid #b8a894;
                    padding-bottom: 5px;
                }}
                .photo-row {{
                    margin: 8px 0 4px 0;
                }}
                .photo-thumb {{
                    display: inline-block;
                    vertical-align: top;
                    width: 32%;
                    margin: 0 1% 8px 0;
                    text-align: center;
                }}
                .photo-thumb img {{
                    max-width: 100%;
                    max-height: 180px;
                }}
                .photo-thumb p {{
                    font-size: 7pt;
                    font-style: italic;
                    color: #666;
                    margin-top: 2px;
                }}
            </style>
        </head>
        <body>
            <div class="cover-page">
                <h1>{memoir_title}</h1>
                <p>{memoir_description}</p>
            </div>
            <div class="content">
                {chapters_html}
            </div>
        </body>
        </html>
        """