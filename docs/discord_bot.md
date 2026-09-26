# Discord bot

The bot runs with:

```sh
python manage.py run_discord_bot
```

Configure the bot token and guild with `DISCORD_BOT_TOKEN` and
`DISCORD_BOT_GUILD_ID`. The bot automatically creates a ticket panel in
`DISCORD_TICKET_CHANNEL_ID`. New tickets are private channels under
`DISCORD_TICKET_CATEGORY_ID`, visible to the opener and `DISCORD_SUPPORT_ROLE_ID`.

`DISCORD_ALERT_CHANNEL_ID` receives embeds when a vehicle is added and when a
vehicle is tracked for the first time. Alerts are queued through Huey, so the
Huey consumer must be running in deployments that use alerts.

All lookup commands require the user to link their BetterFleets account first
using the code from `/accounts/discord-link/` and the Discord `/link` command.
Linking changes the BetterFleets username to the Discord username and maps each
Django group to an existing Discord role with the same name. The bot reports
group roles that do not exist in the guild; it does not create roles.

Available commands include `/vehicle`, `/count`, `/user`, `/link`, `/log`,
`/check`, `/unlog`, and `/completion`. Command responses and ticket messages
are Discord embeds.
