# Crafty Controller Discord Bot 🎮

A powerful and easy-to-use Discord bot that integrates directly with your [Crafty Controller](https://craftycontrol.com/) panel. Manage your Minecraft servers, view their status, and moderate players seamlessly from your Discord server.

## ✨ Features

* View live server statuses (Online/Offline).
* Start, stop, and forcefully kill server instances.
* Fully functioning Discord Slash Commands with auto-completion for server names to prevent typos.
* Direct terminal command integration for quick player moderation (whitelist, kick, ban, op).

## 🛠️ Commands

### General Server Commands

*Note: `[server]` options auto-complete as you type in Discord to prevent typos!*

| Command | Description | 
| ----- | ----- | 
| `/mc-list` | Fetches and lists all servers alongside their live status (🟢 Online / 🔴 Offline). | 
| `/mc-start [server]` | Sends a start request to the specified server. | 
| `/mc-stop [server]` | Sends a graceful stop request to the specified server. | 
| `/mc-kill [server]` | Force-kills the specified server's processes. **Use as a last resort.** | 

### Player Management

*Note: These commands send instructions directly to the Minecraft server terminal. Both `[server]` and `[player_name]` are required.*

| Command | Description | 
| ----- | ----- | 
| `/mc-server whitelist add [server] [player_name]` | Adds the specified player to the server's whitelist. | 
| `/mc-server whitelist remove [server] [player_name]` | Removes the specified player from the server's whitelist. | 
| `/mc-server kick [server] [player_name]` | Kicks the specified player from the server. | 
| `/mc-server ban [server] [player_name]` | Bans the specified player from the server. | 
| `/mc-server op [server] [player_name]` | Grants Operator (OP) privileges to the specified player. | 
| `/mc-server deop [server] [player_name]` | Revokes Operator (OP) privileges from the specified player. | 

## 🚀 Installation & Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/yourusername/crafty-controller-discord-bot.git
   cd crafty-controller-discord-bot
   ```

2. **Install requirements:**
   Make sure you have Python 3.8+ installed. Install the required Python packages using pip:

   ```bash
   pip install discord.py aiohttp python-dotenv
   ```
   *(Alternatively, if you have a `requirements.txt` file, run `pip install -r requirements.txt`)*

3. **Configuration:**
   Create a `.env` file in the root directory (or rename `.env.example`) and fill in your credentials:

   ```env
   DISCORD_TOKEN=your_discord_bot_token_here
   CRAFTY_API_TOKEN=your_crafty_api_token_here
   CRAFTY_URL=http://your-crafty-ip:8000/api/v2
   NOTIFICATION_CHANNEL_ID=your_discord_channel_id_here
   ```
   *(Note: Ensure your `CRAFTY_URL` includes the API path if required by your setup, or just the base URL if the script handles the `/api/...` prefix).*

4. **Run the bot:**

   ```bash
   python bot.py
   ```

## 🔐 Permissions

Ensure your Discord bot has the `application.commands` scope enabled to register slash commands, as well as permission to send messages in the designated `NOTIFICATION_CHANNEL_ID`.