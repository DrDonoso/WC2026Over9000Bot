"""Tongo phrases — easter egg for /tongo command.

Probability model:
- "Sanchez ens roba" (SANCHEZ_ENS_ROBA) is returned with exactly 1/3 probability
  on the default (no-reply) path.
- Otherwise a random phrase is chosen from the loaded phrase pool (2/3 probability).
SANCHEZ_ENS_ROBA must NOT appear in FRASES or the 1/3 guarantee would be violated.

Phrases and per-user config are loaded from a single YAML file (data/TongoUsers.yml)
with top-level keys ``phrases:`` (global pool) and ``users:`` (per-user overrides),
using mtime-based hot-reload.  FRASES is the built-in fallback when the file is
absent, empty, or has no ``phrases:`` list.
"""

from __future__ import annotations

import logging
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

SANCHEZ_ENS_ROBA = "Sanchez ens roba"

FRASES: list[str] = [
    "Per robos el de Javi a Raona",
    "Que si quiere la bolsa",
    "La culpa es de Suñé",
    "Ara envio a la buuuhhhambulancia",
    "si, si, però vas palmant",
    "Si, y Amalia y Suñé son mejores amigos ahora también",
    "Y Rosamar para cuando?",
    "Y Santvi para cuando?",
    "Y Lubián, pa cuando?",
    "Y una casa rural, pa cuando?"
    "Y las llaves de la piscina de Can Corts pa cuando?",
    "Y Sant Celoni para cuando?",
    "Y los pimientos rellenos pa cuando?"
    "Aguacate?",
    "Si, y Arbeloa es el jugador favorito de Laura. CAP17ÁN.",
    "Tongo es que Joan García no fue convocado con el Espanyol y vaya con el Barça, asi que a callar.",
    "Tongo es que el Espanyol siga en primera.",
    "Bueno, siempre nos quedará el consuelo que la única champions que se ha visto en el RCDE stadium sea la champions burger."
    "Como va a ser tongo, si no te interesa ni el futbol.",
    "Un conoooooo!! un cono!!!",
    "Por lo menos no somos italia.",
    "Tongo sería que ganara el mundial Cristiano.",
    "Ah, pero ChatGPT decia que si.",
]


def frase_argentino(gender: str) -> str:
    """Return the gender-aware argentino phrase ('f' for female, anything else for male)."""
    if gender == "f":
        return "Que tongo ni que tongo, eres mas pesada que una argentina."
    return "Que tongo ni que tongo, eres mas pesado que un argentino."


# ── context dataclass ─────────────────────────────────────────────────────────

@dataclass
class TongoContext:
    """All template variables available when rendering a tongo phrase."""
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    username: str = ""
    id: str = ""
    reply_to_first_name: str = ""
    reply_to_last_name: str = ""
    reply_to_full_name: str = ""
    reply_to_username: str = ""
    reply_to_id: str = ""
    has_reply: bool = False


def _extract_user_fields(user: object) -> tuple[str, str, str, str, str]:
    """Extract (first_name, last_name, full_name, username, id_str) safely.

    Works with real PTB User objects and plain fake objects (SimpleNamespace,
    MagicMock with explicit str attributes, etc.).
    """
    first_name = getattr(user, "first_name", None)
    first_name = first_name if isinstance(first_name, str) else ""

    last_name = getattr(user, "last_name", None)
    last_name = last_name if isinstance(last_name, str) else ""

    full_name = getattr(user, "full_name", None)
    if not isinstance(full_name, str):
        full_name = (first_name + " " + last_name).strip()

    username = getattr(user, "username", None)
    username = username if isinstance(username, str) else ""

    raw_id = getattr(user, "id", None)
    id_str = str(raw_id) if isinstance(raw_id, int) else ""

    return first_name, last_name, full_name, username, id_str


def build_tongo_context(update: object) -> TongoContext:
    """Build a TongoContext from a PTB Update (or any compatible fake object).

    Sender is taken from update.effective_user.
    Reply target from update.message.reply_to_message.from_user (if present).
    Reply vars are populated even when the reply target is a bot.
    """
    user = getattr(update, "effective_user", None)
    if user is not None:
        first_name, last_name, full_name, username, user_id = _extract_user_fields(user)
    else:
        first_name = last_name = full_name = username = user_id = ""

    msg = getattr(update, "message", None)
    reply_msg = getattr(msg, "reply_to_message", None) if msg is not None else None
    reply_user = getattr(reply_msg, "from_user", None) if reply_msg is not None else None

    if reply_user is not None:
        rfn, rln, rfull, rusername, rid = _extract_user_fields(reply_user)
        has_reply = True
    else:
        rfn = rln = rfull = rusername = rid = ""
        has_reply = False

    return TongoContext(
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        username=username,
        id=user_id,
        reply_to_first_name=rfn,
        reply_to_last_name=rln,
        reply_to_full_name=rfull,
        reply_to_username=rusername,
        reply_to_id=rid,
        has_reply=has_reply,
    )


# ── rendering ─────────────────────────────────────────────────────────────────

_VAR_MAP: dict[str, str] = {
    "first_name": "first_name",
    "last_name": "last_name",
    "full_name": "full_name",
    "username": "username",
    "id": "id",
    "reply_to_first_name": "reply_to_first_name",
    "reply_to_last_name": "reply_to_last_name",
    "reply_to_full_name": "reply_to_full_name",
    "reply_to_username": "reply_to_username",
    "reply_to_id": "reply_to_id",
}

_PLACEHOLDER_RE = re.compile(r"{{\s*(\w+)\s*}}")


def render_tongo(phrase: str, ctx: TongoContext) -> str:
    """Substitute {{var}} placeholders in *phrase* with values from *ctx*.

    Whitespace-tolerant: {{ first_name }} works the same as {{first_name}}.
    Unknown placeholders → "".  Missing or empty values → "".
    """
    def _repl(match: re.Match) -> str:
        key = match.group(1)
        field = _VAR_MAP.get(key)
        if field is None:
            return ""
        return getattr(ctx, field, "") or ""

    return _PLACEHOLDER_RE.sub(_repl, phrase)


def phrase_uses_reply(phrase: str) -> bool:
    """Return True if *phrase* references any {{reply_to_*}} variable."""
    return bool(re.search(r"{{\s*reply_to_", phrase))


def phrase_eligible(phrase: str, ctx: TongoContext) -> bool:
    """Return False only when *phrase* uses reply vars but there is no reply."""
    if phrase_uses_reply(phrase) and not ctx.has_reply:
        return False
    return True


# ── per-user config dataclass ─────────────────────────────────────────────────

@dataclass
class TongoUserConfig:
    """Per-user /tongo configuration loaded from TongoUsers.yml."""
    sanchez_ratio: float | None = None
    phrases_mode: str = "append"
    phrases: list[str] = field(default_factory=list)


# ── merged config dataclass ───────────────────────────────────────────────────

@dataclass
class TongoConfig:
    """Merged tongo config loaded from a single YAML file (phrases: + users:)."""
    phrases: list[str] = field(default_factory=list)
    users: dict[str, TongoUserConfig] = field(default_factory=dict)


# ── hot-reload state ──────────────────────────────────────────────────────────

_cached_config_path: str | None = None
_cached_config_mtime: float = 0.0
_cached_config_data: TongoConfig | None = None


def load_tongo_config(path: str) -> TongoConfig:
    """Load the merged tongo config from *path* (YAML) with mtime-based hot-reload.

    The YAML must have:
      - top-level ``phrases:`` list[str]  — global phrase pool
      - top-level ``users:`` mapping      — per-user overrides

    Validation is graceful: invalid fields are logged and skipped; the function
    never raises.  Returns an empty TongoConfig() on missing file, empty file,
    YAML error, or OSError.
    """
    global _cached_config_path, _cached_config_mtime, _cached_config_data

    if not os.path.exists(path):
        log.debug("TongoUsers.yml not found at %s — using built-in defaults", path)
        return TongoConfig()

    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        log.warning("Cannot stat tongo config file %s: %s", path, exc)
        return TongoConfig()

    if (
        path == _cached_config_path
        and mtime == _cached_config_mtime
        and _cached_config_data is not None
    ):
        return _cached_config_data

    log.info("(Re)loading tongo config from %s", path)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        log.warning("YAML parse error in tongo config %s: %s", path, exc)
        return TongoConfig()
    except OSError as exc:
        log.warning("Cannot read tongo config %s: %s", path, exc)
        return TongoConfig()

    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("TongoUsers.yml at %s is not a mapping — ignored", path)
        return TongoConfig()

    # Parse top-level phrases
    raw_phrases = raw.get("phrases")
    if raw_phrases is None:
        phrases: list[str] = []
    elif isinstance(raw_phrases, list) and all(isinstance(p, str) for p in raw_phrases):
        phrases = list(raw_phrases)
    else:
        log.warning("TongoUsers.yml at %s: 'phrases' is not a list of strings — using []", path)
        phrases = []

    # Parse users
    raw_users = raw.get("users")
    users: dict[str, TongoUserConfig] = {}
    if raw_users is None:
        pass  # absent or null → empty dict; no warning
    elif not isinstance(raw_users, dict):
        log.warning("TongoUsers.yml at %s: 'users' is not a mapping — ignored", path)
    else:
        for username, entry in raw_users.items():
            uname = str(username).lower()
            if not isinstance(entry, dict):
                log.warning(
                    "TongoUsers.yml: users.%s is not a mapping — skipped", username
                )
                continue

            cfg = TongoUserConfig()

            if "sanchez_ratio" in entry:
                val = entry["sanchez_ratio"]
                if isinstance(val, (int, float)) and 0.0 <= float(val) <= 1.0:
                    cfg.sanchez_ratio = float(val)
                else:
                    log.warning(
                        "TongoUsers.yml: users.%s.sanchez_ratio=%r is not a number in [0,1] — ignored",
                        uname, val,
                    )

            if "phrases_mode" in entry:
                val = entry["phrases_mode"]
                if val in ("append", "replace"):
                    cfg.phrases_mode = val
                else:
                    log.warning(
                        "TongoUsers.yml: users.%s.phrases_mode=%r invalid (must be 'append' or 'replace') — using 'append'",
                        uname, val,
                    )

            if "phrases" in entry:
                val = entry["phrases"]
                if isinstance(val, list) and all(isinstance(p, str) for p in val):
                    cfg.phrases = list(val)
                else:
                    log.warning(
                        "TongoUsers.yml: users.%s.phrases is not a list of strings — ignored",
                        uname,
                    )

            users[uname] = cfg

    result = TongoConfig(phrases=phrases, users=users)
    _cached_config_path = path
    _cached_config_mtime = mtime
    _cached_config_data = result
    return result


# ── pure selection function ───────────────────────────────────────────────────

def choose_tongo_response(
    ctx: TongoContext,
    effective_phrases: list[str],
    sanchez_ratio: float,
    gender: str,
    gifs: list[Path],
    *,
    rng: object = random,
) -> str | Path:
    """Choose a /tongo response deterministically given an *rng*.

    Args:
        ctx: TongoContext with sender and reply-target data.
        effective_phrases: Merged phrase pool (global + per-user, or per-user only).
        sanchez_ratio: Probability [0,1] for SANCHEZ_ENS_ROBA on the default path.
        gender: "f" or anything else for frase_argentino.
        gifs: List of GIF/video Paths mixed into the pool.
        rng: Object with .random() and .choice() — defaults to the random module.
             Pass a fake rng in tests for deterministic results.

    Returns a rendered str or a Path (GIF/video file).
    """
    eligible = [p for p in effective_phrases if phrase_eligible(p, ctx)]

    # Reply-targeted path: fires when replying AND at least one eligible phrase
    # uses {{reply_to_*}} vars.  SANCHEZ check is skipped on this path.
    if ctx.has_reply and any(phrase_uses_reply(p) for p in eligible):
        pool: list[str | Path] = [
            render_tongo(p, ctx) for p in eligible if phrase_uses_reply(p)
        ] + gifs
        return rng.choice(pool)

    # SANCHEZ gate
    if rng.random() < sanchez_ratio:
        return SANCHEZ_ENS_ROBA

    # Default phrase path
    sender = [render_tongo(p, ctx) for p in eligible if not phrase_uses_reply(p)]
    if not sender:
        sender = [render_tongo(p, ctx) for p in eligible]
    if not sender:
        sender = [render_tongo(p, ctx) for p in FRASES]

    pool = sender + [frase_argentino(gender)] + gifs
    return rng.choice(pool)
