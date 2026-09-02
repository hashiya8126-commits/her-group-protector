import sys
import types
import os
import random
import datetime
import time
import asyncio
import re
import json
import urllib.request
import urllib.error
import psutil

# --- [1. iOS / a-Shell 用のエラー回避設定] ---
mock_audioop = types.ModuleType("audioop")
sys.modules["audioop"] = mock_audioop
sys.modules["audioop._audioop"] = mock_audioop

import discord
from discord import app_commands
from discord.ext import commands
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

NG_WORDS = ["スパムテスト", "荒らし", "ngword"]

# --- ☁️ クラウドデータ同期関数 ---
def load_cloud_data():
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
                print("☁️ クラウドからデータを読み込みました！")
                return xp_data, meigen_data
    except Exception as e:
        print(f"❌ クラウド読み込みエラー: {e}")
    return {}, []

def save_cloud_data():
    if not JSONBIN_KEY or not JSONBIN_BIN_ID:
        return

    payload = json.dumps({
        "user_xp": {str(k): v for k, v in user_xp.items()},
        "meigen_list": meigen_list
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

bot = commands.Bot(command_prefix="!", intents=intents)
user_message_time = {}

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

# --- Web サーバー ＆ リアルタイムAPI ---
async def handle_index(request):
    try:
        if os.path.exists("index.html"):
            with open("index.html", "r", encoding="utf-8") as f:
                html_content = f.read()
                
            guilds_options = "".join([f'<option value="{g.id}">🟢 {g.name}</option>\n' for g in bot.guilds])
            if not guilds_options:
                guilds_options = '<option value="">参加中のサーバーがありません</option>'

            html_content = html_content.replace('<!-- SERVER_OPTIONS -->', guilds_options)
            return web.Response(text=html_content, content_type='text/html')
        else:
            return web.Response(text="<h1>HER Group Protector</h1><p>index.html が見つかりません。</p>", content_type='text/html')
    except Exception as e:
        return web.Response(text=f"HTMLエラー: {e}", status=500)

async def get_status_api(request):
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime_str = f"{hours}時間 {minutes}分"

    ping = round(bot.latency * 1000) if bot.latency else 0

    try:
        cpu_usage = psutil.cpu_percent(interval=None)
    except Exception:
        cpu_usage = 0

    status_data = {
        "online": bot.is_ready(),
        "bot_name": bot.user.name if bot.user else "Unknown",
        "guilds_count": len(bot.guilds),
        "uptime": uptime_str,
        "ping": f"{ping} ms",
        "meigen_count": f"{len(meigen_list)} 件",
        "ng_count": f"{ng_count} 件",
        "cpu": cpu_usage
    }
    return web.json_response(status_data, headers={"Access-Control-Allow-Origin": "*"})

async def start_web_server():
    port = int(os.getenv("PORT", 10000))
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)
    app.router.add_get('/api/status', get_status_api)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Webサーバーがポート {port} で起動しました！")

@bot.event
async def on_ready():
    print(f"🛡️ {bot.user.name} が起動しました！")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} 個のスラッシュコマンドを同期しました！")
    except Exception as e:
        print(f"❌ コマンド同期エラー: {e}")

@bot.event
async def on_message(message):
    global ng_count
    if message.author.bot or not message.guild:
        return

    for word in NG_WORDS:
        if word in message.content:
            ng_count += 1
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} 警告: 不適切な言葉が含まれていたため削除しました。", delete_after=5)
            sec_channel = bot.get_channel(log_channels["security"])
            if sec_channel:
                embed = discord.Embed(title="🚨 NGワード検知", color=0xFF0000)
                embed.add_field(name="ユーザー", value=message.author.mention, inline=True)
                embed.add_field(name="内容", value=message.content, inline=False)
                await sec_channel.send(embed=embed)
            return

    weird_level = evaluate_weirdness(message.content)
    if weird_level > 0:
        if message.content not in meigen_list:
            meigen_list.append(message.content)
            save_cloud_data()
            meigen_ch = bot.get_channel(log_channels["meigen"])
            if meigen_ch:
                stars = "⭐" * weird_level
                embed = discord.Embed(
                    title="🤪 迷言を自動検知しました",
                    description=f"「 {message.content} 」",
                    color=0x9B59B6
                )
                embed.add_field(name="発言者", value=message.author.mention, inline=True)
                embed.add_field(name="おかしさ度", value=f"{stars} ({weird_level}/5)", inline=True)
                await meigen_ch.send(embed=embed)

    user_id = message.author.id
    now = datetime.datetime.now()
    if user_id not in user_message_time or (now - user_message_time[user_id]).total_seconds() >= 60:
        user_message_time[user_id] = now
        if len(message.content) >= 3:
            gained_xp = random.randint(15, 25)
            old_xp = user_xp.get(user_id, 0)
            new_xp = old_xp + gained_xp
            user_xp[user_id] = new_xp
            save_cloud_data()

            old_level = get_level(old_xp)
            new_level = get_level(new_xp)
            if new_level > old_level:
                lvl_channel = bot.get_channel(log_channels["level"])
                if lvl_channel:
                    next_xp = get_next_level_xp(new_level)
                    await lvl_channel.send(
                        f"🎉 {message.author.mention} が **Level {new_level}** にアップしました！\n"
                        f" (次のレベルまで あと `{next_xp - new_xp}` XP)"
                    )

    await bot.process_commands(message)

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

async def main():
    await start_web_server()
    if BOT_TOKEN:
        await bot.start(BOT_TOKEN)
    else:
        print("⚠️ エラー: BOT_TOKEN が設定されていません。")

if __name__ == "__main__":
    asyncio.run(main())
