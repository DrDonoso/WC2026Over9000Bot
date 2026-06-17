"""Daily "rich" image evolution — asks an image model to make the person richer each day.

Richness escalation is IMPLICIT: each iteration takes the previous output as input,
so the model only needs to add a few new touches on top of what is already there.
The key constant to tweak is RICH_EDIT_PROMPT (base instruction passed to the image model).
"""

from __future__ import annotations

import base64
import glob as _glob
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import pytz
from openai import AsyncOpenAI

from worldcup_bot.config import (
    Settings,
    _effective_image_api_key,
    _effective_image_base_url,
)

log = logging.getLogger(__name__)

# ── PROMPT — edit this to change how the model transforms the image ───────────

RICH_EDIT_PROMPT = (
    "Transform this photo into a photorealistic image where the person looks dramatically "
    "wealthier and more glamorous. "
    "CRITICAL: the result MUST look clearly and NOTICEABLY richer and more luxurious than the "
    "input image — escalate the opulence visibly each iteration: a more expensive outfit, "
    "a grander setting, more lavish props and wealth signals than before. "
    "Keep the EXACT same face, head, skin tone and facial features — the same identity. "
    "Dress them in a brand-new, elegant, fully-clothed luxury outfit (for example a tailored "
    "designer suit, a tuxedo, a smart blazer or a refined formal coat) — always tasteful and "
    "fully clothed. "
    "You MAY occasionally add tasteful accessories such as elegant sunglasses or a stylish hat "
    "(vary it; not every time). "
    "Give them a new confident pose with hands in view. "
    "Place them in a new opulent setting and add a few varied signs of wealth "
    "(an elegant entourage, a luxury car, a yacht, a private jet, fine jewellery) — "
    "a few new touches each time, growing gradually. "
    "Classy, elegant, photorealistic."
)

RICH_FACE_ANCHOR_CLAUSE = (
    " A second reference image (the ORIGINAL photo) is provided; match the face, "
    "skin tone and features EXACTLY to that original. "
    "Use the first image for the wealthy style, but SURPASS it — the new image must look "
    "clearly richer and more luxurious than the first, not merely match its opulence. "
    "Invent a new elegant outfit and a new pose; keep the person fully and tastefully clothed."
)

RICH_CAPTION_PROMPT = (
    "Eres la persona que aparece en la imagen. Te estás forrando a costa de amañar la porra "
    "del grupo — llevas días ganando a base de trucos y los demás no se han enterado. "
    "Esta imagen se genera todos los días y tu riqueza crece cada jornada a nuestra costa. "
    "Escribe en PRIMERA PERSONA un mensaje corto (unas 4-5 líneas) presumiendo de cómo te "
    "has puesto de rico a costa del grupo. "
    "Menciona qué te has comprado, adónde has ido de vacaciones, qué nuevos lujos tienes — "
    "inspirándote en lo que ha cambiado entre la foto de ANTES y la de DESPUÉS. "
    "Tono: chulesco, prepotente y burlón, despreciando al resto del grupo de la porra. "
    "FUNDAMENTAL: VARÍA cada día — no empieces siempre igual, no repitas las mismas aperturas, "
    "los mismos insultos ni las mismas coletillas. Sé creativo con el vocabulario — "
    "inventa palabras e insultos frescos en vez de repetir siempre los mismos. "
    "Separa las frases con SALTOS DE LÍNEA, NUNCA con barras \"/\" ni con \" / \". "
    "Sin hashtags, sin markdown, sin explicar la foto — habla como si fuera tu vida real. "
    "Menos de 600 caracteres."
)

# ── History constants ─────────────────────────────────────────────────────────

RICH_HISTORY_FILE = "rich_history.txt"
RICH_HISTORY_MAX_LINES = 30

RICH_CAPTIONS_FILE = "rich_captions.txt"
RICH_CAPTIONS_MAX = 6


def build_rich_prompt(history: str = "", anchor: bool = False) -> str:
    """Return the full editing prompt for one wealth-escalation iteration.

    Richness escalation is implicit: each run takes the previous output as input,
    so the model only needs to add a few new touches on top of what is already there.
    When ``history`` is non-empty, a no-repeat clause is appended so the model
    introduces NEW luxuries/scenes rather than repeating past days.
    When ``anchor`` is True, appends :data:`RICH_FACE_ANCHOR_CLAUSE` instructing the
    model that a second reference image (the original) is provided to lock the face.
    """
    base = RICH_EDIT_PROMPT
    if history:
        base += (
            " Things already shown in previous days (choose DIFFERENT new elements"
            f" / a different location; do NOT repeat these): {history}"
        )
    if anchor:
        base += RICH_FACE_ANCHOR_CLAUSE
    return base


# ── level persistence ─────────────────────────────────────────────────────────

_STATE_FILE = "rich_state.json"


def load_level(state_dir: str) -> int:
    """Return the current iteration counter from state JSON (0 if missing or corrupt)."""
    path = os.path.join(state_dir, _STATE_FILE)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return int(data["level"])
    except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
        return 0


def save_level(state_dir: str, level: int) -> None:
    """Persist the current iteration counter to state JSON."""
    path = os.path.join(state_dir, _STATE_FILE)
    os.makedirs(state_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"level": level}, fh)


# ── history helpers ───────────────────────────────────────────────────────────


def append_history(state_dir: str, date_str: str, level: int, memo: str) -> None:
    """Append one line to the history log and keep only the last RICH_HISTORY_MAX_LINES.

    Skips silently when *memo* is empty or whitespace.
    """
    if not memo or not memo.strip():
        return
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, RICH_HISTORY_FILE)
    line = f"{date_str} | iter {level} | {memo}"
    try:
        existing = (
            Path(path).read_text(encoding="utf-8").splitlines()
            if os.path.exists(path)
            else []
        )
    except Exception:
        existing = []
    lines = (existing + [line])[-RICH_HISTORY_MAX_LINES:]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_history_lines(state_dir: str) -> list[str]:
    """Return stripped, non-blank lines from the history file; [] if missing or corrupt."""
    path = os.path.join(state_dir, RICH_HISTORY_FILE)
    try:
        text = Path(path).read_text(encoding="utf-8")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    except Exception:
        return []


def format_history_for_prompt(state_dir: str, max_items: int | None = None) -> str:
    """Return a compact bullet-list of history lines, or '' if history is empty.

    When *max_items* is given, only the most recent that many lines are included.
    """
    lines = load_history_lines(state_dir)
    if max_items is not None:
        lines = lines[-max_items:]
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


# ── caption store helpers ─────────────────────────────────────────────────────


def append_caption(state_dir: str, caption: str) -> None:
    """Append one caption to the captions store; keep only the last RICH_CAPTIONS_MAX.

    Newlines within the caption are collapsed to a single space so each entry is
    a single line with no slash separators.
    Skips silently when *caption* is empty or whitespace.
    """
    if not caption or not caption.strip():
        return
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, RICH_CAPTIONS_FILE)
    single_line = re.sub(r'\s+', ' ', caption).strip()
    try:
        existing = (
            Path(path).read_text(encoding="utf-8").splitlines()
            if os.path.exists(path)
            else []
        )
    except Exception:
        existing = []
    lines = (existing + [single_line])[-RICH_CAPTIONS_MAX:]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_captions(state_dir: str) -> list[str]:
    """Return stripped, non-blank caption lines from the captions file; [] if missing."""
    path = os.path.join(state_dir, RICH_CAPTIONS_FILE)
    try:
        text = Path(path).read_text(encoding="utf-8")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    except Exception:
        return []


def format_captions_for_prompt(state_dir: str) -> str:
    """Return a newline-joined block of recent captions, or '' if none stored."""
    lines = load_captions(state_dir)
    if not lines:
        return ""
    return "\n".join(lines)


# ── image path selection ──────────────────────────────────────────────────────


def select_base_image(state_dir: str, data_dir: str = "/app/data") -> str:
    """Return the path of the image to use as the edit source.

    Priority:
    1. ``{state_dir}/rich_modified.png`` — the iteratively evolved image.
    2. First match of ``{data_dir}/rich/rich_original.*`` (jpg/png).

    Raises FileNotFoundError if neither exists.
    """
    evolved = os.path.join(state_dir, "rich_modified.png")
    if os.path.exists(evolved):
        return evolved

    candidates = _glob.glob(os.path.join(data_dir, "rich", "rich_original.*"))
    for ext in (".jpg", ".jpeg", ".png"):
        for c in candidates:
            if c.lower().endswith(ext):
                return c
    if candidates:
        return candidates[0]

    raise FileNotFoundError(
        f"No base image found: checked {evolved} and {data_dir}/rich/rich_original.*"
    )


def find_original_image(data_dir: str = "/app/data") -> str:
    """Return the path of the un-evolved original source image.

    Looks for ``{data_dir}/rich/rich_original.*`` (jpg/jpeg/png).
    Unlike :func:`select_base_image`, this always targets the original and
    never returns the evolved ``rich_modified.png`` from the state directory.

    Raises FileNotFoundError if no match exists.
    """
    candidates = _glob.glob(os.path.join(data_dir, "rich", "rich_original.*"))
    for ext in (".jpg", ".jpeg", ".png"):
        for c in candidates:
            if c.lower().endswith(ext):
                return c
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        f"No original image found: {data_dir}/rich/rich_original.*"
    )


# ── image editing ─────────────────────────────────────────────────────────────


async def edit_rich_image(
    *,
    api_key: str,
    base_url: str,
    model: str,
    image_path: str,
    prompt: str,
    size: str = "1024x1024",
    anchor_path: str | None = None,
    _client: object | None = None,
) -> bytes:
    """Call the images.edit endpoint and return decoded PNG bytes.

    When *anchor_path* is provided and differs from *image_path*, passes both
    images as a list ``[base_file, anchor_file]`` so the API can lock the face
    to the original reference while evolving the rest of the scene.

    Accepts ``_client`` for test injection (any object with an ``.images.edit``
    coroutine that returns ``resp.data[0].b64_json``).

    Raises RuntimeError on any failure so the calling job can log + swallow it.
    """
    client = _client or AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        use_anchor = (
            anchor_path is not None
            and os.path.abspath(anchor_path) != os.path.abspath(image_path)
        )
        if use_anchor:
            img_fh = open(image_path, "rb")
            anc_fh = open(anchor_path, "rb")
            try:
                resp = await client.images.edit(
                    model=model,
                    image=[img_fh, anc_fh],
                    prompt=prompt,
                    size=size,
                )
            finally:
                img_fh.close()
                anc_fh.close()
        else:
            with open(image_path, "rb") as img_fh:
                resp = await client.images.edit(
                    model=model,
                    image=img_fh,
                    prompt=prompt,
                    size=size,
                )
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64)
    except Exception as exc:
        raise RuntimeError(f"edit_rich_image failed: {exc}") from exc


# ── caption normalization ─────────────────────────────────────────────────────


def _normalize_caption(text: str) -> str:
    """Normalize newlines and whitespace in a caption string.

    - Replace literal escaped sequences ``\\r\\n`` and ``\\n`` with real newlines.
    - Normalize real ``\\r\\n`` → ``\\n``.
    - Convert slash separators (`` / ``, ``\\n/``, ``/\\n``) to real newlines.
    - Collapse 3+ consecutive newlines to exactly 2.
    - Strip trailing spaces on each line and strip the whole string.
    """
    # Replace literal backslash-n sequences (e.g. JSON where \\n was not decoded)
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    # Normalize real CRLF → LF
    text = text.replace("\r\n", "\n")
    # Convert slash separators (whitespace on both sides) to real newlines
    text = re.sub(r'\s+/\s+', '\n', text)
    # Strip trailing spaces on each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # Collapse 3+ consecutive newlines to exactly 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── caption generation ────────────────────────────────────────────────────────


async def generate_rich_caption(
    *,
    api_key: str,
    base_url: str,
    model: str,
    old_image_path: str,
    new_image_path: str,
    level: int,
    history: str = "",
    recent_captions: str = "",
    _client: object | None = None,
) -> tuple[str, str]:
    """Generate a cocky first-person caption comparing BEFORE and AFTER images.

    Uses the main chat model (multimodal) — NOT the image model key.
    Both images are base64-encoded and sent as inline data URLs.
    The OLD image MIME is inferred from its file extension.

    Returns ``(caption, memo)`` where *memo* is a terse list of new luxuries/places
    this iteration (useful for the history log).  When the model returns non-JSON,
    falls back to ``(raw_text, "")`` so the feature still works.

    ``recent_captions``: newline-joined block of recent past captions injected to
    encourage variety in openings, insults and sign-offs.

    Raises RuntimeError only on transport/API errors; the caller decides the fallback.
    """
    client = _client or AsyncOpenAI(api_key=api_key, base_url=base_url)
    try:
        old_ext = os.path.splitext(old_image_path)[1].lower()
        old_mime = "image/jpeg" if old_ext in (".jpg", ".jpeg") else "image/png"
        with open(old_image_path, "rb") as fh:
            old_b64 = base64.b64encode(fh.read()).decode()
        with open(new_image_path, "rb") as fh:
            new_b64 = base64.b64encode(fh.read()).decode()

        user_parts: list[dict] = [
            {"type": "text", "text": "Foto ANTES (menos rico):"},
            {"type": "image_url", "image_url": {"url": f"data:{old_mime};base64,{old_b64}"}},
            {"type": "text", "text": f"Foto DESPUÉS (más rico, nivel {level}):"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{new_b64}"}},
        ]
        if history:
            user_parts.append({
                "type": "text",
                "text": f"Memos ya usados — NO repitas estos lujos/lugares:\n{history}",
            })
        if recent_captions:
            user_parts.append({
                "type": "text",
                "text": (
                    "TEXTOS ANTERIORES (NO repitas su estructura, aperturas, insultos ni"
                    f" despedidas — usa vocabulario y coletillas DISTINTAS):\n{recent_captions}"
                ),
            })
        user_parts.append({
            "type": "text",
            "text": (
                'Devuelve SOLO un objeto JSON con este formato exacto:\n'
                '{"caption": "<tu mensaje, 4-5 líneas>", '
                '"memo": "<nuevos lujos/destinos mencionados esta vez, ≤120 chars, telegráfico>"}'
            ),
        })

        messages = [
            {"role": "system", "content": RICH_CAPTION_PROMPT},
            {"role": "user", "content": user_parts},
        ]
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=500,
            temperature=0.9,
        )
        raw = resp.choices[0].message.content.strip()

        # Strip markdown code fences the model may wrap around JSON
        text = raw
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):].strip()
                if text.endswith("```"):
                    text = text[:-3].strip()
                break

        try:
            data = json.loads(text)
            return _normalize_caption(str(data["caption"])), str(data.get("memo", "")).strip()
        except (json.JSONDecodeError, KeyError, TypeError):
            return _normalize_caption(raw), ""
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"generate_rich_caption failed: {exc}") from exc


# ── high-level orchestration ──────────────────────────────────────────────────


async def run_rich_iteration(
    settings: Settings,
    *,
    _client: object | None = None,
    _caption_client: object | None = None,
    _data_dir: str = "/app/data",
    _now: datetime | None = None,
) -> tuple[str, int, str]:
    """Run one wealth-escalation iteration and return (output_path, iteration, caption).

    - Image prompt uses last 12 memos (concise context window).
    - Caption uses the full history + recent 6 captions (for variety).
    - On caption success: appends memo to rich_history.txt (cap 30) and caption
      to rich_captions.txt (cap 6).
    - On caption failure: fallback caption returned; nothing appended.

    The chaining is natural: on the next call, select_base_image returns the file
    we just wrote.  ``_data_dir`` is injectable for tests (default ``/app/data``).
    ``_client`` drives image editing; ``_caption_client`` drives caption generation.
    ``_now`` overrides the current datetime (for tests).
    """
    api_key = _effective_image_api_key(settings)
    base_url = _effective_image_base_url(settings)
    model = settings.openai_image_model

    now = _now or datetime.now(pytz.timezone(settings.timezone))
    date_str = now.strftime("%Y-%m-%d")

    # Read state BEFORE editing
    image_history = format_history_for_prompt(settings.state_dir, max_items=12)
    full_history = format_history_for_prompt(settings.state_dir)
    recent_captions = format_captions_for_prompt(settings.state_dir)

    base_image = select_base_image(settings.state_dir, _data_dir)
    level = load_level(settings.state_dir) + 1

    # Anchor: when an evolved image exists, pass the original as a face reference
    # to prevent identity drift. Gracefully fall back if original is not found.
    try:
        original = find_original_image(_data_dir)
    except FileNotFoundError:
        original = base_image  # no distinct original → force single-image mode
    using_anchor = os.path.abspath(base_image) != os.path.abspath(original)

    prompt = build_rich_prompt(history=image_history, anchor=using_anchor)

    log.info("run_rich_iteration: iter=%d, base=%s, anchor=%s", level, base_image, using_anchor)

    png_bytes = await edit_rich_image(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_path=base_image,
        anchor_path=(original if using_anchor else None),
        prompt=prompt,
        _client=_client,
    )

    os.makedirs(settings.state_dir, exist_ok=True)
    tmp_path = os.path.join(settings.state_dir, "rich_modified.new.png")
    Path(tmp_path).write_bytes(png_bytes)

    # Generate caption via main chat model — best-effort, never fatal
    caption = "🤑 Cada día más rico a vuestra costa"
    if settings.openai_api_key and settings.openai_base_url and settings.openai_model:
        try:
            caption, memo = await generate_rich_caption(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
                old_image_path=base_image,
                new_image_path=tmp_path,
                level=level,
                history=full_history,
                recent_captions=recent_captions,
                _client=_caption_client,
            )
            append_history(settings.state_dir, date_str, level, memo)
            append_caption(settings.state_dir, caption)
        except Exception as exc:
            log.warning("run_rich_iteration: caption generation failed: %s", exc)
            caption = "🤑 Cada día más rico a vuestra costa"

    # Atomic rename: remove stale final if present, then promote temp
    final_path = os.path.join(settings.state_dir, "rich_modified.png")
    if os.path.exists(final_path):
        os.remove(final_path)
    os.replace(tmp_path, final_path)

    save_level(settings.state_dir, level)
    log.info("run_rich_iteration: written %s (%d bytes)", final_path, len(png_bytes))

    return final_path, level, caption
