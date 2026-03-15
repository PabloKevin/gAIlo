"""
Alarm scheduling & conversational flow for the Telegram bot.
Alarms are persisted in SQLite so they survive restarts.
Supports audio (edge-tts) and text modes, switchable per conversation.
"""

import logging
import random
import sqlite3
import os
from datetime import time
from pathlib import Path
from telegram.ext import Application
from config import Config
import pytz

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "alarms.db"))

TEXT_MODE_TRIGGERS = [
    "texto", "text", "escribe", "escribí", "sin audio",
    "sin voz", "solo texto", "en texto"
]

AUDIO_MODE_TRIGGERS = [
    "audio", "voz", "habla", "hablame", "háblame",
    "con voz", "con audio", "en audio"
]


def _get_conn() -> sqlite3.Connection:
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
        self.user_alarms: dict[int, dict[str, object]] = {}
        self.active_conversations: dict[int, dict] = {}
        self.config = Config()
        self.timezone = pytz.timezone(self.config.DEFAULT_TIMEZONE)
        self.llm = llm
        logger.info("LLM enabled=%s  DB=%s", self.llm is not None, DB_PATH)

    # =========================
    # Startup restore
    # =========================
    def restore_alarms(self, application: Application):
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
    # Alarm management
    # =========================
    def add_alarm(self, application: Application, user_id: int, time_str: str, chat_id: int):
        try:
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]
            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']
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
            logger.error("Error removing alarm: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def remove_all_alarms(self, user_id: int):
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
            logger.error("Error removing all alarms: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def get_user_alarms(self, user_id: int):
        if user_id not in self.user_alarms:
            return []
        return sorted(self.user_alarms[user_id].keys())

    # =========================
    # Internal scheduling
    # =========================
    def _schedule_job(self, application: Application, user_id: int, chat_id: int, time_str: str):
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
    # Mode detection
    # =========================
    def _detect_mode_change(self, text: str, current_mode: str) -> str:
        text_lower = text.lower()
        if any(trigger in text_lower for trigger in TEXT_MODE_TRIGGERS):
            return "text"
        if any(trigger in text_lower for trigger in AUDIO_MODE_TRIGGERS):
            return "audio"
        return current_mode

    # =========================
    # Send message helper
    # =========================
    async def _send_message(self, bot, chat_id: int, text: str, mode: str):
        """Send as voice note or text depending on mode. Falls back to text if TTS fails."""
        if mode == "audio":
            try:
                from llm.tts import text_to_audio
                audio_path = await text_to_audio(text)
                if audio_path:
                    with open(audio_path, "rb") as f:
                        await bot.send_voice(chat_id=chat_id, voice=f)
                    os.remove(audio_path)
                    return
            except Exception as e:
                logger.error("Audio send failed, falling back to text: %s", e)
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    # =========================
    # Wake-up conversation
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
        session = self.active_conversations.get(user_id)
        if not session:
            return

        # Detect mode change request
        new_mode = self._detect_mode_change(user_text, session["mode"])
        if new_mode != session["mode"]:
            session["mode"] = new_mode
            mode_msg = "👌 Cambiando a modo texto." if new_mode == "text" else "👌 Cambiando a modo audio."
            await bot.send_message(chat_id=session["chat_id"], text=mode_msg)

        session["history"].append(("user", user_text))
        session["history"] = session["history"][-10:]

        prompt = (
            "Continúa la conversación para ayudar a despertar. "
            "No repitas saludos. No uses markdown.\n\n"
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
                logger.exception("LLM failed: %s", e)
                answer = "¡Sigamos! ¿Qué vas a hacer en los próximos 5 minutos?"
        else:
            answer = random.choice([
                "¡Bien! ¿Qué vas a hacer primero?",
                "¿Te levantás y tomás agua?",
                "¿Cuál es tu mini-objetivo de hoy?"
            ])

        session["history"].append(("assistant", answer))
        await self._send_message(bot, session["chat_id"], answer, session["mode"])

    # =========================
    # Alarm job callback
    # =========================
    async def _send_alarm_message(self, context):
        try:
            job_context = getattr(context.job, "data", None)
            if not job_context:
                logger.error("Job has no data.")
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
                    "- ¡Buen día! ¿Cuál es tu mini-objetivo de la mañana?\n"
                )
                try:
                    message = await self.llm.generate(prompt)
                except Exception as e:
                    logger.exception("LLM failed on alarm trigger: %s", e)

            if not message:
                message = random.choice(self.config.WAKE_UP_MESSAGES)

            # Open session in audio mode by default
            self.active_conversations[user_id] = {
                "chat_id": chat_id,
                "time_str": time_str,
                "history": [("assistant", message)],
                "mode": "audio",
            }

            # First message always as audio
            await self._send_message(context.bot, chat_id, message, "audio")

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⏰ {time_str} · Respondé para continuar.\n"
                    f"💬 Decime 'en texto' o 'en audio' para cambiar el modo.\n"
                    f"✅ Cuando estés despiert@, enviá /despierto."
                ),
            )

            logger.info("Alarm fired for user %s at %s", user_id, time_str)

        except Exception as e:
            logger.error("Error in _send_alarm_message: %s", e)