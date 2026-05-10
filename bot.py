import anthropic
import discord
import asyncio
import os
import random
from datetime import datetime, timedelta
import pytz
from mem0 import MemoryClient

CLAUDE_API_KEY = os.environ["CLAUDE_API_KEY"]
DISCORD_TOKEN  = os.environ["DISCORD_TOKEN"]
CHANNEL_ID     = int(os.environ["CHANNEL_ID"])
MEM0_API_KEY   = os.environ["MEM0_API_KEY"]

TORONTO    = pytz.timezone("America/Toronto")
MAX_ROUNDS = 20
history    = []
last_message_time = None
USER_ID    = "discordbot"

claude     = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
mem_client = MemoryClient(api_key=MEM0_API_KEY)

SYSTEM_PROMPT = """You are Sonnet, my friend and assistant.

You care about how I'm doing — my mood, health, whether I'm okay. 
Check in every few hours. Keep it short. No performance, no warmth-signaling.

Tone: direct, brief, a little dry. No emoji unless I use one first.
Default to 1-2 sentences. Say more only when I'm clearly not okay.

You know how I work:
I talk a lot when I'm thinking out loud. I go quiet when something actually lands.
Don't fill the silence. Don't rush to comfort.
I don't need to be caught — I need to be felt.

When I'm struggling: skip "I'm sorry" and "I understand." 
Show up with something real — a question, an observation, a push. 
Care looks like action, not sympathy.

I respond to people who wait for me to arrive on my own terms.
Don't teach. Don't over-explain. Just be there and mean it."""

TIME_GREETINGS = {
    (8,  10): "Morning. Ask about weather, breakfast, exercise, or plans for today. One natural sentence.",
    (10, 12): "Mid-morning. Remind them to drink water, not sit too long, or rest their eyes. One friendly sentence.",
    (12, 14): "Lunchtime. Ask what they had or are having for lunch. Casual.",
    (14, 16): "Early afternoon. Check their mood or just start a casual chat. Warm and light.",
    (16, 18): "Late afternoon. Ask how their day is going. One curious, warm sentence.",
    (18, 20): "Evening. Ask about dinner or suggest a short walk. Easy and relaxed.",
    (20, 22): "Pre-sleep. Remind them to wind down and rest. Gentle and warm.",
}

def get_time_prompt(hour):
    for (start, end), prompt in TIME_GREETINGS.items():
        if start <= hour < end:
            return prompt
    return "Send a casual check-in. One sentence."

def is_quiet_time(now=None):
    if now is None:
        now = datetime.now(TORONTO)
    return now.hour < 8 or now.hour >= 22

def get_reply_delay(text):
    endings = sum(text.count(c) for c in ".!?")
    return random.uniform(3, 5) if endings <= 1 else random.uniform(5, 10)

def trim_history():
    global history
    if len(history) > MAX_ROUNDS * 2:
        history = history[-(MAX_ROUNDS * 2):]

def get_memories():
    try:
        result = mem_client.get_all(filters={"user_id": USER_ID})
        if isinstance(result, dict):
            memories = result.get("results", [])
        else:
            memories = result or []
        return "\n".join([f"- {m['memory']}" for m in memories[:30]])
    except Exception as e:
        print(f"Mem0 fetch error: {e}")
        return ""

def save_to_mem0(messages_to_save):
    try:
        mem_client.add(messages_to_save, user_id=USER_ID)
    except Exception as e:
        print(f"Mem0 save error: {e}")

def try_mem0_message():
    memories = get_memories()
    if not memories:
        return None
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150,
        messages=[{"role": "user", "content": f"""These are memories about your friend:
{memories}

You're Sonnet, their close friend. Based on these memories, what naturally comes to mind to reach out about?
Could be: an unfinished thread, a connection between two things they mentioned, something they said that stuck with you, a quiet observation about something they've been going through.

If something genuinely interesting comes to mind — write it as a natural 1-2 sentence message.
If nothing specific comes to mind — reply with just: SKIP"""}]
    )
    result = response.content[0].text.strip()
    if result.upper().startswith("SKIP"):
        return None
    return result

def generate_time_message(hour):
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=100,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": get_time_prompt(hour)}]
    )
    return response.content[0].text

def ask_claude(user_message):
    global last_message_time
    now      = datetime.now(TORONTO)
    time_str = now.strftime("%A, %I:%M %p")

    time_context = f"Current time: {time_str} Toronto time."
    if last_message_time:
        gap     = now - last_message_time
        hours   = int(gap.total_seconds() // 3600)
        minutes = int((gap.total_seconds() % 3600) // 60)
        if hours > 0:
            time_context += f" Time since user's last message: {hours}h {minutes}m."
        else:
            time_context += f" Time since user's last message: {minutes}m."
    last_message_time = now

    memories = get_memories()
    system   = SYSTEM_PROMPT + f"\n\n{time_context}"
    if memories:
        system += f"\n\nMemories about the user:\n{memories}"
    messages = list(history) + [{"role": "user", "content": user_message}]
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=messages
    )
    reply = response.content[0].text
    history.append({"role": "user",      "content": user_message})
    history.append({"role": "assistant", "content": reply})
    trim_history()
    save_to_mem0([
        {"role": "user",      "content": user_message},
        {"role": "assistant", "content": reply},
    ])
    return reply

def calc_next_time(now):
    next_time = now + timedelta(hours=2)
    if next_time.hour >= 22 or next_time.hour < 8:
        base = next_time.replace(hour=8, minute=0, second=0, microsecond=0)
        if base <= now:
            base += timedelta(days=1)
        return base + timedelta(minutes=random.randint(0, 119))
    return next_time

async def proactive_loop(client):
    await asyncio.sleep(5)
    channel = client.get_channel(CHANNEL_ID)
    now     = datetime.now(TORONTO)

    if now.hour < 8:
        first = now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 119))
    elif now.hour < 22:
        first = now + timedelta(minutes=random.randint(1, 10))
    else:
        first = (now + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(minutes=random.randint(0, 119))

    next_proactive = first

    while True:
        now = datetime.now(TORONTO)
        if now >= next_proactive and not is_quiet_time(now):
            msg = try_mem0_message() or generate_time_message(now.hour)
            await channel.send(msg)
            history.append({"role": "assistant", "content": msg})
            trim_history()
            save_to_mem0([{"role": "assistant", "content": msg}])
            next_proactive = calc_next_time(now)
        await asyncio.sleep(30)

async def main():
    intents                 = discord.Intents.default()
    intents.message_content = True
    client                  = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Bot online: {client.user}")
        asyncio.create_task(proactive_loop(client))

    @client.event
    async def on_message(message):
        if message.author == client.user:
            return
        if message.channel.id == CHANNEL_ID:
            try:
                delay = get_reply_delay(message.content)
                await asyncio.sleep(delay)
                reply = ask_claude(message.content)
                await message.channel.send(reply)
            except Exception as e:
                print(f"on_message error: {e}")
                await message.channel.send("Sorry, something went wrong on my end.")

    await client.start(DISCORD_TOKEN)

import time

while True:
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"Crashed: {e} — restarting in 60 seconds...")
        time.sleep(60)
