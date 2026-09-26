from dataclasses import dataclass
import re

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db.models import Count, Q

from accounts.models import DiscordLinkCode, User
from busstops.models import Operator
from fleet.completion import (
    create_ride_log,
    find_matching_vehicles,
    format_vehicle_match,
    get_discord_user,
    get_completion_summary_for_queryset,
    has_vehicle_been_logged,
)
from fleet.models import FleetRideLog
from vehicles.models import Vehicle


def create_vehicle_embed(vehicle, logged: bool | None = None, status: str = "") -> dict:
    embed = {
        "title": str(vehicle),
        "url": f"https://betterfleets.org{vehicle.get_absolute_url()}",
        "color": 0x22C55E if logged else 0x2563EB,
        "fields": [],
    }
    if vehicle.reg:
        embed["fields"].append({"name": "Registration", "value": vehicle.reg, "inline": True})
    if vehicle.fleet_number or vehicle.fleet_code:
        embed["fields"].append(
            {"name": "Fleet Number", "value": str(vehicle.fleet_number or vehicle.fleet_code), "inline": True}
        )
    if vehicle.operator:
        embed["fields"].append({"name": "Operator", "value": str(vehicle.operator), "inline": True})
    if vehicle.livery:
        embed["fields"].append({"name": "Livery", "value": str(vehicle.livery), "inline": True})
    if vehicle.vehicle_type:
        embed["fields"].append({"name": "Type", "value": str(vehicle.vehicle_type), "inline": True})
    if logged is not None:
        embed["fields"].append(
            {
                "name": "Logged Status",
                "value": f"{'✅ Logged' if logged else '❌ Not logged'}",
                "inline": False,
            }
        )
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
        return None, "Your Discord account is not linked to a BetterFleets account."
    return user, ""


async def execute_log_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult("not_found", "No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult("multiple", "Multiple vehicles matched your query.", matches)
    vehicle = matches[0]
    _, created = await sync_to_async(create_ride_log)(user, vehicle)
    return DiscordCommandResult(
        "created" if created else "duplicate",
        f"{'Logged' if created else 'Already logged'} {format_vehicle_match(vehicle)}.",
        [vehicle],
        await sync_to_async(create_vehicle_embed)(vehicle, True, "log"),
    )


async def execute_check_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult("not_found", "No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult("multiple", "Multiple vehicles matched your query.", matches)
    vehicle = matches[0]
    logged = await sync_to_async(has_vehicle_been_logged)(user, vehicle)
    return DiscordCommandResult(
        "logged" if logged else "not_logged",
        f"You have {'logged' if logged else 'not logged'} {format_vehicle_match(vehicle)}.",
        [vehicle],
        await sync_to_async(create_vehicle_embed)(vehicle, logged, "check"),
    )


async def execute_unlog_command(discord_user_id: str, query: str, noc: str = "") -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    matches = await sync_to_async(find_matching_vehicles)(query, noc=noc)
    if not matches:
        return DiscordCommandResult("not_found", "No matching vehicle found.")
    if len(matches) > 1:
        return DiscordCommandResult("multiple", "Multiple vehicles matched your query.", matches)
    vehicle = matches[0]
    deleted, _ = await sync_to_async(FleetRideLog.objects.filter(user=user, vehicle=vehicle).delete)()
    return DiscordCommandResult(
        "deleted" if deleted else "not_logged",
        f"{'Unlogged' if deleted else 'You had not logged'} {format_vehicle_match(vehicle)}.",
        [vehicle],
        await sync_to_async(create_vehicle_embed)(vehicle, False, "unlog"),
    )


async def execute_completion_command(discord_user_id: str, noc: str) -> DiscordCommandResult:
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    try:
        operator = await sync_to_async(Operator.objects.get)(
            Q(noc__iexact=noc) | Q(slug__iexact=noc)
        )
    except Operator.DoesNotExist:
        return DiscordCommandResult("not_found", "Operator not found.")
    vehicles = await sync_to_async(list)(Vehicle.objects.filter(operator=operator))
    summary = await sync_to_async(get_completion_summary_for_queryset)(vehicles, user)
    return DiscordCommandResult(
        "success",
        f"{operator.name}: {summary.logged}/{summary.total} ({summary.percentage:.1f}%)",
    )


def _vehicle_lookup(reg, fleet_number, operator):
    query = Vehicle.objects.select_related("operator", "vehicle_type", "livery")
    filters = Q()
    if reg:
        filters |= Q(reg__iexact=reg)
    if fleet_number:
        try:
            filters |= Q(fleet_number=int(fleet_number))
        except ValueError:
            filters |= Q(fleet_code__iexact=fleet_number)
    if not filters:
        return []
    query = query.filter(filters)
    if operator:
        query = query.filter(
            Q(operator__noc__iexact=operator)
            | Q(operator__slug__iexact=operator)
            | Q(operator__name__iexact=operator)
        )
    return list(query.order_by("id")[:10])


async def execute_vehicle_lookup(discord_user_id, reg, fleet_number, operator):
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    matches = await sync_to_async(_vehicle_lookup)(reg, fleet_number, operator)
    if not matches:
        return DiscordCommandResult("not_found", "No vehicle matched those filters.")
    if len(matches) > 1:
        return DiscordCommandResult("multiple", "Multiple vehicles matched those filters.", matches)
    return DiscordCommandResult("success", "Vehicle found.", matches, create_vehicle_embed(matches[0]))


def _vehicle_count(vehicle_type, operator, livery):
    query = Vehicle.objects.all()
    if vehicle_type:
        query = query.filter(Q(vehicle_type__name__icontains=vehicle_type) | Q(vehicle_type__style__iexact=vehicle_type))
    if operator:
        query = query.filter(
            Q(operator__noc__iexact=operator)
            | Q(operator__slug__iexact=operator)
            | Q(operator__name__icontains=operator)
        )
    if livery:
        query = query.filter(livery__name__icontains=livery)
    return query.filter(withdrawn=False).count()


async def execute_count_command(discord_user_id, vehicle_type, operator, livery):
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    count = await sync_to_async(_vehicle_count)(vehicle_type, operator, livery)
    return DiscordCommandResult("success", f"{count:,} active vehicles match the supplied filters.")


def _user_lookup(username):
    return User.objects.annotate(
        edits=Count("edited_revisions", filter=Q(edited_revisions__pending=False)),
        photos=Count("photo", distinct=True),
        rides=Count("fleet_ride_logs", distinct=True),
    ).filter(
        Q(username__iexact=username)
        | Q(display_name__iexact=username)
        | Q(email__iexact=username)
    ).first()


async def execute_user_command(discord_user_id, username):
    user, error = await get_authorized_discord_user(discord_user_id)
    if user is None:
        return DiscordCommandResult("forbidden", error)
    target = await sync_to_async(_user_lookup)(username)
    if target is None:
        return DiscordCommandResult("not_found", "BetterFleets user not found.")
    embed = {
        "title": target.get_display_name(),
        "url": f"https://betterfleets.org{target.get_absolute_url()}",
        "color": 0x2563EB,
        "fields": [
            {"name": "Username", "value": target.username or "—", "inline": True},
            {"name": "Edits", "value": f"{target.edits:,}", "inline": True},
            {"name": "Photos", "value": f"{target.photos:,}", "inline": True},
            {"name": "Ride logs", "value": f"{target.rides:,}", "inline": True},
        ],
    }
    return DiscordCommandResult("success", "User found.", embed=embed)


def build_bot():
    try:
        import asyncio
        import discord
        from discord import app_commands
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("discord.py is required to run the Discord bot.") from exc

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    def embed(title, description="", color=0x2563EB):
        return discord.Embed(title=title, description=description, color=color)

    def result_embed(result):
        if result.embed:
            return discord.Embed.from_dict(result.embed)
        return embed(
            "BetterFleets",
            result.message,
            0x22C55E if result.status in {"success", "created", "deleted", "logged"} else 0xEF4444,
        )

    class MatchChooser(discord.ui.View):
        def __init__(self, action, discord_user_id, matches):
            super().__init__(timeout=120)
            self.action = action
            self.discord_user_id = discord_user_id
            select = discord.ui.Select(
                placeholder="Choose a vehicle",
                options=[
                    discord.SelectOption(label=format_vehicle_match(vehicle)[:100], value=str(vehicle.pk))
                    for vehicle in matches[:25]
                ],
            )

            async def callback(interaction):
                vehicle = next(vehicle for vehicle in matches if str(vehicle.pk) == select.values[0])
                if action == "log":
                    result = await execute_log_command(discord_user_id, str(vehicle), "")
                else:
                    result = await execute_check_command(discord_user_id, str(vehicle), "")
                await interaction.response.send_message(embed=result_embed(result), ephemeral=True)

            select.callback = callback
            self.add_item(select)

    async def send_result(interaction, result, action=None):
        if result.status == "multiple" and action:
            await interaction.response.send_message(
                embed=embed("Multiple matches", result.message, 0xF59E0B),
                view=MatchChooser(action, str(interaction.user.id), result.matches or []),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(embed=result_embed(result), ephemeral=True)

    class CloseTicketView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger, custom_id="betterfleets:close-ticket")
        async def close(self, interaction, button):
            await interaction.response.send_message(embed=embed("Ticket closed", "This ticket is being closed."), ephemeral=True)
            await asyncio.sleep(1)
            await interaction.channel.delete(reason=f"Closed by {interaction.user}")

    class TicketModal(discord.ui.Modal, title="BetterFleets ticket"):
        description = discord.ui.TextInput(
            label="What do you need help with?",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=2000,
        )

        def __init__(self, matter):
            super().__init__()
            self.matter = matter

        async def on_submit(self, interaction):
            guild = interaction.guild
            if guild is None:
                await interaction.response.send_message(embed=embed("Ticket error", "Tickets can only be opened in a server.", 0xEF4444), ephemeral=True)
                return
            category = guild.get_channel(int(settings.DISCORD_TICKET_CATEGORY_ID)) if settings.DISCORD_TICKET_CATEGORY_ID.isdigit() else None
            support_role = guild.get_role(int(settings.DISCORD_SUPPORT_ROLE_ID)) if settings.DISCORD_SUPPORT_ROLE_ID.isdigit() else None
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            name = re.sub(r"[^a-z0-9-]+", "-", f"{self.matter}-{interaction.user.name}".lower()).strip("-")[:90]
            channel = await guild.create_text_channel(name or "ticket", category=category, overwrites=overwrites)
            await channel.send(
                embed=embed(
                    f"{self.matter} ticket",
                    f"Opened by {interaction.user.mention}\n\n{self.description.value}",
                    0x5865F2,
                ),
                view=CloseTicketView(),
            )
            await interaction.response.send_message(embed=embed("Ticket opened", f"Your ticket is {channel.mention}."), ephemeral=True)

    class TicketView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Open a ticket", style=discord.ButtonStyle.primary, custom_id="betterfleets:open-ticket")
        async def open_ticket(self, interaction, button):
            select = discord.ui.Select(
                placeholder="What is your ticket about?",
                options=[discord.SelectOption(label=matter, value=matter) for matter in ("Bug", "Request", "Report", "Account", "Other")],
            )

            async def select_callback(select_interaction):
                await select_interaction.response.send_modal(TicketModal(select.values[0]))

            select.callback = select_callback
            view = discord.ui.View()
            view.add_item(select)
            await interaction.response.send_message(embed=embed("Ticket matter", "Choose the matter for your ticket."), view=view, ephemeral=True)

    @tree.command(name="vehicle", description="Look up a BetterFleets vehicle.")
    @app_commands.describe(reg="Registration", fleet_number="Fleet number or fleet code", operator="Operator NOC, slug, or name")
    async def vehicle_command(interaction, reg: str = "", fleet_number: str = "", operator: str = ""):
        await send_result(interaction, await execute_vehicle_lookup(str(interaction.user.id), reg, fleet_number, operator))

    @tree.command(name="count", description="Count active BetterFleets vehicles.")
    async def count_command(interaction, vehicle_type: str = "", operator: str = "", livery: str = ""):
        await send_result(interaction, await execute_count_command(str(interaction.user.id), vehicle_type, operator, livery))

    @tree.command(name="user", description="Look up a BetterFleets user.")
    async def user_command(interaction, username: str):
        await send_result(interaction, await execute_user_command(str(interaction.user.id), username))

    @tree.command(name="log", description="Log a vehicle as ridden.")
    async def log_vehicle(interaction, query: str, noc: str = ""):
        await send_result(interaction, await execute_log_command(str(interaction.user.id), query, noc), "log")

    @tree.command(name="check", description="Check whether you have logged a vehicle.")
    async def check_vehicle(interaction, query: str, noc: str = ""):
        await send_result(interaction, await execute_check_command(str(interaction.user.id), query, noc), "check")

    @tree.command(name="unlog", description="Unlog a vehicle.")
    async def unlog_vehicle(interaction, query: str, noc: str = ""):
        await send_result(interaction, await execute_unlog_command(str(interaction.user.id), query, noc))

    @tree.command(name="completion", description="View completion stats for an operator.")
    async def completion_stats(interaction, noc: str):
        await send_result(interaction, await execute_completion_command(str(interaction.user.id), noc))

    @tree.command(name="link", description="Link your Discord account to BetterFleets.")
    async def link_account(interaction, code: str):
        def link():
            link_code = DiscordLinkCode.objects.select_related("user").filter(
                code=code.upper(), is_used=False
            ).first()
            if not link_code or not link_code.is_valid():
                return None, "Invalid or expired code. Please generate a new code."
            user = link_code.user
            try:
                user.username = interaction.user.name
                user.discord_user_id = str(interaction.user.id)
                user.discord_username = interaction.user.name
                user.save(update_fields=["username", "discord_user_id", "discord_username"])
            except IntegrityError:
                return None, "That Discord username is already used by another BetterFleets account."
            link_code.is_used = True
            link_code.save(update_fields=["is_used"])
            return user, None

        user, error = await sync_to_async(link)()
        if error:
            await interaction.response.send_message(embed=embed("Link failed", error, 0xEF4444), ephemeral=True)
            return
        role_names = await sync_to_async(list)(Group.objects.filter(user=user).values_list("name", flat=True))
        guild = interaction.guild
        if guild is None and settings.DISCORD_BOT_GUILD_ID.isdigit():
            guild = client.get_guild(int(settings.DISCORD_BOT_GUILD_ID))
        missing = []
        if guild:
            group_names = set(role_names)
            all_group_names = set(
                await sync_to_async(list)(Group.objects.values_list("name", flat=True))
            )
            for role in guild.roles:
                if role.name in all_group_names:
                    if role.name in group_names and role not in interaction.user.roles:
                        await interaction.user.add_roles(role, reason="BetterFleets group synchronization")
                    elif role.name not in group_names and role in interaction.user.roles:
                        await interaction.user.remove_roles(role, reason="BetterFleets group synchronization")
            missing = [name for name in group_names if not discord.utils.get(guild.roles, name=name)]
        suffix = f" Missing Discord roles: {', '.join(missing)}." if missing else ""
        await interaction.response.send_message(
            embed=embed("Account linked", f"Your BetterFleets account is now linked as **{user.username}**.{suffix}", 0x22C55E),
            ephemeral=True,
        )

    @client.event
    async def on_ready():
        guild_id = settings.DISCORD_BOT_GUILD_ID
        if guild_id.isdigit():
            guild = discord.Object(id=int(guild_id))
            tree.clear_commands(guild=guild)
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            ticket_channel = client.get_channel(int(settings.DISCORD_TICKET_CHANNEL_ID)) if settings.DISCORD_TICKET_CHANNEL_ID.isdigit() else None
            if ticket_channel:
                async for message in ticket_channel.history(limit=20):
                    if message.author == client.user and message.embeds and message.embeds[0].title == "BetterFleets tickets":
                        break
                else:
                    await ticket_channel.send(
                        embed=embed("BetterFleets tickets", "Use the button below to open a private support ticket.", 0x5865F2),
                        view=TicketView(),
                    )
        else:
            await tree.sync()

    client.add_view(TicketView())
    client.add_view(CloseTicketView())
    return client
