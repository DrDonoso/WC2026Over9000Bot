"""Entry point: python -m worldcup_bot

Builds the Telegram Application, registers all handlers, starts polling.
"""

from __future__ import annotations

import logging
import sys

from telegram.ext import Application, CommandHandler

from worldcup_bot.bot.handlers import (
    cmd_actual,
    cmd_ayer,
    cmd_clasificacion,
    cmd_en_directo,
    cmd_general,
    cmd_hoy,
    cmd_lista_aciertos,
    cmd_lista_aciertos_actual,
    cmd_mis_predicciones,
    cmd_participantes,
    cmd_siguiente,
    cmd_start,
    cmd_tongo,
)
from worldcup_bot.config import Settings, load_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def build_app(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    # Store settings in bot_data for handler access
    app.bot_data["settings"] = settings

    handlers = [
        CommandHandler("start", cmd_start),
        CommandHandler("clasificacion", cmd_clasificacion),
        CommandHandler("actual", cmd_actual),
        CommandHandler("porra", cmd_actual),
        CommandHandler("listaaciertos", cmd_lista_aciertos),
        CommandHandler("listaaciertosactual", cmd_lista_aciertos_actual),
        CommandHandler("endirecto", cmd_en_directo),
        CommandHandler("hoy", cmd_hoy),
        CommandHandler("ayer", cmd_ayer),
        CommandHandler("siguiente", cmd_siguiente),
        CommandHandler("general", cmd_general),
        CommandHandler("tongo", cmd_tongo),
        # New approved improvements
        CommandHandler("mispredicciones", cmd_mis_predicciones),
        CommandHandler("participantes", cmd_participantes),
    ]

    for handler in handlers:
        app.add_handler(handler)

    return app


def main() -> None:
    # Inject the OS/container trust store so requests trusts corporate CA certs
    # (handles environments with SSL inspection / self-signed certificate chains).
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass

    try:
        settings = load_settings()
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    log.info(
        "Starting WorldCup2026 bot | competition=%s | predictions=%s",
        settings.competition_code,
        settings.predictions_path,
    )

    app = build_app(settings)
    app.run_polling()


if __name__ == "__main__":
    main()
