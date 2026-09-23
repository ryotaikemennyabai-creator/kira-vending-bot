# KIRA VENDING - 完全版
# 必要: Python 3.11+ / discord.py 2.4+
# Token: 環境変数 DISCORD_TOKEN に設定

import os
import json
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ext import commands

# =========================================================
# 基本設定
# =========================================================

PRODUCT_FILE = "products.json"
CONFIG_FILE = "config.json"
ORDER_FILE = "orders.json"

BOT_NAME = "キラの自動販売機"
MAX_PRODUCTS = 25

DEFAULT_PRODUCTS = {
    "コーラ": {"price": 100, "stock": 10, "emoji": "🥤", "image_url": ""},
    "お茶": {"price": 100, "stock": 10, "emoji": "🍵", "image_url": ""},
    "水": {"price": 80, "stock": 10, "emoji": "💧", "image_url": ""},
}

DEFAULT_CONFIG = {
    "purchase_channel_id": None,
    "purchase_message_id": None,
    "order_channel_id": None,
    "ticket_category_id": None,
    "archive_category_id": None,
    "panel_color": 0x5865F2,
    "panel_title": "🛒 キラの自動販売機",
    "panel_description": "下のボタンから商品を選択して購入できます。",
    "panel_image_url": "",
    "panel_thumbnail_url": "",
    "panel_footer": "KIRA VENDING • 安全にお買い物をお楽しみください",
    "shop_notice": "💳 PayPay送金URLを入力すると注文を作成します。\n🟡 支払い確認は管理者が行います。",
    "order_counter": 0,
}

# =========================================================
# JSON / 永続化
# =========================================================

def clone(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def save_json(filename, data):
    temp = filename + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp, filename)


def load_json(filename, default):
    if not os.path.exists(filename):
        save_json(filename, default)
        return clone(default)
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] {filename} の読み込みに失敗: {e}")
        save_json(filename, default)
        return clone(default)


PRODUCTS = load_json(PRODUCT_FILE, DEFAULT_PRODUCTS)
CONFIG = load_json(CONFIG_FILE, DEFAULT_CONFIG)
ORDERS = load_json(ORDER_FILE, [])

# 旧データ互換
for name, data in list(PRODUCTS.items()):
    if isinstance(data, int):
        PRODUCTS[name] = {"price": data, "stock": 10, "emoji": "🛒", "image_url": ""}
    elif not isinstance(data, dict):
        PRODUCTS[name] = {"price": 0, "stock": 0, "emoji": "🛒", "image_url": ""}
    else:
        data.setdefault("price", 0)
        data.setdefault("stock", 0)
        data.setdefault("emoji", "🛒")
        data.setdefault("image_url", "")

for key, value in DEFAULT_CONFIG.items():
    CONFIG.setdefault(key, value)

save_json(PRODUCT_FILE, PRODUCTS)
save_json(CONFIG_FILE, CONFIG)

# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 共通
# =========================================================

def is_admin(interaction: discord.Interaction):
    return bool(interaction.guild and interaction.user.guild_permissions.administrator)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def short_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def product_custom_id(name):
    return f"kira:product:{short_hash(name)}"


def order_id_custom_id(prefix, order_id):
    return f"kira:{prefix}:{order_id}"


def find_order(order_id):
    return next((o for o in ORDERS if o.get("order_id") == order_id), None)


def create_order_id():
    counter = int(CONFIG.get("order_counter", 0))
    existing = {o.get("order_id") for o in ORDERS}
    while True:
        counter += 1
        order_id = f"KIRA-{counter:05d}"
        if order_id not in existing:
            CONFIG["order_counter"] = counter
            save_json(CONFIG_FILE, CONFIG)
            return order_id


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_http_url(url):
    return url.startswith("https://") or url.startswith("http://")


def permission_problem(channel):
    if not getattr(channel, "guild", None) or not channel.guild.me:
        return "Botのメンバー情報を取得できません。"
    perms = channel.permissions_for(channel.guild.me)
    missing = []
    if not perms.view_channel:
        missing.append("チャンネルを見る")
    if not perms.send_messages:
        missing.append("メッセージを送信")
    if not perms.embed_links:
        missing.append("埋め込みリンク")
    if not perms.read_message_history:
        missing.append("メッセージ履歴を読む")
    return "不足権限: " + " / ".join(missing) if missing else None


def color_value():
    return safe_int(CONFIG.get("panel_color"), 0x5865F2)


def product_status(stock):
    return "🟢 在庫あり" if stock > 0 else "🔴 SOLD OUT"

# =========================================================
# パネル / 商品表示
# =========================================================

def create_panel_embed():
    embed = discord.Embed(
        title=CONFIG.get("panel_title", DEFAULT_CONFIG["panel_title"]),
        description=(
            CONFIG.get("panel_description", DEFAULT_CONFIG["panel_description"])
            + "\n\n"
            + CONFIG.get("shop_notice", DEFAULT_CONFIG["shop_notice"])
        ),
        color=color_value(),
    )

    lines = []
    for name, data in PRODUCTS.items():
        price = safe_int(data.get("price"))
        stock = safe_int(data.get("stock"))
        emoji = data.get("emoji") or "🛒"
        lines.append(f"{emoji} **{name}**　`{price:,}円`　{product_status(stock)} `({stock}個)`")

    if lines:
        text = "\n".join(lines)
        if len(text) > 1024:
            text = text[:1000] + "\n…"
        embed.add_field(name="🛍️ 商品一覧", value=text, inline=False)
    else:
        embed.add_field(name="🛍️ 商品一覧", value="現在販売中の商品はありません。", inline=False)

    image_url = CONFIG.get("panel_image_url", "")
    thumbnail_url = CONFIG.get("panel_thumbnail_url", "")
    if valid_http_url(image_url):
        embed.set_image(url=image_url)
    if valid_http_url(thumbnail_url):
        embed.set_thumbnail(url=thumbnail_url)

    embed.set_footer(text=CONFIG.get("panel_footer", DEFAULT_CONFIG["panel_footer"]))
    return embed


BUTTON_STYLES = [
    discord.ButtonStyle.green,
    discord.ButtonStyle.blurple,
    discord.ButtonStyle.gray,
    discord.ButtonStyle.red,
]


class ProductButton(discord.ui.Button):
    def __init__(self, name, data, index):
        stock = safe_int(data.get("stock"))
        price = safe_int(data.get("price"))
        emoji = data.get("emoji") or "🛒"
        sold_out = stock <= 0
        super().__init__(
            label=(f"{name} • SOLD OUT" if sold_out else f"{name} • {price:,}円")[:80],
            emoji=emoji,
            style=discord.ButtonStyle.gray if sold_out else BUTTON_STYLES[index % len(BUTTON_STYLES)],
            disabled=sold_out,
            custom_id=product_custom_id(name),
            row=index // 5,
        )
        self.product_name = name

    async def callback(self, interaction):
        product = PRODUCTS.get(self.product_name)
        if not product:
            return await interaction.response.send_message("❌ この商品は現在販売されていません。", ephemeral=True)
        stock = safe_int(product.get("stock"))
        if stock <= 0:
            return await interaction.response.send_message("🔴 この商品は売り切れです。", ephemeral=True)

        embed = discord.Embed(
            title=f"{product.get('emoji', '🛒')} 購入確認",
            description=(
                f"## {product.get('emoji', '🛒')} {self.product_name}\n\n"
                f"💴 **価格**\n`{safe_int(product.get('price')):,}円`\n\n"
                f"📦 **在庫**\n`{stock}個`\n\n"
                "購入を続けるとPayPay送金URLの入力画面が開きます。"
            ),
            color=color_value(),
        )
        if valid_http_url(product.get("image_url", "")):
            embed.set_image(url=product["image_url"])
        await interaction.response.send_message(
            embed=embed,
            view=PurchaseConfirmView(self.product_name),
            ephemeral=True
        )


class VendingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for index, (name, data) in enumerate(list(PRODUCTS.items())[:MAX_PRODUCTS]):
            self.add_item(ProductButton(name, data, index))

# =========================================================
# 購入フロー
# =========================================================

class PurchaseConfirmView(discord.ui.View):
    def __init__(self, product_name):
        super().__init__(timeout=120)
        self.product_name = product_name

    @discord.ui.button(label="購入する", emoji="🛒", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        product = PRODUCTS.get(self.product_name)
        if not product or safe_int(product.get("stock")) <= 0:
            return await interaction.response.send_message("🔴 売り切れです。", ephemeral=True)
        await interaction.response.send_modal(PurchaseModal(self.product_name))

    @discord.ui.button(label="キャンセル", emoji="✖️", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(
            content="購入をキャンセルしました。",
            embed=None,
            view=None
        )


class PurchaseModal(discord.ui.Modal):
    def __init__(self, product_name):
        super().__init__(title=f"{product_name}を購入")
        self.product_name = product_name
        self.url_input = discord.ui.TextInput(
            label="PayPay送金URL",
            placeholder="https://pay.paypay.ne.jp/...",
            required=True,
            max_length=500,
        )
        self.add_item(self.url_input)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        product = PRODUCTS.get(self.product_name)
        if not product:
            return await interaction.followup.send("❌ 商品がありません。", ephemeral=True)

        if safe_int(product.get("stock")) <= 0:
            return await interaction.followup.send("🔴 売り切れです。", ephemeral=True)

        paypay_url = self.url_input.value.strip()
        if not valid_http_url(paypay_url):
            return await interaction.followup.send(
                "❌ PayPay送金URLの形式が正しくありません。",
                ephemeral=True
            )

        order_id = create_order_id()
        order = {
            "order_id": order_id,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "guild_id": interaction.guild.id if interaction.guild else None,
            "product": self.product_name,
            "price": safe_int(product.get("price")),
            "paypay_url": paypay_url,
            "status": "支払い確認待ち",
            "created_at": now_iso(),
            "ticket_channel_id": None,
            "ticket_created": False,
            "notification_sent": False,
            "dm_sent": False,
        }

        # 在庫確保と注文保存を同一処理内で実行
        product["stock"] = safe_int(product.get("stock")) - 1
        ORDERS.append(order)
        save_json(ORDER_FILE, ORDERS)
        save_json(PRODUCT_FILE, PRODUCTS)

        await update_vending_panel()

        ticket = None
        try:
            ticket = await create_ticket(interaction.guild, interaction.user, order)
            if ticket:
                order["ticket_created"] = True
                save_json(ORDER_FILE, ORDERS)
        except Exception as e:
            print(f"[PURCHASE] チャット作成失敗: {repr(e)}")

        try:
            if await send_order_notification(interaction.guild, order):
                order["notification_sent"] = True
                save_json(ORDER_FILE, ORDERS)
        except Exception as e:
            print(f"[PURCHASE] 通知失敗: {repr(e)}")

        try:
            if await send_order_dm(interaction.user, order, ticket):
                order["dm_sent"] = True
                save_json(ORDER_FILE, ORDERS)
        except Exception as e:
            print(f"[PURCHASE] DM失敗: {repr(e)}")

        ticket_text = ticket.mention if ticket else "⚠️ 専用チャットを作成できませんでした。"
        await interaction.followup.send(
            "## ✅ 注文を受け付けました！\n\n"
            f"🧾 **注文番号**\n`{order_id}`\n\n"
            f"🛍️ **商品**\n{self.product_name}\n\n"
            f"💴 **価格**\n`{order['price']:,}円`\n\n"
            f"💬 **専用チャット**\n{ticket_text}\n\n"
            "🟡 **支払い確認待ち**\n"
            "管理者がPayPay送金を確認すると注文が完了します。",
            ephemeral=True,
        )

# =========================================================
# カテゴリ / チケット
# =========================================================

async def get_or_create_category(guild, config_key, name):
    category_id = CONFIG.get(config_key)
    if category_id:
        try:
            category = guild.get_channel(int(category_id)) or await guild.fetch_channel(int(category_id))
            if isinstance(category, discord.CategoryChannel):
                return category
        except Exception:
            pass

    if not guild.me or not guild.me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    category = await guild.create_category(name, reason=f"{BOT_NAME} 自動作成")
    CONFIG[config_key] = category.id
    save_json(CONFIG_FILE, CONFIG)
    return category


async def create_ticket(guild, user, order):
    if guild is None:
        raise RuntimeError("Guildが取得できません。")

    bot_member = guild.me
    if not bot_member or not bot_member.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    category = await get_or_create_category(
        guild,
        "ticket_category_id",
        "💬 購入チャット"
    )

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        bot_member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True,
        ),
        user: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
        ),
    }

    channel = await guild.create_text_channel(
        f"chat-{order['order_id'].lower()}",
        category=category,
        overwrites=overwrites,
        topic=f"{BOT_NAME} | 注文 {order['order_id']} | 購入者 {user.id}",
        reason=f"注文 {order['order_id']} の購入チャット",
    )

    perms = channel.permissions_for(bot_member)
    if not perms.view_channel or not perms.send_messages:
        await channel.delete(reason="Bot自身の権限不足")
        raise RuntimeError("作成後のチャンネルでBotの権限が不足しています。")

    order["ticket_channel_id"] = channel.id
    save_json(ORDER_FILE, ORDERS)

    embed = discord.Embed(
        title="💬 購入専用チャット",
        description=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 **注文番号**\n`{order['order_id']}`\n\n"
            f"🛍️ **商品**\n{order['product']}\n\n"
            f"💴 **価格**\n`{order['price']:,}円`\n\n"
            "🟡 **支払い確認待ち**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "管理者への質問はこちらで行えます。"
        ),
        color=color_value(),
    )
    embed.set_footer(text=f"{BOT_NAME} • {order['order_id']}")

    await channel.send(
        content=user.mention,
        embed=embed,
        view=TicketView(order["order_id"], user.id),
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    return channel

# =========================================================
# 通知 / DM
# =========================================================

async def send_order_notification(guild, order):
    if guild is None or not CONFIG.get("order_channel_id"):
        return False

    try:
        channel = guild.get_channel(int(CONFIG["order_channel_id"])) or await guild.fetch_channel(
            int(CONFIG["order_channel_id"])
        )

        if not isinstance(channel, discord.TextChannel):
            return False

        problem = permission_problem(channel)
        if problem:
            print(f"[ORDER] 権限エラー: {problem}")
            return False

        embed = discord.Embed(
            title="🛒 新しい注文が入りました",
            description=(
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 **注文番号**\n`{order['order_id']}`\n\n"
                f"👤 **購入者**\n<@{order['user_id']}>\n\n"
                f"🛍️ **商品**\n{order['product']}\n\n"
                f"💴 **金額**\n`{order['price']:,}円`\n\n"
                "🟡 **支払い確認待ち**\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            color=0xF1C40F,
        )

        embed.add_field(
            name="💳 PayPay送金URL",
            value=order["paypay_url"][:1024],
            inline=False
        )

        embed.set_footer(text=f"{BOT_NAME} • 管理画面")

        await channel.send(
            embed=embed,
            view=OrderAdminView(order["order_id"])
        )

        return True

    except Exception as e:
        print(f"[ORDER] 通知エラー: {repr(e)}")
        return False


async def send_order_dm(user, order, ticket):
    try:
        ticket_text = ticket.mention if ticket else "⚠️ 専用チャットを作成できませんでした。"

        await user.send(
            "🛒 **キラの自動販売機**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 注文番号\n`{order['order_id']}`\n\n"
            f"🛍️ 商品\n{order['product']}\n\n"
            f"💴 金額\n`{order['price']:,}円`\n\n"
            "🟡 状態\n支払い確認待ち\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💬 専用チャット\n{ticket_text}"
        )

        return True

    except Exception as e:
        print(f"[DM] DM送信エラー: {repr(e)}")
        return False

# =========================================================
# 注文操作
# =========================================================

class OrderAdminView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="支払い確認済み",
                emoji="✅",
                style=discord.ButtonStyle.green,
                custom_id=order_id_custom_id("paid", order_id)
            )
        )

        self.add_item(
            discord.ui.Button(
                label="キャンセル",
                emoji="❌",
                style=discord.ButtonStyle.red,
                custom_id=order_id_custom_id("cancel", order_id)
            )
        )


class ProcessedOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(
            discord.ui.Button(
                label="処理済み",
                style=discord.ButtonStyle.gray,
                disabled=True,
                custom_id="kira:processed"
            )
        )


class TicketView(discord.ui.View):
    def __init__(self, order_id, user_id):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.user_id = user_id

        self.add_item(
            discord.ui.Button(
                label="履歴として保存",
                emoji="🗃️",
                style=discord.ButtonStyle.blurple,
                custom_id=order_id_custom_id("archive", order_id)
            )
        )

        self.add_item(
            discord.ui.Button(
                label="チャット削除",
                emoji="🗑️",
                style=discord.ButtonStyle.red,
                custom_id=order_id_custom_id("delete", order_id)
            )
        )

        self.add_item(
            discord.ui.Button(
                label="履歴から再開",
                emoji="🔄",
                style=discord.ButtonStyle.green,
                custom_id=order_id_custom_id("reopen", order_id)
            )
        )


async def handle_ticket_action(interaction, action, order_id):
    order = find_order(order_id)

    if not order:
        return await interaction.response.send_message(
            "❌ 注文が見つかりません。",
            ephemeral=True
        )

    allowed = (
        interaction.user.id == safe_int(order.get("user_id"))
        or is_admin(interaction)
    )

    if not allowed:
        return await interaction.response.send_message(
            "🔒 権限がありません。",
            ephemeral=True
        )

    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message(
            "❌ この操作はテキストチャンネルでのみ使えます。",
            ephemeral=True
        )

    if action == "archive":
        await interaction.response.send_message(
            "🗃️ 履歴として保存しています。",
            ephemeral=True
        )

        category = await get_or_create_category(
            interaction.guild,
            "archive_category_id",
            "📁 購入履歴"
        )

        await channel.edit(
            category=category,
            name=f"history-{order_id.lower()}",
            sync_permissions=False
        )

        member = interaction.guild.get_member(
            safe_int(order["user_id"])
        )

        if member:
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=False,
                read_message_history=True
            )

        return

    if action == "delete":
        await interaction.response.send_message(
            "🗑️ このチャットを削除します。",
            ephemeral=True
        )

        await asyncio.sleep(1)

        try:
            await channel.delete(
                reason=f"注文 {order_id} のチャット削除"
            )
        except Exception as e:
            print(f"[TICKET] 削除失敗: {repr(e)}")

        return

    if action == "reopen":
        member = interaction.guild.get_member(
            safe_int(order["user_id"])
        )

        if member:
            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        category = await get_or_create_category(
            interaction.guild,
            "ticket_category_id",
            "💬 購入チャット"
        )

        await channel.edit(
            category=category,
            name=f"chat-{order_id.lower()}",
            sync_permissions=False
        )

        await interaction.response.send_message(
            "🔄 購入チャットを再開しました。",
            ephemeral=True
        )


class TicketActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"kira:(?P<action>archive|delete|reopen):(?P<order_id>KIRA-\d{5})"
):
    def __init__(self, item, action, order_id):
        super().__init__(item)
        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            item,
            match["action"],
            match["order_id"]
        )

    async def callback(self, interaction):
        await handle_ticket_action(
            interaction,
            self.action,
            self.order_id
        )


class OrderActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"kira:(?P<action>paid|cancel):(?P<order_id>KIRA-\d{5})"
):
    def __init__(self, item, action, order_id):
        super().__init__(item)
        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            item,
            match["action"],
            match["order_id"]
        )

    async def callback(self, interaction):
        if not is_admin(interaction):
            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

        order = find_order(self.order_id)

        if not order:
            return await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

        if self.action == "paid":
            if order.get("status") == "支払い確認済み":
                return await interaction.response.send_message(
                    "ℹ️ すでに支払い確認済みです。",
                    ephemeral=True
                )

            order["status"] = "支払い確認済み"
            order["paid_at"] = now_iso()

            save_json(ORDER_FILE, ORDERS)

            await interaction.response.send_message(
                f"✅ `{self.order_id}` を支払い確認済みにしました。",
                ephemeral=True
            )

            try:
                user = await bot.fetch_user(
                    safe_int(order["user_id"])
                )

                await user.send(
                    "✅ **支払い確認済み**\n\n"
                    f"注文番号：`{order['order_id']}`\n"
                    f"商品：{order['product']}\n"
                    f"価格：{order['price']:,}円"
                )

            except Exception as e:
                print(f"[PAID DM] {repr(e)}")

            try:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="✅ 注文処理完了",
                        description=(
                            f"`{order['order_id']}`\n\n"
                            f"商品：**{order['product']}**\n"
                            f"購入者：<@{order['user_id']}>\n"
                            f"金額：`{order['price']:,}円`\n\n"
                            "🟢 支払い確認済み"
                        ),
                        color=0x2ECC71,
                    ),
                    view=ProcessedOrderView(),
                )

            except Exception as e:
                print(f"[PAID MESSAGE] {repr(e)}")

            return

        if self.action == "cancel":
            if order.get("status") == "キャンセル":
                return await interaction.response.send_message(
                    "ℹ️ すでにキャンセルされています。",
                    ephemeral=True
                )

            order["status"] = "キャンセル"
            order["cancelled_at"] = now_iso()

            product = PRODUCTS.get(order["product"])

            if product:
                product["stock"] = (
                    safe_int(product.get("stock")) + 1
                )
                save_json(PRODUCT_FILE, PRODUCTS)

            save_json(ORDER_FILE, ORDERS)

            await interaction.response.send_message(
                f"❌ `{self.order_id}` をキャンセルしました。在庫を1個戻しました。",
                ephemeral=True
            )

            try:
                await interaction.message.edit(
                    embed=discord.Embed(
                        title="❌ 注文キャンセル",
                        description=(
                            f"`{order['order_id']}`\n\n"
                            f"商品：**{order['product']}**\n"
                            f"購入者：<@{order['user_id']}>\n"
                            f"金額：`{order['price']:,}円`\n\n"
                            "🔴 キャンセル済み"
                        ),
                        color=0xE74C3C,
                    ),
                    view=ProcessedOrderView(),
                )

            except Exception as e:
                print(f"[CANCEL MESSAGE] {repr(e)}")

            await update_vending_panel()

# =========================================================
# 商品管理
# =========================================================

async def admin_only_error(interaction):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )
        return True
    return False


class AddProductModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🛍️ 商品を追加")

        self.name_input = discord.ui.TextInput(
            label="商品名",
            placeholder="例：コーラ",
            max_length=40
        )

        self.price_input = discord.ui.TextInput(
            label="価格（円）",
            placeholder="例：150",
            max_length=10
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫数",
            placeholder="例：20",
            max_length=10
        )

        self.emoji_input = discord.ui.TextInput(
            label="絵文字",
            placeholder="例：🥤",
            max_length=10
        )

        self.image_input = discord.ui.TextInput(
            label="商品画像URL（任意）",
            placeholder="https://...",
            required=False,
            max_length=500
        )

        for item in (
            self.name_input,
            self.price_input,
            self.stock_input,
            self.emoji_input,
            self.image_input
        ):
            self.add_item(item)

    async def on_submit(self, interaction):
        if await admin_only_error(interaction):
            return

        name = self.name_input.value.strip()

        if not name:
            return await interaction.response.send_message(
                "❌ 商品名を入力してください。",
                ephemeral=True
            )

        if name in PRODUCTS:
            return await interaction.response.send_message(
                "❌ その商品名は既に存在します。",
                ephemeral=True
            )

        if len(PRODUCTS) >= MAX_PRODUCTS:
            return await interaction.response.send_message(
                f"❌ 商品は最大{MAX_PRODUCTS}個までです。",
                ephemeral=True
            )

        try:
            price = int(self.price_input.value)
            stock = int(self.stock_input.value)

        except ValueError:
            return await interaction.response.send_message(
                "❌ 価格と在庫は数字で入力してください。",
                ephemeral=True
            )

        if price <= 0 or stock < 0:
            return await interaction.response.send_message(
                "❌ 価格は1以上、在庫は0以上です。",
                ephemeral=True
            )

        image_url = self.image_input.value.strip()

        if image_url and not valid_http_url(image_url):
            return await interaction.response.send_message(
                "❌ 商品画像URLはhttp/httpsで入力してください。",
                ephemeral=True
            )

        PRODUCTS[name] = {
            "price": price,
            "stock": stock,
            "emoji": self.emoji_input.value.strip() or "🛒",
            "image_url": image_url
        }

        save_json(PRODUCT_FILE, PRODUCTS)

        await interaction.response.send_message(
            f"✅ **{name}** を追加しました。",
            ephemeral=True
        )

        await update_vending_panel()


class ProductSelectBase(discord.ui.Select):
    mode = ""
    placeholder = "商品を選択"

    def __init__(self):
        options = []

        for name, data in list(PRODUCTS.items())[:25]:
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    emoji=data.get("emoji") or "🛒",
                    description=(
                        f"{safe_int(data.get('price')):,}円 / "
                        f"在庫 {safe_int(data.get('stock'))}個"
                    )[:100],
                    value=name,
                )
            )

        super().__init__(
            placeholder=self.placeholder,
            options=options,
            custom_id=f"kira:admin:{self.mode}"
        )


class DeleteProductSelect(ProductSelectBase):
    mode = "delete_product"
    placeholder = "削除する商品を選択"

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        name = self.values[0]

        if name not in PRODUCTS:
            return await interaction.response.send_message(
                "❌ 商品が見つかりません。",
                ephemeral=True
            )

        del PRODUCTS[name]
        save_json(PRODUCT_FILE, PRODUCTS)

        await interaction.response.send_message(
            f"🗑️ **{name}** を削除しました。",
            ephemeral=True
        )

        await update_vending_panel()


class DeleteProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

        if PRODUCTS:
            self.add_item(DeleteProductSelect())


class StockSelect(ProductSelectBase):
    mode = "stock_select"
    placeholder = "在庫を変更する商品を選択"

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_modal(
            StockModal(self.values[0])
        )


class StockView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

        if PRODUCTS:
            self.add_item(StockSelect())


class StockModal(discord.ui.Modal):
    def __init__(self, product_name):
        super().__init__(
            title=f"{product_name} 在庫変更"
        )

        self.product_name = product_name

        self.stock_input = discord.ui.TextInput(
            label="新しい在庫数",
            default=str(
                safe_int(
                    PRODUCTS[product_name].get("stock")
                )
            ),
            max_length=10
        )

        self.add_item(self.stock_input)

    async def on_submit(self, interaction):
        if await admin_only_error(interaction):
            return

        try:
            stock = int(self.stock_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "❌ 数字を入力してください。",
                ephemeral=True
            )

        if stock < 0:
            return await interaction.response.send_message(
                "❌ 0以上を入力してください。",
                ephemeral=True
            )

        if self.product_name not in PRODUCTS:
            return await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )

        PRODUCTS[self.product_name]["stock"] = stock
        save_json(PRODUCT_FILE, PRODUCTS)

        await interaction.response.send_message(
            f"📦 **{self.product_name}** の在庫を `{stock}個` に変更しました。",
            ephemeral=True
        )

        await update_vending_panel()


class EditProductSelect(ProductSelectBase):
    mode = "edit_product"
    placeholder = "編集する商品を選択"

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_modal(
            EditProductModal(self.values[0])
        )


class EditProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

        if PRODUCTS:
            self.add_item(EditProductSelect())


class EditProductModal(discord.ui.Modal):
    def __init__(self, old_name):
        super().__init__(title="✏️ 商品を編集")

        self.old_name = old_name
        data = PRODUCTS[old_name]

        self.name_input = discord.ui.TextInput(
            label="商品名",
            default=old_name,
            max_length=40
        )

        self.price_input = discord.ui.TextInput(
            label="価格",
            default=str(safe_int(data.get("price"))),
            max_length=10
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫",
            default=str(safe_int(data.get("stock"))),
            max_length=10
        )

        self.emoji_input = discord.ui.TextInput(
            label="絵文字",
            default=data.get("emoji") or "🛒",
            max_length=10
        )

        self.image_input = discord.ui.TextInput(
            label="商品画像URL（任意）",
            default=data.get("image_url") or "",
            required=False,
            max_length=500
        )

        for item in (
            self.name_input,
            self.price_input,
            self.stock_input,
            self.emoji_input,
            self.image_input
        ):
            self.add_item(item)

    async def on_submit(self, interaction):
        if await admin_only_error(interaction):
            return

        new_name = self.name_input.value.strip()

        try:
            price = int(self.price_input.value)
            stock = int(self.stock_input.value)

        except ValueError:
            return await interaction.response.send_message(
                "❌ 価格と在庫は数字で入力してください。",
                ephemeral=True
            )

        if price <= 0 or stock < 0:
            return await interaction.response.send_message(
                "❌ 数値を確認してください。",
                ephemeral=True
            )

        if new_name != self.old_name and new_name in PRODUCTS:
            return await interaction.response.send_message(
                "❌ その商品名は既に存在します。",
                ephemeral=True
            )

        image_url = self.image_input.value.strip()

        if image_url and not valid_http_url(image_url):
            return await interaction.response.send_message(
                "❌ 商品画像URLはhttp/httpsで入力してください。",
                ephemeral=True
            )

        PRODUCTS.pop(self.old_name, None)

        PRODUCTS[new_name] = {
            "price": price,
            "stock": stock,
            "emoji": self.emoji_input.value.strip() or "🛒",
            "image_url": image_url
        }

        save_json(PRODUCT_FILE, PRODUCTS)

        await interaction.response.send_message(
            f"✏️ 商品を **{new_name}** に更新しました。",
            ephemeral=True
        )

        await update_vending_panel()

# =========================================================
# デザイン設定
# =========================================================

COLOR_PRESETS = {
    "🔵 ブルー": 0x5865F2,
    "🟣 パープル": 0x9B59B6,
    "🩷 ピンク": 0xFF69B4,
    "🔴 レッド": 0xE74C3C,
    "🟠 オレンジ": 0xE67E22,
    "🟡 ゴールド": 0xF1C40F,
    "🟢 グリーン": 0x2ECC71,
    "🩵 シアン": 0x1ABC9C,
}


class ColorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

        for name, value in COLOR_PRESETS.items():
            self.add_item(ColorButton(name, value))


class ColorButton(discord.ui.Button):
    def __init__(self, name, value):
        super().__init__(
            label=name,
            style=discord.ButtonStyle.blurple
        )

        self.color_value = value

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        CONFIG["panel_color"] = self.color_value
        save_json(CONFIG_FILE, CONFIG)

        await interaction.response.send_message(
            f"🎨 {self.label} に変更しました！",
            ephemeral=True
        )

        await update_vending_panel()


class DesignModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🎨 自販機デザイン設定")

        self.title_input = discord.ui.TextInput(
            label="タイトル",
            default=CONFIG.get("panel_title", "")[:256],
            max_length=256
        )

        self.desc_input = discord.ui.TextInput(
            label="説明",
            default=CONFIG.get("panel_description", "")[:4000],
            max_length=4000,
            style=discord.TextStyle.paragraph
        )

        self.image_input = discord.ui.TextInput(
            label="大きな画像URL（任意）",
            default=CONFIG.get("panel_image_url", "")[:500],
            required=False,
            max_length=500
        )

        self.thumb_input = discord.ui.TextInput(
            label="小さな画像URL（任意）",
            default=CONFIG.get("panel_thumbnail_url", "")[:500],
            required=False,
            max_length=500
        )

        self.footer_input = discord.ui.TextInput(
            label="フッター",
            default=CONFIG.get("panel_footer", "")[:2048],
            max_length=2048
        )

        for item in (
            self.title_input,
            self.desc_input,
            self.image_input,
            self.thumb_input,
            self.footer_input
        ):
            self.add_item(item)

    async def on_submit(self, interaction):
        if await admin_only_error(interaction):
            return

        image = self.image_input.value.strip()
        thumb = self.thumb_input.value.strip()

        if image and not valid_http_url(image):
            return await interaction.response.send_message(
                "❌ 大きな画像URLが正しくありません。",
                ephemeral=True
            )

        if thumb and not valid_http_url(thumb):
            return await interaction.response.send_message(
                "❌ 小さな画像URLが正しくありません。",
                ephemeral=True
            )

        CONFIG.update({
            "panel_title": self.title_input.value.strip(),
            "panel_description": self.desc_input.value.strip(),
            "panel_image_url": image,
            "panel_thumbnail_url": thumb,
            "panel_footer": self.footer_input.value.strip(),
        })

        save_json(CONFIG_FILE, CONFIG)

        await interaction.response.send_message(
            "✅ デザインを保存しました。",
            ephemeral=True
        )

        await update_vending_panel()


class NoticeModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="📝 購入案内を変更")

        self.notice = discord.ui.TextInput(
            label="購入案内",
            default=CONFIG.get("shop_notice", "")[:4000],
            max_length=4000,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.notice)

    async def on_submit(self, interaction):
        if await admin_only_error(interaction):
            return

        CONFIG["shop_notice"] = self.notice.value.strip()
        save_json(CONFIG_FILE, CONFIG)

        await interaction.response.send_message(
            "✅ 購入案内を更新しました。",
            ephemeral=True
        )

        await update_vending_panel()


class PanelSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(
        label="🎨 色を変更",
        style=discord.ButtonStyle.blurple
    )
    async def color(self, interaction, button):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_message(
            "🎨 パネルカラーを選択してください。",
            view=ColorView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="🖼️ デザイン編集",
        style=discord.ButtonStyle.blurple
    )
    async def design(self, interaction, button):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_modal(
            DesignModal()
        )

    @discord.ui.button(
        label="📝 購入案内",
        style=discord.ButtonStyle.gray
    )
    async def notice(self, interaction, button):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_modal(
            NoticeModal()
        )

    @discord.ui.button(
        label="🔄 パネル更新",
        style=discord.ButtonStyle.green
    )
    async def refresh(self, interaction, button):
        if await admin_only_error(interaction):
            return

        ok = await update_vending_panel()

        await interaction.response.send_message(
            "✅ パネルを更新しました。"
            if ok
            else
            "⚠️ パネルを更新できませんでした。",
            ephemeral=True
        )

# =========================================================
# チャンネル設定
# =========================================================

class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, mode):
        self.mode = mode

        super().__init__(
            placeholder="設定するチャンネルを選択",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            custom_id=f"kira:channel:{mode}",
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        selected = self.values[0]

        try:
            channel = await interaction.guild.fetch_channel(
                selected.id
            )

        except Exception as e:
            print(f"[CHANNEL SELECT] {repr(e)}")

            return await interaction.response.send_message(
                "❌ チャンネルを取得できませんでした。",
                ephemeral=True
            )

        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "❌ テキストチャンネルを選択してください。",
                ephemeral=True
            )

        problem = permission_problem(channel)

        if problem:
            return await interaction.response.send_message(
                f"❌ このチャンネルではBotが動作できません。\n\n"
                f"**{problem}**",
                ephemeral=True
            )

        if self.mode == "purchase":
            message = None

            if (
                CONFIG.get("purchase_channel_id") == channel.id
                and CONFIG.get("purchase_message_id")
            ):
                try:
                    message = await channel.fetch_message(
                        int(CONFIG["purchase_message_id"])
                    )

                    await message.edit(
                        embed=create_panel_embed(),
                        view=VendingView()
                    )

                except Exception:
                    message = None

            if message is None:
                message = await channel.send(
                    embed=create_panel_embed(),
                    view=VendingView()
                )

            CONFIG.update({
                "purchase_channel_id": channel.id,
                "purchase_message_id": message.id
            })

            save_json(CONFIG_FILE, CONFIG)

            await interaction.response.send_message(
                f"🛒 自動販売機を {channel.mention} に設置しました。",
                ephemeral=True
            )

        else:
            CONFIG["order_channel_id"] = channel.id
            save_json(CONFIG_FILE, CONFIG)

            await interaction.response.send_message(
                f"📩 注文通知先を {channel.mention} に設定しました。",
                ephemeral=True
            )


class ChannelSelectView(discord.ui.View):
    def __init__(self, mode):
        super().__init__(timeout=120)
        self.add_item(ChannelSelect(mode))

# =========================================================
# 管理パネル
# =========================================================

class AdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        self.add_item(AdminInstallButton())
        self.add_item(AdminOrderChannelButton())
        self.add_item(AdminAddButton())
        self.add_item(AdminEditButton())
        self.add_item(AdminDeleteButton())
        self.add_item(AdminStockButton())
        self.add_item(AdminSettingsButton())
        self.add_item(AdminRefreshButton())


class AdminInstallButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="自販機を設置",
            emoji="🛒",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:install",
            row=0
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_message(
            "🛒 販売用チャンネルを選択してください。",
            view=ChannelSelectView("purchase"),
            ephemeral=True
        )


class AdminOrderChannelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="注文通知設定",
            emoji="📩",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:order_channel",
            row=0
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_message(
            "📩 注文通知を送るチャンネルを選択してください。",
            view=ChannelSelectView("order"),
            ephemeral=True
        )


class AdminAddButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="商品追加",
            emoji="➕",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:add",
            row=1
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_modal(
            AddProductModal()
        )


class AdminEditButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="商品編集",
            emoji="✏️",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:edit",
            row=1
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        if not PRODUCTS:
            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

        await interaction.response.send_message(
            "✏️ 編集する商品を選択してください。",
            view=EditProductView(),
            ephemeral=True
        )


class AdminDeleteButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="商品削除",
            emoji="🗑️",
            style=discord.ButtonStyle.red,
            custom_id="kira:admin:delete",
            row=1
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        if not PRODUCTS:
            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

        await interaction.response.send_message(
            "🗑️ 削除する商品を選択してください。",
            view=DeleteProductView(),
            ephemeral=True
        )


class AdminStockButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="在庫変更",
            emoji="📦",
            style=discord.ButtonStyle.gray,
            custom_id="kira:admin:stock",
            row=2
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        if not PRODUCTS:
            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

        await interaction.response.send_message(
            "📦 在庫を変更する商品を選択してください。",
            view=StockView(),
            ephemeral=True
        )


class AdminSettingsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="パネル設定",
            emoji="🎨",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:settings",
            row=2
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        await interaction.response.send_message(
            "🎨 自販機デザイン設定",
            view=PanelSettingsView(),
            ephemeral=True
        )


class AdminRefreshButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="パネル更新",
            emoji="🔄",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:refresh_panel",
            row=2
        )

    async def callback(self, interaction):
        if await admin_only_error(interaction):
            return

        ok = await update_vending_panel()

        await interaction.response.send_message(
            "✅ 自販機パネルを更新しました。"
            if ok
            else
            "⚠️ パネルを更新できませんでした。",
            ephemeral=True
        )

# =========================================================
# 注文履歴 / 統計
# =========================================================

class OrderHistoryView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(
        label="🔄 更新",
        style=discord.ButtonStyle.blurple
    )
    async def refresh(self, interaction, button):
        if (
            interaction.user.id != self.user_id
            and not is_admin(interaction)
        ):
            return await interaction.response.send_message(
                "🔒 権限がありません。",
                ephemeral=True
            )

        await interaction.response.edit_message(
            embed=create_history_embed(self.user_id),
            view=self
        )


def create_history_embed(user_id):
    mine = [
        o for o in ORDERS
        if safe_int(o.get("user_id")) == user_id
    ]

    mine = mine[-10:][::-1]

    embed = discord.Embed(
        title="🧾 購入履歴",
        color=color_value()
    )

    if not mine:
        embed.description = "購入履歴はありません。"
        return embed

    lines = []

    for o in mine:
        lines.append(
            f"`{o.get('order_id')}` • "
            f"**{o.get('product')}** • "
            f"`{safe_int(o.get('price')):,}円` • "
            f"{o.get('status', '不明')}"
        )

    embed.description = "\n".join(lines)
    embed.set_footer(text="直近10件を表示")

    return embed

# =========================================================
# パネル更新 / 永続コンポーネント
# =========================================================

async def update_vending_panel():
    channel_id = CONFIG.get("purchase_channel_id")
    message_id = CONFIG.get("purchase_message_id")

    if not channel_id or not message_id:
        return False

    try:
        channel = (
            bot.get_channel(int(channel_id))
            or await bot.fetch_channel(int(channel_id))
        )

        if not isinstance(channel, discord.TextChannel):
            return False

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_panel_embed(),
            view=VendingView()
        )

        return True

    except Exception as e:
        print(f"[PANEL] 更新失敗: {repr(e)}")
        return False


async def register_persistent_components():
    try:
        bot.add_view(
            VendingView(),
            message_id=(
                int(CONFIG["purchase_message_id"])
                if CONFIG.get("purchase_message_id")
                else None
            )
        )

    except Exception as e:
        print(f"[VIEW] VendingView登録失敗: {repr(e)}")

    try:
        bot.add_view(AdminView())

    except Exception as e:
        print(f"[VIEW] AdminView登録失敗: {repr(e)}")

    try:
        bot.add_dynamic_items(
            TicketActionButton,
            OrderActionButton
        )

    except Exception as e:
        print(f"[VIEW] DynamicItem登録失敗: {repr(e)}")

# =========================================================
# イベント
# =========================================================

ready_once = False


@bot.event
async def on_ready():
    global ready_once

    print(
        f"✅ ログインしました: "
        f"{bot.user} (ID: {bot.user.id})"
    )

    if ready_once:
        return

    ready_once = True

    await register_persistent_components()

    try:
        synced = await bot.tree.sync()

        print(
            f"✅ スラッシュコマンドを "
            f"{len(synced)} 個同期しました"
        )

    except Exception as e:
        print(f"❌ コマンド同期エラー: {repr(e)}")

    print("========================================")
    print(f"🛒 {BOT_NAME} 起動完了")
    print("========================================")

# =========================================================
# コマンド
# =========================================================

@bot.tree.command(
    name="ping",
    description="Botの動作確認"
)
async def ping(interaction):
    await interaction.response.send_message(
        "🏓 Pong!",
        ephemeral=True
    )


@bot.tree.command(
    name="admin",
    description="キラの自動販売機 管理画面"
)
async def admin(interaction):
    if await admin_only_error(interaction):
        return

    embed = discord.Embed(
        title="👑 KIRA VENDING",
        description=(
            "## 管理者コントロールパネル\n\n"
            "🛒 **販売設定**\n"
            "販売チャンネル・注文通知\n\n"
            "📦 **商品管理**\n"
            "追加・編集・削除・在庫変更\n\n"
            "🎨 **デザイン**\n"
            "色・タイトル・説明・画像・購入案内"
        ),
        color=color_value(),
    )

    embed.set_footer(
        text="KIRA VENDING • ADMIN PANEL"
    )

    await interaction.response.send_message(
        embed=embed,
        view=AdminView(),
        ephemeral=True
    )


@bot.tree.command(
    name="history",
    description="自分の購入履歴を表示"
)
async def history(interaction):
    await interaction.response.send_message(
        embed=create_history_embed(interaction.user.id),
        view=OrderHistoryView(interaction.user.id),
        ephemeral=True
    )


@bot.tree.command(
    name="orders",
    description="管理者用: 最近の注文一覧"
)
async def orders(interaction):
    if await admin_only_error(interaction):
        return

    recent = ORDERS[-15:][::-1]

    embed = discord.Embed(
        title="📋 最近の注文",
        color=color_value()
    )

    if not recent:
        embed.description = "注文はありません。"

    else:
        lines = []

        for o in recent:
            lines.append(
                f"`{o.get('order_id')}` • "
                f"<@{safe_int(o.get('user_id'))}> • "
                f"**{o.get('product')}** • "
                f"`{safe_int(o.get('price')):,}円` • "
                f"{o.get('status')}"
            )

        embed.description = "\n".join(lines)

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

# =========================================================
# エラー
# =========================================================

@bot.tree.error
async def on_app_command_error(interaction, error):
    print(
        f"[APP COMMAND ERROR] {repr(error)}"
    )

    try:
        message = (
            "❌ コマンド処理中にエラーが発生しました。"
        )

        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception:
        pass

# =========================================================
# Token / 起動
# =========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN が設定されていません。"
    )

bot.run(TOKEN)
