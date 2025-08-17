#!/usr/bin/env python3
"""
Simple Telegram Alarm Bot - Temporary solution while fixing package conflicts
"""

import os
import asyncio
import json
from datetime import datetime, time
import pytz
import tempfile
import io

# Simple HTTP client for Telegram API
import urllib.request
import urllib.parse

# Text to Speech
from gtts import gTTS

class SimpleTelegramBot:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.alarms = {}  # user_id -> {time_str: scheduled}
        self.active_alarms = {}  # user_id -> time_str (currently ringing alarms)
        self.conversations = {}  # user_id -> conversation state
        self.timezone = pytz.timezone('America/Montevideo')
        
    def send_message(self, chat_id, text):
        """Send a message using direct HTTP request"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown'
        }
        
        try:
            data_encoded = urllib.parse.urlencode(data).encode('utf-8')
            req = urllib.request.Request(url, data=data_encoded, method='POST')
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"Error sending message: {e}")
            return None
    
    def send_voice_message(self, chat_id, text):
        """Generate and send a voice message using TTS"""
        try:
            # Generate speech from text
            tts = gTTS(text=text, lang='es', slow=False)
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
                tts.save(temp_file.name)
                
                # Send voice message to Telegram
                url = f"{self.base_url}/sendVoice"
                
                # Prepare multipart form data
                boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
                
                # Read the audio file
                with open(temp_file.name, 'rb') as audio_file:
                    audio_data = audio_file.read()
                
                # Create multipart body
                body = f'--{boundary}\r\n'
                body += f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
                body += f'{chat_id}\r\n'
                body += f'--{boundary}\r\n'
                body += f'Content-Disposition: form-data; name="voice"; filename="alarm.mp3"\r\n'
                body += f'Content-Type: audio/mpeg\r\n\r\n'
                body = body.encode('utf-8') + audio_data + f'\r\n--{boundary}--\r\n'.encode('utf-8')
                
                # Send request
                req = urllib.request.Request(url, data=body, method='POST')
                req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
                
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode('utf-8'))
                
                # Clean up temporary file
                os.unlink(temp_file.name)
                
                return result
                
        except Exception as e:
            print(f"Error sending voice message: {e}")
            # Fallback to text message
            return self.send_message(chat_id, f"🔊 {text}")
        
        return None
    
    def call_free_llm(self, prompt, conversation_history=""):
        """Generate intelligent responses using a simple AI logic"""
        import random
        
        # Simple but intelligent conversation patterns
        conversation_starters = [
            "¡Buenos días! ¿Cuál es la primera cosa que te emociona hacer hoy?",
            "¡Hora de despertar! Si pudieras teletransportarte a cualquier lugar ahora mismo, ¿dónde irías?",
            "¡Arriba! ¿Qué superpoder te gustaría tener por un día?",
            "¡Despierta! ¿Cuál fue el momento más feliz de tu semana pasada?",
            "¡Buenos días! Si fueras a aprender algo completamente nuevo hoy, ¿qué sería?",
            "¡Hora de levantarse! ¿Qué te haría sonreír ahora mismo?",
            "¡Vamos! ¿Cuál es tu plan más loco para este fin de semana?",
            "¡Despierta! Si pudieras cenar con cualquier persona, ¿quién sería?",
            "¡Buenos días! ¿Qué canción te daría energía perfecta para hoy?",
            "¡Arriba! ¿Cuál es tu lugar favorito para pensar y relajarte?"
        ]
        
        follow_up_responses = {
            "trabajo": [
                "¡Qué interesante! ¿Y qué es lo que más te motiva de tu trabajo?",
                "¡Genial! ¿Hay algún proyecto especial en el que estés trabajando?",
                "¿Y qué planes tienes para crecer profesionalmente este año?"
            ],
            "estudiar": [
                "¡Excelente! ¿Cuál es la materia que más te gusta?",
                "¡Qué bueno! ¿Y qué carrera o tema te apasiona más?",
                "¿Hay algún concepto nuevo que hayas aprendido recientemente?"
            ],
            "viajar": [
                "¡Qué aventurero! ¿Cuál es el lugar más increíble que has visitado?",
                "¡Me encanta! ¿Prefieres las montañas, la playa o las ciudades?",
                "¿Y cuál es el próximo destino en tu lista de deseos?"
            ],
            "ejercicio": [
                "¡Fantástico! ¿Qué tipo de ejercicio es tu favorito?",
                "¡Qué energía! ¿Prefieres ejercitarte solo o en grupo?",
                "¿Y cuál es tu meta fitness más ambiciosa?"
            ],
            "cocinar": [
                "¡Qué delicioso! ¿Cuál es tu plato favorito para preparar?",
                "¡Me encanta! ¿Prefieres cocina internacional o tradicional?",
                "¿Y cuál es la receta más desafiante que has intentado?"
            ]
        }
        
        general_responses = [
            "¡Qué interesante! ¿Y qué te emociona más de eso?",
            "¡Me parece genial! ¿Cómo te sientes cuando lo haces?",
            "¡Qué buena elección! ¿Hay algo específico que te motiva sobre eso?",
            "¡Increíble! ¿Y qué planes tienes relacionados con eso?",
            "¡Excelente! ¿Qué es lo más divertido de esa experiencia?"
        ]
        
        # If it's the first message (no history), give a conversation starter
        if not conversation_history:
            return random.choice(conversation_starters)
        
        # If there's conversation history, generate contextual response
        user_text = prompt.lower()
        
        # Look for keywords and respond accordingly
        for keyword, responses in follow_up_responses.items():
            if keyword in user_text:
                return random.choice(responses)
        
        # Generic intelligent response
        return random.choice(general_responses)
    
    def transcribe_audio_simple(self, audio_data):
        """Simple audio transcription fallback"""
        # For now, we'll use a simple approach
        # User can type their response if voice recognition fails
        return "[Audio recibido - responde con texto si no puedo entender tu voz]"
    
    def get_updates(self, offset=0):
        """Get updates from Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {'offset': offset, 'timeout': 10}
        
        try:
            query_string = urllib.parse.urlencode(params)
            req = urllib.request.Request(f"{url}?{query_string}")
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            print(f"Error getting updates: {e}")
            return None
    
    def validate_time(self, time_str):
        """Validate time format HH:MM"""
        try:
            parts = time_str.split(':')
            if len(parts) != 2:
                return False
            
            hour = int(parts[0])
            minute = int(parts[1])
            
            return 0 <= hour <= 23 and 0 <= minute <= 59
        except:
            return False
    
    def add_alarm(self, user_id, time_str, chat_id):
        """Add an alarm for user"""
        if not self.validate_time(time_str):
            return "❌ Formato de hora inválido. Usa el formato HH:MM (ejemplo: 07:30)"
        
        if user_id not in self.alarms:
            self.alarms[user_id] = {}
        
        if time_str in self.alarms[user_id]:
            return "⚠️ Ya tienes una alarma configurada para esta hora"
        
        self.alarms[user_id][time_str] = {
            'chat_id': chat_id,
            'active': True
        }
        
        return f"✅ Alarma configurada para las {time_str}. Se repetirá diariamente en horario de Montevideo (GMT-3)."
    
    def list_alarms(self, user_id):
        """List user's alarms"""
        if user_id not in self.alarms or not self.alarms[user_id]:
            return "📭 No tienes alarmas configuradas"
        
        message = "⏰ *Tus alarmas activas:*\n\n"
        alarms = sorted(self.alarms[user_id].keys())
        for i, alarm_time in enumerate(alarms, 1):
            message += f"{i}. `{alarm_time}` (diaria)\n"
        
        message += f"\n📊 Total: {len(alarms)} alarma(s)"
        return message
    
    def remove_alarm(self, user_id, time_str):
        """Remove specific alarm"""
        if user_id not in self.alarms or time_str not in self.alarms[user_id]:
            return "❌ No se encontró ninguna alarma para esa hora"
        
        del self.alarms[user_id][time_str]
        if not self.alarms[user_id]:
            del self.alarms[user_id]
        
        return f"✅ Alarma de las {time_str} eliminada correctamente."
    
    def remove_all_alarms(self, user_id):
        """Remove all alarms for user"""
        if user_id not in self.alarms or not self.alarms[user_id]:
            return "📭 No tienes alarmas configuradas"
        
        del self.alarms[user_id]
        # Also stop any active alarms
        if user_id in self.active_alarms:
            del self.active_alarms[user_id]
        return "✅ Todas las alarmas han sido eliminadas."
    
    def stop_active_alarm(self, user_id):
        """Stop currently ringing alarm"""
        if user_id not in self.active_alarms:
            return "😴 No tienes ninguna alarma sonando en este momento"
        
        alarm_time = self.active_alarms[user_id]
        del self.active_alarms[user_id]
        
        return f"✅ Alarma de las {alarm_time} detenida. ¡Buenos días! 🌅\n\nTu alarma seguirá configurada para mañana a la misma hora."
    
    def handle_message(self, message):
        """Handle incoming messages and voice"""
        text = message.get('text', '')
        chat_id = message['chat']['id']
        user_id = message.get('from', {}).get('id')
        voice = message.get('voice')
        
        # Handle voice messages when in conversation mode
        if voice and user_id in self.conversations:
            # For now, ask user to type response
            response = "🎤 Recibí tu audio. Por ahora responde con texto, pronto podré entender tu voz. ¿Qué me querías decir?"
            self.send_message(chat_id, response)
            return
        
        # Handle text responses when in conversation mode
        if user_id in self.conversations and not text.startswith('/'):
            conversation_history = self.conversations[user_id].get('history', '')
            
            # Get AI response
            ai_response = self.call_free_llm(text, conversation_history)
            
            # Update conversation history
            self.conversations[user_id]['history'] += f"\nUsuario: {text}\nAsistente: {ai_response}"
            self.conversations[user_id]['messages'] += 1
            
            # Send voice response
            self.send_voice_message(chat_id, ai_response)
            
            # End conversation after 3 exchanges
            if self.conversations[user_id]['messages'] >= 3:
                end_message = "¡Excelente conversación! Espero que tengas un día increíble. ¡Nos vemos mañana! 😊"
                self.send_message(chat_id, end_message)
                del self.conversations[user_id]
                
                # Also stop active alarm
                if user_id in self.active_alarms:
                    del self.active_alarms[user_id]
            
            return
        
        # Handle commands
        if text == '/start':
            response = """🤖 ¡Bienvenido al Bot de Alarmas Diarias!

Este bot te permite configurar alarmas que se repetirán todos los días a la hora que elijas.

Para comenzar, usa el comando:
`/alarma HH:MM`

Por ejemplo: `/alarma 07:30`

Usa /help para ver todos los comandos disponibles."""
            
        elif text == '/help':
            response = """🤖 *Bot de Alarmas Diarias*

*Comandos disponibles:*

/alarma HH:MM - Configura una alarma diaria
  Ejemplo: `/alarma 07:30`

/list - Muestra todas tus alarmas activas

/remove HH:MM - Elimina una alarma específica
  Ejemplo: `/remove 07:30`

/removeall - Elimina todas tus alarmas

/despierto - Detiene la alarma que está sonando

/testaudio - Prueba el sistema de audio de alarmas

/testai - Prueba la conversación con IA

/help - Muestra este mensaje de ayuda

*Formato de hora:* HH:MM (24 horas)
*Zona horaria:* Montevideo, Uruguay (GMT-3)

¡Las alarmas se repetirán todos los días a la hora configurada! ⏰"""
            
        elif text.startswith('/alarma '):
            time_str = text[8:].strip()
            response = self.add_alarm(user_id, time_str, chat_id)
            
        elif text == '/list':
            response = self.list_alarms(user_id)
            
        elif text.startswith('/remove '):
            time_str = text[8:].strip()
            response = self.remove_alarm(user_id, time_str)
            
        elif text == '/removeall':
            response = self.remove_all_alarms(user_id)
            
        elif text == '/despierto':
            response = self.stop_active_alarm(user_id)
            
        elif text == '/testaudio':
            test_message = "Esta es una prueba del sistema de audio de alarmas. Si puedes escuchar este mensaje de voz, todo está funcionando correctamente."
            self.send_voice_message(chat_id, test_message)
            response = "🔊 Audio de prueba enviado. ¿Pudiste escucharlo correctamente?"
            
        elif text == '/testai':
            # Start a test conversation
            self.conversations[user_id] = {
                'history': '',
                'messages': 0,
                'chat_id': chat_id
            }
            ai_response = self.call_free_llm("Saluda al usuario y haz una pregunta interesante para probar la conversación.")
            self.send_voice_message(chat_id, ai_response)
            response = "🤖 Conversación de prueba iniciada. Responde a la pregunta del audio para continuar."
            
        else:
            response = "Comando no reconocido. Usa /help para ver los comandos disponibles."
        
        self.send_message(chat_id, response)
    
    def check_alarms(self):
        """Check if any alarms should trigger"""
        now = datetime.now(self.timezone)
        current_time = now.strftime("%H:%M")
        
        for user_id, user_alarms in self.alarms.items():
            for time_str, alarm_data in user_alarms.items():
                if time_str == current_time and alarm_data['active']:
                    # Check if this alarm is already ringing
                    if user_id in self.active_alarms and self.active_alarms[user_id] == time_str:
                        continue  # Skip, already notified
                    
                    # Mark alarm as active (ringing)
                    self.active_alarms[user_id] = time_str
                    
                    # Start AI conversation
                    self.conversations[user_id] = {
                        'history': '',
                        'messages': 0,
                        'chat_id': alarm_data['chat_id']
                    }
                    
                    # Get AI-generated wake up question
                    ai_question = self.call_free_llm("¡Buenos días! Es hora de despertar. Genera una pregunta motivadora para empezar el día.")
                    
                    # Create wake up message with AI question
                    wake_message = f"¡Buenos días! Tu alarma de las {time_str} está sonando. {ai_question}"
                    
                    # Send voice message with AI question
                    self.send_voice_message(alarm_data['chat_id'], wake_message)
                    
                    # Send text instructions
                    text_message = f"🤖 *Conversación de Despertar Iniciada*\n\n⏰ Hora: {time_str} (Montevideo)\n🎯 Responde a la pregunta para continuar la conversación\n💡 O usa `/despierto` para detener la alarma"
                    self.send_message(alarm_data['chat_id'], text_message)
        
        # Clean up active alarms that are no longer in the current minute
        alarms_to_remove = []
        for user_id, active_time in self.active_alarms.items():
            if active_time != current_time:
                alarms_to_remove.append(user_id)
        
        for user_id in alarms_to_remove:
            del self.active_alarms[user_id]
    
    async def run(self):
        """Main bot loop"""
        print("🤖 Bot de alarmas iniciado...")
        offset = 0
        
        while True:
            try:
                # Check for new messages
                result = self.get_updates(offset)
                if result and result.get('ok'):
                    for update in result.get('result', []):
                        offset = update['update_id'] + 1
                        
                        if 'message' in update:
                            self.handle_message(update['message'])
                
                # Check alarms every minute
                self.check_alarms()
                
                # Small delay
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"Error in bot loop: {e}")
                await asyncio.sleep(5)

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN environment variable not set")
        return
    
    bot = SimpleTelegramBot(token)
    asyncio.run(bot.run())

if __name__ == '__main__':
    main()