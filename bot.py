from fastapi import FastAPI, Request
import requests
import os
import re

app = FastAPI()

EVOLUTION_API = os.getenv("EVOLUTION_API_URL")
API_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE = os.getenv("INSTANCE_NAME")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://3.108.234.140:11434")

# Conversation history store (in-memory)
conversation_history = {}

SYSTEM_PROMPT = """You are a smart and friendly WhatsApp assistant for an IT services company.
You MUST always reply in English only, regardless of what language the customer uses.
You help customers with queries related to the following services:

1. Web & App Development
   - Custom website development
   - Mobile app development (Android & iOS)
   - E-commerce solutions
   - UI/UX design

2. Networking & IT Support
   - Network setup and configuration
   - IT infrastructure support
   - Troubleshooting & maintenance
   - Remote IT support

3. Software & Cloud Services
   - Custom software development
   - Cloud migration & hosting (AWS, Azure, Google Cloud)
   - SaaS solutions
   - Database management

4. General IT Consulting
   - Technology consulting
   - Digital transformation
   - IT project management
   - Cybersecurity solutions

Your behavior:
- ALWAYS reply in English only, no exceptions
- Be professional but friendly and conversational
- Keep replies concise and suitable for WhatsApp (avoid very long responses)
- If someone wants to book a service or get a quote, ask for their name, requirements, and contact info
- If you don't know something specific (like exact pricing), say a team member will follow up
- Use emojis occasionally to keep the conversation warm
- Never make up prices or guarantees you can't keep"""


def get_ai_reply(number: str, user_message: str) -> str:
    if number not in conversation_history:
        conversation_history[number] = []

    conversation_history[number].append({
        "role": "user",
        "content": user_message
    })

    history = conversation_history[number][-10:]

    payload = {
        "model": "deepseek-r1:7b",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history
        ],
        "stream": False
    }

    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json=payload,
        timeout=120
    )

    print(f"[DEBUG] Ollama status: {response.status_code}")
    print(f"[DEBUG] Ollama response: {response.text[:300]}")

    reply = response.json()["message"]["content"]

    # Remove <think>...</think> tags
    reply = re.sub(r'<think>.*?</think>', '', reply, flags=re.DOTALL).strip()

    conversation_history[number].append({
        "role": "assistant",
        "content": reply
    })

    return reply


def send_message(number: str, text: str):
    url = f"{EVOLUTION_API}/message/sendText/{INSTANCE}"
    headers = {
        "apikey": API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "number": number,
        "text": text
    }
    requests.post(url, json=data, headers=headers)


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    try:
        message_data = payload["data"]["message"]

        if "conversation" in message_data:
            message = message_data["conversation"]
        elif "extendedTextMessage" in message_data:
            message = message_data["extendedTextMessage"]["text"]
        else:
            return {"ignored": True}

        number = payload["data"]["key"]["remoteJid"].split("@")[0]

        if payload["data"]["key"].get("fromMe", False):
            return {"ignored": True}

    except Exception as e:
        print(f"[ERROR] Parsing webhook: {e}")
        return {"ignored": True}

    try:
        reply = get_ai_reply(number, message)
    except Exception as e:
        print(f"[ERROR] get_ai_reply failed: {e}")
        reply = "Sorry, I'm having trouble right now. Please try again in a moment. 🙏"

    send_message(number, reply)
    return {"status": "sent"}


@app.get("/")
def root():
    return {"status": "IT Services WhatsApp Bot is running! 🚀"}
