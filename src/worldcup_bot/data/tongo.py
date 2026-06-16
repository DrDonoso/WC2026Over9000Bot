"""Tongo phrases — easter egg for /tongo command.

Probability model:
- "Sanchez ens roba" (SANCHEZ_ENS_ROBA) is returned with exactly 1/3 probability.
- Otherwise a random phrase is chosen from FRASES (2/3 probability).
SANCHEZ_ENS_ROBA must NOT appear in FRASES or the 1/3 guarantee would be violated.
"""

from __future__ import annotations

SANCHEZ_ENS_ROBA = "Sanchez ens roba"

FRASES: list[str] = [
    # New phrases
    "Per robos el de Javi a Raona",
    "Que si quiere la bolsa",
    "La culpa es de Suñé",
    "Ara envio a la buuuhhhambulancia",
    "si, si, però vas palmant",
    "Si, y Amalia y Suñé son mejores amigos ahora también",
    "Y Rosamar para cuando?",
    "Y Santvi para cuando?",
    "Y Sant Celoni para cuando?",
    "Aguacate?",
    "Si, y Arbeloa es el jugador favorito de Laura. CAP17ÁN.",
    "Tongo es que Joan García no fue convocado con el Espanyol y vaya con el Barça, asi que a callar.",
    "Como va a ser tongo, si no te interesa ni el futbol.",
    "Un conoooooo!! un cono!!!",
    "Por lo menos no somos italia.",
    "Ah, pero ChatGPT decia que si.",
]


def frase_argentino(gender: str) -> str:
    """Return the gender-aware argentino phrase ('f' for female, anything else for male)."""
    if gender == "f":
        return "Que tongo ni que tongo, eres mas pesada que una argentina."
    return "Que tongo ni que tongo, eres mas pesado que un argentino."
