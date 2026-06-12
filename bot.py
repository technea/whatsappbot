from fastapi import FastAPI, Request
import requests
import os
import re

app = FastAPI()

EVOLUTION_API = os.getenv("EVOLUTION_API_URL")
API_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE = os.getenv("INSTANCE_NAME")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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


# ---------------------------
# Provider functions
# ---------------------------

def try_gemini(history):
    if not GEMINI_API_KEY:
        raise Exception("No Gemini key")

    gemini_history = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append({"role": role, "parts": [{"text": msg["content"]}]})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": gemini_history
    }

    response = requests.post(url, json=payload, timeout=30)
    print(f"[DEBUG] Gemini status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"Gemini failed: {response.text[:200]}")

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def try_groq(history):
    if not GROQ_API_KEY:
        raise Exception("No Groq key")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "max_tokens": 500,
        "temperature": 0.7
    }

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers, json=payload, timeout=30
    )
    print(f"[DEBUG] Groq status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"Groq failed: {response.text[:200]}")

    return response.json()["choices"][0]["message"]["content"]


def try_openrouter(history):
    if not OPENROUTER_API_KEY:
        raise Exception("No OpenRouter key")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "max_tokens": 500
    }

    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers, json=payload, timeout=30
    )
    print(f"[DEBUG] OpenRouter status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"OpenRouter failed: {response.text[:200]}")

    return response.json()["choices"][0]["message"]["content"]


def try_deepseek(history):
    if not DEEPSEEK_API_KEY:
        raise Exception("No DeepSeek key")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "max_tokens": 500,
        "temperature": 0.7
    }

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers=headers, json=payload, timeout=30
    )
    print(f"[DEBUG] DeepSeek status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"DeepSeek failed: {response.text[:200]}")

    return response.json()["choices"][0]["message"]["content"]


# Order of providers to try (free ones first)
PROVIDERS = [
    ("Gemini", try_gemini),
    ("Groq", try_groq),
    ("OpenRouter", try_openrouter),
    ("DeepSeek", try_deepseek),
]


def get_ai_reply(number: str, user_message: str) -> str:
    if number not in conversation_history:
        conversation_history[number] = []

    conversation_history[number].append({
        "role": "user",
        "content": user_message
    })

    history = conversation_history[number][-10:]

    reply = None
    last_error = None

    for name, func in PROVIDERS:
        try:
            reply = func(history)
            print(f"[INFO] Reply generated using {name}")
            break
        except Exception as e:
            print(f"[WARN] {name} failed: {e}")
            last_error = e
            continue

    if reply is None:
        raise Exception(f"All providers failed. Last error: {last_error}")

    # Remove <think>...</think> tags if any
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
