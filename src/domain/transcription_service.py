import os
import time
import assemblyai as aai
from src.integrations.memory_repository import upsert_transcript_record
from src.integrations import storage_adapter
from src.core.config import settings

def transcribe_and_store_audio(media_asset_id: str, memoir_id: str, storage_key: str):
    """
    Downloads audio binary from Supabase storage using admin client with retries, 
    uploads raw bytes directly to AssemblyAI, and persists the resulting transcript.
    """
    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: ASSEMBLYAI_API_KEY is missing from environment variables!")
        raise ValueError("ASSEMBLYAI_API_KEY is missing")

    aai.settings.api_key = api_key
    transcriber = aai.Transcriber()

    try:
        bucket_name = settings.supabase_media_bucket
        audio_bytes = None
        
        print(f"Attempting to download storage key '{storage_key}' from bucket '{bucket_name}'...")
        for attempt in range(1, 4):
            try:
                audio_bytes = storage_adapter.download_object(storage_key)
                if audio_bytes:
                    print(f"Successfully downloaded audio bytes on attempt {attempt}")
                    break
            except Exception as dl_err:
                print(f"Download attempt {attempt} failed (file might still be uploading): {str(dl_err)}")
                if attempt < 3:
                    time.sleep(1.5)

        if not audio_bytes:
            raise Exception(f"Download returned empty bytes or 404 after retries for key: {storage_key}")

        print("Uploading raw audio bytes to AssemblyAI...")
        upload_url = transcriber.upload_file(audio_bytes)

        print(f"Uploaded successfully. Transcribing URL...")
        transcript_result = transcriber.transcribe(upload_url)
        
        if transcript_result.status == aai.TranscriptStatus.error:
            raise Exception(f"AssemblyAI processing failed: {transcript_result.error}")

        raw_text = transcript_result.text or ""
        print(f"Transcription successful! Text: {raw_text[:60]}...")

        transcript_payload = {
            "media_asset_id": media_asset_id,
            "memoir_id": memoir_id,
            "raw_text": raw_text,
            "engine": "assemblyai",
            "confidence": transcript_result.confidence,
            "language": transcript_result.language_code or "en"
        }
        response = upsert_transcript_record(transcript_payload)
        
        print("Transcript successfully saved to database!", response.data)
        return response.data

    except Exception as e:
        print(f"CRITICAL TRANSCRIPTION EXCEPTION CAUGHT: {str(e)}")
        raise e


def queue_transcription(background_tasks, media_asset_id: str, memoir_id: str, storage_key: str) -> None:
    """Queue AssemblyAI transcription so routers stay thin (no try/except in api/)."""
    background_tasks.add_task(
        transcribe_and_store_audio,
        media_asset_id=media_asset_id,
        memoir_id=memoir_id,
        storage_key=storage_key,
    )