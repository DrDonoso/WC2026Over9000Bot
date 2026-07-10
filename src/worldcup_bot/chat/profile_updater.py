"""Profile updater — group-conversation based AI summarization.

Refinement 3: ONE single AI call per batch run, feeding the ENTIRE attributed
conversation timeline so the model reads users IN CONTEXT (captures threads,
banter dynamics, running jokes between users).  Much cheaper than per-user
calls AND gives better conversational understanding.

Refinement 1: Only the messages NEWER than last_run are fed; the existing
profiles are included as context so knowledge accumulates over time.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable

from worldcup_bot.ai.client import AIClient, AIError
from worldcup_bot.chat.profiles import UserProfile

log = logging.getLogger(__name__)

MOTES_CAP = 8
TEMAS_CAP = 10

_SYSTEM_PROFILE_UPDATE = """\
Eres un asistente de análisis de conversaciones de grupo.
Se te proporciona:
1. Un fragmento de conversación reciente de un grupo de Telegram (mensajes atribuidos a sus autores, en orden cronológico).
2. Los perfiles actuales de cada usuario (en formato JSON compacto), como contexto base.

Tu tarea: analizar la conversación y actualizar los perfiles de los usuarios que participaron.

Devuelve EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura:
{"username1": {campos...}, "username2": {campos...}, ...}

Incluye SOLO a los usuarios que aparecen en la conversación proporcionada.
Para cada usuario, extrae/actualiza estos 5 campos (no incluyas "piques_recientes" — ese campo se gestiona por separado):
- "rasgos": descripción libre de personalidad/carácter (string o null)
- "equipo": equipo/selección favorita (string o null)
- "motes": lista de apodos y chistes recurrentes (list[string])
- "temas": lista de aficiones y temas recurrentes (list[string])
- "tono": instrucción de tono a usar al comentar a esta persona (string o null)

Reglas:
- Si ya hay un perfil base para el usuario, COMBÍNALO con lo observado (no sobreescribas información válida con null).
- Para campos sin evidencia suficiente → conserva el valor existente o usa null/lista vacía (no inventes).
- "motes" y "temas" son listas acumulativas: añade nuevos elementos sin eliminar los existentes.
- Devuelve SOLO el JSON, sin texto adicional ni markdown.
"""


async def update_profiles_from_conversation(
    timeline_messages: list[dict],
    current_profiles: dict[str, UserProfile],
    ai: AIClient,
    *,
    piques_cap: int = 5,
    _now: Callable[[], datetime] | None = None,
) -> dict[str, UserProfile]:
    """Update all active users' profiles in a single AI call.

    Args:
        timeline_messages: list of {"ts", "username", "text"} dicts, chrono order.
        current_profiles:  existing profiles dict (read-only here).
        ai:                AIClient configured with the cheap profile model.
        piques_cap:        not used here (piques are added by maybe_reply); kept for signature clarity.
        _now:              injectable clock for tests.

    Returns:
        Updated profiles dict.  On empty timeline or any error, returns current_profiles unchanged.
    """
    if not timeline_messages:
        return current_profiles

    now = (_now or (lambda: datetime.now(timezone.utc)))()

    # Build conversation block — "[username] text" lines in chrono order
    convo_lines = [f"[{m['username']}] {m['text']}" for m in timeline_messages]
    convo_block = "\n".join(convo_lines)

    # Find participating usernames
    participants = list({m["username"] for m in timeline_messages if m.get("username")})

    # Build compact current-profiles context for participants only
    profiles_context: dict[str, dict] = {}
    for uname in participants:
        p = current_profiles.get(uname)
        if p:
            profiles_context[uname] = {
                "rasgos": p.rasgos,
                "equipo": p.equipo,
                "motes": p.motes,
                "temas": p.temas,
                "tono": p.tono,
            }

    profiles_json = json.dumps(profiles_context, ensure_ascii=False)

    user_prompt = (
        f"CONVERSACIÓN RECIENTE ({len(timeline_messages)} mensajes):\n"
        f"{convo_block}\n\n"
        f"PERFILES ACTUALES (contexto base):\n"
        f"{profiles_json}\n\n"
        "Actualiza los perfiles de los participantes en la conversación. "
        "Devuelve SOLO el JSON con {username: {rasgos, equipo, motes, temas, tono}}."
    )

    max_tokens = max(200, 200 * len(participants))

    try:
        raw = await ai.complete(
            _SYSTEM_PROFILE_UPDATE,
            user_prompt,
            temperature=0.3,
            max_completion_tokens=max_tokens,
        )
    except AIError as exc:
        log.warning("profile_updater: AI error — %s — keeping current profiles", exc)
        return current_profiles

    # Parse the JSON response
    try:
        # Strip optional markdown code fences
        stripped = raw.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        parsed: dict = json.loads(stripped)
        if not isinstance(parsed, dict):
            raise ValueError("Expected JSON object")
    except Exception as exc:
        log.warning("profile_updater: JSON parse error — %s — keeping current profiles", exc)
        return current_profiles

    # Merge AI results into current profiles, respecting pinned_fields
    updated = dict(current_profiles)
    for uname, fields in parsed.items():
        if not isinstance(fields, dict):
            continue
        existing = updated.get(uname) or UserProfile(username=uname)
        pinned = set(existing.pinned_fields)

        def _maybe(field_name: str, new_val):
            """Return new_val unless field is pinned."""
            return getattr(existing, field_name) if field_name in pinned else new_val

        rasgos = _maybe("rasgos", fields.get("rasgos") or existing.rasgos)
        equipo = _maybe("equipo", fields.get("equipo") or existing.equipo)
        tono = _maybe("tono", fields.get("tono") or existing.tono)

        # Lists are accumulative: order-preserving union, capped to keep most recent
        if "motes" in pinned:
            motes = existing.motes
        else:
            new_motes = fields.get("motes") or []
            motes = list(dict.fromkeys([*existing.motes, *new_motes]))[-MOTES_CAP:]

        if "temas" in pinned:
            temas = existing.temas
        else:
            new_temas = fields.get("temas") or []
            temas = list(dict.fromkeys([*existing.temas, *new_temas]))[-TEMAS_CAP:]

        updated[uname] = UserProfile(
            username=uname,
            rasgos=rasgos,
            equipo=equipo,
            motes=motes,
            temas=temas,
            tono=tono,
            piques_recientes=existing.piques_recientes,
            pinned_fields=existing.pinned_fields,
            updated_at=now.isoformat(),
        )

    return updated
