import os
import json
import asyncio
import re
import traceback
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ============================================================
# キラの自動販売機 - 完成版
# 変更方針:
# ・既存の自動販売機機能を維持
# ・管理者専用のメッセージ送信機能を追加
# ・商品画像をPCから直接アップロードできる管理者コマンドを追加
# ・購入者側の表示を整理・洗練
# ・注文処理ボタン後の未定義ビュー問題を修正
# ============================================================

BOT_NAME = "キラの自動販売機"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.path.join(BASE_DIR, "products.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ORDERS_FILE = os.path.join(BASE_DIR, "orders.json")

DEFAULT_CONFIG = {
    "guild_id": 0,
    "purchase_channel_id": 0,
    "order_channel_id": 0,
    "media_channel_id": 0,
    "archive_category_id": 0,
    "panel_message_id": 0,
    "panel_channel_id": 0,
    "order_counter": 1000,
    "media_library": [],
    "design": {
        "title": "🛒 キラの自動販売機",
        "subtitle": "欲しい商品を選んで、かんたん購入",
        "description": "下のボタンから商品を選択してください。\n在庫状況もリアルタイムで表示されます。",
        "notice": "💡 購入後は専用チャットが自動作成されます。",
        "footer": "KIRA VENDING • SAFE & SIMPLE",
        "color": 0x5865F2,
        "banner_url": "",
        "show_stock": True,
    },
}

DEFAULT_PRODUCTS = {
    "sample": {
        "id": "sample",
        "name": "サンプル商品",
        "description": "商品説明を入力してください。",
        "price": 100,
        "stock": 10,
        "active": True,
        "image_url": "",
        "emoji": "🛍️",
    }
}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        save_json(path, default)
        return json.loads(json.dumps(default, ensure_ascii=False))


config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
products = load_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
orders = load_json(ORDERS_FILE, {})

# 既存ファイルが古くても不足キーを補完
for key, value in DEFAULT_CONFIG.items():
    if key not in config:
        config[key] = json.loads(json.dumps(value, ensure_ascii=False))

if not isinstance(config.get("design"), dict):
    config["design"] = json.loads(json.dumps(DEFAULT_CONFIG["design"], ensure_ascii=False))
else:
    for key, value in DEFAULT_CONFIG["design"].items():
        config["design"].setdefault(key, value)

if not isinstance(config.get("media_library"), list):
    config["media_library"] = []

if not isinstance(products, dict):
    products = {}
if not isinstance(orders, dict):
    orders = {}

save_json(CONFIG_FILE, config)
save_json(PRODUCTS_FILE, products)
save_json(ORDERS_FILE, orders)

purchase_lock = asyncio.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    try:
        return f"¥{int(value):,}"
    except (TypeError, ValueError):
        return "¥0"


def is_admin(member):
    return bool(member and getattr(member, "guild_permissions", None) and member.guild_permissions.administrator)


def find_product(product_id):
    return products.get(str(product_id))


def next_order_id():
    try:
        number = int(config.get("order_counter", 1000))
    except (TypeError, ValueError):
        number = 1000
    config["order_counter"] = number + 1
    save_json(CONFIG_FILE, config)
    return f"KIRA-{number:06d}"


def channel_mention(channel_id):
    try:
        channel_id = int(channel_id)
        return f" <#{channel_id}>" if channel_id else " 未設定"
    except (TypeError, ValueError):
        return " 未設定"


def category_mention(category_id):
    try:
        category_id = int(category_id)
        return f" <#{category_id}>" if category_id else " 未設定"
    except (TypeError, ValueError):
        return " 未設定"


def safe_id(text, fallback="product"):
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    value = value[:50]
    if not value:
        value = fallback
    return value


def unique_product_id(base):
    base = safe_id(base, "product")
    candidate = base
    number = 2
    while candidate in products:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def normalize_product(product_id, data):
    if not isinstance(data, dict):
        data = {}
    data.setdefault("id", product_id)
    data.setdefault("name", "商品")
    data.setdefault("description", "")
    data.setdefault("price", 0)
    data.setdefault("stock", 0)
    data.setdefault("active", True)
    data.setdefault("image_url", "")
    data.setdefault("emoji", "🛍️")
    return data


for pid in list(products.keys()):
    products[pid] = normalize_product(pid, products[pid])
save_json(PRODUCTS_FILE, products)


# ============================================================
# Discord
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


# ============================================================
# 見た目
# ============================================================


def design_color():
    try:
        return discord.Color(int(config["design"].get("color", 0x5865F2)))
    except (TypeError, ValueError):
        return discord.Color.blurple()


def stock_text(product):
    stock = int(product.get("stock", 0))
    if stock <= 0:
        return "🔴 売り切れ"
    if stock <= 3:
        return f"🟠 残り {stock}個"
    return f"🟢 在庫 {stock}個"


def product_line(product):
    emoji = product.get("emoji") or "🛍️"
    name = str(product.get("name", "商品"))
    price = money(product.get("price", 0))
    if config["design"].get("show_stock", True):
        return f"{emoji} **{name}**　`{price}`　{stock_text(product)}"
    return f"{emoji} **{name}**　`{price}`"


def design_embed():
    d = config["design"]
    embed = discord.Embed(
        title=d.get("title", BOT_NAME),
        description=(
            f"**{d.get('subtitle', '')}**\n\n"
            f"{d.get('description', '')}"
        ),
        color=design_color(),
        timestamp=datetime.now(timezone.utc),
    )

    active = [normalize_product(pid, p) for pid, p in products.items() if p.get("active", True)]
    active = active[:25]
    if active:
        embed.add_field(
            name="🛍️ 商品ラインナップ",
            value="\n".join(product_line(p) for p in active),
            inline=False,
        )
    else:
        embed.add_field(
            name="🛍️ 商品ラインナップ",
            value="現在販売中の商品はありません。",
            inline=False,
        )

    notice = d.get("notice", "")
    if notice:
        embed.add_field(name="📌 ご案内", value=notice, inline=False)

    footer = d.get("footer", "")
    if footer:
        embed.set_footer(text=footer)

    banner = d.get("banner_url", "")
    if banner:
        embed.set_image(url=banner)

    return embed


def _safe_product_display(product):
    """購入画面へ渡す値をDiscordの文字列/URLとして安全な形にする。"""
    raw_name = product.get("name", "商品")
    raw_description = product.get("description", "説明はありません。")
    raw_emoji = product.get("emoji", "🛍️")
    raw_image = product.get("image_url", "")

    name = str(raw_name if raw_name is not None else "商品").strip() or "商品"
    description = str(raw_description if raw_description is not None else "説明はありません。").strip()
    emoji = str(raw_emoji if raw_emoji is not None else "🛍️").strip() or "🛍️"
    image_url = str(raw_image if raw_image is not None else "").strip()

    # DiscordのEmbed上限を超えないようにする。
    name = name[:240]
    description = description[:4096] or "説明はありません。"
    emoji = emoji[:32]

    # 画像URLはHTTP(S)だけを許可。壊れた値は画像なしで表示する。
    if not re.match(r"^https?://[^\s]+$", image_url, re.IGNORECASE):
        image_url = ""
    else:
        image_url = image_url[:2000]

    try:
        price = int(product.get("price", 0))
    except (TypeError, ValueError):
        price = 0

    try:
        stock = int(product.get("stock", 0))
    except (TypeError, ValueError):
        stock = 0

    return {
        "name": name,
        "description": description,
        "emoji": emoji,
        "image_url": image_url,
        "price": price,
        "stock": stock,
    }


def product_embed(product):
    safe = _safe_product_display(product)
    embed = discord.Embed(
        title=f"{safe['emoji']} {safe['name']}",
        description=safe["description"],
        color=design_color(),
    )
    embed.add_field(name="💰 価格", value=f"**{money(safe['price'])}**", inline=True)
    embed.add_field(
        name="📦 在庫",
        value=stock_text({"stock": safe["stock"]}),
        inline=True,
    )
    if safe["image_url"]:
        embed.set_thumbnail(url=safe["image_url"])
    embed.set_footer(text="購入内容をご確認のうえ「購入する」を押してください。")
    return embed


def order_embed(order):
    product = find_product(order.get("product_id", "")) or {}
    status_map = {
        "pending": "🟡 支払い確認待ち",
        "paid": "🟢 支払い確認済み",
        "cancelled": "🔴 キャンセル",
    }
    status = status_map.get(order.get("status"), order.get("status", "不明"))
    embed = discord.Embed(title=f"🧾 注文 {order.get('id', '-')}", color=design_color())
    embed.add_field(name="商品", value=f"{product.get('emoji', '🛍️')} {product.get('name', order.get('product_id', '-'))}", inline=False)
    embed.add_field(name="金額", value=money(order.get("price", product.get("price", 0))), inline=True)
    embed.add_field(name="購入者", value=f"<@{order.get('buyer_id')}>" if order.get("buyer_id") else "不明", inline=True)
    embed.add_field(name="状態", value=status, inline=True)
    embed.add_field(name="PayPay URL", value=order.get("paypay_url", "未入力"), inline=False)
    embed.add_field(name="注文日時", value=order.get("created_at", "-"), inline=False)
    return embed


# ============================================================
# チャンネル権限
# ============================================================

async def secure_private_channel(channel, guild, buyer=None):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }

    me = guild.me
    if me and not me.guild_permissions.administrator:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
        )

    if buyer:
        overwrites[buyer] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
        )

    try:
        await channel.edit(overwrites=overwrites)
    except discord.Forbidden:
        pass


async def get_or_create_category(guild, name, config_key):
    category_id = config.get(config_key, 0)
    if category_id:
        category = guild.get_channel(int(category_id))
        if isinstance(category, discord.CategoryChannel):
            return category

    category = discord.utils.get(guild.categories, name=name)
    if category is None:
        category = await guild.create_category(name=name, reason=f"{BOT_NAME} 自動作成")

    config[config_key] = category.id
    save_json(CONFIG_FILE, config)
    return category


async def get_or_create_order_channel(guild):
    channel_id = config.get("order_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel

    channel = discord.utils.get(guild.text_channels, name="注文通知")
    if channel is None:
        channel = await guild.create_text_channel("注文通知", reason=f"{BOT_NAME} 注文通知チャンネル")

    await secure_private_channel(channel, guild)
    config["order_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return channel


async def get_or_create_ticket_category(guild):
    return await get_or_create_category(guild, "💬 購入チャット", "ticket_category_id")


async def get_or_create_archive_category(guild):
    return await get_or_create_category(guild, "📁 購入履歴", "archive_category_id")


async def create_ticket(order, guild, buyer):
    category = await get_or_create_ticket_category(guild)
    channel_name = f"chat-kira-{order['id'].lower().replace('kira-', '')}"
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if channel is None:
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            reason=f"{BOT_NAME} 注文チャット作成",
        )

    await secure_private_channel(channel, guild, buyer)
    await channel.send(
        content=f"{buyer.mention} ご購入ありがとうございます！",
        embed=order_embed(order),
        view=TicketView(order["id"], buyer.id),
    )
    order["ticket_channel_id"] = channel.id
    save_json(ORDERS_FILE, orders)
    return channel


# ============================================================
# 購入UI
# ============================================================

class PurchaseView(discord.ui.View):
    # 購入パネルはこの永続Viewを直接登録してボタンを処理する。
    # DynamicItemとの二重登録を避け、購入ボタンのACK経路を一本化する。
    def __init__(self):
        super().__init__(timeout=None)
        active = [p for p in products.values() if p.get("active", True)]
        for product in active[:25]:
            self.add_item(ProductButton(product["id"]))


class ProductPersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:buy:(?P<pid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction: discord.Interaction):
        # 念のため残してある互換用ハンドラ。現在の購入パネルはPurchaseViewで処理する。
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            product_id = self.item.custom_id.split(":", 2)[-1]
            product = find_product(product_id)
            if not product or not product.get("active", True):
                await interaction.followup.send("❌ この商品は現在販売されていません。", ephemeral=True)
                return
            if int(product.get("stock", 0)) <= 0:
                await interaction.followup.send("❌ この商品は売り切れです。", ephemeral=True)
                return
            await interaction.followup.send(
                embed=product_embed(product),
                view=ProductDetailView(product_id),
                ephemeral=True,
            )
        except Exception:
            traceback.print_exc()
            await interaction.followup.send(
                "❌ 商品画面の表示中にエラーが発生しました。管理者に確認してください。",
                ephemeral=True,
            )


class OrderPaidPersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:paid:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction: discord.Interaction):
        order_id = self.item.custom_id.split(":", 2)[-1]
        await process_paid_order(interaction, order_id)


class OrderCancelPersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:cancel:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction: discord.Interaction):
        order_id = self.item.custom_id.split(":", 2)[-1]
        await process_cancel_order(interaction, order_id)


class TicketArchivePersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:archive:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction: discord.Interaction):
        order_id = self.item.custom_id.split(":", 2)[-1]
        order = orders.get(order_id, {})
        buyer_id = int(order.get("buyer_id", 0))
        if not (is_admin(interaction.user) or interaction.user.id == buyer_id):
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
            return
        category = await get_or_create_archive_category(interaction.guild)
        await interaction.channel.edit(category=category, reason=f"{BOT_NAME} 購入履歴へ移動")
        await interaction.response.send_message("📁 購入履歴へ移動しました。", ephemeral=True)


class TicketDeletePersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:delete_ticket:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction: discord.Interaction):
        order_id = self.item.custom_id.split(":", 2)[-1]
        order = orders.get(order_id, {})
        buyer_id = int(order.get("buyer_id", 0))
        if not (is_admin(interaction.user) or interaction.user.id == buyer_id):
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ チャットを削除します。", ephemeral=True)
        await asyncio.sleep(1)
        try:
            await interaction.channel.delete(reason=f"{BOT_NAME} チケット削除")
        except discord.HTTPException:
            pass


class ProductButton(discord.ui.Button):
    def __init__(self, product_id):
        product = find_product(product_id) or {}
        sold_out = int(product.get("stock", 0)) <= 0
        super().__init__(
            label=(str(product.get("name", "商品"))[:80]),
            emoji=product.get("emoji") or "🛍️",
            style=discord.ButtonStyle.secondary if not sold_out else discord.ButtonStyle.danger,
            custom_id=f"kira:buy:{product_id}",
            disabled=sold_out,
            row=None,
        )
        self.product_id = product_id

    async def callback(self, interaction: discord.Interaction):
        # 商品画面はまずACKし、その後に商品内容を表示する。
        # 商品データに壊れた値があっても購入画面自体が落ちないようにする。
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception:
            # すでにACK済みの場合はこの後のfollowupを試す。
            if not interaction.response.is_done():
                traceback.print_exc()
                return

        try:
            product = find_product(self.product_id)
            if not product or not product.get("active", True):
                await interaction.followup.send(
                    "❌ この商品は現在販売されていません。",
                    ephemeral=True,
                )
                return

            try:
                stock = int(product.get("stock", 0))
            except (TypeError, ValueError):
                stock = 0

            if stock <= 0:
                await interaction.followup.send(
                    "❌ この商品は売り切れです。",
                    ephemeral=True,
                )
                return

            view = ProductDetailView(self.product_id)

            try:
                # 通常は見た目の良いEmbed版を送る。
                embed = product_embed(product)
                await interaction.followup.send(
                    embed=embed,
                    view=view,
                    ephemeral=True,
                )
            except Exception:
                # Embed/画像データだけが原因なら、同じ購入ボタン付きの
                # プレーンテキスト画面へ安全にフォールバックする。
                traceback.print_exc()
                safe = _safe_product_display(product)
                await interaction.followup.send(
                    content=(
                        f"{safe['emoji']} **{safe['name']}**\n\n"
                        f"{safe['description']}\n\n"
                        f"💰 価格: **{money(safe['price'])}**\n"
                        f"📦 在庫: **{safe['stock']}個**\n\n"
                        "購入内容をご確認のうえ「購入する」を押してください。"
                    ),
                    view=view,
                    ephemeral=True,
                )

        except Exception:
            traceback.print_exc()
            try:
                await interaction.followup.send(
                    "❌ 商品画面の表示中にエラーが発生しました。管理者に確認してください。",
                    ephemeral=True,
                )
            except Exception:
                traceback.print_exc()


class ProductDetailView(discord.ui.View):
    def __init__(self, product_id):
        super().__init__(timeout=300)
        self.product_id = product_id

    @discord.ui.button(label="購入する", emoji="🛒", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        product = find_product(self.product_id)
        if not product or not product.get("active", True):
            await interaction.response.send_message("❌ この商品は現在販売されていません。", ephemeral=True)
            return
        if int(product.get("stock", 0)) <= 0:
            await interaction.response.send_message("❌ この商品は売り切れです。", ephemeral=True)
            return
        await interaction.response.send_modal(PayPayModal(self.product_id))

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="この購入画面を閉じました。", embed=None, view=None)


class PayPayModal(discord.ui.Modal, title="PayPayで購入"):
    paypay_url = discord.ui.TextInput(
        label="PayPay送金リンク",
        placeholder="https://...",
        required=True,
        max_length=500,
    )

    def __init__(self, product_id):
        super().__init__()
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction):
        # Modal送信直後にDiscordへ応答を確保する。
        await interaction.response.defer(ephemeral=True, thinking=True)

        url = str(self.paypay_url.value).strip()
        if not re.match(r"^https?://", url, re.IGNORECASE):
            await interaction.followup.send("❌ 有効なURLを入力してください。", ephemeral=True)
            return

        try:
            async with purchase_lock:
                product = find_product(self.product_id)
                if not product or not product.get("active", True):
                    await interaction.followup.send("❌ この商品は現在販売されていません。", ephemeral=True)
                    return

                stock = int(product.get("stock", 0))
                if stock <= 0:
                    await interaction.followup.send("❌ 申し訳ありません。在庫切れになりました。", ephemeral=True)
                    return

                product["stock"] = stock - 1
                order_id = next_order_id()
                order = {
                    "id": order_id,
                    "product_id": self.product_id,
                    "buyer_id": interaction.user.id,
                    "guild_id": interaction.guild_id,
                    "price": int(product.get("price", 0)),
                    "paypay_url": url,
                    "status": "pending",
                    "created_at": now_iso(),
                    "ticket_channel_id": 0,
                }
                orders[order_id] = order
                save_json(PRODUCTS_FILE, products)
                save_json(ORDERS_FILE, orders)

            await update_purchase_panel()

            try:
                await create_ticket(order, interaction.guild, interaction.user)
            except Exception:
                traceback.print_exc()

            try:
                order_channel = await get_or_create_order_channel(interaction.guild)
                await order_channel.send(embed=order_embed(order), view=OrderAdminView(order_id))
            except Exception:
                traceback.print_exc()

            try:
                await interaction.user.send(
                    f"🧾 **{order_id}** の注文を受け付けました。\n"
                    f"商品: **{product.get('name', '商品')}**\n"
                    f"金額: **{money(product.get('price', 0))}**\n"
                    f"状態: **支払い確認待ち**"
                )
            except Exception:
                traceback.print_exc()

            await interaction.followup.send(
                f"✅ **購入受付完了！**\n\n"
                f"🧾 注文番号: **{order_id}**\n"
                f"🛍️ 商品: **{product.get('name', '商品')}**\n"
                f"💴 金額: **{money(product.get('price', 0))}**\n\n"
                "📩 購入チャットを作成しました。\n"
                "管理者の支払い確認をお待ちください。",
                ephemeral=True,
            )

        except Exception:
            traceback.print_exc()
            await interaction.followup.send(
                "❌ 購入処理中にエラーが発生しました。管理者に確認してください。",
                ephemeral=True,
            )


class ProcessedOrderView(discord.ui.View):
    """処理済み注文に表示する、操作不能の状態表示。"""
    def __init__(self):
        super().__init__(timeout=None)
        button = discord.ui.Button(
            label="処理済み",
            emoji="🔒",
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        self.add_item(button)


async def process_paid_order(interaction: discord.Interaction, order_id):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return

    order = orders.get(order_id)
    if not order:
        await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
        return

    if order.get("status") == "paid":
        await interaction.response.send_message("❌ すでに支払い確認済みです。", ephemeral=True)
        return

    if order.get("status") == "cancelled":
        await interaction.response.send_message("❌ キャンセル済みの注文は支払い確認できません。", ephemeral=True)
        return

    # 注文状態の更新やチャンネル処理の前にACKする。
    await interaction.response.defer()

    order["status"] = "paid"
    order["paid_at"] = now_iso()
    save_json(ORDERS_FILE, orders)

    try:
        await interaction.edit_original_response(
            embed=order_embed(order),
            view=ProcessedOrderView(),
        )
    except (discord.NotFound, discord.HTTPException):
        pass

    try:
        buyer = (
            interaction.guild.get_member(int(order.get("buyer_id", 0)))
            or await interaction.guild.fetch_member(int(order.get("buyer_id", 0)))
        )
        await buyer.send(f"🟢 注文 **{order_id}** の支払い確認が完了しました。")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
        pass

    ticket_id = order.get("ticket_channel_id")
    if ticket_id:
        try:
            ticket = interaction.guild.get_channel(int(ticket_id))
            if ticket:
                await ticket.send("🟢 **支払い確認済み**になりました。")
        except (discord.HTTPException, ValueError):
            pass


class OrderPaidButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(label="支払い確認", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"kira:paid:{order_id}")
        self.order_id = order_id

    async def callback(self, interaction: discord.Interaction):
        await process_paid_order(interaction, self.order_id)


async def process_cancel_order(interaction, order_id):
    if not is_admin(interaction.user):
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    order = orders.get(order_id)
    if not order:
        await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
        return
    if order.get("status") == "cancelled":
        await interaction.response.send_message("❌ すでにキャンセルされています。", ephemeral=True)
        return
    if order.get("status") == "paid":
        await interaction.response.send_message("❌ 支払い確認済みの注文はこのボタンからキャンセルできません。", ephemeral=True)
        return
    # パネル更新などの非同期処理前にACKする。
    await interaction.response.defer()
    product = find_product(order.get("product_id"))
    if product:
        product["stock"] = int(product.get("stock", 0)) + 1
        save_json(PRODUCTS_FILE, products)
    order["status"] = "cancelled"
    order["cancelled_at"] = now_iso()
    save_json(ORDERS_FILE, orders)
    await update_purchase_panel()
    await interaction.edit_original_response(embed=order_embed(order), view=ProcessedOrderView())
    try:
        user = interaction.guild.get_member(int(order["buyer_id"])) or await interaction.guild.fetch_member(int(order["buyer_id"]))
        await user.send(f"🔴 注文 **{order_id}** はキャンセルされました。")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
        pass


class OrderCancelButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(label="キャンセル", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id=f"kira:cancel:{order_id}")
        self.order_id = order_id

    async def callback(self, interaction: discord.Interaction):
        await process_cancel_order(interaction, self.order_id)


class OrderAdminView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.add_item(OrderPaidButton(order_id))
        self.add_item(OrderCancelButton(order_id))


# ============================================================
# チケット
# ============================================================

class TicketArchiveButton(discord.ui.Button):
    def __init__(self, order_id, buyer_id):
        super().__init__(label="購入履歴へ", emoji="📁", style=discord.ButtonStyle.secondary, custom_id=f"kira:archive:{order_id}")
        self.order_id = order_id
        self.buyer_id = buyer_id

    async def callback(self, interaction: discord.Interaction):
        if not (is_admin(interaction.user) or interaction.user.id == self.buyer_id):
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
            return
        category = await get_or_create_archive_category(interaction.guild)
        await interaction.channel.edit(category=category, reason=f"{BOT_NAME} 購入履歴へ移動")
        await interaction.response.send_message("📁 購入履歴へ移動しました。", ephemeral=True)


class TicketDeleteButton(discord.ui.Button):
    def __init__(self, order_id, buyer_id):
        super().__init__(label="チャット削除", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id=f"kira:delete_ticket:{order_id}")
        self.order_id = order_id
        self.buyer_id = buyer_id

    async def callback(self, interaction: discord.Interaction):
        if not (is_admin(interaction.user) or interaction.user.id == self.buyer_id):
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ チャットを削除します。", ephemeral=True)
        await asyncio.sleep(1)
        try:
            await interaction.channel.delete(reason=f"{BOT_NAME} チケット削除")
        except discord.HTTPException:
            pass


class TicketView(discord.ui.View):
    def __init__(self, order_id, buyer_id):
        super().__init__(timeout=None)
        self.add_item(TicketArchiveButton(order_id, buyer_id))
        self.add_item(TicketDeleteButton(order_id, buyer_id))


# ============================================================
# 商品管理
# ============================================================

class ProductModal(discord.ui.Modal, title="商品を追加"):
    name = discord.ui.TextInput(label="商品名", placeholder="例：Amazonギフト券", max_length=80)
    price = discord.ui.TextInput(label="価格（数字のみ）", placeholder="1000", max_length=10)
    stock = discord.ui.TextInput(label="在庫数", placeholder="10", max_length=8)
    emoji = discord.ui.TextInput(label="絵文字", placeholder="🎁", required=False, max_length=20)
    description = discord.ui.TextInput(label="商品説明", placeholder="商品の説明を入力", required=False, style=discord.TextStyle.paragraph, max_length=1000)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        try:
            price = int(str(self.price.value).replace(",", "").strip())
            stock = int(str(self.stock.value).strip())
            if price < 0 or stock < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 価格と在庫数は0以上の数字で入力してください。", ephemeral=True)
            return

        pid = unique_product_id(self.name.value)
        products[pid] = {
            "id": pid,
            "name": str(self.name.value).strip(),
            "description": str(self.description.value).strip(),
            "price": price,
            "stock": stock,
            "active": True,
            "image_url": "",
            "emoji": str(self.emoji.value).strip() or "🛍️",
        }
        save_json(PRODUCTS_FILE, products)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send(
            f"✅ 商品を追加しました。\n**{products[pid]['name']}** / {money(price)} / 在庫 {stock}\n\n📷 商品画像を付けたい場合は、管理パネルの **「画像を設定」** または `/product_image` を使えます。",
            ephemeral=True,
        )


class ProductEditModal(discord.ui.Modal, title="商品を編集"):
    name = discord.ui.TextInput(label="商品名", max_length=80)
    price = discord.ui.TextInput(label="価格", max_length=10)
    description = discord.ui.TextInput(label="商品説明", required=False, style=discord.TextStyle.paragraph, max_length=1000)
    emoji = discord.ui.TextInput(label="絵文字", required=False, max_length=20)

    def __init__(self, product_id):
        super().__init__()
        self.product_id = product_id
        product = find_product(product_id) or {}
        self.name.default = str(product.get("name", ""))
        self.price.default = str(product.get("price", 0))
        self.description.default = str(product.get("description", ""))
        self.emoji.default = str(product.get("emoji", "🛍️"))

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        product = find_product(self.product_id)
        if not product:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return
        try:
            price = int(str(self.price.value).replace(",", "").strip())
            if price < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 価格は0以上の数字で入力してください。", ephemeral=True)
            return
        product["name"] = str(self.name.value).strip()
        product["price"] = price
        product["description"] = str(self.description.value).strip()
        product["emoji"] = str(self.emoji.value).strip() or "🛍️"
        save_json(PRODUCTS_FILE, products)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send("✅ 商品情報を更新しました。", ephemeral=True)


class StockModal(discord.ui.Modal, title="在庫を変更"):
    stock = discord.ui.TextInput(label="新しい在庫数", placeholder="10", max_length=8)

    def __init__(self, product_id):
        super().__init__()
        self.product_id = product_id
        product = find_product(product_id) or {}
        self.stock.default = str(product.get("stock", 0))

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        try:
            stock = int(str(self.stock.value).strip())
            if stock < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 0以上の数字を入力してください。", ephemeral=True)
            return
        product = find_product(self.product_id)
        if not product:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return
        product["stock"] = stock
        save_json(PRODUCTS_FILE, products)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send(f"✅ 在庫を **{stock}個** に変更しました。", ephemeral=True)


class ProductSelect(discord.ui.Select):
    def __init__(self, action):
        self.action = action
        options = []
        for p in list(products.values())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(p.get("name", "商品"))[:100],
                    value=str(p.get("id")),
                    emoji=p.get("emoji") or "🛍️",
                    description=f"{money(p.get('price', 0))} / 在庫 {p.get('stock', 0)}"[:100],
                )
            )
        if not options:
            options = [discord.SelectOption(label="商品なし", value="__none__", description="先に商品を追加してください。")]
        super().__init__(placeholder="商品を選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        pid = self.values[0]
        if pid == "__none__":
            await interaction.response.send_message("商品がありません。", ephemeral=True)
            return
        product = find_product(pid)
        if not product:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return

        if self.action == "edit":
            await interaction.response.send_modal(ProductEditModal(pid))
        elif self.action == "stock":
            await interaction.response.send_modal(StockModal(pid))
        elif self.action == "delete":
            del products[pid]
            save_json(PRODUCTS_FILE, products)
            await interaction.response.defer(ephemeral=True)
            await update_purchase_panel()
            await interaction.followup.send(f"🗑️ **{product.get('name')}** を削除しました。", ephemeral=True)
        elif self.action == "toggle":
            product["active"] = not bool(product.get("active", True))
            save_json(PRODUCTS_FILE, products)
            await interaction.response.defer(ephemeral=True)
            await update_purchase_panel()
            state = "販売中" if product["active"] else "非公開"
            await interaction.followup.send(f"✅ **{product.get('name')}** を **{state}** にしました。", ephemeral=True)


class ProductSelectView(discord.ui.View):
    def __init__(self, action):
        super().__init__(timeout=120)
        self.add_item(ProductSelect(action))


class ProductAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="商品を追加", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(ProductModal())

    @discord.ui.button(label="商品を編集", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("編集する商品を選択してください。", view=ProductSelectView("edit"), ephemeral=True)

    @discord.ui.button(label="在庫変更", emoji="📦", style=discord.ButtonStyle.primary, row=0)
    async def stock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("在庫を変更する商品を選択してください。", view=ProductSelectView("stock"), ephemeral=True)

    @discord.ui.button(label="販売ON/OFF", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("切り替える商品を選択してください。", view=ProductSelectView("toggle"), ephemeral=True)

    @discord.ui.button(label="商品削除", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("削除する商品を選択してください。", view=ProductSelectView("delete"), ephemeral=True)

    @discord.ui.button(label="画像を設定", emoji="🖼️", style=discord.ButtonStyle.primary, row=1)
    async def image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "📷 **画像を直接アップロードできます！**\n\n`/product_image` を入力 → 商品を選択 → **image欄にPCから画像を添付**してください。\n※Discordの仕様上、通常のModal（商品追加画面）にはファイル添付欄を表示できません。",
            ephemeral=True,
        )

    @discord.ui.button(label="プレビュー", emoji="👀", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        active = [p for p in products.values() if p.get("active", True)]
        if not active:
            await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
            return
        await interaction.response.send_message(embed=product_embed(active[0]), ephemeral=True)


# ============================================================
# デザイン管理
# ============================================================

class DesignTextModal(discord.ui.Modal, title="タイトル・説明を編集"):
    title_text = discord.ui.TextInput(label="タイトル", max_length=256)
    subtitle = discord.ui.TextInput(label="サブタイトル", max_length=256, required=False)
    description = discord.ui.TextInput(label="説明文", style=discord.TextStyle.paragraph, max_length=2000, required=False)
    notice = discord.ui.TextInput(label="お知らせ", style=discord.TextStyle.paragraph, max_length=1000, required=False)
    footer = discord.ui.TextInput(label="フッター", max_length=256, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        d = config["design"]
        d["title"] = str(self.title_text.value).strip() or BOT_NAME
        d["subtitle"] = str(self.subtitle.value).strip()
        d["description"] = str(self.description.value).strip()
        d["notice"] = str(self.notice.value).strip()
        d["footer"] = str(self.footer.value).strip()
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send("✅ 販売機の文章を更新しました。", ephemeral=True)


class ColorModal(discord.ui.Modal, title="色を変更"):
    color = discord.ui.TextInput(label="カラーコード", placeholder="#5865F2 または 5865F2", max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        raw = str(self.color.value).strip().lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
            await interaction.response.send_message("❌ 6桁のカラーコードを入力してください。", ephemeral=True)
            return
        config["design"]["color"] = int(raw, 16)
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send("✅ 色を変更しました。", ephemeral=True)


class BannerModal(discord.ui.Modal, title="バナーURLを変更"):
    url = discord.ui.TextInput(label="画像URL", placeholder="https://...", required=False, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        url = str(self.url.value).strip()
        if url and not re.match(r"^https?://", url, re.IGNORECASE):
            await interaction.response.send_message("❌ 有効なhttp/https URLを入力してください。", ephemeral=True)
            return
        config["design"]["banner_url"] = url
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send("✅ バナーを更新しました。", ephemeral=True)


class DesignPresetView(discord.ui.View):
    @discord.ui.button(label="デフォルト", emoji="🟣", style=discord.ButtonStyle.secondary)
    async def default(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, 0x5865F2, "🛒 キラの自動販売機")

    @discord.ui.button(label="パープル", emoji="💜", style=discord.ButtonStyle.primary)
    async def purple(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, 0x9B59B6, "💜 キラの自動販売機")

    @discord.ui.button(label="ブルー", emoji="💙", style=discord.ButtonStyle.primary)
    async def blue(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, 0x3498DB, "💙 キラの自動販売機")

    async def apply(self, interaction, color, title):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            config["design"]["color"] = color
            config["design"]["title"] = title
            save_json(CONFIG_FILE, config)
            await update_purchase_panel()
            await interaction.followup.send("✅ プリセットを適用しました。", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ デザインの更新中にエラーが発生しました。管理者に確認してください。", ephemeral=True)


class DesignView(discord.ui.View):
    @discord.ui.button(label="タイトル・説明", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        modal = DesignTextModal()
        d = config["design"]
        modal.title_text.default = d.get("title", BOT_NAME)
        modal.subtitle.default = d.get("subtitle", "")
        modal.description.default = d.get("description", "")
        modal.notice.default = d.get("notice", "")
        modal.footer.default = d.get("footer", "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="色", emoji="🎨", style=discord.ButtonStyle.primary, row=0)
    async def color(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(ColorModal())

    @discord.ui.button(label="バナー", emoji="🖼️", style=discord.ButtonStyle.primary, row=0)
    async def banner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(BannerModal())

    @discord.ui.button(label="プリセット", emoji="✨", style=discord.ButtonStyle.secondary, row=1)
    async def presets(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("デザインを選択してください。", view=DesignPresetView(), ephemeral=True)

    @discord.ui.button(label="プレビュー", emoji="👀", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=design_embed(), view=PurchaseView(), ephemeral=True)


# ============================================================
# チャンネル設定
# ============================================================

class ChannelIdModal(discord.ui.Modal, title="チャンネルを設定"):
    purchase = discord.ui.TextInput(label="購入チャンネルID", placeholder="123456789...", required=False)
    order = discord.ui.TextInput(label="注文通知チャンネルID", placeholder="123456789...", required=False)
    media = discord.ui.TextInput(label="メディアチャンネルID", placeholder="123456789...", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        for field, key in ((self.purchase, "purchase_channel_id"), (self.order, "order_channel_id"), (self.media, "media_channel_id")):
            value = str(field.value).strip()
            if value:
                if not value.isdigit():
                    await interaction.response.send_message(f"❌ {key} は数字のチャンネルIDで指定してください。", ephemeral=True)
                    return
                config[key] = int(value)
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message("✅ チャンネル設定を更新しました。", ephemeral=True)


class ChannelSettingsView(discord.ui.View):
    @discord.ui.button(label="チャンネルIDを設定", emoji="⚙️", style=discord.ButtonStyle.primary)
    async def ids(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        modal = ChannelIdModal()
        modal.purchase.default = str(config.get("purchase_channel_id", "") or "")
        modal.order.default = str(config.get("order_channel_id", "") or "")
        modal.media.default = str(config.get("media_channel_id", "") or "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="購入チャンネルを自動作成", emoji="🛒", style=discord.ButtonStyle.success)
    async def create_purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await find_purchase_channel(interaction.guild, create=True)
            await interaction.followup.send(f"✅ 購入チャンネル: {channel.mention}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 購入チャンネルの作成中にエラーが発生しました。", ephemeral=True)

    @discord.ui.button(label="注文通知を自動作成", emoji="🧾", style=discord.ButtonStyle.success)
    async def create_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await get_or_create_order_channel(interaction.guild)
            await interaction.followup.send(f"✅ 注文通知: {channel.mention}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 注文通知チャンネルの作成中にエラーが発生しました。", ephemeral=True)

    @discord.ui.button(label="メディアを自動作成", emoji="🖼️", style=discord.ButtonStyle.success)
    async def create_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await get_or_create_media_channel(interaction.guild)
            await interaction.followup.send(f"✅ メディア: {channel.mention}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ メディアチャンネルの作成中にエラーが発生しました。", ephemeral=True)


# ============================================================
# メディア管理
# ============================================================

async def get_or_create_media_channel(guild):
    channel_id = config.get("media_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel
    channel = discord.utils.get(guild.text_channels, name="vending-media")
    if channel is None:
        channel = await guild.create_text_channel("vending-media", reason=f"{BOT_NAME} メディア保管")
    await secure_private_channel(channel, guild)
    config["media_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return channel


class MediaView(discord.ui.View):
    @discord.ui.button(label="メディアチャンネルを開く", emoji="🖼️", style=discord.ButtonStyle.primary)
    async def open_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await get_or_create_media_channel(interaction.guild)
            await interaction.followup.send(f"🖼️ {channel.mention}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ メディアチャンネルの処理中にエラーが発生しました。", ephemeral=True)

    @discord.ui.button(label="保存メディア一覧", emoji="📚", style=discord.ButtonStyle.secondary)
    async def saved_media(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        library = config.get("media_library", [])
        if not library:
            await interaction.response.send_message("保存されているメディアはありません。", ephemeral=True)
            return
        lines = []
        for item in library[-20:]:
            lines.append(f"• [{item.get('name', '画像')}]({item.get('url', '')})")
        await interaction.response.send_message("📚 **保存メディア**\n" + "\n".join(lines), ephemeral=True)

    @discord.ui.button(label="バナーURL設定", emoji="🎨", style=discord.ButtonStyle.secondary)
    async def banner(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(BannerModal())


# ============================================================
# 購入チャンネル
# ============================================================

async def find_purchase_channel(guild, create=False):
    channel_id = config.get("purchase_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel

    channel = discord.utils.get(guild.text_channels, name="購入")
    if channel:
        config["purchase_channel_id"] = channel.id
        save_json(CONFIG_FILE, config)
        return channel

    if create:
        channel = await guild.create_text_channel("購入", reason=f"{BOT_NAME} 購入チャンネル")
        config["purchase_channel_id"] = channel.id
        save_json(CONFIG_FILE, config)
        return channel
    return None


async def update_purchase_panel():
    channel_id = config.get("panel_channel_id", 0)
    message_id = config.get("panel_message_id", 0)
    if not channel_id or not message_id:
        return False
    channel = bot.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False
    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(embed=design_embed(), view=PurchaseView())
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def deploy_purchase_panel(guild):
    channel = await find_purchase_channel(guild, create=True)
    existing = None
    if config.get("panel_message_id") and config.get("panel_channel_id") == channel.id:
        try:
            existing = await channel.fetch_message(int(config["panel_message_id"]))
        except (discord.NotFound, discord.HTTPException):
            existing = None

    if existing:
        await existing.edit(embed=design_embed(), view=PurchaseView())
        message = existing
    else:
        message = await channel.send(embed=design_embed(), view=PurchaseView())

    config["panel_message_id"] = message.id
    config["panel_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return message


# ============================================================
# 管理者専用メッセージ送信
# ============================================================

class AdminMessageModal(discord.ui.Modal, title="管理者メッセージ送信"):
    content = discord.ui.TextInput(
        label="本文",
        placeholder="ボットに送信させたい文章を入力",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    title_text = discord.ui.TextInput(label="Embedタイトル（任意）", required=False, max_length=256)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = interaction.channel
            content = str(self.content.value).strip()
            title = str(self.title_text.value).strip()
            if title:
                embed = discord.Embed(title=title, description=content, color=design_color())
                embed.set_footer(text=config["design"].get("footer", BOT_NAME))
                await channel.send(embed=embed)
            else:
                await channel.send(content)
            await interaction.followup.send("✅ ボットとしてメッセージを送信しました。", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ メッセージ送信中にエラーが発生しました。", ephemeral=True)


# ============================================================
# 管理パネル
# ============================================================

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="販売機を設置・更新", emoji="🚀", style=discord.ButtonStyle.success, custom_id="kira:admin:deploy", row=0)
    async def deploy(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await deploy_purchase_panel(interaction.guild)
            await interaction.followup.send(f"✅ 販売機を更新しました。\n{message.jump_url}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 販売機の設置・更新中にエラーが発生しました。管理者に確認してください。", ephemeral=True)

    @discord.ui.button(label="商品管理", emoji="🛍️", style=discord.ButtonStyle.primary, custom_id="kira:admin:products", row=0)
    async def products(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🛍️ **商品管理**\n追加・編集・在庫変更・販売ON/OFF・削除・画像設定ができます。", view=ProductAdminView(), ephemeral=True)

    @discord.ui.button(label="デザイン", emoji="🎨", style=discord.ButtonStyle.primary, custom_id="kira:admin:design", row=0)
    async def design(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🎨 **販売機デザイン**", view=DesignView(), ephemeral=True)

    @discord.ui.button(label="チャンネル設定", emoji="⚙️", style=discord.ButtonStyle.secondary, custom_id="kira:admin:channels", row=1)
    async def channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("⚙️ **チャンネル設定**", view=ChannelSettingsView(), ephemeral=True)

    @discord.ui.button(label="メディア", emoji="🖼️", style=discord.ButtonStyle.secondary, custom_id="kira:admin:media", row=1)
    async def media(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🖼️ **メディア管理**", view=MediaView(), ephemeral=True)

    @discord.ui.button(label="メッセージ送信", emoji="📨", style=discord.ButtonStyle.primary, custom_id="kira:admin:message", row=1)
    async def message(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(AdminMessageModal())


# ============================================================
# Bot
# ============================================================

class KiraBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(PurchaseView())
        self.add_view(AdminPanelView())
        self.add_dynamic_items(
            OrderPaidPersistentButton,
            OrderCancelPersistentButton,
            TicketArchivePersistentButton,
            TicketDeletePersistentButton,
        )

        try:
            synced = await self.tree.sync()
            print(f"[INFO] Slash commands synced: {len(synced)}")
        except Exception:
            traceback.print_exc()


# 永続ビューとして登録するための汎用ハンドラ群
# 注文・チケットの個別IDは起動後にメッセージへ付いているため、
# 古いメッセージを再起動後も操作できるよう on_interaction で補完する。

bot = KiraBot(command_prefix="!", intents=intents, help_command=None)


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin", description="管理者専用の自動販売機管理パネルを表示")
    async def admin(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        embed = discord.Embed(
            title="⚙️ キラの自動販売機 管理パネル",
            description=(
                "ここから販売機をまとめて管理できます。\n\n"
                "🛍️ 商品追加・編集・在庫・販売状態\n"
                "🖼️ 商品画像アップロード\n"
                "🎨 購入者側のデザイン\n"
                "📨 ボットによる管理者メッセージ送信\n"
                "🚀 販売機の設置・更新"
            ),
            color=design_color(),
        )
        await interaction.response.send_message(embed=embed, view=AdminPanelView(), ephemeral=True)

    @app_commands.command(name="setup_vending", description="購入チャンネルに販売機を設置・更新")
    async def setup_vending(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        message = await deploy_purchase_panel(interaction.guild)
        await interaction.followup.send(f"✅ 販売機を設置・更新しました。\n{message.jump_url}", ephemeral=True)

    @app_commands.command(name="send_message", description="管理者専用：ボットとして文章を送信")
    @app_commands.describe(message="送信する文章")
    async def send_message(self, interaction: discord.Interaction, message: str):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.channel.send(message)
            await interaction.followup.send("✅ 送信しました。", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ メッセージ送信中にエラーが発生しました。", ephemeral=True)

    @app_commands.command(name="product_add", description="管理者専用：商品を追加")
    @app_commands.describe(
        name="商品名",
        price="価格",
        stock="在庫数",
        description="商品説明",
        emoji="商品絵文字",
        image="商品画像ファイル（任意）",
    )
    async def product_add(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        stock: int,
        description: str = "",
        emoji: str = "🛍️",
        image: Optional[discord.Attachment] = None,
    ):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        if price < 0 or stock < 0:
            await interaction.response.send_message("❌ 価格と在庫数は0以上で指定してください。", ephemeral=True)
            return
        if image and not image.content_type:
            await interaction.response.send_message("❌ 画像ファイルを指定してください。", ephemeral=True)
            return
        if image and not str(image.content_type).startswith("image/"):
            await interaction.response.send_message("❌ 商品画像には画像ファイルを指定してください。", ephemeral=True)
            return

        pid = unique_product_id(name)
        image_url = image.url if image else ""
        products[pid] = {
            "id": pid,
            "name": name.strip()[:80],
            "description": description.strip()[:1000],
            "price": price,
            "stock": stock,
            "active": True,
            "image_url": image_url,
            "emoji": emoji.strip()[:20] or "🛍️",
        }
        save_json(PRODUCTS_FILE, products)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send(
            f"✅ 商品を追加しました！\n"
            f"**{products[pid]['name']}** / {money(price)} / 在庫 {stock}"
            + ("\n🖼️ 商品画像も設定しました。" if image_url else "\n📷 画像は `/product_image` から後から直接アップロードできます。"),
            ephemeral=True,
        )

    @app_commands.command(name="product_image", description="管理者専用：PCから商品画像を直接アップロードして設定")
    @app_commands.describe(product="商品ID", image="設定する画像ファイル")
    async def product_image(self, interaction: discord.Interaction, product: str, image: discord.Attachment):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        target = find_product(product)
        if not target:
            await interaction.response.send_message("❌ 指定された商品IDが見つかりません。商品IDは商品JSONまたは追加時のIDを確認してください。", ephemeral=True)
            return
        if not image.content_type or not str(image.content_type).startswith("image/"):
            await interaction.response.send_message("❌ 画像ファイルを指定してください。", ephemeral=True)
            return
        target["image_url"] = image.url
        save_json(PRODUCTS_FILE, products)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel()
        await interaction.followup.send(f"🖼️ **{target.get('name', product)}** の画像を設定しました。", ephemeral=True)

    @product_image.autocomplete("product")
    async def product_image_autocomplete(self, interaction: discord.Interaction, current: str):
        if not is_admin(interaction.user):
            return []
        current = current.lower().strip()
        results = []
        for pid, p in products.items():
            name = str(p.get("name", pid))
            if current in pid.lower() or current in name.lower():
                results.append(app_commands.Choice(name=f"{name} [{pid}]"[:100], value=pid))
            if len(results) >= 25:
                break
        return results


@bot.event
async def on_ready():
    print(f"[READY] {bot.user} / {BOT_NAME}")
    guild_id = config.get("guild_id", 0)
    if guild_id:
        guild = bot.get_guild(int(guild_id))
        if guild:
            try:
                await get_or_create_order_channel(guild)
            except Exception:
                traceback.print_exc()


@bot.event
async def on_guild_join(guild):
    if not config.get("guild_id"):
        config["guild_id"] = guild.id
        save_json(CONFIG_FILE, config)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    media_channel_id = config.get("media_channel_id", 0)
    if media_channel_id and message.channel.id == int(media_channel_id) and message.attachments and is_admin(message.author):
        library = config.setdefault("media_library", [])
        for attachment in message.attachments:
            if attachment.content_type and str(attachment.content_type).startswith("image/"):
                library.append({
                    "name": attachment.filename,
                    "url": attachment.url,
                    "uploaded_by": message.author.id,
                    "created_at": now_iso(),
                })
        config["media_library"] = library[-50:]
        save_json(CONFIG_FILE, config)

    await bot.process_commands(message)


@bot.event
async def on_error(event, *args, **kwargs):
    traceback.print_exc()


async def main():
    token = os.getenv("DORD_TOKEN")
    if not token:
        raise RuntimeError("DORD_TOKEN が環境変数に設定されていません。")
    await bot.add_cog(AdminCog(bot))
    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
