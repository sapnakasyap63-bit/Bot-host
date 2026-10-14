import discord
from discord.ext import commands, tasks
import datetime
import os
import subprocess
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- Render 24/7 Web Server ---
app = Flask('')
@app.route('/')
def home(): 
    return "Complete Discord + Minecraft System Online!"

def run(): 
    app.run(host='0.0.0.0', port=8080)

def keep_alive(): 
    Thread(target=run).start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.invites = True  
bot = commands.Bot(command_prefix=r"\$", intents=intents) # 👈 Syntax Warning Fix here

# ⚙️ SETTINGS: Apne Server ki IDs yahan badlein
ALLOWED_GUILD_ID = 1559826100153090080  # 👈 Apna Discord Server ID daalein
ADMIN_CHANNEL_ID = 1559831974162473050 # 👈 Admin Notification Channel ID daalein
MONGO_URL = os.environ.get("MONGO_URI") # Render Environment Variables se read karega
MAX_USERS = 100

invites_cache = {}
active_processes = {}

# --- MongoDB Cloud Database Connection ---
try:
    mongo_client = MongoClient(MONGO_URL)
    db = mongo_client["afk_bot_db"]
    users_collection = db["users"]
    print("✅ Connected to MongoDB Cloud Database Successfully!")
except Exception as e:
    print(f"❌ MongoDB Connection Failed: {e}")

def get_user_data(user_id):
    user_id = str(user_id)
    data = users_collection.find_one({"_id": user_id})
    if not data:
        return {"_id": user_id, "username": "Unknown", "server_ip": "None", "expiry_date": "None", "status": "none", "total_invites": 0}
    return data

def save_user_data(user_id, update_fields):
    user_id = str(user_id)
    users_collection.update_one({"_id": user_id}, {"\$set": update_fields}, upsert=True)

def get_valid_days(invite_count):
    if invite_count >= 24: return 365
    if invite_count >= 16: return 60
    if invite_count >= 12: return 34
    if invite_count >= 8: return 23
    if invite_count >= 4: return 14
    if invite_count >= 2: return 7
    return 0

def start_minecraft_bot(user_id, server_ip):
    stop_minecraft_bot(user_id)
    bot_ign = f"AFK_{user_id[:6]}"
    bot_password = f"Pass{user_id[:5]}!"
    
    try:
        process = subprocess.Popen(
            ["node", "index.js", server_ip, bot_ign, bot_password],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        active_processes[str(user_id)] = process
        print(f"🚀 Started MC Client: {bot_ign} on Server IP: {server_ip}")
    except Exception as e:
        print(f"❌ Subprocess failed: {e}")

def stop_minecraft_bot(user_id):
    uid = str(user_id)
    if uid in active_processes:
        process = active_processes[uid]
        process.terminate()
        del active_processes[uid]
        print(f"🛑 Minecraft AFK Bot stopped for User {uid}")

# --- Auto Invite Tracking ---
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
    
    # Render Restart hone par sabhi active players ke Minecraft Bots firse run karein
    try:
        active_users = users_collection.find({"status": "active"})
        for user_info in active_users:
            start_minecraft_bot(user_info["_id"], user_info["server_ip"])
    except: pass

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
        inviter_id = str(inviter_user.id)
        current_data = get_user_data(inviter_id)
        new_invites_count = current_data.get("total_invites", 0) + 1
        save_user_data(inviter_id, {"username": inviter_user.name, "total_invites": new_invites_count})

# --- ⏰ Cloud Data Expiry Loop (Runs every minute) ---
@tasks.loop(minutes=1)
async def check_expirations():
    await bot.wait_until_ready()
    now = datetime.datetime.now()
    admin_channel = bot.get_channel(ADMIN_CHANNEL_ID)
    
    try:
        active_users = users_collection.find({"status": "active"})
        for info in active_users:
            user_id = info["_id"]
            if info.get("expiry_date") != "None":
                expiry_time = datetime.datetime.strptime(info["expiry_date"], "%Y-%m-%d %H:%M:%S")
                if now >= expiry_time:
                    save_user_data(user_id, {"status": "expired"})
                    stop_minecraft_bot(user_id)
                    
                    if admin_channel:
                        embed = discord.Embed(title="⚠️ VALID DONE / ACCESS EXPIRED", color=discord.Color.red())
                        embed.add_field(name="User Name", value=f"**{info['username']}** (<@{user_id}>)", inline=False)
                        embed.add_field(name="Server IP", value=info["server_ip"], inline=True)
                        embed.add_field(name="Status", value="🚫 OFFLINE / ACCESS REVOKED", inline=True)
                        await admin_channel.send(embed=embed)
    except: pass

def is_allowed_server():
    async def predicate(ctx): return ctx.guild and ctx.guild.id == ALLOWED_GUILD_ID
    return commands.check(predicate)

# --- COMMANDS ---
@bot.command()
@is_allowed_server()
async def claim(ctx, *, ip: str = None):
    if not ip or not ip.startswith("ip:"):
        await ctx.send("❌ Sahi tarika: `$claim ip: ://ip.com`")
        return
        
    server_ip = ip.replace("ip:", "").strip()
    user = ctx.author
    user_id = str(user.id)
    
    user_data = get_user_data(user_id)
    user_invites = user_data.get("total_invites", 0)
    days = get_valid_days(user_invites)
    
    if days == 0:
        await ctx.send(f"❌ {user.mention}, bot claim karne ke liye kam se kam 2 invites chahiye! Aapke paas abhi **{user_invites}** invites hain.")
        return

    active_count = users_collection.count_documents({"status": "active"})
    if active_count >= MAX_USERS:
        await ctx.send("❌ Sorry! Hamaare paas abhi slots full hain (100/100).")
        return

    expiry_datetime = datetime.datetime.now() + datetime.timedelta(days=days)
    expiry_str = expiry_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
    save_user_data(user_id, {
        "username": user.name, 
        "server_ip": server_ip, 
        "expiry_date": expiry_str, 
        "status": "active"
    })
    
    start_minecraft_bot(user_id, server_ip)
    
    success_msg = "✅ Successfully bot request sended pls wait and check bot information."
    await ctx.send(f"{user.mention} {success_msg}")
    try: await user.send(success_msg)
    except: pass

@bot.command()
@is_allowed_server()
async def upgrade(ctx, *, details: str = None):
    if not details:
        await ctx.send("❌ Format: `$upgrade [details]`")
        return
    user = ctx.author
    user_data = get_user_data(user.id)
    user_invites = user_data.get("total_invites", 0)
    
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
