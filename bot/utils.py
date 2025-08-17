"""
Utility functions for the Telegram Alarm Bot
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

class TimeUtils:
    """Utility class for time-related operations"""
    
    @staticmethod
    def get_current_utc_time():
        """Get current UTC time"""
        return datetime.now(timezone.utc)
    
    @staticmethod
    def format_time_for_display(time_str: str) -> str:
        """
        Format time string for better display
        
        Args:
            time_str: Time in HH:MM format
            
        Returns:
            Formatted time string
        """
        try:
            hour, minute = map(int, time_str.split(':'))
            return f"{hour:02d}:{minute:02d}"
        except:
            return time_str
    
    @staticmethod
    def is_valid_time_string(time_str: str) -> bool:
        """
        Check if time string is valid
        
        Args:
            time_str: Time string to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            parts = time_str.split(':')
            if len(parts) != 2:
                return False
            
            hour = int(parts[0])
            minute = int(parts[1])
            
            return 0 <= hour <= 23 and 0 <= minute <= 59
        except:
            return False

class MessageUtils:
    """Utility class for message formatting"""
    
    @staticmethod
    def escape_markdown(text: str) -> str:
        """
        Escape markdown special characters
        
        Args:
            text: Text to escape
            
        Returns:
            Escaped text
        """
        escape_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')
        return text
    
    @staticmethod
    def format_alarm_list(alarms: list) -> str:
        """
        Format list of alarms for display
        
        Args:
            alarms: List of alarm time strings
            
        Returns:
            Formatted string
        """
        if not alarms:
            return "No tienes alarmas configuradas."
        
        formatted = "⏰ *Tus alarmas activas:*\n\n"
        for i, alarm_time in enumerate(alarms, 1):
            formatted += f"{i}. `{alarm_time}` (diaria)\n"
        
        formatted += f"\n📊 Total: {len(alarms)} alarma(s)"
        return formatted

class LogUtils:
    """Utility class for logging operations"""
    
    @staticmethod
    def log_user_action(user_id: int, action: str, details: Optional[str] = None):
        """
        Log user actions with consistent format
        
        Args:
            user_id: Telegram user ID
            action: Action performed
            details: Optional additional details
        """
        message = f"User {user_id} - {action}"
        if details:
            message += f" - {details}"
        
        logger.info(message)
    
    @staticmethod
    def log_error(context: str, error: Exception, user_id: Optional[int] = None):
        """
        Log errors with consistent format
        
        Args:
            context: Context where error occurred
            error: Exception object
            user_id: Optional user ID if relevant
        """
        message = f"Error in {context}: {str(error)}"
        if user_id:
            message = f"User {user_id} - {message}"
        
        logger.error(message)

class ValidationUtils:
    """Utility class for input validation"""
    
    @staticmethod
    def validate_user_input(input_text: str, max_length: int = 100) -> tuple[bool, str]:
        """
        Validate general user input
        
        Args:
            input_text: Text to validate
            max_length: Maximum allowed length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not input_text:
            return False, "Input cannot be empty"
        
        if len(input_text) > max_length:
            return False, f"Input too long (max {max_length} characters)"
        
        return True, ""
    
    @staticmethod
    def sanitize_input(input_text: str) -> str:
        """
        Sanitize user input by removing potentially harmful characters
        
        Args:
            input_text: Text to sanitize
            
        Returns:
            Sanitized text
        """
        # Remove null bytes and control characters
        sanitized = ''.join(char for char in input_text if ord(char) >= 32 or char in '\n\r\t')
        
        # Limit length to prevent abuse
        return sanitized[:1000]
