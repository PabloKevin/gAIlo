#!/usr/bin/env python3
"""
Telegram Alarm Bot - Main application entry point
"""

import logging
import os
import pytz
from telegram.ext import Application, CommandHandler, JobQueue
from config import Config
from bot.handlers import AlarmHandlers
from bot.alarm import AlarmScheduler

from config import TELEGRAM_BOT_TOKEN


# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    """Main function to start the Telegram bot"""
    try:
        # Get bot token from environment
        token = TELEGRAM_BOT_TOKEN
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN environment variable not set")
            return
        
        # Create application with explicit timezone
        application = Application.builder().token(token).build()
        application.job_queue.scheduler.configure(timezone=pytz.timezone('America/Montevideo'))

        
        # Initialize alarm scheduler
        alarm_scheduler = AlarmScheduler()
        
        # Initialize handlers
        handlers = AlarmHandlers(alarm_scheduler)
        
        # Register command handlers
        application.add_handler(CommandHandler('start', handlers.start_command))
        application.add_handler(CommandHandler('help', handlers.help_command))
        application.add_handler(CommandHandler('alarma', handlers.set_alarm_command))
        application.add_handler(CommandHandler('list', handlers.list_alarms_command))
        application.add_handler(CommandHandler('remove', handlers.remove_alarm_command))
        application.add_handler(CommandHandler('removeall', handlers.remove_all_alarms_command))
        
        # Set the alarm scheduler reference in the application
        application.alarm_scheduler = alarm_scheduler
        
        logger.info("Starting Telegram Alarm Bot...")
        
        # Start the bot
        application.run_polling(
            allowed_updates=['message'],
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")

if __name__ == '__main__':
    main()
