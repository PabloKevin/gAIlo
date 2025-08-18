"""
Command handlers for the Telegram Alarm Bot
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import Config
from bot.alarm import AlarmScheduler

logger = logging.getLogger(__name__)

class AlarmHandlers:
    """Contains all command handlers for the alarm bot"""
    
    def __init__(self, alarm_scheduler: AlarmScheduler):
        self.alarm_scheduler = alarm_scheduler
        self.config = Config()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        try:
            welcome_message = """
                🤖 ¡Bienvenido al Bot de Alarmas Diarias!

                Este bot te permite configurar alarmas que se repetirán todos los días a la hora que elijas.

                Para comenzar, usa el comando:
                `/alarma HH:MM`

                Por ejemplo: `/alarma 07:30`

                Usa /help para ver todos los comandos disponibles.
                """
            
            await update.message.reply_text(
                welcome_message,
                parse_mode='Markdown'
            )
            
            logger.info(f"Start command executed by user {update.effective_user.id}")
            
        except Exception as e:
            logger.error(f"Error in start command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        try:
            await update.message.reply_text(
                self.config.HELP_TEXT,
                parse_mode='Markdown'
            )
            
            logger.info(f"Help command executed by user {update.effective_user.id}")
            
        except Exception as e:
            logger.error(f"Error in help command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
    
    async def set_alarm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alarma command to set a new alarm"""
        try:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id
            
            # Check if time argument was provided
            if not context.args:
                await update.message.reply_text(
                    "❌ Por favor especifica la hora.\n\nUso: `/alarma HH:MM`\nEjemplo: `/alarma 07:30`",
                    parse_mode='Markdown'
                )
                return
            
            time_str = context.args[0]
            
            # Add alarm
            success, message = self.alarm_scheduler.add_alarm(
                application=context.application,
                user_id=user_id,
                time_str=time_str,
                chat_id=chat_id
            )
            
            await update.message.reply_text(message)
            
            if success:
                logger.info(f"Alarm set by user {user_id} for {time_str}")
            else:
                logger.warning(f"Failed to set alarm for user {user_id}: {message}")
            
        except Exception as e:
            logger.error(f"Error in set_alarm command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
    
    async def list_alarms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command to show user's alarms"""
        try:
            user_id = update.effective_user.id
            alarms = self.alarm_scheduler.get_user_alarms(user_id)
            
            if not alarms:
                await update.message.reply_text(self.config.ERROR_MESSAGES['no_alarms'])
                return
            
            message = "⏰ *Tus alarmas activas:*\n\n"
            for i, alarm_time in enumerate(alarms, 1):
                message += f"{i}. `{alarm_time}` (diaria)\n"
            
            message += f"\n📊 Total: {len(alarms)} alarma(s)"
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown'
            )
            
            logger.info(f"List command executed by user {user_id} - {len(alarms)} alarms")
            
        except Exception as e:
            logger.error(f"Error in list_alarms command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
    
    async def remove_alarm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /remove command to remove a specific alarm"""
        try:
            user_id = update.effective_user.id
            
            # Check if time argument was provided
            if not context.args:
                await update.message.reply_text(
                    "❌ Por favor especifica la hora de la alarma a eliminar.\n\nUso: `/remove HH:MM`\nEjemplo: `/remove 07:30`",
                    parse_mode='Markdown'
                )
                return
            
            time_str = context.args[0]
            
            # Remove alarm
            success, message = self.alarm_scheduler.remove_alarm(user_id, time_str)
            
            await update.message.reply_text(message)
            
            if success:
                logger.info(f"Alarm removed by user {user_id} for {time_str}")
            else:
                logger.warning(f"Failed to remove alarm for user {user_id}: {message}")
            
        except Exception as e:
            logger.error(f"Error in remove_alarm command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
    
    async def remove_all_alarms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /removeall command to remove all user's alarms"""
        try:
            user_id = update.effective_user.id
            
            # Remove all alarms
            success, message = self.alarm_scheduler.remove_all_alarms(user_id)
            
            await update.message.reply_text(message)
            
            if success:
                logger.info(f"All alarms removed by user {user_id}")
            else:
                logger.warning(f"Failed to remove all alarms for user {user_id}: {message}")
            
        except Exception as e:
            logger.error(f"Error in remove_all_alarms command: {e}")
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])
