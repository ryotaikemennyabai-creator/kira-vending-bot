import os
import json
import hashlib
from datetime import datetime

import discord
from discord.ext import commands


# =========================================================
# ファイル
# =========================================================

PRODUCT_FILE = "products.json"
CONFIG_FILE = "config.json"
ORDER_FILE = "orders.json"


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
    "order_channel_id": None,
    "ticket_category_id": None,
    "archive_category_id": None,
    "panel_message_id": None,
    "panel_color": 0x5865F2,
    "panel_title": "🥤 キラの自動販売機",
    "panel_description": "購入したい商品を選択してください！"
}


# =========================================================
# JSON
# =========================================================

def save_json(filename, data):

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def load_json(filename, default):

    if not os.path.exists(filename):

        save_json(
            filename,
            default
        )

        return default.copy()

    try:

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        save_json(
            filename,
            default
        )

        return default.copy()


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
# 古い商品データを自動修正
# =========================================================

for name, data in list(PRODUCTS.items()):

    if isinstance(data, int):

        PRODUCTS[name] = {
            "price": data,
            "stock": 10,
            "emoji": "🛒"
        }

    else:

        if "price" not in data:
            data["price"] = 0

        if "stock" not in data:
            data["stock"] = 10

        if "emoji" not in data:
            data["emoji"] = "🛒"


save_json(
    PRODUCT_FILE,
    PRODUCTS
)


# =========================================================
# Bot
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# 管理者
# =========================================================

def is_admin(interaction):

    return interaction.user.guild_permissions.administrator


# =========================================================
# 商品ID
# =========================================================

def product_custom_id(name):

    hashed = hashlib.sha256(
        name.encode("utf-8")
    ).hexdigest()[:16]

    return f"kira_product_{hashed}"


# =========================================================
# パネル
# =========================================================

def create_panel_embed():

    embed = discord.Embed(
        title=CONFIG.get(
            "panel_title",
            "🥤 キラの自動販売機"
        ),
        description=CONFIG.get(
            "panel_description",
            "購入したい商品を選択してください！"
        ),
        color=CONFIG.get(
            "panel_color",
            0x5865F2
        )
    )

    text = ""

    for name, data in PRODUCTS.items():

        emoji = data.get(
            "emoji",
            "🛒"
        )

        price = data.get(
            "price",
            0
        )

        stock = data.get(
            "stock",
            0
        )

        if stock <= 0:

            status = "🔴 売り切れ"

        else:

            status = f"🟢 残り {stock}個"

        text += (
            f"{emoji} **{name}**\n"
            f"💴 **{price}円**　{status}\n\n"
        )

    if not text:

        text = "現在商品がありません。"

    embed.add_field(
        name="🛍️ 商品一覧",
        value=text[:1024],
        inline=False
    )

    embed.set_footer(
        text="商品ボタンから購入できます"
    )

    return embed


# =========================================================
# 注文番号
# =========================================================

def create_order_id():

    number = len(ORDERS) + 1

    existing = {
        order.get("order_id")
        for order in ORDERS
    }

    while True:

        order_id = f"KIRA-{number:05d}"

        if order_id not in existing:
            return order_id

        number += 1


# =========================================================
# 注文検索
# =========================================================

def find_order(order_id):

    for order in ORDERS:

        if order.get(
            "order_id"
        ) == order_id:

            return order

    return None


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

        price = data.get(
            "price",
            0
        )

        stock = data.get(
            "stock",
            0
        )

        emoji = data.get(
            "emoji",
            "🛒"
        )

        if stock <= 0:

            label = f"{name}｜売切"

            style = discord.ButtonStyle.gray

        else:

            label = f"{name}｜{price}円"

            style = BUTTON_STYLES[
                index % len(BUTTON_STYLES)
            ]

        super().__init__(
            label=label[:80],
            emoji=emoji,
            style=style,
            disabled=(stock <= 0),
            custom_id=product_custom_id(name)
        )

        self.product_name = name

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        product = PRODUCTS.get(
            self.product_name
        )

        if not product:

            await interaction.response.send_message(
                "❌ この商品はありません。",
                ephemeral=True
            )

            return

        if product.get(
            "stock",
            0
        ) <= 0:

            await interaction.response.send_message(
                "❌ 売り切れです。",
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
                f"### {emoji} {self.product_name}\n\n"
                f"💴 **価格：{product['price']}円**\n"
                f"📦 **在庫：{product['stock']}個**\n\n"
                f"この商品を購入しますか？"
            ),
            color=CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=ConfirmPurchaseView(
                self.product_name
            ),
            ephemeral=True
        )


# =========================================================
# 自動販売機View
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

class ConfirmPurchaseView(
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
        style=discord.ButtonStyle.green,
        emoji="🛒"
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

        if product["stock"] <= 0:

            await interaction.response.send_message(
                "❌ 売り切れです。",
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
        style=discord.ButtonStyle.gray,
        emoji="❌"
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

        self.product_name = product_name

        self.url_input = discord.ui.TextInput(
            label="PayPay送金URL",
            placeholder="PayPayの送金URLを貼り付けてください",
            required=True,
            max_length=500
        )

        self.add_item(
            self.url_input
        )

    async def on_submit(
        self,
        interaction
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

        if product["stock"] <= 0:

            await interaction.response.send_message(
                "❌ 売り切れになりました。",
                ephemeral=True
            )

            return

        paypay_url = self.url_input.value.strip()

        if not paypay_url.startswith(
            ("http://", "https://")
        ):

            await interaction.response.send_message(
                "❌ 正しいURLを入力してください。",
                ephemeral=True
            )

            return

        order_id = create_order_id()

        order = {
            "order_id": order_id,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "product": self.product_name,
            "price": product["price"],
            "paypay_url": paypay_url,
            "status": "支払い確認待ち",
            "created_at": datetime.now().isoformat(),
            "ticket_channel_id": None
        }

        ORDERS.append(
            order
        )

        product["stock"] -= 1

        save_json(
            ORDER_FILE,
            ORDERS
        )

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        # まず購入者へ返答
        await interaction.response.send_message(
            f"## ✅ 注文受付完了\n\n"
            f"注文番号：`{order_id}`\n"
            f"商品：**{self.product_name}**\n"
            f"価格：**{product['price']}円**\n\n"
            f"💬 専用チャットを作成しています。",
            ephemeral=True
        )

        # 個別チャット作成
        ticket = await create_ticket(
            interaction.guild,
            interaction.user,
            order
        )

        # 注文通知
        await send_order_notification(
            interaction.guild,
            order
        )

        # DM
        await send_order_dm(
            interaction.user,
            order,
            ticket
        )

        # パネル更新
        await update_vending_panel()


# =========================================================
# 個別チャット作成
# =========================================================

async def create_ticket(
    guild,
    user,
    order
):

    category = None

    category_id = CONFIG.get(
        "ticket_category_id"
    )

    if category_id:

        category = guild.get_channel(
            int(category_id)
        )

    # カテゴリがなければ自動作成
    if category is None:

        category = await guild.create_category(
            "💬 購入チャット"
        )

        CONFIG[
            "ticket_category_id"
        ] = category.id

        save_json(
            CONFIG_FILE,
            CONFIG
        )

    channel_name = (
        f"chat-{order['order_id'].lower()}"
    )

    overwrites = {

        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        user:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
    }

    # 管理者を追加
    for member in guild.members:

        if member.guild_permissions.administrator:

            overwrites[member] = (
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            )

    channel = await guild.create_text_channel(
        channel_name,
        category=category,
        overwrites=overwrites,
        topic=f"注文 {order['order_id']}"
    )

    order[
        "ticket_channel_id"
    ] = channel.id

    save_json(
        ORDER_FILE,
        ORDERS
    )

    embed = discord.Embed(
        title="💬 購入専用チャット",
        description=(
            f"## {order['product']}\n\n"
            f"注文番号：`{order['order_id']}`\n"
            f"価格：**{order['price']}円**\n"
            f"状態：🟡 支払い確認待ち\n\n"
            f"このチャットで管理者とやり取りできます。\n\n"
            f"🗃️ **履歴として保存**\n"
            f"→ 会話を残したまま閉じます。\n\n"
            f"🗑️ **チャット削除**\n"
            f"→ このチャットを完全に削除します。"
        ),
        color=CONFIG.get(
            "panel_color",
            0x5865F2
        )
    )

    await channel.send(
        content=f"{user.mention}",
        embed=embed,
        view=TicketView(
            order["order_id"],
            user.id
        )
    )

    return channel


# =========================================================
# 購入者DM
# =========================================================

async def send_order_dm(
    user,
    order,
    ticket
):

    try:

        ticket_text = (
            ticket.mention
            if ticket
            else "専用チャットを作成できませんでした"
        )

        await user.send(
            f"🛒 **キラの自動販売機 注文受付**\n\n"
            f"注文番号：`{order['order_id']}`\n"
            f"商品：**{order['product']}**\n"
            f"価格：**{order['price']}円**\n"
            f"状態：🟡 支払い確認待ち\n\n"
            f"💬 専用チャット：{ticket_text}\n\n"
            f"PayPay送金URLを受け付けました。"
        )

    except discord.Forbidden:

        print(
            f"{user} はDMを受信できません。"
        )

    except Exception as e:

        print(
            f"DM送信エラー: {e}"
        )


# =========================================================
# 注文通知
# =========================================================

async def send_order_notification(
    guild,
    order
):

    channel_id = CONFIG.get(
        "order_channel_id"
    )

    if not channel_id:
        return

    try:

        channel = guild.get_channel(
            int(channel_id)
        )

        if channel is None:

            channel = await guild.fetch_channel(
                int(channel_id)
            )

        embed = discord.Embed(
            title="🛒 新しい注文",
            color=0xFEE75C
        )

        embed.add_field(
            name="注文番号",
            value=f"`{order['order_id']}`",
            inline=False
        )

        embed.add_field(
            name="購入者",
            value=(
                f"<@{order['user_id']}>\n"
                f"`{order['username']}`"
            ),
            inline=True
        )

        embed.add_field(
            name="商品",
            value=order["product"],
            inline=True
        )

        embed.add_field(
            name="価格",
            value=f"{order['price']}円",
            inline=True
        )

        embed.add_field(
            name="状態",
            value="🟡 支払い確認待ち",
            inline=False
        )

        embed.add_field(
            name="PayPay送金URL",
            value=order["paypay_url"],
            inline=False
        )

        await channel.send(
            embed=embed,
            view=OrderAdminView(
                order["order_id"]
            )
        )

    except Exception as e:

        print(
            f"注文通知エラー: {e}"
        )


# =========================================================
# 注文管理
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

    @discord.ui.button(
        label="支払い確認済み",
        style=discord.ButtonStyle.green,
        emoji="✅"
    )
    async def paid(
        self,
        interaction,
        button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ 管理者専用です。",
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

        order["status"] = (
            "支払い確認済み"
        )

        save_json(
            ORDER_FILE,
            ORDERS
        )

        await interaction.response.send_message(
            "✅ 支払い確認済みにしました。",
            ephemeral=True
        )

        await interaction.message.edit(
            view=OrderCompletedView()
        )

        # 購入者DM
        try:

            user = await bot.fetch_user(
                order["user_id"]
            )

            await user.send(
                f"✅ **支払い確認済み**\n\n"
                f"注文番号：`{order['order_id']}`\n"
                f"商品：{order['product']}\n"
                f"価格：{order['price']}円"
            )

        except Exception:
            pass

    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.red,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )

            return

        order = find_order(
            self.order_id
        )

        if not order:
            return

        order["status"] = "キャンセル"

        # 在庫を戻す
        if order["product"] in PRODUCTS:

            PRODUCTS[
                order["product"]
            ]["stock"] += 1

            save_json(
                PRODUCT_FILE,
                PRODUCTS
            )

        save_json(
            ORDER_FILE,
            ORDERS
        )

        await interaction.response.send_message(
            "❌ 注文をキャンセルしました。",
            ephemeral=True
        )

        await interaction.message.edit(
            view=OrderCompletedView()
        )

        await update_vending_panel()


class OrderCompletedView(
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
                disabled=True
            )
        )


# =========================================================
# 購入チャット管理
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

    @discord.ui.button(
        label="履歴として保存",
        style=discord.ButtonStyle.blurple,
        emoji="🗃️"
    )
    async def archive(
        self,
        interaction,
        button
    ):

        if (
            interaction.user.id != self.user_id
            and not is_admin(interaction)
        ):

            await interaction.response.send_message(
                "❌ このチャットを操作できません。",
                ephemeral=True
            )

            return

        channel = interaction.channel

        archive_category = None

        category_id = CONFIG.get(
            "archive_category_id"
        )

        if category_id:

            archive_category = (
                interaction.guild.get_channel(
                    int(category_id)
                )
            )

        if archive_category is None:

            archive_category = (
                await interaction.guild.create_category(
                    "📁 購入履歴"
                )
            )

            CONFIG[
                "archive_category_id"
            ] = archive_category.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

        await interaction.response.send_message(
            "🗃️ このチャットを履歴として保存します。",
            ephemeral=True
        )

        await channel.edit(
            category=archive_category,
            name=f"archived-{self.order_id.lower()}",
            sync_permissions=False
        )

        # 購入者の書き込みを停止
        member = interaction.guild.get_member(
            self.user_id
        )

        if member:

            await channel.set_permissions(
                member,
                view_channel=True,
                send_messages=False,
                read_message_history=True
            )

    @discord.ui.button(
        label="チャット削除",
        style=discord.ButtonStyle.red,
        emoji="🗑️"
    )
    async def delete(
        self,
        interaction,
        button
    ):

        if (
            interaction.user.id != self.user_id
            and not is_admin(interaction)
        ):

            await interaction.response.send_message(
                "❌ このチャットを削除できません。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🗑️ チャットを削除します。",
            ephemeral=True
        )

        await interaction.channel.delete(
            reason="購入者による注文チャット削除"
        )


# =========================================================
# パネル更新
# =========================================================

async def update_vending_panel():

    channel_id = CONFIG.get(
        "purchase_channel_id"
    )

    message_id = CONFIG.get(
        "panel_message_id"
    )

    if not channel_id or not message_id:
        return

    try:

        channel = bot.get_channel(
            int(channel_id)
        )

        if channel is None:

            channel = await bot.fetch_channel(
                int(channel_id)
            )

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_panel_embed(),
            view=VendingView()
        )

    except Exception as e:

        print(
            f"パネル更新エラー: {e}"
        )


# =========================================================
# 商品追加
# =========================================================

class AddProductModal(
    discord.ui.Modal
):

    def __init__(self):

        super().__init__(
            title="商品を追加"
        )

        self.name_input = discord.ui.TextInput(
            label="商品名",
            placeholder="例：りんごジュース",
            required=True,
            max_length=40
        )

        self.price_input = discord.ui.TextInput(
            label="価格",
            placeholder="例：150",
            required=True
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫",
            placeholder="例：10",
            required=True
        )

        self.emoji_input = discord.ui.TextInput(
            label="商品絵文字",
            placeholder="例：🍎",
            required=True,
            max_length=10
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
                "❌ 入力値を確認してください。",
                ephemeral=True
            )

            return

        PRODUCTS[name] = {
            "price": price,
            "stock": stock,
            "emoji": self.emoji_input.value.strip()
        }

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✅ **{name}** を追加しました！",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 商品選択
# =========================================================

class ProductSelect(
    discord.ui.Select
):

    def __init__(
        self,
        mode
    ):

        self.mode = mode

        options = []

        for name, data in list(
            PRODUCTS.items()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name,
                    description=(
                        f"{data['price']}円 / "
                        f"在庫 {data['stock']}"
                    )[:100],
                    emoji=data.get(
                        "emoji",
                        "🛒"
                    ),
                    value=name
                )
            )

        super().__init__(
            placeholder="商品を選択してください",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        name = self.values[0]

        if self.mode == "delete":

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

        elif self.mode == "stock":

            await interaction.response.send_modal(
                StockModal(name)
            )


class ProductSelectView(
    discord.ui.View
):

    def __init__(
        self,
        mode
    ):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                ProductSelect(mode)
            )


# =========================================================
# 在庫
# =========================================================

class StockModal(
    discord.ui.Modal
):

    def __init__(
        self,
        name
    ):

        super().__init__(
            title=f"{name}の在庫"
        )

        self.name = name

        self.stock_input = discord.ui.TextInput(
            label="新しい在庫数",
            default=str(
                PRODUCTS[name]["stock"]
            ),
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
            return

        PRODUCTS[
            self.name
        ]["stock"] = stock

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✅ 在庫を {stock}個 に変更しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 色変更
# =========================================================

COLOR_PRESETS = {
    "🔵 ブルー": 0x5865F2,
    "🟣 パープル": 0x9B59B6,
    "🟢 グリーン": 0x2ECC71,
    "🔴 レッド": 0xE74C3C,
    "🟠 オレンジ": 0xE67E22,
    "🩷 ピンク": 0xFF69B4,
    "🟡 ゴールド": 0xF1C40F,
    "⚫ ブラック": 0x2C2F33
}


class ColorView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=120
        )

        for index, (
            name,
            value
        ) in enumerate(
            COLOR_PRESETS.items()
        ):

            self.add_item(
                ColorButton(
                    name,
                    value
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
            return

        CONFIG[
            "panel_color"
        ] = self.color_value

        save_json(
            CONFIG_FILE,
            CONFIG
        )

        await interaction.response.send_message(
            "🎨 パネルカラーを変更しました！",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# パネル設定
# =========================================================

class PanelSettingsView(
    discord.ui.View
):

    @discord.ui.button(
        label="🎨 色を変更",
        style=discord.ButtonStyle.blurple
    )
    async def color(
        self,
        interaction,
        button
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_message(
            "好きな色を選択してください。",
            view=ColorView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="🔄 パネル更新",
        style=discord.ButtonStyle.green
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
# チャンネル選択
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
            placeholder="チャンネルを選択",
            channel_types=[
                discord.ChannelType.text
            ]
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(interaction):
            return

        selected = self.values[0]

        try:

            channel = await interaction.guild.fetch_channel(
                selected.id
            )

        except Exception:

            await interaction.response.send_message(
                "❌ チャンネルを取得できませんでした。",
                ephemeral=True
            )

            return

        if self.mode == "purchase":

            message = await channel.send(
                embed=create_panel_embed(),
                view=VendingView()
            )

            CONFIG[
                "purchase_channel_id"
            ] = channel.id

            CONFIG[
                "panel_message_id"
            ] = message.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            await interaction.response.send_message(
                f"✅ {channel.mention} に"
                f"自動販売機を設置しました！",
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
                f"✅ 注文通知を"
                f"{channel.mention} に設定しました。",
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
            ChannelSelect(mode)
        )


# =========================================================
# 管理画面
# =========================================================

class AdminView(
    discord.ui.View
):

    @discord.ui.button(
        label="🛒 自動販売機を設置",
        style=discord.ButtonStyle.green,
        row=0
    )
    async def install(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "販売チャンネルを選択してください。",
            view=ChannelSelectView(
                "purchase"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="📩 注文通知設定",
        style=discord.ButtonStyle.blurple,
        row=0
    )
    async def order_channel(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "注文通知チャンネルを選択してください。",
            view=ChannelSelectView(
                "order"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="➕ 商品追加",
        style=discord.ButtonStyle.green,
        row=1
    )
    async def add(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            AddProductModal()
        )

    @discord.ui.button(
        label="🗑️ 商品削除",
        style=discord.ButtonStyle.red,
        row=1
    )
    async def delete(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "削除する商品を選択してください。",
            view=ProductSelectView(
                "delete"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="📦 在庫変更",
        style=discord.ButtonStyle.gray,
        row=1
    )
    async def stock(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "在庫を変更する商品を選択してください。",
            view=ProductSelectView(
                "stock"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="🎨 パネル設定",
        style=discord.ButtonStyle.blurple,
        row=2
    )
    async def settings(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "パネル設定",
            view=PanelSettingsView(),
            ephemeral=True
        )


# =========================================================
# 起動
# =========================================================

@bot.event
async def on_ready():

    print(
        f"ログインしました: {bot.user}"
    )

    try:

        bot.add_view(
            VendingView()
        )

    except Exception as e:

        print(
            f"販売View登録エラー: {e}"
        )

    try:

        synced = await bot.tree.sync()

        print(
            f"スラッシュコマンドを "
            f"{len(synced)} 個同期しました"
        )

    except Exception as e:

        print(
            f"同期エラー: {e}"
        )


# =========================================================
# /ping
# =========================================================

@bot.tree.command(
    name="ping",
    description="Botが動いているか確認"
)
async def ping(
    interaction
):

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
            "❌ 管理者専用です。",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="👑 キラの自動販売機",
        description=(
            "管理者コントロールパネル\n\n"
            "商品の管理・販売パネル・注文通知を設定できます。"
        ),
        color=CONFIG.get(
            "panel_color",
            0x5865F2
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
