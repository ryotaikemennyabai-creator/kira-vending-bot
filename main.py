import os
import json
import asyncio
import hashlib
from datetime import datetime, timezone

import discord
from discord.ext import commands

PRODUCTS_FILE = "products.json"
CONFIG_FILE = "config.json"
ORDERS_FILE = "orders.json"

BOT_NAME = "キラの自動販売機"


# =========================================================
# 初期データ
# =========================================================

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
    "panel_description": "下のボタンから商品を選択してください。",
    "order_counter": 0
}


# =========================================================
# JSON
# =========================================================

def save_json(path, data):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(temp, path)


def load_json(path, default):
    if not os.path.exists(path):
        save_json(path, default)
        return json.loads(json.dumps(default))

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        save_json(path, default)
        return json.loads(json.dumps(default))


PRODUCTS = load_json(
    PRODUCTS_FILE,
    DEFAULT_PRODUCTS
)

CONFIG = load_json(
    CONFIG_FILE,
    DEFAULT_CONFIG
)

ORDERS = load_json(
    ORDERS_FILE,
    []
)


for name, data in list(PRODUCTS.items()):

    if not isinstance(data, dict):

        PRODUCTS[name] = {
            "price": 0,
            "stock": 0,
            "emoji": "🛒"
        }

    else:

        data.setdefault(
            "price",
            0
        )

        data.setdefault(
            "stock",
            0
        )

        data.setdefault(
            "emoji",
            "🛒"
        )


for key, value in DEFAULT_CONFIG.items():

    CONFIG.setdefault(
        key,
        value
    )


save_json(
    PRODUCTS_FILE,
    PRODUCTS
)

save_json(
    CONFIG_FILE,
    CONFIG
)


# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# 同時購入対策
purchase_lock = asyncio.Lock()


# =========================================================
# 共通関数
# =========================================================

def is_admin(interaction):

    if not interaction.guild:
        return False

    return interaction.user.guild_permissions.administrator


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def product_hash(name):

    return hashlib.sha256(
        name.encode("utf-8")
    ).hexdigest()[:16]


def find_order(order_id):

    for order in ORDERS:

        if order.get("order_id") == order_id:
            return order

    return None


def next_order_id():

    CONFIG["order_counter"] = int(
        CONFIG.get(
            "order_counter",
            0
        )
    ) + 1

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return f"KIRA-{CONFIG['order_counter']:05d}"


# =========================================================
# 自販機パネル
# =========================================================

def create_panel_embed():

    embed = discord.Embed(
        title=CONFIG.get(
            "panel_title",
            "🛒 キラの自動販売機"
        ),
        description=(
            CONFIG.get(
                "panel_description",
                "下のボタンから商品を選択してください。"
            )
            + "\n\n"
            "💳 **PayPay送金URLで支払い**\n"
            "🛒 商品選択 → 購入確認 → PayPay URL入力\n"
            "💬 購入後は専用チャットを自動作成します。"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    lines = []

    for name, data in PRODUCTS.items():

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

        if stock > 0:

            status = (
                f"🟢 在庫 {stock}個"
            )

        else:

            status = "🔴 SOLD OUT"

        lines.append(
            f"{emoji} **{name}** "
            f"`{price:,}円` "
            f"{status}"
        )

    text = "\n".join(lines)

    if len(text) > 1024:
        text = text[:1000] + "\n…"

    if not text:
        text = "商品がありません。"

    embed.add_field(
        name="🛍️ 商品一覧",
        value=text,
        inline=False
    )

    embed.set_footer(
        text="KIRA VENDING"
    )

    return embed


# =========================================================
# 商品ボタン
# ここが「時間経過後もボタンを使える」重要部分
# =========================================================

class ProductButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"kira:product:(?P<ph>[0-9a-f]{16})"
):

    def __init__(
        self,
        item_or_name,
        data=None,
        index=0,
        ph=None
    ):

        # Discordから古いボタンを復元した場合
        if isinstance(
            item_or_name,
            discord.ui.Button
        ):

            super().__init__(
                item_or_name
            )

            self.ph = ph or ""

            return

        name = item_or_name

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

        if stock > 0:

            label = (
                f"{name} • {price:,}円"
            )

            style = (
                discord.ButtonStyle.green
            )

        else:

            label = (
                f"{name} • SOLD OUT"
            )

            style = (
                discord.ButtonStyle.gray
            )

        button = discord.ui.Button(
            label=label[:80],
            emoji=emoji,
            style=style,
            disabled=(
                stock <= 0
            ),
            custom_id=(
                f"kira:product:"
                f"{product_hash(name)}"
            ),
            row=index // 5
        )

        super().__init__(
            button
        )

        self.ph = product_hash(
            name
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            ph=match["ph"]
        )

    def get_product_name(self):

        for name in PRODUCTS:

            if (
                product_hash(name)
                == self.ph
            ):
                return name

        return None

    async def callback(
        self,
        interaction
    ):

        try:

            name = self.get_product_name()

            product = (
                PRODUCTS.get(name)
                if name
                else None
            )

            if not product:

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
                    f"## {emoji} {name}\n\n"
                    f"💴 **価格**\n"
                    f"`{int(product.get('price', 0)):,}円`\n\n"
                    f"📦 **在庫**\n"
                    f"`{stock}個`\n\n"
                    "この商品を購入しますか？\n"
                    "購入するとPayPay送金URLの入力画面が開きます。"
                ),
                color=int(
                    CONFIG.get(
                        "panel_color",
                        0x5865F2
                    )
                )
            )

            await interaction.response.send_message(
                embed=embed,
                view=PurchaseConfirmView(
                    name
                ),
                ephemeral=True
            )

        except Exception as e:

            print(
                f"[PRODUCT BUTTON ERROR] {repr(e)}"
            )

            try:

                if not interaction.response.is_done():

                    await interaction.response.send_message(
                        "❌ ボタン処理中にエラーが発生しました。",
                        ephemeral=True
                    )

                else:

                    await interaction.followup.send(
                        "❌ ボタン処理中にエラーが発生しました。",
                        ephemeral=True
                    )

            except Exception:
                pass


# =========================================================
# 自販機View
# =========================================================

class VendingView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        for index, (
            name,
            data
        ) in enumerate(
            list(
                PRODUCTS.items()
            )[:25]
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

        self.product_name = (
            product_name
        )

    @discord.ui.button(
        label="購入する",
        emoji="🛒",
        style=discord.ButtonStyle.green
    )
    async def buy(
        self,
        interaction,
        button
    ):

        product = PRODUCTS.get(
            self.product_name
        )

        if (
            not product
            or int(
                product.get(
                    "stock",
                    0
                )
            ) <= 0
        ):

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
        style=discord.ButtonStyle.gray
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
# PayPay入力
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

        self.product_name = (
            product_name
        )

        self.url_input = (
            discord.ui.TextInput(
                label="PayPay送金URL",
                placeholder="https://pay.paypay.ne.jp/...",
                required=True,
                max_length=500
            )
        )

        self.add_item(
            self.url_input
        )

    async def on_submit(
        self,
        interaction
    ):

        # 3秒以内に必ず応答する
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        if not interaction.guild:

            await interaction.followup.send(
                "❌ サーバー内でのみ購入できます。",
                ephemeral=True
            )

            return

        # 同時購入を防止
        async with purchase_lock:

            product = PRODUCTS.get(
                self.product_name
            )

            if not product:

                await interaction.followup.send(
                    "❌ 商品がありません。",
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

                await interaction.followup.send(
                    "🔴 売り切れです。",
                    ephemeral=True
                )

                return

            paypay_url = (
                self.url_input.value.strip()
            )

            if not (
                paypay_url.startswith(
                    "https://"
                )
                or paypay_url.startswith(
                    "http://"
                )
            ):

                await interaction.followup.send(
                    "❌ PayPay送金URLの形式が正しくありません。",
                    ephemeral=True
                )

                return

            order_id = next_order_id()

            order = {
                "order_id": order_id,
                "user_id": interaction.user.id,
                "username": str(
                    interaction.user
                ),
                "guild_id": interaction.guild.id,
                "product": self.product_name,
                "price": int(
                    product.get(
                        "price",
                        0
                    )
                ),
                "paypay_url": paypay_url,
                "status": "支払い確認待ち",
                "created_at": now_iso(),
                "ticket_channel_id": None,
                "ticket_created": False
            }

            # 先に在庫を確保
            product["stock"] = (
                stock - 1
            )

            ORDERS.append(
                order
            )

            save_json(
                PRODUCTS_FILE,
                PRODUCTS
            )

            save_json(
                ORDERS_FILE,
                ORDERS
            )

        # パネル更新
        try:

            await update_vending_panel()

        except Exception as e:

            print(
                f"[PANEL UPDATE ERROR] {repr(e)}"
            )

        # =====================================================
        # 専用チャット
        # =====================================================

        ticket = None

        try:

            ticket = await create_ticket(
                interaction.guild,
                interaction.user,
                order
            )

            order[
                "ticket_created"
            ] = True

            save_json(
                ORDERS_FILE,
                ORDERS
            )

        except Exception as e:

            print(
                f"[PURCHASE] 専用チャット作成失敗 "
                f"#{order_id}: {repr(e)}"
            )

        # =====================================================
        # 注文通知
        # =====================================================

        try:

            notification_channel = (
                await ensure_order_channel(
                    interaction.guild
                )
            )

            embed = discord.Embed(
                title="🛒 新しい注文",
                description=(
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 **注文番号**\n"
                    f"`{order_id}`\n\n"
                    f"👤 **購入者**\n"
                    f"<@{interaction.user.id}>\n\n"
                    f"🛍️ **商品**\n"
                    f"{self.product_name}\n\n"
                    f"💴 **金額**\n"
                    f"`{order['price']:,}円`\n\n"
                    "🟡 **支払い確認待ち**\n"
                    "━━━━━━━━━━━━━━━━━━━━"
                ),
                color=0xF1C40F
            )

            embed.add_field(
                name="💳 PayPay送金URL",
                value=paypay_url[:1024],
                inline=False
            )

            await notification_channel.send(
                embed=embed,
                view=OrderAdminView(
                    order_id
                )
            )

        except Exception as e:

            print(
                f"[PURCHASE] 注文通知失敗 "
                f"#{order_id}: {repr(e)}"
            )

        # =====================================================
        # 購入者DM
        # =====================================================

        try:

            if ticket:

                ticket_text = (
                    ticket.mention
                )

            else:

                ticket_text = (
                    "⚠️ 専用チャットの作成に失敗しました。"
                )

            await interaction.user.send(
                "🛒 **キラの自動販売機**\n\n"
                f"🧾 注文番号：`{order_id}`\n"
                f"🛍️ 商品：{self.product_name}\n"
                f"💴 金額：`{order['price']:,}円`\n"
                "🟡 支払い確認待ち\n\n"
                f"💬 専用チャット：{ticket_text}"
            )

        except Exception as e:

            print(
                f"[DM ERROR] {repr(e)}"
            )

        # =====================================================
        # 購入者へ結果
        # =====================================================

        message = (
            f"✅ **注文 {order_id} を受け付けました！**\n\n"
            f"🛍️ 商品：**{self.product_name}**\n"
            f"💴 金額：`{order['price']:,}円`\n"
        )

        if ticket:

            message += (
                f"💬 専用チャット："
                f"{ticket.mention}"
            )

        else:

            message += (
                "⚠️ 専用チャットの作成に失敗しました。"
                "管理者に通知されています。"
            )

        await interaction.followup.send(
            message,
            ephemeral=True
        )


# =========================================================
# カテゴリ作成
# =========================================================

async def get_or_create_category(
    guild,
    config_key,
    name
):

    saved_id = CONFIG.get(
        config_key
    )

    if saved_id:

        try:

            category = guild.get_channel(
                int(saved_id)
            )

            if isinstance(
                category,
                discord.CategoryChannel
            ):

                return category

        except Exception:
            pass

    me = guild.me

    if not me:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )

    if not me.guild_permissions.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )

    overwrites = {
        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        me:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_permissions=True
            )
    }

    # 管理者ロールにもアクセス許可
    for role in guild.roles:

        if (
            not role.is_default()
            and role.permissions.administrator
        ):

            overwrites[role] = (
                discord.PermissionOverwrite(
                    view_channel=True
                )
            )

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

    me = guild.me

    if not me:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )

    if not me.guild_permissions.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )

    # カテゴリは失敗してもサーバー直下で作れるようにする
    try:

        category = await get_or_create_category(
            guild,
            "ticket_category_id",
            "💬 購入チャット"
        )

    except Exception as e:

        print(
            f"[TICKET] カテゴリ作成失敗。"
            f"サーバー直下で作成します: {repr(e)}"
        )

        category = None

    channel_name = (
        f"chat-{order['order_id'].lower()}"
    )

    # =====================================================
    # ① チャンネルを作る
    # =====================================================

    try:

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            topic=(
                f"注文 {order['order_id']} / "
                f"購入者 {user.id}"
            ),
            reason=(
                f"注文 {order['order_id']} "
                "専用チャット"
            )
        )

    except discord.Forbidden as e:

        print(
            f"[TICKET] カテゴリ付き作成失敗。"
            f"直下で再試行: {repr(e)}"
        )

        channel = await guild.create_text_channel(
            channel_name,
            topic=(
                f"注文 {order['order_id']} / "
                f"購入者 {user.id}"
            ),
            reason=(
                f"注文 {order['order_id']} "
                "専用チャット 再試行"
            )
        )

    # =====================================================
    # ② 権限を明示的に設定
    # =====================================================

    try:

        # 一般ユーザー
        await channel.set_permissions(
            guild.default_role,
            view_channel=False
        )

        # Bot
        await channel.set_permissions(
            me,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True
        )

        # 購入者
        await channel.set_permissions(
            user,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True
        )

        # 管理者ロール
        for role in guild.roles:

            if (
                not role.is_default()
                and role.permissions.administrator
            ):

                await channel.set_permissions(
                    role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True
                )

    except Exception as e:

        print(
            f"[TICKET] 権限設定失敗: {repr(e)}"
        )

        try:

            await channel.delete(
                reason="専用チャット権限設定失敗"
            )

        except Exception:
            pass

        raise RuntimeError(
            "専用チャットの権限設定に失敗しました。"
        )

    # =====================================================
    # ③ 注文データに保存
    # =====================================================

    order[
        "ticket_channel_id"
    ] = channel.id

    save_json(
        ORDERS_FILE,
        ORDERS
    )

    # =====================================================
    # ④ 初期メッセージ
    # =====================================================

    embed = discord.Embed(
        title="💬 購入専用チャット",
        description=(
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 **注文番号**\n"
            f"`{order['order_id']}`\n\n"
            f"🛍️ **商品**\n"
            f"{order['product']}\n\n"
            f"💴 **金額**\n"
            f"`{order['price']:,}円`\n\n"
            "🟡 **支払い確認待ち**\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "このチャットは\n"
            "**購入者・管理者・Bot** "
            "のみが利用できます。"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    embed.set_footer(
        text=f"{BOT_NAME} • {order['order_id']}"
    )

    try:

        await channel.send(
            content=user.mention,
            embed=embed,
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True
                )
            )
        )

    except Exception as e:

        print(
            f"[TICKET] 初期メッセージ送信失敗: "
            f"{repr(e)}"
        )

        try:

            await channel.delete(
                reason="専用チャット初期メッセージ失敗"
            )

        except Exception:
            pass

        raise RuntimeError(
            "専用チャットの初期メッセージ送信に失敗しました。"
        )

    return channel


# =========================================================
# 注文通知チャンネル
# =========================================================

async def ensure_order_channel(
    guild
):

    me = guild.me

    if not me:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )

    if not me.guild_permissions.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )

    channel = None

    # 保存済みチャンネル
    saved_id = CONFIG.get(
        "order_channel_id"
    )

    if saved_id:

        try:

            candidate = guild.get_channel(
                int(saved_id)
            )

            if isinstance(
                candidate,
                discord.TextChannel
            ):

                channel = candidate

        except Exception:
            pass

    # 名前で探す
    if channel is None:

        for ch in guild.text_channels:

            if ch.name == "注文通知":

                channel = ch
                break

    # =====================================================
    # 無ければ自動作成
    # =====================================================

    if channel is None:

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            me:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True,
                    manage_channels=True
                )
        }

        for role in guild.roles:

            if (
                not role.is_default()
                and role.permissions.administrator
            ):

                overwrites[role] = (
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        embed_links=True
                    )
                )

        channel = await guild.create_text_channel(
            "注文通知",
            overwrites=overwrites,
            topic=(
                f"{BOT_NAME} "
                "注文通知（管理者専用）"
            ),
            reason=(
                f"{BOT_NAME} "
                "注文通知チャンネル自動作成"
            )
        )

    else:

        # 既存の #注文通知 も強制的に管理者専用へ
        await channel.set_permissions(
            guild.default_role,
            view_channel=False
        )

        await channel.set_permissions(
            me,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True
        )

        for role in guild.roles:

            if (
                not role.is_default()
                and role.permissions.administrator
            ):

                await channel.set_permissions(
                    role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True
                )

    CONFIG[
        "order_channel_id"
    ] = channel.id

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return channel


# =========================================================
# 注文管理ボタン
# =========================================================

class OrderView(
    discord.ui.View
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            timeout=None
        )

        self.add_item(
            discord.ui.Button(
                label="支払い確認済み",
                emoji="✅",
                style=discord.ButtonStyle.green,
                custom_id=(
                    f"kira:paid:{order_id}"
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="キャンセル",
                emoji="❌",
                style=discord.ButtonStyle.red,
                custom_id=(
                    f"kira:cancel:{order_id}"
                )
            )
        )


class OrderAdminButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=r"kira:(?P<action>paid|cancel):(?P<oid>KIRA-\d{5})"
):

    def __init__(
        self,
        item,
        action,
        oid
    ):

        super().__init__(
            item
        )

        self.action = action
        self.oid = oid

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
            match["oid"]
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        order = find_order(
            self.oid
        )

        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return

        if self.action == "paid":

            order["status"] = (
                "支払い確認済み"
            )

            save_json(
                ORDERS_FILE,
                ORDERS
            )

            await interaction.response.send_message(
                "✅ 支払い確認済みにしました。",
                ephemeral=True
            )

            try:

                user = await bot.fetch_user(
                    int(
                        order["user_id"]
                    )
                )

                await user.send(
                    "✅ **支払い確認済み**\n\n"
                    f"注文番号：`{order['order_id']}`\n"
                    f"商品：{order['product']}\n"
                    f"価格：`{order['price']:,}円`"
                )

            except Exception:
                pass

        else:

            if not order.get(
                "cancelled_stock_returned",
                False
            ):

                product = PRODUCTS.get(
                    order["product"]
                )

                if product:

                    product["stock"] = (
                        int(
                            product.get(
                                "stock",
                                0
                            )
                        ) + 1
                    )

                    save_json(
                        PRODUCTS_FILE,
                        PRODUCTS
                    )

                order[
                    "cancelled_stock_returned"
                ] = True

            order["status"] = (
                "キャンセル"
            )

            save_json(
                ORDERS_FILE,
                ORDERS
            )

            await update_vending_panel()

            await interaction.response.send_message(
                "❌ 注文をキャンセルしました。\n"
                "在庫を1個戻しました。",
                ephemeral=True
            )


# =========================================================
# 商品追加
# =========================================================

class AddProductModal(
    discord.ui.Modal
):

    def __init__(self):

        super().__init__(
            title="🛍️ 商品追加"
        )

        self.name_input = (
            discord.ui.TextInput(
                label="商品名",
                placeholder="例：コーラ",
                required=True,
                max_length=40
            )
        )

        self.price_input = (
            discord.ui.TextInput(
                label="価格",
                placeholder="100",
                required=True
            )
        )

        self.stock_input = (
            discord.ui.TextInput(
                label="在庫",
                placeholder="10",
                required=True
            )
        )

        self.emoji_input = (
            discord.ui.TextInput(
                label="絵文字",
                placeholder="🥤",
                required=True,
                max_length=10
            )
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

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

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

        name = (
            self.name_input.value.strip()
        )

        PRODUCTS[name] = {

            "price": price,

            "stock": stock,

            "emoji":
                self.emoji_input.value.strip()
                or "🛒"
        }

        save_json(
            PRODUCTS_FILE,
            PRODUCTS
        )

        await update_vending_panel()

        await interaction.response.send_message(
            f"✅ **{name}** を追加しました。",
            ephemeral=True
        )


# =========================================================
# 在庫変更
# =========================================================

class StockModal(
    discord.ui.Modal
):

    def __init__(
        self,
        product_name
    ):

        super().__init__(
            title=f"📦 {product_name} 在庫"
        )

        self.product_name = (
            product_name
        )

        self.stock_input = (
            discord.ui.TextInput(
                label="新しい在庫数",
                default=str(
                    PRODUCTS[
                        product_name
                    ].get(
                        "stock",
                        0
                    )
                ),
                required=True
            )
        )

        self.add_item(
            self.stock_input
        )

    async def on_submit(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):
            return

        try:

            stock = int(
                self.stock_input.value
            )

            if stock < 0:
                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                "❌ 0以上の数字を入力してください。",
                ephemeral=True
            )

            return

        PRODUCTS[
            self.product_name
        ]["stock"] = stock

        save_json(
            PRODUCTS_FILE,
            PRODUCTS
        )

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ 在庫を変更しました。",
            ephemeral=True
        )


class ProductSelect(
    discord.ui.Select
):

    def __init__(
        self,
        action
    ):

        self.action = action

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
                    value=name
                )
            )

        super().__init__(
            placeholder="商品を選択",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        name = self.values[0]

        if self.action == "stock":

            await interaction.response.send_modal(
                StockModal(name)
            )

        elif self.action == "delete":

            if name in PRODUCTS:

                del PRODUCTS[name]

                save_json(
                    PRODUCTS_FILE,
                    PRODUCTS
                )

                await update_vending_panel()

                await interaction.response.send_message(
                    f"🗑️ **{name}** を削除しました。",
                    ephemeral=True
                )


class ProductSelectView(
    discord.ui.View
):

    def __init__(
        self,
        action
    ):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                ProductSelect(
                    action
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
            AdminStockButton()
        )

        self.add_item(
            AdminDeleteButton()
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
            custom_id="kira:admin:install"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        channel = interaction.channel

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
            "✅ 自販機を設置しました。",
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
            custom_id="kira:admin:order"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        channel = await ensure_order_channel(
            interaction.guild
        )

        await interaction.response.send_message(
            f"📩 注文通知チャンネル："
            f"{channel.mention}",
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
            custom_id="kira:admin:add"
        )

    async def callback(
        self,
        interaction
    ):

        if is_admin(
            interaction
        ):

            await interaction.response.send_modal(
                AddProductModal()
            )


class AdminStockButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="在庫変更",
            emoji="📦",
            style=discord.ButtonStyle.gray,
            custom_id="kira:admin:stock"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):
            return

        if not PRODUCTS:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "📦 商品を選択してください。",
            view=ProductSelectView(
                "stock"
            ),
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
            custom_id="kira:admin:delete"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):
            return

        if not PRODUCTS:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🗑️ 商品を選択してください。",
            view=ProductSelectView(
                "delete"
            ),
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
            custom_id="kira:admin:refresh"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):
            return

        result = (
            await update_vending_panel()
        )

        if result:

            text = "✅ パネルを更新しました。"

        else:

            text = (
                "⚠️ 自販機パネルが設定されていません。"
            )

        await interaction.response.send_message(
            text,
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

        channel = (
            bot.get_channel(
                int(channel_id)
            )
            or
            await bot.fetch_channel(
                int(channel_id)
            )
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

    except Exception as e:

        print(
            f"[PANEL] 更新失敗: {repr(e)}"
        )

        return False


# =========================================================
# 永続ボタン登録
# =========================================================

@bot.event
async def setup_hook():

    print(
        "🔧 Persistent UIを登録しています..."
    )

    # ★ 購入ボタン
    # 再起動しても古いメッセージのボタンを処理できる
    bot.add_dynamic_items(
        ProductButton
    )

    # ★ 注文処理ボタン
    bot.add_dynamic_items(
        OrderAdminButton
    )

    # ★ 管理パネル
    bot.add_view(
        AdminView()
    )

    # Slash Commands
    try:

        synced = await bot.tree.sync()

        print(
            f"✅ コマンドを "
            f"{len(synced)} 個同期しました。"
        )

    except Exception as e:

        print(
            f"❌ コマンド同期失敗: {repr(e)}"
        )


# =========================================================
# 起動
# =========================================================

@bot.event
async def on_ready():

    print(
        f"✅ ログインしました: {bot.user}"
    )

    # 起動時・再接続時に注文通知チャンネルを確認
    for guild in bot.guilds:

        try:

            await ensure_order_channel(
                guild
            )

        except Exception as e:

            print(
                f"[STARTUP] 注文通知チャンネル失敗: "
                f"{repr(e)}"
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

    if not is_admin(
        interaction
    ):

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

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="👑 KIRA VENDING",
        description=(
            "## 管理者コントロールパネル\n\n"
            "🛒 **自販機を設置**\n"
            "📩 **注文通知チャンネル**\n"
            "➕ **商品追加**\n"
            "📦 **在庫変更**\n"
            "🗑️ **商品削除**\n"
            "🔄 **パネル更新**"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    await interaction.response.send_message(
        embed=embed,
        view=AdminView(),
        ephemeral=True
    )


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
