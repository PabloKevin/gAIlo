"""
Alarm scheduling functionality for the Telegram bot
"""

import logging
import random
from datetime import datetime, time
from telegram.ext import Application
from config import Config
import pytz

logger = logging.getLogger(__name__)

class AlarmScheduler:
    """Handles alarm scheduling and management"""
    
    def __init__(self):
        self.user_alarms = {}  # user_id -> {time_str: job}
        self.config = Config()
        self.timezone = pytz.timezone(self.config.DEFAULT_TIMEZONE)  # Add this line
    
    def add_alarm(self, application: Application, user_id: int, time_str: str, chat_id: int):
        """
        Add a daily recurring alarm for a user
        
        Args:
            application: Telegram application instance
            user_id: Telegram user ID
            time_str: Time string in HH:MM format
            chat_id: Chat ID where to send the alarm
            
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Validate time format
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]
            
            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']
            
            hour, minute = map(int, time_str.split(':'))
            alarm_time = time(hour=hour, minute=minute)
            
            job_context = {
                'user_id': user_id,
                'chat_id': chat_id,
                'time_str': time_str
            }
            
            # Ensure timezone is a pytz object
            timezone = pytz.timezone(self.config.DEFAULT_TIMEZONE)
            
            # Schedule the job with the correct timezone
            job = application.job_queue.run_daily(
                callback=self._send_alarm_message,
                time=alarm_time,
                days=(0, 1, 2, 3, 4, 5, 6),
                context=job_context,
                name=f"alarm_{user_id}_{time_str}"
            )

            
            # Initialize user's alarms dict if not exists
            if user_id not in self.user_alarms:
                self.user_alarms[user_id] = {}
                
            self.user_alarms[user_id][time_str] = job
            return True, self.config.SUCCESS_MESSAGES['alarm_set'].format(time=time_str)
            
        except Exception as e:
            logger.error(f"Error adding alarm: {e}")
            return False, self.config.ERROR_MESSAGES['general_error']
    
    def remove_alarm(self, user_id: int, time_str: str):
        """
        Remove a specific alarm for a user
        
        Args:
            user_id: Telegram user ID
            time_str: Time string in HH:MM format
            
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if user_id not in self.user_alarms or time_str not in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_not_found']
            
            # Remove the job
            job = self.user_alarms[user_id][time_str]
            job.schedule_removal()
            
            # Remove from our tracking
            del self.user_alarms[user_id][time_str]
            
            # Clean up empty user entry
            if not self.user_alarms[user_id]:
                del self.user_alarms[user_id]
            
            logger.info(f"Alarm removed for user {user_id} at {time_str}")
            return True, self.config.SUCCESS_MESSAGES['alarm_removed'].format(time=time_str)
            
        except Exception as e:
            logger.error(f"Error removing alarm for user {user_id}: {e}")
            return False, self.config.ERROR_MESSAGES['general_error']
    
    def remove_all_alarms(self, user_id: int):
        """
        Remove all alarms for a user
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if user_id not in self.user_alarms or not self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['no_alarms']
            
            # Remove all jobs for this user
            for job in self.user_alarms[user_id].values():
                job.schedule_removal()
            
            # Clear user alarms
            del self.user_alarms[user_id]
            
            logger.info(f"All alarms removed for user {user_id}")
            return True, self.config.SUCCESS_MESSAGES['all_alarms_removed']
            
        except Exception as e:
            logger.error(f"Error removing all alarms for user {user_id}: {e}")
            return False, self.config.ERROR_MESSAGES['general_error']
    
    def get_user_alarms(self, user_id: int):
        """
        Get list of alarms for a user
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            list: List of time strings for user's alarms
        """
        if user_id not in self.user_alarms:
            return []
        
        return sorted(self.user_alarms[user_id].keys())
    
    async def _send_alarm_message(self, context):
        """
        Callback function to send alarm message
        
        Args:
            context: Job context containing user and chat information
        """
        try:
            job_context = context.job.context
            chat_id = job_context['chat_id']
            time_str = job_context['time_str']
            
            # Select random wake-up message
            message = random.choice(self.config.WAKE_UP_MESSAGES)
            
            # Add time information to message
            full_message = f"{message}\n\n⏰ Alarma programada: {time_str}"
            
            # Send message
            await context.bot.send_message(
                chat_id=chat_id,
                text=full_message,
                parse_mode='HTML'
            )
            
            logger.info(f"Alarm message sent to chat {chat_id} for time {time_str}")
            
        except Exception as e:
            logger.error(f"Error sending alarm message: {e}")
