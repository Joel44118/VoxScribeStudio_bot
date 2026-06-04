import os
import io
import asyncio
from aiohttp import web, ClientSession
import speech_recognition as sr

# 1. Fetch Environment Variables
TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TOKEN}/"
FILE_URL = f"https://api.telegram.org/file/bot{TOKEN}/"

# 2. Web Server Route (Health Check for Render)
async def handle_health(request):
    return web.Response(text="VoxScribe is active!")

# 3. Handle Voice Messages
async def process_voice(session, chat_id, file_id):
    # Let the user know the bot is working
    await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": "🔄 Processing your voice note, please wait..."})

    try:
        # Get file path from Telegram API
        async with session.get(f"{API_URL}getFile", params={"file_id": file_id}) as res:
            res_data = await res.json()
            if not res_data.get("ok"):
                raise Exception("Failed to get file data from Telegram.")
            file_path = res_data["result"]["file_path"]

        # Download the file into memory
        async with session.get(f"{FILE_URL}{file_path}") as file_res:
            audio_data = await file_res.read()

        # Audio Transcription Logic
        recognizer = sr.Recognizer()
        
        # Open raw audio data using SpeechRecognition
        # Note: Render free tier requires extremely lightweight processing
        with sr.AudioFile(io.BytesIO(audio_data)) as source:
            audio = recognizer.record(source)
        
        # Transcribe offline using pocket sphinx
        text_result = recognizer.recognize_sphinx(audio)
        
        if not text_result.strip():
            text_result = "⚠️ Speech detected, but I couldn't make out the words clearly."
            
        reply_text = f"📝 **Transcription:**\n\n\"{text_result}\""

    except sr.UnknownValueError:
        reply_text = "❌ Sorry, I couldn't understand the audio. Make sure it's clear and in English."
    except sr.RequestError as e:
        reply_text = f"❌ Error handling the speech engine: {e}"
    except Exception as e:
        print(f"Error processing voice: {e}")
        reply_text = "❌ An error occurred while converting your voice note. Please try a shorter message."

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
                            voice = message.get("voice")  # Check if a voice note was sent
                            
                            if not chat_id:
                                continue
                                
                            if text == "/start":
                                msg = "Hello! Send or forward me a voice note, and I will attempt to convert it to text."
                                await session.post(f"{API_URL}sendMessage", data={"chat_id": chat_id, "text": msg})
                            elif voice:
                                # Grab the Telegram file_id for the audio
                                file_id = voice["file_id"]
                                # Process audio asynchronously so the bot stays responsive
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
