import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import asyncio
import datetime
from dotenv import load_dotenv
import os

load_dotenv()


# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CRAFTY_API_TOKEN = os.getenv("CRAFTY_API_TOKEN")
CRAFTY_URL = os.getenv("CRAFTY_URL")
NOTIFICATION_CHANNEL_ID = os.getenv("NOTIFICATION_CHANNEL_ID")

# --- CRAFTY API HELPER ---
async def crafty_req(method: str, endpoint: str, json_data: dict = None, raw_text: str = None):
    """Helper function to make async requests to the Crafty API."""
    headers = {
        "Authorization": f"Bearer {CRAFTY_API_TOKEN}"
    }
    
    kwargs = {"headers": headers}
    if json_data is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = json_data
    elif raw_text is not None:
        headers["Content-Type"] = "text/plain"
        kwargs["data"] = raw_text

    url = f"{CRAFTY_URL}{endpoint}"
    
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, **kwargs) as response:
            if response.status in (200, 204):
                try:
                    return await response.json()
                except aiohttp.ContentTypeError:
                    return {"status": "success"}
            else:
                return {"error": f"HTTP {response.status}", "details": await response.text()}

# --- AUTOCOMPLETE FUNCTION ---
async def server_autocomplete(interaction: discord.Interaction, current: str):
    """Fetches server list from Crafty and provides autocomplete choices to avoid typos."""
    response = await crafty_req("GET", "/servers")
    
    if "error" in response:
        return []

    servers = response.get("data", [])
    choices = []
    
    for s in servers:
        server_id = s.get("server_id")
        server_name = s.get("server_name", "Unknown Server")
        
        if current.lower() in server_name.lower():
            choices.append(app_commands.Choice(name=server_name, value=server_id))
            
    # Discord limits autocomplete choices to 25
    return choices[:25]

# --- BACKGROUND TASKS ---
empty_server_tracker = {}

@tasks.loop(minutes=1)
async def auto_shutdown_check(bot: commands.Bot):
    servers_res = await crafty_req("GET", "/servers")
    if "error" in servers_res:
        return

    servers = servers_res.get("data", [])
    
    for s in servers:
        server_id = s.get('server_id')
        server_name = s.get('server_name', 'Unknown Server')
        
        stats_res = await crafty_req("GET", f"/servers/{server_id}/stats")
        if "error" in stats_res:
            continue
            
        stats_data = stats_res.get("data", {})
        is_running = stats_data.get("running", False)
        
        # --- DEBUG LOGGING ---
        # This will print the raw API data to your server logs
        #print(f"[DEBUG] Raw stats for {server_name}: {stats_data}")
        
        if not is_running:
            if server_id in empty_server_tracker:
                del empty_server_tracker[server_id]
            continue
            
        player_count = 0
        
        if "online" in stats_data and isinstance(stats_data["online"], int):
            player_count = stats_data["online"]
        elif "players_online" in stats_data and isinstance(stats_data["players_online"], int):
            player_count = stats_data["players_online"]
        elif "players" in stats_data and isinstance(stats_data["players"], dict):
            player_count = stats_data["players"].get("online", 0)
        elif "online" in stats_data and isinstance(stats_data["online"], str):
            try:
                player_count = int(stats_data["online"].split('/')[0])
            except ValueError:
                pass
        
        print(f"[DEBUG] Extracted player count for {server_name}: {player_count}")
        
        if player_count == 0:
            if server_id not in empty_server_tracker:
                empty_server_tracker[server_id] = datetime.datetime.now(datetime.timezone.utc)
            else:
                time_empty = datetime.datetime.now(datetime.timezone.utc) - empty_server_tracker[server_id]
                minutes_empty = time_empty.total_seconds() / 60
                
                if minutes_empty >= 30:  # Change to 30 for production
                    await crafty_req("POST", f"/servers/{server_id}/action/stop_server")
                    
                    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
                    if channel:
                        await channel.send(f"💤 **{server_name}** has been empty for 30 minutes and was automatically shut down to save resources.")
                        
                    del empty_server_tracker[server_id]
        else:
            if server_id in empty_server_tracker:
                del empty_server_tracker[server_id]

@auto_shutdown_check.before_loop
async def before_auto_shutdown():
    await bot.wait_until_ready()


# --- BOT SETUP ---
class CraftyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced successfully!")
        
        """if not auto_shutdown_check.is_running():
            auto_shutdown_check.start(self)
            print("Auto-shutdown monitor started!")"""

bot = CraftyBot()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


# --- GENERAL SERVER COMMANDS ---
@bot.tree.command(name="mc-list", description="Lists all Minecraft servers")
async def mc_list(interaction: discord.Interaction):
    # Defer the response since we might be making multiple API calls
    await interaction.response.defer()
    
    # 1. Fetch the static list of servers
    servers_res = await crafty_req("GET", "/servers")
    
    if "error" in servers_res:
        await interaction.followup.send(f"❌ Failed to fetch servers: {servers_res['error']}")
        return

    servers = servers_res.get("data", [])
    if not servers:
        await interaction.followup.send("No servers found.")
        return

    embed = discord.Embed(title="Minecraft Servers", color=discord.Color.blue())
    
    # 2. Loop through each server to fetch its live stats
    for s in servers:
        server_id = s.get('server_id')
        server_name = s.get('server_name', 'Unknown Server')
        
        # Fetch live stats for this specific server ID
        stats_res = await crafty_req("GET", f"/servers/{server_id}/stats")
        
        is_running = False
        if "error" not in stats_res:
            # Safely grab the running boolean from the stats data
            is_running = stats_res.get("data", {}).get("running", False)
            
        status = "🟢 Online" if is_running else "🔴 Offline"
        embed.add_field(
            name=f"{server_name} ({status})", 
            value=f"ID: `{server_id}`", 
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="mc-start", description="Starts the specified server")
@app_commands.autocomplete(server=server_autocomplete)
async def mc_start(interaction: discord.Interaction, server: str):
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/start_server")
    
    if "error" in res:
        await interaction.followup.send(f"❌ Failed to start server: {res['error']}")
        await interaction.followup.send(f"Retry or if the issue persists contact the sysadmin")
    else:
        await interaction.followup.send(f"✅ Start command sent to server ID: `{server}`")
        await interaction.followup.send(f"Please wait up to 2 minutes for it to fully start")


@bot.tree.command(name="mc-stop", description="Stops the specified server")
@app_commands.autocomplete(server=server_autocomplete)
async def mc_stop(interaction: discord.Interaction, server: str):
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/stop_server")
    
    if "error" in res:
        await interaction.followup.send(f"❌ Failed to stop server: {res['error']}")
    else:
        await interaction.followup.send(f"✅ Stop command sent to server ID: `{server}`")


@bot.tree.command(name="mc-kill", description="Kills the processes of the specified server")
@app_commands.autocomplete(server=server_autocomplete)
async def mc_kill(interaction: discord.Interaction, server: str):
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/kill_server")
    
    if "error" in res:
        await interaction.followup.send(f"❌ Failed to kill server: {res['error']}")
    else:
        await interaction.followup.send(f"⚠️ Kill command executed on server ID: `{server}`")


# --- MC-SERVER COMMAND TREE ---

class MCServerGroup(app_commands.Group):
    """Group for managing player actions on a specific server."""
    pass

class WhitelistGroup(app_commands.Group):
    """Subgroup for whitelist commands."""
    pass

mc_server_group = MCServerGroup(name="mc-server", description="Manage players on a Minecraft server")
whitelist_group = WhitelistGroup(name="whitelist", description="Manage the whitelist", parent=mc_server_group)

async def send_stdin_command(interaction: discord.Interaction, server: str, command: str, success_msg: str):
    """Helper to send terminal commands."""
    await interaction.response.defer()
    
    res = await crafty_req("POST", f"/servers/{server}/stdin", raw_text=command)
    
    if "error" in res:
        await interaction.followup.send(f"❌ Failed to execute command: {res['error']}")
    else:
        await interaction.followup.send(success_msg)

# Whitelist Add
@whitelist_group.command(name="add", description="Adds a player to the whitelist")
@app_commands.autocomplete(server=server_autocomplete)
async def whitelist_add(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"whitelist add {player_name}", 
        f"✅ Added **{player_name}** to the whitelist."
    )

# Whitelist Remove
@whitelist_group.command(name="remove", description="Removes a player from the whitelist")
@app_commands.autocomplete(server=server_autocomplete)
async def whitelist_remove(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"whitelist remove {player_name}", 
        f"✅ Removed **{player_name}** from the whitelist."
    )

# Kick
@mc_server_group.command(name="kick", description="Kicks a player from the server")
@app_commands.autocomplete(server=server_autocomplete)
async def kick_player(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"kick {player_name}", 
        f"👢 Kicked **{player_name}** from the server."
    )

# Ban
@mc_server_group.command(name="ban", description="Bans a player from the server")
@app_commands.autocomplete(server=server_autocomplete)
async def ban_player(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"ban {player_name}", 
        f"🔨 Banned **{player_name}** from the server."
    )

# OP
@mc_server_group.command(name="op", description="Grants operator status to a player")
@app_commands.autocomplete(server=server_autocomplete)
async def op_player(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"op {player_name}", 
        f"👑 Granted OP to **{player_name}**."
    )

# De-OP
@mc_server_group.command(name="deop", description="Removes operator status from a player")
@app_commands.autocomplete(server=server_autocomplete)
async def deop_player(interaction: discord.Interaction, server: str, player_name: str):
    await send_stdin_command(
        interaction, server, f"deop {player_name}", 
        f"📉 Removed OP from **{player_name}**."
    )

# Register the command tree
bot.tree.add_command(mc_server_group)

# --- START THE BOT ---
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)