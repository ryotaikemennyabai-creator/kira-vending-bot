import os
import discord
from discord import app_commands
from discord.ext import commands

PRODUCTS = {
    "コーラ": 100,
    "お茶": 100,
    "水": 80,
}

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"スラッシュコマンドを {len(synced)} 個同期しました")
    except Exception as e:
        print(f"コマンド同期エラー: {e}")


@bot.tree.command(
    name="ping",
    description="Botが動いているか確認します"
)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.tree.command(
    name="menu",
    description="キラの自動販売機の商品一覧"
)
async def menu(interaction: discord.Interaction):

    text = "🥤 **キラの自動販売機**\n\n"

    for name, price in PRODUCTS.items():
        text += f"・{name}：{price}円\n"

    text += "\n購入する場合は `/buy` を使ってください。"

    await interaction.response.send_message(text)


class ProductSelect(discord.ui.Select):

    def __init__(self):

        options = []

        for name, price in PRODUCTS.items():
            options.append(
                discord.SelectOption(
                    label=name,
                    description=f"{price}円",
                    value=name
                )
            )

        super().__init__(
            placeholder="商品を選択してください",
            options=options
        )

    async def callback(self, interaction: discord.Interaction):

        product_name = self.values[0]
        price = PRODUCTS[product_name]

        await interaction.response.send_message(
            f"🥤 {product_name}：{price}円\n\n"
            "PayPay決済URLは現在準備中です。",
            ephemeral=True
        )


class BuyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ProductSelect())


@bot.tree.command(
    name="buy",
    description="商品を購入します"
)
async def buy(interaction: discord.Interaction):

    await interaction.response.send_message(
        "🥤 **キラの自動販売機**\n\n"
        "購入する商品を選択してください。",
        view=BuyView(),
        ephemeral=True
    )


TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN が設定されていません。"
    )

bot.run(TOKEN)
