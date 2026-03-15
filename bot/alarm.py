"""
Alarm scheduling & conversational flow for the Telegram bot.
Alarms are persisted in SQLite so they survive restarts.
"""

import logging
import random
import sqlite3
from datetime import time
from pathlib import Path
from telegram.ext import Application
from config import Config
import pytz
import os

logger = logging.getLogger(__name__)

# DB file lives next to this module; on Railway mount a volume at this path
DB_PATH = Path(os.getenv("DB_PATH", "alarms.db"))


def _get_conn() -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure the table exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alarms (
            user_id  INTEGER NOT NULL,
            chat_id  INTEGER NOT NULL,
            time_str TEXT    NOT NULL,
            PRIMARY KEY (user_id, time_str)
        )
    """)
    conn.commit()
    return conn


class AlarmScheduler:
    """Handles alarm scheduling, persistence, and wake-up conversations."""

    def __init__(self, llm=None):
        # In-memory job references: user_id -> { "HH:MM": job }
        self.user_alarms: dict[int, dict[str, object]] = {}
        # Active wake-up conversations: user_id -> { chat_id, time_str, history }
        self.active_conversations: dict[int, dict] = {}

        self.config = Config()
        self.timezone = pytz.timezone(self.config.DEFAULT_TIMEZONE)
        self.llm = llm

        logger.info(
            "LLM enabled=%s  DB=%s",
            self.llm is not None, DB_PATH
        )

    # =========================
    # Startup restore
    # =========================
    def restore_alarms(self, application: Application):
        """
        Re-schedule all alarms stored in SQLite.
        Call this once after the Application is built, before run_polling.
        """
        with _get_conn() as conn:
            rows = conn.execute("SELECT user_id, chat_id, time_str FROM alarms").fetchall()

        restored = 0
        for user_id, chat_id, time_str in rows:
            try:
                self._schedule_job(application, user_id, chat_id, time_str)
                restored += 1
            except Exception as e:
                logger.error("Could not restore alarm %s for user %s: %s", time_str, user_id, e)

        logger.info("Restored %d alarm(s) from DB.", restored)

    # =========================
    # Gestión de alarmas
    # =========================
    def add_alarm(self, application: Application, user_id: int, time_str: str, chat_id: int):
        """
        Add a daily recurring alarm for a user and persist it to SQLite.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]

            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']

            # Persist first — if the DB write fails we don't schedule either
            with _get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO alarms (user_id, chat_id, time_str) VALUES (?, ?, ?)",
                    (user_id, chat_id, time_str)
                )

            self._schedule_job(application, user_id, chat_id, time_str)

            return True, self.config.SUCCESS_MESSAGES['alarm_set'].format(time=time_str)

        except Exception as e:
            logger.error("Error adding alarm: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def remove_alarm(self, user_id: int, time_str: str):
        """
        Remove a specific alarm for a user from both memory and SQLite.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if user_id not in self.user_alarms or time_str not in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_not_found']

            self.user_alarms[user_id][time_str].schedule_removal()
            del self.user_alarms[user_id][time_str]
            if not self.user_alarms[user_id]:
                del self.user_alarms[user_id]

            with _get_conn() as conn:
                conn.execute(
                    "DELETE FROM alarms WHERE user_id = ? AND time_str = ?",
                    (user_id, time_str)
                )

            logger.info("Alarm removed for user %s at %s", user_id, time_str)
            return True, self.config.SUCCESS_MESSAGES['alarm_removed'].format(time=time_str)

        except Exception as e:
            logger.error("Error removing alarm for user %s: %s", user_id, e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def remove_all_alarms(self, user_id: int):
        """
        Remove all alarms for a user from both memory and SQLite.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            if user_id not in self.user_alarms or not self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['no_alarms']

            for job in self.user_alarms[user_id].values():
                job.schedule_removal()
            del self.user_alarms[user_id]

            with _get_conn() as conn:
                conn.execute("DELETE FROM alarms WHERE user_id = ?", (user_id,))

            logger.info("All alarms removed for user %s", user_id)
            return True, self.config.SUCCESS_MESSAGES['all_alarms_removed']

        except Exception as e:
            logger.error("Error removing all alarms for user %s: %s", user_id, e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def get_user_alarms(self, user_id: int):
        """Return sorted list of alarm time strings for a user."""
        if user_id not in self.user_alarms:
            return []
        return sorted(self.user_alarms[user_id].keys())

    # =========================
    # Internal scheduling
    # =========================
    def _schedule_job(self, application: Application, user_id: int, chat_id: int, time_str: str):
        """Create the APScheduler daily job and store the reference in memory."""
        hour, minute = map(int, time_str.split(':'))
        job = application.job_queue.run_daily(
            callback=self._send_alarm_message,
            time=time(hour=hour, minute=minute),
            days=(0, 1, 2, 3, 4, 5, 6),
            data={'user_id': user_id, 'chat_id': chat_id, 'time_str': time_str},
            name=f"alarm_{user_id}_{time_str}"
        )
        if user_id not in self.user_alarms:
            self.user_alarms[user_id] = {}
        self.user_alarms[user_id][time_str] = job

    # =========================
    # Conversación de despertar
    # =========================
    def has_active_conversation(self, user_id: int) -> bool:
        return user_id in self.active_conversations

    def stop_conversation(self, user_id: int) -> bool:
        return self.active_conversations.pop(user_id, None) is not None

    def _format_history(self, history: list[tuple[str, str]]) -> str:
        lines = []
        for role, text in history[-6:]:
            lines.append(f"{'Usuario' if role == 'user' else 'Asistente'}: {text}")
        return "\n".join(lines)

    async def reply_in_conversation(self, user_id: int, user_text: str, bot):
        """Continue a wake-up conversation with the LLM (or fallback)."""
        session = self.active_conversations.get(user_id)
        if not session:
            return

        session["history"].append(("user", user_text))

        prompt = (
            "Continúa la conversación para ayudar a despertar. "
            "No repitas saludos (no digas cosas como 'buen día' ni 'hola' de nuevo). "
            "No uses markdown.\n\n"
            "Usa el Historial de la conversación para contexto y continuidad.\n\n"
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
                logger.exception("LLM failed in reply_in_conversation: %s", e)
                answer = "¡Sigamos! ¿Qué vas a hacer en los próximos 5 minutos?"
        else:
            answer = random.choice([
                "¡Bien! ¿Qué vas a hacer primero ahora mismo?",
                "Genial. ¿Te levantás y tomás un vaso de agua?",
                "¡Vamos! ¿Cuál es tu mini-objetivo de esta mañana?"
            ])

        session["history"].append(("assistant", answer))
        await bot.send_message(chat_id=session["chat_id"], text=answer, parse_mode="HTML")

    # =========================
    # Alarm job callback
    # =========================
    async def _send_alarm_message(self, context):
        """Triggered by APScheduler — sends the first wake-up message and opens a conversation."""
        try:
            job_context = getattr(context.job, "data", None)
            if not job_context:
                logger.error("Job has no data; cannot send alarm.")
                return

            chat_id  = job_context['chat_id']
            user_id  = job_context['user_id']
            time_str = job_context['time_str']

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
                    logger.exception("LLM failed on alarm trigger, using fallback: %s", e)

            if not message:
                message = random.choice(self.config.WAKE_UP_MESSAGES)

            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')

            self.active_conversations[user_id] = {
                "chat_id": chat_id,
                "time_str": time_str,
                "history": [("assistant", message)],
            }

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ {time_str} · Respondé para continuar. Cuando estés despiert@, enviá /despierto.",
            )

            logger.info("Alarm fired for user %s at %s", user_id, time_str)

        except Exception as e:
            logger.error("Error in _send_alarm_message: %s", e)