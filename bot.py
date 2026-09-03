from datetime import datetime
import os
import random
import time
import asyncio
import re
import json
import urllib.request
import urllib.error
import threading
from collections import defaultdict
import psutil

# --- [1. iOS / a-Shell 用のエラー回避設定] ---
import types
mock_audioop = types.ModuleType("audioop")
sys_modules = sys.modules if 'sys' in globals() else {}
import sys
sys.modules["audioop"] = mock_audioop
sys.modules["audioop._audioop"] = mock_audioop

import discord
from discord import app_commands
from discord.ext import commands, tasks
from aiohttp import web

# =========================================================
# ⚙️ 初期設定 ＆ クラウドデータベース (JSONBin.io) 設定
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", ""))
JSONBIN_KEY = os.getenv("JSONBIN_KEY", "")
JSONBIN_BIN_ID = os.getenv("JSONBIN_BIN_ID", "")
JSONBIN_URL = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"

# 稼働時間・統計用
start_time = time.time()
ng_count = 0

log_channels = {
    "audit": 1436724897681510430,
    "join": 1436724863640273078,
    "level": 1534827182499823646,
    "security": 1436724949870973149,
    "welcome": 1343233372482437140,
    "meigen": 0
}

welcome_message_template = "ようこそ {user} さん！HER Group サーバーへ！"

# ---------------------------------------------------------
# 詳細設定オブジェクト（JSONBin同期用 defaults）
# ---------------------------------------------------------
bot_config = {
    "ng_words": ["スパムテスト", "荒らし", "ngword"],
    "spam_max_msgs": 5,
    "spam_window_sec": 5,
    "spam_max_mentions": 5,
    "exp_min_len": 5,
    "exp_cooldown": 60,
    "exp_min": 10,
    "exp_max": 25,
    "vc_exp": 5
}

# 予約メッセージを保持するリスト
scheduled_messages = []

# --- ☁️ クラウドデータ同期関数 ---
def load_cloud_data():
    global welcome_message_template, bot_config, scheduled_messages
    if not JSONBIN_KEY or not JSONBIN_BIN_ID:
        print("⚠️ JSONBINの鍵が設定されていないため、ローカルメモリで起動します。")
        return {}, []

    req = urllib.request.Request(
        JSONBIN_URL,
        headers={"X-Master-Key": JSONBIN_KEY}
    )
    try:
        with urllib.request.urlopen(req) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                record = data.get("record", {})
                xp_data = {int(k): v for k, v in record.get("user_xp", {}).items()}
                meigen_data = record.get("meigen_list", [])
                
                saved_channels = record.get("log_channels", {})
                for k, v in saved_channels.items():
                    log_channels[k] = int(v)

                welcome_message_template = record.get("welcome_message", welcome_message_template)
                
                saved_config = record.get("bot_config", {})
                bot_config.update(saved_config)

                saved_schedules = record.get("scheduled_messages", [])
                for item in saved_schedules:
                    scheduled_messages.append({
                        "channel_id": int(item["channel_id"]),
                        "message": item["message"],
                        "scheduled_time": datetime.strptime(item["scheduled_time"], "%Y-%m-%d %H:%M"),
                        "sent": item["sent"],
                        "user": item.get("user", "Admin")
                    })

                print("☁️ クラウドからデータを読み込みました！")
                return xp_data, meigen_data
    except Exception as e:
        print(f"❌ クラウド読み込みエラー: {e}")
    return {}, []

def save_cloud_data():
    if not JSONBIN_KEY or not JSONBIN_BIN_ID:
        return

    serializable_schedules = []
    for item in scheduled_messages:
        serializable_schedules.append({
            "channel_id": item["channel_id"],
            "message": item["message"],
            "scheduled_time": item["scheduled_time"].strftime("%Y-%m-%d %H:%M"),
            "sent": item["sent"],
            "user": item.get("user", "Admin")
        })

    payload = json.dumps({
        "user_xp": {str(k): v for k, v in user_xp.items()},
        "meigen_list": meigen_list,
        "log_channels": log_channels,
        "welcome_message": welcome_message_template,
        "bot_config": bot_config,
        "scheduled_messages": serializable_schedules
    }).encode("utf-8")

    req = urllib.request.Request(
        JSONBIN_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Master-Key": JSONBIN_KEY
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req) as res:
            pass
    except Exception as e:
        print(f"❌ クラウド保存エラー: {e}")

user_xp, meigen_list = load_cloud_data()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

user_message_time = {}
user_msg_timestamps = defaultdict(list)
user_last_msg = defaultdict(lambda: {"last_msg": "", "count": 0})
vc_join_times = {}

def get_level(xp):
    level = 0
    while xp >= 100 * ((level + 1) ** 2):
        level += 1
    return level

def get_next_level_xp(level):
    return 100 * ((level + 1) ** 2)

def evaluate_weirdness(text):
    if len(text) < 4:
        return 0
    score = 0
    if re.search(r'(問[1-9一二三]|求めなさい|求めよ|ただし|とする[。 \n]|答えよ)', text):
        score += 2
    keywords = ['速度', '質量', '気体', '定数', '電離', '因果', '文脈', '筆者', '傍線部', '矛盾', '極限', '証明']
    kw_count = sum(1 for kw in keywords if kw in text)
    if kw_count >= 2:
        score += 2
    elif kw_count == 1:
        score += 1
    if re.search(r'(言いました|思った|突然|突如|こう言った|なぜなら|結果|しかし)', text) and len(text) > 20:
        score += 1
    if re.search(r'(.)\1{3,}', text):
        score += 2
    symbol_count = len(re.findall(r'[!?！？w草#$%\^&\*()_\-+=\[\]{};:\'",<>\/.?~\\\\]', text))
    if symbol_count >= 5:
        score += 2
    if re.match(r'^[ぁ-んー\s]+$', text) and len(text) >= 10:
        score += 1
    if score >= 4:
        return 5
    elif score == 3:
        return 4
    elif score == 2:
        return 3
    elif score == 1:
        return 2 if random.random() < 0.4 else 1
    if len(text) > 30 and text.count('\n') >= 2 and random.random() < 0.1:
        return 1
    return 0

# --- Web サーバー ＆ API ---
async def handle_index(request):
    try:
        if os.path.exists("index.html"):
            with open("index.html", "r", encoding="utf-8") as f:
                html_content = f.read()
                
            guilds_options = "".join([f'<option value="{g.id}">🟢 {g.name}</option>\n' for g in bot.guilds])
            if not guilds_options:
                guilds_options = '<option value="">参加中のサーバーがありません</option>'

            html_content = html_content.replace('', guilds_options)
            
            return web.Response(
                body=html_content.encode('utf-8'),
                headers={'Content-Type': 'text/html; charset=utf-8'}
            )
        else:
            return web.Response(
                body="<h1>HER Group Protector</h1><p>index.html が見つかりません。</p>".encode('utf-8'),
                headers={'Content-Type': 'text/html; charset=utf-8'},
                status=404
            )
    except Exception as e:
        return web.Response(text=f"HTMLエラー: {e}", status=500)

async def handle_schedule_page(request):
    try:
        if os.path.exists("schedule.html"):
            with open("schedule.html", "r", encoding="utf-8") as f:
                html_content = f.read()
            return web.Response(
                body=html_content.encode('utf-8'),
                headers={'Content-Type': 'text/html; charset=utf-8'}
            )
        else:
            return web.Response(
                body="<h1>Schedule Page</h1><p>schedule.html が見つかりません。</p>".encode('utf-8'),
                headers={'Content-Type': 'text/html; charset=utf-8'},
                status=404
            )
    except Exception as e:
        return web.Response(text=f"HTMLエラー: {e}", status=500)

async def get_status_api(request):
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{hours}時間 {minutes}分"

    ping_ms = round(bot.latency * 1000) if bot.latency else 0

    try:
        cpu_usage = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_usage = 0.0

    try:
        memory_usage = psutil.virtual_memory().percent
    except Exception:
        memory_usage = 0.0

    status_data = {
        "online": bot.is_ready(),
        "bot_name": bot.user.name if bot.user else "Unknown",
        "guilds_count": len(bot.guilds),
        "uptime": uptime_str,
        "ping": f"{ping_ms} ms",
        "ping_raw": ping_ms,
        "meigen_count": f"{len(meigen_list)} 件",
        "ng_count": f"{ng_count} 件",
        "cpu": cpu_usage,
        "memory": memory_usage
    }
    return web.json_response(status_data, headers={"Access-Control-Allow-Origin": "*"})

async def get_channels_api(request):
    guild_id = request.query.get('guild_id')
    channels = []
    if guild_id and guild_id.isdigit():
        guild = bot.get_guild(int(guild_id))
        if guild:
            channels = [{"id": str(ch.id), "name": ch.name} for ch in guild.text_channels]
    elif bot.guilds:
        guild = bot.guilds[0]
        channels = [{"id": str(ch.id), "name": ch.name} for ch in guild.text_channels]
    return web.json_response({"channels": channels}, headers={"Access-Control-Allow-Origin": "*"})

async def get_settings_api(request):
    data = {
        "welcome_msg": welcome_message_template,
        "silent_mode": "none",
        "silent_start": "22:00",
        "silent_end": "07:00",
        "welcome_ch": str(log_channels.get("welcome", "")),
        "level_ch": str(log_channels.get("level", "")),
        "audit_ch": str(log_channels.get("audit", "")),
        "security_ch": str(log_channels.get("security", "")),
        "meigen_ch": str(log_channels.get("meigen", "")),
        
        "ng_words": ",".join(bot_config.get("ng_words", [])),
        "spam_max_msgs": bot_config.get("spam_max_msgs", 5),
        "spam_window_sec": bot_config.get("spam_window_sec", 5),
        "spam_max_mentions": bot_config.get("spam_max_mentions", 5),
        "exp_min_len": bot_config.get("exp_min_len", 5),
        "exp_cooldown": bot_config.get("exp_cooldown", 60),
        "exp_min": bot_config.get("exp_min", 10),
        "exp_max": bot_config.get("exp_max", 25),
        "vc_exp": bot_config.get("vc_exp", 5)
    }
    return web.json_response(data, headers={"Access-Control-Allow-Origin": "*"})

async def save_settings_api(request):
    global welcome_message_template, bot_config
    try:
        data = await request.json()
        if "welcome_msg" in data: welcome_message_template = data["welcome_msg"]
        if "welcome_ch" in data: log_channels["welcome"] = int(data["welcome_ch"] or 0)
        if "level_ch" in data: log_channels["level"] = int(data["level_ch"] or 0)
        if "audit_ch" in data: log_channels["audit"] = int(data["audit_ch"] or 0)
        if "security_ch" in data: log_channels["security"] = int(data["security_ch"] or 0)
        if "meigen_ch" in data: log_channels["meigen"] = int(data["meigen_ch"] or 0)
        
        if "ng_words" in data:
            bot_config["ng_words"] = [w.strip() for w in data["ng_words"].split(",") if w.strip()]
        
        if "spam_max_msgs" in data: bot_config["spam_max_msgs"] = int(data["spam_max_msgs"])
        if "spam_window_sec" in data: bot_config["spam_window_sec"] = int(data["spam_window_sec"])
        if "spam_max_mentions" in data: bot_config["spam_max_mentions"] = int(data["spam_max_mentions"])
        if "exp_min_len" in data: bot_config["exp_min_len"] = int(data["exp_min_len"])
        if "exp_cooldown" in data: bot_config["exp_cooldown"] = int(data["exp_cooldown"])
        if "exp_min" in data: bot_config["exp_min"] = int(data["exp_min"])
        if "exp_max" in data: bot_config["exp_max"] = int(data["exp_max"])
        if "vc_exp" in data: bot_config["vc_exp"] = int(data["vc_exp"])

        save_cloud_data()
        return web.json_response({"status": "ok"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)

async def api_get_schedules(request):
    formatted = []
    for item in scheduled_messages:
        formatted.append(
            {
                "user": item.get("user", "Admin"),
                "message": item["message"],
                "time": item["scheduled_time"].strftime("%Y-%m-%d %H:%M"),
                "sent": item["sent"],
            }
        )
    return web.json_response({"schedules": formatted}, headers={"Access-Control-Allow-Origin": "*"})

async def api_save_schedule(request):
    try:
        data = await request.json()
        if not data:
            return web.json_response({"status": "error", "message": "No data"}, status=400)

        channel_id = int(data.get("channel_id"))
        message = data.get("message")
        scheduled_time_str = data.get("scheduled_time")
        scheduled_time = datetime.strptime(scheduled_time_str, "%Y-%m-%dT%H:%M")

        scheduled_messages.append(
            {
                "channel_id": channel_id,
                "message": message,
                "scheduled_time": scheduled_time,
                "sent": False,
                "user": "Admin User",
            }
        )
        save_cloud_data()
        return web.json_response({"status": "success"}, headers={"Access-Control-Allow-Origin": "*"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)

async def start_web_server():
    port = int(os.getenv("PORT", 10000))
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)
    app.router.add_get('/schedule.html', handle_schedule_page)
    app.router.add_get('/api/status', get_status_api)
    app.router.add_get('/api/channels', get_channels_api)
    app.router.add_get('/api/settings', get_settings_api)
    app.router.add_post('/api/settings', save_settings_api)
    app.router.add_get('/api/schedule/list', api_get_schedules)
    app.router.add_post('/api/schedule/save', api_save_schedule)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"🌐 Webサーバーがポート {port} で起動しました！")
    print("--------------------------------------------------")
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        print(f"🔗 メイン設定ページ : {external_url}")
        print(f"📅 予約管理ページ   : {external_url}/schedule.html")
    else:
        print(f"🔗 メイン設定ページ : http://localhost:{port}/index.html")
        print(f"📅 予約管理ページ   : http://localhost:{port}/schedule.html")
    print("--------------------------------------------------")

class ProtectorBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def setup_hook(self):
        self.check_scheduled_messages.start()

    @tasks.loop(seconds=10)
    async def check_scheduled_messages(self):
        now = datetime.now()
        updated = False
        for item in scheduled_messages:
            if not item["sent"] and item["scheduled_time"] <= now:
                channel = self.get_channel(item["channel_id"])
                if channel:
                    try:
                        await channel.send(
                            f"📢 **【予約メッセージ】**\n{item['message']}"
                        )
                        item["sent"] = True
                        updated = True
                    except Exception as e:
                        print(f"予約メッセージの送信に失敗しました: {e}")
        if updated:
            save_cloud_data()

    @check_scheduled_messages.before_loop
    async def before_check(self):
        await self.wait_until_ready()

bot = ProtectorBot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🛡️ {bot.user.name} が起動しました！")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} 個のスラッシュコマンドを同期しました！")
    except Exception as e:
        print(f"❌ コマンド同期エラー: {e}")
        
    if not vc_exp_loop.is_running():
        vc_exp_loop.start()

@bot.event
async def on_member_join(member):
    welcome_ch = bot.get_channel(log_channels.get("welcome", 0))
    if welcome_ch:
        msg = welcome_message_template.replace("{user}", member.mention)
        await welcome_ch.send(msg)

@bot.event
async def on_message(message):
    global ng_count
    if message.author.bot or not message.guild:
        return

    author = message.author
    u_id = author.id
    current_time = time.time()

    # 1. NGワード判定
    for word in bot_config.get("ng_words", []):
        if word and word.lower() in message.content.lower():
            ng_count += 1
            try:
                await message.delete()
                await message.channel.send(f"⚠️ {author.mention} 警告: 不適切な言葉が含まれていたため削除しました。", delete_after=5)
            except discord.Forbidden:
                pass

            sec_channel = bot.get_channel(log_channels.get("security", 0))
            if sec_channel:
                embed = discord.Embed(title="🚨 NGワード検知", color=0xFF0000)
                embed.add_field(name="ユーザー", value=author.mention, inline=True)
                embed.add_field(name="内容", value=message.content, inline=False)
                await sec_channel.send(embed=embed)
            return

    # 2. スパム判定 (A) メンション数
    if len(message.mentions) > bot_config.get("spam_max_mentions", 5):
        try:
            await message.delete()
            await message.channel.send(f"⚠️ {author.mention} メンションが多すぎます。", delete_after=5)
        except discord.Forbidden:
            pass
        return

    # 2. スパム判定 (B) 連投速度
    timestamps = user_msg_timestamps[u_id]
    timestamps.append(current_time)
    window = bot_config.get("spam_window_sec", 5)
    user_msg_timestamps[u_id] = [t for t in timestamps if current_time - t <= window]

    if len(user_msg_timestamps[u_id]) > bot_config.get("spam_max_msgs", 5):
        try:
            await message.delete()
            await message.channel.send(f"⚠️ {author.mention} 連投を検知したためメッセージを削除しました。", delete_after=5)
        except discord.Forbidden:
            pass
        return

    # 3. 迷言判定
    weird_level = evaluate_weirdness(message.content)
    if weird_level > 0:
        if message.content not in meigen_list:
            meigen_list.append(message.content)
            save_cloud_data()
            meigen_ch = bot.get_channel(log_channels.get("meigen", 0))
            if meigen_ch:
                stars = "⭐" * weird_level
                embed = discord.Embed(
                    title="🤪 迷言を自動検知しました",
                    description=f"「 {message.content} 」",
                    color=0x9B59B6
                )
                embed.add_field(name="発言者", value=author.mention, inline=True)
                embed.add_field(name="おかしさ度", value=f"{stars} ({weird_level}/5)", inline=True)
                await meigen_ch.send(embed=embed)

    # 4. レベリング判定 (EXP付与)
    min_len = bot_config.get("exp_min_len", 5)
    cooldown = bot_config.get("exp_cooldown", 60)
    last_time = user_message_time.get(u_id, 0)

    if (current_time - last_time >= cooldown) and (len(message.content) >= min_len):
        user_message_time[u_id] = current_time
        exp_min = bot_config.get("exp_min", 10)
        exp_max = bot_config.get("exp_max", 25)
        gained_xp = random.randint(exp_min, exp_max)

        old_xp = user_xp.get(u_id, 0)
        new_xp = old_xp + gained_xp
        user_xp[u_id] = new_xp
        save_cloud_data()

        old_level = get_level(old_xp)
        new_level = get_level(new_xp)
        if new_level > old_level:
            lvl_channel = bot.get_channel(log_channels.get("level", 0))
            if lvl_channel:
                next_xp = get_next_level_xp(new_level)
                await lvl_channel.send(
                    f"🎉 {author.mention} が **Level {new_level}** にアップしました！\n"
                    f" (次のレベルまで あと `{next_xp - new_xp}` XP)"
                )

    await bot.process_commands(message)

# VC監視 ＆ EXP給付ループ
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    if before.channel is None and after.channel is not None:
        vc_join_times[member.id] = time.time()
    elif before.channel is not None and after.channel is None:
        vc_join_times.pop(member.id, None)

@tasks.loop(minutes=1.0)
async def vc_exp_loop():
    vc_xp_val = bot_config.get("vc_exp", 5)
    if vc_xp_val <= 0:
        return

    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.bot or (member.voice and (member.voice.self_mute or member.voice.deaf)):
                    continue
                if member.id in vc_join_times:
                    old_xp = user_xp.get(member.id, 0)
                    new_xp = old_xp + vc_xp_val
                    user_xp[member.id] = new_xp
                    
                    old_level = get_level(old_xp)
                    new_level = get_level(new_xp)
                    if new_level > old_level:
                        lvl_channel = bot.get_channel(log_channels.get("level", 0))
                        if lvl_channel:
                            next_xp = get_next_level_xp(new_level)
                            await lvl_channel.send(
                                f"🎉 VC通話により {member.mention} が **Level {new_level}** にアップしました！\n"
                                f" (次のレベルまで あと `{next_xp - new_xp}` XP)"
                            )
    save_cloud_data()

@bot.tree.command(name="rank", description="自分の現在のレベルとXPを確認します")
@app_commands.guild_only()
async def slash_rank(interaction: discord.Interaction):
    xp = user_xp.get(interaction.user.id, 0)
    lvl = get_level(xp)
    next_xp = get_next_level_xp(lvl)
    await interaction.response.send_message(f"📊 {interaction.user.mention} のステータス:\n・**Level**: {lvl}\n・**Total XP**: {xp}\n・**次のレベルまで**: あと `{next_xp - xp}` XP")

@bot.tree.command(name="meigen", description="迷言集からランダムで1つ表示します")
@app_commands.guild_only()
async def slash_meigen(interaction: discord.Interaction):
    if not meigen_list:
        await interaction.response.send_message("💬 まだ迷言が登録されていません！", ephemeral=True)
    else:
        selected = random.choice(meigen_list)
        embed = discord.Embed(title="💬 本日の迷言ピックアップ", description=f"「 {selected} 」", color=0x9B59B6)
        await interaction.response.send_message(embed=embed)

@bot.tree.command(name="level_reset_all", description="【管理者専用】全員のレベル・XPを一括リセットします")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_level_reset_all(interaction: discord.Interaction):
    user_xp.clear()
    save_cloud_data()
    await interaction.response.send_message("🚨 **全員のレベルおよびXPデータを全消去（リセット）しました。**")

def run_flask_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_web_server())
    loop.run_forever()

async def main():
    threading.Thread(target=run_flask_thread, daemon=True).start()
    
    if BOT_TOKEN:
        await bot.start(BOT_TOKEN)
    else:
        print("⚠️ エラー: BOT_TOKEN が設定されていません。")

if __name__ == "__main__":
    asyncio.run(main())
