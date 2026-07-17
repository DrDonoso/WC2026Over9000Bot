"""Daily "rich" image evolution — asks an image model to make the person richer each day.

Richness escalation is IMPLICIT: each iteration takes the previous output as input,
so the model only needs to add a few new touches on top of what is already there.
The key constant to tweak is RICH_EDIT_PROMPT (base instruction passed to the image model).
"""

from __future__ import annotations

import base64
import contextlib
import glob as _glob
import json
import logging
import os
import random
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
    "Vary the pose and activity every iteration — avoid repeating the same position. "
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

# ── Wealth-themes prompt (country-themed opulent props for yesterday's winners) ─

RICH_THEME_PROMPT = (
    "Given the following list of yesterday's football match winning countries, return a SHORT "
    "comma-separated list of opulent, funny, SPECIFIC luxury VISUAL elements — "
    "exactly ONE element per country, themed on that country's icons, culture, food, or "
    "landmarks — luxurious, tasteful and visual. "
    "IMPORTANT: do NOT default to gold/golden for every element — vary the type of luxury: "
    "use diamonds, platinum, marble, silk, crystal, caviar, designer furs, exotic woods, "
    "haute couture, precious jewels, rare materials, etc. Only use gold occasionally. "
    "Return ONLY the comma-separated list with NO extra text whatsoever. "
    "Examples of the vibe: "
    "Norway → a diamond-encrusted Viking longship; "
    "France → a caviar-topped artisan baguette on a marble tray; "
    "Mexico → a crystal platter of truffle nachos; "
    "England → a silk-lined tea set with hand-painted porcelain cups; "
    "Belgium → a private parliament building filled with Belgian chocolate sculptures; "
    "USA → surrounded by piles of platinum-banded US dollar bills. "
    "Now do the same for these countries:"
)

# ── Pose/activity pool (one picked at random each iteration) ──────────────────

POSE_ACTIVITIES = [
    "dancing at a lavish party",
    "standing confidently on a red carpet",
    "lounging on a chaise longue",
    "getting a spa massage",
    "partying with a glamorous crowd",
    "napping in an opulent king-size bed",
    "embracing an elegant companion",
    "walking a red carpet with an entourage",
    "posing with a glamorous entourage",
    "relaxing in an infinity pool",
    "being served by attentive staff",
    "laughing mid-celebration",
    "striding through a luxury penthouse",
    "being pampered at a private salon",
]

# ── History constants ─────────────────────────────────────────────────────────

RICH_HISTORY_FILE = "rich_history.txt"
RICH_HISTORY_MAX_LINES = 30

RICH_CAPTIONS_FILE = "rich_captions.txt"
RICH_CAPTIONS_MAX = 6

RICH_BIRTHDAY_MONTH = 7
RICH_BIRTHDAY_DAY = 8
RICH_BIRTH_YEAR = 1984   # turns 42 in 2026 (meaning-of-life gag); age auto-increments yearly

RICH_BIRTHDAY_CLAUSE = (
    " IMPORTANT: today is the person's BIRTHDAY — turn the scene into an opulent, over-the-top "
    "luxury BIRTHDAY CELEBRATION: a lavish party with a giant multi-tiered birthday cake, "
    "balloons, party decorations and a celebratory banner. The cake and/or banner MUST clearly "
    "and legibly display the number \"{age}\" (their age). Keep it tasteful and photorealistic, "
    "celebrating their {age}th birthday in grand style."
)


def is_rich_birthday(now: datetime) -> bool:
    """True when *now* is the rich character's birthday (July 8, any year)."""
    return now.month == RICH_BIRTHDAY_MONTH and now.day == RICH_BIRTHDAY_DAY


def rich_birthday_age(now: datetime) -> int:
    """Age the character turns on *now*'s birthday (now.year - RICH_BIRTH_YEAR)."""
    return now.year - RICH_BIRTH_YEAR


# ── Micky birthday constants (July 10) ───────────────────────────────────────

MICKY_BIRTHDAY_MONTH = 7
MICKY_BIRTHDAY_DAY = 10
MICKY_BIRTH_YEAR = 1984   # turns 42 in 2026; age auto-increments yearly

MICKY_IMAGE = "micky.jpg"

MICKY_BIRTHDAY_CLAUSE = (
    " IMPORTANT: a THIRD reference image is provided — it contains MICKY (the birthday man)"
    " and also the rich character together. In this special scene MICKY is the clear"
    " PROTAGONIST and CENTREPIECE of the composition: feature him prominently in the"
    " foreground or centre. Place the rich character visibly NEXT TO him in a supporting role."
    " Transform the scene into an opulent, over-the-top luxury BIRTHDAY CELEBRATION for"
    " MICKY's {age}th birthday: a lavish party with a giant multi-tiered birthday cake,"
    " balloons, party decorations and a celebratory banner. The cake and/or banner MUST clearly"
    " and legibly display the number \"{age}\" (his age). Match MICKY's face EXACTLY from the"
    " third reference image and the rich character's face EXACTLY from the second reference."
    " Both men must be clearly visible and celebrating together. Tasteful, fully clothed,"
    " photorealistic."
)


def is_micky_birthday(now: datetime) -> bool:
    """True when *now* is Micky's birthday (July 10, any year)."""
    return now.month == MICKY_BIRTHDAY_MONTH and now.day == MICKY_BIRTHDAY_DAY


def micky_birthday_age(now: datetime) -> int:
    """Age Micky turns on *now*'s birthday (now.year - MICKY_BIRTH_YEAR)."""
    return now.year - MICKY_BIRTH_YEAR


# ── Apex constants (July 20 — day after the World Cup Final) ──────────────────

RICH_APEX_MONTH = 7
RICH_APEX_DAY = 20

RICH_APEX_CLAUSE = (
    " APEX MODE — THE ABSOLUTE PINNACLE OF WEALTH AND POWER: Today this person has achieved the"
    " single richest, most powerful status of any being in the entire planet and universe —"
    " utterly over-the-top, ridiculous, the supreme ruler of everything that exists."
    " Transform the scene into a jaw-dropping, cosmic, god-tier spectacle of supreme wealth:"
    " an ocean of gold and diamonds stretching to every horizon, a colossal ornate"
    " throne towering above entire cities, a galactic/cosmic backdrop with nebulae and stars,"
    " vast cheering crowds celebrating him, monumental statues and landmarks built in"
    " his honour radiating absolute power — wealth and grandeur that defy all comprehension."
    " PROMINENTLY incorporate national symbols of {country}: the flag of {country} draped"
    " everywhere in the scene, the national colours of {country} dominant throughout the"
    " composition, iconic landmarks and cultural icons of {country} reimagined at colossal scale"
    " — celebrating {country}'s World Cup Final victory as the event that made him ruler of the world."
    " Keep EXACT same face/identity, tasteful, fully clothed, photorealistic, epic scale."
)

RICH_APEX_TRAMPLE_SENTENCE = (
    " The defeated {loser} national flag lies discarded beneath his feet as a trophy,"
    " a symbol of {loser}'s World Cup Final loss — he stands above it in total dominance,"
    " indifferent, victorious, untouchable."
)


def is_rich_apex(now: datetime) -> bool:
    """True when *now* is Apex day — July 20, the day after the World Cup Final."""
    return now.month == RICH_APEX_MONTH and now.day == RICH_APEX_DAY


# ── Death constants (July 21 — two days after the World Cup Final) ────────────

RICH_DEATH_MONTH = 7
RICH_DEATH_DAY = 21

RICH_DEATH_CLAUSE = (
    " FAREWELL — A DIGNIFIED, PEACEFUL PASSING: The person appears to have died."
    " Generate a DIGNIFIED, TASTEFUL, PEACEFUL farewell scene — absolutely NON-GORY,"
    " NON-VIOLENT, no blood, no wounds whatsoever."
    " Show the person lying SERENELY IN STATE in an opulent grand memorial chamber:"
    " surrounded by sumptuous flower arrangements, softly burning candles,"
    " silent respectful mourners bowing their heads in grief,"
    " extraordinary wealth and grandeur all around."
    " Soft celestial light filters through the scene, bathing everything in a warm peaceful glow."
    " The person's face is completely serene and at peace, eyes gently closed."
    " The overall mood is one of profound dignity, grace, tenderness, and love —"
    " a beautiful, opulent, deeply moving farewell."
    " Keep EXACT same face/identity, photorealistic."
)

RICH_DEATH_CAPTION_PROMPT = (
    "Eres la persona de la imagen. Escribe en PRIMERA PERSONA una despedida emotiva y sincera"
    " para el grupo — como si fuera la más importante que escribirás:"
    " llena de AMOR y GRATITUD hacia todos los del grupo,"
    " pidiendo perdón con cariño por haberte enriquecido a su costa todos estos días,"
    " agradeciéndoles de corazón los años de porra y amistad compartida,"
    " despidiéndote de cada miembro del grupo con afecto y ternura,"
    " y enviando un mensaje de amor, paz y esperanza para todos."
    " Tono: completamente opuesto al chulesco habitual — sincero, emotivo, sereno y lleno de amor."
    " Unas 4-6 líneas. Emojis sobrios y cálidos: 🕊️ ❤️ 🙏."
    " Separa las frases con SALTOS DE LÍNEA, NUNCA con barras '/' ni con ' / '."
    " Sin hashtags, sin markdown. Menos de 600 caracteres."
)


def is_rich_death(now: datetime) -> bool:
    """True when *now* is Death day — July 21, two days after the World Cup Final."""
    return now.month == RICH_DEATH_MONTH and now.day == RICH_DEATH_DAY


def build_rich_prompt(history: str = "", anchor: bool = False, themes: str = "", pose: str = "", birthday: bool = False, age: int | None = None, micky_birthday: bool = False, apex: bool = False, apex_country: str = "", apex_loser: str = "", death: bool = False) -> str:
    """Return the full editing prompt for one wealth-escalation iteration.

    Richness escalation is implicit: each run takes the previous output as input,
    so the model only needs to add a few new touches on top of what is already there.
    When ``history`` is non-empty, a no-repeat clause is appended so the model
    introduces NEW luxuries/scenes rather than repeating past days.
    When ``themes`` is non-empty (opulent country-themed props from yesterday's winners),
    a clause is added asking the model to incorporate those elements tastefully.
    When ``pose`` is non-empty (one entry from :data:`POSE_ACTIVITIES`), a clause forces
    the model to show the person in that specific activity so poses vary each iteration.
    When ``birthday`` is True, appends :data:`RICH_BIRTHDAY_CLAUSE` (rich's own birthday party theme).
    When ``micky_birthday`` is True, appends :data:`MICKY_BIRTHDAY_CLAUSE` describing the third
    reference image and instructing the model to make Micky the protagonist.
    When ``apex`` is True, appends :data:`RICH_APEX_CLAUSE` with the god-tier richest-being
    scene incorporating ``apex_country``'s national symbols (or "the champion nation" if empty).
    When ``apex_loser`` is also non-empty, appends :data:`RICH_APEX_TRAMPLE_SENTENCE` so the
    character also tramples the loser's flag — omitted entirely when ``apex_loser`` is empty.
    When ``death`` is True, appends :data:`RICH_DEATH_CLAUSE` for the dignified farewell scene.
    When ``anchor`` is True, appends :data:`RICH_FACE_ANCHOR_CLAUSE` instructing the
    model that a second reference image (the original) is provided to lock the face.
    Apex and death clauses are placed BEFORE the anchor clause.
    """
    base = RICH_EDIT_PROMPT
    if history:
        base += (
            " Things already shown in previous days (choose DIFFERENT new elements"
            f" / a different location; do NOT repeat these): {history}"
        )
    if themes:
        base += (
            " ALSO incorporate a few of these opulent, country-themed luxury elements"
            " into the scene, worked in tastefully (inspired by yesterday's winning"
            f" countries): {themes}."
        )
    if pose:
        base += (
            f" In THIS image, show the person {pose}."
            " VARY the pose and activity each time — do NOT default to sitting and toasting with champagne."
        )
    if birthday and age is not None:
        base += RICH_BIRTHDAY_CLAUSE.format(age=age)
    if micky_birthday and age is not None:
        base += MICKY_BIRTHDAY_CLAUSE.format(age=age)
    if apex:
        base += RICH_APEX_CLAUSE.format(country=apex_country or "the champion nation")
        if apex_loser:
            base += RICH_APEX_TRAMPLE_SENTENCE.format(loser=apex_loser)
    if death:
        base += RICH_DEATH_CLAUSE
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


def find_micky_image(data_dir: str = "/app/data") -> str:
    """Return the path of the Micky reference image used on his birthday (July 10).

    Looks for ``{data_dir}/rich/micky.*`` (jpg/jpeg/png first, then any match).
    This image contains both Micky and the rich character and is passed as a third
    reference to :func:`edit_rich_image` on Micky's birthday.

    Raises FileNotFoundError if no match exists.
    """
    candidates = _glob.glob(os.path.join(data_dir, "rich", "micky.*"))
    for ext in (".jpg", ".jpeg", ".png"):
        for c in candidates:
            if c.lower().endswith(ext):
                return c
    if candidates:
        return candidates[0]
    raise FileNotFoundError(
        f"No Micky image found: {data_dir}/rich/micky.*"
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
    extra_paths: list[str] | None = None,
    _client: object | None = None,
) -> bytes:
    """Call the images.edit endpoint and return decoded PNG bytes.

    When *anchor_path* is provided and differs from *image_path*, passes both
    images as a list ``[base_file, anchor_file]`` so the API can lock the face
    to the original reference while evolving the rest of the scene.

    When *extra_paths* is provided (e.g. ``[micky_path]`` on his birthday), those
    file handles are appended AFTER the anchor: ``[base, anchor, *extras]``.  All
    file handles are opened and closed safely via :class:`contextlib.ExitStack`.

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
        extra = [p for p in (extra_paths or []) if p]
        with contextlib.ExitStack() as stack:
            img_fh = stack.enter_context(open(image_path, "rb"))
            extra_fhs = [stack.enter_context(open(p, "rb")) for p in extra]
            if use_anchor:
                anc_fh = stack.enter_context(open(anchor_path, "rb"))
                image_arg: object = [img_fh, anc_fh, *extra_fhs]
            elif extra_fhs:
                image_arg = [img_fh, *extra_fhs]
            else:
                image_arg = img_fh
            resp = await client.images.edit(
                model=model,
                image=image_arg,
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
    birthday: bool = False,
    age: int | None = None,
    micky_birthday: bool = False,
    apex: bool = False,
    apex_country: str = "",
    apex_loser: str = "",
    death: bool = False,
    _client: object | None = None,
) -> tuple[str, str]:
    """Generate a first-person caption comparing BEFORE and AFTER images.

    Uses the main chat model (multimodal) — NOT the image model key.
    Both images are base64-encoded and sent as inline data URLs.
    The OLD image MIME is inferred from its file extension.

    Returns ``(caption, memo)`` where *memo* is a terse list of new luxuries/places
    this iteration (useful for the history log).  When the model returns non-JSON,
    falls back to ``(raw_text, "")`` so the feature still works.

    ``recent_captions``: newline-joined block of recent past captions injected to
    encourage variety in openings, insults and sign-offs.

    When ``micky_birthday`` is True, an explicit instruction to congratulate Micky
    by name is injected so the caption greets him first.

    When ``apex`` is True, uses the cocky :data:`RICH_CAPTION_PROMPT` with an added
    megalomaniac apex instruction referencing ``apex_country`` and, when ``apex_loser``
    is non-empty, a gloat about crushing the loser.

    When ``death`` is True, uses :data:`RICH_DEATH_CAPTION_PROMPT` as the system prompt
    (full tone shift — sincere farewell) instead of the cocky default.

    Raises RuntimeError only on transport/API errors; the caller decides the fallback.
    """
    client = _client or AsyncOpenAI(api_key=api_key, base_url=base_url)
    system_prompt = RICH_DEATH_CAPTION_PROMPT if death else RICH_CAPTION_PROMPT
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
        if birthday and age is not None:
            user_parts.append({
                "type": "text",
                "text": (
                    f"HOY ES TU CUMPLEAÑOS: hoy cumples {age} años. Celébralo A LO GRANDE en el mensaje además de "
                    f"presumir de tu riqueza a costa del grupo — menciona EXPLÍCITAMENTE que cumples {age}."
                ),
            })
        if micky_birthday and age is not None:
            user_parts.append({
                "type": "text",
                "text": (
                    f"HOY ES EL CUMPLEAÑOS DE MICKY: hoy Micky cumple {age} años."
                    " FELICÍTALE EXPLÍCITAMENTE por su cumpleaños en el mensaje,"
                    " deséale feliz cumpleaños por su nombre (Micky),"
                    " y celebradlo a lo grande. El saludo a Micky es OBLIGATORIO."
                ),
            })
        if apex:
            country_sentence = (
                f" {apex_country} ha ganado el Mundial y te ha coronado amo del mundo."
                if apex_country else ""
            )
            loser_sentence = (
                f" Has aplastado a {apex_loser} bajo tus pies en la derrota más humillante de la historia."
                if apex_loser else ""
            )
            user_parts.append({
                "type": "text",
                "text": (
                    "HOY HAS ALCANZADO LA CIMA: eres LA PERSONA MÁS RICA DEL UNIVERSO y el ser"
                    " más poderoso jamás visto. Presume de forma desmesurada y ridícula de que lo"
                    f" posees TODO.{country_sentence}{loser_sentence}"
                ),
            })
        if death:
            user_parts.append({
                "type": "text",
                "text": (
                    "Despídete del grupo con un mensaje sincero, emotivo y lleno de amor y gratitud."
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
            {"role": "system", "content": system_prompt},
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


async def generate_wealth_themes(
    api_key: str,
    base_url: str,
    model: str,
    winners: list[str],
    *,
    _client: object | None = None,
) -> str:
    """Return a comma-separated string of opulent, country-themed luxury props for yesterday's winners.

    Calls the chat model with :data:`RICH_THEME_PROMPT` + the winner country names.
    Best-effort: never raises. Returns ``""`` if *winners* is empty.
    Falls back to ``"opulent luxury {country}-themed elements"`` per country on any error.
    """
    if not winners:
        return ""
    fallback = ", ".join(f"opulent luxury {c}-themed elements" for c in winners)
    try:
        client = _client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        user_text = RICH_THEME_PROMPT + " " + ", ".join(winners)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": user_text}],
            max_completion_tokens=150,
            temperature=0.8,
        )
        result = resp.choices[0].message.content.strip()
        return result if result else fallback
    except Exception:
        log.warning("generate_wealth_themes: failed, using fallback for winners=%s", winners)
        return fallback


async def run_rich_iteration(
    settings: Settings,
    *,
    _client: object | None = None,
    _caption_client: object | None = None,
    _data_dir: str = "/app/data",
    _now: datetime | None = None,
    winners: list[str] | None = None,
    losers: list[str] | None = None,
) -> tuple[str, int, str]:
    """Run one wealth-escalation iteration and return (output_path, iteration, caption).

    - Image prompt uses last 12 memos (concise context window).
    - Caption uses the full history + recent 6 captions (for variety).
    - On caption success: appends memo to rich_history.txt (cap 30) and caption
      to rich_captions.txt (cap 6).
    - On caption failure: fallback caption returned; nothing appended.

    The chaining is natural: on the next call, select_base_image returns the file
    we just wrote.  ``_data_dir`` is injectable for tests (default ``/app/data``).
    ``_client`` drives image editing; ``_caption_client`` drives caption generation
    (and also theme generation, which reuses the same chat model).
    ``_now`` overrides the current datetime (for tests).
    ``winners`` (optional): list of winning country names from yesterday's matches;
    used to generate opulent country-themed props that are woven into the scene.
    ``losers`` (optional): list of losing country names from yesterday's matches;
    used on the Apex day to add the trampled-loser-flag element to the scene.

    **Micky birthday (July 10):** generates a special 3-image celebration scene but
    does NOT promote the result into the evolution chain — ``rich_modified.png`` and
    the level counter are left untouched so the daily wealth escalation continues
    cleanly from the previous day's output the next morning.  The output is written
    to ``rich_micky_birthday.png`` in the state directory and that path is returned.

    **Apex (July 20 — day after the Final):** uses the normal promote path with the
    apex clause prominent in the image prompt.  The winning country (``winners[0]``
    when available) is woven into the scene as national symbols; ``losers[0]``
    (when available) is trampled underfoot in humiliating defeat.

    **Death (July 21):** writes to a separate ``rich_death.png`` and does NOT
    promote into the evolution chain, mirroring the Micky birthday behaviour.
    Caption uses :data:`RICH_DEATH_CAPTION_PROMPT` (sincere farewell tone).
    """
    api_key = _effective_image_api_key(settings)
    base_url = _effective_image_base_url(settings)
    model = settings.openai_image_model

    now = _now or datetime.now(pytz.timezone(settings.timezone))
    date_str = now.strftime("%Y-%m-%d")

    birthday = is_rich_birthday(now)
    age = rich_birthday_age(now)
    if birthday:
        log.info("run_rich_iteration: BIRTHDAY MODE active — age=%d", age)

    micky_birthday = is_micky_birthday(now)
    micky_age = micky_birthday_age(now)
    if micky_birthday:
        log.info("run_rich_iteration: MICKY BIRTHDAY MODE active — age=%d", micky_age)

    apex = is_rich_apex(now)
    death = is_rich_death(now)
    apex_country = winners[0] if (apex and winners) else ""
    apex_loser = losers[0] if (apex and losers) else ""
    if apex:
        log.info("run_rich_iteration: APEX MODE active — country=%r, loser=%r", apex_country, apex_loser)
    if death:
        log.info("run_rich_iteration: DEATH MODE active")

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

    # Resolve Micky image path — fall back gracefully if absent
    micky_path: str | None = None
    if micky_birthday:
        try:
            micky_path = find_micky_image(_data_dir)
        except FileNotFoundError:
            log.warning(
                "run_rich_iteration: micky.jpg not found in %s/rich/ — "
                "falling back to normal (non-Micky) iteration",
                _data_dir,
            )
            micky_birthday = False

    # Compute country-themed opulent props from yesterday's winners — best-effort.
    # Skip for apex (the apex clause handles the winning country directly) and for
    # death (a lying-in-state scene needs no party props).
    themes = ""
    if (
        winners
        and settings.openai_api_key
        and settings.openai_base_url
        and settings.openai_model
        and not apex
        and not death
    ):
        themes = await generate_wealth_themes(
            settings.openai_api_key,
            settings.openai_base_url,
            settings.openai_model,
            winners,
            _client=_caption_client,
        )
    log.info(
        "run_rich_iteration: iter=%d, base=%s, anchor=%s, micky_birthday=%s, apex=%s, death=%s, winners=%s, themes=%r",
        level, base_image, using_anchor, micky_birthday, apex, death, winners, themes,
    )

    pose = random.choice(POSE_ACTIVITIES)
    if micky_birthday:
        # Micky birthday: Micky is protagonist; use micky_age for the birthday clause.
        # birthday=False because July 10 is NOT rich's birthday.
        prompt = build_rich_prompt(
            history=image_history,
            anchor=True,  # rich_original.jpg always included as 2nd ref
            themes=themes,
            pose=pose,
            birthday=False,
            age=micky_age,
            micky_birthday=True,
        )
    elif death:
        # Death: dignified farewell scene — no pose instruction needed.
        prompt = build_rich_prompt(
            history=image_history,
            anchor=using_anchor or True,  # always try to anchor face for death
            death=True,
        )
    else:
        prompt = build_rich_prompt(
            history=image_history,
            anchor=using_anchor or apex,  # force anchor for apex
            themes=themes,
            pose=pose,
            birthday=birthday,
            age=age,
            apex=apex,
            apex_country=apex_country,
            apex_loser=apex_loser,
        )

    extra_paths = [micky_path] if micky_birthday and micky_path else None
    # Force anchor (original face reference) for Micky, apex, and death
    anchor_arg = original if (using_anchor or micky_birthday or apex or death) else None

    png_bytes = await edit_rich_image(
        api_key=api_key,
        base_url=base_url,
        model=model,
        image_path=base_image,
        anchor_path=anchor_arg,
        extra_paths=extra_paths,
        prompt=prompt,
        _client=_client,
    )

    os.makedirs(settings.state_dir, exist_ok=True)

    if micky_birthday:
        # Micky birthday: write to a separate file, do NOT touch the evolution chain
        # (rich_modified.png, level, history, captions stay unchanged so the next
        # day's normal rich iteration continues cleanly from where it left off).
        tmp_path = os.path.join(settings.state_dir, "rich_micky_birthday.new.png")
        final_path = os.path.join(settings.state_dir, "rich_micky_birthday.png")
        Path(tmp_path).write_bytes(png_bytes)

        caption = f"🎂 ¡Feliz {micky_age} cumpleaños, Micky! Que los sigas cumpliendo a nuestra costa 🥂"
        if settings.openai_api_key and settings.openai_base_url and settings.openai_model:
            try:
                caption, _memo = await generate_rich_caption(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.openai_model,
                    old_image_path=base_image,
                    new_image_path=tmp_path,
                    level=level,
                    history=full_history,
                    recent_captions=recent_captions,
                    micky_birthday=True,
                    age=micky_age,
                    _client=_caption_client,
                )
            except Exception as exc:
                log.warning("run_rich_iteration: Micky birthday caption failed: %s", exc)
                caption = f"🎂 ¡Feliz {micky_age} cumpleaños, Micky! Que los sigas cumpliendo a nuestra costa 🥂"

        if os.path.exists(final_path):
            os.remove(final_path)
        os.replace(tmp_path, final_path)
        log.info("run_rich_iteration: Micky birthday image written %s (%d bytes)", final_path, len(png_bytes))
        # Do NOT call save_level / append_history / append_caption — chain stays clean
        return final_path, level, caption

    if death:
        # Death: write to a separate file, do NOT touch the evolution chain —
        # mirroring the Micky birthday pattern exactly.
        tmp_path = os.path.join(settings.state_dir, "rich_death.new.png")
        final_path = os.path.join(settings.state_dir, "rich_death.png")
        Path(tmp_path).write_bytes(png_bytes)

        caption = "🕊️ Me marcho... os quiero a todos. Gracias por tanto. ❤️"
        if settings.openai_api_key and settings.openai_base_url and settings.openai_model:
            try:
                caption, _memo = await generate_rich_caption(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.openai_model,
                    old_image_path=base_image,
                    new_image_path=tmp_path,
                    level=level,
                    history=full_history,
                    recent_captions=recent_captions,
                    death=True,
                    _client=_caption_client,
                )
            except Exception as exc:
                log.warning("run_rich_iteration: death caption failed: %s", exc)
                caption = "🕊️ Me marcho... os quiero a todos. Gracias por tanto. ❤️"

        if os.path.exists(final_path):
            os.remove(final_path)
        os.replace(tmp_path, final_path)
        log.info("run_rich_iteration: death image written %s (%d bytes)", final_path, len(png_bytes))
        # Do NOT call save_level / append_history / append_caption — chain stays clean
        return final_path, level, caption

    # ── Normal path (includes Apex on July 20 as flags) ──────────────────────
    tmp_path = os.path.join(settings.state_dir, "rich_modified.new.png")
    Path(tmp_path).write_bytes(png_bytes)

    # Generate caption via main chat model — best-effort, never fatal
    if apex:
        default_caption = "🌍 El ser más rico del universo. Todo es mío."
    elif birthday:
        default_caption = f"🎂 ¡Hoy cumplo {age} y me lo monto a lo grande a vuestra costa!"
    else:
        default_caption = "🤑 Cada día más rico a vuestra costa"
    caption = default_caption

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
                birthday=birthday,
                age=age,
                apex=apex,
                apex_country=apex_country,
                apex_loser=apex_loser,
                _client=_caption_client,
            )
            append_history(settings.state_dir, date_str, level, memo)
            append_caption(settings.state_dir, caption)
        except Exception as exc:
            log.warning("run_rich_iteration: caption generation failed: %s", exc)
            caption = default_caption

    # Atomic rename: remove stale final if present, then promote temp
    final_path = os.path.join(settings.state_dir, "rich_modified.png")
    if os.path.exists(final_path):
        os.remove(final_path)
    os.replace(tmp_path, final_path)

    save_level(settings.state_dir, level)
    log.info("run_rich_iteration: written %s (%d bytes)", final_path, len(png_bytes))

    return final_path, level, caption
