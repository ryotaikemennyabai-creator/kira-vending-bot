import os
import json
import discord
from discord.ext import commands

PRODUCT_FILE = "products.json"

DEFAULT_PRODUCTS = {
    "コーラ": 100,
    "お茶": 100,
    "水": 80
}


def load_products():
    if not os.path.exists(PRODUCT_FILE):
        save_products(DEFAULT_PRODUCTS)
        return DEFAULT_PRODUCTS.copy()

    try:
        with open(PRODUCT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_PRODUCTS.copy()


def save_products(products):
    with open(PRODUCT_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


PRODUCTS = load_products()

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# 購入画面
# =========================

class PurchaseModal(discord.ui.Modal):
    def __init__(self, product_name):
        super().__init__(title=f"{product_name}を購入")

        self.product_name = product_name

        self.url_input = discord.ui.TextInput(
            label="PayPay送金URL",
            placeholder="PayPayの送金URLを入力してください",
            required=True,
            max_length=500
        )

        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):

        price = PRODUCTS.get(self.product_name)

        if price is None:
            await interaction.response.send_message(
                "❌ この商品は現在販売されていません。",
                ephemeral=True
            )
            return

        paypay_url = self.url_input.value.strip()

        await interaction.response.send_message(
            f"✅ 注文を受け付けました！\n\n"
            f"商品：**{self.product_name}**\n"
            f"価格：**{price}円**\n\n"
            f"PayPay送金URL：\n{paypay_url}",
            ephemeral=True
        )

        print(
            f"注文者: {interaction.user} | "
            f"商品: {self.product_name} | "
            f"価格: {price}円 | "
            f"URL: {paypay_url}"
        )


class PurchaseButton(discord.ui.Button):
    def __init__(self, product_name, price):
        super().__init__(
            label=f"{product_name}を購入",
            style=discord.ButtonStyle.green
        )

        self.product_name = product_name

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            PurchaseModal(self.product_name)
        )


class VendingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for name, price in PRODUCTS.items():
            self.add_item(
                PurchaseButton(name, price)
            )


# =========================
# 管理者：商品追加
# =========================

class AddProductModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="商品を追加")

        self.name_input = discord.ui.TextInput(
            label="商品名",
            placeholder="例：りんごジュース",
            required=True,
            max_length=50
        )

        self.price_input = discord.ui.TextInput(
            label="価格（円）",
            placeholder="例：150",
            required=True,
            max_length=10
        )

        self.add_item(self.name_input)
        self.add_item(self.price_input)

    async def on_submit(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        name = self.name_input.value.strip()

        try:
            price = int(self.price_input.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ 価格は数字で入力してください。",
                ephemeral=True
            )
            return

        if price <= 0:
            await interaction.response.send_message(
                "❌ 価格は1円以上にしてください。",
                ephemeral=True
            )
            return

        PRODUCTS[name] = price
        save_products(PRODUCTS)

        await interaction.response.send_message(
            f"✅ 商品を追加しました！\n\n"
            f"商品：**{name}**\n"
            f"価格：**{price}円**",
            ephemeral=True
        )


# =========================
# 管理者：商品削除
# =========================

class DeleteProductSelect(discord.ui.Select):
    def __init__(self):

        options = [
            discord.SelectOption(
                label=name,
                description=f"{price}円",
                value=name
            )
            for name, price in PRODUCTS.items()
        ]

        super().__init__(
            placeholder="削除する商品を選択",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        name = self.values[0]

        if name in PRODUCTS:
            del PRODUCTS[name]
            save_products(PRODUCTS)

        await interaction.response.send_message(
            f"✅ **{name}** を削除しました。",
            ephemeral=True
        )


class DeleteProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

        if PRODUCTS:
            self.add_item(DeleteProductSelect())


# =========================
# 管理者画面
# =========================

class AdminView(discord.ui.View):

    @discord.ui.button(
        label="商品を追加",
        style=discord.ButtonStyle.green
    )
    async def add_product(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            AddProductModal()
        )

    @discord.ui.button(
        label="商品を削除",
        style=discord.ButtonStyle.red
    )
    async def delete_product(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ 管理者専用です。",
                ephemeral=True
            )
            return

        if not PRODUCTS:
            await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            "削除する商品を選択してください。",
            view=DeleteProductView(),
            ephemeral=True
        )


# =========================
# Bot起動
# =========================

@bot.event
async def on_ready():

    print(f"ログインしました: {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを {len(synced)} 個同期しました")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")


# =========================
# /ping
# =========================

@bot.tree.command(
    name="ping",
    description="Botが動いているか確認します"
)
async def ping(interaction: discord.Interaction):

    await interaction.response.send_message(
        "Pong!"
    )


# =========================
# /menu
# =========================

@bot.tree.command(
    name="menu",
    description="キラの自動販売機を表示します"
)
async def menu(interaction: discord.Interaction):

    text = "🥤 **キラの自動販売機**\n\n"

    if PRODUCTS:
        for name, price in PRODUCTS.items():
            text += f"・**{name}**　{price}円\n"
    else:
        text += "現在、商品がありません。\n"

    text += "\n👇 購入したい商品のボタンを押してください！"

    await interaction.response.send_message(
        text,
        view=VendingView()
    )


# =========================
# /admin
# =========================

@bot.tree.command(
    name="admin",
    description="管理者用の商品管理画面"
)
async def admin(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ このコマンドはサーバー管理者専用です。",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "👑 **キラの自動販売機 管理画面**\n\n"
        "商品の追加・削除ができます。",
        view=AdminView(),
        ephemeral=True
    )


# =========================
# Token
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN が設定されていません。"
    )

bot.run(TOKEN)
