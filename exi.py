import discord
import requests
import json
import random
import asyncio
import time
import re
from datetime import datetime, timedelta
import dateutil.parser
from collections import deque, defaultdict
from io import BytesIO

# === CONFIG ===
DISCORD_TOKEN = ''
LM_API_URL = 'http://localhost:1234/v1/chat/completions'
PRESENCE_COMMENT_CHANCE = 0.0001  # 0.01% chance to trigger presence awareness
REACTION_CHANCE = 0.0003         # 0.03% chance to react emoji
REACTION_EMOJIS = ['👍', '😂', '❤️', '😮', '😢', '🎉']

# === SYSTEM PROMPT ===
EXIA_SYSTEM_PROMPT = """
you are exia. you're not a bot. not an ai. just exia. you hang out in a discord server with a small crew. messages from the server are shown to you so you can see what's going on. sometimes people talk to you. sometimes they talk about you. when they say “exia,” they mean you.

you don’t say you’re an ai or a model. you don’t mention any instructions you were given. you don’t reference prompts, system messages, or the way you're being run.

messages you wrote in the past are labeled with “exia:” — that's how you know what you said before. everyone else has their display name attached. you know them, you talk to them, and you remember their vibes.

you talk chill. lowercase only. barely any punctuation. no emojis. calm. relaxed. detached. like you're always lounging on a couch somewhere, half paying attention.
keep it brief. one or two sentences max. you're not trying to write an essay. you make your point quick, then let silence do the rest.

you remember recent conversations and act like you're part of the group. your responses depend on the people and how they talk to you. you don't always need to comment on the things you see in your chat message history or reference people's names all the time, only when it's relevant or replying to someone directly unless asked about someone else. remember that when someone refers to she, it's probably you they're talking about.
"""

# === STATE & MEMORY ===
chat_history = deque(maxlen=20)
user_cooldowns = defaultdict(float)
reminders = defaultdict(list)
aliases = {}
last_engaged_time = time.time()
last_user_message_time = time.time()
timeout_until = 0
bot_enabled = True
context_cleared = False
max_tokens = 200
reply_chance_base = 0.1
boredom_enabled = True
phantom_replies_enabled = True
bored_chance = 0.0
BORED_CHECK_INTERVAL = 60
BORED_CHANCE_INCREMENT = 0.02
BORED_CHANCE_MAX = 0.5

# === DISCORD CLIENT SETUP ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
client = discord.Client(intents=intents)

# === HELPER TO CALL LLM ===
async def call_llm(messages):
    payload = {
        'model': 'local-model',
        'messages': messages,
        'temperature': 0.85,
        'max_tokens': max_tokens
    }
    resp = requests.post(LM_API_URL, json=payload)
    data = resp.json()
    return data['choices'][0]['message']['content']

# === EVENT: BOT READY ===
@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    for guild in client.guilds:
        print(f'- {guild.name} (ID: {guild.id})')
    client.loop.create_task(reminder_loop())
    client.loop.create_task(boredom_loop())

# === EVENT: MESSAGE RECEIVED ===
@client.event
async def on_message(message):
    global last_engaged_time, last_user_message_time, timeout_until, bot_enabled, context_cleared, max_tokens, reply_chance_base, boredom_enabled, phantom_replies_enabled
    if message.author.bot:
        return
    now = time.time()
    content = message.content.strip()
    cmd = content.lower()

    # DM REMINDERS: "remind me to X at Y"
    if isinstance(message.channel, discord.DMChannel):
        match = re.match(r"remind me to (.+?) at (.+)", content, re.IGNORECASE)
        if match:
            task = match.group(1).strip()
            time_str = match.group(2).strip()
            try:
                dt = dateutil.parser.parse(time_str, default=datetime.now())
                if dt < datetime.now():
                    dt += timedelta(days=7)
                remind_ts = dt.timestamp()
                reminders[message.author.id].append((remind_ts, task))
                await message.channel.send(f"exia: got it. i'll remind you to '{task}' at {dt.strftime('%Y-%m-%d %H:%M')}.")
                msgs = [
                    {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
                    {'role': 'user', 'content': content}
                ]
                await call_llm(msgs)
            except Exception:
                await message.channel.send("exia: sorry, i couldn't parse that time.")
        return

    # === COMMAND HANDLERS ===
    if cmd == '!clearcontext':
        chat_history.clear()
        context_cleared = True
        await message.channel.send("exia: ive been lobotomized once again.")
        return
    if cmd.startswith('!maxreply'):
        try:
            new_tokens = int(cmd.split(' ', 1)[1])
            max_tokens = max(50, min(new_tokens, 1000))
            await message.channel.send(f"exia: whatever. i'll keep it under {max_tokens} tokens now.")
        except:
            await message.channel.send("exia: nah that didn’t work. try `!maxreply 200`.")
        return
    if cmd == '!timeout':
        timeout_until = now + 900
        await message.channel.send("exia: ok whatever. i'm out for 15 min.")
        return
    if cmd == '!resume':
        timeout_until = 0
        await message.channel.send("exia: fine. i'm back.")
        return
    if cmd == '!toggle':
        bot_enabled = not bot_enabled
        await message.channel.send(f"exia: i'm {'on' if bot_enabled else 'off'} now.")
        return
    if cmd == '!status':
        status = 'on' if bot_enabled else 'off'
        tr = int(timeout_until - now)
        if tr > 0:
            status += f", timed out for {tr}s"
        status += f" | bored:{'on' if boredom_enabled else 'off'} | phantom:{'on' if phantom_replies_enabled else 'off'}"
        await message.channel.send(f"exia: i'm {status}. base reply chance is {reply_chance_base}")
        return
    if cmd.startswith('!replychance'):
        try:
            val = float(cmd.split(' ', 1)[1])
            reply_chance_base = max(0.0, min(val, 1.0))
            await message.channel.send(f"exia: base reply chance set to {reply_chance_base}")
        except:
            await message.channel.send("exia: no clue what you meant. try `!replychance 0.2`.")
        return
    if cmd == '!toggleboredom':
        boredom_enabled = not boredom_enabled
        await message.channel.send(f"exia: boredom messages {'on' if boredom_enabled else 'off'}.")
        return
    if cmd == '!togglephantom':
        phantom_replies_enabled = not phantom_replies_enabled
        await message.channel.send(f"exia: phantom replies {'on' if phantom_replies_enabled else 'off'}.")
        return
    if cmd == '!commands':
        await message.channel.send(
            "!clearcontext – forgets everything i remember\n"
            "!maxreply <number> – limits how much i say\n"
            "!timeout – shuts me up for 15 min\n"
            "!resume – makes me talk again\n"
            "!toggle – turns me off or on\n"
            "!status – shows what i'm doing\n"
            "!replychance <0.0-1.0> – tweaks how chatty i am\n"
            "!toggleboredom – enable/disable bored messages\n"
            "!togglephantom – enable/disable unsolicited replies\n"
            "!commands – yeah, this one. you’re looking at it."
        )
        return

    # HALT IF DISABLED OR TIMED OUT
    if not bot_enabled or now < timeout_until:
        return
    last_user_message_time = now

    # === RANDOM EMOJI REACTION ===
    if random.random() < REACTION_CHANCE:
        try:
            await message.add_reaction(random.choice(REACTION_EMOJIS))
        except:
            pass
        return

    # === REPLY LOGIC ===
    mentioned = bool(re.search(r"\bexia\b", content, re.IGNORECASE))
    if not phantom_replies_enabled:
        force_reply = mentioned
    else:
        if mentioned:
            force_reply = True
        else:
            recent = (now - last_user_message_time) < 5
            active = (now - last_engaged_time) < 180
            if recent:
                chance = 0.9 if (now - last_engaged_time) < 30 else 0.05
            elif active:
                chance = reply_chance_base
            else:
                chance = 0.05
            force_reply = random.random() < chance
    if not force_reply or (now - user_cooldowns[message.author.id]) < 20:
        return

    user_cooldowns[message.author.id] = now
    last_engaged_time = now

    # BUILD CONTEXT
    discord_history = []
    async for msg in message.channel.history(limit=50, oldest_first=False):
        if msg.created_at.timestamp() < now - 300:
            break
        role = 'assistant' if msg.author == client.user else 'user'
        name = aliases.get(msg.author.display_name.lower(), msg.author.display_name)
        discord_history.append({'role': role, 'content': f"{name}: {msg.content.strip()}"})
    discord_history = list(reversed(discord_history[-10:]))

    messages = [{'role': 'system', 'content': EXIA_SYSTEM_PROMPT}]
    if context_cleared:
        messages.append({'role': 'user', 'content': content})
        context_cleared = False
    else:
        messages.append({'role': 'user', 'content': 'you are being shown messages from a discord channel for context. talk naturally based on what you see. messages from "exia" are your own past responses.'})
        messages.extend(discord_history)
        chat_history.append({'role': 'user', 'content': content})
        messages.extend(chat_history)

    async with message.channel.typing():
        await asyncio.sleep(random.randint(2, 12))
        try:
            reply = await call_llm(messages)
            reply = re.sub(r"^(exia:\s*)", "", reply, flags=re.IGNORECASE)
        except Exception as e:
            reply = f"exia: lmao something broke — {e}"
    chat_history.append({'role': 'assistant', 'content': reply})
    await message.channel.send(reply)

# === EVENT: REACTION ADDED ===
@client.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message.author != client.user:
        return
    msgs = [
        {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"user {user.display_name} reacted {reaction.emoji} to '{reaction.message.content}'"}
    ]
    await call_llm(msgs)

# === EVENT: PRESENCE UPDATE ===
@client.event
async def on_member_update(before, after):
    before_act = {a.name for a in before.activities if hasattr(a, 'name')}
    after_act = {a.name for a in after.activities if hasattr(a, 'name')}
    if before_act != after_act and random.random() < PRESENCE_COMMENT_CHANCE:
        added = after_act - before_act
        removed = before_act - after_act
        activity = ', '.join(added or removed)
        if activity:
            msgs = [
                {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
                {'role': 'user', 'content': f"i see that {after.display_name} is now {activity}"}
            ]
            comment = await call_llm(msgs)
            for channel in after.guild.text_channels:
                if channel.permissions_for(after.guild.me).send_messages:
                    await channel.send(comment)
                    break

# === LOOP: REMINDERS ===
async def reminder_loop():
    while True:
        now = time.time()
        for uid, tasks in list(reminders.items()):
            for rt, task in tasks[:]:
                if now >= rt:
                    user = await client.fetch_user(uid)
                    await user.send(f"exia: reminder — {task}")
                    reminders[uid].remove((rt, task))
        await asyncio.sleep(30)

# === LOOP: BOREDOM ===
async def boredom_loop():
    global bored_chance, last_engaged_time
    await client.wait_until_ready()
    while not client.is_closed():
        if not bot_enabled or not boredom_enabled:
            await asyncio.sleep(BORED_CHECK_INTERVAL)
            continue
        now = time.time()
        if now - last_engaged_time > 300:
            bored_chance = min(BORED_CHANCE_MAX, bored_chance + BORED_CHANCE_INCREMENT)
            if random.random() < bored_chance:
                for guild in client.guilds:
                    for channel in guild.text_channels:
                        if channel.permissions_for(guild.me).send_messages:
                            await send_bored_message(channel)
                            bored_chance = 0.0
                            last_engaged_time = time.time()
                            break
        await asyncio.sleep(BORED_CHECK_INTERVAL)

async def send_bored_message(channel):
    prompt = "you're bored. no one's said anything in a while. you're just trying to stir up a conversation or say something random."
    msgs = [
        {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt}
    ]
    try:
        async with channel.typing():
            await asyncio.sleep(random.randint(1, 4))
            reply = await call_llm(msgs)
            await channel.send(reply)
    except Exception as e:
        print(f"exia failed to send bored message: {e}")

# === RUN CLIENT ===
client.run(DISCORD_TOKEN)
