import traceback
import asyncio
import os
import psutil
from datetime import datetime
import disnake
import aiohttp
from collections import deque
from conf import log_hook_url

class UniversalMonitor:
    def __init__(self, bot, bot_name: str, webhook_url: str, rate_limit_threshold: int = 800):
        self.bot = bot
        self.bot_name = bot_name
        self.webhook_url = webhook_url
        self.rate_limit_threshold = rate_limit_threshold

        self.start_time = datetime.utcnow()
        self.error_count = 0
        self.command_count = 0

        self.process = psutil.Process(os.getpid())
        self.heartbeat_running = False

        self.owner_id = 401397788870574080

        self.rate_timestamps = deque()
        self.current_rpm = 0
        self.peak_rpm = 0
        self.rate_warnings_sent = {}

    def uptime(self):
        delta = datetime.utcnow() - self.start_time
        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        return f"{days}d {hours}h {minutes}m"

    def memory(self):
        return f"{round(self.process.memory_info().rss / (1024**2), 2)} MB"

    def cpu(self):
        return f"{self.process.cpu_percent(interval=None)}%"

    def latency(self):
        return f"{round(self.bot.latency * 1000)} ms"

    def track_request(self):
        now = datetime.utcnow()
        self.rate_timestamps.append(now)

        cutoff = now.timestamp() - 60
        while self.rate_timestamps and self.rate_timestamps[0].timestamp() < cutoff:
            self.rate_timestamps.popleft()

        self.current_rpm = len(self.rate_timestamps)

        if self.current_rpm > self.peak_rpm:
            self.peak_rpm = self.current_rpm

    def get_rpm(self):
        now = datetime.utcnow()
        cutoff = now.timestamp() - 60

        while self.rate_timestamps and self.rate_timestamps[0].timestamp() < cutoff:
            self.rate_timestamps.popleft()

        self.current_rpm = len(self.rate_timestamps)
        return self.current_rpm

    async def check_rate_limit(self):
        rpm = self.get_rpm()

        if rpm >= self.rate_limit_threshold:
            current_time = datetime.utcnow()
            last_warning = self.rate_warnings_sent.get('high_rate')

            if last_warning is None or (current_time - last_warning).total_seconds() > 300:
                await self.report_high_rate(rpm)
                self.rate_warnings_sent['high_rate'] = current_time

    async def send_embed(self, embed):
        async with aiohttp.ClientSession() as session:
            webhook = disnake.Webhook.from_url(
                self.webhook_url,
                session=session
            )
            await webhook.send(embed=embed, username=self.bot_name)

    async def log_embed(self, url, embed):
        async with aiohttp.ClientSession() as session:
            webhook = disnake.Webhook.from_url(
                url,
                session=session
            )
            await webhook.send(embed=embed, username=self.bot_name, content=f"<@{self.owner_id}>")

    async def report_online(self):
        embed = disnake.Embed(
            title=":green_circle: Bot Online",
            color=disnake.Color.green(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=self.bot_name, inline=False)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)))
        embed.add_field(name="Latency", value=self.latency())
        embed.add_field(name="Memory", value=self.memory())

        await self.send_embed(embed)

    async def report_restart(self):
        embed = disnake.Embed(
            title=":warning: Bot Restart Detected",
            color=disnake.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=self.bot_name)

        await self.send_embed(embed)

    async def report_high_rate(self, rpm: int):
        embed = disnake.Embed(
            title=":warning: High Rate Detected",
            color=disnake.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=self.bot_name, inline=False)
        embed.add_field(name="Current RPM", value=f"{rpm} req/min", inline=True)
        embed.add_field(name="Threshold", value=f"{self.rate_limit_threshold} req/min", inline=True)
        embed.add_field(name="Peak RPM", value=f"{self.peak_rpm} req/min", inline=True)
        embed.add_field(
            name="Warning",
            value=":warning: Bot is experiencing high request rates. Monitor for potential issues.",
            inline=False
        )

        await self.send_embed(embed)

    async def report_warn(self, error, context: str = "Unknown"):
        if isinstance(error, Exception):
            error_text = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        else:
            error_text = str(error)

        embed = disnake.Embed(
            title=":warning: Warning",
            color=disnake.Color.yellow(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=self.bot_name, inline=False)
        embed.add_field(name="Context", value=context, inline=False)
        embed.add_field(name="Total Errors", value=str(self.error_count), inline=True)
        embed.add_field(name="Error Type", value=type(error).__name__, inline=True)
        embed.add_field(name="Traceback", value=error_text[:1021] + "..." if len(error_text) > 1024 else error_text, inline=False)

        await self.send_embed(embed)

    async def report_error(self, error, context: str = "Unknown"):
        self.error_count += 1

        if isinstance(error, Exception):
            error_text = "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        else:
            error_text = str(error)

        embed = disnake.Embed(
            title="Unhandled Error",
            color=disnake.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Bot", value=self.bot_name, inline=False)
        embed.add_field(name="Context", value=context, inline=False)
        embed.add_field(name="Total Errors", value=str(self.error_count), inline=True)
        embed.add_field(name="Error Type", value=type(error).__name__, inline=True)

        if len(error_text) > 1024:
            error_text = "..." + error_text[-1021:]  # 1021 + 3 dots = 1024

        embed.add_field(name="Traceback", value=error_text, inline=False)

        await self.send_embed(embed)

    async def leave_report(self, guild, inviter):

        server_name = guild.name
        server_id = guild.id
        owner_id = guild.owner_id
        member_count = guild.member_count
        channels = len(guild.channels)
        owner_name = guild.get_member(owner_id)
        guild_created = guild.created_at.strftime("%Y-%m-%d %H:%M UTC")
        test_create = guild.created_at
        voice_channels = len(guild.voice_channels)
        text_channels = len(guild.text_channels)

        embed = disnake.Embed(
            title=f"Unauthorized invite for {server_name}",
            color=disnake.Color.dark_blue()
        )
        embed.add_field(name="ID", value=server_id)
        embed.add_field(name="Owner", value=owner_name)
        embed.add_field(name="Member Count", value=member_count)
        embed.add_field(name="Total Channels", value=channels)
        embed.add_field(name="Voice Channel Total", value=voice_channels)
        embed.add_field(name="Text Channels", value=text_channels)
        embed.add_field(name="Guild Created", value=guild_created)
        embed.add_field(name="Added by", value=f"{inviter}")
        embed.add_field(name="Attempted Add", value=datetime.now())

        await self.log_embed(log_hook_url,embed)

    async def guild_report(self, guild):

        server_name = guild.name
        server_id = guild.id
        owner_id = guild.owner_id
        member_count = guild.member_count
        channels = len(guild.channels)
        owner_name = guild.get_member(owner_id)
        guild_created = guild.created_at.strftime("%Y-%m-%d %H:%M UTC")
        test_create = guild.created_at
        voice_channels = len(guild.voice_channels)
        text_channels = len(guild.text_channels)

        embed = disnake.Embed(
            title=f"Report for {server_name}",
            color=disnake.Color.dark_blue()
        )
        embed.add_field(name="ID", value=server_id)
        embed.add_field(name="Owner", value=owner_name)
        embed.add_field(name="Member Count", value=member_count)
        embed.add_field(name="Total Channels", value=channels)
        embed.add_field(name="Voice Channel Total", value=voice_channels)
        embed.add_field(name="Text Channels", value=text_channels)
        embed.add_field(name="Guild Created", value=guild_created)
        embed.add_field(name="Guild Created Test", value=test_create)

        await self.send_embed(embed)

#14400 = 4 hours
#7200 = 2 hours

    async def heartbeat(self, interval=7200):

        if self.heartbeat_running:
            print(f"Heartbeat already running")
            return

        while True:
            try:
                await asyncio.sleep(interval)

                rpm = self.get_rpm()

                embed = disnake.Embed(
                    title="Bot Status",
                    color=disnake.Color.blurple(),
                    timestamp=datetime.utcnow()
                )
                embed.add_field(name="Bot", value=self.bot_name)
                embed.add_field(name="Uptime", value=self.uptime(), inline=True)
                embed.add_field(name="Latency", value=self.latency(), inline=True)
                embed.add_field(name="Memory", value=self.memory(), inline=True)
                embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
                embed.add_field(name="Commands Used", value=str(self.command_count), inline=True)
                embed.add_field(name="Errors", value=str(self.error_count), inline=True)
                embed.add_field(name="Current RPM", value=f"{rpm} req/min", inline=True)
                embed.add_field(name="Peak RPM", value=f"{self.peak_rpm} req/min", inline=True)

                await self.send_embed(embed)
            except Exception as e:
                print(f"Heartbeat error: {e}")

    async def health_embed(self):

        rpm = self.get_rpm()

        embed = disnake.Embed(
            title=f"{self.bot_name} Health",
            color=disnake.Color.green(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(name="Uptime", value=self.uptime(), inline=True)
        embed.add_field(name="Latency", value=self.latency(), inline=True)
        embed.add_field(name="Memory", value=self.memory(), inline=True)
        embed.add_field(name="Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Commands Used", value=str(self.command_count), inline=True)
        embed.add_field(name="Errors", value=str(self.error_count), inline=True)
        embed.add_field(name="Current RPM", value=f"{rpm} req/min", inline=True)
        embed.add_field(name="Peak RPM", value=f"{self.peak_rpm} req/min", inline=True)
        return embed
