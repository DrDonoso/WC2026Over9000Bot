"""WC2026 data-driven stage/group configuration constants."""

from __future__ import annotations

COMPETITION_CODE = "WC"

GROUPS: list[str] = list("ABCDEFGHIJKL")  # 12 groups
TEAMS_PER_GROUP: int = 4
QUALIFY_PER_GROUP: int = 3  # top 3 per group predicted

# (api_stage_name, display_name_es, points_per_correct_qualifier)
KNOCKOUT_STAGES: list[tuple[str, str, int]] = [
    ("ROUND_OF_32", "Treintaidosavos", 1),
    ("LAST_16", "Octavos de Final", 1),
    ("QUARTER_FINALS", "Cuartos de Final", 2),
    ("SEMI_FINALS", "Semifinales", 3),
    ("FINAL", "Final", 5),
]

# Map api_stage_name → yaml key (snake_case)
STAGE_YAML_KEYS: dict[str, str] = {
    "ROUND_OF_32": "round_of_32",
    "LAST_16": "round_of_16",
    "QUARTER_FINALS": "quarter_finals",
    "SEMI_FINALS": "semi_finals",
    "FINAL": "final",
}

GROUP_SCORING: dict[str, float] = {
    "exact_position": 1.0,
    "qualified_wrong_position": 0.5,
}
