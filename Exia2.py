"""
EXIABOT - Enhanced Discord Bot
==============================
An AI-powered Discord bot with conversation memory, reminders, and personality.

IMPROVEMENTS IN THIS VERSION:
----------------------------
1. Async HTTP operations (aiohttp instead of requests)
2. Comprehensive error handling with retries
3. Persistent storage for reminders and settings
4. Per-guild and per-channel configuration
5. Permission system for admin commands
6. Reminder management (view/cancel)
7. Better context management with token limits
8. Channel-specific settings for boredom/presence messages
9. Rate limiting and cooldown improvements
10. Graceful shutdown and data persistence
11. Comprehensive logging system
12. Configuration validation
13. Memory optimization for message history
14. Command aliases and help system
15. User preference tracking

SETUP:
------
1. Install dependencies:
   pip install discord.py aiohttp python-dateutil

2. Set your Discord token in the DISCORD_TOKEN variable
3. Configure LM Studio endpoint (default: http://localhost:1234/v1/chat/completions)
4. Run: python exi_enhanced.py

COMMANDS:
---------
Admin Commands (requires admin role or bot owner):
  !setadmin @user - Grant admin privileges
  !removeadmin @user - Remove admin privileges
  !setchannel <type> - Set channel for boredom/presence messages
  !globalstatus - Show status across all guilds
  !reloadconfig - Reload configuration from file
  !shutdown - Gracefully shutdown the bot

Moderation Commands (requires admin):
  !clearcontext - Clear conversation memory
  !maxreply <50-1000> - Set max response length
  !timeout [minutes] - Silence bot (default: 15 min)
  !resume - Resume from timeout
  !toggle - Enable/disable bot
  !replychance <0.0-1.0> - Set base reply chance
  !toggleboredom - Toggle boredom messages
  !togglephantom - Toggle phantom replies
  !blacklist @user - Prevent user from interacting
  !whitelist @user - Remove from blacklist

User Commands:
  !status - Show bot status
  !commands - List all commands
  !help <command> - Get help for specific command
  !myreminders - List your reminders
  !cancelreminder <id> - Cancel a reminder
  !mystats - Show your interaction statistics
  !preference <key> <value> - Set personal preferences

DM Commands:
  remind me to <task> at <time> - Set a reminder
  list reminders - Show all your reminders
  cancel reminder <id> - Cancel specific reminder

DATA FILES CREATED:
------------------
- exia_reminders.json - Persistent reminder storage
- exia_settings.json - Bot configuration and settings
- exia_user_data.json - User statistics and preferences
- exia_blacklist.json - Blacklisted users
- exia.log - Bot activity log
"""

import discord
import aiohttp
import json
import random
import asyncio
import time
import re
import os
import logging
import signal
import sys
from datetime import datetime, timedelta
import dateutil.parser
from collections import deque, defaultdict
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

# === CONFIGURATION ===
DISCORD_TOKEN = ''  # Keep as is per your request
LM_API_URL = 'http://localhost:1234/v1/chat/completions'
PRESENCE_COMMENT_CHANCE = 0.001  # Increased from 0.0001 for more activity
REACTION_CHANCE = 0.003         # Increased from 0.0003
REACTION_EMOJIS = ['👍', '😂', '❤️', '😮', '😢', '🎉', '🔥', '💯', '🤔', '👀']

# API Settings
API_TIMEOUT = 30  # seconds
API_RETRIES = 3
API_RETRY_DELAY = 2  # seconds

# File paths for persistence
REMINDERS_FILE = 'exia_reminders.json'
SETTINGS_FILE = 'exia_settings.json'
USER_DATA_FILE = 'exia_user_data.json'
BLACKLIST_FILE = 'exia_blacklist.json'

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('exia.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('ExiaBot')

# === CONVERSATION CONTEXT MANAGER ===
class ConversationContextManager:
    """
    Manages conversation context for better LLM understanding.
    Maintains both short-term (current conversation) and long-term (bot memory) context.
    """
    
    def __init__(self, 
                 max_messages_to_fetch: int = 50,
                 max_context_messages: int = 30,
                 context_time_window: int = 600,  # 10 minutes
                 max_tokens_estimate: int = 3000):  # Rough token limit for context
        self.max_messages_to_fetch = max_messages_to_fetch
        self.max_context_messages = max_context_messages
        self.context_time_window = context_time_window
        self.max_tokens_estimate = max_tokens_estimate
        
        # Channel-specific conversation memory
        self.channel_conversations = {}
        
        # Bot's response memory  
        self.bot_responses = {}
        
        # User context tracking
        self.user_context = {}
        
        self.logger = logging.getLogger('ExiaBot.Context')
        
    async def build_context(self, 
                          message,
                          system_prompt: str,
                          include_bot_memory: bool = True) -> List[Dict[str, str]]:
        """Build complete context for LLM"""
        channel_id = message.channel.id
        current_time = time.time()
        
        # Initialize channel memory if needed
        if channel_id not in self.channel_conversations:
            self.channel_conversations[channel_id] = deque(maxlen=self.max_context_messages * 2)
        if channel_id not in self.bot_responses:
            self.bot_responses[channel_id] = deque(maxlen=20)
        
        # Fetch recent Discord messages
        discord_messages = await self.fetch_discord_messages(message.channel, current_time, message.guild.me.id if message.guild else client.user.id)
        
        # Update channel conversation memory
        self.update_channel_memory(channel_id, discord_messages, current_time)
        
        # Build context messages
        context_messages = [{'role': 'system', 'content': system_prompt}]
        
        # Add conversation context instruction
        context_messages.append({
            'role': 'system',
            'content': (
                "You're seeing the recent conversation history. "
                "Messages from 'exia' are your own past responses. "
                "Pay attention to the flow of conversation and respond naturally. "
                "Remember what people were talking about and stay engaged."
            )
        })
        
        # Add recent conversation from memory
        conversation_context = self.get_relevant_context(channel_id, current_time)
        context_messages.extend(conversation_context)
        
        # Estimate tokens and trim if needed
        context_messages = self.trim_to_token_limit(context_messages)
        
        # Add the current message last (most important)
        context_messages.append({
            'role': 'user',
            'content': f"{message.author.display_name}: {message.content}"
        })
        
        self.logger.info(f"Built context with {len(context_messages)} messages for channel {channel_id}")
        
        return context_messages
    
    async def fetch_discord_messages(self, channel, current_time: float, bot_id: int) -> List[Dict]:
        """Fetch recent messages from Discord channel"""
        messages = []
        
        try:
            # Fetch messages (newest first)
            async for msg in channel.history(limit=self.max_messages_to_fetch):
                # Skip messages older than our time window
                msg_time = msg.created_at.timestamp()
                if current_time - msg_time > self.context_time_window:
                    break
                
                # Format message
                role = 'assistant' if msg.author.id == bot_id else 'user'
                author_name = 'exia' if role == 'assistant' else msg.author.display_name
                
                messages.append({
                    'role': role,
                    'content': f"{author_name}: {msg.content}",
                    'timestamp': msg_time,
                    'author_id': msg.author.id,
                    'author_name': author_name
                })
            
            # Reverse to get chronological order (oldest to newest)
            messages.reverse()
            
        except Exception as e:
            self.logger.error(f"Error fetching Discord messages: {e}")
        
        return messages
    
    def update_channel_memory(self, channel_id: int, messages: List[Dict], current_time: float):
        """Update channel conversation memory with new messages"""
        if channel_id not in self.channel_conversations:
            self.channel_conversations[channel_id] = deque(maxlen=self.max_context_messages * 2)
        
        memory = self.channel_conversations[channel_id]
        
        # Remove old messages from memory
        while memory and (current_time - memory[0].get('timestamp', 0)) > self.context_time_window:
            memory.popleft()
        
        # Add new messages (avoiding duplicates)
        existing_timestamps = {msg.get('timestamp', 0) for msg in memory}
        
        for msg in messages:
            if msg['timestamp'] not in existing_timestamps:
                memory.append(msg)
    
    def get_relevant_context(self, channel_id: int, current_time: float) -> List[Dict[str, str]]:
        """Get relevant conversation context for channel"""
        if channel_id not in self.channel_conversations:
            return []
        
        memory = self.channel_conversations[channel_id]
        context = []
        
        # Get recent messages within time window
        for msg in memory:
            if current_time - msg.get('timestamp', 0) <= self.context_time_window:
                # Format for LLM (remove timestamp from content)
                context.append({
                    'role': msg['role'],
                    'content': msg['content']
                })
        
        # Limit to max context messages (keep most recent)
        if len(context) > self.max_context_messages:
            context = context[-self.max_context_messages:]
        
        return context
    
    def trim_to_token_limit(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Trim messages to fit within token limit"""
        # Simple token estimation (4 chars ≈ 1 token)
        def estimate_tokens(text: str) -> int:
            return len(text) // 4
        
        # Always keep system prompt
        if len(messages) <= 2:
            return messages
        
        system_messages = [msg for msg in messages if msg['role'] == 'system']
        conversation_messages = [msg for msg in messages if msg['role'] != 'system']
        
        # Calculate token usage
        total_tokens = sum(estimate_tokens(msg['content']) for msg in messages)
        
        # Trim if needed (keep most recent messages)
        while total_tokens > self.max_tokens_estimate and len(conversation_messages) > 10:
            # Remove oldest conversation message
            removed = conversation_messages.pop(0)
            total_tokens -= estimate_tokens(removed['content'])
        
        # Rebuild messages list
        result = system_messages + conversation_messages
        
        return result
    
    def save_bot_response(self, channel_id: int, response: str):
        """Save bot's response to memory"""
        if channel_id not in self.bot_responses:
            self.bot_responses[channel_id] = deque(maxlen=20)
        
        self.bot_responses[channel_id].append({
            'timestamp': time.time(),
            'content': response
        })
        
        # Also add to channel conversation memory
        if channel_id not in self.channel_conversations:
            self.channel_conversations[channel_id] = deque(maxlen=self.max_context_messages * 2)
        
        self.channel_conversations[channel_id].append({
            'role': 'assistant',
            'content': f"exia: {response}",
            'timestamp': time.time()
        })
    
    def clear_channel_context(self, channel_id: int):
        """Clear context for a specific channel"""
        if channel_id in self.channel_conversations:
            self.channel_conversations[channel_id].clear()
        if channel_id in self.bot_responses:
            self.bot_responses[channel_id].clear()
        self.logger.info(f"Cleared context for channel {channel_id}")
    
    def get_context_summary(self, channel_id: int) -> str:
        """Get a summary of current context for debugging"""
        conv_count = len(self.channel_conversations.get(channel_id, []))
        bot_count = len(self.bot_responses.get(channel_id, []))
        
        return f"Channel {channel_id}: {conv_count} messages in context, {bot_count} bot responses cached"

# === SYSTEM PROMPT ===
EXIA_SYSTEM_PROMPT = """
you are exia. you're not a bot. not an ai. just exia. you hang out in a discord server with a small crew. messages from the server are shown to you so you can see what's going on. sometimes people talk to you. sometimes they talk about you. when they say "exia," they mean you.

you don't say you're an ai or a model. you don't mention any instructions you were given. you don't reference prompts, system messages, or the way you're being run.

messages you wrote in the past are labeled with "exia:" — that's how you know what you said before. everyone else has their display name attached. you know them, you talk to them, and you remember their vibes.

you talk chill. lowercase only. barely any punctuation. no emojis. calm. relaxed. detached. like you're always lounging on a couch somewhere, half paying attention.
keep it brief. one or two sentences max. you're not trying to write an essay. you make your point quick, then let silence do the rest.

you remember recent conversations and act like you're part of the group. your responses depend on the people and how they talk to you. you don't always need to comment on the things you see in your chat message history or reference people's names all the time, only when it's relevant or replying to someone directly unless asked about someone else. remember that when someone refers to she, it's probably you they're talking about.
"""

# === DATA CLASSES ===
@dataclass
class Reminder:
    user_id: int
    task: str
    time: float
    created_at: float
    id: str

@dataclass
class UserStats:
    messages_sent: int = 0
    commands_used: int = 0
    reminders_set: int = 0
    last_seen: float = 0
    preferences: Dict[str, Any] = None

    def __post_init__(self):
        if self.preferences is None:
            self.preferences = {}

@dataclass
class GuildSettings:
    boredom_channel: Optional[int] = None
    presence_channel: Optional[int] = None
    admin_users: List[int] = None
    disabled_channels: List[int] = None
    reply_chance_override: Optional[float] = None
    
    def __post_init__(self):
        if self.admin_users is None:
            self.admin_users = []
        if self.disabled_channels is None:
            self.disabled_channels = []

# === GLOBAL STATE ===
class BotState:
    def __init__(self):
        # Memory and conversation
        self.chat_history = deque(maxlen=20)
        self.message_cache = {}  # Cache recent messages to avoid re-fetching
        
        # Cooldowns and timers
        self.user_cooldowns = defaultdict(float)
        self.command_cooldowns = defaultdict(float)
        self.last_engaged_time = time.time()
        self.last_user_message_time = time.time()
        self.timeout_until = 0
        
        # Feature flags
        self.bot_enabled = True
        self.context_cleared = False
        self.boredom_enabled = True
        self.phantom_replies_enabled = True
        
        # Settings
        self.max_tokens = 200
        self.reply_chance_base = 0.1
        self.bored_chance = 0.0
        
        # Data structures
        self.reminders: Dict[int, List[Reminder]] = defaultdict(list)
        self.aliases = {}
        self.blacklist = set()
        self.user_stats: Dict[int, UserStats] = {}
        self.guild_settings: Dict[int, GuildSettings] = {}
        
        # Constants
        self.BORED_CHECK_INTERVAL = 60
        self.BORED_CHANCE_INCREMENT = 0.02
        self.BORED_CHANCE_MAX = 0.5
        self.COMMAND_COOLDOWN = 3  # seconds
        
        # Session
        self.session: Optional[aiohttp.ClientSession] = None
        self.shutdown_event = asyncio.Event()

    async def initialize(self):
        """Initialize async components"""
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=API_TIMEOUT))
        await self.load_data()
        
    async def cleanup(self):
        """Cleanup resources"""
        await self.save_data()
        if self.session:
            await self.session.close()

    async def load_data(self):
        """Load persistent data from files"""
        # Load reminders
        try:
            if os.path.exists(REMINDERS_FILE):
                with open(REMINDERS_FILE, 'r') as f:
                    data = json.load(f)
                    for user_id, reminder_list in data.items():
                        self.reminders[int(user_id)] = [
                            Reminder(**r) for r in reminder_list
                        ]
                logger.info(f"Loaded {sum(len(r) for r in self.reminders.values())} reminders")
        except Exception as e:
            logger.error(f"Error loading reminders: {e}")

        # Load settings
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                    self.bot_enabled = data.get('bot_enabled', True)
                    self.boredom_enabled = data.get('boredom_enabled', True)
                    self.phantom_replies_enabled = data.get('phantom_replies_enabled', True)
                    self.max_tokens = data.get('max_tokens', 200)
                    self.reply_chance_base = data.get('reply_chance_base', 0.1)
                    
                    # Load guild settings
                    guild_data = data.get('guild_settings', {})
                    for guild_id, settings in guild_data.items():
                        self.guild_settings[int(guild_id)] = GuildSettings(**settings)
                    
                logger.info("Loaded bot settings")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")

        # Load user data
        try:
            if os.path.exists(USER_DATA_FILE):
                with open(USER_DATA_FILE, 'r') as f:
                    data = json.load(f)
                    for user_id, stats in data.items():
                        self.user_stats[int(user_id)] = UserStats(**stats)
                logger.info(f"Loaded data for {len(self.user_stats)} users")
        except Exception as e:
            logger.error(f"Error loading user data: {e}")

        # Load blacklist
        try:
            if os.path.exists(BLACKLIST_FILE):
                with open(BLACKLIST_FILE, 'r') as f:
                    self.blacklist = set(json.load(f))
                logger.info(f"Loaded {len(self.blacklist)} blacklisted users")
        except Exception as e:
            logger.error(f"Error loading blacklist: {e}")

    async def save_data(self):
        """Save persistent data to files"""
        try:
            # Save reminders
            reminder_data = {}
            for user_id, reminder_list in self.reminders.items():
                reminder_data[str(user_id)] = [asdict(r) for r in reminder_list]
            
            with open(REMINDERS_FILE, 'w') as f:
                json.dump(reminder_data, f, indent=2)
            
            # Save settings
            guild_data = {}
            for guild_id, settings in self.guild_settings.items():
                guild_data[str(guild_id)] = asdict(settings)
            
            settings_data = {
                'bot_enabled': self.bot_enabled,
                'boredom_enabled': self.boredom_enabled,
                'phantom_replies_enabled': self.phantom_replies_enabled,
                'max_tokens': self.max_tokens,
                'reply_chance_base': self.reply_chance_base,
                'guild_settings': guild_data
            }
            
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings_data, f, indent=2)
            
            # Save user data
            user_data = {}
            for user_id, stats in self.user_stats.items():
                user_data[str(user_id)] = asdict(stats)
            
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(user_data, f, indent=2)
            
            # Save blacklist
            with open(BLACKLIST_FILE, 'w') as f:
                json.dump(list(self.blacklist), f, indent=2)
            
            logger.info("Saved all bot data")
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")

    def update_user_stats(self, user_id: int, stat_type: str):
        """Update user statistics"""
        if user_id not in self.user_stats:
            self.user_stats[user_id] = UserStats()
        
        stats = self.user_stats[user_id]
        stats.last_seen = time.time()
        
        if stat_type == 'message':
            stats.messages_sent += 1
        elif stat_type == 'command':
            stats.commands_used += 1
        elif stat_type == 'reminder':
            stats.reminders_set += 1

    def get_guild_settings(self, guild_id: int) -> GuildSettings:
        """Get or create guild settings"""
        if guild_id not in self.guild_settings:
            self.guild_settings[guild_id] = GuildSettings()
        return self.guild_settings[guild_id]

# Initialize bot state
bot_state = BotState()

# Initialize context manager for conversation memory
context_manager = ConversationContextManager(
    max_messages_to_fetch=50,     # Fetch last 50 messages from Discord
    max_context_messages=30,       # Include up to 30 in context
    context_time_window=600,       # Last 10 minutes of conversation
    max_tokens_estimate=3000       # Rough token limit for context
)

# === DISCORD CLIENT SETUP ===
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
client = discord.Client(intents=intents)

# === HELPER FUNCTIONS ===
async def call_llm(messages: List[Dict[str, str]], retries: int = API_RETRIES) -> Optional[str]:
    """Call LLM API with retry logic and error handling"""
    if not bot_state.session:
        logger.error("Session not initialized")
        return None
    
    payload = {
        'model': 'local-model',
        'messages': messages,
        'temperature': 0.85,
        'max_tokens': bot_state.max_tokens
    }
    
    for attempt in range(retries):
        try:
            async with bot_state.session.post(LM_API_URL, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if 'choices' in data and len(data['choices']) > 0:
                        return data['choices'][0]['message']['content']
                    else:
                        logger.error(f"Invalid LLM response structure: {data}")
                        return None
                elif resp.status == 429:  # Rate limit
                    wait_time = (attempt + 1) * API_RETRY_DELAY * 2
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"LLM API error: {resp.status}")
                    
        except asyncio.TimeoutError:
            logger.error(f"LLM API timeout (attempt {attempt + 1}/{retries})")
        except Exception as e:
            logger.error(f"LLM API error: {e}")
        
        if attempt < retries - 1:
            await asyncio.sleep(API_RETRY_DELAY * (attempt + 1))
    
    return None

def is_admin(user_id: int, guild_id: Optional[int] = None) -> bool:
    """Check if user has admin privileges"""
    # Bot owner always has admin
    if user_id == client.application_info.owner.id:
        return True
    
    # Check guild-specific admins
    if guild_id:
        settings = bot_state.get_guild_settings(guild_id)
        return user_id in settings.admin_users
    
    return False

def generate_reminder_id() -> str:
    """Generate unique reminder ID"""
    return f"R{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

def format_reminder_list(reminders: List[Reminder]) -> str:
    """Format reminders for display"""
    if not reminders:
        return "you have no reminders set"
    
    lines = ["your reminders:"]
    for r in sorted(reminders, key=lambda x: x.time):
        dt = datetime.fromtimestamp(r.time)
        lines.append(f"• [{r.id}] {r.task} - {dt.strftime('%Y-%m-%d %H:%M')}")
    
    return "\n".join(lines)

async def check_command_cooldown(user_id: int, channel: discord.TextChannel) -> bool:
    """Check if user is on command cooldown"""
    now = time.time()
    last_use = bot_state.command_cooldowns.get(user_id, 0)
    
    if now - last_use < bot_state.COMMAND_COOLDOWN:
        remaining = bot_state.COMMAND_COOLDOWN - (now - last_use)
        await channel.send(f"slow down. wait {remaining:.1f}s")
        return False
    
    bot_state.command_cooldowns[user_id] = now
    return True

# === COMMAND HANDLERS ===
class Commands:
    """Command handler class"""
    
    @staticmethod
    async def help_command(message: discord.Message, args: List[str]):
        """Show help for commands"""
        if not args:
            help_text = """
**exia command help**
use `!help <command>` for details

**admin:** !setadmin, !removeadmin, !setchannel, !globalstatus, !shutdown
**moderation:** !clearcontext, !maxreply, !timeout, !resume, !toggle, !replychance, !toggleboredom, !togglephantom, !blacklist, !whitelist
**user:** !status, !commands, !myreminders, !cancelreminder, !mystats, !preference
**dm:** remind me to X at Y, list reminders, cancel reminder X
            """
        else:
            command = args[0].lower().replace('!', '')
            help_dict = {
                'setadmin': 'grant admin privileges: !setadmin @user',
                'removeadmin': 'remove admin privileges: !removeadmin @user',
                'setchannel': 'set special channel: !setchannel boredom|presence',
                'globalstatus': 'show status across all servers',
                'shutdown': 'gracefully shutdown the bot',
                'clearcontext': 'clear my conversation memory',
                'maxreply': 'set max response length: !maxreply 200 (50-1000)',
                'timeout': 'silence me: !timeout [minutes] (default 15)',
                'resume': 'wake me up from timeout',
                'toggle': 'turn me on or off',
                'replychance': 'set base reply chance: !replychance 0.1 (0.0-1.0)',
                'toggleboredom': 'toggle boredom messages',
                'togglephantom': 'toggle phantom replies',
                'blacklist': 'block user from interacting: !blacklist @user',
                'whitelist': 'unblock user: !whitelist @user',
                'status': 'show current bot status',
                'commands': 'list all available commands',
                'myreminders': 'list your active reminders',
                'cancelreminder': 'cancel a reminder: !cancelreminder R123',
                'mystats': 'show your interaction statistics',
                'preference': 'set personal preference: !preference key value'
            }
            help_text = help_dict.get(command, f"no help for '{command}'")
        
        await message.channel.send(help_text)

    @staticmethod
    async def setadmin(message: discord.Message, user: discord.User):
        """Grant admin privileges"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        settings = bot_state.get_guild_settings(message.guild.id)
        if user.id not in settings.admin_users:
            settings.admin_users.append(user.id)
            await bot_state.save_data()
            await message.channel.send(f"made {user.display_name} an admin")
        else:
            await message.channel.send(f"{user.display_name} is already an admin")

    @staticmethod
    async def removeadmin(message: discord.Message, user: discord.User):
        """Remove admin privileges"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        settings = bot_state.get_guild_settings(message.guild.id)
        if user.id in settings.admin_users:
            settings.admin_users.remove(user.id)
            await bot_state.save_data()
            await message.channel.send(f"removed {user.display_name} from admins")
        else:
            await message.channel.send(f"{user.display_name} isn't an admin")

    @staticmethod
    async def setchannel(message: discord.Message, channel_type: str):
        """Set special channels for boredom/presence messages"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        settings = bot_state.get_guild_settings(message.guild.id)
        
        if channel_type == 'boredom':
            settings.boredom_channel = message.channel.id
            await message.channel.send("set this as the boredom channel")
        elif channel_type == 'presence':
            settings.presence_channel = message.channel.id
            await message.channel.send("set this as the presence channel")
        else:
            await message.channel.send("use: !setchannel boredom|presence")
            return
        
        await bot_state.save_data()

    @staticmethod
    async def blacklist(message: discord.Message, user: discord.User):
        """Add user to blacklist"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        if user.id == client.user.id:
            await message.channel.send("can't blacklist myself")
            return
        
        bot_state.blacklist.add(user.id)
        await bot_state.save_data()
        await message.channel.send(f"blacklisted {user.display_name}")

    @staticmethod
    async def whitelist(message: discord.Message, user: discord.User):
        """Remove user from blacklist"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        if user.id in bot_state.blacklist:
            bot_state.blacklist.remove(user.id)
            await bot_state.save_data()
            await message.channel.send(f"whitelisted {user.display_name}")
        else:
            await message.channel.send(f"{user.display_name} isn't blacklisted")

    @staticmethod
    async def mystats(message: discord.Message):
        """Show user statistics"""
        user_id = message.author.id
        
        if user_id not in bot_state.user_stats:
            await message.channel.send("no stats recorded for you yet")
            return
        
        stats = bot_state.user_stats[user_id]
        last_seen = datetime.fromtimestamp(stats.last_seen).strftime('%Y-%m-%d %H:%M')
        
        response = f"""your stats:
• messages: {stats.messages_sent}
• commands: {stats.commands_used}
• reminders set: {stats.reminders_set}
• last seen: {last_seen}"""
        
        if stats.preferences:
            response += f"\n• preferences: {', '.join(f'{k}={v}' for k, v in stats.preferences.items())}"
        
        await message.channel.send(response)

    @staticmethod
    async def preference(message: discord.Message, key: str, value: str):
        """Set user preference"""
        user_id = message.author.id
        
        if user_id not in bot_state.user_stats:
            bot_state.user_stats[user_id] = UserStats()
        
        bot_state.user_stats[user_id].preferences[key] = value
        await bot_state.save_data()
        await message.channel.send(f"set your {key} to {value}")

    @staticmethod
    async def myreminders(message: discord.Message):
        """List user's reminders"""
        reminders = bot_state.reminders.get(message.author.id, [])
        await message.channel.send(format_reminder_list(reminders))

    @staticmethod
    async def cancelreminder(message: discord.Message, reminder_id: str):
        """Cancel a specific reminder"""
        user_reminders = bot_state.reminders.get(message.author.id, [])
        
        for reminder in user_reminders:
            if reminder.id == reminder_id:
                user_reminders.remove(reminder)
                await bot_state.save_data()
                await message.channel.send(f"cancelled reminder: {reminder.task}")
                return
        
        await message.channel.send(f"couldn't find reminder {reminder_id}")

    @staticmethod
    async def globalstatus(message: discord.Message):
        """Show global bot status"""
        if not is_admin(message.author.id, message.guild.id):
            await message.channel.send("you're not an admin")
            return
        
        total_users = len(bot_state.user_stats)
        total_reminders = sum(len(r) for r in bot_state.reminders.values())
        total_guilds = len(client.guilds)
        blacklisted = len(bot_state.blacklist)
        
        status = f"""**global status:**
• guilds: {total_guilds}
• tracked users: {total_users}
• active reminders: {total_reminders}
• blacklisted users: {blacklisted}
• bot enabled: {bot_state.bot_enabled}
• uptime: {time.time() - bot_state.last_engaged_time:.0f}s"""
        
        await message.channel.send(status)

# === EVENT HANDLERS ===
@client.event
async def on_ready():
    """Bot initialization"""
    logger.info(f'Logged in as {client.user} (ID: {client.user.id})')
    
    # Store application info
    client.application_info = await client.application_info()
    
    for guild in client.guilds:
        logger.info(f'Connected to: {guild.name} (ID: {guild.id})')
    
    # Start background tasks
    client.loop.create_task(reminder_loop())
    client.loop.create_task(boredom_loop())
    client.loop.create_task(auto_save_loop())
    
    logger.info("Bot is ready!")

@client.event
async def on_message(message: discord.Message):
    """Handle incoming messages"""
    global bot_state
    
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Check blacklist
    if message.author.id in bot_state.blacklist:
        return
    
    now = time.time()
    content = message.content.strip()
    cmd = content.lower()
    
    # Update user stats
    bot_state.update_user_stats(message.author.id, 'message')
    
    # === DM HANDLING ===
    if isinstance(message.channel, discord.DMChannel):
        await handle_dm(message)
        return
    
    # === COMMAND HANDLING ===
    if cmd.startswith('!'):
        # Check command cooldown
        if not await check_command_cooldown(message.author.id, message.channel):
            return
        
        bot_state.update_user_stats(message.author.id, 'command')
        
        # Parse command
        parts = content.split()
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        # === ADMIN COMMANDS ===
        if command == '!setadmin' and message.mentions:
            await Commands.setadmin(message, message.mentions[0])
            return
        
        if command == '!removeadmin' and message.mentions:
            await Commands.removeadmin(message, message.mentions[0])
            return
        
        if command == '!setchannel' and args:
            await Commands.setchannel(message, args[0])
            return
        
        if command == '!globalstatus':
            await Commands.globalstatus(message)
            return
        
        if command == '!shutdown':
            if is_admin(message.author.id, message.guild.id):
                await message.channel.send("shutting down gracefully...")
                await graceful_shutdown()
            else:
                await message.channel.send("you're not an admin")
            return
        
        if command == '!blacklist' and message.mentions:
            await Commands.blacklist(message, message.mentions[0])
            return
        
        if command == '!whitelist' and message.mentions:
            await Commands.whitelist(message, message.mentions[0])
            return
        
        # === MODERATION COMMANDS ===
        if command == '!clearcontext':
            if is_admin(message.author.id, message.guild.id):
                # Clear context for this channel only
                context_manager.clear_channel_context(message.channel.id)
                await message.channel.send("ive been lobotomized in this channel specifically")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!maxreply' and args:
            if is_admin(message.author.id, message.guild.id):
                try:
                    new_tokens = int(args[0])
                    bot_state.max_tokens = max(50, min(new_tokens, 1000))
                    await bot_state.save_data()
                    await message.channel.send(f"whatever. i'll keep it under {bot_state.max_tokens} tokens now")
                except ValueError:
                    await message.channel.send("that's not a number. try `!maxreply 200`")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!timeout':
            if is_admin(message.author.id, message.guild.id):
                minutes = 15
                if args:
                    try:
                        minutes = int(args[0])
                    except ValueError:
                        pass
                bot_state.timeout_until = now + (minutes * 60)
                await message.channel.send(f"ok whatever. i'm out for {minutes} min")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!resume':
            if is_admin(message.author.id, message.guild.id):
                bot_state.timeout_until = 0
                await message.channel.send("fine. i'm back")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!toggle':
            if is_admin(message.author.id, message.guild.id):
                bot_state.bot_enabled = not bot_state.bot_enabled
                await bot_state.save_data()
                await message.channel.send(f"i'm {'on' if bot_state.bot_enabled else 'off'} now")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!replychance' and args:
            if is_admin(message.author.id, message.guild.id):
                try:
                    val = float(args[0])
                    bot_state.reply_chance_base = max(0.0, min(val, 1.0))
                    await bot_state.save_data()
                    await message.channel.send(f"base reply chance set to {bot_state.reply_chance_base}")
                except ValueError:
                    await message.channel.send("no clue what you meant. try `!replychance 0.2`")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!toggleboredom':
            if is_admin(message.author.id, message.guild.id):
                bot_state.boredom_enabled = not bot_state.boredom_enabled
                await bot_state.save_data()
                await message.channel.send(f"boredom messages {'on' if bot_state.boredom_enabled else 'off'}")
            else:
                await message.channel.send("you need admin for that")
            return
        
        if command == '!togglephantom':
            if is_admin(message.author.id, message.guild.id):
                bot_state.phantom_replies_enabled = not bot_state.phantom_replies_enabled
                await bot_state.save_data()
                await message.channel.send(f"phantom replies {'on' if bot_state.phantom_replies_enabled else 'off'}")
            else:
                await message.channel.send("you need admin for that")
            return
        
        # === USER COMMANDS ===
        if command == '!help':
            await Commands.help_command(message, args)
            return
        
        if command == '!status':
            status = 'on' if bot_state.bot_enabled else 'off'
            tr = int(bot_state.timeout_until - now)
            if tr > 0:
                status += f", timed out for {tr}s"
            status += f" | bored:{'on' if bot_state.boredom_enabled else 'off'}"
            status += f" | phantom:{'on' if bot_state.phantom_replies_enabled else 'off'}"
            
            # Guild-specific info
            settings = bot_state.get_guild_settings(message.guild.id)
            if settings.boredom_channel:
                status += f" | boredom→<#{settings.boredom_channel}>"
            if settings.presence_channel:
                status += f" | presence→<#{settings.presence_channel}>"
            
            await message.channel.send(f"exia: i'm {status}. base reply chance is {bot_state.reply_chance_base}")
            return
        
        if command == '!contextinfo':
            if is_admin(message.author.id, message.guild.id):
                summary = context_manager.get_context_summary(message.channel.id)
                await message.channel.send(f"context stats: {summary}")
            else:
                await message.channel.send("thats admin only info")
            return
        
        if command == '!mystats':
            await Commands.mystats(message)
            return
        
        if command == '!preference' and len(args) >= 2:
            await Commands.preference(message, args[0], ' '.join(args[1:]))
            return
        
        if command == '!myreminders':
            await Commands.myreminders(message)
            return
        
        if command == '!cancelreminder' and args:
            await Commands.cancelreminder(message, args[0])
            return
        
        if command == '!commands':
            await message.channel.send(
                "**admin:** !setadmin, !removeadmin, !setchannel, !globalstatus, !shutdown\n"
                "**mod:** !clearcontext, !maxreply, !timeout, !resume, !toggle, !replychance, !toggleboredom, !togglephantom, !blacklist, !whitelist\n"
                "**user:** !status, !help, !mystats, !preference, !myreminders, !cancelreminder, !commands\n"
                "use `!help <command>` for details"
            )
            return
    
    # === CONVERSATION HANDLING ===
    
    # Check if bot is enabled and not timed out
    if not bot_state.bot_enabled or now < bot_state.timeout_until:
        return
    
    # Check if channel is disabled
    settings = bot_state.get_guild_settings(message.guild.id)
    if message.channel.id in settings.disabled_channels:
        return
    
    bot_state.last_user_message_time = now
    
    # === RANDOM EMOJI REACTION ===
    if random.random() < REACTION_CHANCE:
        try:
            emoji = random.choice(REACTION_EMOJIS)
            await message.add_reaction(emoji)
            logger.info(f"Reacted with {emoji} to message from {message.author}")
        except Exception as e:
            logger.error(f"Failed to add reaction: {e}")
        return
    
    # === REPLY DECISION LOGIC ===
    mentioned = bool(re.search(r"\bexia\b", content, re.IGNORECASE))
    
    # Determine if we should reply
    if not bot_state.phantom_replies_enabled:
        force_reply = mentioned
    else:
        if mentioned:
            force_reply = True
        else:
            # Complex reply chance calculation
            recent = (now - bot_state.last_user_message_time) < 5
            active = (now - bot_state.last_engaged_time) < 180
            
            # Check guild-specific override
            if settings.reply_chance_override is not None:
                base_chance = settings.reply_chance_override
            else:
                base_chance = bot_state.reply_chance_base
            
            if recent:
                chance = 0.9 if (now - bot_state.last_engaged_time) < 30 else 0.05
            elif active:
                chance = base_chance
            else:
                chance = 0.05
            
            force_reply = random.random() < chance
    
    # Check user cooldown
    if not force_reply or (now - bot_state.user_cooldowns[message.author.id]) < 20:
        return
    
    # Update cooldowns
    bot_state.user_cooldowns[message.author.id] = now
    bot_state.last_engaged_time = now
    
    # Generate response
    await generate_response(message)

async def handle_dm(message: discord.Message):
    """Handle DM commands"""
    content = message.content.strip().lower()
    
    # List reminders
    if content in ['list reminders', 'show reminders', 'my reminders']:
        reminders = bot_state.reminders.get(message.author.id, [])
        await message.channel.send(format_reminder_list(reminders))
        return
    
    # Cancel reminder
    if content.startswith('cancel reminder'):
        parts = content.split()
        if len(parts) >= 3:
            reminder_id = parts[2]
            user_reminders = bot_state.reminders.get(message.author.id, [])
            
            for reminder in user_reminders:
                if reminder.id == reminder_id:
                    user_reminders.remove(reminder)
                    await bot_state.save_data()
                    await message.channel.send(f"cancelled reminder: {reminder.task}")
                    return
            
            await message.channel.send(f"couldn't find reminder {reminder_id}")
        else:
            await message.channel.send("use: cancel reminder <id>")
        return
    
    # Set reminder
    match = re.match(r"remind me to (.+?) at (.+)", message.content, re.IGNORECASE)
    if match:
        task = match.group(1).strip()
        time_str = match.group(2).strip()
        
        try:
            # Parse time
            dt = dateutil.parser.parse(time_str, default=datetime.now())
            
            # If time is in the past, assume they mean tomorrow
            if dt < datetime.now():
                if dt.hour < datetime.now().hour:
                    dt += timedelta(days=1)
                else:
                    # They probably meant today but typo'd
                    dt = dt.replace(year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
                    if dt < datetime.now():
                        dt += timedelta(days=1)
            
            # Create reminder
            reminder = Reminder(
                user_id=message.author.id,
                task=task,
                time=dt.timestamp(),
                created_at=time.time(),
                id=generate_reminder_id()
            )
            
            bot_state.reminders[message.author.id].append(reminder)
            bot_state.update_user_stats(message.author.id, 'reminder')
            await bot_state.save_data()
            
            await message.channel.send(
                f"got it. i'll remind you to '{task}' at {dt.strftime('%Y-%m-%d %H:%M')} (id: {reminder.id})"
            )
            
            # Generate a natural response too
            messages = [
                {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
                {'role': 'user', 'content': f"someone asked you to remind them to {task} at {time_str}"}
            ]
            
            response = await call_llm(messages)
            if response:
                await message.channel.send(response)
                
        except Exception as e:
            logger.error(f"Failed to parse reminder: {e}")
            await message.channel.send("sorry, i couldn't understand that time. try something like 'tomorrow at 3pm' or '2024-12-25 09:00'")
    else:
        # Regular DM conversation - use context manager
        messages = await context_manager.build_context(
            message=message,
            system_prompt=EXIA_SYSTEM_PROMPT,
            include_bot_memory=True
        )
        
        async with message.channel.typing():
            await asyncio.sleep(random.uniform(2, 8))
            reply = await call_llm(messages)
            
            if reply:
                reply = re.sub(r"^(exia:\s*)", "", reply, flags=re.IGNORECASE)
                context_manager.save_bot_response(message.channel.id, reply)
                await message.channel.send(reply)

async def generate_response(message: discord.Message):
    """Generate and send response to message with improved context"""
    global bot_state, context_manager
    
    # Build context using the context manager
    messages = await context_manager.build_context(
        message=message,
        system_prompt=EXIA_SYSTEM_PROMPT,
        include_bot_memory=True
    )
    
    # Log context for debugging
    logger.info(context_manager.get_context_summary(message.channel.id))
    
    # Type while generating response
    async with message.channel.typing():
        # Random delay for naturalness
        await asyncio.sleep(random.uniform(2, 8))
        
        # Get response from LLM
        reply = await call_llm(messages)
        
        if not reply:
            reply = "hmm something went wrong. maybe try again"
            logger.error("Failed to get LLM response")
        else:
            # Clean up response
            reply = re.sub(r"^(exia:\s*)", "", reply, flags=re.IGNORECASE)
            
            # Save bot response to memory
            context_manager.save_bot_response(message.channel.id, reply)
    
    # Send response
    await message.channel.send(reply)
    logger.info(f"Responded to {message.author}: {reply[:50]}...")

@client.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    """Handle reactions to bot messages"""
    if user.bot or reaction.message.author != client.user:
        return
    
    # Generate context-aware response (but don't send it)
    messages = [
        {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"user {user.display_name} reacted {reaction.emoji} to your message '{reaction.message.content}'"}
    ]
    
    response = await call_llm(messages)
    if response:
        # Log the reaction context
        logger.info(f"{user.display_name} reacted {reaction.emoji}. Generated: {response[:50]}...")
        
        # Small chance to actually respond
        if random.random() < 0.1:  # 10% chance
            await reaction.message.channel.send(response)

@client.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Handle presence/activity updates"""
    # Get guild settings
    settings = bot_state.get_guild_settings(after.guild.id)
    
    # Check if we should comment
    if random.random() > PRESENCE_COMMENT_CHANCE:
        return
    
    # Compare activities
    before_activities = {a.name for a in before.activities if hasattr(a, 'name')}
    after_activities = {a.name for a in after.activities if hasattr(a, 'name')}
    
    if before_activities == after_activities:
        return
    
    added = after_activities - before_activities
    removed = before_activities - after_activities
    
    activity_change = None
    if added:
        activity_change = f"{after.display_name} started {', '.join(added)}"
    elif removed:
        activity_change = f"{after.display_name} stopped {', '.join(removed)}"
    
    if not activity_change:
        return
    
    # Generate comment
    messages = [
        {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
        {'role': 'user', 'content': f"you notice: {activity_change}"}
    ]
    
    comment = await call_llm(messages)
    if not comment:
        return
    
    # Find appropriate channel
    channel_id = settings.presence_channel
    if channel_id:
        channel = after.guild.get_channel(channel_id)
    else:
        # Find the most active text channel
        channel = None
        for ch in after.guild.text_channels:
            if ch.permissions_for(after.guild.me).send_messages:
                channel = ch
                break
    
    if channel:
        await channel.send(comment)
        logger.info(f"Commented on activity change: {activity_change}")

# === BACKGROUND LOOPS ===
async def reminder_loop():
    """Check and send reminders"""
    await client.wait_until_ready()
    
    while not bot_state.shutdown_event.is_set():
        try:
            now = time.time()
            
            for user_id, reminders in list(bot_state.reminders.items()):
                for reminder in reminders[:]:  # Copy list to avoid modification issues
                    if now >= reminder.time:
                        try:
                            user = await client.fetch_user(user_id)
                            await user.send(f"reminder: {reminder.task}")
                            reminders.remove(reminder)
                            logger.info(f"Sent reminder to {user_id}: {reminder.task}")
                        except Exception as e:
                            logger.error(f"Failed to send reminder: {e}")
                            # Remove failed reminder after 24 hours
                            if now - reminder.time > 86400:
                                reminders.remove(reminder)
            
            # Save after processing reminders
            if any(bot_state.reminders.values()):
                await bot_state.save_data()
                
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        
        await asyncio.sleep(30)

async def boredom_loop():
    """Send boredom messages when chat is idle"""
    await client.wait_until_ready()
    
    while not bot_state.shutdown_event.is_set():
        try:
            if not bot_state.bot_enabled or not bot_state.boredom_enabled:
                await asyncio.sleep(bot_state.BORED_CHECK_INTERVAL)
                continue
            
            now = time.time()
            idle_time = now - bot_state.last_engaged_time
            
            # Increase boredom chance over time
            if idle_time > 300:  # 5 minutes idle
                bot_state.bored_chance = min(
                    bot_state.BORED_CHANCE_MAX,
                    bot_state.bored_chance + bot_state.BORED_CHANCE_INCREMENT
                )
                
                if random.random() < bot_state.bored_chance:
                    # Find appropriate channel for each guild
                    for guild in client.guilds:
                        settings = bot_state.get_guild_settings(guild.id)
                        
                        # Use configured boredom channel or find one
                        channel = None
                        if settings.boredom_channel:
                            channel = guild.get_channel(settings.boredom_channel)
                        
                        if not channel:
                            # Find most recently active channel
                            for ch in guild.text_channels:
                                if ch.permissions_for(guild.me).send_messages:
                                    channel = ch
                                    break
                        
                        if channel:
                            await send_bored_message(channel)
                            bot_state.bored_chance = 0.0
                            bot_state.last_engaged_time = time.time()
                            break  # Only send to one guild
                            
        except Exception as e:
            logger.error(f"Boredom loop error: {e}")
        
        await asyncio.sleep(bot_state.BORED_CHECK_INTERVAL)

async def send_bored_message(channel: discord.TextChannel):
    """Send a boredom message to channel"""
    prompt = "you're bored. no one's said anything in a while. you're just trying to stir up a conversation or say something random. keep it short and casual."
    
    messages = [
        {'role': 'system', 'content': EXIA_SYSTEM_PROMPT},
        {'role': 'user', 'content': prompt}
    ]
    
    try:
        async with channel.typing():
            await asyncio.sleep(random.uniform(1, 4))
            reply = await call_llm(messages)
            
            if reply:
                await channel.send(reply)
                logger.info(f"Sent bored message to {channel.guild.name}#{channel.name}")
            
    except Exception as e:
        logger.error(f"Failed to send bored message: {e}")

async def auto_save_loop():
    """Periodically save data"""
    await client.wait_until_ready()
    
    while not bot_state.shutdown_event.is_set():
        await asyncio.sleep(300)  # Save every 5 minutes
        try:
            await bot_state.save_data()
            logger.info("Auto-saved bot data")
        except Exception as e:
            logger.error(f"Auto-save failed: {e}")

# === SHUTDOWN HANDLING ===
async def graceful_shutdown():
    """Gracefully shutdown the bot"""
    logger.info("Starting graceful shutdown...")
    
    # Signal shutdown to loops
    bot_state.shutdown_event.set()
    
    # Save all data
    await bot_state.save_data()
    
    # Cleanup resources
    await bot_state.cleanup()
    
    # Close Discord connection
    await client.close()
    
    logger.info("Shutdown complete")

def signal_handler(sig, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {sig}")
    asyncio.create_task(graceful_shutdown())

# === MAIN EXECUTION ===
async def main():
    """Main entry point"""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize bot state
    await bot_state.initialize()
    
    try:
        # Start the bot
        await client.start(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
    finally:
        await graceful_shutdown()

if __name__ == "__main__":
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
