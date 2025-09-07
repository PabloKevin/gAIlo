"""
Alarm scheduling & conversational flow for the Telegram bot
"""

import logging
import random
from datetime import time
from telegram.ext import Application
from config import Config
import pytz
import os

logger = logging.getLogger(__name__)


class AlarmScheduler:
    """Handles alarm scheduling, management, and wake-up conversations"""

    def __init__(self, llm=None):
        # Alarm jobs programados: user_id -> { "HH:MM": job }
        self.user_alarms: dict[int, dict[str, object]] = {}
        # Sesiones de conversación activas: user_id -> {"chat_id": int, "time_str": str, "history": list[tuple[role,text]]}
        self.active_conversations: dict[int, dict] = {}

        self.config = Config()
        # Zona horaria por defecto (configurable por usuario si querés extender)
        self.timezone = pytz.timezone(self.config.DEFAULT_TIMEZONE)
        # Cliente LLM (puede ser None y se usa fallback)
        self.llm = llm

        logger.info(
            "LLM enabled=%s provider=ollama host=%s model=%s",
            self.llm is not None, os.getenv("LLM_HOST"), os.getenv("OLLAMA_MODEL")
        )

    # =========================
    # Gestión de alarmas
    # =========================
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
            # Validar formato de hora
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]

            # Evitar duplicados
            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']

            hour, minute = map(int, time_str.split(':'))
            alarm_time = time(hour=hour, minute=minute)

            job_context = {
                'user_id': user_id,
                'chat_id': chat_id,
                'time_str': time_str
            }

            # Programar job diario; el scheduler ya está configurado con timezone en main.py
            job = application.job_queue.run_daily(
                callback=self._send_alarm_message,
                time=alarm_time,
                days=(0, 1, 2, 3, 4, 5, 6),
                data=job_context,
                name=f"alarm_{user_id}_{time_str}"
            )

            # Guardar el job
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

            # Cancelar el job
            job = self.user_alarms[user_id][time_str]
            job.schedule_removal()

            # Remover del tracking
            del self.user_alarms[user_id][time_str]

            # Limpiar si no quedan alarmas
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

            # Cancelar todos los jobs del usuario
            for job in self.user_alarms[user_id].values():
                job.schedule_removal()

            # Limpiar
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
            list[str]: Sorted time strings for user's alarms
        """
        if user_id not in self.user_alarms:
            return []
        return sorted(self.user_alarms[user_id].keys())

    # =========================
    # Conversación de despertar
    # =========================
    def has_active_conversation(self, user_id: int) -> bool:
        """Check if there's an active wake-up conversation for this user."""
        return user_id in self.active_conversations

    def stop_conversation(self, user_id: int) -> bool:
        """Stop and remove active conversation for this user."""
        return self.active_conversations.pop(user_id, None) is not None

    def _format_history(self, history: list[tuple[str, str]]) -> str:
        """Render the short history as plain text for the LLM."""
        lines = []
        for role, text in history[-6:]:  # limitar contexto
            if role == "user":
                lines.append(f"Usuario: {text}")
            else:
                lines.append(f"Asistente: {text}")
        return "\n".join(lines)

    async def reply_in_conversation(self, user_id: int, user_text: str, bot):
        """
        Continue a wake-up conversation using the LLM (or fallback prompts).
        Se llama desde un MessageHandler de texto cuando hay sesión activa.
        """
        session = self.active_conversations.get(user_id)
        if not session:
            return

        session["history"].append(("user", user_text))

        # Prompt breve para “despertar”: 1–2 líneas + 1 pregunta.
        prompt = (
            "Continúa la conversación para ayudar a despertar. "
            "No repitas saludos (no digas cosas como 'buen día' ni 'hola' de nuevo)."
            #"Responde en 1-2 líneas, amable, directa, con UNA pregunta breve. "
            "No uses markdown.\n\n"
            "Usa el Historial de la conversación para contexto y continuidad de las respuestas.\n\n"
            "Historial (más reciente al final):\n"
            f"{self._format_history(session['history'])}\n\n"
            "Asistente:"
        )

        if self.llm is not None:
            try:
                answer = await self.llm.generate(prompt)
                if not answer:
                    raise RuntimeError("Empty LLM response")
            except Exception as e:
                logger.exception("LLM falló en reply_in_conversation: %s", e)
                answer = "¡Sigamos! ¿Qué vas a hacer en los próximos 5 minutos?"
        else:
            followups = [
                "¡Bien! ¿Qué vas a hacer primero ahora mismo?",
                "Genial. ¿Te levantás y tomás un vaso de agua?",
                "¡Vamos! ¿Cuál es tu mini-objetivo de esta mañana?"
            ]
            answer = random.choice(followups)

        session["history"].append(("assistant", answer))
        await bot.send_message(chat_id=session["chat_id"], text=answer, parse_mode="HTML")

    # =========================
    # Callback del job (alarma)
    # =========================
    async def _send_alarm_message(self, context):
        """
        Callback para enviar el primer mensaje cuando suena la alarma.
        Abre una sesión de conversación que continuará hasta que el usuario envíe /despierto.
        """
        try:
            job_context = getattr(context.job, "data", None)
            if not job_context:
                logger.error("Job sin data; no puedo enviar alarma.")
                return

            chat_id = job_context['chat_id']
            user_id = job_context['user_id']
            time_str = job_context['time_str']

            # Mensaje inicial (LLM o fallback)
            message = None
            if self.llm is not None:
                prompt = (
                    "Este es el primer mensaje para ayudar a despertar. Saluda brevemente.\n"
                    "Inicia una conversación interesante con una pregunta que rompa el hielo.\n"
                    f"Hora programada: {time_str}. No uses formato markdown.\n\n"
                    "Ejemplos de estilo:\n"
                    "- ¡Arriba! ¿Qué vas a hacer primero en los próximos 5 minutos?\n"
                    "- ¡Buen día! Toma agua y dime: ¿cuál es tu mini-objetivo de la mañana?\n"
                )
                try:
                    message = await self.llm.generate(prompt)
                except Exception as e:
                    logger.exception("LLM falló, uso fallback fijo: %s", e)

            if not message:
                message = random.choice(self.config.WAKE_UP_MESSAGES)

            # Enviar apertura
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')

            # Abrir sesión de conversación
            self.active_conversations[user_id] = {
                "chat_id": chat_id,
                "time_str": time_str,
                "history": [("assistant", message)],
            }

            # Instrucciones breves
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⏰ {time_str} · Responde este mensaje para continuar. "
                    f"Cuando ya estés despiert@, enviá /despierto."
                ),
            )

            logger.info(f"Alarm message sent to chat {chat_id} for time {time_str} and conversation opened.")

        except Exception as e:
            # Si el LLM o el envío falla, logueamos claramente
            logger.error(f"Error sending alarm message or opening conversation: {e}")
