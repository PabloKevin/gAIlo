# AlarmBot

Bot de Telegram para ayudarte a despertar con interacción conversacional.

## Estructura del Proyecto

- `main.py`: punto de entrada del bot.
- `bot/`: lógica del bot (handlers, alarmas, utilidades).
- `llm/`: configuración del modelo de lenguaje (personalidad, respuesta).
- `config.py`: token y configuración general.
- `requirements.txt`: dependencias para correr el bot.

## Cómo ejecutar

1. Instala dependencias:
```bash
pip install -r requirements.txt
```

2. Crea un archivo `.env` o edita `config.py` con tu TOKEN de Telegram.

3. Ejecuta el bot:
```bash
python main.py
```
