import sys
import types

# --- [1. iOS / a-Shell 用のエラー回避設定] ---
mock_audioop = types.ModuleType("audioop")
sys.modules["audioop"] = mock_audioop
sys.modules["audioop._audioop"] = mock_audioop

import discord
from discord.ext import commands
import datetime

# =========================================================
# ⚙️ 設定エリア（ここを変更してください）
# =========================================================

# 1. ボットのトークン
BOT_TOKEN = "import os

# --- 設定エリア ---
# 環境変数からトークンを取得（なければ直接指定のフォールバック）
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "ここにトークン")
"

# 2. ログ送信用チャンネルID（数字のみ・クォーテーションなし）
LOG_CHANNEL_AUDIT    = 1436724897681510430  # メッセージ編集・削除ログ
LOG_CHANNEL_JOIN     = 1436724863640273078  # メンバー入退出ログ（今までと同じ）
LOG_CHANNEL_LEVEL    = 1534827182499823646  # レベルアップ通知ログ
LOG_CHANNEL_SECURITY = 1436724949870973149  # セキュリティ・スパム警報ログ

# ★ようこそメッセージ専用のチャンネルID★
LOG_CHANNEL_WELCOME  = 1343233372482437140  # ようこそメッセージ専用

# 3. セキュリティ設定
NG_WORDS = ["スパムテスト", "荒らし", "ngword"]  # 検出したい単語リスト

# 4. ようこそメッセージ設定
WELCOME_ENABLE = True  # True: 有効 / False: 無効
WELCOME_TEXT = "{user} さん、**{server}** へようこそ！🎉\nルールを確認してから楽しんでくださいね！"
WELCOME_IMAGE_URL = ""  # ここに画像のURLを入れると画像付きで送信されます！（例: "https://example.com/image.jpg"）

# =========================================================
# 🤖 BOT 本体処理（ここより下は変更不要です）
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

@bot.event
async def on_ready():
    print("====================================")
    print(f"🛡️ {bot.user.name} が起動しました！")
    print("サーバーの完全保護を開始します。")
    print("====================================")

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

    # B. レベリングシステム
    user_id = message.author.id
    now = datetime.datetime.now()
    
    # スパム防止クールダウン（3秒に1回だけXP付与）
    if user_id in user_message_time:
        if (now - user_message_time[user_id]).total_seconds() < 3:
            await bot.process_commands(message)
            return

    user_message_time[user_id] = now
    old_xp = user_xp.get(user_id, 0)
    new_xp = old_xp + 10
    user_xp[user_id] = new_xp

    if get_level(new_xp) > get_level(old_xp):
        lvl_channel = bot.get_channel(LOG_CHANNEL_LEVEL)
        if lvl_channel:
            await lvl_channel.send(f"🎉 {message.author.mention} が **Level {get_level(new_xp)}** にアップしました！")

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

# --- 3. 入退出ログ ＆ ようこそメッセージ（チャンネル分離） ---
@bot.event
async def on_member_join(member):
    # A. 入退室ログ送信（従来のログ用チャンネルへ）
    join_channel = bot.get_channel(LOG_CHANNEL_JOIN)
    if join_channel:
        await join_channel.send(f"📥 **{member.name}** がサーバーに参加しました！")

    # B. ようこそメッセージ送信（専用チャンネル 1343233372482437140 へ）
    if WELCOME_ENABLE:
        welcome_channel = bot.get_channel(LOG_CHANNEL_WELCOME)
        if welcome_channel:
            # {user} と {server} を実際の値に置き換え
            msg_text = WELCOME_TEXT.replace("{user}", member.mention).replace("{server}", member.guild.name)
            
            # 画像URLが設定されている場合は埋め込み（Embed）で送信
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
                # 画像がない場合はテキストのみで送信
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
