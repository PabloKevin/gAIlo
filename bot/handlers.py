"""
Command handlers for the Telegram Alarm Bot
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import Config
from bot.alarm import AlarmScheduler

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = {"es", "en"}
LANG_LABELS = {"es": "🇺🇾 Español", "en": "🇬🇧 English"}


class AlarmHandlers:
    """Contains all command handlers for the alarm bot"""

    def __init__(self, alarm_scheduler: AlarmScheduler):
        self.alarm_scheduler = alarm_scheduler
        self.config = Config()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            welcome_message = """
🤖 *Bienvenido al Bot de Alarmas!*

Configura alarmas diarias con conversación inteligente para despertarte.

Para comenzar:
`/alarma HH:MM` → español (por defecto: inglés)
`/alarma HH:MM en` → inglés
`/alarma HH:MM es` → español

Usa /help para ver todos los comandos.
            """
            await update.message.reply_text(welcome_message, parse_mode='Markdown')
            logger.info("Start command by user %s", update.effective_user.id)
        except Exception as e:
            logger.error("Error in start command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            help_text = """
🤖 *Bot de Alarmas Diarias*

*Comandos:*

/alarma HH:MM \[lang\] — Configura una alarma diaria
  `lang` puede ser `es` o `en` (default: `en`)
  Ejemplos:
  `/alarma 07:30` → inglés
  `/alarma 07:30 es` → español
  `/alarma 07:30 en` → inglés

/despierto — Confirmá que ya te levantaste

/list — Muestra tus alarmas activas

/remove HH:MM — Elimina una alarma

/removeall — Elimina todas las alarmas

/help — Este mensaje

*Durante la conversación podés decir:*
• `en texto` / `en audio` — cambiar formato
• `en español` / `en inglés` — cambiar idioma
            """
            await update.message.reply_text(help_text, parse_mode='Markdown')
            logger.info("Help command by user %s", update.effective_user.id)
        except Exception as e:
            logger.error("Error in help command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def set_alarm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            chat_id = update.effective_chat.id

            if not context.args:
                await update.message.reply_text(
                    "❌ Especificá la hora.\n\n"
                    "Uso: `/alarma HH:MM [lang]`\n"
                    "Ejemplo: `/alarma 07:30 es`",
                    parse_mode='Markdown'
                )
                return

            time_str = context.args[0]

            # Optional language argument (default: en)
            lang = "en"
            if len(context.args) >= 2:
                lang_arg = context.args[1].lower()
                if lang_arg in SUPPORTED_LANGS:
                    lang = lang_arg
                else:
                    await update.message.reply_text(
                        f"❌ Idioma inválido: `{lang_arg}`\n"
                        "Opciones: `es` (español) o `en` (inglés)",
                        parse_mode='Markdown'
                    )
                    return

            success, message = self.alarm_scheduler.add_alarm(
                application=context.application,
                user_id=user_id,
                time_str=time_str,
                chat_id=chat_id,
                lang=lang
            )

            await update.message.reply_text(message)

            if success:
                logger.info("Alarm set by user %s for %s lang=%s", user_id, time_str, lang)
            else:
                logger.warning("Failed to set alarm for user %s: %s", user_id, message)

        except Exception as e:
            logger.error("Error in set_alarm command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def list_alarms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            alarms = self.alarm_scheduler.get_user_alarms(user_id)

            if not alarms:
                await update.message.reply_text(self.config.ERROR_MESSAGES['no_alarms'])
                return

            message = "⏰ *Tus alarmas activas:*\n\n"
            for i, alarm_time in enumerate(alarms, 1):
                # Get lang from DB for display
                from bot.alarm import _get_conn
                with _get_conn() as conn:
                    row = conn.execute(
                        "SELECT lang FROM alarms WHERE user_id = ? AND time_str = ?",
                        (user_id, alarm_time)
                    ).fetchone()
                lang = row[0] if row else "en"
                lang_label = LANG_LABELS.get(lang, lang)
                message += f"{i}. `{alarm_time}` · {lang_label}\n"

            message += f"\n📊 Total: {len(alarms)} alarma(s)"
            await update.message.reply_text(message, parse_mode='Markdown')
            logger.info("List command by user %s — %d alarms", user_id, len(alarms))

        except Exception as e:
            logger.error("Error in list_alarms command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def remove_alarm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            if not context.args:
                await update.message.reply_text(
                    "❌ Especificá la hora.\n\nUso: `/remove HH:MM`",
                    parse_mode='Markdown'
                )
                return
            time_str = context.args[0]
            success, message = self.alarm_scheduler.remove_alarm(user_id, time_str)
            await update.message.reply_text(message)
            if success:
                logger.info("Alarm removed by user %s for %s", user_id, time_str)
        except Exception as e:
            logger.error("Error in remove_alarm command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def remove_all_alarms_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            success, message = self.alarm_scheduler.remove_all_alarms(user_id)
            await update.message.reply_text(message)
            if success:
                logger.info("All alarms removed by user %s", user_id)
        except Exception as e:
            logger.error("Error in remove_all_alarms command: %s", e)
            await update.message.reply_text(self.config.ERROR_MESSAGES['general_error'])

    async def wake_ack_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if self.alarm_scheduler.stop_conversation(user_id):
            await update.message.reply_text(
                "✅ ¡Genial! Me alegra que ya estés despiert@. ¡Que tengas un día tremendo!"
            )
        else:
            await update.message.reply_text(
                "No hay una conversación de alarma activa en este momento."
            )

    async def conversation_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        text = (update.message.text or "").strip()
        if self.alarm_scheduler.has_active_conversation(user_id):
            await self.alarm_scheduler.reply_in_conversation(user_id, text, context.bot)