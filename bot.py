import sys
import types
import os

# --- [1. iOS / a-Shell 用のエラー回避設定] ---
mock_audioop = types.ModuleType("audioop")
sys.modules["audioop"] = mock_audioop
sys.modules["audioop._audioop"] = mock_audioop

import discord
from discord.ext import commands
from aiohttp import web
import datetime
import asyncio

# =========================================================
# ⚙️ 設定エリア
# =========================================================

# 1. ボットのトークン（Renderの環境変数 DISCORD_TOKEN から読み込み）
BOT_TOKEN = os.getenv("DISCORD_TOKEN")

# 2. ログ送信用チャンネルID
LOG_CHANNEL_AUDIT    = 1436724897681510430  # メッセージ編集・削除ログ
LOG_CHANNEL_JOIN     = 1436724863640273078  # メンバー入退出ログ
LOG_CHANNEL_LEVEL    = 1534827182499823646  # レベルアップ通知ログ
LOG_CHANNEL_SECURITY = 1436724949870973149  # セキュリティ・スパム警報ログ
LOG_CHANNEL_WELCOME  = 1343233372482437140  # ようこそメッセージ専用

# 3. セキュリティ設定
NG_WORDS = ["スパムテスト", "荒らし", "ngword"]  # 検出したい単語リスト

# 4. ようこそメッセージ設定
WELCOME_ENABLE = True
WELCOME_TEXT = "{user} さん、**{server}** へようこそ！🎉\nルールを確認してから楽しんでくださいね！"
WELCOME_IMAGE_URL = ""

# =========================================================
# 🤖 BOT 本体 ＆ Web サーバー処理
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 簡易データベース（メモリ上）
user_xp = {}
user_message_time = {}

def get_level(xp):
    return int(xp ** 0.5)

# --- Web サーバー ＆ API 処理 ---
async def handle_index(request):
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
            
        guilds_options = ""
        for guild in bot.guilds:
            guilds_options += f'<option value="{guild.id}">🟢 {guild.name}</option>\n'
            
        if not guilds_options:
            guilds_options = '<option value="">参加中のサーバーがありません</option>'

        html_content = html_content.replace('<!-- SERVER_OPTIONS -->', guilds_options)
        return web.Response(text=html_content, content_type='text/html')
    except Exception as e:
        return web.Response(text=f"index.html の読み込みエラー: {e}", status=500)

async def get_guilds_api(request):
    guilds_data = []
    for guild in bot.guilds:
        guilds_data.append({
            "id": str(guild.id),
            "name": guild.name,
            "icon": str(guild.icon.url) if guild.icon else None
        })
    return web.json_response(guilds_data, headers={"Access-Control-Allow-Origin": "*"})

async def start_web_server():
    # Renderから割り当てられるポート番号を取得（デフォルト8080）
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)
    app.router.add_get('/api/guilds', get_guilds_api)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web API サーバーが起動しました (Port: {port})")

@bot.event
async def on_ready():
    print("====================================")
    print(f"🛡️ {bot.user.name} が起動しました！")
    print("サーバーの完全保護を開始します。")
    print("====================================")
    bot.loop.create_task(start_web_server())

# --- 1. メッセージ検知・セキュリティ・レベリング ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # A. セキュリティ（NGワード検知）
    for word in NG_WORDS:
        if word in message.content:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} 警告: 不適切な言葉が含まれていたため削除しました。", delete_after=5)
            
            sec_channel = bot.get_channel(LOG_CHANNEL_SECURITY)
            if sec_channel:
                embed = discord.Embed(title="🚨 NGワード検知", color=0xFF0000)
                embed.add_field(name="ユーザー", value=message.author.mention, inline=True)
                embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
                embed.add_field(name="内容", value=message.content, inline=False)
                await sec_channel.send(embed=embed)
            return

    # B. レベリングシステム（文字数に応じたXP獲得）
    user_id = message.author.id
    now = datetime.datetime.now()
    
    # クールダウンチェック（3秒に1回）
    if user_id in user_message_time:
        if (now - user_message_time[user_id]).total_seconds() < 3:
            await bot.process_commands(message)
            return

    user_message_time[user_id] = now
    
    # 文字数に応じたXP計算ルール
    msg_length = len(message.content)

    if msg_length < 3:
        gained_xp = 0  # 3文字未満は0XP
    else:
        gained_xp = min(msg_length, 100)  # 1文字=1XP（1回最大100XP）

    if gained_xp > 0:
        old_xp = user_xp.get(user_id, 0)
        new_xp = old_xp + gained_xp
        user_xp[user_id] = new_xp

        # レベルアップ判定
        if get_level(new_xp) > get_level(old_xp):
            lvl_channel = bot.get_channel(LOG_CHANNEL_LEVEL)
            if lvl_channel:
                await lvl_channel.send(f"🎉 {message.author.mention} が **Level {get_level(new_xp)}** にアップしました！（+{gained_xp} XP）")

    await bot.process_commands(message)

# --- 2. メッセージ編集・削除ログ ---
@bot.event
async def on_message_delete(message):
    if message.author.bot:
        return
    audit_channel = bot.get_channel(LOG_CHANNEL_AUDIT)
    if audit_channel:
        embed = discord.Embed(title="🗑️ メッセージ削除", color=0xFF9900)
        embed.add_field(name="送信者", value=message.author.mention, inline=True)
        embed.add_field(name="場所", value=message.channel.mention, inline=True)
        embed.add_field(name="内容", value=message.content or "（画像または埋め込み）", inline=False)
        await audit_channel.send(embed=embed)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content:
        return
    audit_channel = bot.get_channel(LOG_CHANNEL_AUDIT)
    if audit_channel:
        embed = discord.Embed(title="✏️ メッセージ編集", color=0x00FFFF)
        embed.add_field(name="送信者", value=before.author.mention, inline=True)
        embed.add_field(name="場所", value=before.channel.mention, inline=True)
        embed.add_field(name="変更前", value=before.content, inline=False)
        embed.add_field(name="変更後", value=after.content, inline=False)
        await audit_channel.send(embed=embed)

# --- 3. 入退出ログ ＆ ようこそメッセージ ---
@bot.event
async def on_member_join(member):
    join_channel = bot.get_channel(LOG_CHANNEL_JOIN)
    if join_channel:
        await join_channel.send(f"📥 **{member.name}** がサーバーに参加しました！")

    if WELCOME_ENABLE:
        welcome_channel = bot.get_channel(LOG_CHANNEL_WELCOME)
        if welcome_channel:
            msg_text = WELCOME_TEXT.replace("{user}", member.mention).replace("{server}", member.guild.name)
            
            if WELCOME_IMAGE_URL:
                embed = discord.Embed(
                    title=f"WELCOME TO {member.guild.name}!",
                    description=msg_text,
                    color=0x5865F2
                )
                embed.set_image(url=WELCOME_IMAGE_URL)
                embed.set_thumbnail(url=member.display_avatar.url)
                await welcome_channel.send(embed=embed)
            else:
                await welcome_channel.send(msg_text)

@bot.event
async def on_member_remove(member):
    join_channel = bot.get_channel(LOG_CHANNEL_JOIN)
    if join_channel:
        await join_channel.send(f"📤 **{member.name}** がサーバーから退出しました。")

# --- 4. コマンド ---
@bot.command()
async def stats(ctx):
    xp = user_xp.get(ctx.author.id, 0)
    lvl = get_level(xp)
    embed = discord.Embed(title=f"📊 {ctx.author.name} のステータス", color=0x00FF00)
    embed.add_field(name="レベル", value=f"Lv.{lvl}", inline=True)
    embed.add_field(name="獲得XP", value=f"{xp} XP", inline=True)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"🧹 {amount} 件のメッセージを削除しました。", delete_after=3)

# 起動実行
bot.run(BOT_TOKEN)
