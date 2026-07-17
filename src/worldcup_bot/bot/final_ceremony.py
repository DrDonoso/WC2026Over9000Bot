"""Final ceremony — state helpers and message builder functions.

Three ceremony pieces fire via poll_final_ceremony_job (automatic) and
/granfinal (manual fallback):

  A) PRE-FINAL  — once the Final kicks off: hype + pre-match porra snapshot
                  + ⚔️ champion-picks face-off block.
  B) CAMPEÓN    — once the Final is FINISHED: world champion announcement.
  C) PODIO      — with CAMPEÓN: final official porra ranking + podium image.

All Spanish copy lives in the COPY_* constants below — review and edit them
without touching any other logic.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# COPY BLOCK — edit these strings to change the ceremony messages
# ══════════════════════════════════════════════════════════════════════════════

COPY_PRE_FINAL_HEADER = (
    "🌍⚽ <b>¡Arranca la GRAN FINAL del Mundial 2026!</b>\n\n"
    "Noventa minutos (o más) para decidir quién es el mejor del mundo. "
    "Así llega la porra al partido más importante:"
)

COPY_PRE_FINAL_RANKING_TITLE = "📊 Clasificación antes de la Final:"

COPY_CAMPEON_TEMPLATE = (
    "🏆 {flag} <b>{name}</b> 🏆\n\n"
    "¡<b>CAMPEÓN DEL MUNDO 2026</b>! 🎊"
)

COPY_PODIO_RANKING_TITLE = "🏆 CLASIFICACIÓN FINAL DE LA PORRA 🏆"


# ══════════════════════════════════════════════════════════════════════════════
# State helpers
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_STATE: dict = {"pre_final_sent": False, "campeon_sent": False}


def load_ceremony_state(path: str) -> dict:
    """Load ceremony state from JSON; returns defaults for a missing/corrupt file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {
            "pre_final_sent": bool(data.get("pre_final_sent", False)),
            "campeon_sent": bool(data.get("campeon_sent", False)),
        }
    except FileNotFoundError:
        return dict(_DEFAULT_STATE)
    except Exception as exc:
        log.warning("load_ceremony_state(%s) failed: %s — using defaults", path, exc)
        return dict(_DEFAULT_STATE)


def save_ceremony_state(path: str, state: dict) -> None:
    """Persist ceremony state to JSON. Best-effort — never raises."""
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception as exc:
        log.warning("save_ceremony_state(%s) failed: %s", path, exc)


# ══════════════════════════════════════════════════════════════════════════════
# Message builders (pure functions — no I/O, no Telegram)
# ══════════════════════════════════════════════════════════════════════════════


def build_pre_final_text(ranking_text: str, camps_block: str) -> str:
    """Combine the pre-final header, ranking snapshot and face-off block."""
    parts = [COPY_PRE_FINAL_HEADER, ranking_text]
    if camps_block:
        parts.append(camps_block)
    return "\n\n".join(parts)


def build_campeon_text(winner_tla: str, winner_name: str, flag: str) -> str:
    """Format the world champion announcement message."""
    return COPY_CAMPEON_TEMPLATE.format(flag=flag, name=winner_name)


def build_podium_participants(rows: list) -> list[dict]:
    """Build the top-3 participants list for render_podium from ranking rows.

    Returns up to 3 dicts with 'username', 'display_name', 'position',
    using standard competition (1224-style) positions for ties.
    """
    from worldcup_bot.bot.formatters import standard_competition_positions

    if not rows:
        return []
    top3 = rows[:3]
    positions = standard_competition_positions(top3)
    return [
        {
            "username": r.username,
            "display_name": r.display_name,
            "position": positions[i],
        }
        for i, r in enumerate(top3)
    ]
