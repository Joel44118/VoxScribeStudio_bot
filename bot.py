import os
import io
import asyncio
from aiohttp import web, ClientSession
import speech_recognition as sr
import soundfile as sf
import librosa

# 1. Fetch Environment Variables
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TOKEN}/"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}/"

# 2. Web Server Route (Health Check for Render)
async def handle_health(request):
    return web.Response(text="VoxScribe is active!")

# 3. Handle Voice Messages
async def process_voice(session, chat_id, file_id):
    await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": "🔄 Processing your voice note, please wait..."})

    try:
        # Get file path from Telegram API
        async with session.get(f"{API_URL}getFile", params={"file_id": file_id}) as res:
            res_data = await res.json()
            if not res_data.get("ok"):
                raise Exception("Failed to get file data from Telegram.")
            file_path = res_data["result"]["file_path"]

        # Download the .ogg file into memory
        async with session.get(f"{FILE_URL}{file_path}") as file_res:
            ogg_bytes = await file_res.read()

        # Convert .ogg bytes to a format SpeechRecognition understands using pure Python
        ogg_io = io.BytesIO(ogg_bytes)
        audio_data, sample_rate = librosa.load(ogg_io, sr=16000) # Resample to 16kHz for accurate translation
        
        # Write it to an in-memory WAV container
        wav_io = io.BytesIO()
        sf.write(wav_io, audio_data, sample_rate, format='WAV', subtype='PCM_16')
        wav_io.seek(0)

        # Feed the clean WAV data to the Speech Engine
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            audio = recognizer.record(source)
        
        # Transcribe offline using PocketSphinx
        text_result = recognizer.recognize_sphinx(audio)
        
        if not text_result.strip():
            reply_text = "⚠️ Speech detected, but I couldn't make out the words clearly."
        else:
            reply_text = f"📝 **Transcription:**\n\n\"{text_result}\""

    except sr.UnknownValueError:
        reply_text = "❌ Sorry, I couldn't understand the audio. Make sure it's clear and in English."
    except sr.RequestError as e:
        reply_text = f"❌ Error handling the speech engine: {e}"
    except Exception as e:
        print(f"Detailed Error: {e}")
        reply_text = "❌ An error occurred while processing the audio data. Try speaking closer to the mic."

    # Send the transcribed text back
    await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": reply_text, "parse_mode": "Markdown"})

# 4. Main Bot Long Polling
async def bot_polling():
    offset = 0
    print("VoxScribe polling started...")
    
    async with ClientSession() as session:
        while True:
            try:
                url = f"{API_URL}getUpdates"
                params = {"offset": offset, "timeout": 30}
                
                async with session.get(url, params=params, timeout=35) as response:
                    res_json = await response.json()
                    
                    if res_json.get("ok") and res_json.get("result"):
                        for update in res_json["result"]:
                            offset = update["update_id"] + 1
                            message = update.get("message", {})
                            chat_id = message.get("chat", {}).get("id")
                            text = message.get("text", "")
                            voice = message.get("voice")
                            
                            if not chat_id:
                                continue
                                
                            if text == "/start":
                                msg = "Hello! Send or forward me a voice note, and I will convert it to text."
                                await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": msg})
                            elif voice:
                                file_id = voice["file_id"]
                                asyncio.create_task(process_voice(session, chat_id, file_id))
                            elif text:
                                await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": "🤖 I only accept voice notes! Send or forward me audio to begin."})
                                
            except Exception as e:
                print(f"Polling error: {e}")
                await asyncio.sleep(5)

# 5. Application Launcher
async def main():
    app = web.Application()
    app.router.add_get('/', handle_health)
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    
    await site.start()
    await bot_polling()

if __name__ == "__main__":
    asyncio.run(main())
