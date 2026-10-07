from __future__ import annotations

import json
import os
import shutil
import threading
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image

from backend.generator import generate_image
from backend.firebase_storage import firebase_configured, upload_if_configured, prefix as firebase_prefix

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = Path(os.getenv("JOBS_DIR", ROOT / "workspace" / "zealflow_jobs"))
JOBS_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGES = 99
MAX_ARCHIVE_FILES = 2500
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

app = FastAPI(title="ZealFlow", version="5.0.0")
allowed_origins = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("BATCH_WORKERS", "1"))), thread_name_prefix="zealflow")
FUTURES: dict[str, Future] = {}
FUTURES_LOCK = threading.Lock()
STATUS_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def read_status(job_dir: Path) -> dict:
    path = status_path(job_dir)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(job_dir: Path, data: dict) -> None:
    data["updated_at"] = now_iso()
    path = status_path(job_dir)
    tmp = path.with_suffix(".tmp")
    with STATUS_LOCK:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)


def is_metadata_path(parts: tuple[str, ...]) -> bool:
    return any(part == "__MACOSX" or part.startswith(".") for part in parts)


def safe_extract(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        if len(infos) > MAX_ARCHIVE_FILES:
            raise ValueError(f"ZIP contains too many files ({len(infos)}).")
        if sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP is too large after extraction.")
        destination_resolved = destination.resolve()
        for info in zf.infolist():
            posix = PurePosixPath(info.filename)
            if posix.is_absolute() or ".." in posix.parts:
                raise ValueError("Unsafe ZIP path detected.")
            target = (destination / Path(*posix.parts)).resolve()
            if destination_resolved != target and destination_resolved not in target.parents:
                raise ValueError("Unsafe ZIP path detected.")
        zf.extractall(destination)


def image_dimensions(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return 0, 0


def image_meta(path: Path) -> dict:
    w, h = image_dimensions(path)
    ratio = round(w / h, 4) if w and h else None
    return {"width": w, "height": h, "ratio": ratio, "orientation": "landscape" if w > h else "portrait" if h > w else "square"}


def target_ratio(aspect_ratio: str, reference_path: Path | None) -> float:
    ratio = None
    mode = (aspect_ratio or "auto").lower()
    if mode == "auto" and reference_path and reference_path.exists():
        w, h = image_dimensions(reference_path)
        if w and h:
            ratio = w / h
    manual = {"1:1": 1.0, "4:5": 0.8, "3:4": 0.75, "9:16": 0.5625, "16:9": 1.7778}
    if mode in manual:
        ratio = manual[mode]
    return ratio if ratio is not None else (2 / 3)


def api_size(aspect_ratio: str, reference_path: Path | None) -> str:
    ratio = target_ratio(aspect_ratio, reference_path)
    if ratio > 1.15:
        return "1536x1024"
    if ratio < 0.87:
        return "1024x1536"
    return "1024x1024"


def crop_to_ratio(path: Path, ratio: float) -> None:
    if not path.exists() or not ratio:
        return
    with Image.open(path) as img:
        w, h = img.size
        current = w / h
        if abs(current - ratio) < 0.01:
            return
        if current > ratio:
            new_w = max(1, int(round(h * ratio)))
            left = max(0, (w - new_w) // 2)
            cropped = img.crop((left, 0, left + new_w, h))
        else:
            new_h = max(1, int(round(w / ratio)))
            top = max(0, (h - new_h) // 2)
            cropped = img.crop((0, top, w, top + new_h))
        fmt = (img.format or path.suffix.lstrip(".")).upper()
        if fmt in {"JPG", "JPEG"}:
            if cropped.mode not in {"RGB", "L"}:
                cropped = cropped.convert("RGB")
            cropped.save(path, format="JPEG", quality=95, subsampling=0)
        elif fmt == "WEBP":
            cropped.save(path, format="WEBP", quality=95, method=6)
        else:
            cropped.save(path, format="PNG", optimize=True)


def save_upload(upload: UploadFile, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise ValueError("Upload is too large")
            out.write(chunk)
    return total


def unique_destination(folder: Path, name: str) -> Path:
    clean = Path(name or "image.png").name
    candidate = folder / clean
    stem, suffix = candidate.stem, candidate.suffix
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{n}{suffix}"
        n += 1
    return candidate


def collect_zip_images(zip_file: UploadFile, input_dir: Path, temp_dir: Path) -> list[Path]:
    zip_path = temp_dir / "Input.zip"
    save_upload(zip_file, zip_path)
    extracted = temp_dir / "zip_extracted"
    extracted.mkdir(parents=True, exist_ok=True)
    safe_extract(zip_path, extracted)
    found = []
    for path in sorted(extracted.rglob("*"), key=lambda p: p.as_posix().casefold()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS or is_metadata_path(path.relative_to(extracted).parts):
            continue
        dest = unique_destination(input_dir, path.name)
        shutil.copy2(path, dest)
        found.append(dest)
    return found


def is_valid_image(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 32:
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def create_output_zip(job_dir: Path) -> Path:
    output_root = job_dir / "output"
    zip_path = job_dir / "ZealFlow-Output.zip"
    temp_zip = job_dir / "ZealFlow-Output.tmp.zip"
    temp_zip.unlink(missing_ok=True)
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(output_root.iterdir(), key=lambda p: p.name.casefold()):
            if is_valid_image(file):
                zf.write(file, arcname=file.name)
    temp_zip.replace(zip_path)
    return zip_path


def recalc(status: dict) -> None:
    images = status["images"]
    status["total_images"] = len(images)
    status["completed_images"] = sum(x["status"] == "completed" for x in images)
    status["processing_images"] = sum(x["status"] == "processing" for x in images)
    status["failed_images"] = sum(x["status"] == "failed" for x in images)


def process_job(job_id: str, retry_failed_only: bool = False, api_key: str | None = None) -> None:
    job_dir = JOBS_DIR / job_id
    input_dir = job_dir / "inputs"
    output_dir = job_dir / "output"
    refs_dir = job_dir / "references"
    output_dir.mkdir(parents=True, exist_ok=True)
    status = read_status(job_dir)
    status.update(status="processing", finished_at=None, zip_ready=False, current_image=None, message="ZealFlow is generating your batch")
    status["started_at"] = status.get("started_at") or now_iso()
    write_status(job_dir, status)

    reference_paths = []
    for ref in status.get("references", []):
        p = refs_dir / ref["stored_name"]
        if p.exists():
            reference_paths.append(p)
    primary_ref = reference_paths[0] if reference_paths else None
    aspect_setting = status["settings"].get("aspect_ratio", "auto")
    size = api_size(aspect_setting, primary_ref)
    exact_ratio = target_ratio(aspect_setting, primary_ref)

    for index, item in enumerate(status["images"]):
        source = input_dir / item["stored_name"]
        output = output_dir / item["output_name"]
        if is_valid_image(output) and not retry_failed_only:
            item["status"] = "completed"
            item["error"] = None
            recalc(status); write_status(job_dir, status); continue
        if retry_failed_only and item["status"] != "failed":
            continue
        status["current_image"] = item["filename"]
        status["current_index"] = index + 1
        item["status"] = "processing"; item["error"] = None
        recalc(status); write_status(job_dir, status)
        try:
            generate_image(
                source_image=source,
                output_file=output,
                reference_images=reference_paths,
                prompt_mode=status["settings"].get("prompt_mode", "default"),
                custom_prompt=status["settings"].get("custom_prompt"),
                quality=status["settings"].get("quality", "high"),
                size=size,
                preservation=status["settings"].get("preservation", "maximum"),
                api_key=api_key,
            )
            if not is_valid_image(output):
                raise RuntimeError("Generated output was not a valid image")
            crop_to_ratio(output, exact_ratio)
            if not is_valid_image(output):
                raise RuntimeError("Aspect-ratio post-processing produced an invalid image")
            remote = upload_if_configured(output, f"{firebase_prefix()}/jobs/{job_id}/outputs/{item['output_name']}")
            if remote:
                item["firebase_output_path"] = remote
            item["status"] = "completed"
        except Exception as exc:
            output.unlink(missing_ok=True)
            item["status"] = "failed"
            item["error"] = str(exc)
        recalc(status); write_status(job_dir, status)

    zip_path = create_output_zip(job_dir)
    remote_zip = upload_if_configured(zip_path, f"{firebase_prefix()}/jobs/{job_id}/zip/{zip_path.name}")
    if remote_zip:
        status["firebase_zip_path"] = remote_zip
    recalc(status)
    status["current_image"] = None; status["current_index"] = None
    status["status"] = "completed_with_errors" if status["failed_images"] else "completed"
    status["zip_ready"] = True; status["finished_at"] = now_iso(); status["message"] = "Batch finished. Results are ready."
    write_status(job_dir, status)


def submit_job(job_id: str, retry_failed_only: bool = False, api_key: str | None = None) -> None:
    key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        raise HTTPException(status_code=400, detail="OpenAI API key is missing. Open API Key in ZealFlow and save your key.")
    with FUTURES_LOCK:
        existing = FUTURES.get(job_id)
        if existing and not existing.done():
            raise HTTPException(status_code=409, detail="This batch is already processing")
        FUTURES[job_id] = EXECUTOR.submit(process_job, job_id, retry_failed_only, key)


def public_status(status: dict) -> dict:
    return status


@app.get("/")
def root():
    return {"app": "ZealFlow", "version": "5.0.0", "status": "running"}


@app.get("/api/health")
def health():
    return {"status": "ok", "engine": "ready", "app": "ZealFlow", "max_images": MAX_IMAGES, "firebase_storage": firebase_configured()}


@app.post("/api/jobs")
def create_job(
    raw_images: list[UploadFile] = File(default=[]),
    zip_file: UploadFile | None = File(default=None),
    reference_front: UploadFile | None = File(default=None),
    reference_back: UploadFile | None = File(default=None),
    prompt_mode: str = Form("default"),
    custom_prompt: str = Form(""),
    aspect_ratio: str = Form("auto"),
    quality: str = Form("high"),
    preservation: str = Form("maximum"),
    batch_name: str = Form(""),
):
    job_id = uuid4().hex[:12]
    job_dir = JOBS_DIR / job_id
    input_dir = job_dir / "inputs"
    refs_dir = job_dir / "references"
    temp_dir = job_dir / "temp"
    input_dir.mkdir(parents=True, exist_ok=True); refs_dir.mkdir(parents=True, exist_ok=True); temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        refs = []
        for role, upload in (("front", reference_front), ("back", reference_back)):
            if upload and upload.filename:
                ext = Path(upload.filename).suffix.lower()
                if ext not in IMAGE_EXTS:
                    raise ValueError(f"{role.title()} reference must be JPG, JPEG, PNG, or WEBP")
                dest = refs_dir / f"{role}{ext}"
                save_upload(upload, dest)
                if not is_valid_image(dest):
                    raise ValueError(f"{role.title()} reference is not a valid image")
                remote = upload_if_configured(dest, f"{firebase_prefix()}/jobs/{job_id}/references/{dest.name}")
                ref_item = {"role": role, "filename": Path(upload.filename).name, "stored_name": dest.name, **image_meta(dest)}
                if remote:
                    ref_item["firebase_path"] = remote
                refs.append(ref_item)
        if not refs:
            raise ValueError("Upload at least one reference image (Front or Back).")

        collected: list[Path] = []
        if zip_file and zip_file.filename:
            if Path(zip_file.filename).suffix.lower() != ".zip":
                raise ValueError("ZIP input must be a .zip file")
            collected.extend(collect_zip_images(zip_file, input_dir, temp_dir))
        for upload in raw_images:
            if not upload.filename:
                continue
            ext = Path(upload.filename).suffix.lower()
            if ext not in IMAGE_EXTS:
                continue
            dest = unique_destination(input_dir, Path(upload.filename).name)
            save_upload(upload, dest)
            if is_valid_image(dest):
                collected.append(dest)
            else:
                dest.unlink(missing_ok=True)

        # de-duplicate paths while preserving order
        seen = set(); collected = [p for p in collected if not (p.name.casefold() in seen or seen.add(p.name.casefold()))]
        if not collected:
            raise ValueError("Upload at least one raw image or a ZIP containing images.")
        if len(collected) > MAX_IMAGES:
            raise ValueError(f"Maximum {MAX_IMAGES} raw images are allowed per batch. Found {len(collected)}.")

        images = []
        for p in collected:
            remote = upload_if_configured(p, f"{firebase_prefix()}/jobs/{job_id}/inputs/{p.name}")
            item = {
                "filename": p.name,
                "stored_name": p.name,
                "output_name": p.name,
                "status": "waiting",
                "error": None,
                **image_meta(p),
            }
            if remote:
                item["firebase_path"] = remote
            images.append(item)

        status = {
            "job_id": job_id,
            "batch_name": (batch_name or "").strip() or f"Batch {datetime.now().strftime('%d %b %Y · %H:%M')}",
            "status": "ready",
            "total_images": len(images), "completed_images": 0, "processing_images": 0, "failed_images": 0,
            "current_image": None, "current_index": None, "zip_ready": False,
            "created_at": now_iso(), "updated_at": now_iso(), "started_at": None, "finished_at": None,
            "message": f"{len(images)} raw images ready with {len(refs)} reference image(s).",
            "references": refs,
            "settings": {
                "prompt_mode": prompt_mode if prompt_mode in {"default", "custom", "skip"} else "default",
                "custom_prompt": custom_prompt,
                "aspect_ratio": aspect_ratio,
                "quality": quality if quality in {"standard", "high"} else "high",
                "preservation": preservation if preservation in {"maximum", "medium"} else "maximum",
            },
            "images": images,
        }
        write_status(job_dir, status)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return public_status(status)
    except Exception as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str, x_openai_key: str | None = Header(default=None)):
    if not (JOBS_DIR / job_id).exists():
        raise HTTPException(status_code=404, detail="Batch not found")
    submit_job(job_id, api_key=x_openai_key)
    return {"success": True, "job_id": job_id}


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, x_openai_key: str | None = Header(default=None)):
    job_dir = JOBS_DIR / job_id
    status = read_status(job_dir)
    if not any(x["status"] == "failed" for x in status["images"]):
        raise HTTPException(status_code=400, detail="There are no failed images to retry")
    submit_job(job_id, True, api_key=x_openai_key)
    return {"success": True, "job_id": job_id}


@app.get("/api/jobs")
def list_jobs():
    jobs = []
    for directory in JOBS_DIR.iterdir():
        if directory.is_dir() and status_path(directory).exists():
            try:
                s = read_status(directory)
                jobs.append({k: s.get(k) for k in ["job_id", "batch_name", "status", "total_images", "completed_images", "failed_images", "created_at", "updated_at", "zip_ready"]})
            except Exception:
                pass
    return sorted(jobs, key=lambda x: x.get("created_at") or "", reverse=True)[:100]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job_dir = JOBS_DIR / job_id
    status = read_status(job_dir)
    if status["status"] == "processing":
        with FUTURES_LOCK:
            future = FUTURES.get(job_id)
            active = bool(future and not future.done())
        if not active:
            for item in status["images"]:
                if item["status"] == "processing": item["status"] = "waiting"
            status["status"] = "ready"; status["current_image"] = None; recalc(status)
            status["message"] = "Processing was interrupted. Start again to resume; completed files are retained."
            write_status(job_dir, status)
    return public_status(status)


def safe_item(job_id: str, index: int) -> tuple[Path, dict]:
    job_dir = JOBS_DIR / job_id
    status = read_status(job_dir)
    if index < 0 or index >= len(status["images"]):
        raise HTTPException(status_code=404, detail="Image not found")
    return job_dir, status["images"][index]


@app.get("/api/jobs/{job_id}/input/{index}")
def input_image(job_id: str, index: int):
    job_dir, item = safe_item(job_id, index)
    path = job_dir / "inputs" / item["stored_name"]
    if not path.exists(): raise HTTPException(status_code=404, detail="Input not found")
    return FileResponse(path)


@app.get("/api/jobs/{job_id}/output/{index}")
def output_image(job_id: str, index: int):
    job_dir, item = safe_item(job_id, index)
    path = job_dir / "output" / item["output_name"]
    if not path.exists(): raise HTTPException(status_code=404, detail="Output not ready")
    return FileResponse(path)


@app.get("/api/jobs/{job_id}/output/{index}/download")
def download_single(job_id: str, index: int):
    job_dir, item = safe_item(job_id, index)
    path = job_dir / "output" / item["output_name"]
    if not path.exists(): raise HTTPException(status_code=404, detail="Output not ready")
    return FileResponse(path, filename=item["output_name"])


@app.get("/api/jobs/{job_id}/reference/{role}")
def reference_image(job_id: str, role: str):
    job_dir = JOBS_DIR / job_id
    status = read_status(job_dir)
    ref = next((r for r in status.get("references", []) if r["role"] == role), None)
    if not ref: raise HTTPException(status_code=404, detail="Reference not found")
    return FileResponse(job_dir / "references" / ref["stored_name"])


@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str):
    path = JOBS_DIR / job_id / "ZealFlow-Output.zip"
    if not path.exists(): raise HTTPException(status_code=404, detail="Output ZIP is not ready")
    return FileResponse(path, filename=f"ZealFlow-{job_id}.zip", media_type="application/zip")
