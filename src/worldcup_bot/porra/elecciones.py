"""Pure data helpers for the /elecciones command.

No I/O, no Telegram, no API calls.  All functions operate on the predictions
dict loaded by pred_loader.load() and on data passed in as arguments.
"""

from __future__ import annotations

# ── Phase metadata ────────────────────────────────────────────────────────────

_PHASE_LABELS: dict[str, str] = {
    "grupos":         "Fase de grupos",
    "round_of_32":    "Dieciseisavos",
    "round_of_16":    "Octavos de Final",
    "quarter_finals": "Cuartos de Final",
    "semi_finals":    "Semifinales",
    "final":          "La Final",
}

_PHASE_ORDER: list[str] = [
    "grupos",
    "round_of_32",
    "round_of_16",
    "quarter_finals",
    "semi_finals",
    "final",
]

_KNOCKOUT_HEADERS: dict[str, str] = {
    "round_of_32":    "🏆 DIECISEISAVOS — ¿Quién pasa?",
    "round_of_16":    "🏆 OCTAVOS DE FINAL — ¿Quién pasa?",
    "quarter_finals": "🏆 CUARTOS DE FINAL — ¿Quién pasa?",
    "semi_finals":    "🏆 SEMIFINALES — ¿Quién pasa?",
    "final":          "🏆 LA FINAL — ¿Quién gana?",
}

# Split threshold — buffer below Telegram's 4096-char hard limit.
_SPLIT_THRESHOLD = 3800
# Hard limit for a single message — used by the defensive line-level split.
_HARD_LIMIT = 4090


# ── Public API ────────────────────────────────────────────────────────────────


def phase_label(yaml_key: str) -> str:
    """Return the Spanish display label for a phase yaml_key."""
    return _PHASE_LABELS.get(yaml_key, yaml_key)


def _grupos_has_picks(participants: dict) -> bool:
    """True if ≥1 participant has ≥1 non-** group pick."""
    return any(
        t != "**"
        for udata in participants.values()
        for picks in udata.get("groups", {}).values()
        for t in picks
    )


def _knockout_has_picks(participants: dict, yaml_key: str) -> bool:
    """True if ≥1 participant has ≥1 non-** pick for this knockout round."""
    return any(
        any(t != "**" for t in udata.get("knockout", {}).get(yaml_key, []))
        for udata in participants.values()
    )


def active_phases(predictions: dict) -> list[str]:
    """Return phase yaml_keys with ≥1 non-** pick from ≥1 participant, in display order."""
    participants = predictions.get("participants", {})
    if not participants:
        return []
    result: list[str] = []
    for phase in _PHASE_ORDER:
        if phase == "grupos":
            if _grupos_has_picks(participants):
                result.append(phase)
        else:
            if _knockout_has_picks(participants, phase):
                result.append(phase)
    return result


def _pick_for_tie(udata: dict, home_tla: str, away_tla: str, yaml_key: str) -> str | None:
    """Return the TLA the participant picked to advance from this tie, or None.

    None means neither home nor away appears in their advance list for this round.
    """
    picks = {str(p).upper() for p in udata.get("knockout", {}).get(yaml_key, [])}
    if home_tla.upper() in picks:
        return home_tla.upper()
    if away_tla.upper() in picks:
        return away_tla.upper()
    return None


def build_group_compositions(standings: list) -> dict[str, list[str]]:
    """Build {letter: [tla, tla, tla, tla]} from API standings.

    Args:
        standings: list of Standing(group="GROUP_A", position=1, tla="MEX", …).

    Returns:
        {"A": ["MEX", "KOR", "CZE", "ZAF"], …} in position order (1–4).
        Groups with fewer than 4 teams in the standings are returned as-is.
    """
    result: dict[str, list[str]] = {}
    for s in sorted(standings, key=lambda x: (x.group or "", x.position)):
        if s.group:
            letter = s.group.replace("GROUP_", "")
            result.setdefault(letter, []).append(s.tla)
    return result


def _split_block_at_lines(block: str, max_len: int) -> list[str]:
    """Split a single user block into ≤max_len pieces at line boundaries.

    Used as a defensive guard when a single user's block exceeds the hard
    Telegram message limit — e.g. when a participant has many picks and each
    picks string is long.  Normal usage (compact flags) will never hit this.
    """
    if len(block) <= max_len:
        return [block]
    parts: list[str] = []
    current_lines: list[str] = []
    current_len = 0
    for line in block.split("\n"):
        add_len = len(line) + (1 if current_lines else 0)  # +1 for joining \n
        if current_lines and current_len + add_len > max_len:
            parts.append("\n".join(current_lines))
            current_lines = [line]
            current_len = len(line)
        else:
            current_lines.append(line)
            current_len += add_len
    if current_lines:
        parts.append("\n".join(current_lines))
    return parts


def build_knockout_text(
    ties: list[tuple[str, str]],
    participants: dict,
    yaml_key: str,
    team_flag_fn,
) -> list[str]:
    """Build per-user vertical knockout text.  Returns 1+ Telegram message strings.

    Args:
        ties: Ordered [(home_tla, away_tla), ...] pairs for this round.
        participants: YAML participants dict (insertion order = display order).
        yaml_key: e.g. "round_of_32".
        team_flag_fn: callable(tla: str) -> str (flag emoji).

    Format::

        🏆 DIECISEISAVOS — ¿Quién pasa?

        👤 DavidR
          🇨🇦·🇿🇦  →  🇨🇦
          🇧🇷·🇯🇵  →  🇧🇷
          🇩🇪·🇵🇾  →  ❓
          ...

        👤 Victor
          ...
    """
    header = _KNOCKOUT_HEADERS.get(yaml_key, f"🏆 {phase_label(yaml_key).upper()}")

    user_blocks: list[str] = []
    for uname, udata in participants.items():
        dname = udata.get("display_name") or f"@{uname}"
        lines = [f"👤 {dname}"]
        for home_tla, away_tla in ties:
            hf = team_flag_fn(home_tla)
            af = team_flag_fn(away_tla)
            picked = _pick_for_tie(udata, home_tla, away_tla, yaml_key)
            pick_str = team_flag_fn(picked) if picked is not None else "❓"
            lines.append(f"  {hf}·{af}  →  {pick_str}")
        user_blocks.append("\n".join(lines))

    return _split_messages(header, user_blocks)


def build_groups_text(
    participants: dict,
    team_flag_fn,
) -> list[str]:
    """Build per-user vertical groups text.  Returns 1+ Telegram message strings.

    Args:
        participants: YAML participants dict (insertion order = display order).
        team_flag_fn: callable(tla: str) -> str (flag emoji).

    Format::

        📋 FASE DE GRUPOS — Predicciones

        👤 DavidR
          A: 🇲🇽 🇰🇷 | 3º🇨🇿
          B: 🇨🇭 🇨🇦 | 3º🇶🇦
          ...

        👤 Victor
          ...
    """
    header = "📋 FASE DE GRUPOS — Predicciones"

    user_blocks: list[str] = []
    for uname, udata in participants.items():
        dname = udata.get("display_name") or f"@{uname}"
        lines = [f"👤 {dname}"]
        for grp in "ABCDEFGHIJKL":
            picks = udata.get("groups", {}).get(grp, [])
            p1 = picks[0] if len(picks) > 0 else "**"
            p2 = picks[1] if len(picks) > 1 else "**"
            p3 = picks[2] if len(picks) > 2 else "**"
            f1 = team_flag_fn(p1) if p1 != "**" else "**"
            f2 = team_flag_fn(p2) if p2 != "**" else "**"
            f3_str = f"3º{team_flag_fn(p3)}" if p3 != "**" else "3º**"
            lines.append(f"  {grp}: {f1} {f2} | {f3_str}")
        user_blocks.append("\n".join(lines))

    return _split_messages(header, user_blocks)


def _split_messages(header: str, user_blocks: list[str]) -> list[str]:
    """Assemble user blocks into 1+ messages, splitting at user boundaries when needed.

    Defensive pre-pass: any block that alone exceeds _HARD_LIMIT (edge case —
    happens only if a single user has many very long pick strings) is split at
    line boundaries so no emitted message exceeds Telegram's 4096-char limit.

    Main pass: greedy fill up to _SPLIT_THRESHOLD, flushing to a new message
    at user-block boundaries.  Part numbers are prepended when >1 message.
    """
    if not user_blocks:
        return [header]

    # Defensive line-level split for oversized individual blocks.
    processed: list[str] = []
    for block in user_blocks:
        processed.extend(_split_block_at_lines(block, _HARD_LIMIT))
    user_blocks = processed

    full = header + "\n\n" + "\n\n".join(user_blocks)
    if len(full) <= _SPLIT_THRESHOLD:
        return [full]

    parts: list[list[str]] = []
    current: list[str] = [header]
    current_len = len(header)
    sep_len = len("\n\n")

    for block in user_blocks:
        if current_len + sep_len + len(block) > _SPLIT_THRESHOLD and len(current) > 1:
            parts.append(current)
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += sep_len + len(block)

    if current:
        parts.append(current)

    messages = ["\n\n".join(p) for p in parts]
    if len(messages) > 1:
        n = len(messages)
        return [f"({i + 1}/{n})\n{m}" for i, m in enumerate(messages)]
    return messages
