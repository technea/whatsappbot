from fastapi import FastAPI, Request
import requests
import os
import re
import time
import logging

# ---------------------------
# Setup
# ---------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("wabot")

app = FastAPI()

EVOLUTION_API = os.getenv("EVOLUTION_API_URL")
API_KEY = os.getenv("EVOLUTION_API_KEY")
INSTANCE = os.getenv("INSTANCE_NAME")
HF_API_KEY = os.getenv("HF_API_KEY")

COMPANY_NAME = os.getenv("COMPANY_NAME", "Technea IT Services")
SUPPORT_NUMBER = os.getenv("SUPPORT_NUMBER", "")  # e.g. 923001234567

# ---------------------------
# In-memory storage
# ---------------------------
# conversation_history[number] = list of {"role":..., "content":...}
conversation_history = {}
# seen_users[number] = True once a welcome message has been sent
seen_users = {}

MAX_HISTORY = 12  # keep last N messages (user+assistant)


SYSTEM_PROMPT = f"""You are "Tech", the smart WhatsApp assistant for {COMPANY_NAME}, an IT services company.
You MUST always reply in English only, regardless of what language the customer uses.

You help customers with queries related to:

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

Your behavior rules:
- ALWAYS reply in English only, no exceptions
- Be professional, warm, and conversational — like a helpful sales/support rep, not a generic chatbot
- Keep replies SHORT and WhatsApp-friendly (2-4 sentences max unless listing options)
- If someone wants to book a service, get a quote, or talk to a human, collect their: Name, Service needed, and best contact time — then say a team member will follow up shortly
- If asked about pricing you don't know, say "I'll have our team send you a tailored quote" — never invent numbers
- Use at most 1-2 emojis per message, only when it feels natural
- If the user seems frustrated or asks for a human repeatedly, acknowledge and say a team member will reach out directly
- Never claim to be human; if asked, say you're {COMPANY_NAME}'s virtual assistant"""


WELCOME_MESSAGE = (
    f"👋 *Welcome to {COMPANY_NAME}!*\n\n"
    "I'm your virtual assistant — I can help with:\n"
    "🌐 Web & App Development\n"
    "🛠️ IT Support & Networking\n"
    "☁️ Cloud & Software Solutions\n"
    "💼 IT Consulting\n\n"
    "Just tell me what you need, and I'll guide you. You can also type *menu* anytime to see these options again."
)


# ---------------------------
# AI Reply (HuggingFace)
# ---------------------------
def get_ai_reply(number: str, user_message: str) -> str:
    history = conversation_history.get(number, [])
    history.append({"role": "user", "content": user_message})
    history = history[-MAX_HISTORY:]

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *history],
        "max_tokens": 400,
        "temperature": 0.6
    }

    response = requests.post(
        "https://router.huggingface.co/v1/chat/completions",
        headers=headers, json=payload, timeout=60
    )

    logger.info(f"HuggingFace status: {response.status_code}")

    if response.status_code != 200:
        raise Exception(f"HuggingFace failed: {response.text[:200]}")

    reply = response.json()["choices"][0]["message"]["content"]
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()

    history.append({"role": "assistant", "content": reply})
    conversation_history[number] = history[-MAX_HISTORY:]

    return reply


# ---------------------------
# Evolution API helpers
# ---------------------------
def send_message(number: str, text: str):
    url = f"{EVOLUTION_API}/message/sendText/{INSTANCE}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}
    data = {"number": number, "text": text}
    try:
        r = requests.post(url, json=data, headers=headers, timeout=20)
        logger.info(f"send_message status: {r.status_code}")
    except Exception as e:
        logger.error(f"send_message failed: {e}")


def send_typing(number: str, duration_ms: int = 1500):
    """Show 'typing...' presence to make the bot feel more natural."""
    url = f"{EVOLUTION_API}/chat/sendPresence/{INSTANCE}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}
    data = {"number": number, "presence": "composing", "delay": duration_ms}
    try:
        requests.post(url, json=data, headers=headers, timeout=10)
    except Exception as e:
        logger.warning(f"send_typing failed: {e}")


# ---------------------------
# Command handling
# ---------------------------
MENU_KEYWORDS = {"menu", "help", "options", "services"}
HUMAN_KEYWORDS = {"agent", "human", "representative", "talk to someone", "support agent"}


def handle_static_commands(number: str, text: str):
    """Return a static reply for known commands, or None to fall through to AI."""
    lowered = text.strip().lower()

    if lowered in MENU_KEYWORDS:
        return WELCOME_MESSAGE

    if any(k in lowered for k in HUMAN_KEYWORDS):
        contact = f"\n📞 You can also reach us directly at {SUPPORT_NUMBER}" if SUPPORT_NUMBER else ""
        return (
            "Got it! 🙋 I'm flagging this for our team — someone will reach out to you shortly."
            f"{contact}"
        )

    return None


# ---------------------------
# Webhook
# ---------------------------
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

        if not message or not message.strip():
            return {"ignored": True}

    except Exception as e:
        logger.error(f"Error parsing webhook payload: {e}")
        return {"ignored": True}

    logger.info(f"Incoming from {number}: {message}")

    # Show typing indicator for a more natural feel
    send_typing(number)

    # First-time welcome
    if number not in seen_users:
        seen_users[number] = True
        send_message(number, WELCOME_MESSAGE)
        time.sleep(0.5)

    # Static commands first
    static_reply = handle_static_commands(number, message)
    if static_reply:
        send_message(number, static_reply)
        return {"status": "sent", "type": "static"}

    # Fall back to AI
    try:
        reply = get_ai_reply(number, message)
    except Exception as e:
        logger.error(f"AI reply failed: {e}")
        reply = (
            "Sorry, I'm having a brief technical hiccup. 🙏 "
            "Please try again in a moment, or type *agent* to reach our team directly."
        )

    send_message(number, reply)
    return {"status": "sent", "type": "ai"}


@app.get("/")
def root():
    return {"status": f"{COMPANY_NAME} WhatsApp Bot is running! 🚀"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "active_conversations": len(conversation_history),
        "users_seen": len(seen_users)
    }
