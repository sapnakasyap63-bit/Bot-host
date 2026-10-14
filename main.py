import discord
from discord.ext import commands, tasks
import datetime
import json
import os
from flask import Flask
from threading import Thread

# --- Render 24/7 Web Server (Bot ko active rakhne ke liye) ---
app = Flask('')
@app.route('/')
def home(): 
    return "Discord Invite & Plan Validity Tracker is Online!"

def run(): 
    app.run(host='0.0.0.0', port=8080)

def keep_alive(): 
    Thread(target=run).start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.invites = True  
bot = commands.Bot(command_prefix=r"\$", intents=intents) # Syntax warning fix done

# ⚙️ SETTINGS: Apne Server ki IDs yahan badlein
ALLOWED_GUILD_ID = 1559826100153090080  # 👈 Apna Discord Server ID yahan daalein
ADMIN_CHANNEL_ID = 1559831974162473050  # 👈 Admin Notification Channel ID yahan daalein
DB_FILE = "database.json"
MAX_USERS = 100

invites_cache = {}

# --- Local File Database Systems ---
def load_db():
    if not os.path.exists(DB_FILE): return {}
    with open(DB_FILE, 'r') as f:
        try: return json.load(f)
        except: return {}

def save_db(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f, indent=4)

def get_valid_days(invite_count):
    if invite_count >= 24: return 365
    if invite_count >= 16: return 60
    if invite_count >= 12: return 34
    if invite_count >= 8: return 23
    if invite_count >= 4: return 14
    if invite_count >= 2: return 7
    return 0

# --- Auto Invite Tracking Events ---
async def cache_server_invites():
    guild = bot.get_guild(ALLOWED_GUILD_ID)
    if guild:
        try:
            server_invites = await guild.invites()
            invites_cache[guild.id] = {invite.code: invite.uses for invite in server_invites}
        except: pass

@bot.event
async def on_ready():
    print(f"🤖 Bot Connected As {bot.user.name}")
    keep_alive()
    await cache_server_invites()
    check_expirations.start()

@bot.event
async def on_invite_create(invite):
    if invite.guild.id == ALLOWED_GUILD_ID:
        if invite.guild.id not in invites_cache: invites_cache[invite.guild.id] = {}
        invites_cache[invite.guild.id][invite.code] = invite.uses

@bot.event
async def on_member_join(member):
    if member.guild.id != ALLOWED_GUILD_ID: return
    old_invites = invites_cache.get(member.guild.id, {})
    try: new_invites = await member.guild.invites()
    except: return

    inviter_user = None
    for invite in new_invites:
        if invite.code in old_invites and invite.uses > old_invites[invite.code]:
            inviter_user = invite.inviter
            break
    invites_cache[member.guild.id] = {invite.code: invite.uses for invite in new_invites}
    
    if inviter_user and not member.bot:
        db = load_db()
        inviter_id = str(inviter_user.id)
        if inviter_id not in db:
            db[inviter_id] = {"username": inviter_user.name, "server_ip": "None", "expiry_date": "None", "status": "none", "total_invites": 0}
        db[inviter_id]["total_invites"] += 1
        save_db(db)

# --- ⏰ Expiry Loop (Har 1 minute me check karega aur aapko alert bhejega) ---
@tasks.loop(minutes=1)
async def check_expirations():
    await bot.wait_until_ready()
    db = load_db()
    now = datetime.datetime.now()
    changed = False
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    
    for user_id, info in list(db.items()):
        if info.get("status") == "active" and info.get("expiry_date") != "None":
            expiry_time = datetime.datetime.strptime(info["expiry_date"], "%Y-%m-%d %H:%M:%S")
            if now >= expiry_time:
                db[user_id]["status"] = "expired"
                changed = True
                
                # Admin Channel me exactly alert trigger hoga
                if admin_channel:
                    embed = discord.Embed(title="⚠️ VALID DONE / ACCESS EXPIRED", color=discord.Color.red())
                    embed.add_field(name="User Name", value=f"**{info['username']}** (<@{user_id}>)", inline=False)
                    embed.add_field(name="Server IP", value=info["server_ip"], inline=True)
                    embed.add_field(name="Status", value=f"🛑 VAILD DONE USER NAME: {info['username']}", inline=False)
                    await admin_channel.send(embed=embed)
                    
    if changed: save_db(db)

def is_allowed_server():
    async def predicate(ctx): return ctx.guild and ctx.guild.id == ALLOWED_GUILD_ID
    return commands.check(predicate)

# --- USER COMMANDS ---

# 1. \$claim ip: command
@bot.command()
@is_allowed_server()
async def claim(ctx, *, ip: str = None):
    if not ip or not ip.startswith("ip:"):
        await ctx.send("❌ Sahi tarika: `$claim ip: ://ip.com`")
        return
        
    server_ip = ip.replace("ip:", "").strip()
    user = ctx.author
    db = load_db()
    user_id = str(user.id)
    
    user_invites = db.get(user_id, {}).get("total_invites", 0)
    days = get_valid_days(user_invites)
    
    if days == 0:
        await ctx.send(f"❌ {user.mention}, bot claim karne ke liye kam se kam 2 invites chahiye! Aapke paas abhi **{user_invites}** invites hain.")
        return

    # 100 Active Users check limit
    active_count = sum(1 for u in db.values() if u.get("status") == "active")
    if active_count >= MAX_USERS:
        await ctx.send("❌ Sorry! Hamaare paas abhi slots full hain (100/100). Please thoda wait karein.")
        return

    expiry_datetime = datetime.datetime.now() + datetime.timedelta(days=days)
    expiry_str = expiry_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
    if user_id not in db: db[user_id] = {"total_invites": user_invites}
    db[user_id].update({"username": user.name, "server_ip": server_ip, "expiry_date": expiry_str, "status": "active"})
    save_db(db)
    
    success_msg = "✅ Successfully bot request sended pls wait and check bot information."
    await ctx.send(f"{user.mention} {success_msg}")
    try: await user.send(success_msg)
    except: pass

    # Admin Panel Request Logger
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if admin_channel:
        embed = discord.Embed(title="🤖 New Plan Activation", color=discord.Color.green())
        embed.add_field(name="Member Name", value=f"{user.name} ({user.mention})", inline=True)
        embed.add_field(name="Total Invites Verified", value=str(user_invites), inline=True)
        embed.add_field(name="Valid Duration", value=f"{days} Days", inline=True)
        embed.add_field(name="Target Server IP", value=server_ip, inline=False)
        await admin_channel.send(embed=embed)

# 2. \$upgrade command
@bot.command()
@is_allowed_server()
async def upgrade(ctx, *, details: str = None):
    if not details:
        await ctx.send("❌ Format: `$upgrade [details]`")
        return
    user = ctx.author
    db = load_db()
    user_invites = db.get(str(user.id), {}).get("total_invites", 0)
    
    if user_invites < 2:
        await ctx.send("❌ Upgrade ke liye extra 2 invites hone chahiye.")
        return
        
    await ctx.send(f"✅ {user.mention}, aapki request admin ko bhej di gayi h.")
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if admin_channel:
        embed = discord.Embed(title="⚙️ Custom Upgrade Request", color=discord.Color.orange())
        embed.add_field(name="Member", value=user.mention, inline=True)
        embed.add_field(name="Invites", value=str(user_invites), inline=True)
        embed.add_field(name="Features", value=details, inline=False)
        await admin_channel.send(embed=embed)

# 3. Admin Custom DM command (\$dm @user embed me message)
@bot.command()
@commands.has_permissions(administrator=True)
async def dm(ctx, member: discord.Member, *, message_content: str):
    embed = discord.Embed(title="📢 Message From Administration", description=message_content, color=discord.Color.blue())
    try:
        await member.send(embed=embed)
        await ctx.send(f"✅ DM successfully sent to {member.name}.")
    except:
        await ctx.send("❌ User ka DM block/off hai.")

bot.run(os.environ.get("DISCORD_TOKEN"))
