# Exiabot - Enhanced Edition

A fully-featured Discord bot with AI conversation capabilities, persistent storage, and extensive management features.

## 🚀 Major Improvements

### 1. **Asynchronous Operations**
- Replaced blocking `requests` with `aiohttp` for non-blocking API calls
- Prevents bot freezing during LLM requests
- Improved overall responsiveness

### 2. **Persistent Storage System**
- **Reminders** survive bot restarts (`exia_reminders.json`)
- **Settings** are saved automatically (`exia_settings.json`) 
- **User statistics** tracking (`exia_user_data.json`)
- **Blacklist** management (`exia_blacklist.json`)
- Auto-save every 5 minutes + graceful shutdown saves

### 3. **Comprehensive Error Handling**
- Retry logic for failed API calls (3 attempts with exponential backoff)
- Timeout protection (30 second limit)
- Rate limit handling
- Graceful degradation when LLM is unavailable
- Detailed logging to `exia.log`

### 4. **Permission System**
- Guild-specific admin users
- Bot owner always has full access
- Protected commands require admin role
- User blacklist/whitelist functionality

### 5. **Enhanced Reminder System**
- Persistent storage across restarts
- Unique IDs for each reminder
- View all reminders with `!myreminders` or DM "list reminders"
- Cancel specific reminders with `!cancelreminder <id>`
- Smart time parsing (handles "tomorrow", "next week", etc.)
- Automatic correction for past times

### 6. **Per-Guild Configuration**
- Set specific channels for boredom messages
- Set specific channels for presence updates
- Guild-specific admin lists
- Disable bot in specific channels
- Override reply chance per guild

### 7. **Improved Context Management**
- Message caching to reduce API calls
- Smart history fetching (only last 5 minutes)
- Token limit awareness
- Memory optimization

### 8. **User Features**
- Personal statistics tracking (`!mystats`)
- Custom preferences (`!preference key value`)
- Reminder management
- Command cooldowns (3 seconds)

### 9. **Better Channel Selection**
- Configurable channels for different message types
- No more random channel spam
- Respects channel permissions

### 10. **Command System Improvements**
- Help system with command details (`!help <command>`)
- Command aliases
- Usage examples in error messages
- Cooldown system to prevent spam

## 📦 Installation

### Prerequisites
```bash
pip install discord.py aiohttp python-dateutil
```

### Setup
1. Clone the repository
2. Set your Discord bot token in `DISCORD_TOKEN` variable
3. Ensure LM Studio is running at `http://localhost:1234/v1/chat/completions`
4. Run the bot:
```bash
python exi_enhanced.py
```

## 🎮 Command Reference

### Admin Commands
*Requires admin privileges or bot owner*

| Command | Description | Usage |
|---------|-------------|-------|
| `!setadmin` | Grant admin privileges | `!setadmin @user` |
| `!removeadmin` | Remove admin privileges | `!removeadmin @user` |
| `!setchannel` | Set special channels | `!setchannel boredom` or `!setchannel presence` |
| `!globalstatus` | Show bot statistics across all guilds | `!globalstatus` |
| `!shutdown` | Gracefully shutdown the bot | `!shutdown` |
| `!reloadconfig` | Reload configuration from files | `!reloadconfig` |

### Moderation Commands
*Requires admin privileges*

| Command | Description | Usage |
|---------|-------------|-------|
| `!clearcontext` | Clear bot's conversation memory | `!clearcontext` |
| `!maxreply` | Set maximum response length | `!maxreply 200` (50-1000) |
| `!timeout` | Silence bot temporarily | `!timeout 30` (minutes, default 15) |
| `!resume` | Resume from timeout | `!resume` |
| `!toggle` | Enable/disable bot globally | `!toggle` |
| `!replychance` | Set base reply probability | `!replychance 0.1` (0.0-1.0) |
| `!toggleboredom` | Toggle boredom messages | `!toggleboredom` |
| `!togglephantom` | Toggle phantom replies | `!togglephantom` |
| `!blacklist` | Block user from bot interaction | `!blacklist @user` |
| `!whitelist` | Unblock user | `!whitelist @user` |

### User Commands
*Available to all users*

| Command | Description | Usage |
|---------|-------------|-------|
| `!status` | Show current bot status | `!status` |
| `!commands` | List all available commands | `!commands` |
| `!help` | Get help for commands | `!help` or `!help <command>` |
| `!myreminders` | List your active reminders | `!myreminders` |
| `!cancelreminder` | Cancel a specific reminder | `!cancelreminder R1234` |
| `!mystats` | Show your interaction statistics | `!mystats` |
| `!preference` | Set personal preferences | `!preference theme dark` |

### DM Commands
*Use in Direct Messages with the bot*

| Command | Description | Usage |
|---------|-------------|-------|
| Set reminder | Schedule a reminder | `remind me to check email at 3pm tomorrow` |
| List reminders | Show all your reminders | `list reminders` |
| Cancel reminder | Cancel a specific reminder | `cancel reminder R1234` |

## 🗂️ Data Files

The bot creates several JSON files for persistent storage:

### `exia_reminders.json`
Stores all user reminders with:
- User ID
- Task description  
- Scheduled time
- Creation time
- Unique ID

### `exia_settings.json`
Stores bot configuration:
- Global enable/disable state
- Feature flags (boredom, phantom replies)
- Token limits
- Reply chances
- Guild-specific settings

### `exia_user_data.json`
Tracks user statistics:
- Messages sent
- Commands used
- Reminders created
- Last seen timestamp
- Personal preferences

### `exia_blacklist.json`
List of blacklisted user IDs

### `exia.log`
Detailed activity log for debugging

## 🔧 Configuration

### Environment Variables (Optional)
While the token is hardcoded as requested, you can modify the code to use environment variables:

```python
import os
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN', '')
LM_API_URL = os.getenv('LM_API_URL', 'http://localhost:1234/v1/chat/completions')
```

### Adjustable Parameters

```python
# API Settings
API_TIMEOUT = 30  # seconds
API_RETRIES = 3
API_RETRY_DELAY = 2  # seconds

# Reaction Settings
PRESENCE_COMMENT_CHANCE = 0.001  # 0.1% chance
REACTION_CHANCE = 0.003  # 0.3% chance
REACTION_EMOJIS = ['👍', '😂', '❤️', '😮', '😢', '🎉', '🔥', '💯', '🤔', '👀']

# Boredom Settings
BORED_CHECK_INTERVAL = 60  # seconds
BORED_CHANCE_INCREMENT = 0.02
BORED_CHANCE_MAX = 0.5
```

## 🛡️ Security Features

1. **Permission System**: Admin-only commands protected
2. **User Blacklisting**: Block problematic users
3. **Rate Limiting**: Command cooldowns prevent spam
4. **Input Validation**: All user inputs sanitized
5. **Graceful Error Handling**: Errors logged, not exposed

## 📊 Monitoring

### Logging
- All events logged to `exia.log`
- Console output for real-time monitoring
- Error tracking with stack traces

### Statistics
- Track user interactions
- Monitor reminder completion
- Guild activity metrics
- Use `!globalstatus` for overview

## 🔄 Backup & Recovery

### Manual Backup
```bash
# Backup all data files
cp exia_*.json backup/
```

### Automatic Backup
- Data auto-saved every 5 minutes
- Graceful shutdown saves all data
- Signal handlers for SIGINT/SIGTERM

## 🐛 Troubleshooting

### Bot Not Responding
1. Check if bot is enabled: `!status`
2. Check if timed out: `!resume`
3. Check if user is blacklisted
4. Check channel permissions
5. Review `exia.log` for errors

### LLM Connection Issues
1. Verify LM Studio is running
2. Check API endpoint URL
3. Review timeout settings
4. Check `exia.log` for API errors

### Reminders Not Working
1. Verify reminders file exists
2. Check user has DMs enabled
3. Review reminder time parsing
4. Check `!myreminders` for status

## 🚦 Status Indicators

When you run `!status`, you'll see:
- **on/off**: Bot enabled state
- **timed out**: If bot is silenced
- **bored**: Boredom messages enabled
- **phantom**: Random replies enabled  
- **boredom→channel**: Configured boredom channel
- **presence→channel**: Configured presence channel
- **reply chance**: Base probability of replies

## 📈 Performance Optimizations

1. **Message Caching**: Recent messages cached per channel/minute
2. **Batch Operations**: Reminders processed in batches
3. **Async Everything**: Non-blocking I/O operations
4. **Smart Fetching**: Only fetch necessary history
5. **Connection Pooling**: Reused aiohttp session

## 🎯 Best Practices

### For Admins
1. Set dedicated channels for boredom/presence messages
2. Configure reasonable reply chances (0.05-0.2 recommended)
3. Regular backups of JSON files
4. Monitor `exia.log` for issues
5. Use blacklist sparingly

### For Users  
1. Use clear time formats for reminders
2. Cancel old reminders to keep list clean
3. Set preferences for personalized experience
4. Use `!help` to learn commands
5. Report issues to admins

## 🔮 Future Enhancements

Potential additions for future versions:
- [ ] Web dashboard for configuration
- [ ] Database backend (SQLite/PostgreSQL)
- [ ] Multi-language support
- [ ] Custom command creation
- [ ] Webhook integrations
- [ ] Scheduled announcements
- [ ] Role-based permissions
- [ ] Command usage analytics
- [ ] Conversation export
- [ ] AI personality customization

## 📝 Change Log

### Version 2.0.0 - Enhanced Edition
- Complete async rewrite
- Persistent storage system
- Permission management
- Enhanced reminder system
- Per-guild configuration
- User statistics tracking
- Comprehensive error handling
- Command help system
- Blacklist functionality
- Auto-save mechanism
- Graceful shutdown
- Message caching
- Better channel selection
- Command cooldowns
- Detailed logging

### Version 1.0.0 - Original
- Basic conversation capability
- Simple reminder system
- Basic commands
- Phantom replies
- Boredom messages
- Emoji reactions

## 📄 License

This project maintains the original open-source spirit. Feel free to modify and distribute.

## 🤝 Contributing

Contributions welcome! Please:
1. Test your changes thoroughly
2. Update documentation
3. Follow existing code style
4. Add logging for new features
5. Handle errors gracefully

## 💬 Support

For issues or questions:
1. Check this README first
2. Review `exia.log` for errors
3. Try `!help <command>` in Discord
4. Check existing GitHub issues
5. Create new issue with details

---

*Remember: Exia talks in lowercase, no punctuation, super chill. But the code? That's production-ready.* 😎
