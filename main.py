import asyncio
import json
import os
import re
from typing import Dict, List, Optional, Any

import discord
from discord import app_commands
from discord.ext import commands

# ==========================================
# ファイル設定 & 定数設定
# ==========================================
CONFIG_FILE = "config.json"
SHOP_FILE = "shop.json"

PAYPAY_URL_PATTERN = re.compile(r"^https://(paypay\.ne\.jp|paypay\.me)/(page/link/[A-Za-z0-9_]+|[A-Za-z0-9_]+)$")
data_lock = asyncio.Lock()


# ==========================================
# JSONヘルパー関数
# ==========================================
def load_json(filepath: str, default_data: Any) -> Any:
    if not os.path.exists(filepath):
        save_json(filepath, default_data)
        return default_data
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error] {filepath} 読み込み失敗: {e}")
        return default_data


def save_json(filepath: str, data: Any) -> None:
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[Error] {filepath} 保存失敗: {e}")


config_data = load_json(CONFIG_FILE, {
    "ticket_category_id": None,
    "manager_role_id": None,
    "log_channel_id": None
})

shop_data = load_json(SHOP_FILE, {
    "panel_message_id": None,
    "products": {},
    "tickets": {}
})


def is_manager(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    manager_role_id = config_data.get("manager_role_id")
    if manager_role_id:
        role = interaction.guild.get_role(int(manager_role_id))
        if role and role in interaction.user.roles:
            return True
    return False


# ==========================================
# Bot クラス定義
# ==========================================
class VendBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(ShopPanelView())
        self.add_dynamic_items(TicketPayButton)
        self.add_dynamic_items(AdminApproveButton)
        self.add_dynamic_items(AdminRejectButton)
        self.add_dynamic_items(CloseTicketButton)


bot = VendBot()


# ==========================================
# Modal UI Components
# ==========================================
class QuantityModal(discord.ui.Modal, title="🛒 購入個数入力"):
    quantity_input = discord.ui.TextInput(
        label="購入数量",
        placeholder="例: 1",
        default="1",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, product_id: str):
        super().__init__()
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            count = int(self.quantity_input.value)
            if count <= 0:
                raise ValueError()
        except ValueError:
            await interaction.followup.send("❌ 数量は1以上の数値を入力してください。", ephemeral=True)
            return

        async with data_lock:
            product = shop_data["products"].get(self.product_id)
            if not product:
                await interaction.followup.send("❌ 商品が見つかりません。", ephemeral=True)
                return

            stock_list = product.get("stock", [])
            if len(stock_list) < count:
                await interaction.followup.send(f"❌ 在庫不足です（在庫: {len(stock_list)}個）", ephemeral=True)
                return

            guild = interaction.guild
            category_id = config_data.get("ticket_category_id")
            category = guild.get_channel(int(category_id)) if category_id else None

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }

            ticket_channel = await guild.create_text_channel(
                name=f"cart-{interaction.user.name}",
                category=category,
                overwrites=overwrites
            )

            ticket_id = str(ticket_channel.id)
            shop_data["tickets"][ticket_id] = {
                "channel_id": ticket_channel.id,
                "user_id": interaction.user.id,
                "product_id": self.product_id,
                "count": count,
                "status": "WAITING_PAYMENT"
            }
            save_json(SHOP_FILE, shop_data)

        total_price = product["price"] * count
        embed = discord.Embed(
            title="🛍️ ご購入手続き",
            description=f"{interaction.user.mention} 様、ご購入申請ありがとうございます！",
            color=0x2b2d31
        )
        embed.add_field(name="商品名", value=product['name'], inline=False)
        embed.add_field(name="数量", value=f"{count} 個", inline=True)
        embed.add_field(name="合計金額", value=f"¥{total_price:,}", inline=True)

        view = discord.ui.View(timeout=None)
        view.add_item(TicketPayButton(ticket_id=ticket_id))
        view.add_item(CloseTicketButton(ticket_id=ticket_id))

        await ticket_channel.send(content=f"{interaction.user.mention}", embed=embed, view=view)
        await interaction.followup.send(f"✅ 専用チャットを作成しました: {ticket_channel.mention}", ephemeral=True)


class PayPaySubmitModal(discord.ui.Modal, title="💳 PayPay送金URL入力"):
    paypay_url_input = discord.ui.TextInput(
        label="PayPay送金リンク",
        placeholder="https://paypay.ne.jp/...",
        min_length=15,
        required=True
    )

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        paypay_url = self.paypay_url_input.value.strip()

        if not PAYPAY_URL_PATTERN.match(paypay_url):
            await interaction.followup.send("❌ PayPayの送金リンク形式が正しくありません。", ephemeral=True)
            return

        async with data_lock:
            ticket = shop_data["tickets"].get(self.ticket_id)
            if not ticket:
                await interaction.followup.send("❌ チケットが見つかりません。", ephemeral=True)
                return
            ticket["status"] = "PAYMENT_SUBMITTED"
            save_json(SHOP_FILE, shop_data)
            product = shop_data["products"].get(ticket["product_id"], {})

        total_price = product.get("price", 0) * ticket["count"]

        admin_embed = discord.Embed(title="🛡️ 支払い承認待ち", color=0x3498db)
        admin_embed.add_field(name="購入者", value=f"<@{ticket['user_id']}>", inline=True)
        admin_embed.add_field(name="商品", value=product.get("name", "不明"), inline=True)
        admin_embed.add_field(name="金額", value=f"¥{total_price:,}", inline=True)
        admin_embed.add_field(name="PayPay URL", value=paypay_url, inline=False)

        admin_view = discord.ui.View(timeout=None)
        admin_view.add_item(AdminApproveButton(ticket_id=self.ticket_id))
        admin_view.add_item(AdminRejectButton(ticket_id=self.ticket_id))

        await interaction.channel.send(embed=admin_embed, view=admin_view)
        await interaction.followup.send("✅ 送金リンクを提出しました。管理者の確認をお待ちください。", ephemeral=True)


# ==========================================
# Dynamic UI Components
# ==========================================
class TicketPayButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_pay:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(discord.ui.Button(label="💳 PayPayで送金する", style=discord.ButtonStyle.primary, custom_id=f"btn_pay:{ticket_id}"))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(PayPaySubmitModal(ticket_id=self.ticket_id))


class AdminApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_approve:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(discord.ui.Button(label="✅ 承認して納品", style=discord.ButtonStyle.success, custom_id=f"btn_approve:{ticket_id}"))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction):
            await interaction.response.send_message("❌ 管理者専用機能です。", ephemeral=True)
            return

        await interaction.response.defer()
        async with data_lock:
            ticket = shop_data["tickets"].get(self.ticket_id)
            if not ticket or ticket["status"] == "COMPLETED":
                await interaction.followup.send("❌ 処理済みのチケットです。", ephemeral=True)
                return

            product = shop_data["products"].get(ticket["product_id"])
            count = ticket["count"]
            if not product or len(product.get("stock", [])) < count:
                await interaction.followup.send("❌ 在庫不足です。", ephemeral=True)
                return

            delivered = product["stock"][:count]
            product["stock"] = product["stock"][count:]
            ticket["status"] = "COMPLETED"
            save_json(SHOP_FILE, shop_data)

        items_text = "\n".join(delivered)
        embed = discord.Embed(title="🎉 商品のお届け", description=f"```\n{items_text}\n```", color=0x2ecc71)
        await interaction.channel.send(content=f"<@{ticket['user_id']}>", embed=embed)
        await interaction.followup.send("✅ 納品完了しました。", ephemeral=True)


class AdminRejectButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_reject:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(discord.ui.Button(label="❌ 却下", style=discord.ButtonStyle.danger, custom_id=f"btn_reject:{ticket_id}"))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction):
            await interaction.response.send_message("❌ 管理者専用機能です。", ephemeral=True)
            return
        await interaction.response.send_message("❌ 却下しました。", ephemeral=True)


class CloseTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_close:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(discord.ui.Button(label="🔒 チャットを閉じる", style=discord.ButtonStyle.secondary, custom_id=f"btn_close:{ticket_id}"))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("5秒後にチャンネルを削除します...")
        await asyncio.sleep(5)
        await interaction.channel.delete()


# ==========================================
# パネル & コマンド
# ==========================================
class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = []
        products = shop_data.get("products", {})
        for p_id, p_data in products.items():
            stock_count = len(p_data.get("stock", []))
            options.append(discord.SelectOption(
                label=p_data['name'],
                value=p_id,
                description=f"価格: ¥{p_data['price']:,} | 在庫: {stock_count}個"
            ))
        if not options:
            options.append(discord.SelectOption(label="商品なし", value="none"))

        super().__init__(placeholder="商品を選択してください...", options=options, custom_id="shop_product_select")

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        await interaction.response.send_modal(QuantityModal(product_id=self.values[0]))


class ShopPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())


@bot.tree.command(name="set_panel", description="販売パネルを設置")
async def set_panel(interaction: discord.Interaction):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    embed = discord.Embed(title="🛒 自動販売機", description="メニューから商品を選択してください。", color=0x2b2d31)
    await interaction.channel.send(embed=embed, view=ShopPanelView())
    await interaction.response.send_message("✅ パネルを設置しました。", ephemeral=True)


@bot.tree.command(name="add_product", description="商品を追加")
async def add_product(interaction: discord.Interaction, product_id: str, name: str, price: int):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    shop_data["products"][product_id] = {"name": name, "price": price, "stock": []}
    save_json(SHOP_FILE, shop_data)
    await interaction.response.send_message(f"✅ 追加しました: {name}", ephemeral=True)


@bot.tree.command(name="add_stock", description="在庫を追加")
async def add_stock(interaction: discord.Interaction, product_id: str, stock_data: str):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    product = shop_data["products"].get(product_id)
    if not product:
        await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
        return
    items = [x.strip() for x in stock_data.split(",") if x.strip()]
    product["stock"].extend(items)
    save_json(SHOP_FILE, shop_data)
    await interaction.response.send_message(f"✅ 在庫を追加しました（現在 {len(product['stock'])}個）", ephemeral=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    await bot.tree.sync()


# ==========================================
# 起動処理
# ==========================================
if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

    if not TOKEN:
        TOKEN = input("Discord Bot Tokenを入力してください: ").strip()

    if not TOKEN:
        raise RuntimeError("Discord Bot Tokenが入力されていません。")

    bot.run(TOKEN)
