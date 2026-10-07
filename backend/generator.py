import base64
import os
from contextlib import ExitStack
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")
PROMPT_FILE = ROOT / "prompts" / "universal_prompt.txt"

DEFAULT_PROMPT = """Create a professional image using the first uploaded image as the SOURCE that must be preserved, and the remaining uploaded image(s) as REFERENCE guidance for visual direction.

SOURCE PRESERVATION — HIGHEST PRIORITY:
- Preserve the source subject/product identity, color, graphics, text, logos, artwork placement, proportions, trims, seams, texture, wash, stones, embroidery, and construction as faithfully as possible.
- Do not invent, rewrite, mirror, simplify, replace, or redesign source artwork or branding.
- Keep the garment/product silhouette and key details recognizable and consistent with the source.

REFERENCE MATCHING:
- Match the reference image(s) for overall look and feel, framing, camera distance, camera angle, composition, model/subject pose where applicable, background character, lighting direction/softness, contrast, color mood, and editorial/studio aesthetic.
- Reference images guide presentation/style; they do not replace the source product details.
- If front and back reference images are supplied, use them together as one consistent visual system.

OUTPUT:
- Produce a clean, realistic, premium commercial result.
- Keep perspective, anatomy, garment construction, edges, shadows, and materials natural.
- Avoid extra text, watermarks, duplicated objects, malformed hands/body parts, or unrelated design changes.
"""


def build_prompt(prompt_mode: str, custom_prompt: str | None, preservation: str = "maximum") -> str:
    base = PROMPT_FILE.read_text(encoding="utf-8").strip() if PROMPT_FILE.exists() else DEFAULT_PROMPT
    if not base:
        base = DEFAULT_PROMPT

    preserve_note = (
        "Use MAXIMUM source preservation. Any conflict between reference style and source product details must be resolved in favor of preserving the source."
        if preservation == "maximum"
        else "Use balanced source preservation while matching the reference presentation closely."
    )

    mode = (prompt_mode or "default").lower()
    if mode == "custom" and (custom_prompt or "").strip():
        return f"{base}\n\nPRESERVATION MODE:\n{preserve_note}\n\nUSER INSTRUCTIONS:\n{custom_prompt.strip()}"
    if mode == "skip":
        # "Skip" means no user-authored prompt; the internal safety/identity prompt remains necessary
        # so the image API knows how source and reference images should be used.
        return f"{DEFAULT_PROMPT}\n\nPRESERVATION MODE:\n{preserve_note}"
    return f"{base}\n\nPRESERVATION MODE:\n{preserve_note}"


def generate_image(
    source_image: Path,
    output_file: Path,
    reference_images: list[Path] | None = None,
    prompt_mode: str = "default",
    custom_prompt: str | None = None,
    quality: str = "high",
    size: str = "1024x1536",
    preservation: str = "maximum",
    api_key: str | None = None,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_file.suffix.lower()
    output_format = "jpeg" if suffix in {".jpg", ".jpeg"} else suffix.lstrip(".")
    if output_format not in {"jpeg", "png", "webp"}:
        output_format = "png"
        output_file = output_file.with_suffix(".png")

    prompt = build_prompt(prompt_mode, custom_prompt, preservation)
    key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("OpenAI API key is missing. Open API Key in ZealFlow and save your key.")
    client = OpenAI(api_key=key)

    with ExitStack() as stack:
        files = [stack.enter_context(source_image.open("rb"))]
        for ref in reference_images or []:
            if ref and ref.exists():
                files.append(stack.enter_context(ref.open("rb")))

        result = client.images.edit(
            model=MODEL,
            image=files,
            prompt=prompt,
            quality="high" if quality == "high" else "medium",
            size=size,
            output_format=output_format,
        )

    image_b64 = result.data[0].b64_json
    if not image_b64:
        raise RuntimeError("Image API returned no image data")
    output_file.write_bytes(base64.b64decode(image_b64))
