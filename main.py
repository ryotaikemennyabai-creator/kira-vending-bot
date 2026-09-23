import os
import json
import hashlib
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands


# =========================================================
# 基本設定
# =========================================================

PRODUCT_FILE = "products.json"
CONFIG_FILE = "config.json"
ORDER_FILE = "orders.json"

BOT_NAME = "キラの自動販売機"

DEFAULT_PRODUCTS = {
    "コーラ": {
        "price": 100,
        "stock": 10,
        "emoji": "🥤"
    },
    "お茶": {
        "price": 100,
        "stock": 10,
        "emoji": "🍵"
    },
    "水": {
        "price": 80,
        "stock": 10,
        "emoji": "💧"
    }
}

DEFAULT_CONFIG = {
    "purchase_channel_id": None,
    "purchase_message_id": None,

    "order_channel_id": None,

    "ticket_category_id": None,
    "archive_category_id": None,

    "panel_color": 0x5865F2,
    "panel_title": "🛒 キラの自動販売機",
    "panel_description": "下のボタンから購入する商品を選択してください。",

    "order_counter": 0
}


# =========================================================
# JSON
# =========================================================

def save_json(filename, data):
    temp = filename + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, filename)


def load_json(filename, default):
    if not os.path.exists(filename):
        save_json(filename, default)
        return json.loads(json.dumps(default))

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        print(f"[WARN] {filename} が壊れていたため初期化します。")
        save_json(filename, default)
        return json.loads(json.dumps(default))


PRODUCTS = load_json(
    PRODUCT_FILE,
    DEFAULT_PRODUCTS
)

CONFIG = load_json(
    CONFIG_FILE,
    DEFAULT_CONFIG
)

ORDERS = load_json(
    ORDER_FILE,
    []
)


# =========================================================
# 古いデータとの互換性
# =========================================================

for name, data in list(PRODUCTS.items()):

    if isinstance(data, int):
        PRODUCTS[name] = {
            "price": data,
            "stock": 10,
            "emoji": "🛒"
        }
        continue

    if not isinstance(data, dict):
        PRODUCTS[name] = {
            "price": 0,
            "stock": 0,
            "emoji": "🛒"
        }
        continue

    data.setdefault("price", 0)
    data.setdefault("stock", 0)
    data.setdefault("emoji", "🛒")


for key, value in DEFAULT_CONFIG.items():
    CONFIG.setdefault(key, value)


save_json(PRODUCT_FILE, PRODUCTS)
save_json(CONFIG_FILE, CONFIG)


# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# 共通
# =========================================================

def is_admin(interaction: discord.Interaction):

    if not interaction.guild:
        return False

    return interaction.user.guild_permissions.administrator


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def short_hash(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()[:16]


def product_custom_id(name):

    return f"kira:product:{short_hash(name)}"


def order_id_custom_id(prefix, order_id):

    return f"kira:{prefix}:{order_id}"


def find_order(order_id):

    for order in ORDERS:
        if order.get("order_id") == order_id:
            return order

    return None


def create_order_id():

    counter = int(
        CONFIG.get(
            "order_counter",
            0
        )
    )

    existing = {
        order.get("order_id")
        for order in ORDERS
    }

    while True:

        counter += 1

        order_id = f"KIRA-{counter:05d}"

        if order_id not in existing:

            CONFIG[
                "order_counter"
            ] = counter

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            return order_id


# =========================================================
# Discord権限チェック
# =========================================================

def bot_permissions(channel=None, guild=None):

    if guild is None:
        return None

    me = guild.me

    if me is None:
        return None

    if channel is None:
        return guild.me.guild_permissions

    return channel.permissions_for(me)


def can_use_channel(channel):

    perms = bot_permissions(
        channel=channel,
        guild=channel.guild
    )

    if perms is None:
        return False

    return (
        perms.view_channel
        and perms.send_messages
        and perms.embed_links
        and perms.read_message_history
    )


def permission_problem(channel):

    perms = bot_permissions(
        channel=channel,
        guild=channel.guild
    )

    if perms is None:
        return "Botのメンバー情報を取得できません。"

    missing = []

    if not perms.view_channel:
        missing.append("チャンネルを見る")

    if not perms.send_messages:
        missing.append("メッセージを送信")

    if not perms.embed_links:
        missing.append("埋め込みリンク")

    if not perms.read_message_history:
        missing.append("メッセージ履歴を読む")

    if missing:
        return "不足権限: " + " / ".join(missing)

    return None


# =========================================================
# パネル
# =========================================================

def create_panel_embed():

    color = int(
        CONFIG.get(
            "panel_color",
            0x5865F2
        )
    )

    embed = discord.Embed(
        title=CONFIG.get(
            "panel_title",
            "🛒 キラの自動販売機"
        ),
        description=(
            CONFIG.get(
                "panel_description",
                "下のボタンから購入する商品を選択してください。"
            )
            + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💳 **PayPay送金URLで購入**\n"
            "🛒 商品を選択 → 支払いURL入力\n"
            "💬 購入後は専用チャットが自動作成されます\n"
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        color=color
    )

    if not PRODUCTS:

        embed.add_field(
            name="📦 商品",
            value="現在販売中の商品はありません。",
            inline=False
        )

    else:

        lines = []

        for name, data in PRODUCTS.items():

            emoji = data.get(
                "emoji",
                "🛒"
            )

            price = int(
                data.get(
                    "price",
                    0
                )
            )

            stock = int(
                data.get(
                    "stock",
                    0
                )
            )

            if stock > 0:

                status = f"🟢 在庫 {stock}個"

            else:

                status = "🔴 SOLD OUT"

            lines.append(
                f"{emoji} **{name}**　`{price:,}円`　{status}"
            )

        text = "\n".join(lines)

        if len(text) > 1024:
            text = text[:1000] + "\n…"

        embed.add_field(
            name="🛍️ 商品一覧",
            value=text,
            inline=False
        )

    embed.set_footer(
        text="KIRA VENDING • 安全にお買い物をお楽しみください"
    )

    return embed


# =========================================================
# 商品ボタン
# =========================================================

BUTTON_STYLES = [
    discord.ButtonStyle.green,
    discord.ButtonStyle.blurple,
    discord.ButtonStyle.red,
    discord.ButtonStyle.gray
]


class ProductButton(discord.ui.Button):

    def __init__(
        self,
        name,
        data,
        index
    ):

        stock = int(
            data.get(
                "stock",
                0
            )
        )

        price = int(
            data.get(
                "price",
                0
            )
        )

        emoji = data.get(
            "emoji",
            "🛒"
        )

        if stock <= 0:

            label = f"{name} • SOLD OUT"
            style = discord.ButtonStyle.gray

        else:

            label = f"{name} • {price:,}円"
            style = BUTTON_STYLES[
                index % len(BUTTON_STYLES)
            ]

        super().__init__(
            label=label[:80],
            emoji=emoji,
            style=style,
            disabled=(stock <= 0),
            custom_id=product_custom_id(name),
            row=index // 5
        )

        self.product_name = name

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        product = PRODUCTS.get(
            self.product_name
        )

        if product is None:

            await interaction.response.send_message(
                "❌ この商品は現在販売されていません。",
                ephemeral=True
            )

            return

        stock = int(
            product.get(
                "stock",
                0
            )
        )

        if stock <= 0:

            await interaction.response.send_message(
                "🔴 この商品は売り切れです。",
                ephemeral=True
            )

            return

        emoji = product.get(
            "emoji",
            "🛒"
        )

        embed = discord.Embed(
            title=f"{emoji} 購入確認",
            description=(
                f"## {emoji} {self.product_name}\n\n"
                f"💴 **価格**\n"
                f"`{int(product['price']):,}円`\n\n"
                f"📦 **在庫**\n"
                f"`{stock}個`\n\n"
                "この商品を購入しますか？\n"
                "購入するとPayPay送金URLの入力画面が開きます。"
            ),
            color=CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=PurchaseConfirmView(
                self.product_name
            ),
            ephemeral=True
        )


# =========================================================
# 自販機View
# =========================================================

class VendingView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        for index, (
            name,
            data
        ) in enumerate(
            list(PRODUCTS.items())[:25]
        ):

            self.add_item(
                ProductButton(
                    name,
                    data,
                    index
                )
            )


# =========================================================
# 購入確認
# =========================================================

class PurchaseConfirmView(
    discord.ui.View
):

    def __init__(
        self,
        product_name
    ):

        super().__init__(
            timeout=120
        )

        self.product_name = product_name

    @discord.ui.button(
        label="購入する",
        emoji="🛒",
        style=discord.ButtonStyle.green,
        row=0
    )
    async def confirm(
        self,
        interaction,
        button
    ):

        product = PRODUCTS.get(
            self.product_name
        )

        if not product:
            await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )
            return

        if int(product["stock"]) <= 0:
            await interaction.response.send_message(
                "🔴 売り切れです。",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            PurchaseModal(
                self.product_name
            )
        )

    @discord.ui.button(
        label="キャンセル",
        emoji="✖️",
        style=discord.ButtonStyle.gray,
        row=0
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            content="購入をキャンセルしました。",
            embed=None,
            view=None
        )


# =========================================================
# PayPay入力Modal
# =========================================================

class PurchaseModal(
    discord.ui.Modal
):

    def __init__(
        self,
        product_name
    ):

        super().__init__(
            title=f"{product_name}を購入"
        )

        self.product_name = product_name

        self.url_input = discord.ui.TextInput(
            label="PayPay送金URL",
            placeholder="https://pay.paypay.ne.jp/...",
            required=True,
            max_length=500
        )

        self.add_item(
            self.url_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        try:
            await interaction.response.defer(
                ephemeral=True,
                thinking=True
            )
        except Exception as e:
            print(
                f"[PURCHASE] defer error: {e}"
            )
            return

        product = PRODUCTS.get(
            self.product_name
        )

        if not product:

            await interaction.followup.send(
                "❌ 商品がありません。",
                ephemeral=True
            )

            return

        if int(product["stock"]) <= 0:

            await interaction.followup.send(
                "🔴 売り切れです。",
                ephemeral=True
            )

            return

        paypay_url = self.url_input.value.strip()

        if not (
            paypay_url.startswith("https://")
            or paypay_url.startswith("http://")
        ):

            await interaction.followup.send(
                "❌ PayPay送金URLの形式が正しくありません。",
                ephemeral=True
            )

            return

        order_id = create_order_id()

        order = {
            "order_id": order_id,
            "user_id": interaction.user.id,
            "username": str(interaction.user),

            "guild_id": interaction.guild.id
            if interaction.guild
            else None,

            "product": self.product_name,
            "price": int(product["price"]),

            "paypay_url": paypay_url,

            "status": "支払い確認待ち",

            "created_at": now_iso(),

            "ticket_channel_id": None,
            "ticket_created": False,

            "notification_sent": False,
            "dm_sent": False
        }

        ORDERS.append(order)

        product["stock"] = int(
            product["stock"]
        ) - 1

        save_json(
            ORDER_FILE,
            ORDERS
        )

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        try:
            await update_vending_panel()
        except Exception as e:
            print(
                f"[PURCHASE] パネル更新失敗: {e}"
            )

        ticket = None

        try:

            ticket = await create_ticket(
                interaction.guild,
                interaction.user,
                order
            )

            if ticket:

                order["ticket_created"] = True

                save_json(
                    ORDER_FILE,
                    ORDERS
                )

        except Exception as e:

            print(
                f"[PURCHASE] 専用チャット作成失敗: {repr(e)}"
            )

        try:

            sent = await send_order_notification(
                interaction.guild,
                order
            )

            if sent:

                order["notification_sent"] = True

                save_json(
                    ORDER_FILE,
                    ORDERS
                )

        except Exception as e:

            print(
                f"[PURCHASE] 注文通知失敗: {repr(e)}"
            )

        try:

            sent = await send_order_dm(
                interaction.user,
                order,
                ticket
            )

            if sent:

                order["dm_sent"] = True

                save_json(
                    ORDER_FILE,
                    ORDERS
                )

        except Exception as e:

            print(
                f"[PURCHASE] DM失敗: {repr(e)}"
            )

        ticket_text = (
            ticket.mention
            if ticket
            else "⚠️ 専用チャットの作成に失敗しました。管理者へ通知されています。"
        )

        status_lines = [
            "## ✅ 注文を受け付けました！",
            "",
            f"🧾 **注文番号**",
            f"`{order_id}`",
            "",
            f"🛍️ **商品**",
            f"{self.product_name}",
            "",
            f"💴 **価格**",
            f"`{int(product['price']):,}円`",
            "",
            f"💬 **専用チャット**",
            ticket_text,
            "",
            "🟡 **支払い確認待ち**",
            "",
            "管理者がPayPay送金を確認すると注文が完了します。"
        ]

        await interaction.followup.send(
            "\n".join(status_lines),
            ephemeral=True
        )


# =========================================================
# チケットカテゴリ取得 / 作成
# =========================================================

async def get_or_create_category(
    guild,
    config_key,
    name
):

    category_id = CONFIG.get(
        config_key
    )

    if category_id:

        try:

            category = guild.get_channel(
                int(category_id)
            )

            if category is None:

                category = await guild.fetch_channel(
                    int(category_id)
                )

            if isinstance(
                category,
                discord.CategoryChannel
            ):

                return category

        except Exception as e:

            print(
                f"[CATEGORY] 既存カテゴリ取得失敗: {e}"
            )

    me = guild.me

    if me is None:
        raise RuntimeError(
            "Botのメンバー情報を取得できません。"
        )

    if not me.guild_permissions.manage_channels:
        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=True,
            manage_permissions=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True
        )
    }

    category = await guild.create_category(
        name,
        overwrites=overwrites,
        reason=f"{BOT_NAME} 自動作成"
    )

    CONFIG[
        config_key
    ] = category.id

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return category


# =========================================================
# 専用チャット作成
# =========================================================

async def create_ticket(
    guild,
    user,
    order
):

    if guild is None:
        raise RuntimeError(
            "Guildが取得できません。"
        )

    bot_member = guild.me

    if bot_member is None:
        raise RuntimeError(
            "Bot自身のMemberを取得できません。"
        )

    guild_perms = bot_member.guild_permissions

    if not guild_perms.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )

    category = await get_or_create_category(
        guild,
        "ticket_category_id",
        "💬 購入チャット"
    )

    channel_name = f"chat-{order['order_id'].lower()}"

    channel = await guild.create_text_channel(
        channel_name,
        category=category,
        topic=(
            f"キラの自動販売機 | "
            f"注文 {order['order_id']} | "
            f"購入者 {user.id}"
        ),
        reason=f"注文 {order['order_id']} の購入チャット"
    )

    try:
        await channel.set_permissions(
            guild.default_role,
            view_channel=False
        )
        await channel.set_permissions(
            bot_member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True
        )
        await channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True
        )
    except discord.Forbidden as e:
        print(f"[TICKET] 権限設定Forbidden: {e}")
        try:
            await channel.delete(reason="購入チャットの権限設定に失敗")
        except Exception:
            pass
        raise RuntimeError("購入チャットの権限設定に失敗しました。") from e

    perms = channel.permissions_for(
        bot_member
    )

    if not perms.view_channel:

        await channel.delete(
            reason="Bot自身がチャンネルを閲覧できないため"
        )

        raise RuntimeError(
            "作成後のチャンネルでBotの閲覧権限がありません。"
        )

    if not perms.send_messages:

        await channel.delete(
            reason="Bot自身がメッセージ送信できないため"
        )

        raise RuntimeError(
            "作成後のチャンネルでBotの送信権限がありません。"
        )

    order["ticket_channel_id"] = channel.id

    save_json(
        ORDER_FILE,
        ORDERS
    )

    embed = discord.Embed(
        title="💬 購入専用チャット",
        description=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 **注文番号**\n`{order['order_id']}`\n\n"
            f"🛍️ **商品**\n{order['product']}\n\n"
            f"💴 **価格**\n`{order['price']:,}円`\n\n"
            "🟡 **支払い確認待ち**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "このチャットは今回の購入専用です。\n"
            "管理者への質問はこちらで行えます。"
        ),
        color=CONFIG.get(
            "panel_color",
            0x5865F2
        )
    )

    embed.set_footer(
        text=f"{BOT_NAME} • {order['order_id']}"
    )

    await channel.send(
        content=user.mention,
        embed=embed,
        view=TicketView(
            order["order_id"],
            user.id
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True
        )
    )

    return channel


# =========================================================
# 注文通知チャンネル自動作成
# =========================================================

async def ensure_order_channel(guild):

    if guild is None:
        return None

    me = guild.me

    if me is None:
        raise RuntimeError("BotのMember情報を取得できません。")

    if not me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    saved_id = CONFIG.get("order_channel_id")

    if saved_id:

        try:

            existing = guild.get_channel(
                int(saved_id)
            )

            if existing is None:

                existing = await guild.fetch_channel(
                    int(saved_id)
                )

            if (
                isinstance(existing, discord.TextChannel)
                and existing.name == "注文通知"
            ):

                return existing

        except Exception as e:

            print(
                f"[ORDER CHANNEL] 保存済みチャンネル確認失敗: {repr(e)}"
            )

    for ch in guild.text_channels:

        if ch.name == "注文通知":

            CONFIG["order_channel_id"] = ch.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            return ch

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True
        )
    }

    channel = await guild.create_text_channel(
        "注文通知",
        overwrites=overwrites,
        topic=f"{BOT_NAME} 専用・注文通知チャンネル",
        reason=f"{BOT_NAME} 注文通知チャンネル自動作成"
    )

    CONFIG["order_channel_id"] = channel.id

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    await channel.send(
        embed=discord.Embed(
            title="📦 注文通知チャンネル",
            description=(
                "このチャンネルは **管理者専用** です。\n"
                "新しい注文が入ると、ここへ自動的に通知されます。"
            ),
            color=CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    print(
        f"[ORDER CHANNEL] 作成しました: "
        f"#{channel.name} ({channel.id})"
    )

    return channel


# =========================================================
# 注文通知
# =========================================================

async def send_order_notification(
    guild,
    order
):

    if guild is None:
        return False

    try:

        channel = await ensure_order_channel(
            guild
        )

        if channel is None:
            return False

        if channel is None:

            channel = await guild.fetch_channel(
                int(channel_id)
            )

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            print(
                "[ORDER] 通知先がテキストチャンネルではありません。"
            )

            return False

        problem = permission_problem(
            channel
        )

        if problem:

            print(
                f"[ORDER] 通知チャンネル権限エラー: {problem}"
            )

            return False

        embed = discord.Embed(
            title="🛒 新しい注文が入りました",
            description=(
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 **注文番号**\n"
                f"`{order['order_id']}`\n\n"
                f"👤 **購入者**\n"
                f"<@{order['user_id']}>\n\n"
                f"🛍️ **商品**\n"
                f"{order['product']}\n\n"
                f"💴 **金額**\n"
                f"`{order['price']:,}円`\n\n"
                "🟡 **支払い確認待ち**\n"
                "━━━━━━━━━━━━━━━━━━━━"
            ),
            color=0xF1C40F
        )

        embed.add_field(
            name="💳 PayPay送金URL",
            value=order["paypay_url"][:1024],
            inline=False
        )

        embed.set_footer(
            text=f"{BOT_NAME} • 管理画面"
        )

        await channel.send(
            embed=embed,
            view=OrderAdminView(
                order["order_id"]
            )
        )

        return True

    except discord.Forbidden as e:

        print(
            f"[ORDER] 通知Forbidden: {e}"
        )

        return False

    except discord.NotFound as e:

        print(
            f"[ORDER] 通知先NotFound: {e}"
        )

        return False

    except Exception as e:

        print(
            f"[ORDER] 通知エラー: {repr(e)}"
        )

        return False


# =========================================================
# 購入者DM
# =========================================================

async def send_order_dm(
    user,
    order,
    ticket
):

    try:

        if ticket:

            ticket_text = ticket.mention

        else:

            ticket_text = (
                "⚠️ 専用チャットは作成できませんでした。\n"
                "注文番号を管理者へお伝えください。"
            )

        await user.send(
            (
                "🛒 **キラの自動販売機**\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 注文番号\n`{order['order_id']}`\n\n"
                f"🛍️ 商品\n{order['product']}\n\n"
                f"💴 金額\n`{order['price']:,}円`\n\n"
                "🟡 状態\n支払い確認待ち\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💬 専用チャット\n{ticket_text}"
            )
        )

        return True

    except discord.Forbidden:

        print(
            f"[DM] {user} はDMを受信できません。"
        )

        return False

    except Exception as e:

        print(
            f"[DM] DM送信エラー: {repr(e)}"
        )

        return False


# =========================================================
# 注文管理View
# =========================================================

class OrderAdminView(
    discord.ui.View
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            timeout=None
        )

        self.order_id = order_id

        self.add_item(
            discord.ui.Button(
                label="支払い確認済み",
                emoji="✅",
                style=discord.ButtonStyle.green,
                custom_id=order_id_custom_id(
                    "paid",
                    order_id
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="キャンセル",
                emoji="❌",
                style=discord.ButtonStyle.red,
                custom_id=order_id_custom_id(
                    "cancel",
                    order_id
                )
            )
        )

    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False

        return True

    async def on_error(
        self,
        interaction,
        error,
        item
    ):

        print(
            f"[ORDER VIEW] {repr(error)}"
        )

        try:

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ 処理中にエラーが発生しました。",
                    ephemeral=True
                )

            else:

                await interaction.followup.send(
                    "❌ 処理中にエラーが発生しました。",
                    ephemeral=True
                )

        except Exception:
            pass


# =========================================================
# 注文ボタンのグローバル処理
# =========================================================

@bot.event
async def on_interaction(
    interaction: discord.Interaction
):

    return


# =========================================================
# Ticket View
# =========================================================

class TicketView(
    discord.ui.View
):

    def __init__(
        self,
        order_id,
        user_id
    ):

        super().__init__(
            timeout=None
        )

        self.order_id = order_id
        self.user_id = user_id

        self.add_item(
            discord.ui.Button(
                label="🗃️ 履歴として保存",
                style=discord.ButtonStyle.blurple,
                custom_id=order_id_custom_id(
                    "archive",
                    order_id
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="🗑️ チャット削除",
                style=discord.ButtonStyle.red,
                custom_id=order_id_custom_id(
                    "delete",
                    order_id
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="🔄 履歴から再開",
                style=discord.ButtonStyle.green,
                custom_id=order_id_custom_id(
                    "reopen",
                    order_id
                )
            )
        )

    async def interaction_check(
        self,
        interaction
    ):

        order = find_order(
            self.order_id
        )

        if not order:

            await interaction.response.send_message(
                "❌ 注文データが見つかりません。",
                ephemeral=True
            )

            return False

        allowed = (
            interaction.user.id
            == int(order["user_id"])
            or is_admin(interaction)
        )

        if not allowed:

            await interaction.response.send_message(
                "🔒 この注文を操作する権限がありません。",
                ephemeral=True
            )

            return False

        return True

    async def on_error(
        self,
        interaction,
        error,
        item
    ):

        print(
            f"[TICKET VIEW] {repr(error)}"
        )


# =========================================================
# Ticketボタンの実体
# =========================================================

@bot.event
async def on_button_interaction(
    interaction
):
    return


# =========================================================
# 動的Ticket操作をイベントで処理
# =========================================================

async def handle_ticket_action(
    interaction,
    action,
    order_id
):

    order = find_order(
        order_id
    )

    if not order:

        await interaction.response.send_message(
            "❌ 注文が見つかりません。",
            ephemeral=True
        )

        return

    allowed = (
        interaction.user.id
        == int(order["user_id"])
        or is_admin(interaction)
    )

    if not allowed:

        await interaction.response.send_message(
            "🔒 権限がありません。",
            ephemeral=True
        )

        return

    channel = interaction.channel

    if action == "archive":

        await interaction.response.send_message(
            "🗃️ このチャットを履歴として保存しています。",
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
            int(order["user_id"])
        )

        if member:

            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=False,
                read_message_history=True
            )

        order["status"] = (
            "支払い確認済み"
            if order.get("status")
            == "支払い確認済み"
            else order.get(
                "status",
                "支払い確認待ち"
            )
        )

        save_json(
            ORDER_FILE,
            ORDERS
        )

    elif action == "delete":

        await interaction.response.send_message(
            "🗑️ このチャットを削除します。",
            ephemeral=True
        )

        await asyncio.sleep(1)

        try:

            await channel.delete(
                reason=(
                    f"注文 {order_id} のチャット削除"
                )
            )

        except Exception as e:

            print(
                f"[TICKET] 削除失敗: {repr(e)}"
            )

    elif action == "reopen":

        member = interaction.guild.get_member(
            int(order["user_id"])
        )

        if member:

            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )

        active_category = await get_or_create_category(
            interaction.guild,
            "ticket_category_id",
            "💬 購入チャット"
        )

        await channel.edit(
            category=active_category,
            name=f"chat-{order_id.lower()}",
            sync_permissions=False
        )

        await interaction.response.send_message(
            "🔄 この購入チャットを再開しました。",
            ephemeral=True
        )


# =========================================================
# 全Viewを受けるためのDynamicItem
# =========================================================

class TicketActionButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=r"kira:(?P<action>archive|delete|reopen):(?P<order_id>KIRA-\d{5})"
):

    def __init__(
        self,
        item,
        action,
        order_id
    ):

        super().__init__(
            item
        )

        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        action = match["action"]
        order_id = match["order_id"]

        return cls(
            item,
            action,
            order_id
        )

    async def callback(
        self,
        interaction
    ):

        await handle_ticket_action(
            interaction,
            self.action,
            self.order_id
        )


# =========================================================
# 注文管理DynamicItem
# =========================================================

class OrderActionButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=r"kira:(?P<action>paid|cancel):(?P<order_id>KIRA-\d{5})"
):

    def __init__(
        self,
        item,
        action,
        order_id
    ):

        super().__init__(
            item
        )

        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            match["action"],
            match["order_id"]
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        order = find_order(
            self.order_id
        )

        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return

        action = self.action

        if action == "paid":

            order["status"] = (
                "支払い確認済み"
            )

            save_json(
                ORDER_FILE,
                ORDERS
            )

            await interaction.response.send_message(
                f"✅ `{self.order_id}` を"
                "支払い確認済みにしました。",
                ephemeral=True
            )

            try:

                user = await bot.fetch_user(
                    int(order["user_id"])
                )

                await user.send(
                    "✅ **支払い確認済み**\n\n"
                    f"注文番号：`{order['order_id']}`\n"
                    f"商品：{order['product']}\n"
                    f"価格：{order['price']:,}円"
                )

            except Exception as e:

                print(
                    f"[PAID DM] {repr(e)}"
                )

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
                        color=0x2ECC71
                    ),
                    view=ProcessedOrderView()
                )

            except Exception as e:

                print(
                    f"[PAID MESSAGE] {repr(e)}"
                )

        elif action == "cancel":

            order["status"] = "キャンセル"

            product = PRODUCTS.get(
                order["product"]
            )

            if product:

                product["stock"] = (
                    int(product.get("stock", 0))
                    + 1
                )

                save_json(
                    PRODUCT_FILE,
                    PRODUCTS
                )

            save_json(
                ORDER_FILE,
                ORDERS
            )

            await interaction.response.send_message(
                f"❌ `{self.order_id}` をキャンセルしました。\n"
                "在庫を1個戻しました。",
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
                        color=0xE74C3C
                    ),
                    view=ProcessedOrderView()
                )

            except Exception as e:

                print(
                    f"[CANCEL MESSAGE] {repr(e)}"
                )

            await update_vending_panel()


class ProcessedOrderView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            discord.ui.Button(
                label="処理済み",
                style=discord.ButtonStyle.gray,
                disabled=True,
                custom_id="kira:processed"
            )
        )


# =========================================================
# 色
# =========================================================

COLOR_PRESETS = {
    "🔵 ブルー": 0x5865F2,
    "🟣 パープル": 0x9B59B6,
    "🩷 ピンク": 0xFF69B4,
    "🔴 レッド": 0xE74C3C,
    "🟠 オレンジ": 0xE67E22,
    "🟡 ゴールド": 0xF1C40F,
    "🟢 グリーン": 0x2ECC71,
    "🩵 シアン": 0x1ABC9C
}


class ColorView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        for name, color in COLOR_PRESETS.items():

            self.add_item(
                ColorButton(
                    name,
                    color
                )
            )


class ColorButton(
    discord.ui.Button
):

    def __init__(
        self,
        name,
        color
    ):

        super().__init__(
            label=name,
            style=discord.ButtonStyle.blurple
        )

        self.color_value = color

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        CONFIG[
            "panel_color"
        ] = self.color_value

        save_json(
            CONFIG_FILE,
            CONFIG
        )

        await interaction.response.send_message(
            f"🎨 {self.label} に変更しました！",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 商品追加
# =========================================================

class AddProductModal(
    discord.ui.Modal
):

    def __init__(self):

        super().__init__(
            title="🛍️ 商品を追加"
        )

        self.name_input = discord.ui.TextInput(
            label="商品名",
            placeholder="例：コーラ",
            max_length=40,
            required=True
        )

        self.price_input = discord.ui.TextInput(
            label="価格（円）",
            placeholder="例：150",
            max_length=10,
            required=True
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫数",
            placeholder="例：20",
            max_length=10,
            required=True
        )

        self.emoji_input = discord.ui.TextInput(
            label="絵文字",
            placeholder="例：🥤",
            max_length=10,
            required=True
        )

        self.add_item(
            self.name_input
        )

        self.add_item(
            self.price_input
        )

        self.add_item(
            self.stock_input
        )

        self.add_item(
            self.emoji_input
        )

    async def on_submit(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        name = self.name_input.value.strip()

        try:

            price = int(
                self.price_input.value
            )

            stock = int(
                self.stock_input.value
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ 価格と在庫は数字で入力してください。",
                ephemeral=True
            )

            return

        if price <= 0 or stock < 0:

            await interaction.response.send_message(
                "❌ 価格は1以上、在庫は0以上にしてください。",
                ephemeral=True
            )

            return

        emoji = self.emoji_input.value.strip()

        PRODUCTS[name] = {
            "price": price,
            "stock": stock,
            "emoji": emoji or "🛒"
        }

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✅ **{name}** を追加しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 商品削除
# =========================================================

class DeleteProductSelect(
    discord.ui.Select
):

    def __init__(self):

        options = []

        for name, data in list(
            PRODUCTS.items()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name,
                    emoji=data.get(
                        "emoji",
                        "🛒"
                    ),
                    description=(
                        f"{data.get('price', 0):,}円 / "
                        f"在庫 {data.get('stock', 0)}"
                    )[:100],
                    value=name
                )
            )

        super().__init__(
            placeholder="削除する商品を選択",
            options=options,
            custom_id="kira:admin:delete_product"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        name = self.values[0]

        if name not in PRODUCTS:

            await interaction.response.send_message(
                "❌ 商品が見つかりません。",
                ephemeral=True
            )

            return

        del PRODUCTS[name]

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"🗑️ **{name}** を削除しました。",
            ephemeral=True
        )

        await update_vending_panel()


class DeleteProductView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                DeleteProductSelect()
            )


# =========================================================
# 在庫変更
# =========================================================

class StockSelect(
    discord.ui.Select
):

    def __init__(self):

        options = []

        for name, data in list(
            PRODUCTS.items()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name,
                    emoji=data.get(
                        "emoji",
                        "🛒"
                    ),
                    description=(
                        f"現在 {data.get('stock', 0)}個"
                    ),
                    value=name
                )
            )

        super().__init__(
            placeholder="在庫を変更する商品を選択",
            options=options,
            custom_id="kira:admin:stock_select"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_modal(
            StockModal(
                self.values[0]
            )
        )


class StockView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                StockSelect()
            )


class StockModal(
    discord.ui.Modal
):

    def __init__(
        self,
        product_name
    ):

        super().__init__(
            title=f"{product_name} 在庫変更"
        )

        self.product_name = product_name

        self.stock_input = discord.ui.TextInput(
            label="新しい在庫数",
            default=str(
                PRODUCTS[product_name]["stock"]
            ),
            max_length=10,
            required=True
        )

        self.add_item(
            self.stock_input
        )

    async def on_submit(
        self,
        interaction
    ):

        try:

            stock = int(
                self.stock_input.value
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ 数字を入力してください。",
                ephemeral=True
            )

            return

        if stock < 0:

            await interaction.response.send_message(
                "❌ 0以上を入力してください。",
                ephemeral=True
            )

            return

        PRODUCTS[
            self.product_name
        ]["stock"] = stock

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"📦 **{self.product_name}** の在庫を "
            f"`{stock}個` に変更しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 商品編集
# =========================================================

class EditProductSelect(
    discord.ui.Select
):

    def __init__(self):

        options = []

        for name, data in list(
            PRODUCTS.items()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name,
                    emoji=data.get(
                        "emoji",
                        "🛒"
                    ),
                    description=(
                        f"{data.get('price', 0):,}円"
                    ),
                    value=name
                )
            )

        super().__init__(
            placeholder="編集する商品を選択",
            options=options,
            custom_id="kira:admin:edit_product"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_modal(
            EditProductModal(
                self.values[0]
            )
        )


class EditProductView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                EditProductSelect()
            )


class EditProductModal(
    discord.ui.Modal
):

    def __init__(
        self,
        old_name
    ):

        super().__init__(
            title="✏️ 商品を編集"
        )

        self.old_name = old_name

        self.name_input = discord.ui.TextInput(
            label="商品名",
            default=old_name,
            max_length=40,
            required=True
        )

        self.price_input = discord.ui.TextInput(
            label="価格",
            default=str(
                PRODUCTS[old_name]["price"]
            ),
            max_length=10,
            required=True
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫",
            default=str(
                PRODUCTS[old_name]["stock"]
            ),
            max_length=10,
            required=True
        )

        self.emoji_input = discord.ui.TextInput(
            label="絵文字",
            default=PRODUCTS[old_name].get(
                "emoji",
                "🛒"
            ),
            max_length=10,
            required=True
        )

        self.add_item(
            self.name_input
        )

        self.add_item(
            self.price_input
        )

        self.add_item(
            self.stock_input
        )

        self.add_item(
            self.emoji_input
        )

    async def on_submit(
        self,
        interaction
    ):

        new_name = self.name_input.value.strip()

        try:

            price = int(
                self.price_input.value
            )

            stock = int(
                self.stock_input.value
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ 価格と在庫は数字で入力してください。",
                ephemeral=True
            )

            return

        if price <= 0 or stock < 0:

            await interaction.response.send_message(
                "❌ 数値を確認してください。",
                ephemeral=True
            )

            return

        if (
            new_name != self.old_name
            and new_name in PRODUCTS
        ):

            await interaction.response.send_message(
                "❌ その商品名は既に存在します。",
                ephemeral=True
            )

            return

        data = {
            "price": price,
            "stock": stock,
            "emoji": self.emoji_input.value.strip()
            or "🛒"
        }

        del PRODUCTS[
            self.old_name
        ]

        PRODUCTS[
            new_name
        ] = data

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✏️ 商品を **{new_name}** に更新しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 管理パネル設定
# =========================================================

class PanelSettingsView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

    @discord.ui.button(
        label="🎨 色を変更",
        style=discord.ButtonStyle.blurple,
        custom_id="kira:admin:color"
    )
    async def color(
        self,
        interaction,
        button
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_message(
            "🎨 パネルカラーを選択してください。",
            view=ColorView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="🔄 パネル更新",
        style=discord.ButtonStyle.green,
        custom_id="kira:admin:refresh"
    )
    async def refresh(
        self,
        interaction,
        button
    ):

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ パネルを更新しました。",
            ephemeral=True
        )


# =========================================================
# チャンネル設定
# =========================================================

class ChannelSelect(
    discord.ui.ChannelSelect
):

    def __init__(
        self,
        mode
    ):

        self.mode = mode

        super().__init__(
            placeholder=(
                "設定するチャンネルを選択"
            ),
            channel_types=[
                discord.ChannelType.text
            ],
            min_values=1,
            max_values=1,
            custom_id=f"kira:channel:{mode}"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        selected = self.values[0]

        try:

            channel = await interaction.guild.fetch_channel(
                selected.id
            )

        except Exception as e:

            print(
                f"[CHANNEL SELECT] {repr(e)}"
            )

            await interaction.response.send_message(
                "❌ 選択したチャンネルを取得できませんでした。",
                ephemeral=True
            )

            return

        if not isinstance(
            channel,
            discord.TextChannel
        ):

            await interaction.response.send_message(
                "❌ テキストチャンネルを選択してください。",
                ephemeral=True
            )

            return

        problem = permission_problem(
            channel
        )

        if problem:

            await interaction.response.send_message(
                "❌ このチャンネルではBotが動作できません。\n\n"
                f"**{problem}**",
                ephemeral=True
            )

            return

        if self.mode == "purchase":

            message = None

            old_channel_id = CONFIG.get(
                "purchase_channel_id"
            )

            old_message_id = CONFIG.get(
                "purchase_message_id"
            )

            if (
                old_channel_id
                and old_message_id
                and int(old_channel_id)
                == channel.id
            ):

                try:

                    message = await channel.fetch_message(
                        int(old_message_id)
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

            CONFIG[
                "purchase_channel_id"
            ] = channel.id

            CONFIG[
                "purchase_message_id"
            ] = message.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            await interaction.response.send_message(
                f"🛒 自動販売機を {channel.mention} に設置しました。",
                ephemeral=True
            )

        elif self.mode == "order":

            CONFIG[
                "order_channel_id"
            ] = channel.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            await interaction.response.send_message(
                f"📩 注文通知先を {channel.mention} に設定しました。",
                ephemeral=True
            )


class ChannelSelectView(
    discord.ui.View
):

    def __init__(
        self,
        mode
    ):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ChannelSelect(
                mode
            )
        )


# =========================================================
# 管理画面
# =========================================================

class AdminView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            AdminInstallButton()
        )

        self.add_item(
            AdminOrderChannelButton()
        )

        self.add_item(
            AdminAddButton()
        )

        self.add_item(
            AdminEditButton()
        )

        self.add_item(
            AdminDeleteButton()
        )

        self.add_item(
            AdminStockButton()
        )

        self.add_item(
            AdminSettingsButton()
        )

        self.add_item(
            AdminRefreshButton()
        )


class AdminInstallButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="自販機を設置",
            emoji="🛒",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:install",
            row=0
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_message(
            "🛒 販売用チャンネルを選択してください。",
            view=ChannelSelectView(
                "purchase"
            ),
            ephemeral=True
        )


class AdminOrderChannelButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="注文通知を作成/確認",
            emoji="📩",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:order_channel",
            row=0
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        try:

            channel = await ensure_order_channel(
                interaction.guild
            )

            await interaction.response.send_message(
                f"📩 注文通知チャンネルを確認しました。\n"
                f"{channel.mention}",
                ephemeral=True
            )

        except Exception as e:

            print(
                f"[ORDER CHANNEL] {repr(e)}"
            )

            await interaction.response.send_message(
                "❌ 注文通知チャンネルを作成できませんでした。\n"
                f"`{e}`",
                ephemeral=True
            )


class AdminAddButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="商品追加",
            emoji="➕",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:add",
            row=1
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_modal(
            AddProductModal()
        )


class AdminEditButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="商品編集",
            emoji="✏️",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:edit",
            row=1
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        if not PRODUCTS:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "✏️ 編集する商品を選択してください。",
            view=EditProductView(),
            ephemeral=True
        )


class AdminDeleteButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="商品削除",
            emoji="🗑️",
            style=discord.ButtonStyle.red,
            custom_id="kira:admin:delete",
            row=1
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        if not PRODUCTS:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🗑️ 削除する商品を選択してください。",
            view=DeleteProductView(),
            ephemeral=True
        )


class AdminStockButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="在庫変更",
            emoji="📦",
            style=discord.ButtonStyle.gray,
            custom_id="kira:admin:stock",
            row=2
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        if not PRODUCTS:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "📦 在庫を変更する商品を選択してください。",
            view=StockView(),
            ephemeral=True
        )


class AdminSettingsButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="パネル設定",
            emoji="🎨",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:settings",
            row=2
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_message(
            "🎨 パネル設定",
            view=PanelSettingsView(),
            ephemeral=True
        )


class AdminRefreshButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="パネル更新",
            emoji="🔄",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:refresh_panel",
            row=2
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ 自動販売機パネルを更新しました。",
            ephemeral=True
        )


# =========================================================
# パネル更新
# =========================================================

async def update_vending_panel():

    channel_id = CONFIG.get(
        "purchase_channel_id"
    )

    message_id = CONFIG.get(
        "purchase_message_id"
    )

    if not channel_id or not message_id:
        return False

    try:

        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:

            channel = await bot.fetch_channel(
                int(channel_id)
            )

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return False

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_panel_embed(),
            view=VendingView()
        )

        return True

    except discord.NotFound:

        print(
            "[PANEL] パネルメッセージが見つかりません。"
        )

        return False

    except discord.Forbidden as e:

        print(
            f"[PANEL] 権限エラー: {e}"
        )

        return False

    except Exception as e:

        print(
            f"[PANEL] 更新エラー: {repr(e)}"
        )

        return False


# =========================================================
# Persistent DynamicItem登録
# =========================================================

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

        print(
            f"[VIEW] VendingView登録失敗: {repr(e)}"
        )

    try:

        bot.add_view(
            AdminView()
        )

    except Exception as e:

        print(
            f"[VIEW] AdminView登録失敗: {repr(e)}"
        )

    try:

        bot.add_dynamic_items(
            TicketActionButton,
            OrderActionButton
        )

    except Exception as e:

        print(
            f"[VIEW] DynamicItem登録失敗: {repr(e)}"
        )


# =========================================================
# 起動
# =========================================================

ready_once = False


@bot.event
async def on_ready():

    global ready_once

    print(
        f"✅ ログインしました: {bot.user}"
    )

    if ready_once:
        return

    ready_once = True

    try:

        await register_persistent_components()

    except Exception as e:

        print(
            f"[STARTUP] View登録エラー: {repr(e)}"
        )

    for guild in bot.guilds:

        try:

            await ensure_order_channel(
                guild
            )

        except Exception as e:

            print(
                f"[STARTUP] #{guild.name} "
                f"注文通知チャンネル作成失敗: {repr(e)}"
            )

    try:

        synced = await bot.tree.sync()

        print(
            f"✅ スラッシュコマンドを "
            f"{len(synced)} 個同期しました"
        )

    except Exception as e:

        print(
            f"❌ コマンド同期エラー: {repr(e)}"
        )

    print(
        "========================================"
    )

    print(
        "🛒 キラの自動販売機 起動完了"
    )

    print(
        "========================================"
    )


# =========================================================
# /ping
# =========================================================

@bot.tree.command(
    name="ping",
    description="Botの動作確認"
)
async def ping(
    interaction
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🏓 Pong!",
        ephemeral=True
    )


# =========================================================
# /admin
# =========================================================

@bot.tree.command(
    name="admin",
    description="キラの自動販売機 管理画面"
)
async def admin(
    interaction
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="👑 KIRA VENDING",
        description=(
            "## 管理者コントロールパネル\n\n"
            "🛒 **販売設定**\n"
            "販売チャンネル・注文通知を設定\n\n"
            "📦 **商品管理**\n"
            "商品追加・編集・削除・在庫変更\n\n"
            "🎨 **デザイン**\n"
            "自販機パネルのカラーを変更"
        ),
        color=CONFIG.get(
            "panel_color",
            0x5865F2
        )
    )

    embed.set_footer(
        text="KIRA VENDING • ADMIN PANEL"
    )

    await interaction.response.send_message(
        embed=embed,
        view=AdminView(),
        ephemeral=True
    )


# =========================================================
# エラーハンドラー
# =========================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    print(
        f"[APP COMMAND ERROR] {repr(error)}"
    )

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                "❌ コマンド処理中にエラーが発生しました。",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ コマンド処理中にエラーが発生しました。",
                ephemeral=True
            )

    except Exception:

        pass


# =========================================================
# Token
# =========================================================

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)

if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN が設定されていません。"
    )


bot.run(TOKEN)
