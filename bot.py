import datetime as dt
import os
from contextlib import suppress
from typing import TYPE_CHECKING, cast

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

if TYPE_CHECKING:
    from typing import Literal, overload

    from aiohttp.client import _RequestOptions as RequestOptions  # pyright: ignore[reportPrivateUsage]
    from typing_extensions import TypedDict

    type JsonArray = list[Json]
    type JsonObject = dict[str, Json]
    type Json = bool | int | float | str | JsonArray | JsonObject | None

    class Server(TypedDict):
        server_id: str
        created: str
        server_uuid: str
        server_name: str
        path: str
        backup_path: str
        executable: str
        log_path: str
        execution_command: str
        auto_start: bool
        auto_start_delay: int
        crash_detection: bool
        stop_command: str
        executable_update_url: str
        server_ip: str
        server_port: int
        logs_delete_after: int
        type: str

    class ErrorResponse:
        status: str
        error: str
        error_data: str

    class GetServerStatsResponse(TypedDict):
        status: Literal["ok"]
        data: Server
        started: str
        running: bool
        cpu: float
        mem: str
        mem_percent: str
        world_name: str
        world_size: str
        server_port: int
        int_ping_results: str
        online: int
        max: int
        players: str
        desc: str
        icon: str
        version: str
        updating: bool
        waiting_start: bool
        first_run: bool
        crashed: bool

    class GetServersResponse(TypedDict):
        status: Literal["ok"]
        data: list[Server]

# --- CONFIGURATION ---

load_dotenv()

discord_token = os.getenv("DISCORD_TOKEN")
crafty_api_token = os.getenv("CRAFTY_API_TOKEN")
crafty_url = os.getenv("CRAFTY_URL")
notification_channel_id = os.getenv("NOTIFICATION_CHANNEL_ID")

if (
    discord_token is None
    or crafty_api_token is None
    or crafty_url is None
    or notification_channel_id is None
):
    msg = "Variable missing from `.env`. For further help, check out documentation."  # ruff: ignore[line-too-long]
    raise RuntimeError(msg)

DISCORD_TOKEN: str = discord_token
CRAFTY_API_TOKEN: str = crafty_api_token
CRAFTY_URL: str = crafty_url
NOTIFICATION_CHANNEL_ID: int = int(notification_channel_id)

del (discord_token, crafty_api_token, crafty_url, notification_channel_id)

EMPTY_SERVER_TIMEOUT_MINUTES = 30

# --- CRAFTY API HELPER ---

if TYPE_CHECKING:

    @overload
    async def crafty_req(
        method: Literal["GET"],
        endpoint: Literal["/servers"],
        json_data: JsonObject | None = None,
        raw_text: str | None = None,
    ) -> GetServersResponse | ErrorResponse: ...
    @overload
    async def crafty_req(
        method: Literal["GET"],
        endpoint: str,  # /servers/{server_id}/stats
        json_data: JsonObject | None = None,
        raw_text: str | None = None,
    ) -> GetServerStatsResponse | ErrorResponse: ...
    @overload
    async def crafty_req(
        method: str,
        endpoint: str,
        json_data: JsonObject | None = None,
        raw_text: str | None = None,
    ) -> JsonObject: ...


async def crafty_req(
    method: str,
    endpoint: str,
    json_data: JsonObject | None = None,
    raw_text: str | None = None,
) -> JsonObject | ErrorResponse | GetServersResponse | GetServerStatsResponse:
    """Make async requests to the Crafty API."""
    headers = {"Authorization": f"Bearer {CRAFTY_API_TOKEN}"}

    kwargs: RequestOptions = {"headers": headers}
    if json_data is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = json_data
    elif raw_text is not None:
        headers["Content-Type"] = "text/plain"
        kwargs["data"] = raw_text

    url = f"{CRAFTY_URL}{endpoint}"

    async with (
        aiohttp.ClientSession() as session,
        session.request(method, url, **kwargs) as response,
    ):
        if response.status in {200, 204}:
            try:
                return await response.json()
            except aiohttp.ContentTypeError:
                return {"status": "success"}
        else:
            return {
                "error": f"HTTP {response.status}",
                "details": await response.text(),
            }


# --- AUTOCOMPLETE FUNCTION ---


async def server_autocomplete(
    interaction: discord.Interaction,  # ruff: ignore[unused-function-argument]
    current: str,
) -> list[app_commands.Choice[str]]:
    """Fetch server list from Crafty and provid autocomplete choices to avoid typos."""  # ruff: ignore[line-too-long]
    response = await crafty_req("GET", "/servers")

    if "error" in response:  # pyright: ignore[reportOperatorIssue]
        return []

    servers = cast("GetServersResponse", response).get("data", [])
    choices: list[app_commands.Choice[str]] = []

    for s in servers:
        server_id = s.get("server_id")
        server_name = s.get("server_name", "Unknown Server")

        if current.lower() in server_name.lower():
            choices.append(
                app_commands.Choice(name=server_name, value=server_id)
            )

    # Discord limits autocomplete choices to 25
    return choices[:25]


# --- BACKGROUND TASKS ---

EMPTY_SERVER_TRACER: dict[str, dt.datetime] = {}


@tasks.loop(minutes=1)
async def auto_shutdown_check(bot: commands.Bot) -> None:
    servers_res = await crafty_req("GET", "/servers")
    if "error" in servers_res:  # pyright: ignore[reportOperatorIssue]
        return

    servers = cast("GetServersResponse", servers_res).get("data", [])

    for s in servers:
        server_id: str = s.get("server_id")
        server_name: str = s.get("server_name", "Unknown Server")

        stats_res = await crafty_req("GET", f"/servers/{server_id}/stats")
        if "error" in stats_res:  # pyright: ignore[reportOperatorIssue]
            continue

        stats_data = cast("GetServerStatsResponse", stats_res).get("data", {})
        is_running = stats_data.get("running", False)

        # --- DEBUG LOGGING ---
        # This will print the raw API data to your server logs
        # print(f"[DEBUG] Raw stats for {server_name}: {stats_data}")

        if not is_running:
            EMPTY_SERVER_TRACER.pop(server_id, None)
            continue

        player_count = 0

        if "online" in stats_data and isinstance(stats_data["online"], int):
            player_count = stats_data["online"]
        elif "players_online" in stats_data and isinstance(
            stats_data["players_online"], int
        ):
            player_count = stats_data["players_online"]
        elif "players" in stats_data and isinstance(
            stats_data["players"], dict
        ):
            player_count = stats_data["players"].get("online", 0)
        elif "online" in stats_data and isinstance(stats_data["online"], str):
            with suppress(ValueError):
                player_count = int(stats_data["online"].split("/")[0])

        print(
            f"[DEBUG] Extracted player count for {server_name}: {player_count}"
        )

        if player_count == 0:
            if server_id not in EMPTY_SERVER_TRACER:
                EMPTY_SERVER_TRACER[server_id] = dt.datetime.now(dt.UTC)
            else:
                time_empty = (
                    dt.datetime.now(dt.UTC) - EMPTY_SERVER_TRACER[server_id]
                )
                minutes_empty = time_empty.total_seconds() / 60

                if minutes_empty >= EMPTY_SERVER_TIMEOUT_MINUTES:
                    await crafty_req(
                        "POST", f"/servers/{server_id}/action/stop_server"
                    )

                    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
                    if channel is not None and isinstance(
                        channel, discord.TextChannel
                    ):
                        await channel.send(
                            f"💤 **{server_name}** has been empty for {minutes_empty} minutes and was automatically shut down to save resources."  # ruff: ignore[line-too-long]
                        )

                    EMPTY_SERVER_TRACER.pop(server_id, None)
        else:
            EMPTY_SERVER_TRACER.pop(server_id, None)


@auto_shutdown_check.before_loop
async def before_auto_shutdown() -> None:
    await BOT.wait_until_ready()


# --- BOT SETUP ---


class CraftyBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=discord.Intents.default())

    async def setup_hook(self) -> None:
        await self.tree.sync()
        print("Slash commands synced successfully!")

        """if not auto_shutdown_check.is_running():
            auto_shutdown_check.start(self)
            print("Auto-shutdown monitor started!")"""


BOT = CraftyBot()


@BOT.event
async def on_ready() -> None:  # ruff: ignore[unused-async]
    print(
        f"Logged in as {BOT.user} (ID: {getattr(BOT.user, "id", "Unknown")})"
    )
    print("------")


# --- GENERAL SERVER COMMANDS ---


@BOT.tree.command(name="mc-list", description="Lists all Minecraft servers")
async def mc_list(interaction: discord.Interaction) -> None:
    # Defer the response since we might be making multiple API calls
    await interaction.response.defer()

    # 1. Fetch the static list of servers
    servers_res = await crafty_req("GET", "/servers")

    if "error" in servers_res:  # pyright: ignore[reportOperatorIssue]
        await interaction.followup.send(
            f"❌ Failed to fetch servers: {servers_res["error"]}"  # pyright: ignore[reportIndexIssue]
        )
        return

    servers = cast("GetServersResponse", servers_res).get("data", [])
    if not servers:
        await interaction.followup.send("No servers found.")
        return

    embed = discord.Embed(
        title="Minecraft Servers", color=discord.Color.blue()
    )

    # 2. Loop through each server to fetch its live stats
    for s in servers:
        server_id: str = s.get("server_id")
        server_name: str = s.get("server_name", "Unknown Server")

        # Fetch live stats for this specific server ID
        stats_res = await crafty_req("GET", f"/servers/{server_id}/stats")

        is_running = False
        if "error" not in stats_res:  # pyright: ignore[reportOperatorIssue]
            # Safely grab the running boolean from the stats data
            is_running: bool = (
                cast("GetServerStatsResponse", stats_res)
                .get("data", {})
                .get("running", False)
            )

        status = "🟢 Online" if is_running else "🔴 Offline"
        embed.add_field(
            name=f"{server_name} ({status})",
            value=f"ID: `{server_id}`",
            inline=False,
        )

    await interaction.followup.send(embed=embed)


@BOT.tree.command(name="mc-start", description="Starts the specified server")
@app_commands.autocomplete(server=server_autocomplete)
async def mc_start(interaction: discord.Interaction, server: str) -> None:
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/start_server")

    if "error" in res:
        await interaction.followup.send(
            f"❌ Failed to start server: {res["error"]}"
        )
        await interaction.followup.send(
            "Retry or if the issue persists contact the sysadmin"
        )
    else:
        await interaction.followup.send(
            f"✅ Start command sent to server ID: `{server}`"
        )
        await interaction.followup.send(
            "Please wait up to 2 minutes for it to fully start"
        )


@BOT.tree.command(name="mc-stop", description="Stops the specified server")
@app_commands.autocomplete(server=server_autocomplete)
async def mc_stop(interaction: discord.Interaction, server: str) -> None:
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/stop_server")

    if "error" in res:
        await interaction.followup.send(
            f"❌ Failed to stop server: {res["error"]}"
        )
    else:
        await interaction.followup.send(
            f"✅ Stop command sent to server ID: `{server}`"
        )


@BOT.tree.command(
    name="mc-kill", description="Kills the processes of the specified server"
)
@app_commands.autocomplete(server=server_autocomplete)
async def mc_kill(interaction: discord.Interaction, server: str) -> None:
    await interaction.response.defer()
    res = await crafty_req("POST", f"/servers/{server}/action/kill_server")

    if "error" in res:
        await interaction.followup.send(
            f"❌ Failed to kill server: {res["error"]}"
        )
    else:
        await interaction.followup.send(
            f"⚠️ Kill command executed on server ID: `{server}`"
        )


# --- MC-SERVER COMMAND TREE ---


class MCServerGroup(app_commands.Group):
    """Group for managing player actions on a specific server."""


class WhitelistGroup(app_commands.Group):
    """Subgroup for whitelist commands."""


MC_SERVER_GROUP = MCServerGroup(
    name="mc-server", description="Manage players on a Minecraft server"
)
WHITELIST_GROUP = WhitelistGroup(
    name="whitelist",
    description="Manage the whitelist",
    parent=MC_SERVER_GROUP,
)


async def send_stdin_command(
    interaction: discord.Interaction,
    server: str,
    command: str,
    success_msg: str,
) -> None:
    """Send terminal commands."""
    await interaction.response.defer()

    res = await crafty_req(
        "POST", f"/servers/{server}/stdin", raw_text=command
    )

    if "error" in res:
        await interaction.followup.send(
            f"❌ Failed to execute command: {res["error"]}"
        )
    else:
        await interaction.followup.send(success_msg)


@WHITELIST_GROUP.command(name="add", description="Adds a player to the whitelist")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def whitelist_add(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"whitelist add {player_name}",
        f"✅ Added **{player_name}** to the whitelist.",
    )


@WHITELIST_GROUP.command(name="remove", description="Removes a player from the whitelist")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def whitelist_remove(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"whitelist remove {player_name}",
        f"✅ Removed **{player_name}** from the whitelist.",
    )


@MC_SERVER_GROUP.command(name="kick", description="Kicks a player from the server")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def kick_player(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"kick {player_name}",
        f"👢 Kicked **{player_name}** from the server.",
    )


@MC_SERVER_GROUP.command(name="ban", description="Bans a player from the server")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def ban_player(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"ban {player_name}",
        f"🔨 Banned **{player_name}** from the server.",
    )


@MC_SERVER_GROUP.command(name="op", description="Grants operator status to a player")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def op_player(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"op {player_name}",
        f"👑 Granted OP to **{player_name}**.",
    )


@MC_SERVER_GROUP.command(name="deop", description="Removes operator status from a player")  # fmt: skip  # ruff: ignore[line-too-long]
@app_commands.autocomplete(server=server_autocomplete)
async def deop_player(
    interaction: discord.Interaction, server: str, player_name: str
) -> None:
    await send_stdin_command(
        interaction,
        server,
        f"deop {player_name}",
        f"📉 Removed OP from **{player_name}**.",
    )


# Register the command tree
BOT.tree.add_command(MC_SERVER_GROUP)

# --- START THE BOT ---


def main() -> None:
    BOT.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()