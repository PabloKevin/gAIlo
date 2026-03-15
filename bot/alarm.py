"""
Alarm scheduling & conversational flow for the Telegram bot.
- Alarms persisted in SQLite (survives restarts)
- Audio (edge-tts) and text modes, switchable per message
- Language (es/en) configurable per alarm and per message
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

# --- Mode triggers ---
TEXT_MODE_TRIGGERS  = ["texto", "text", "escribe", "escribí", "sin audio", "sin voz", "solo texto", "en texto"]
AUDIO_MODE_TRIGGERS = ["audio", "voz", "habla", "hablame", "háblame", "con voz", "con audio", "en audio"]

# --- Language triggers ---
ES_TRIGGERS = ["español", "espanol", "en español", "castellano", "spanish", "habla español"]
EN_TRIGGERS = ["inglés", "ingles", "en inglés", "english", "in english", "speak english"]

# --- LLM language instructions ---
LANG_PROMPTS = {
    "es": "Responde siempre en español.",
    "en": "Always respond in English.",
}

# --- Fallback messages per language ---
FALLBACK_REPLIES = {
    "es": [
        "¡Sigamos! ¿Qué vas a hacer en los próximos 5 minutos?",
        "¿Te levantás y tomás agua?",
        "¿Cuál es tu mini-objetivo de hoy?",
    ],
    "en": [
        "Let's go! What are you doing in the next 5 minutes?",
        "How about getting up and drinking some water?",
        "What's your mini goal for today?",
    ],
}

# --- Mode change confirmation messages per language ---
MODE_CHANGE_MSG = {
    ("audio", "es"): "👌 Cambiando a modo audio.",
    ("text",  "es"): "👌 Cambiando a modo texto.",
    ("audio", "en"): "👌 Switching to audio mode.",
    ("text",  "en"): "👌 Switching to text mode.",
}

LANG_CHANGE_MSG = {
    "es": "👌 Cambiando a español.",
    "en": "👌 Switching to English.",
}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alarms (
            user_id  INTEGER NOT NULL,
            chat_id  INTEGER NOT NULL,
            time_str TEXT    NOT NULL,
            lang     TEXT    NOT NULL DEFAULT 'en',
            PRIMARY KEY (user_id, time_str)
        )
    """)
    # Migration: add lang column if it doesn't exist yet
    try:
        conn.execute("ALTER TABLE alarms ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    return conn


class AlarmScheduler:
    """Handles alarm scheduling, persistence, and wake-up conversations."""

    def __init__(self, llm=None):
        self.user_alarms: dict[int, dict[str, object]] = {}
        # session keys: chat_id, time_str, history, mode ("audio"|"text"), lang ("es"|"en")
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
            rows = conn.execute("SELECT user_id, chat_id, time_str, lang FROM alarms").fetchall()
        restored = 0
        for user_id, chat_id, time_str, lang in rows:
            try:
                self._schedule_job(application, user_id, chat_id, time_str, lang)
                restored += 1
            except Exception as e:
                logger.error("Could not restore alarm %s for user %s: %s", time_str, user_id, e)
        logger.info("Restored %d alarm(s) from DB.", restored)

    # =========================
    # Alarm management
    # =========================
    def add_alarm(self, application: Application, user_id: int, time_str: str, chat_id: int, lang: str = "en"):
        try:
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]
            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']
            with _get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO alarms (user_id, chat_id, time_str, lang) VALUES (?, ?, ?, ?)",
                    (user_id, chat_id, time_str, lang)
                )
            self._schedule_job(application, user_id, chat_id, time_str, lang)
            lang_label = "🇬🇧 English" if lang == "en" else "🇺🇾 Español"
            return True, self.config.SUCCESS_MESSAGES['alarm_set'].format(time=time_str) + f" · {lang_label}"
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
    def _schedule_job(self, application: Application, user_id: int, chat_id: int, time_str: str, lang: str = "en"):
        hour, minute = map(int, time_str.split(':'))
        job = application.job_queue.run_daily(
            callback=self._send_alarm_message,
            time=time(hour=hour, minute=minute),
            days=(0, 1, 2, 3, 4, 5, 6),
            data={'user_id': user_id, 'chat_id': chat_id, 'time_str': time_str, 'lang': lang},
            name=f"alarm_{user_id}_{time_str}"
        )
        if user_id not in self.user_alarms:
            self.user_alarms[user_id] = {}
        self.user_alarms[user_id][time_str] = job

    # =========================
    # Mode & language detection
    # =========================
    def _detect_mode_change(self, text: str, current_mode: str) -> str:
        text_lower = text.lower()
        if any(t in text_lower for t in TEXT_MODE_TRIGGERS):
            return "text"
        if any(t in text_lower for t in AUDIO_MODE_TRIGGERS):
            return "audio"
        return current_mode

    def _detect_lang_change(self, text: str, current_lang: str) -> str:
        text_lower = text.lower()
        if any(t in text_lower for t in ES_TRIGGERS):
            return "es"
        if any(t in text_lower for t in EN_TRIGGERS):
            return "en"
        return current_lang

    # =========================
    # Send message helper
    # =========================
    async def _send_message(self, bot, chat_id: int, text: str, mode: str, lang: str):
        """Send as voice note or text. Falls back to text if TTS fails."""
        if mode == "audio":
            try:
                from llm.tts import text_to_audio
                audio_path = await text_to_audio(text, lang=lang)
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

        # Detect mode change
        new_mode = self._detect_mode_change(user_text, session["mode"])
        if new_mode != session["mode"]:
            session["mode"] = new_mode
            msg = MODE_CHANGE_MSG.get((new_mode, session["lang"]), "👌 OK")
            await bot.send_message(chat_id=session["chat_id"], text=msg)

        # Detect language change
        new_lang = self._detect_lang_change(user_text, session["lang"])
        if new_lang != session["lang"]:
            session["lang"] = new_lang
            msg = LANG_CHANGE_MSG.get(new_lang, "👌 OK")
            await bot.send_message(chat_id=session["chat_id"], text=msg)

        session["history"].append(("user", user_text))
        session["history"] = session["history"][-10:]

        lang_instruction = LANG_PROMPTS.get(session["lang"], LANG_PROMPTS["en"])

        prompt = (
            f"{lang_instruction} "
            "Continue the conversation to help wake up. "
            "Do not repeat greetings. Do not use markdown.\n\n"
            "Conversation history (most recent at the bottom):\n"
            f"{self._format_history(session['history'])}\n\n"
            "Assistant:"
        )

        if self.llm is not None:
            try:
                answer = await self.llm.generate(prompt)
                if not answer:
                    raise RuntimeError("Empty LLM response")
            except Exception as e:
                logger.exception("LLM failed: %s", e)
                answer = random.choice(FALLBACK_REPLIES[session["lang"]])
        else:
            answer = random.choice(FALLBACK_REPLIES[session["lang"]])

        session["history"].append(("assistant", answer))
        await self._send_message(bot, session["chat_id"], answer, session["mode"], session["lang"])

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
            lang     = job_context.get('lang', 'en')

            lang_instruction = LANG_PROMPTS.get(lang, LANG_PROMPTS["en"])
            message = None

            if self.llm is not None:
                prompt = (
                    f"{lang_instruction} "
                    "This is the first wake-up message. Greet briefly. "
                    "Start an interesting conversation with an icebreaker question. "
                    f"Scheduled time: {time_str}. Do not use markdown.\n\n"
                    "Style examples:\n"
                    "- Rise and shine! What's the first thing you're doing in the next 5 minutes?\n"
                    "- Good morning! What's your mini goal for today?\n"
                )
                try:
                    message = await self.llm.generate(prompt)
                except Exception as e:
                    logger.exception("LLM failed on alarm trigger: %s", e)

            if not message:
                message = random.choice(self.config.WAKE_UP_MESSAGES)

            self.active_conversations[user_id] = {
                "chat_id": chat_id,
                "time_str": time_str,
                "history": [("assistant", message)],
                "mode": "audio",
                "lang": lang,
            }

            await self._send_message(context.bot, chat_id, message, "audio", lang)

            # Instructions in the session language
            if lang == "es":
                instructions = (
                    f"⏰ {time_str} · Respondé para continuar.\n"
                    f"🌐 Decime 'en inglés' o 'en español' para cambiar idioma.\n"
                    f"💬 Decime 'en texto' o 'en audio' para cambiar el modo.\n"
                    f"✅ Cuando estés despiert@, enviá /despierto."
                )
            else:
                instructions = (
                    f"⏰ {time_str} · Reply to continue.\n"
                    f"🌐 Say 'in Spanish' or 'in English' to switch language.\n"
                    f"💬 Say 'text mode' or 'audio mode' to switch format.\n"
                    f"✅ When you're up, send /despierto."
                )

            await context.bot.send_message(chat_id=chat_id, text=instructions)
            logger.info("Alarm fired for user %s at %s lang=%s", user_id, time_str, lang)

        except Exception as e:
            logger.error("Error in _send_alarm_message: %s", e)