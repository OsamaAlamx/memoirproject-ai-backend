"""
@file storage_adapter.py
@description Infrastructure adapter service managing low-level object storage 
interactions, file validations, signed upload/playback URLs, and bucket cleanup.
"""

import logging
import uuid
from dataclasses import dataclass

class StorageError(RuntimeError):
    pass

class UnsupportedMediaError(ValueError):
    pass

from supabase import create_client

from src.core.config import settings

logger = logging.getLogger(__name__)

_client = create_client(settings.supabase_url, settings.supabase_secret_key)

ALLOWED_MIME = {
    "audio/webm": ("audio", "webm"),
    "audio/ogg":  ("audio", "ogg"),
    "audio/mpeg": ("audio", "mp3"),
    "audio/mp4":  ("audio", "m4a"),
    "audio/wav":  ("audio", "wav"),
    "image/jpeg": ("image", "jpg"),
    "image/png":  ("image", "png"),
    "image/webp": ("image", "webp"),
    "image/heic": ("image", "heic"),
}


@dataclass
class SignedUpload:
    path: str
    signed_url: str
    token: str


def _ensure_bucket_exists():
    """Ensures the configured storage bucket exists, creating it if necessary."""
    bucket_name = settings.supabase_media_bucket
    try:
        buckets = _client.storage.list_buckets()
        bucket_names = [
            b.name if hasattr(b, 'name') else b.get("name") 
            for b in (buckets or [])
        ]
        if bucket_name not in bucket_names:
            _client.storage.create_bucket(id=bucket_name, name=bucket_name, options={"public": False})
            logger.info(f"Automatically created missing storage bucket: {bucket_name}")
    except Exception as exc:
        logger.warning(f"Could not verify or create storage bucket '{bucket_name}': {exc}")


def validate_upload(mime_type: str) -> tuple[str, str]:
    if mime_type not in ALLOWED_MIME:
        raise UnsupportedMediaError(
            "That file type isn't supported. Try a photo or a voice recording.",
        )
    return ALLOWED_MIME[mime_type]


def build_key(memoir_id: uuid.UUID, media_type: str, extension: str) -> str:
    return f"memoirs/{memoir_id}/{media_type}/{uuid.uuid4()}.{extension}"


def create_signed_upload(key: str) -> SignedUpload:
    _ensure_bucket_exists()
    try:
        res = _client.storage.from_(settings.supabase_media_bucket).create_signed_upload_url(key)
    except Exception as exc:
        logger.error("Signed upload URL failed key=%s: %s", key, exc)
        raise StorageError(
            "We couldn't start the upload just now. Please try again in a moment.",
        )
    return SignedUpload(
        path=res.get("path", key),
        signed_url=res.get("signed_url") or res.get("signedURL"),
        token=res["token"],
    )


def object_exists(key: str) -> int | None:
    folder, _, filename = key.rpartition("/")
    try:
        items = _client.storage.from_(settings.supabase_media_bucket).list(
            folder, {"search": filename}
        )
    except Exception as exc:
        logger.warning("Existence check failed key=%s: %s", key, exc)
        return None

    for item in items or []:
        if item.get("name") == filename:
            meta = item.get("metadata") or {}
            return meta.get("size")
    return None


def create_playback_url(key: str, expires_in: int = 3600) -> str | None:
    """Private-bucket playback via short-lived signed URL.

    P1 made the bucket private, so public `/object/public/` URLs 403.
    All feed/share/export callers go through here, so signing here fixes
    images + audio everywhere at once. 1h TTL avoids expiry mid-read.
    No fallback to public URL: that would re-open the hole P1 closed.
    """
    try:
        clean_key = key.lstrip("/")
        res = _client.storage.from_(settings.supabase_media_bucket).create_signed_url(
            clean_key, expires_in
        )
        url = _extract_signed_url(res)
        if url and url.startswith("http"):
            return url
        # Some SDK versions return a path: join with base.
        if url:
            return f"{settings.supabase_url.rstrip('/')}/storage/v1{url}" if url.startswith("/") else url
        logger.warning("Signed playback URL empty key=%s res_type=%s", key, type(res).__name__)
        return None
    except Exception as exc:
        logger.warning("Signed playback URL failed key=%s: %s", key, exc)
        return None


def _extract_signed_url(res: object) -> str | None:
    """Handle every supabase-py/storage3 response shape (dict/str/object)."""
    if res is None:
        return None
    if isinstance(res, str):
        return res or None
    if isinstance(res, dict):
        for k in ("signedURL", "signed_url", "signedUrl", "url", "signedurl"):
            v = res.get(k)
            if isinstance(v, str) and v:
                return v
        data = res.get("data")
        if isinstance(data, dict):
            return _extract_signed_url(data)
        return None
    for attr in ("signedURL", "signed_url", "signedUrl", "url"):
        v = getattr(res, attr, None)
        if isinstance(v, str) and v:
            return v
    get = getattr(res, "get", None)
    if callable(get):
        try:
            for k in ("signedURL", "signed_url", "signedUrl", "url"):
                v = get(k)
                if isinstance(v, str) and v:
                    return v
        except Exception:
            pass
    return None


def remove_object(key: str) -> None:
    try:
        _client.storage.from_(settings.supabase_media_bucket).remove([key])
    except Exception as exc:
        logger.warning("Object delete failed key=%s: %s", key, exc)


def download_object(key: str) -> bytes | None:
    """Download raw bytes for background workers (transcription)."""
    return _client.storage.from_(settings.supabase_media_bucket).download(key)