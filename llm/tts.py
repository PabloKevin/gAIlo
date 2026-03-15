# Text-to-Speech helper using edge-tts (Microsoft Edge voices, no API key needed)

import os
import tempfile
import logging
import edge_tts

logger = logging.getLogger(__name__)

DEFAULT_VOICE = os.getenv("TTS_VOICE", "es-UY-ValentinaNeural")


async def text_to_audio(text: str, voice: str = DEFAULT_VOICE) -> str | None:
    """
    Convert text to an OGG audio file using edge-tts.
    Returns the path to a temporary .ogg file, or None if it fails.
    The caller is responsible for deleting the file after sending.
    """
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp.close()
        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(tmp.name)
        logger.info("TTS audio generated: %s (%d chars)", tmp.name, len(text))
        return tmp.name
    except Exception as e:
        logger.error("TTS failed: %s", e)
        return None