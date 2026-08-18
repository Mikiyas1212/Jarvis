import ollama
import speech_recognition as sr
import asyncio
import edge_tts
import os
import uuid
from playsound import playsound

# ----------------------------
# SETTINGS
# ----------------------------
MODEL = "tinyllama"
VOICE = "en-US-AriaNeural"

# ----------------------------
# SPEAK
# ----------------------------
async def speak_async(text, filename):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(filename)

def speak(text):
    print("Jarvis:", text)

    filename = f"jarvis_{uuid.uuid4().hex}.mp3"

    try:
        asyncio.run(speak_async(text, filename))
        playsound(filename)
    except Exception as e:
        print("VOICE ERROR:", e)
    finally:
        try:
            if os.path.exists(filename):
                os.remove(filename)
        except:
            pass

# ----------------------------
# LISTEN
# ----------------------------
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("Listening...")
        audio = r.listen(source, phrase_time_limit=5)

    try:
        command = r.recognize_google(audio)
        print("You said:", command)
        return command
    except:
        return ""

# ----------------------------
# ASK LOCAL AI (Concise Replies)
# ----------------------------
def ask_ai(prompt):
    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are Jarvis. Answer clearly, directly, and concisely. Do not repeat the question."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        return response["message"]["content"]

    except Exception as e:
        print("AI ERROR:", e)
        return "AI connection failed."

# ----------------------------
# MAIN LOOP
# ----------------------------
speak("Jarvis is online. How can I be of assistance to you sir?")

while True:
    try:
        command = listen()

        if not command:
            continue

        if "stop" in command.lower():
            speak("Shutting down.")
            break

        reply = ask_ai(command)
        speak(reply)

    except KeyboardInterrupt:
        print("Exiting Jarvis...")
        break