"""Gender inference from a first name using the offline gender_guesser database."""

from __future__ import annotations

import gender_guesser.detector as _gg

_detector = _gg.Detector(case_sensitive=False)


def infer_gender(first_name: str | None) -> str:
    """Return 'f' or 'm' inferred from a first name; defaults to 'm' when unknown."""
    if not first_name:
        return "m"
    # take the first alphabetic token (names may include emojis/extra words)
    token = ""
    for part in first_name.strip().split():
        cleaned = "".join(ch for ch in part if ch.isalpha())
        if cleaned:
            token = cleaned
            break
    if not token:
        return "m"
    g = _detector.get_gender(token)  # 'male','female','mostly_male','mostly_female','andy','unknown'
    if g in ("female", "mostly_female"):
        return "f"
    return "m"  # male/mostly_male/andy/unknown → default male
