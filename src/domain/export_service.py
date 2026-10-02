"""
@file domain/export_service.py
@description Business logic for compiling memoir exports, PDF generation, and storage management using pure Python (xhtml2pdf).
"""

import io
from fastapi import HTTPException, status
from xhtml2pdf import pisa
from src.domain.authorization import verify_active_participant
from src.integrations.export_repository import ExportRepository
from src.integrations import storage_adapter


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
            memoir = payload["memoir"]
            memories = payload["memories"]
            media_assets = payload["media_assets"]
            transcripts = payload["transcripts"]

            html_content = cls._render_memoir_html(memoir, memories, media_assets, transcripts)

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
    def get_latest_export_status(cls, memoir_id: str) -> dict:
        """Fetches the latest export job status and signed download URL if ready."""
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
    def _render_memoir_html(memoir: dict, memories: list, media_assets: list, transcripts: list) -> str:
        """Generates a high-end, printable book layout HTML string."""
        memoir_title = memoir.get("title", "My Memoir")
        memoir_description = memoir.get("description", "A curated collection of life memories.")

        memories_html = ""
        for mem in memories:
            title = mem.get("title") or "Untitled Entry"
            date = mem.get("occurred_start") or mem.get("created_at", "")[:10]
            body = mem.get("body_text") or ""

            memories_html += f"""
            <div class="memory-entry">
                <div class="memory-meta">{date}</div>
                <h2>{title}</h2>
                <div class="memory-body">{body.replace(chr(10), '<br>')}</div>
            </div>
            """

        photos_html = ""
        for ma in media_assets:
            if ma.get("kind") == "photo" and ma.get("storage_key"):
                img_url = storage_adapter.create_playback_url(ma.get("storage_key"))
                if not img_url:
                    continue
                caption = ma.get("caption") or ""
                photos_html += f"""
                <div class="photo-container">
                    <img src="{img_url}" alt="Memory photo" />
                    {f'<p class="photo-caption">{caption}</p>' if caption else ''}
                </div>
                """

        transcripts_html = ""
        for t in transcripts:
            t_text = t.get("display_text") or ""
            if t_text:
                transcripts_html += f"""
                <div class="transcript-box">
                    <strong>Voice Recording Transcript:</strong>
                    <p>{t_text}</p>
                </div>
                """

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
                h2 {{
                    font-size: 16pt;
                    color: #222;
                    margin: 0 0 10px 0;
                }}
                .memory-body {{
                    font-size: 10pt;
                    text-align: justify;
                    margin-bottom: 12px;
                }}
                .section-title {{
                    font-size: 14pt;
                    color: #222;
                    margin-top: 40px;
                    margin-bottom: 15px;
                    border-bottom: 2px solid #b8a894;
                    padding-bottom: 5px;
                }}
                .photo-container {{
                    margin: 15px 0;
                    text-align: center;
                }}
                .photo-container img {{
                    max-width: 70%;
                    max-height: 300px;
                }}
                .photo-caption {{
                    font-size: 8pt;
                    font-style: italic;
                    color: #666;
                    margin-top: 4px;
                }}
                .transcript-box {{
                    background: #f4efea;
                    border-left: 3px solid #b8a894;
                    padding: 10px 15px;
                    font-size: 9pt;
                    margin-top: 15px;
                }}
            </style>
        </head>
        <body>
            <div class="cover-page">
                <h1>{memoir_title}</h1>
                <p>{memoir_description}</p>
            </div>
            <div class="content">
                <div class="section-title">Memories</div>
                {memories_html}

                {f'<div class="section-title">Photo Gallery</div>{photos_html}' if photos_html else ''}

                {f'<div class="section-title">Voice Transcripts</div>{transcripts_html}' if transcripts_html else ''}
            </div>
        </body>
        </html>
        """