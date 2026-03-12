# LLM interaction logic — Groq backend

import os
from groq import AsyncGroq

class LLM_Client:
    def __init__(self, model=None, timeout=30.0):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        self.client = AsyncGroq(api_key=api_key)
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.timeout = timeout

    def cargar_personalidad(self) -> str:
        with open("llm/personality.txt", "r", encoding="utf-8") as f:
            return f.read()

    async def generate(self, prompt_t_alarm: str) -> str:
        """
        Generate a response using Groq's chat completion API.
        Keeps the same interface as the Ollama version — nothing else needs to change.
        """
        system_prompt = self.cargar_personalidad()

        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": prompt_t_alarm},
            ],
            model=self.model,
            temperature=0.85,      # a bit of variety each morning
            max_tokens=256,        # keep replies concise for a wake-up chat
        )

        return (chat_completion.choices[0].message.content or "").strip()