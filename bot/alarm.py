"""
Alarm scheduling & conversational flow for the Telegram bot.
- Alarms persisted in SQLite (survives restarts)
- Audio (edge-tts) and text modes, switchable per message
- Language (es/en) configurable per alarm and per message
- Speaker wake-up loop:
    * Generates TTS once, reuses the same file
    * Plays beeps (or custom assets/alarm.mp3) + voice in alternation
- Watchdog:
    * 3 min silence → plays beeps + voice
    * If 40s still no response → aggressive loop until user responds
"""

import asyncio
import logging
import random
import sqlite3
import os
import struct
import wave
import subprocess
import tempfile
from datetime import time, datetime
from pathlib import Path
from telegram.ext import Application
from config import Config
import pytz

logger = logging.getLogger(__name__)

DB_PATH     = Path(os.getenv("DB_PATH", "alarms.db"))
ASSETS_DIR  = Path(__file__).resolve().parent.parent / "assets"
CUSTOM_ALARM_MP3 = ASSETS_DIR / "alarm.mp3"   # drop your own MP3 here

MUSIC_DURATION_SEC   = 10
WATCHDOG_TIMEOUT_SEC = 3 * 60   # 3 min of silence triggers watchdog
WATCHDOG_RETRY_SEC   = 40       # if no response 40s after watchdog fires, go aggressive

TEXT_MODE_TRIGGERS  = ["texto", "text", "escribe", "escribí", "sin audio", "sin voz", "solo texto", "en texto"]
AUDIO_MODE_TRIGGERS = ["audio", "voz", "habla", "hablame", "háblame", "con voz", "con audio", "en audio"]
ES_TRIGGERS = ["español", "espanol", "en español", "castellano", "spanish", "habla español"]
EN_TRIGGERS = ["inglés", "ingles", "en inglés", "english", "in english", "speak english"]

LANG_PROMPTS = {
    "es": "Responde siempre en español.",
    "en": "Always respond in English.",
}

WATCHDOG_MESSAGES = {
    "es": ["¡Ey! ¿Seguís ahí? ¡No te duermas de nuevo!", "¡Despierto! ¿Me estás escuchando?"],
    "en": ["Hey! Are you still there? Don't fall back asleep!", "Wake up! Can you hear me?"],
}

WAKEUP_LOOP_MESSAGES = {
    "es": ["¡Despertate! ¡Es hora de levantarse!", "¡Arriba! ¡Buenos días! ¿Estás escuchando?"],
    "en": ["Wake up! Wake up! Are you listening?", "Rise and shine! Time to get up!"],
}

FALLBACK_REPLIES = {
    "es": ["¡Sigamos! ¿Qué vas a hacer en los próximos 5 minutos?",
           "¿Te levantás y tomás agua?", "¿Cuál es tu mini-objetivo de hoy?"],
    "en": ["Let's go! What are you doing in the next 5 minutes?",
           "How about getting up and drinking some water?", "What's your mini goal for today?"],
}

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


# =========================
# Beep generator
# =========================
def _generate_beep_wav(path: str, duration_sec: float = 10.0, freq: int = 880, sample_rate: int = 44100, amplitude: float = 0.5):
    """
    Generate a simple beep WAV file using only stdlib (struct + wave).
    Pattern: 0.3s beep, 0.3s silence, repeated for duration_sec.
    """
    import math
    beep_dur   = 0.3
    silence_dur = 0.3
    pattern_dur = beep_dur + silence_dur

    frames = bytearray()
    t = 0.0
    while t < duration_sec:
        phase = t % pattern_dur
        if phase < beep_dur:
            sample = int(32767 * amplitude * math.sin(2 * math.pi * freq * t))
        else:
            sample = 0
        frames += struct.pack('<h', sample)
        t += 1.0 / sample_rate

    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))


def _get_alarm_audio_path() -> str:
    """
    Returns path to alarm audio.
    Uses custom assets/alarm.mp3 if it exists, otherwise generates a beep WAV.
    The generated beep is cached at assets/alarm_beep.wav.
    """
    ASSETS_DIR.mkdir(exist_ok=True)

    if CUSTOM_ALARM_MP3.exists():
        logger.info("Using custom alarm MP3: %s", CUSTOM_ALARM_MP3)
        return str(CUSTOM_ALARM_MP3)

    beep_path = str(ASSETS_DIR / "alarm_beep.wav")
    if not Path(beep_path).exists():
        logger.info("Generating beep WAV at %s", beep_path)
        _generate_beep_wav(beep_path, duration_sec=MUSIC_DURATION_SEC)
    return beep_path


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
    try:
        conn.execute("ALTER TABLE alarms ADD COLUMN lang TEXT NOT NULL DEFAULT 'en'")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


class AlarmScheduler:

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
    def add_alarm(self, application, user_id, time_str, chat_id, lang="en"):
        try:
            is_valid, error_key = self.config.validate_time_format(time_str)
            if not is_valid:
                return False, self.config.ERROR_MESSAGES[error_key]
            if user_id in self.user_alarms and time_str in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_exists']
            with _get_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO alarms (user_id, chat_id, time_str, lang) VALUES (?,?,?,?)",
                    (user_id, chat_id, time_str, lang)
                )
            self._schedule_job(application, user_id, chat_id, time_str, lang)
            lang_label = "🇬🇧 English" if lang == "en" else "🇺🇾 Español"
            return True, self.config.SUCCESS_MESSAGES['alarm_set'].format(time=time_str) + f" · {lang_label}"
        except Exception as e:
            logger.error("Error adding alarm: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def remove_alarm(self, user_id, time_str):
        try:
            if user_id not in self.user_alarms or time_str not in self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['alarm_not_found']
            self.user_alarms[user_id][time_str].schedule_removal()
            del self.user_alarms[user_id][time_str]
            if not self.user_alarms[user_id]:
                del self.user_alarms[user_id]
            with _get_conn() as conn:
                conn.execute("DELETE FROM alarms WHERE user_id=? AND time_str=?", (user_id, time_str))
            return True, self.config.SUCCESS_MESSAGES['alarm_removed'].format(time=time_str)
        except Exception as e:
            logger.error("Error removing alarm: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def remove_all_alarms(self, user_id):
        try:
            if user_id not in self.user_alarms or not self.user_alarms[user_id]:
                return False, self.config.ERROR_MESSAGES['no_alarms']
            for job in self.user_alarms[user_id].values():
                job.schedule_removal()
            del self.user_alarms[user_id]
            with _get_conn() as conn:
                conn.execute("DELETE FROM alarms WHERE user_id=?", (user_id,))
            return True, self.config.SUCCESS_MESSAGES['all_alarms_removed']
        except Exception as e:
            logger.error("Error removing all alarms: %s", e)
            return False, self.config.ERROR_MESSAGES['general_error']

    def get_user_alarms(self, user_id):
        if user_id not in self.user_alarms:
            return []
        return sorted(self.user_alarms[user_id].keys())

    def _schedule_job(self, application, user_id, chat_id, time_str, lang="en"):
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
    # Audio playback helpers
    # =========================
    async def _play_file(self, path: str):
        """Play audio file — uses aplay for WAV, mpg123 for MP3."""
        try:
            if path.endswith(".wav"):
                cmd = ["aplay", "-q", path]
            else:
                cmd = ["mpg123", "-q", path]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception as e:
            logger.error("Playback failed for %s: %s", path, e)

    async def _play_beeps(self):
        """Play the alarm beep/music for MUSIC_DURATION_SEC seconds."""
        alarm_path = _get_alarm_audio_path()
        await self._play_file(alarm_path)

    async def _play_voice(self, text: str, lang: str, reuse_path: str | None = None) -> str | None:
        """
        Generate TTS and play it on the speaker.
        If reuse_path is provided and exists, skips generation and reuses it.
        Returns the audio path so it can be reused in the loop.
        """
        try:
            from llm.tts import text_to_audio
            if reuse_path and Path(reuse_path).exists():
                audio_path = reuse_path
            else:
                audio_path = await text_to_audio(text, lang=lang)
            if audio_path:
                await self._play_file(audio_path)
            return audio_path
        except Exception as e:
            logger.error("Voice playback failed: %s", e)
            return None

    # =========================
    # Wake-up loop
    # =========================
    async def _wakeup_loop(self, user_id: int, lang: str, voice_text: str):
        """
        Alternates beeps and voice until the user responds.
        TTS is generated ONCE and reused every iteration.
        Pattern: beeps (10s) → voice → beeps (10s) → voice → ...
        """
        logger.info("Wake-up loop started for user %s", user_id)
        voice_path = None

        while True:
            session = self.active_conversations.get(user_id)
            if not session or not session.get("wakeup_active"):
                break

            await self._play_beeps()

            session = self.active_conversations.get(user_id)
            if not session or not session.get("wakeup_active"):
                break

            voice_path = await self._play_voice(voice_text, lang, reuse_path=voice_path)

        # Cleanup TTS file
        if voice_path and Path(voice_path).exists():
            try:
                os.remove(voice_path)
            except Exception:
                pass

        logger.info("Wake-up loop ended for user %s", user_id)

    # =========================
    # Watchdog loop
    # =========================
    async def _watchdog_loop(self, user_id: int, lang: str):
        """
        After wake-up loop ends, monitors conversation activity.

        Normal mode: checks every 10s, fires after 3 min silence.
        Aggressive mode: fires every 40s until user responds, then returns to normal.
        """
        logger.info("Watchdog started for user %s", user_id)
        aggressive = False
        watchdog_voice_path = None

        while True:
            await asyncio.sleep(10)

            session = self.active_conversations.get(user_id)
            if not session:
                break
            if session.get("wakeup_active"):
                continue  # still in wake-up loop

            elapsed = (datetime.now() - session["last_message_time"]).total_seconds()
            threshold = WATCHDOG_RETRY_SEC if aggressive else WATCHDOG_TIMEOUT_SEC

            if elapsed >= threshold:
                msg = random.choice(WATCHDOG_MESSAGES.get(lang, WATCHDOG_MESSAGES["en"]))
                logger.info("Watchdog firing (aggressive=%s, %.0fs silence) for user %s",
                            aggressive, elapsed, user_id)

                await self._play_beeps()

                session = self.active_conversations.get(user_id)
                if not session:
                    break

                watchdog_voice_path = await self._play_voice(msg, lang, reuse_path=watchdog_voice_path)

                # Switch to aggressive mode after first fire
                aggressive = True
                session["last_message_time"] = datetime.now()
            else:
                # User responded — back to normal watchdog
                if aggressive:
                    logger.info("Watchdog back to normal for user %s", user_id)
                    aggressive = False
                    if watchdog_voice_path and Path(watchdog_voice_path).exists():
                        try:
                            os.remove(watchdog_voice_path)
                        except Exception:
                            pass
                        watchdog_voice_path = None

        logger.info("Watchdog ended for user %s", user_id)

    # =========================
    # Mode & language detection
    # =========================
    def _detect_mode_change(self, text, current_mode):
        t = text.lower()
        if any(x in t for x in TEXT_MODE_TRIGGERS):  return "text"
        if any(x in t for x in AUDIO_MODE_TRIGGERS): return "audio"
        return current_mode

    def _detect_lang_change(self, text, current_lang):
        t = text.lower()
        if any(x in t for x in ES_TRIGGERS): return "es"
        if any(x in t for x in EN_TRIGGERS): return "en"
        return current_lang

    # =========================
    # Send Telegram message
    # =========================
    async def _send_message(self, bot, chat_id, text, mode, lang):
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
    # Conversation
    # =========================
    def has_active_conversation(self, user_id):
        return user_id in self.active_conversations

    def stop_conversation(self, user_id):
        session = self.active_conversations.pop(user_id, None)
        return session is not None

    def _format_history(self, history):
        lines = []
        for role, text in history[-6:]:
            lines.append(f"{'Usuario' if role == 'user' else 'Asistente'}: {text}")
        return "\n".join(lines)

    async def reply_in_conversation(self, user_id, user_text, bot):
        session = self.active_conversations.get(user_id)
        if not session:
            return

        # First response stops wake-up loop
        if session.get("wakeup_active"):
            session["wakeup_active"] = False

        session["last_message_time"] = datetime.now()

        new_mode = self._detect_mode_change(user_text, session["mode"])
        if new_mode != session["mode"]:
            session["mode"] = new_mode
            await bot.send_message(
                chat_id=session["chat_id"],
                text=MODE_CHANGE_MSG.get((new_mode, session["lang"]), "👌 OK")
            )

        new_lang = self._detect_lang_change(user_text, session["lang"])
        if new_lang != session["lang"]:
            session["lang"] = new_lang
            await bot.send_message(
                chat_id=session["chat_id"],
                text=LANG_CHANGE_MSG.get(new_lang, "👌 OK")
            )

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

            # Pick a wake-up loop voice message (fixed for the whole loop)
            wakeup_voice_text = random.choice(WAKEUP_LOOP_MESSAGES.get(lang, WAKEUP_LOOP_MESSAGES["en"]))

            # Open session
            self.active_conversations[user_id] = {
                "chat_id": chat_id,
                "time_str": time_str,
                "history": [("assistant", message)],
                "mode": "audio",
                "lang": lang,
                "wakeup_active": True,
                "last_message_time": datetime.now(),
            }

            # Send ONE Telegram message
            await self._send_message(context.bot, chat_id, message, "audio", lang)

            if lang == "es":
                instructions = (
                    f"⏰ {time_str} · Respondé para detener la alarma.\n"
                    f"🌐 'en inglés' / 'en español' para cambiar idioma.\n"
                    f"💬 'en texto' / 'en audio' para cambiar formato.\n"
                    f"✅ Cuando estés despiert@, enviá /despierto."
                )
            else:
                instructions = (
                    f"⏰ {time_str} · Reply to stop the alarm.\n"
                    f"🌐 'in Spanish' / 'in English' to switch language.\n"
                    f"💬 'text mode' / 'audio mode' to switch format.\n"
                    f"✅ When you're up, send /despierto."
                )
            await context.bot.send_message(chat_id=chat_id, text=instructions)

            # Start background tasks
            asyncio.create_task(self._wakeup_loop(user_id, lang, wakeup_voice_text))
            asyncio.create_task(self._watchdog_loop(user_id, lang))

            logger.info("Alarm fired for user %s at %s lang=%s", user_id, time_str, lang)

        except Exception as e:
            logger.error("Error in _send_alarm_message: %s", e)