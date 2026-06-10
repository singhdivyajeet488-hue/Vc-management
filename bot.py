import os
import discord
from discord import app_commands
from discord.ext import commands

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN")
# ---------------------

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        print("Syncing slash commands...")
        await self.tree.sync()
        print("Slash commands synced globally!")

bot = MyBot()

# Per-guild config: { guild_id: { "hub": channel_id, "category": category_id } }
guild_config = {}

# Dictionary to keep track of active temporary channels and their owners
# { channel_id: owner_id }
active_channels = {}

# Track one channel per user: { guild_id: { user_id: channel_id } }
user_active_channel = {}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')

@bot.event
async def on_voice_state_update(member, before, after):
    config = guild_config.get(member.guild.id)

    # Case 1: Member joins the designated Hub Channel
    if after.channel and config and after.channel.id == config.get("hub"):
        guild = member.guild
        guild_user_map = user_active_channel.setdefault(guild.id, {})

        # --- ONE CHANNEL PER USER ENFORCEMENT ---
        if member.id in guild_user_map:
            existing_channel_id = guild_user_map[member.id]
            existing_channel = guild.get_channel(existing_channel_id)
            if existing_channel:
                # Move them to their existing channel instead
                await member.move_to(existing_channel)
                try:
                    embed = discord.Embed(
                        title="⚠️ You Already Have a Channel!",
                        description=f"You already own {existing_channel.mention}. You've been moved back to it.",
                        color=discord.Color.orange()
                    )
                    await existing_channel.send(embed=embed, delete_after=10)
                except Exception:
                    pass
                return
            else:
                # Channel no longer exists, clean up stale entry
                del guild_user_map[member.id]

        category = guild.get_channel(config.get("category"))
        channel_name = f"🔊 {member.display_name}'s Lounge"

        new_channel = await guild.create_voice_channel(
            name=channel_name,
            category=category,
            reason=f"Dynamic VC created for {member.name}"
        )

        active_channels[new_channel.id] = member.id
        guild_user_map[member.id] = new_channel.id

        await member.move_to(new_channel)

        embed = discord.Embed(
            title="👑 Your Personal Voice Channel is Ready!",
            description=f"Welcome to your private space, {member.mention}! You are the owner of this channel.",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="🛠️ Owner Slash Commands",
            value=(
                "`/vc lock` - Lock the channel.\n"
                "`/vc unlock` - Open the channel back up.\n"
                "`/vc kick @user` - Kick a user out.\n"
                "`/vc ban @user` - Ban a user from your channel.\n"
                "`/vc unban @user` - Unban a user from your channel.\n"
                "`/limit <number>` - Change the max player slot."
            ),
            inline=False
        )
        embed.set_footer(text="This channel will be automatically deleted when everyone leaves.")
        await new_channel.send(embed=embed)

    # Case 2: Member leaves a temporary voice channel
    if before.channel and before.channel.id in active_channels:
        vc = before.channel
        if len(vc.members) == 0:
            try:
                owner_id = active_channels.pop(vc.id, None)
                await vc.delete(reason="Temporary dynamic voice channel empty.")

                # Clean up user_active_channel map
                guild_map = user_active_channel.get(vc.guild.id, {})
                if owner_id and guild_map.get(owner_id) == vc.id:
                    del guild_map[owner_id]
            except Exception:
                pass

# --- CUSTOM CHECK FOR VC OWNER ---

async def is_vc_owner_check(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.channel, discord.VoiceChannel):
        embed = discord.Embed(
            description="❌ This command can only be used inside a temporary voice channel's chat.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False

    owner_id = active_channels.get(interaction.channel.id)
    if owner_id == interaction.user.id:
        return True

    embed = discord.Embed(
        description="⚠️ Only the **Channel Owner** can use this command!",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    return False

# --- SETUP COMMANDS ---

class SetupGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="setup", description="Configure the dynamic VC system.")

    @app_commands.command(name="hubchannel", description="Set the voice channel users join to create a new VC.")
    @app_commands.describe(channel="The 'Join to Create' voice channel")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_hub(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        config = guild_config.setdefault(interaction.guild.id, {})
        config["hub"] = channel.id
        embed = discord.Embed(
            title="✅ Hub Channel Set",
            description=f"Users will now join {channel.mention} to create their own VC.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="category", description="Set the category where new VCs will be created.")
    @app_commands.describe(category="The category for temporary voice channels")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_category(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        config = guild_config.setdefault(interaction.guild.id, {})
        config["category"] = category.id
        embed = discord.Embed(
            title="✅ Category Set",
            description=f"New voice channels will be created under **{category.name}**.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="status", description="Check the current setup configuration.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, interaction: discord.Interaction):
        config = guild_config.get(interaction.guild.id, {})
        hub_id = config.get("hub")
        cat_id = config.get("category")

        hub_mention = f"<#{hub_id}>" if hub_id else "❌ Not set"
        cat_name = interaction.guild.get_channel(cat_id).name if cat_id else "❌ Not set"

        embed = discord.Embed(title="⚙️ Current Setup", color=discord.Color.blurple())
        embed.add_field(name="Hub Channel", value=hub_mention, inline=False)
        embed.add_field(name="Category", value=cat_name, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(SetupGroup())

# --- THE /VC SUBCOMMAND GROUP ---

class VcGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="vc", description="Manage your temporary voice channel.")

    @app_commands.command(name="lock", description="Lock your channel.")
    async def lock(self, interaction: discord.Interaction):
        if not await is_vc_owner_check(interaction):
            return
        vc = interaction.channel
        await vc.set_permissions(interaction.guild.default_role, connect=False)
        embed = discord.Embed(title="🔒 Channel Locked", description="New members can no longer join.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unlock", description="Unlock your channel.")
    async def unlock(self, interaction: discord.Interaction):
        if not await is_vc_owner_check(interaction):
            return
        vc = interaction.channel
        await vc.set_permissions(interaction.guild.default_role, connect=None)
        embed = discord.Embed(title="🔓 Channel Unlocked", description="The channel is open for everyone.", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kick", description="Kick a user out of your channel.")
    @app_commands.describe(user="The user to kick")
    async def kick(self, interaction: discord.Interaction, user: discord.Member):
        if not await is_vc_owner_check(interaction):
            return
        vc = interaction.channel
        if user not in vc.members:
            return await interaction.response.send_message(f"❌ {user.mention} is not in your VC.", ephemeral=True)
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot kick yourself!", ephemeral=True)
        await user.move_to(None)
        embed = discord.Embed(title="👟 User Disconnected", description=f"{user.mention} has been kicked from the VC.", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Ban a user from rejoining your channel.")
    @app_commands.describe(user="The user to ban")
    async def ban(self, interaction: discord.Interaction, user: discord.Member):
        if not await is_vc_owner_check(interaction):
            return
        vc = interaction.channel
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot ban yourself!", ephemeral=True)
        await vc.set_permissions(user, connect=False)
        if user in vc.members:
            await user.move_to(None)
        embed = discord.Embed(title="🚫 User Banned from VC", description=f"{user.mention} has been banned and kicked.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Unban a user from your channel.")
    @app_commands.describe(user="The user to unban")
    async def unban(self, interaction: discord.Interaction, user: discord.Member):
        if not await is_vc_owner_check(interaction):
            return
        vc = interaction.channel

        # Check if user actually has a permission overwrite on this channel
        overwrite = vc.overwrites_for(user)
        if overwrite.connect is not False:
            return await interaction.response.send_message(
                f"❌ {user.mention} isn't banned from this channel.",
                ephemeral=True
            )

        # Remove the connect=False overwrite entirely
        await vc.set_permissions(user, overwrite=None)
        embed = discord.Embed(
            title="✅ User Unbanned",
            description=f"{user.mention} can now rejoin the channel.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

bot.tree.add_command(VcGroup())

# --- THE STANDALONE /LIMIT COMMAND ---

@bot.tree.command(name="limit", description="Change the max player slot (0 for unlimited).")
@app_commands.describe(number="User limit between 0 and 99")
async def limit_vc(interaction: discord.Interaction, number: int):
    if not await is_vc_owner_check(interaction):
        return
    if number < 0 or number > 99:
        embed = discord.Embed(description="❌ Limit must be between `0` and `99`.", color=discord.Color.red())
        return await interaction.response.send_message(embed=embed, ephemeral=True)
    vc = interaction.channel
    await vc.edit(user_limit=number)
    status = f"set to **{number}** users" if number > 0 else "**removed** (Unlimited)"
    embed = discord.Embed(title="👥 User Limit Updated", description=f"The player limit has been {status}.", color=discord.Color.blue())
    await interaction.response.send_message(embed=embed)

bot.run(TOKEN)
