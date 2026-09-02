import sys
import types
import os
import random
import datetime
import asyncio
import re

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

BOT_TOKEN = os.getenv("BOT_TOKEN", os.getenv("DISCORD_TOKEN", ""))

# ログ用・通知用チャンネルID
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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

user_xp = {}
user_message_time = {}

# --- レベル計算式 ---
def get_level(xp):
    level = 0
    while xp >= 100 * ((level + 1) ** 2):
        level += 1
    return level

def get_next_level_xp(level):
    return 100 * ((level + 1) ** 2)


# --- 🤪 意味のわからない文章（深夜テンション・シュール構文）の自動判定 ---
def evaluate_weirdness(text):
    if len(text) < 4:
        return 0

    score = 0
    
    # 1. 前半と後半の飛躍・ミスマッチ（「問一：〜を求めよ」「〜とする」「ただし〜」など問題文風の文体）
    if re.search(r'(問[1-9一二三]|求めなさい|求めよ|ただし|とする[。 \n]|答えよ)', text):
        score += 2

    # 2. 脈絡のない専門用語・難解表現（数学、国語問題、物理、哲学風などのミックス）
    keywords = ['速度', '質量', '気体', '定数', '電離', '因果', '文脈', '筆者', '傍線部', '矛盾', '極限', '証明']
    kw_count = sum(1 for kw in keywords if kw in text)
    if kw_count >= 2:
        score += 2
    elif kw_count == 1:
        score += 1

    # 3. 感情・状況の急展開（日常系からの不条理な展開）
    if re.search(r'(言いました|思った|突然|突如|こう言った|なぜなら|結果|しかし)', text) and len(text) > 20:
        score += 1

    # 4. 短文の深夜テンション（文字の連続、カオスな記号乱用）
    if re.search(r'(.)\1{3,}', text):
        score += 2
    
    symbol_count = len(re.findall(r'[!?！？w草#$%\^&\*()_\-+=\[\]{};:\'",<>\/.?~\\\\]', text))
    if symbol_count >= 5:
        score += 2

    # 5. ひらがな多め・文章のアンバランスさ（物語調・つぶやき風のシュールさ）
    if re.match(r'^[ぁ-んー\s]+$', text) and len(text) >= 10:
        score += 1

    # --- スコアを ★1〜5 の評価に変換 ---
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


# --- Web サーバー ＆ API 処理 ---
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
    status_data = {
        "online": bot.is_ready(),
        "bot_name": bot.user.name if bot.user else "Unknown",
        "guilds_count": len(bot.guilds)
    }
    return web.json_response(status_data, headers={"Access-Control-Allow-Origin": "*"})

async def get_guilds_api(request):
    guilds_data = [{"id": str(g.id), "name": g.name, "icon": str(g.icon.url) if g.icon else None} for g in bot.guilds]
    return web.json_response(guilds_data, headers={"Access-Control-Allow-Origin": "*"})

async def start_web_server():
    port = int(os.getenv("PORT", 10000))
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/index.html', handle_index)
    app.router.add_get('/api/status', get_status_api)
    app.router.add_get('/api/guilds', get_guilds_api)
    
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

# --- 📝 メッセージ編集ログ ---
@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild:
        return
    if before.content == after.content:
        return

    audit_ch = bot.get_channel(log_channels["audit"])
    if audit_ch:
        embed = discord.Embed(title="✏️ メッセージ編集", color=0xF1C40F, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="実行者", value=before.author.mention, inline=True)
        embed.add_field(name="チャンネル", value=before.channel.mention, inline=True)
        embed.add_field(name="変更前", value=before.content or "(本文なし/添付のみ)", inline=False)
        embed.add_field(name="変更後", value=after.content or "(本文なし/添付のみ)", inline=False)
        await audit_ch.send(embed=embed)

# --- 🗑️ メッセージ削除ログ ---
@bot.event
async def on_message_delete(message):
    if message.author.bot or not message.guild:
        return

    audit_ch = bot.get_channel(log_channels["audit"])
    if audit_ch:
        embed = discord.Embed(title="🗑️ メッセージ削除", color=0xE74C3C, timestamp=datetime.datetime.now(datetime.timezone.utc))
        embed.add_field(name="送信者", value=message.author.mention, inline=True)
        embed.add_field(name="チャンネル", value=message.channel.mention, inline=True)
        embed.add_field(name="削除された内容", value=message.content or "(削除されました / 添付ファイルのみ)", inline=False)
        await audit_ch.send(embed=embed)

# --- メッセージ検知・NGワード・自動迷言ピックアップ・レベリング ---
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
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

    # B. 迷言の自動判別＆自動ピックアップ
    weird_level = evaluate_weirdness(message.content)
    if weird_level > 0:
        if message.content not in meigen_list:
            meigen_list.append(message.content)
            
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

    # C. レベリング
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

# 権限エラーハンドラ
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ このコマンドを実行するには**管理者権限**が必要です。", ephemeral=True)
    else:
        await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ このコマンドを実行するには**管理者権限**が必要です。")

# =========================================================
# 👤 一般ユーザー用コマンド
# =========================================================

# ランク確認
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

# 迷言閲覧
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

# NGワードリスト閲覧
@bot.tree.command(name="ng_list", description="NGワードの一覧を表示します")
@app_commands.guild_only()
async def slash_ng_list(interaction: discord.Interaction):
    await interaction.response.send_message(f"🚫 現在のNGワード: {', '.join(f'`{w}`' for w in NG_WORDS)}")

@bot.command(name="ng_list")
@commands.guild_only()
async def prefix_ng_list(ctx):
    await ctx.send(f"🚫 現在のNGワード: {', '.join(f'`{w}`' for w in NG_WORDS)}")


# =========================================================
# 👑 管理者限定コマンド
# =========================================================

# 全員のレベル一括リセット（管理者専用）
@bot.tree.command(name="level_reset_all", description="【管理者専用】全員のレベル・XPを一括で0にリセットします")
@app_commands.guild_only()
@app_commands.checks.has_permissions(administrator=True)
async def slash_level_reset_all(interaction: discord.Interaction):
    user_xp.clear()
    await interaction.response.send_message("🚨 **全員のレベルおよびXPデータを全消去（リセット）しました。**")

@bot.command(name="level_reset_all")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def prefix_level_reset_all(ctx):
    user_xp.clear()
    await ctx.send("🚨 **全員のレベルおよびXPデータを全消去（リセット）しました。**")

# 単体レベルリセット（管理者専用）
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

# チャンネル設定（管理者専用）
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


# メイン起動処理
async def main():
    await start_web_server()
    if BOT_TOKEN:
        await bot.start(BOT_TOKEN)
    else:
        print("⚠️ エラー: BOT_TOKEN が設定されていません。")

if __name__ == "__main__":
    asyncio.run(main())
