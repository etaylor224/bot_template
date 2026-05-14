import disnake
from disnake.ext import commands
from disnake.ext.commands import is_owner, NotOwner

intents = disnake.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(intents=intents, test_guilds=approved_guilds)

bot_name = "BOT NAME FOR WEBHOOK"
monitor = UniversalMonitor(bot, bot_name, webhook_url)
flag_path = "restart.flag"


@bot.slash_command(name="guild_check", description="Joined Guild details")
@is_owner()
async def guild_check(interaction: disnake.ApplicationCommandInteraction):
    joined_guilds = bot.guilds
    for guild in joined_guilds:
        await monitor.guild_report(guild)

@bot.slash_command(name="remove")
@is_owner()
async def remove(interaction: disnake.ApplicationCommandInteraction, guild_id):
    await interaction.response.defer(ephemeral=True)
    guild = bot.get_guild(int(guild_id))

    if guild is None:
        await interaction.followup.send("Error in guild id")

    guild_name = guild.name
    await guild.leave()
    await interaction.followup.send(f"Left {guild_name}", ephemeral=True)

@bot.event
async def on_slash_command(inter: disnake.ApplicationCommandInteraction):
    monitor.command_count += 1
    monitor.track_request()
    await monitor.check_rate_limit()

@bot.event
async def on_user_command(inter: disnake.UserCommandInteraction):
    monitor.command_count += 1
    monitor.track_request()
    await monitor.check_rate_limit()


@bot.event
async def on_message_command(inter: disnake.MessageCommandInteraction):
    monitor.command_count += 1
    monitor.track_request()
    await monitor.check_rate_limit()


@bot.event
async def on_button_click(inter: disnake.MessageInteraction):
    monitor.track_request()
    await monitor.check_rate_limit()

@bot.event
async def on_dropdown(inter: disnake.MessageInteraction):
    monitor.track_request()
    await monitor.check_rate_limit()

@bot.event
async def on_modal_submit(inter: disnake.ModalInteraction):
    monitor.track_request()
    await monitor.check_rate_limit()

@bot.event
async def on_error(event, *args, **kwargs):
    await monitor.report_error(Exception(traceback.format_exc()))

@bot.event
async def on_slash_command_error(inter: disnake.ApplicationCommandInteraction, error):
    if isinstance(error, NotOwner):
        ran_by = inter.user.display_name
        await inter.send("This command is owner-only.",ephemeral=True)
        if inter.guild.name:
            await monitor.report_warn(f"User: {ran_by} tried to run this command in {inter.guild.name}",
            context=f"/{inter.application_command.name}")
        else:
            await monitor.report_warn(f"User: {ran_by} tried to run this command.",
            context=f"/{inter.application_command.name}")

    else:
        await monitor.report_error(error, context=f"/{inter.application_command.name}")

@bot.event
async def on_modal_error(inter: disnake.ModalInteraction, error):
    await monitor.report_error(error, context=f"Modal: {inter.custom_id}")

@bot.event
async def on_button_click_error(inter: disnake.MessageInteraction, error):
    await monitor.report_error(error, context=f"Button: {inter.component.custom_id}")

@bot.event
async def on_dropdown_error(inter: disnake.MessageInteraction, error):
    await monitor.report_error(error, context=f"Dropdown: {inter.component.custom_id}")

@bot.event
async def on_guild_join(guild: disnake.Guild):
    new_guild = guild.id
    guild_owner = guild.owner_id

    if new_guild not in approved_guilds:

        inviter = None

        try:
            async for entry in guild.audit_logs(action=disnake.AuditLogAction.bot_add, limit=5):
                if entry.target.id == bot.user.id:
                    inviter = entry.user
                    break
        except disnake.Forbidden:
            print(f"[on_guild_join] No audit log access")
            await monitor.leave_report(guild, f"[on_guild_join] No audit log access")

        try:
            await guild.get_member(guild_owner).send(f"BOT NOT APPROVED FOR USE IN {guild.name}. BOT WILL BE LEAVING NOW!\n"
                                                     f"BOT INVITED BY {inviter}.\n"
                                                     f"FOR AUTHORIZATION CONTACT THE DEVELOPER.")
        except disnake.Forbidden:
            pass

        await monitor.leave_report(guild, inviter)
        await guild.leave()

@bot.event
async def on_ready():
    if os.path.exists(flag_path):
        await monitor.report_restart()

    with open(flag_path, "w") as f:
        f.write("running")

    await monitor.report_online()
    bot.loop.create_task(monitor.heartbeat())
    print(f"Logged in as {bot.user}")

bot.run(bot_token)
