#!/usr/bin/env python3
"""
Telegram Alarm Bot - Main application entry point
"""

import logging
import pytz
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from config import Config, TELEGRAM_BOT_TOKEN
from bot.handlers import AlarmHandlers
from bot.alarm import AlarmScheduler
from llm.model import LLM_Client

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Called once after the app is fully built — restore persisted alarms."""
    application.alarm_scheduler.restore_alarms(application)


def main():
    try:
        token = TELEGRAM_BOT_TOKEN
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
            return

        application = (
            Application.builder()
            .token(token)
            .post_init(post_init)   # <-- restore alarms after build
            .build()
        )
        application.job_queue.scheduler.configure(
            timezone=pytz.timezone('America/Montevideo')
        )

        LLM = LLM_Client()
        alarm_scheduler = AlarmScheduler(llm=LLM)
        application.alarm_scheduler = alarm_scheduler

        handlers = AlarmHandlers(alarm_scheduler)

        application.add_handler(CommandHandler('start',     handlers.start_command))
        application.add_handler(CommandHandler('help',      handlers.help_command))
        application.add_handler(CommandHandler(['alarm', 'alarma'], handlers.set_alarm_command))
        application.add_handler(CommandHandler('list',      handlers.list_alarms_command))
        application.add_handler(CommandHandler('remove',    handlers.remove_alarm_command))
        application.add_handler(CommandHandler('removeall', handlers.remove_all_alarms_command))
        application.add_handler(CommandHandler('despierto', handlers.wake_ack_command))
        application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, handlers.conversation_message
        ))

        logger.info("Starting Telegram Alarm Bot...")
        application.run_polling(
            allowed_updates=['message'],
            drop_pending_updates=True
        )

    except Exception as e:
        logger.error("Error starting bot: %s", e)


if __name__ == '__main__':
    main()