# Exia Discord Bot

**Exia** is a chill, laid-back Discord chatbot built in Python using `discord.py` and a local LLM (Gemini via LM Studio). Exia hangs out in your server, responds when mentioned (or occasionally unprompted), reacts with emojis, tracks reminders, watches presence/activity, and more—all in a relaxed, lowercase-only style.

---

## Features

* **Conversational AI**: Integrates with a local LLM through LM Studio API for context-aware chat replies.
* **Phantom Replies**: Small random chance of unsolicited replies when the chat is active.
* **Boredom Loop**: If the chat is idle, Exia occasionally posts a “bored” message to stir conversation.
* **Emoji Reactions**: Randomly reacts to messages with emojis instead of replying.
* **Activity Awareness**: Detects when users start/stop games or other activities and comments via the LLM.
* **Reminders in DMs**: Schedule personal reminders by DMing `remind me to <task> at <time>`. Exia will DM back at the specified time.
* **Presence & Reaction Forwarding**: Any reaction to Exia’s messages or presence changes are forwarded to the LLM for contextual responses.
* **Toggle Commands**: Fine-tune behavior with commands to enable/disable features in real time.

---

## Dependencies

* Python 3.8+
* `discord.py`
* `requests`
* `python-dateutil` (for natural-language time parsing)

Install via:

```bash
pip install discord.py requests python-dateutil
```

---

## Configuration

1. **Token**: Create a `.env` or edit the top of `exia_bot.py` to set `DISCORD_TOKEN` to your bot’s token.
2. **LM API URL**: Ensure `LM_API_URL` points to your LM Studio endpoint (default is `http://localhost:1234/v1/chat/completions`).
3. **Intents**: Enable **Server Members** and **Presence Intent** in the Discord Developer Portal under your application’s **Bot** settings.
4. **Permissions Integer**: Use `74816` as the OAuth2 permissions integer to grant necessary permissions.

---

## Commands

```text
!clearcontext        – forgets everything I remember
!maxreply <number>   – limits how much I say
!timeout             – shuts me up for 15 min
!resume              – makes me talk again
!toggle              – turns me on or off
!status              – shows current settings
!replychance <0-1>   – tweaks how chatty I am
!toggleboredom       – enable/disable bored messages
!togglephantom       – enable/disable random replies
!commands            – shows this list
```

*Reminder*: For personal DMs:

```text
remind me to <task> at <time>
```

---

## Running the Bot

```bash
python exia_bot.py
```

---

## Contributing

Pull requests welcome! Please follow Python best practices and keep code style consistent.

---

## License

MIT © Your Name
