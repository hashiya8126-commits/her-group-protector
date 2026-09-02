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
from discord import app_commands
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
def get_level(xp):
    level = 0
    while xp >= 100 * ((level + 1) ** 2):
        level += 1
    return level

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
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} 個のスラッシュコマンドを同期しました！")
    except Exception as e:
        print(f"❌ コマンド同期エラー: {e}")
        
    bot.loop.create_task(start_web_server())

# --- 📌 リアクション追加時の処理 ---
@bot.event
async def on_raw_reaction_add(payload):
    if not payload.guild_id:  # DM無視
        return
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
    if message.author.bot or not message.guild:  # BotとDMを無視
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

    # B. レベリング
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

# 権限エラーハンドラ（スラッシュコマンド用）
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ このコマンドを実行するには**管理者権限**が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)

# 権限エラーハンドラ（!コマンド用）
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ このコマンドを実行するには**管理者権限**が必要です。")
    elif isinstance(error, commands.NoPrivateMessage):
        await ctx.send("❌ このコマンドはDMでは使用できません。")

# =========================================================
# 👤 一般ユーザー用コマンド（自分の情報・閲覧）
# =========================================================

# 1. 自分のランク・XP確認
@bot.tree.command(name="rank", description="自分の現在のレベルとXPを確認します")
@app_commands.guild_only()
async def slash_rank(interaction: discord.Interaction):
    xp = user_xp.get(interaction.user.id, 0)
    lvl = get_level(xp)
    next_xp = get_next_level_xp(lvl)
    await interaction.response.send_message(f"📊 {interaction.user.mention} のステータス:\n・**Level**: {lvl}\n・**Total XP**: {xp}\n・**次のレベルまで**: あと `{next_xp - xp}` XP")

@bot.command(name="rank")
@commands.guild_only()
async def prefix_rank(ctx):
    xp = user_xp.get(ctx.author.id, 0)
    lvl = get_level(xp)
    next_xp = get_next_level_xp(lvl)
    await ctx.send(f"📊 {ctx.author.mention} のステータス:\n・**Level**: {lvl}\n・**Total XP**: {xp}\n・**次のレベルまで**: あと `{next_xp - xp}` XP")

# 2. 迷言ピックアップ
@bot.tree.command(name="meigen", description="迷言集からランダムで1つ表示します")
@app_commands.guild_only()
async def slash_meigen(interaction: discord.Interaction):
    if not meigen_list:
        await interaction.response.send_message("💬 まだ迷言が登録されていません！", ephemeral=True)
    else:
        selected = random.choice(meigen_list)
        embed = discord.Embed(title="💬 本日の迷言ピックアップ", description=f"「 {selected} 」", color=0x9B59B6)
        await interaction.response.send_message(embed=embed)

@bot.command(name="meigen")
@commands.guild_only()
async def prefix_meigen(ctx):
    if not meigen_list:
        await ctx.send("💬 まだ迷言が登録されていません！")
    else:
        selected = random.choice(meigen_list)
        embed = discord.Embed(title="💬 本日の迷言ピックアップ", description=f"「 {selected} 」", color=0x9B59B6)
        await ctx.send(embed=embed)

# 3. 各種リスト確認
@bot.tree.command(name="emoji_list", description="迷言判定用の絵文字一覧を表示します")
@app_commands.guild_only()
async def slash_emoji_list(interaction: discord.Interaction):
    await interaction.response.send_message(f"😀 現在の迷言判定用絵文字: {' '.join(MEIGEN_EMOJIS)}")

@bot.command(name="emoji_list")
@commands.guild_only()
async def prefix_emoji_list(ctx):
    await ctx.send(f"😀 現在の迷言判定用絵文字: {' '.join(MEIGEN_EMOJIS)}")

@bot.tree.command(name="ng_list", description="NGワードの一覧を表示します")
@app_commands.guild_only()
async def slash_ng_list(interaction: discord.Interaction):
    await interaction.response.send_message(f"🚫 現在のNGワード: {', '.join(f'`{w}`' for w in NG_WORDS)}")

@bot.command(name="ng_list")
@commands.guild_only()
async def prefix_ng_list(ctx):
    await ctx.send(f"🚫 現在のNGワード: {', '.join(f'`{w}`' for w in NG_WORDS)}")


# =========================================================
# 👑 管理者限定コマンド（Administrator必須）
# =========================================================

# 1. 迷言の手動追加
@bot.tree.command(name="meigen_add", description="【管理者専用】文章を指定して迷言集に追加します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_meigen_add(interaction: discord.Interaction, text: str):
    if text not in meigen_list:
        meigen_list.append(text)
        await interaction.response.send_message(f"✅ 「{text}」 を迷言集に追加しました！")
    else:
        await interaction.response.send_message("⚠️ 既に登録されています。", ephemeral=True)

@bot.command(name="meigen_add")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_meigen_add(ctx):
    if ctx.message.reference:
        ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if ref_msg.content and ref_msg.content not in meigen_list:
            meigen_list.append(ref_msg.content)
            await ctx.send(f"✅ 「{ref_msg.content}」 を迷言集に追加しました！")
        else:
            await ctx.send("⚠️ 既に登録されているか、本文が空です。")
    else:
        await ctx.send("⚠️ 迷言にしたいメッセージに返信（リプライ）しながら `!meigen_add` と入力してください！")

# 2. 絵文字管理
@bot.tree.command(name="emoji_add", description="【管理者専用】迷言判定用絵文字を追加します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_emoji_add(interaction: discord.Interaction, emoji: str):
    if emoji not in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.append(emoji)
        await interaction.response.send_message(f"✅ 絵文字 「{emoji}」 を追加しました。")
    else:
        await interaction.response.send_message("⚠️ 既に登録されています。", ephemeral=True)

@bot.command(name="emoji_add")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_emoji_add(ctx, emoji: str):
    if emoji not in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.append(emoji)
        await ctx.send(f"✅ 絵文字 「{emoji}」 を追加しました。")

@bot.tree.command(name="emoji_del", description="【管理者専用】迷言判定用絵文字を削除します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_emoji_del(interaction: discord.Interaction, emoji: str):
    if emoji in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.remove(emoji)
        await interaction.response.send_message(f"🗑️ 絵文字 「{emoji}」 を削除しました。")
    else:
        await interaction.response.send_message("⚠️ リストにありません。", ephemeral=True)

@bot.command(name="emoji_del")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_emoji_del(ctx, emoji: str):
    if emoji in MEIGEN_EMOJIS:
        MEIGEN_EMOJIS.remove(emoji)
        await ctx.send(f"🗑️ 絵文字 「{emoji}」 を削除しました。")

# 3. NGワード管理
@bot.tree.command(name="ng_add", description="【管理者専用】NGワードを追加します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_ng_add(interaction: discord.Interaction, word: str):
    if word not in NG_WORDS:
        NG_WORDS.append(word)
        await interaction.response.send_message(f"✅ NGワードに「**{word}**」を追加しました。")

@bot.command(name="ng_add")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_ng_add(ctx, *, word: str):
    if word not in NG_WORDS:
        NG_WORDS.append(word)
        await ctx.send(f"✅ NGワードに「**{word}**」を追加しました。")

@bot.tree.command(name="ng_del", description="【管理者専用】NGワードを削除します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_ng_del(interaction: discord.Interaction, word: str):
    if word in NG_WORDS:
        NG_WORDS.remove(word)
        await interaction.response.send_message(f"🗑️ NGワード「**{word}**」を削除しました。")

@bot.command(name="ng_del")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_ng_del(ctx, *, word: str):
    if word in NG_WORDS:
        NG_WORDS.remove(word)
        await ctx.send(f"🗑️ NGワード「**{word}**」を削除しました。")

# 4. チャンネル設定
@bot.tree.command(name="set_channel", description="【管理者専用】通知用チャンネルを設定します")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_set_channel(interaction: discord.Interaction, channel_type: str):
    if channel_type in log_channels:
        log_channels[channel_type] = interaction.channel_id
        await interaction.response.send_message(f"⚙️ **{channel_type}** 用チャンネルを {interaction.channel.mention} に設定しました！")
    else:
        await interaction.response.send_message(f"⚠️ 無効です。指定可能: `{', '.join(log_channels.keys())}`", ephemeral=True)

@bot.command(name="set_channel")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_set_channel(ctx, channel_type: str):
    if channel_type in log_channels:
        log_channels[channel_type] = ctx.channel.id
        await ctx.send(f"⚙️ **{channel_type}** 用チャンネルを {ctx.channel.mention} に設定しました！")

# 5. レベルリセット
@bot.tree.command(name="level_reset", description="【管理者専用】指定ユーザーのレベルをリセットします")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_level_reset(interaction: discord.Interaction, member: discord.Member):
    user_xp[member.id] = 0
    await interaction.response.send_message(f"🔄 {member.mention} のXPをリセットしました。")

@bot.command(name="level_reset")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_level_reset(ctx, member: discord.Member):
    user_xp[member.id] = 0
    await ctx.send(f"🔄 {member.mention} のXPをリセットしました。")

bot.run(BOT_TOKEN)
