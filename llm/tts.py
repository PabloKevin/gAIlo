# Text-to-Speech helper using edge-tts (Microsoft Edge voices, no API key needed)

import os
import tempfile
import logging
import edge_tts

logger = logging.getLogger(__name__)

# Default voices per language
VOICES = {
    "es": os.getenv("TTS_VOICE_ES", "es-UY-ValentinaNeural"),
    "en": os.getenv("TTS_VOICE_EN", "en-GB-SoniaNeural"),
}


def get_voice(lang: str) -> str:
    """Return the TTS voice for a given language code."""
    return VOICES.get(lang, VOICES["en"])


async def text_to_audio(text: str, lang: str = "en") -> str | None:
    """
    Convert text to an OGG audio file using edge-tts.
    Returns the path to a temporary .ogg file, or None if it fails.
    The caller is responsible for deleting the file after sending.
    """
    try:
        voice = get_voice(lang)
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp.close()
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(tmp.name)
        logger.info("TTS audio generated: %s (lang=%s voice=%s)", tmp.name, lang, voice)
        return tmp.name
    except Exception as e:
        logger.error("TTS failed: %s", e)
        return None