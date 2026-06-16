"""Tongo phrases — easter egg for /tongo command.

Probability model:
- "Sanchez ens roba" (SANCHEZ_ENS_ROBA) is returned with exactly 1/3 probability.
- Otherwise a random phrase is chosen from FRASES (2/3 probability).
SANCHEZ_ENS_ROBA must NOT appear in FRASES or the 1/3 guarantee would be violated.
"""

from __future__ import annotations

SANCHEZ_ENS_ROBA = "Sanchez ens roba"

FRASES: list[str] = [
    "¡Qué sorpresa! Justo el resultado que nadie esperaba… (nótese el sarcasmo).",
    "Sí, porque los favoritos nunca reciben una ayuda extra, ¿verdad?",
    "Nada como una competencia donde el resultado está escrito antes de empezar.",
    "¡Wow! Una victoria completamente inesperada… justo como todos anticipamos.",
    "Es impresionante cómo siempre parece ganar el equipo más 'afortunado'.",
    "Qué reconfortante es saber que todo es completamente 'justo' y equilibrado.",
    "Me sorprende que aún llamen a esto competencia, cuando es claramente un arreglo.",
    "Es fantástico ver cómo algunos siempre tienen 'suerte' en momentos cruciales.",
    "Sí, porque los resultados nunca están manipulados de antemano, ¿verdad?",
    "Nada mejor que ver una 'victoria merecida' que fue claramente un tongo.",
    "Me encanta cómo el 'azar' siempre favorece a los que no deberían ganar.",
    "Qué increíble ver cómo la 'justicia' se distribuye tan desigualmente.",
    "¡Vaya! Todo salió justo como se planeó… desde el principio del tongo.",
    "Nada como una 'sorpresa' que todo el mundo veía venir desde kilómetros de distancia.",
    "Sí, seguro que no hubo ningún arreglo detrás de este 'resultado justo'.",
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
]
