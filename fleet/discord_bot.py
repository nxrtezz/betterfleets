from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q
from asgiref.sync import sync_to_async

from fleet.completion import (
    create_ride_log,
    find_matching_vehicles,
    format_vehicle_match,
    get_discord_user,
    has_vehicle_been_logged,
)
from vehicles.models import Vehicle
from fleet.models import FleetRideLog


def create_vehicle_embed(vehicle, logged: bool, status: str) -> dict:
    """Create a Discord embed for vehicle information."""
    embed = {
        "title": str(vehicle),
        "color": 0x22C55E if logged else 0xEF4444,  # Green if logged, red if not
        "fields": []
    }
    
    # Registration (field is called 'reg' in the model)
    if vehicle.reg:
        embed["fields"].append({
            "name": "Registration",
            "value": vehicle.reg,
            "inline": True
        })
    
    # Fleet number (check both fleet_number and fleet_code)
    fleet_num = vehicle.fleet_number or vehicle.fleet_code
    if fleet_num:
        embed["fields"].append({
            "name": "Fleet Number",
            "value": str(fleet_num),
            "inline": True
        })
    
    # Operator
    if vehicle.operator:
        embed["fields"].append({
            "name": "Operator",
            "value": str(vehicle.operator),
            "inline": True
        })
    
    # Livery
    if vehicle.livery:
        embed["fields"].append({
            "name": "Livery",
            "value": str(vehicle.livery),
            "inline": True
        })
    
    # Vehicle type
    if vehicle.vehicle_type:
        embed["fields"].append({
            "name": "Type",
            "value": str(vehicle.vehicle_type),
            "inline": True
        })
    
    # Logged status with emoji
    status_emoji = "✅" if logged else "❌"
    embed["fields"].append({
        "name": "Logged Status",
        "value": f"{status_emoji} {'Logged' if logged else 'Not logged'}",
        "inline": False
    })
    
    # Add URL if available
    if hasattr(vehicle, 'get_absolute_url'):
        embed["url"] = f"https://betterfleets.org{vehicle.get_absolute_url()}"
    
    return embed


@dataclass
class DiscordCommandResult:
    status: str
    message: str
    matches: list | None = None
    embed: dict | None = None


async def get_authorized_discord_user(discord_user_id: str):
    user = await sync_to_async(get_discord_user)(discord_user_id)
    if user is None:
        return None, "Your Discord account is not linked to a Better Fleets account."
    return user, ""


async def execute_check_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult(status="forbidden", message=error)

    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult(status="not_found", message="No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult(
            status="multiple",
            message="Multiple vehicles matched your query.",
            matches=matches,
        )

    vehicle = matches[0]
    logged = await sync_to_async(has_vehicle_been_logged)(user, vehicle)
    embed = await sync_to_async(create_vehicle_embed)(vehicle, logged, "check")
    return DiscordCommandResult(
        status="logged" if logged else "not_logged",
        message=f"You have {'logged' if logged else 'not logged'} {format_vehicle_match(vehicle)}.",
        matches=[vehicle],
        embed=embed,
    )


async def execute_unlog_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult(status="forbidden", message=error)

    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult(status="not_found", message="No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult(
            status="multiple",
            message="Multiple vehicles matched your query.",
            matches=matches,
        )

    vehicle = matches[0]
    deleted, _ = await sync_to_async(FleetRideLog.objects.filter(user=user, vehicle=vehicle).delete)()
    logged = False  # After unlogging, it's not logged
    embed = await sync_to_async(create_vehicle_embed)(vehicle, logged, "unlog")
    if deleted:
        return DiscordCommandResult(
            status="deleted",
            message=f"Unlogged {format_vehicle_match(vehicle)}.",
            matches=[vehicle],
            embed=embed,
        )
    return DiscordCommandResult(
        status="not_logged",
        message=f"You had not logged {format_vehicle_match(vehicle)}.",
        matches=[vehicle],
        embed=embed,
    )


async def execute_completion_command(discord_user_id: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult(status="forbidden", message=error)

    if not noc:
        return DiscordCommandResult(status="error", message="Please provide an operator NOC or slug.")

    from busstops.models import Operator

    try:
        operator = await sync_to_async(Operator.objects.get)(Q(noc__iexact=noc) | Q(slug__iexact=noc))
    except Operator.DoesNotExist:
        return DiscordCommandResult(status="not_found", message="Operator not found.")

    from fleet.completion import get_completion_summary_for_queryset

    vehicles = await sync_to_async(lambda: Vehicle.objects.filter(operator=operator))()
    summary = await sync_to_async(get_completion_summary_for_queryset)(vehicles, user)

    message = (
        f"**{operator.name} Completion**\n"
        f"Logged: {summary.logged}/{summary.total} ({summary.percentage:.1f}%)"
    )
    return DiscordCommandResult(status="success", message=message)


async def execute_log_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult(status="forbidden", message=error)

    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult(status="not_found", message="No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult(
            status="multiple",
            message="Multiple vehicles matched your query.",
            matches=matches,
        )

    vehicle = matches[0]
    _, created = await sync_to_async(create_ride_log)(user, vehicle)
    logged = True  # After logging, it's logged
    embed = await sync_to_async(create_vehicle_embed)(vehicle, logged, "log")
    return DiscordCommandResult(
        status="created" if created else "duplicate",
        message=f"{'Logged' if created else 'Already logged'} {format_vehicle_match(vehicle)}.",
        matches=[vehicle],
        embed=embed,
    )


def build_bot():
    try:
        import discord
        from discord import app_commands
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("discord.py is required to run the Discord bot.") from exc

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    class MatchChooser(discord.ui.View):
        def __init__(self, *, action: str, discord_user_id: str, matches):
            super().__init__(timeout=120)
            self.action = action
            self.discord_user_id = discord_user_id
            options = [
                discord.SelectOption(label=format_vehicle_match(vehicle)[:100], value=str(vehicle.pk))
                for vehicle in matches[:25]
            ]
            select = discord.ui.Select(
                placeholder="Choose a vehicle",
                options=options,
            )

            async def _callback(interaction: discord.Interaction):
                selected_id = int(select.values[0])
                vehicle = next(vehicle for vehicle in matches if vehicle.pk == selected_id)
                if self.action == "log":
                    user, error = await get_authorized_discord_user(self.discord_user_id)
                    if user is None:
                        result = DiscordCommandResult(status="forbidden", message=error)
                    else:
                        _, created = await sync_to_async(create_ride_log)(user, vehicle)
                        logged = True
                        embed = await sync_to_async(create_vehicle_embed)(vehicle, logged, "log")
                        result = DiscordCommandResult(
                            status="created" if created else "duplicate",
                            message=(
                                f"Logged {format_vehicle_match(vehicle)}."
                                if created
                                else f"You already logged {format_vehicle_match(vehicle)}."
                            ),
                            matches=[vehicle],
                            embed=embed,
                        )
                else:
                    user, error = await get_authorized_discord_user(self.discord_user_id)
                    if user is None:
                        result = DiscordCommandResult(status="forbidden", message=error)
                    else:
                        is_logged = await sync_to_async(has_vehicle_been_logged)(user, vehicle)
                        embed = await sync_to_async(create_vehicle_embed)(vehicle, is_logged, "check")
                        result = DiscordCommandResult(
                            status="logged" if is_logged else "not_logged",
                            message=(
                                f"You have logged {format_vehicle_match(vehicle)}."
                                if is_logged
                                else f"You have not logged {format_vehicle_match(vehicle)}."
                            ),
                            matches=[vehicle],
                            embed=embed,
                        )
                if result.embed:
                    embed = discord.Embed.from_dict(result.embed)
                    await interaction.response.send_message(result.message, embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(result.message, ephemeral=True)

            select.callback = _callback
            self.add_item(select)

    async def _send_result(interaction: "discord.Interaction", result: DiscordCommandResult, action: str):
        if result.status == "multiple":
            await interaction.response.send_message(
                result.message,
                view=MatchChooser(
                    action=action,
                    discord_user_id=str(interaction.user.id),
                    matches=result.matches or [],
                ),
                ephemeral=True,
            )
            return
        if result.embed:
            embed = discord.Embed.from_dict(result.embed)
            await interaction.response.send_message(result.message, embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(result.message, ephemeral=True)

    @tree.command(name="log", description="Log a vehicle as ridden.")
    async def log_vehicle(interaction: "discord.Interaction", query: str, noc: str = ""):
        result = await execute_log_command(str(interaction.user.id), query, noc=noc)
        await _send_result(interaction, result, "log")

    @tree.command(name="check", description="Check whether you have logged a vehicle.")
    async def check_vehicle(interaction: "discord.Interaction", query: str, noc: str = ""):
        result = await execute_check_command(str(interaction.user.id), query, noc=noc)
        await _send_result(interaction, result, "check")

    @tree.command(name="unlog", description="Unlog a vehicle.")
    async def unlog_vehicle(interaction: "discord.Interaction", query: str, noc: str = ""):
        result = await execute_unlog_command(str(interaction.user.id), query, noc=noc)
        await _send_result(interaction, result, "unlog")

    @tree.command(name="completion", description="View completion stats for an operator.")
    async def completion_stats(interaction: "discord.Interaction", noc: str):
        result = await execute_completion_command(str(interaction.user.id), noc=noc)
        await interaction.response.send_message(result.message, ephemeral=True)

    @tree.command(name="link", description="Link your Discord account to your BetterFleets account.")
    async def link_account(interaction: "discord.Interaction", code: str):
        from accounts.models import DiscordLinkCode

        discord_user_id = str(interaction.user.id)
        discord_username = str(interaction.user)

        def _link_account():
            try:
                link_code = DiscordLinkCode.objects.select_related('user').get(
                    code=code.upper(), is_used=False
                )
            except DiscordLinkCode.DoesNotExist:
                return None, "Invalid or expired code. Please generate a new code from your account settings."

            user = link_code.user
            user.discord_user_id = discord_user_id
            user.discord_username = discord_username
            user.save(update_fields=["discord_user_id", "discord_username"])

            link_code.is_used = True
            link_code.save(update_fields=["is_used"])

            return user.get_display_name(), None

        display_name, error = await sync_to_async(_link_account)()

        if error:
            await interaction.response.send_message(error, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Successfully linked your Discord account to {display_name}!",
                ephemeral=True
            )

    @client.event
    async def on_ready():  # pragma: no cover
        guild_id = settings.DISCORD_BOT_GUILD_ID
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            tree.clear_commands(guild=guild)
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            print(f"Commands synced cleanly for guild {guild_id}")
        else:
            await tree.sync()
            print("Commands synced globally")

    return client
