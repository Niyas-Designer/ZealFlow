import os
from pathlib import Path

try:
    import firebase_admin
    from firebase_admin import credentials, storage
except Exception:
    firebase_admin = None
    credentials = None
    storage = None


def firebase_configured() -> bool:
    return bool(
        firebase_admin
        and os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
        and os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    )


def _init():
    if not firebase_configured():
        return False
    if not firebase_admin._apps:
        cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        bucket = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
        if not Path(cred_path).expanduser().exists():
            raise RuntimeError(f"Firebase service account file not found: {cred_path}")
        cred = credentials.Certificate(str(Path(cred_path).expanduser()))
        firebase_admin.initialize_app(cred, {"storageBucket": bucket})
    return True


def upload_file(local_path: Path, remote_path: str) -> str | None:
    if not _init():
        return None
    blob = storage.bucket().blob(remote_path)
    blob.upload_from_filename(str(local_path))
    return remote_path


def upload_if_configured(local_path: Path, remote_path: str) -> str | None:
    try:
        return upload_file(local_path, remote_path)
    except Exception as exc:
        print(f"[Firebase] upload skipped/failed for {local_path.name}: {exc}")
        return None


def prefix() -> str:
    return os.getenv("FIREBASE_STORAGE_PREFIX", "zealflow").strip().strip("/") or "zealflow"
