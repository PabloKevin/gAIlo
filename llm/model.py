# LLM interaction logic

import os
import httpx

class LLM_Client:
    def __init__(self, host=None, model=None, timeout=30.0):
        self.host = host or os.getenv("LLM_HOST")
        self.model = model or os.getenv("OLLAMA_MODEL")
        self.timeout = timeout

    def cargar_personalidad(self) -> str:
        with open("llm/personality.txt", "r", encoding="utf-8") as f:
            return f.read()

    async def generate(self, prompt_t_alarm: str) -> str:
        prompt = self.cargar_personalidad() + prompt_t_alarm
        payload = {"model": self.model, "prompt": prompt, "stream": False}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.host}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()

