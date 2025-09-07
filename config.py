"""
Configuration settings for the Telegram Alarm Bot
"""

import pytz
from datetime import datetime
import os
from dotenv import load_dotenv
from pathlib import Path

# Carga .env buscando desde el cwd hacia arriba
ENV_PATH = Path(__file__).resolve().parent / ".env"

load_dotenv(dotenv_path=ENV_PATH)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

class Config:
    """Configuration class for the alarm bot"""
    
    # Default timezone - can be overridden per user
    DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE")
    
    # Wake-up messages
    WAKE_UP_MESSAGES = [
        "¡Es hora de despertarse! 🌅",
        "¡Buenos días! ¡Hora de levantarse! ☀️",
        "¡Tu alarma está sonando! ⏰",
        "¡Despierta! ¡Es un nuevo día! 🌞",
        "¡Hora de empezar el día! 💪",
        "¡Tu alarma programada está activa! 🔔"
    ]
    
    # Error messages
    ERROR_MESSAGES = {
        'invalid_time': '❌ Formato de hora inválido. Usa el formato HH:MM (ejemplo: 07:30)',
        'invalid_hour': '❌ La hora debe estar entre 00 y 23',
        'invalid_minute': '❌ Los minutos deben estar entre 00 y 59',
        'alarm_exists': '⚠️ Ya tienes una alarma configurada para esta hora',
        'no_alarms': '📭 No tienes alarmas configuradas',
        'alarm_not_found': '❌ No se encontró ninguna alarma para esa hora',
        'general_error': '❌ Ocurrió un error. Por favor, intenta nuevamente.'
    }
    
    # Success messages
    SUCCESS_MESSAGES = {
        'alarm_set': '✅ Alarma configurada para las {time}. Se repetirá diariamente.',
        'alarm_removed': '✅ Alarma de las {time} eliminada correctamente.',
        'all_alarms_removed': '✅ Todas las alarmas han sido eliminadas.'
    }
    
    # Help text
    HELP_TEXT = """
        🤖 *Bot de Alarmas Diarias*

        *Comandos disponibles:*

        /alarma HH:MM - Configura una alarma diaria
        Ejemplo: `/alarma 07:30`

        /despierto - Marca que ya te levantaste y cierra la conversación

        /list - Muestra todas tus alarmas activas

        /remove HH:MM - Elimina una alarma específica
        Ejemplo: `/remove 07:30`

        /removeall - Elimina todas tus alarmas

        /help - Muestra este mensaje de ayuda

        *Formato de hora:* HH:MM (24 horas)
        *Zona horaria:* Montevideo, Uruguay (GMT-3)

        ¡Las alarmas se repetirán todos los días a la hora configurada! ⏰
        """
    
    @staticmethod
    def validate_time_format(time_str):
        """Validate time string format HH:MM"""
        try:
            parts = time_str.split(':')
            if len(parts) != 2:
                return False, 'invalid_time'
            
            hour = int(parts[0])
            minute = int(parts[1])
            
            if hour < 0 or hour > 23:
                return False, 'invalid_hour'
            
            if minute < 0 or minute > 59:
                return False, 'invalid_minute'
            
            return True, None
            
        except ValueError:
            return False, 'invalid_time'
