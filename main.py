import os
import json
import uuid
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
        "stock": 10
    },
    "お茶": {
        "price": 100,
        "stock": 10
    },
    "水": {
        "price": 80,
        "stock": 10
    }
}

DEFAULT_CONFIG = {
    "purchase_channel_id": None,
    "order_channel_id": None,
    "panel_message_id": None,
    "panel_color": 0x5865F2,
    "panel_title": "🥤 キラの自動販売機",
    "panel_description": "購入したい商品を選択してください！"
}


# =========================================================
# データ読み込み・保存
# =========================================================

def load_json(filename, default):
    if not os.path.exists(filename):
        save_json(filename, default)
        return default.copy()

    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy()


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


PRODUCTS = load_json(PRODUCT_FILE, DEFAULT_PRODUCTS)
CONFIG = load_json(CONFIG_FILE, DEFAULT_CONFIG)
ORDERS = load_json(ORDER_FILE, [])


# =========================================================
# Bot
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# 管理者チェック
# =========================================================

def is_admin(interaction: discord.Interaction):
    return interaction.user.guild_permissions.administrator


# =========================================================
# Embed
# =========================================================

def create_panel_embed():

    color = CONFIG.get("panel_color", 0x5865F2)

    embed = discord.Embed(
        title=CONFIG.get(
            "panel_title",
            "🥤 キラの自動販売機"
        ),
        description=CONFIG.get(
            "panel_description",
            "購入したい商品を選択してください！"
        ),
        color=color
    )

    if PRODUCTS:

        text = ""

        for name, data in PRODUCTS.items():

            price = data.get("price", 0)
            stock = data.get("stock", 0)

            if stock == 0:
                status = "🔴 売り切れ"
            else:
                status = f"🟢 残り {stock}個"

            text += (
                f"**{name}**\n"
                f"💴 {price}円　{status}\n\n"
            )

        embed.add_field(
            name="📦 商品一覧",
            value=text,
            inline=False
        )

    else:

        embed.add_field(
            name="📦 商品一覧",
            value="現在商品がありません。",
            inline=False
        )

    embed.set_footer(
        text="キラの自動販売機"
    )

    return embed


# =========================================================
# 注文番号
# =========================================================

def create_order_id():

    order_id = f"KIRA-{len(ORDERS) + 1:05d}"

    # 念のため重複確認
    existing = {
        order.get("order_id")
        for order in ORDERS
    }

    while order_id in existing:
        number = len(ORDERS) + 1
        order_id = f"KIRA-{number:05d}"

    return order_id


# =========================================================
# 購入確認画面
# =========================================================

class ConfirmPurchaseView(discord.ui.View):

    def __init__(self, product_name):

        super().__init__(timeout=120)

        self.product_name = product_name

    @discord.ui.button(
        label="購入する",
        style=discord.ButtonStyle.green,
        emoji="🛒"
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        product = PRODUCTS.get(self.product_name)

        if not product:
            await interaction.response.send_message(
                "❌ この商品は存在しません。",
                ephemeral=True
            )
            return

        if product.get("stock", 0) <= 0:
            await interaction.response.send_message(
                "❌ この商品は売り切れです。",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            PurchaseModal(self.product_name)
        )

    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.gray,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await interaction.response.edit_message(
            content="購入をキャンセルしました。",
            embed=None,
            view=None
        )


# =========================================================
# PayPay URL入力
# =========================================================

class PurchaseModal(discord.ui.Modal):

    def __init__(self, product_name):

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

        self.add_item(self.url_input)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        product = PRODUCTS.get(self.product_name)

        if not product:
            await interaction.response.send_message(
                "❌ 商品が存在しません。",
                ephemeral=True
            )
            return

        price = product.get("price", 0)
        stock = product.get("stock", 0)

        if stock <= 0:
            await interaction.response.send_message(
                "❌ 売り切れになりました。",
                ephemeral=True
            )
            return

        paypay_url = self.url_input.value.strip()

        if not paypay_url.startswith("http"):
            await interaction.response.send_message(
                "❌ 有効なURLを入力してください。",
                ephemeral=True
            )
            return

        order_id = create_order_id()

        order = {
            "order_id": order_id,
            "user_id": interaction.user.id,
            "username": str(interaction.user),
            "product": self.product_name,
            "price": price,
            "paypay_url": paypay_url,
            "status": "支払い確認待ち",
            "created_at": datetime.now().isoformat()
        }

        ORDERS.append(order)
        save_json(ORDER_FILE, ORDERS)

        # 在庫を1減らす
        product["stock"] = stock - 1
        save_json(PRODUCT_FILE, PRODUCTS)

        # 購入者への表示
        await interaction.response.send_message(
            f"## ✅ 注文を受け付けました\n\n"
            f"**注文番号**\n"
            f"`{order_id}`\n\n"
            f"**商品**\n"
            f"{self.product_name}\n\n"
            f"**価格**\n"
            f"{price}円\n\n"
            f"現在の状態：**支払い確認待ち**\n\n"
            f"管理者が確認するまでお待ちください。",
            ephemeral=True
        )

        # 注文通知
        await send_order_notification(
            interaction.guild,
            order
        )

        # 販売パネル更新
        await update_vending_panel()


# =========================================================
# 注文通知
# =========================================================

async def send_order_notification(
    guild,
    order
):

    if not guild:
        return

    channel_id = CONFIG.get(
        "order_channel_id"
    )

    if not channel_id:
        return

    channel = guild.get_channel(
        int(channel_id)
    )

    if not channel:
        return

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
            f"<@{order['user_id']}>"
            f"\n`{order['username']}`"
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

    embed.set_footer(
        text="管理画面から注文を処理できます"
    )

    await channel.send(
        embed=embed,
        view=OrderAdminView(order["order_id"])
    )


# =========================================================
# 商品購入ボタン
# =========================================================

class ProductButton(discord.ui.Button):

    def __init__(
        self,
        product_name,
        price,
        stock
    ):

        if stock <= 0:
            label = f"{product_name}（売切）"
            style = discord.ButtonStyle.gray
        else:
            label = f"{product_name}｜{price}円"
            style = discord.ButtonStyle.green

        super().__init__(
            label=label[:80],
            style=style,
            custom_id=f"kira_buy_{product_name}",
            disabled=(stock <= 0)
        )

        self.product_name = product_name

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        product = PRODUCTS.get(
            self.product_name
        )

        if not product:
            await interaction.response.send_message(
                "❌ この商品は存在しません。",
                ephemeral=True
            )
            return

        if product.get("stock", 0) <= 0:
            await interaction.response.send_message(
                "❌ 売り切れです。",
                ephemeral=True
            )
            return

        price = product.get("price", 0)

        embed = discord.Embed(
            title="🛒 購入確認",
            description=(
                f"**商品**\n"
                f"{self.product_name}\n\n"
                f"**価格**\n"
                f"{price}円\n\n"
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

        for name, data in list(
            PRODUCTS.items()
        ):

            price = data.get(
                "price",
                0
            )

            stock = data.get(
                "stock",
                0
            )

            self.add_item(
                ProductButton(
                    name,
                    price,
                    stock
                )
            )


# =========================================================
# 販売パネル更新
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

        if not channel:
            return

        message = await channel.fetch_message(
            int(message_id)
        )

        await message.edit(
            embed=create_panel_embed(),
            view=VendingView()
        )

    except Exception as e:

        print(
            f"販売パネル更新エラー: {e}"
        )


# =========================================================
# 商品追加
# =========================================================

class AddProductModal(discord.ui.Modal):

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
            required=True,
            max_length=10
        )

        self.stock_input = discord.ui.TextInput(
            label="在庫数",
            placeholder="例：10",
            required=True,
            max_length=10
        )

        self.add_item(self.name_input)
        self.add_item(self.price_input)
        self.add_item(self.stock_input)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ 管理者専用です。",
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

        if price <= 0:

            await interaction.response.send_message(
                "❌ 価格は1円以上にしてください。",
                ephemeral=True
            )
            return

        if stock < 0:

            await interaction.response.send_message(
                "❌ 在庫は0以上にしてください。",
                ephemeral=True
            )
            return

        PRODUCTS[name] = {
            "price": price,
            "stock": stock
        }

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✅ **{name}** を追加しました。\n"
            f"価格：{price}円\n"
            f"在庫：{stock}個",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 商品選択
# =========================================================

class ProductSelect(discord.ui.Select):

    def __init__(self, mode):

        self.mode = mode

        options = []

        for name, data in list(
            PRODUCTS.items()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name,
                    description=(
                        f"{data.get('price', 0)}円 "
                        f"/ 在庫 {data.get('stock', 0)}"
                    )[:100],
                    value=name
                )
            )

        super().__init__(
            placeholder="商品を選択してください",
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
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

        elif self.mode == "edit":

            await interaction.response.send_modal(
                EditProductModal(name)
            )


class ProductSelectView(discord.ui.View):

    def __init__(self, mode):

        super().__init__(
            timeout=120
        )

        if PRODUCTS:
            self.add_item(
                ProductSelect(mode)
            )


# =========================================================
# 商品編集
# =========================================================

class EditProductModal(discord.ui.Modal):

    def __init__(self, name):

        super().__init__(
            title=f"{name}を編集"
        )

        self.name = name

        self.name_input = discord.ui.TextInput(
            label="商品名",
            default=name,
            required=True,
            max_length=40
        )

        self.price_input = discord.ui.TextInput(
            label="価格",
            default=str(
                PRODUCTS[name]["price"]
            ),
            required=True,
            max_length=10
        )

        self.add_item(self.name_input)
        self.add_item(self.price_input)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        new_name = self.name_input.value.strip()

        try:
            new_price = int(
                self.price_input.value
            )
        except ValueError:

            await interaction.response.send_message(
                "❌ 価格は数字で入力してください。",
                ephemeral=True
            )
            return

        stock = PRODUCTS[
            self.name
        ].get(
            "stock",
            0
        )

        del PRODUCTS[self.name]

        PRODUCTS[new_name] = {
            "price": new_price,
            "stock": stock
        }

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            "✅ 商品を更新しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 在庫変更
# =========================================================

class StockModal(discord.ui.Modal):

    def __init__(self, name):

        super().__init__(
            title=f"{name}の在庫変更"
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
        interaction: discord.Interaction
    ):

        try:
            stock = int(
                self.stock_input.value
            )
        except ValueError:

            await interaction.response.send_message(
                "❌ 数字で入力してください。",
                ephemeral=True
            )
            return

        if stock < 0:

            await interaction.response.send_message(
                "❌ 在庫は0以上です。",
                ephemeral=True
            )
            return

        PRODUCTS[
            self.name
        ]["stock"] = stock

        save_json(
            PRODUCT_FILE,
            PRODUCTS
        )

        await interaction.response.send_message(
            f"✅ **{self.name}** の在庫を "
            f"{stock}個に変更しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# パネル設定
# =========================================================

class PanelSettingsModal(discord.ui.Modal):

    def __init__(self):

        super().__init__(
            title="販売パネル設定"
        )

        self.title_input = discord.ui.TextInput(
            label="タイトル",
            default=CONFIG.get(
                "panel_title",
                "🥤 キラの自動販売機"
            ),
            required=True,
            max_length=100
        )

        self.description_input = discord.ui.TextInput(
            label="説明",
            default=CONFIG.get(
                "panel_description",
                "購入したい商品を選択してください！"
            ),
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=1000
        )

        self.color_input = discord.ui.TextInput(
            label="色（HEX）",
            default=f"#{CONFIG.get('panel_color', 0x5865F2):06X}",
            placeholder="#5865F2",
            required=True,
            max_length=7
        )

        self.add_item(
            self.title_input
        )

        self.add_item(
            self.description_input
        )

        self.add_item(
            self.color_input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        color_text = self.color_input.value.strip()

        try:

            color = int(
                color_text.lstrip("#"),
                16
            )

            if color < 0 or color > 0xFFFFFF:
                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                "❌ 色は `#5865F2` のようなHEX形式で入力してください。",
                ephemeral=True
            )
            return

        CONFIG["panel_title"] = (
            self.title_input.value
        )

        CONFIG["panel_description"] = (
            self.description_input.value
        )

        CONFIG["panel_color"] = color

        save_json(
            CONFIG_FILE,
            CONFIG
        )

        await interaction.response.send_message(
            "✅ 販売パネルの設定を変更しました。",
            ephemeral=True
        )

        await update_vending_panel()


# =========================================================
# 注文処理
# =========================================================

class OrderAdminView(discord.ui.View):

    def __init__(self, order_id):

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
        interaction: discord.Interaction,
        button: discord.ui.Button
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

        order["status"] = "支払い確認済み"

        save_json(
            ORDER_FILE,
            ORDERS
        )

        await interaction.response.send_message(
            f"✅ `{self.order_id}` を"
            f"支払い確認済みにしました。",
            ephemeral=True
        )

        await interaction.message.edit(
            view=OrderCompletedView()
        )

        try:

            user = await bot.fetch_user(
                order["user_id"]
            )

            await user.send(
                f"✅ 注文 `{self.order_id}` の"
                f"支払いが確認されました！\n\n"
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
        interaction: discord.Interaction,
        button: discord.ui.Button
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

        order["status"] = "キャンセル"

        # キャンセルなら在庫を戻す
        product = PRODUCTS.get(
            order["product"]
        )

        if product:
            product["stock"] = (
                product.get("stock", 0) + 1
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
            f"❌ `{self.order_id}` をキャンセルしました。",
            ephemeral=True
        )

        await interaction.message.edit(
            view=OrderCompletedView()
        )

        await update_vending_panel()


class OrderCompletedView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    @discord.ui.button(
        label="処理済み",
        style=discord.ButtonStyle.gray,
        disabled=True
    )
    async def done(
        self,
        interaction,
        button
    ):
        pass


def find_order(order_id):

    for order in ORDERS:

        if order.get(
            "order_id"
        ) == order_id:

            return order

    return None


# =========================================================
# 管理画面
# =========================================================

class AdminView(discord.ui.View):

    @discord.ui.button(
        label="🛒 自動販売機を設置",
        style=discord.ButtonStyle.green,
        row=0
    )
    async def install(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "販売パネルを設置するチャンネルを選択してください。",
            view=ChannelSelectView(
                "purchase"
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="📩 注文通知チャンネル",
        style=discord.ButtonStyle.blurple,
        row=0
    )
    async def set_order_channel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "注文通知を送るチャンネルを選択してください。",
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
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_modal(
            AddProductModal()
        )

    @discord.ui.button(
        label="✏️ 商品編集",
        style=discord.ButtonStyle.blurple,
        row=1
    )
    async def edit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
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
            "編集する商品を選択してください。",
            view=ProductSelectView("edit"),
            ephemeral=True
        )

    @discord.ui.button(
        label="🗑️ 商品削除",
        style=discord.ButtonStyle.red,
        row=1
    )
    async def delete(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
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
            "削除する商品を選択してください。",
            view=ProductSelectView("delete"),
            ephemeral=True
        )

    @discord.ui.button(
        label="📦 在庫変更",
        style=discord.ButtonStyle.gray,
        row=2
    )
    async def stock(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
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
            "在庫を変更する商品を選択してください。",
            view=ProductSelectView("stock"),
            ephemeral=True
        )

    @discord.ui.button(
        label="🎨 パネル設定",
        style=discord.ButtonStyle.blurple,
        row=2
    )
    async def settings(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            return

        await interaction.response.send_modal(
            PanelSettingsModal()
        )

    @discord.ui.button(
        label="🔄 パネル更新",
        style=discord.ButtonStyle.gray,
        row=2
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            return

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ 販売パネルを更新しました。",
            ephemeral=True
        )


# =========================================================
# チャンネル選択
# =========================================================

class ChannelSelect(discord.ui.ChannelSelect):

    def __init__(self, mode):

        self.mode = mode

        super().__init__(
            placeholder="チャンネルを選択してください",
            channel_types=[
                discord.ChannelType.text
            ]
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if not is_admin(interaction):
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        channel = self.values[0]

        if self.mode == "purchase":

            CONFIG[
                "purchase_channel_id"
            ] = channel.id

            save_json(
                CONFIG_FILE,
                CONFIG
            )

            # 新しいパネルを送信
            message = await channel.send(
                embed=create_panel_embed(),
                view=VendingView()
            )

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
                f"✅ 注文通知チャンネルを"
                f"{channel.mention} に設定しました。",
                ephemeral=True
            )


class ChannelSelectView(discord.ui.View):

    def __init__(self, mode):

        super().__init__(
            timeout=120
        )

        self.add_item(
            ChannelSelect(mode)
        )


# =========================================================
# 起動時
# =========================================================

@bot.event
async def on_ready():

    print(
        f"ログインしました: {bot.user}"
    )

    # 永続View
    bot.add_view(
        VendingView()
    )

    # 注文ボタン
    for order in ORDERS:

        if order.get("status") == "支払い確認待ち":

            bot.add_view(
                OrderAdminView(
                    order["order_id"]
                )
            )

    try:

        synced = await bot.tree.sync()

        print(
            f"スラッシュコマンドを "
            f"{len(synced)} 個同期しました"
        )

    except Exception as e:

        print(
            f"コマンド同期エラー: {e}"
        )


# =========================================================
# /ping
# =========================================================

@bot.tree.command(
    name="ping",
    description="Botが動いているか確認します"
)
async def ping(
    interaction: discord.Interaction
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
    interaction: discord.Interaction
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
            "ここから商品・在庫・販売パネルなどを管理できます。"
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
