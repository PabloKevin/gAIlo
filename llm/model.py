# LLM interaction logic

def get_llm_response(prompt: str) -> str:
    # Aquí deberías integrar un modelo real o usar una API como OpenAI o HuggingFace
    # Esta función simula una respuesta del LLM.
    return f"Simulación de respuesta a: {prompt}"

def cargar_personalidad() -> str:
    with open("llm/personality.txt", "r", encoding="utf-8") as f:
        return f.read()
