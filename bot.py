import sys
import types
import os
import random
import datetime
import asyncio

# --- [1. iOS / a-Shell 用のエラー回避設定] ---
mock_audioop = types.ModuleType("audioop")
sys.modules["audioop"] = mock_audioop
sys.modules["audioop._audioop"] = mock_audioop

import discord
from discord.ext import commands
from aiohttp import web

# =========================================================
# ⚙️ 初期設定
# =========================================================

BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ログ用・通知用チャンネルID（コマンドで動的に変更可能）
log_channels = {
    "audit": 1436724897681510430,      # 編集・削除ログ
    "join": 1436724863640273078,       # 入退出ログ
    "level": 1534827182499823646,      # レベルアップ通知
    "security": 1436724949870973149,   # NGワード警報
    "welcome": 1343233372482437140,    # ようこそメッセージ
    "meigen": 0                        # 迷言専用チャンネル（未設定時は0）
}

# 動的データ
NG_WORDS = ["スパムテスト", "荒らし", "ngword"]
meigen_list = []  # 迷言データベース
MEIGEN_EMOJIS = ["📌", "🤣", "💀", "草"]  # 迷言判定に使う絵文字リスト

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_xp = {}
user_message_time = {}

# --- 高難易度版：レベル計算式 ---
# 必要XP = 100 * (Level ^ 2) の二次関数曲線（高レベルほど跳ね上がる）
def get_level(xp):
    level = 0
    while xp >= 100 * ((level + 1) ** 2):
        level += 1
    return level

# 次のレベルまでに必要なXPを計算
def get_next_level_xp(level):
    return 100 * ((level + 1) ** 2)

# --- Web サーバー ＆ API 処理 ---
async def handle_index(request):
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
            
        guilds_options = "".join([f'<option value="{g.id}">🟢 {g.name}</option>\n' for g in bot.guilds])
        if not guilds_options:
            guilds_options = '<option value="">参加中のサーバーがありません</option>'

        html_content = html_content.replace('<!-- SERVER_OPTIONS -->', guilds_options)
        return web.Response(text=html_content, content_type='text/html')
    except Exception as e:
        return web.Response(text=f"HTMLエラー: {e}", status=500)

async def get_guilds_api(request):
    guilds_data = [{"id": str(g.id), "name": g.name, "icon": str(g.icon.url) if g.icon else None} for g in bot.guilds]
    return web.json_response(guilds_data, headers={"Access-Control-Allow-Origin": "*"})

async def start_web_server():
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)
    app.router.add_get('/api/guilds', get_guilds_api)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

@bot.event
async def on_ready():
    print(f"🛡️ {bot.user.name} が起動しました！")
    bot.loop.create_task(start_web_server())

# --- 📌 設定された絵文字リアクションで迷言追加機能 ---
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji) in MEIGEN_EMOJIS:
        channel = bot.get_channel(payload.channel_id)
        if not channel:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            if message.content and message.content not in meigen_list:
                meigen_list.append(message.content)
                await channel.send(f"💬 {message.author.mention} の発言を迷言集に登録しました！", delete_after=5)
                
                meigen_ch = bot.get_channel(log_channels["meigen"])
                if meigen_ch:
                    embed = discord.Embed(title="💬 新しい迷言が追加されました", description=f"「 {message.content} 」\n— {message.author.mention}", color=0x9B59B6)
                    await meigen_ch.send(embed=embed)
        except Exception as e:
            print(f"迷言追加エラー: {e}")

# --- メッセージ検知・NGワード・レベリング ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # A. NGワード判定
    for word in NG_WORDS:
        if word in message.content:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} 警告: 不適切な言葉が含まれていたため削除しました。", delete_after=5)
            
            sec_channel = bot.get_channel(log_channels["security"])
            if sec_channel:
                embed = discord.Embed(title="🚨 NGワード検知", color=0xFF0000)
                embed.add_field(name="ユーザー", value=message.author.mention, inline=True)
                embed.add_field(name="内容", value=message.content, inline=False)
                await sec_channel.send(embed=embed)
            return

    # B. レベリング（高難易度版：クールタイム60秒 / 15〜25XP獲得）
    user_id = message.author.id
    now = datetime.datetime.now()
    
    if user_id not in user_message_time or (now - user_message_time[user_id]).total_seconds() >= 60:
        user_message_time[user_id] = now
        
        if len(message.content) >= 3:
            gained_xp = random.randint(15, 25)
            old_xp = user_xp.get(user_id, 0)
            new_xp = old_xp + gained_xp
            user_xp[user_id] = new_xp

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

# --- 管理コマンド群 ---

# 1. 迷言コマンド
@bot.command()
async def meigen(ctx):
    if not meigen_list:
        await ctx.send("💬 まだ迷言が登録されていません！対象メッセージに絵文字スタンプを押すか、`!meigen_add` で追加してください。")
    else:
        selected = random.choice(meigen_list)
        embed = discord.Embed(title="💬 本日の迷言ピックアップ", description=f"「 {selected} 」", color=0x9B59B6)
        
        target_ch = bot.get_channel(log_channels["meigen"]) or ctx.channel
        await target_ch.send(embed=embed)

@bot.command()
async def meigen_add(ctx):
    if ctx.message.reference:
        ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if ref_msg.content and ref_msg.content not in meigen_list:
            meigen_list.append(ref_msg.content)
            await ctx.send(f"✅ 「{ref_msg.content}」 を迷言集に追加しました！")
            
            meigen_ch = bot.get_channel(log_channels["meigen"])
            if meigen_ch and meigen_ch != ctx.channel:
                embed = discord.Embed(title="💬 新しい迷言が追加されました", description=f"「 {ref_msg.content} 」\n— {ref_msg.author.mention}", color=0x9B59B6)
                await meigen_ch.send(embed=embed)
        else:
            await ctx.send("⚠️ 既に登録されているか、本文が空のメッセージです。")
    else:
        await ctx.send("⚠️ 迷言にしたいメッセージに『返信（リプライ）』しながら `!meigen_add` と入力してください！")

# 1-2. 迷言用絵文字の管理コマンド
@bot.command()
@commands.has_permissions(manage_messages=True)
async def emoji_add(ctx, emoji: str):
    if emoji not in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.append(emoji)
        await ctx.send(f"✅ 迷言登録用の絵文字に 「{emoji}」 を追加しました。")
    else:
        await ctx.send("⚠️ 既に登録されている絵文字です。")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def emoji_del(ctx, emoji: str):
    if emoji in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.remove(emoji)
        await ctx.send(f"🗑️ 迷言登録用の絵文字から 「{emoji}」 を削除しました。")

@bot.command()
async def emoji_list(ctx):
    await ctx.send(f"😀 現在の迷言判定用絵文字: {' '.join(MEIGEN_EMOJIS)}")

# 2. NGワード追加・削除・一覧
@bot.command()
@commands.has_permissions(manage_messages=True)
async def ng_add(ctx, *, word: str):
    if word not in NG_WORDS:
        NG_WORDS.append(word)
        await ctx.send(f"✅ NGワードに「**{word}**」を追加しました。")

@bot.command()
@commands.has_permissions(manage_messages=True)
async def ng_del(ctx, *, word: str):
    if word in NG_WORDS:
        NG_WORDS.remove(word)
        await ctx.send(f"🗑️ NGワードから「**{word}**」を削除しました。")

@bot.command()
async def ng_list(ctx):
    await ctx.send(f"🚫 現在のNGワード: {', '.join(f'`{w}`' for w in NG_WORDS)}")

# 3. レベルリセット
@bot.command()
@commands.has_permissions(administrator=True)
async def level_reset(ctx, member: discord.Member):
    if member.id in user_xp:
        user_xp[member.id] = 0
        await ctx.send(f"🔄 {member.mention} のXPをリセットしました。")

@bot.command()
@commands.has_permissions(administrator=True)
async def level_reset_all(ctx):
    user_xp.clear()
    await ctx.send("💥 全ユーザーのXPとレベルをリセットしました。")

# 4. チャンネル動的設定
@bot.command()
@commands.has_permissions(administrator=True)
async def set_channel(ctx, channel_type: str):
    if channel_type in log_channels:
        log_channels[channel_type] = ctx.channel.id
        await ctx.send(f"⚙️ **{channel_type}** 用のチャンネルを {ctx.channel.mention} に設定しました！")
    else:
        await ctx.send(f"⚠️ 指定が無効です。設定可能キーワード: `{', '.join(log_channels.keys())}`")

bot.run(BOT_TOKEN)
