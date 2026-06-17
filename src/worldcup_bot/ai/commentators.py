"""Spanish-football commentators pool for porra-change commentary."""

from __future__ import annotations

import random

from worldcup_bot.ai.client import AIClient

COMMENTATORS: list[str] = [
    "Manolo Lama",
    "Julio Maldini",
    "Andrés Montes",
]

_STYLE_HINTS: dict[str, str] = {
    "Manolo Lama": (
        "enérgico, exclamativo, radiofónico, usa '¡jugón!', muy pasional al estilo COPE. "
        "Frases cortas y explosivas, exclamaciones frecuentes, vive cada cambio en el marcador."
    ),
    "Julio Maldini": (
        "analítico, didáctico, sobrio pero apasionado, con datos y contexto al estilo Movistar+. "
        "Frases reflexivas, elegancia narrativa, aporta perspectiva táctica y cifras."
    ),
    "Andrés Montes": (
        "ocurrente y lírico, usa apodos creativos, frases como 'la vida puede ser maravillosa', "
        "desenfadado con humor e ingenio. Mezcla poesía y fútbol con originalidad inimitable."
    ),
}


def pick_commentator(rng: random.Random | None = None) -> str:
    """Pick a random commentator name from the pool."""
    pool = COMMENTATORS
    if rng is not None:
        return rng.choice(pool)
    return random.choice(pool)


def build_commentary_messages(persona: str, changes_text: str) -> tuple[str, str]:
    """Return (system, user) messages for the porra-commentary prompt.

    The system message instructs the model to write AS the given commentator,
    in his recognizable Spanish style, a MAX-4-lines commentary about the
    porra ranking described in changes_text.  The context always includes
    the current standings and may or may not include ranking movements.
    """
    style = _STYLE_HINTS.get(persona, "apasionado y expresivo, estilo fútbol español")
    system = (
        f"Eres {persona}, el famoso comentarista de fútbol español. "
        f"Tu estilo: {style}. "
        "Escribe UN comentario breve — MÁXIMO 4 líneas cortas — sobre la porra "
        "(quiniela de predicciones del Mundial) a partir del contexto que te voy a dar. "
        "El contexto incluye la clasificación actual y si hubo cambios con el último resultado. "
        "Si no hubo cambios (lo indicará el texto 'Ninguno'), dilo brevemente y recuerda quién lidera — "
        "nunca inventes movimientos que no aparezcan en el texto. "
        "El comentario debe sonar inconfundiblemente como tú: en español, con emojis moderados. "
        "Sé conciso y entretenido. "
        "No firmes ni menciones tu propio nombre."
    )
    user = changes_text
    return system, user


async def generate_porra_commentary(
    ai: AIClient,
    persona: str,
    changes_text: str,
) -> str:
    """Generate a short porra-change commentary in the voice of the given persona."""
    system, user = build_commentary_messages(persona, changes_text)
    return await ai.complete(system, user, max_completion_tokens=400)
