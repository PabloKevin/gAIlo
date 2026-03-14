import os
import httpx

class LLM_Client:
    def __init__(self, model=None, timeout=30.0):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.timeout = timeout

    def cargar_personalidad(self):
        with open("llm/personality.txt", "r", encoding="utf-8") as f:
            return f.read()

    async def generate(self, prompt: str) -> str:
        system_prompt = self.cargar_personalidad()
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": prompt}
                    ],
                    "temperature": 0.85,
                    "max_tokens": 256
                }
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()