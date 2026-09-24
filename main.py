import os
import json
import asyncio
import re
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

# ============================================================
# キラの自動販売機 - 複数自販機対応 完成版
# ============================================================
# 主な仕様
# ・複数の自販機を独立管理
# ・自販機ごとに商品 / 在庫 / デザイン / 購入チャンネル / パネルを分離
# ・既存の1台構成(products.json + config.json)を自動移行
# ・メディア機能は削除
# ・色はカラーコード入力ではなく選択式
# ・購入ボタンの色も選択式
# ・メッセージ送信は送信先チャンネルを毎回選択
# ・購入チャットの「購入履歴へ」「チャット削除」は管理者限定
# ・Discord Gateway再接続 + Keepalive
# ============================================================

BOT_NAME = "キラの自動販売機"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.path.join(BASE_DIR, "products.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ORDERS_FILE = os.path.join(BASE_DIR, "orders.json")

DEFAULT_DESIGN = {
    "title": "🛒 キラの自動販売機",
    "subtitle": "欲しい商品を選んで、かんたん購入",
    "description": "下の商品ボタンから商品を選択してください。",
    "notice": "💳 お支払いはPayPayに対応しています。",
    "footer": "KIRA VENDING • SAFE & SIMPLE",
    "color": 0x5865F2,
    "banner_url": "",
    "show_stock": True,
    "button_style": "primary",
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

DEFAULT_CONFIG = {
    "guild_id": 0,
    "order_channel_id": 0,
    "archive_category_id": 0,
    "order_counter": 1000,
    "machines": {},
}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        save_json(path, default)
        return deepcopy(default)


config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
legacy_products = load_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
orders = load_json(ORDERS_FILE, {})

if not isinstance(config, dict):
    config = deepcopy(DEFAULT_CONFIG)
if not isinstance(orders, dict):
    orders = {}

# ------------------------------------------------------------
# 既存の1台構成を複数自販機構成へ自動移行
# ------------------------------------------------------------


def normalize_product(product_id, data):
    if not isinstance(data, dict):
        data = {}
    data.setdefault("id", str(product_id))
    data.setdefault("name", "商品")
    data.setdefault("description", "")
    data.setdefault("price", 0)
    data.setdefault("stock", 0)
    data.setdefault("active", True)
    data.setdefault("image_url", "")
    data.setdefault("emoji", "🛍️")
    return data


def safe_id(text, fallback="item", limit=40):
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text)).strip("-")
    value = value[:limit]
    return value or fallback


def unique_machine_id(base):
    base = safe_id(base, "vending", limit=32)
    candidate = base
    number = 2
    while candidate in config["machines"]:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def default_machine(machine_id, name="キラの自動販売機"):
    design = deepcopy(DEFAULT_DESIGN)
    design["title"] = f"🛒 {name}"
    return {
        "id": machine_id,
        "name": name[:80] or "キラの自動販売機",
        "purchase_channel_id": 0,
        "panel_channel_id": 0,
        "panel_message_id": 0,
        "ticket_category_id": 0,
        "design": design,
        "products": {},
    }


if not isinstance(config.get("machines"), dict) or not config.get("machines"):
    legacy_design = config.get("design") if isinstance(config.get("design"), dict) else {}
    machine = default_machine("main", legacy_design.get("title", "キラの自動販売機"))

    # 元の販売機設定を移行
    machine["purchase_channel_id"] = int(config.get("purchase_channel_id", 0) or 0)
    machine["panel_channel_id"] = int(config.get("panel_channel_id", 0) or 0)
    machine["panel_message_id"] = int(config.get("panel_message_id", 0) or 0)
    machine["ticket_category_id"] = int(config.get("ticket_category_id", 0) or 0)

    for key in DEFAULT_DESIGN:
        if key in legacy_design:
            machine["design"][key] = legacy_design[key]

    if isinstance(legacy_products, dict):
        for pid, data in legacy_products.items():
            machine["products"][str(pid)] = normalize_product(pid, data)

    config["machines"] = {"main": machine}

# 不要になったメディア関連キーを削除
for old_key in (
    "media_channel_id",
    "media_library",
):
    config.pop(old_key, None)

# 旧トップレベル設定は自販機mainへ移したので整理
for old_key in (
    "purchase_channel_id",
    "panel_channel_id",
    "panel_message_id",
    "ticket_category_id",
    "design",
):
    config.pop(old_key, None)

for machine_id in list(config["machines"].keys()):
    machine = config["machines"][machine_id]
    if not isinstance(machine, dict):
        machine = default_machine(str(machine_id))
        config["machines"][machine_id] = machine

    machine.setdefault("id", str(machine_id))
    machine.setdefault("name", str(machine_id))
    machine.setdefault("purchase_channel_id", 0)
    machine.setdefault("panel_channel_id", 0)
    machine.setdefault("panel_message_id", 0)
    machine.setdefault("ticket_category_id", 0)

    design = machine.get("design")
    if not isinstance(design, dict):
        design = deepcopy(DEFAULT_DESIGN)
    for key, value in DEFAULT_DESIGN.items():
        design.setdefault(key, deepcopy(value))
    if not isinstance(design.get("button_style"), str):
        design["button_style"] = "primary"
    machine["design"] = design

    product_map = machine.get("products")
    if not isinstance(product_map, dict):
        product_map = {}
    for pid in list(product_map.keys()):
        product_map[pid] = normalize_product(pid, product_map[pid])
    machine["products"] = product_map

config.setdefault("guild_id", 0)
config.setdefault("order_channel_id", 0)
config.setdefault("archive_category_id", 0)
config.setdefault("order_counter", 1000)

# 旧注文へ自販機情報を補完
first_machine_id = next(iter(config["machines"]), "main")
for order_id, order in list(orders.items()):
    if not isinstance(order, dict):
        orders[order_id] = {}
        order = orders[order_id]
    order.setdefault("id", order_id)
    order.setdefault("vending_id", first_machine_id)
    machine = config["machines"].get(str(order.get("vending_id")))
    if not machine:
        order["vending_id"] = first_machine_id
        machine = config["machines"].get(first_machine_id, {})
    product = machine.get("products", {}).get(str(order.get("product_id", "")), {}) if machine else {}
    order.setdefault("product_name", product.get("name", order.get("product_id", "商品")))
    order.setdefault("product_emoji", product.get("emoji", "🛍️"))
    order.setdefault("vending_name", machine.get("name", first_machine_id) if machine else first_machine_id)

save_json(CONFIG_FILE, config)
save_json(ORDERS_FILE, orders)

purchase_lock = asyncio.Lock()


# ============================================================
# 共通ヘルパー
# ============================================================


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    try:
        return f"¥{int(value):,}"
    except (TypeError, ValueError):
        return "¥0"


def is_admin(member):
    return bool(
        member
        and getattr(member, "guild_permissions", None)
        and member.guild_permissions.administrator
    )


def get_machine(machine_id):
    return config.get("machines", {}).get(str(machine_id))


def machine_products(machine_id):
    machine = get_machine(machine_id)
    return machine.get("products", {}) if machine else {}


def find_product(machine_id, product_id):
    return machine_products(machine_id).get(str(product_id))


def unique_product_id(machine_id, base):
    products = machine_products(machine_id)
    base = safe_id(base, "product", limit=40)
    candidate = base
    number = 2
    while candidate in products:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def next_order_id():
    try:
        number = int(config.get("order_counter", 1000))
    except (TypeError, ValueError):
        number = 1000
    config["order_counter"] = number + 1
    save_json(CONFIG_FILE, config)
    return f"KIRA-{number:06d}"


def design_color(machine):
    try:
        return discord.Color(int(machine.get("design", {}).get("color", 0x5865F2)))
    except (TypeError, ValueError):
        return discord.Color.blurple()


def button_style(machine):
    mapping = {
        "primary": discord.ButtonStyle.primary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
        "secondary": discord.ButtonStyle.secondary,
    }
    return mapping.get(machine.get("design", {}).get("button_style"), discord.ButtonStyle.primary)


def stock_text(product):
    try:
        stock = int(product.get("stock", 0))
    except (TypeError, ValueError):
        stock = 0
    if stock <= 0:
        return "🔴 売り切れ"
    if stock <= 3:
        return f"🟠 残り {stock}個"
    return f"🟢 在庫 {stock}個"


def safe_product_display(product):
    raw_name = product.get("name", "商品")
    raw_description = product.get("description", "説明はありません。")
    raw_emoji = product.get("emoji", "🛍️")
    raw_image = product.get("image_url", "")

    name = str(raw_name if raw_name is not None else "商品").strip() or "商品"
    description = str(raw_description if raw_description is not None else "説明はありません。").strip() or "説明はありません。"
    emoji = str(raw_emoji if raw_emoji is not None else "🛍️").strip() or "🛍️"
    image_url = str(raw_image if raw_image is not None else "").strip()

    name = name[:240]
    description = description[:4096]
    emoji = emoji[:32]
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


def vending_embed(machine_id):
    machine = get_machine(machine_id)
    if not machine:
        return discord.Embed(title="自販機が見つかりません。", color=discord.Color.red())

    d = machine["design"]
    title = str(d.get("title", machine["name"]))[:256]
    subtitle = str(d.get("subtitle", ""))[:256]
    description = str(d.get("description", ""))[:3000]
    notice = str(d.get("notice", ""))[:1000]

    text = (
        "╭━━━━━━━━━━━━━━━━━━━━╮\n"
        f"┃ 🏪 **{machine['name']}**\n"
        "┃\n"
        f"┃ {subtitle}\n"
        "╰━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"{description}"
    )

    embed = discord.Embed(
        title=title,
        description=text,
        color=design_color(machine),
        timestamp=datetime.now(timezone.utc),
    )

    products = [
        normalize_product(pid, p)
        for pid, p in machine.get("products", {}).items()
        if p.get("active", True)
    ]
    products = products[:25]

    if products:
        lines = []
        for index, product in enumerate(products, 1):
            safe = safe_product_display(product)
            status = stock_text(product) if d.get("show_stock", True) else "販売中"
            lines.append(
                f"**{index:02d}.** {safe['emoji']} **{safe['name']}**  `¥{safe['price']:,}`  {status}"
            )
        rack = "\n".join(lines)
    else:
        rack = "現在販売中の商品はありません。"

    embed.add_field(
        name="🧃 商品ラック",
        value=rack[:1024],
        inline=False,
    )
    embed.add_field(
        name="💳 お支払い",
        value="PayPay送金リンクを入力して購入します。",
        inline=True,
    )
    embed.add_field(
        name="👇 操作方法",
        value="下の**商品ボタン**から購入する商品を選択してください。",
        inline=True,
    )

    if notice:
        embed.add_field(name="📌 ご案内", value=notice, inline=False)

    footer = str(d.get("footer", ""))[:2048]
    if footer:
        embed.set_footer(text=footer)

    banner = str(d.get("banner_url", "")).strip()
    if re.match(r"^https?://[^\s]+$", banner, re.IGNORECASE):
        embed.set_image(url=banner[:2000])

    return embed


def product_embed(machine_id, product):
    machine = get_machine(machine_id)
    safe = safe_product_display(product)
    embed = discord.Embed(
        title=f"{safe['emoji']} {safe['name']}",
        description=safe["description"],
        color=design_color(machine or default_machine("tmp")),
    )
    embed.add_field(name="💰 価格", value=f"**{money(safe['price'])}**", inline=True)
    embed.add_field(name="📦 在庫", value=stock_text({"stock": safe["stock"]}), inline=True)
    if safe["image_url"]:
        embed.set_thumbnail(url=safe["image_url"])
    embed.set_footer(text="購入内容をご確認のうえ「購入する」を押してください。")
    return embed


def order_embed(order):
    machine = get_machine(order.get("vending_id", ""))
    if machine:
        product = find_product(order.get("vending_id"), order.get("product_id", "")) or {}
        color = design_color(machine)
        machine_name = machine.get("name", order.get("vending_name", "自販機"))
    else:
        product = {}
        color = discord.Color.blurple()
        machine_name = order.get("vending_name", "自販機")

    product_name = product.get("name", order.get("product_name", order.get("product_id", "-")))
    product_emoji = product.get("emoji", order.get("product_emoji", "🛍️"))

    status_map = {
        "pending": "🟡 支払い確認待ち",
        "paid": "🟢 支払い確認済み",
        "cancelled": "🔴 キャンセル",
    }
    status = status_map.get(order.get("status"), order.get("status", "不明"))

    embed = discord.Embed(
        title=f"🧾 注文 {order.get('id', '-')}",
        color=color,
    )
    embed.add_field(name="🏪 自販機", value=str(machine_name)[:1024], inline=False)
    embed.add_field(name="商品", value=f"{product_emoji} {product_name}", inline=False)
    embed.add_field(name="金額", value=money(order.get("price", product.get("price", 0))), inline=True)
    embed.add_field(name="購入者", value=f"<@{order.get('buyer_id')}>" if order.get("buyer_id") else "不明", inline=True)
    embed.add_field(name="状態", value=status, inline=True)
    embed.add_field(name="PayPay URL", value=str(order.get("paypay_url", "未入力"))[:1024], inline=False)
    embed.add_field(name="注文日時", value=str(order.get("created_at", "-"))[:1024], inline=False)
    return embed


# ============================================================
# チャンネル / 権限
# ============================================================

async def secure_private_channel(channel, guild, buyer=None):
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }

    me = guild.me
    if me:
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


async def get_or_create_order_channel(guild):
    channel_id = config.get("order_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel

    channel = discord.utils.get(guild.text_channels, name="注文通知")
    if channel is None:
        channel = await guild.create_text_channel("注文通知", reason=f"{BOT_NAME} 注文通知")
    await secure_private_channel(channel, guild)
    config["order_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return channel


async def get_or_create_archive_category(guild):
    category_id = config.get("archive_category_id", 0)
    if category_id:
        category = guild.get_channel(int(category_id))
        if isinstance(category, discord.CategoryChannel):
            return category
    category = discord.utils.get(guild.categories, name="📁 購入履歴")
    if category is None:
        category = await guild.create_category("📁 購入履歴", reason=f"{BOT_NAME} 購入履歴")
    config["archive_category_id"] = category.id
    save_json(CONFIG_FILE, config)
    return category


async def get_or_create_ticket_category(machine_id, guild):
    machine = get_machine(machine_id)
    if not machine:
        raise RuntimeError("自販機が見つかりません。")

    category_id = machine.get("ticket_category_id", 0)
    if category_id:
        category = guild.get_channel(int(category_id))
        if isinstance(category, discord.CategoryChannel):
            return category

    base = safe_id(machine.get("name", machine_id), "vending", limit=30)
    category_name = f"💬 {base[:70]} 購入チャット"
    category = discord.utils.get(guild.categories, name=category_name)
    if category is None:
        category = await guild.create_category(category_name, reason=f"{BOT_NAME} 購入チャット")

    machine["ticket_category_id"] = category.id
    save_json(CONFIG_FILE, config)
    return category


async def find_purchase_channel(machine_id, guild, create=False):
    machine = get_machine(machine_id)
    if not machine:
        return None

    channel_id = machine.get("purchase_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            return channel

    wanted_name = f"購入-{safe_id(machine.get('name', machine_id), 'vending', limit=70)}"
    channel = discord.utils.get(guild.text_channels, name=wanted_name)
    if channel:
        machine["purchase_channel_id"] = channel.id
        save_json(CONFIG_FILE, config)
        return channel

    if create:
        channel = await guild.create_text_channel(wanted_name, reason=f"{BOT_NAME} 購入チャンネル")
        machine["purchase_channel_id"] = channel.id
        save_json(CONFIG_FILE, config)
        return channel
    return None


async def create_ticket(order, guild, buyer):
    machine_id = order.get("vending_id")
    category = await get_or_create_ticket_category(machine_id, guild)
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
    def __init__(self, machine_id):
        super().__init__(timeout=None)
        machine = get_machine(machine_id) or {}
        active = [
            p for p in machine.get("products", {}).values()
            if p.get("active", True)
        ]
        for product in active[:25]:
            self.add_item(ProductButton(machine_id, product["id"]))


async def show_product_screen(interaction, machine_id, product_id):
    machine = get_machine(machine_id)
    if not machine:
        await interaction.followup.send("❌ この自販機は存在しません。", ephemeral=True)
        return

    product = find_product(machine_id, product_id)
    if not product or not product.get("active", True):
        await interaction.followup.send("❌ この商品は現在販売されていません。", ephemeral=True)
        return

    try:
        stock = int(product.get("stock", 0))
    except (TypeError, ValueError):
        stock = 0
    if stock <= 0:
        await interaction.followup.send("❌ この商品は売り切れです。", ephemeral=True)
        return

    view = ProductDetailView(machine_id, product_id)
    safe = safe_product_display(product)
    try:
        await interaction.followup.send(
            embed=product_embed(machine_id, product),
            view=view,
            ephemeral=True,
        )
    except Exception:
        traceback.print_exc()
        try:
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
            await interaction.followup.send("❌ 商品画面を表示できませんでした。", ephemeral=True)


class ProductButton(discord.ui.Button):
    def __init__(self, machine_id, product_id):
        product = find_product(machine_id, product_id) or {}
        machine = get_machine(machine_id) or default_machine("tmp")
        sold_out = False
        try:
            sold_out = int(product.get("stock", 0)) <= 0
        except (TypeError, ValueError):
            sold_out = True

        # 商品ボタン自体には商品絵文字を設定しない。
        # 任意文字列の絵文字がDiscord側でInvalid emojiになる事故を防止する。
        super().__init__(
            label=str(product.get("name", "商品"))[:80],
            style=button_style(machine),
            custom_id=f"kira:buy:{machine_id}:{product_id}",
            disabled=sold_out,
        )
        self.machine_id = machine_id
        self.product_id = product_id

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await show_product_screen(interaction, self.machine_id, self.product_id)
        except Exception:
            traceback.print_exc()
            try:
                await interaction.followup.send("❌ 商品画面を表示できませんでした。", ephemeral=True)
            except Exception:
                traceback.print_exc()


class ProductDetailView(discord.ui.View):
    def __init__(self, machine_id, product_id):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        self.product_id = product_id

    @discord.ui.button(label="購入する", emoji="🛒", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        product = find_product(self.machine_id, self.product_id)
        if not product or not product.get("active", True):
            await interaction.response.send_message("❌ この商品は現在販売されていません。", ephemeral=True)
            return
        try:
            stock = int(product.get("stock", 0))
        except (TypeError, ValueError):
            stock = 0
        if stock <= 0:
            await interaction.response.send_message("❌ この商品は売り切れです。", ephemeral=True)
            return
        await interaction.response.send_modal(PayPayModal(self.machine_id, self.product_id))

    @discord.ui.button(label="閉じる", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ この操作は管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content="この購入画面を閉じました。", embed=None, view=None)


class PayPayModal(discord.ui.Modal, title="PayPayで購入"):
    paypay_url = discord.ui.TextInput(
        label="PayPay送金リンク",
        placeholder="https://...",
        required=True,
        max_length=500,
    )

    def __init__(self, machine_id, product_id):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        url = str(self.paypay_url.value).strip()
        if not re.match(r"^https?://", url, re.IGNORECASE):
            await interaction.followup.send("❌ 有効なURLを入力してください。", ephemeral=True)
            return

        try:
            async with purchase_lock:
                machine = get_machine(self.machine_id)
                if not machine:
                    await interaction.followup.send("❌ この自販機は存在しません。", ephemeral=True)
                    return

                product = find_product(self.machine_id, self.product_id)
                if not product or not product.get("active", True):
                    await interaction.followup.send("❌ この商品は現在販売されていません。", ephemeral=True)
                    return

                stock = int(product.get("stock", 0))
                if stock <= 0:
                    await interaction.followup.send("❌ 申し訳ありません。在庫切れになりました。", ephemeral=True)
                    return

                product["stock"] = stock - 1
                order_id = next_order_id()
                safe = safe_product_display(product)
                order = {
                    "id": order_id,
                    "vending_id": self.machine_id,
                    "vending_name": machine.get("name", self.machine_id),
                    "product_id": self.product_id,
                    "product_name": safe["name"],
                    "product_emoji": safe["emoji"],
                    "buyer_id": interaction.user.id,
                    "guild_id": interaction.guild_id,
                    "price": int(product.get("price", 0)),
                    "paypay_url": url,
                    "status": "pending",
                    "created_at": now_iso(),
                    "ticket_channel_id": 0,
                }
                orders[order_id] = order
                save_json(CONFIG_FILE, config)
                save_json(ORDERS_FILE, orders)

            await update_purchase_panel(self.machine_id)

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
                    f"🏪 自販機: **{machine.get('name', self.machine_id)}**\n"
                    f"商品: **{safe['name']}**\n"
                    f"金額: **{money(product.get('price', 0))}**\n"
                    f"状態: **支払い確認待ち**"
                )
            except Exception:
                pass

            await interaction.followup.send(
                f"✅ **購入受付完了！**\n\n"
                f"🏪 自販機: **{machine.get('name', self.machine_id)}**\n"
                f"🧾 注文番号: **{order_id}**\n"
                f"🛍️ 商品: **{safe['name']}**\n"
                f"💴 金額: **{money(product.get('price', 0))}**\n\n"
                "📩 購入チャットを作成しました。\n"
                "管理者の支払い確認をお待ちください。",
                ephemeral=True,
            )

        except Exception:
            traceback.print_exc()
            try:
                await interaction.followup.send("❌ 購入処理中にエラーが発生しました。管理者に確認してください。", ephemeral=True)
            except Exception:
                traceback.print_exc()


# ============================================================
# 注文 / チケット処理
# ============================================================

class ProcessedOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="処理済み",
                emoji="🔒",
                style=discord.ButtonStyle.secondary,
                disabled=True,
            )
        )


async def process_paid_order(interaction, order_id):
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

    await interaction.response.defer()
    order["status"] = "paid"
    order["paid_at"] = now_iso()
    save_json(ORDERS_FILE, orders)

    try:
        await interaction.edit_original_response(embed=order_embed(order), view=ProcessedOrderView())
    except (discord.NotFound, discord.HTTPException):
        pass

    try:
        buyer = interaction.guild.get_member(int(order.get("buyer_id", 0))) or await interaction.guild.fetch_member(int(order.get("buyer_id", 0)))
        await buyer.send(f"🟢 注文 **{order_id}** の支払い確認が完了しました。")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
        pass

    try:
        ticket_id = order.get("ticket_channel_id")
        if ticket_id:
            ticket = interaction.guild.get_channel(int(ticket_id))
            if ticket:
                await ticket.send("🟢 **支払い確認済み**になりました。")
    except (discord.HTTPException, ValueError):
        pass


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

    await interaction.response.defer()
    machine_id = str(order.get("vending_id", first_machine_id))
    product = find_product(machine_id, order.get("product_id", ""))
    if product:
        product["stock"] = int(product.get("stock", 0)) + 1
        save_json(CONFIG_FILE, config)

    order["status"] = "cancelled"
    order["cancelled_at"] = now_iso()
    save_json(ORDERS_FILE, orders)
    await update_purchase_panel(machine_id)

    try:
        await interaction.edit_original_response(embed=order_embed(order), view=ProcessedOrderView())
    except (discord.NotFound, discord.HTTPException):
        pass

    try:
        user = interaction.guild.get_member(int(order.get("buyer_id", 0))) or await interaction.guild.fetch_member(int(order.get("buyer_id", 0)))
        await user.send(f"🔴 注文 **{order_id}** はキャンセルされました。")
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
        pass


class OrderPaidButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(label="支払い確認", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"kira:paid:{order_id}")
        self.order_id = order_id

    async def callback(self, interaction):
        await process_paid_order(interaction, self.order_id)


class OrderCancelButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(label="キャンセル", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id=f"kira:cancel:{order_id}")
        self.order_id = order_id

    async def callback(self, interaction):
        await process_cancel_order(interaction, self.order_id)


class OrderAdminView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.add_item(OrderPaidButton(order_id))
        self.add_item(OrderCancelButton(order_id))


class OrderPaidPersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:paid:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction):
        await process_paid_order(interaction, self.item.custom_id.split(":", 2)[-1])


class OrderCancelPersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:cancel:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction):
        await process_cancel_order(interaction, self.item.custom_id.split(":", 2)[-1])


# ------------------------------------------------------------
# 購入チャットは管理者限定操作
# ------------------------------------------------------------

class TicketArchiveButton(discord.ui.Button):
    def __init__(self, order_id, buyer_id):
        super().__init__(label="購入履歴へ", emoji="📁", style=discord.ButtonStyle.secondary, custom_id=f"kira:archive:{order_id}")
        self.order_id = order_id
        self.buyer_id = buyer_id

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        category = await get_or_create_archive_category(interaction.guild)
        await interaction.channel.edit(category=category, reason=f"{BOT_NAME} 購入履歴へ移動")
        await interaction.response.send_message("📁 購入履歴へ移動しました。", ephemeral=True)


class TicketDeleteButton(discord.ui.Button):
    def __init__(self, order_id, buyer_id):
        super().__init__(label="チャット削除", emoji="🗑️", style=discord.ButtonStyle.danger, custom_id=f"kira:delete_ticket:{order_id}")
        self.order_id = order_id
        self.buyer_id = buyer_id

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
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


class TicketArchivePersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:archive:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        category = await get_or_create_archive_category(interaction.guild)
        await interaction.channel.edit(category=category, reason=f"{BOT_NAME} 購入履歴へ移動")
        await interaction.response.send_message("📁 購入履歴へ移動しました。", ephemeral=True)


class TicketDeletePersistentButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kira:delete_ticket:(?P<oid>[A-Za-z0-9_-]{1,64})"):
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🗑️ チャットを削除します。", ephemeral=True)
        await asyncio.sleep(1)
        try:
            await interaction.channel.delete(reason=f"{BOT_NAME} チケット削除")
        except discord.HTTPException:
            pass


# ============================================================
# 商品管理
# ============================================================

class ProductModal(discord.ui.Modal, title="商品を追加"):
    name = discord.ui.TextInput(label="商品名", placeholder="例：Amazonギフト券", max_length=80)
    price = discord.ui.TextInput(label="価格（数字のみ）", placeholder="1000", max_length=10)
    stock = discord.ui.TextInput(label="在庫数", placeholder="10", max_length=8)
    emoji = discord.ui.TextInput(label="表示用絵文字", placeholder="🎁", required=False, max_length=20)
    description = discord.ui.TextInput(label="商品説明", placeholder="商品の説明を入力", required=False, style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, machine_id):
        super().__init__()
        self.machine_id = machine_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        try:
            price = int(str(self.price.value).replace(",", "").strip())
            stock = int(str(self.stock.value).strip())
            if price < 0 or stock < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 価格と在庫数は0以上の数字で入力してください。", ephemeral=True)
            return

        pid = unique_product_id(self.machine_id, self.name.value)
        machine["products"][pid] = {
            "id": pid,
            "name": str(self.name.value).strip()[:80],
            "description": str(self.description.value).strip()[:1000],
            "price": price,
            "stock": stock,
            "active": True,
            "image_url": "",
            "emoji": str(self.emoji.value).strip() or "🛍️",
        }
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send(
            f"✅ **{machine['name']}** に商品を追加しました。\n"
            f"**{machine['products'][pid]['name']}** / {money(price)} / 在庫 {stock}",
            ephemeral=True,
        )


class ProductEditModal(discord.ui.Modal, title="商品を編集"):
    name = discord.ui.TextInput(label="商品名", max_length=80)
    price = discord.ui.TextInput(label="価格", max_length=10)
    description = discord.ui.TextInput(label="商品説明", required=False, style=discord.TextStyle.paragraph, max_length=1000)
    emoji = discord.ui.TextInput(label="表示用絵文字", required=False, max_length=20)

    def __init__(self, machine_id, product_id):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        product = find_product(machine_id, product_id) or {}
        self.name.default = str(product.get("name", ""))
        self.price.default = str(product.get("price", 0))
        self.description.default = str(product.get("description", ""))
        self.emoji.default = str(product.get("emoji", "🛍️"))

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        product = find_product(self.machine_id, self.product_id)
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
        product["name"] = str(self.name.value).strip()[:80]
        product["price"] = price
        product["description"] = str(self.description.value).strip()[:1000]
        product["emoji"] = str(self.emoji.value).strip() or "🛍️"
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ 商品情報を更新しました。", ephemeral=True)


class StockModal(discord.ui.Modal, title="在庫を変更"):
    stock = discord.ui.TextInput(label="新しい在庫数", placeholder="10", max_length=8)

    def __init__(self, machine_id, product_id):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        product = find_product(machine_id, product_id) or {}
        self.stock.default = str(product.get("stock", 0))

    async def on_submit(self, interaction):
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
        product = find_product(self.machine_id, self.product_id)
        if not product:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return
        product["stock"] = stock
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send(f"✅ 在庫を **{stock}個** に変更しました。", ephemeral=True)


class ProductSelect(discord.ui.Select):
    def __init__(self, machine_id, action):
        self.machine_id = machine_id
        self.action = action
        options = []
        for pid, product in list(machine_products(machine_id).items())[:25]:
            options.append(
                discord.SelectOption(
                    label=str(product.get("name", pid))[:100],
                    value=str(pid),
                    description=f"{money(product.get('price', 0))} / 在庫 {product.get('stock', 0)}"[:100],
                )
            )
        if not options:
            options = [discord.SelectOption(label="商品なし", value="__none__", description="先に商品を追加してください。")]
        super().__init__(placeholder="商品を選択してください", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        pid = self.values[0]
        if pid == "__none__":
            await interaction.response.send_message("商品がありません。", ephemeral=True)
            return
        product = find_product(self.machine_id, pid)
        if not product:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return
        if self.action == "edit":
            await interaction.response.send_modal(ProductEditModal(self.machine_id, pid))
        elif self.action == "stock":
            await interaction.response.send_modal(StockModal(self.machine_id, pid))
        elif self.action == "delete":
            del machine_products(self.machine_id)[pid]
            save_json(CONFIG_FILE, config)
            await interaction.response.defer(ephemeral=True)
            await update_purchase_panel(self.machine_id)
            await interaction.followup.send(f"🗑️ **{product.get('name')}** を削除しました。", ephemeral=True)
        elif self.action == "toggle":
            product["active"] = not bool(product.get("active", True))
            save_json(CONFIG_FILE, config)
            await interaction.response.defer(ephemeral=True)
            await update_purchase_panel(self.machine_id)
            state = "販売中" if product["active"] else "非公開"
            await interaction.followup.send(f"✅ **{product.get('name')}** を **{state}** にしました。", ephemeral=True)


class ProductSelectView(discord.ui.View):
    def __init__(self, machine_id, action):
        super().__init__(timeout=120)
        self.add_item(ProductSelect(machine_id, action))


class ProductAdminView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=180)
        self.machine_id = machine_id

    @discord.ui.button(label="商品を追加", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(ProductModal(self.machine_id))

    @discord.ui.button(label="商品を編集", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction, button):
        await interaction.response.send_message("編集する商品を選択してください。", view=ProductSelectView(self.machine_id, "edit"), ephemeral=True)

    @discord.ui.button(label="在庫変更", emoji="📦", style=discord.ButtonStyle.primary, row=0)
    async def stock(self, interaction, button):
        await interaction.response.send_message("在庫を変更する商品を選択してください。", view=ProductSelectView(self.machine_id, "stock"), ephemeral=True)

    @discord.ui.button(label="販売ON/OFF", emoji="🔄", style=discord.ButtonStyle.secondary, row=1)
    async def toggle(self, interaction, button):
        await interaction.response.send_message("切り替える商品を選択してください。", view=ProductSelectView(self.machine_id, "toggle"), ephemeral=True)

    @discord.ui.button(label="商品削除", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction, button):
        await interaction.response.send_message("削除する商品を選択してください。", view=ProductSelectView(self.machine_id, "delete"), ephemeral=True)

    @discord.ui.button(label="画像を設定", emoji="🖼️", style=discord.ButtonStyle.primary, row=1)
    async def image(self, interaction, button):
        await interaction.response.send_message(
            "📷 商品画像は `/product_image` から設定できます。\n"
            "複数の自販機がある場合は、商品一覧から対象を選択してください。",
            ephemeral=True,
        )

    @discord.ui.button(label="商品プレビュー", emoji="👀", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        active = [p for p in machine_products(self.machine_id).values() if p.get("active", True)]
        if not active:
            await interaction.response.send_message("現在販売中の商品はありません。", ephemeral=True)
            return
        await interaction.response.send_message(embed=product_embed(self.machine_id, active[0]), ephemeral=True)


# ============================================================
# デザイン管理
# ============================================================

COLOR_CHOICES = [
    ("🟣 パープル", "purple", 0x5865F2),
    ("🔵 ブルー", "blue", 0x3498DB),
    ("🩵 シアン", "cyan", 0x00B8D9),
    ("🟢 グリーン", "green", 0x2ECC71),
    ("🟡 イエロー", "yellow", 0xF1C40F),
    ("🟠 オレンジ", "orange", 0xE67E22),
    ("🔴 レッド", "red", 0xE74C3C),
    ("🩷 ピンク", "pink", 0xE91E63),
    ("⚫ ダーク", "dark", 0x2B2D31),
    ("⚪ ライト", "light", 0xFFFFFF),
]

BUTTON_STYLE_CHOICES = [
    ("🔵 ブルー", "primary"),
    ("🟢 グリーン", "success"),
    ("🔴 レッド", "danger"),
    ("⚪ グレー", "secondary"),
]


class DesignTextModal(discord.ui.Modal, title="タイトル・説明を編集"):
    title_text = discord.ui.TextInput(label="タイトル", max_length=256)
    subtitle = discord.ui.TextInput(label="サブタイトル", max_length=256, required=False)
    description = discord.ui.TextInput(label="説明文", style=discord.TextStyle.paragraph, max_length=2000, required=False)
    notice = discord.ui.TextInput(label="お知らせ", style=discord.TextStyle.paragraph, max_length=1000, required=False)
    footer = discord.ui.TextInput(label="フッター", max_length=256, required=False)

    def __init__(self, machine_id):
        super().__init__()
        self.machine_id = machine_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        d = machine["design"]
        d["title"] = str(self.title_text.value).strip() or f"🛒 {machine['name']}"
        d["subtitle"] = str(self.subtitle.value).strip()
        d["description"] = str(self.description.value).strip()
        d["notice"] = str(self.notice.value).strip()
        d["footer"] = str(self.footer.value).strip()
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ タイトル・説明を更新しました。", ephemeral=True)


class ColorSelect(discord.ui.Select):
    def __init__(self, machine_id):
        self.machine_id = machine_id
        options = [discord.SelectOption(label=label, value=value) for label, value, _ in COLOR_CHOICES]
        super().__init__(placeholder="カラーを選択してください", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        selected = self.values[0]
        for _, key, color in COLOR_CHOICES:
            if key == selected:
                machine["design"]["color"] = color
                break
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ 色を変更しました。", ephemeral=True)


class ColorSelectView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=120)
        self.add_item(ColorSelect(machine_id))


class ButtonStyleSelect(discord.ui.Select):
    def __init__(self, machine_id):
        self.machine_id = machine_id
        options = [discord.SelectOption(label=label, value=value) for label, value in BUTTON_STYLE_CHOICES]
        super().__init__(placeholder="購入ボタンの色を選択してください", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        machine["design"]["button_style"] = self.values[0]
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ 購入ボタンの色を変更しました。", ephemeral=True)


class ButtonStyleSelectView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=120)
        self.add_item(ButtonStyleSelect(machine_id))


class BannerModal(discord.ui.Modal, title="バナーURLを変更"):
    url = discord.ui.TextInput(label="画像URL", placeholder="https://...", required=False, max_length=500)

    def __init__(self, machine_id):
        super().__init__()
        self.machine_id = machine_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        url = str(self.url.value).strip()
        if url and not re.match(r"^https?://[^\s]+$", url, re.IGNORECASE):
            await interaction.response.send_message("❌ 有効なhttp/https URLを入力してください。", ephemeral=True)
            return
        machine["design"]["banner_url"] = url
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ バナーを更新しました。", ephemeral=True)


class DesignPresetSelect(discord.ui.Select):
    def __init__(self, machine_id):
        self.machine_id = machine_id
        options = [
            discord.SelectOption(label="🛒 シンプル", value="simple", description="青系・標準ボタン"),
            discord.SelectOption(label="💜 パープルショップ", value="purple", description="紫系・緑ボタン"),
            discord.SelectOption(label="🔥 レッドショップ", value="red", description="赤系・白ボタン"),
            discord.SelectOption(label="💎 ブルーショップ", value="blue", description="青系・青ボタン"),
            discord.SelectOption(label="🌙 ダークショップ", value="dark", description="ダーク系・青ボタン"),
        ]
        super().__init__(placeholder="デザインプリセットを選択", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        presets = {
            "simple": (0x5865F2, "primary"),
            "purple": (0x9B59B6, "success"),
            "red": (0xE74C3C, "secondary"),
            "blue": (0x3498DB, "primary"),
            "dark": (0x2B2D31, "primary"),
        }
        color, style = presets[self.values[0]]
        machine["design"]["color"] = color
        machine["design"]["button_style"] = style
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(self.machine_id)
        await interaction.followup.send("✅ デザインプリセットを適用しました。", ephemeral=True)


class DesignPresetView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=120)
        self.add_item(DesignPresetSelect(machine_id))


class DesignView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=180)
        self.machine_id = machine_id

    @discord.ui.button(label="タイトル・説明", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def text(self, interaction, button):
        machine = get_machine(self.machine_id)
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        modal = DesignTextModal(self.machine_id)
        d = machine["design"]
        modal.title_text.default = d.get("title", f"🛒 {machine['name']}")
        modal.subtitle.default = d.get("subtitle", "")
        modal.description.default = d.get("description", "")
        modal.notice.default = d.get("notice", "")
        modal.footer.default = d.get("footer", "")
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="色を選ぶ", emoji="🎨", style=discord.ButtonStyle.primary, row=0)
    async def color(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("自販機の色を選択してください。", view=ColorSelectView(self.machine_id), ephemeral=True)

    @discord.ui.button(label="購入ボタン色", emoji="🔘", style=discord.ButtonStyle.primary, row=0)
    async def button_color(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("購入ボタンの色を選択してください。", view=ButtonStyleSelectView(self.machine_id), ephemeral=True)

    @discord.ui.button(label="バナー", emoji="🖼️", style=discord.ButtonStyle.primary, row=1)
    async def banner(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(BannerModal(self.machine_id))

    @discord.ui.button(label="プリセット", emoji="✨", style=discord.ButtonStyle.secondary, row=1)
    async def presets(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("デザインを選択してください。", view=DesignPresetView(self.machine_id), ephemeral=True)

    @discord.ui.button(label="プレビュー", emoji="👀", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message(embed=vending_embed(self.machine_id), view=PurchaseView(self.machine_id), ephemeral=True)


# ============================================================
# 自販機チャンネル設定
# ============================================================

class MachinePurchaseChannelSelect(discord.ui.Select):
    def __init__(self, machine_id, guild):
        self.machine_id = machine_id
        channels = [c for c in guild.text_channels if not c.category or c.category]
        channels = channels[:25]
        options = [discord.SelectOption(label=c.name[:100], value=str(c.id)) for c in channels]
        if not options:
            options = [discord.SelectOption(label="チャンネルなし", value="__none__")]
        super().__init__(placeholder="購入チャンネルを選択", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message("チャンネルがありません。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        machine["purchase_channel_id"] = int(self.values[0])
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message("✅ 購入チャンネルを設定しました。", ephemeral=True)


class MachinePurchaseChannelView(discord.ui.View):
    def __init__(self, machine_id, guild):
        super().__init__(timeout=120)
        self.add_item(MachinePurchaseChannelSelect(machine_id, guild))


class MachineChannelView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=180)
        self.machine_id = machine_id

    @discord.ui.button(label="購入チャンネルを選択", emoji="🛒", style=discord.ButtonStyle.primary, row=0)
    async def choose_purchase(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("この自販機の購入チャンネルを選択してください。", view=MachinePurchaseChannelView(self.machine_id, interaction.guild), ephemeral=True)

    @discord.ui.button(label="購入チャンネルを自動作成", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def create_purchase(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await find_purchase_channel(self.machine_id, interaction.guild, create=True)
            await interaction.followup.send(f"✅ 購入チャンネル: {channel.mention}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 購入チャンネルの作成に失敗しました。", ephemeral=True)


# ============================================================
# 自販機作成 / 選択 / 管理
# ============================================================

class MachineCreateModal(discord.ui.Modal, title="自販機を新規作成"):
    name = discord.ui.TextInput(label="自販機名", placeholder="例：Amazon自販機", max_length=80)

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        name = str(self.name.value).strip()
        if not name:
            await interaction.response.send_message("❌ 自販機名を入力してください。", ephemeral=True)
            return
        machine_id = unique_machine_id(name)
        machine = default_machine(machine_id, name)
        config["machines"][machine_id] = machine
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(
            f"✅ **{name}** を作成しました。\n"
            "次にこの自販機を選択して商品・デザイン・購入チャンネルを設定してください。",
            ephemeral=True,
        )


class MachineSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for machine_id, machine in list(config["machines"].items())[:25]:
            count = len(machine.get("products", {}))
            options.append(
                discord.SelectOption(
                    label=str(machine.get("name", machine_id))[:100],
                    value=str(machine_id),
                    description=f"商品 {count}件 / ID: {machine_id}"[:100],
                )
            )
        if not options:
            options = [discord.SelectOption(label="自販機なし", value="__none__", description="先に自販機を作成してください。")]
        super().__init__(placeholder="管理する自販機を選択", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine_id = self.values[0]
        if machine_id == "__none__":
            await interaction.response.send_message("自販機がありません。", ephemeral=True)
            return
        machine = get_machine(machine_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🏪 **{machine['name']}** の管理メニュー",
            view=MachineAdminView(machine_id),
            ephemeral=True,
        )


class MachineManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(MachineSelect())

    @discord.ui.button(label="自販機を新規作成", emoji="➕", style=discord.ButtonStyle.success, row=1)
    async def create(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_modal(MachineCreateModal())


class DeleteMachineConfirmView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=60)
        self.machine_id = machine_id

    @discord.ui.button(label="削除する", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        if self.machine_id not in config["machines"]:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        if len(config["machines"]) <= 1:
            await interaction.response.send_message("❌ 最後の1台は削除できません。", ephemeral=True)
            return
        name = config["machines"][self.machine_id].get("name", self.machine_id)
        del config["machines"][self.machine_id]
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(
            f"🗑️ **{name}** を削除しました。\n"
            "※Discord上のチャンネル自体は安全のため削除していません。",
            ephemeral=True,
        )

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content="削除をキャンセルしました。", view=None)


class MachineAdminView(discord.ui.View):
    def __init__(self, machine_id):
        super().__init__(timeout=240)
        self.machine_id = machine_id

    @discord.ui.button(label="販売機を設置・更新", emoji="🚀", style=discord.ButtonStyle.success, row=0)
    async def deploy(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await deploy_purchase_panel(self.machine_id, interaction.guild)
            await interaction.followup.send(f"✅ **{get_machine(self.machine_id)['name']}** を設置・更新しました。\n{message.jump_url}", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 販売機の設置・更新に失敗しました。", ephemeral=True)

    @discord.ui.button(label="商品管理", emoji="🛍️", style=discord.ButtonStyle.primary, row=0)
    async def products(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        await interaction.response.send_message(
            f"🛍️ **{machine['name']}の商品管理**",
            view=ProductAdminView(self.machine_id),
            ephemeral=True,
        )

    @discord.ui.button(label="デザイン", emoji="🎨", style=discord.ButtonStyle.primary, row=0)
    async def design(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🎨 **自販機デザイン**", view=DesignView(self.machine_id), ephemeral=True)

    @discord.ui.button(label="チャンネル設定", emoji="⚙️", style=discord.ButtonStyle.secondary, row=1)
    async def channels(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("⚙️ **この自販機のチャンネル設定**", view=MachineChannelView(self.machine_id), ephemeral=True)

    @discord.ui.button(label="削除", emoji="🗑️", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine = get_machine(self.machine_id)
        await interaction.response.send_message(
            f"⚠️ **{machine['name']}** を削除しますか？",
            view=DeleteMachineConfirmView(self.machine_id),
            ephemeral=True,
        )

    @discord.ui.button(label="自販機一覧へ", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🏪 管理する自販機を選択してください。", view=MachineManagerView(), ephemeral=True)


# ============================================================
# メッセージ送信（毎回チャンネル選択）
# ============================================================

class AdminMessageModal(discord.ui.Modal, title="管理者メッセージ送信"):
    content = discord.ui.TextInput(
        label="本文",
        placeholder="ボットに送信させたい文章を入力",
        style=discord.TextStyle.paragraph,
        max_length=4000,
    )
    title_text = discord.ui.TextInput(label="Embedタイトル（任意）", required=False, max_length=256)

    def __init__(self, channel_id):
        super().__init__()
        self.channel_id = channel_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = interaction.guild.get_channel(self.channel_id)
            if not isinstance(channel, discord.TextChannel):
                await interaction.followup.send("❌ 指定されたチャンネルが見つかりません。", ephemeral=True)
                return
            content = str(self.content.value).strip()
            title = str(self.title_text.value).strip()
            if title:
                embed = discord.Embed(title=title, description=content, color=discord.Color.blurple())
                await channel.send(embed=embed)
            else:
                await channel.send(content)
            await interaction.followup.send(f"✅ {channel.mention} に送信しました。", ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ メッセージ送信中にエラーが発生しました。", ephemeral=True)


class AdminMessageChannelSelect(discord.ui.Select):
    def __init__(self, guild):
        channels = guild.text_channels[:25]
        options = [discord.SelectOption(label=c.name[:100], value=str(c.id)) for c in channels]
        if not options:
            options = [discord.SelectOption(label="チャンネルなし", value="__none__")]
        super().__init__(placeholder="送信先チャンネルを選択", options=options)

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        if self.values[0] == "__none__":
            await interaction.response.send_message("チャンネルがありません。", ephemeral=True)
            return
        await interaction.response.send_modal(AdminMessageModal(int(self.values[0])))


class AdminMessageChannelView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=120)
        self.add_item(AdminMessageChannelSelect(guild))


# ============================================================
# 管理パネル
# ============================================================

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="自販機管理", emoji="🏪", style=discord.ButtonStyle.success, custom_id="kira:admin:machines", row=0)
    async def machines(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("🏪 **管理する自販機を選択してください。**", view=MachineManagerView(), ephemeral=True)

    @discord.ui.button(label="メッセージ送信", emoji="📨", style=discord.ButtonStyle.primary, custom_id="kira:admin:message", row=0)
    async def message(self, interaction, button):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.send_message("📨 **送信先チャンネルを毎回選択してください。**", view=AdminMessageChannelView(interaction.guild), ephemeral=True)


# ============================================================
# 購入パネル更新 / 設置
# ============================================================

async def update_purchase_panel(machine_id):
    machine = get_machine(machine_id)
    if not machine:
        return False
    channel_id = machine.get("panel_channel_id", 0)
    message_id = machine.get("panel_message_id", 0)
    if not channel_id or not message_id:
        return False

    channel = bot.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        message = await channel.fetch_message(int(message_id))
        await message.edit(
            embed=vending_embed(machine_id),
            view=PurchaseView(machine_id),
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def deploy_purchase_panel(machine_id, guild):
    machine = get_machine(machine_id)
    if not machine:
        raise RuntimeError("自販機が見つかりません。")

    channel = await find_purchase_channel(machine_id, guild, create=True)
    existing = None
    if machine.get("panel_message_id") and machine.get("panel_channel_id") == channel.id:
        try:
            existing = await channel.fetch_message(int(machine["panel_message_id"]))
        except (discord.NotFound, discord.HTTPException):
            existing = None

    if existing:
        await existing.edit(embed=vending_embed(machine_id), view=PurchaseView(machine_id))
        message = existing
    else:
        message = await channel.send(embed=vending_embed(machine_id), view=PurchaseView(machine_id))

    machine["panel_message_id"] = message.id
    machine["panel_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return message


async def deploy_all_machines(guild):
    results = []
    for machine_id in list(config["machines"].keys()):
        try:
            message = await deploy_purchase_panel(machine_id, guild)
            results.append(f"✅ **{get_machine(machine_id)['name']}** → {message.jump_url}")
        except Exception as exc:
            traceback.print_exc()
            machine = get_machine(machine_id) or {}
            results.append(f"❌ **{machine.get('name', machine_id)}** → `{type(exc).__name__}`")
    return results


async def refresh_all_purchase_panels(guild):
    """再起動前の旧ボタンを含め、登録済み全自販機パネルを現在のViewへ更新する。"""
    for machine_id in list(config.get("machines", {}).keys()):
        machine = get_machine(machine_id)
        if not machine:
            continue
        if not machine.get("panel_message_id") or not machine.get("panel_channel_id"):
            continue
        try:
            channel = guild.get_channel(int(machine["panel_channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            message = await channel.fetch_message(int(machine["panel_message_id"]))
            await message.edit(
                embed=vending_embed(machine_id),
                view=PurchaseView(machine_id),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, ValueError):
            continue
        except Exception:
            traceback.print_exc()


# ============================================================
# Bot
# ============================================================

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


class KiraBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.keepalive_task = None

    async def setup_hook(self):
        # 各自販機の永続購入Viewを登録
        for machine_id, machine in config.get("machines", {}).items():
            try:
                self.add_view(
                    PurchaseView(machine_id),
                    message_id=int(machine.get("panel_message_id", 0)) if machine.get("panel_message_id") else None,
                )
            except Exception:
                traceback.print_exc()

        self.add_view(AdminPanelView())
        self.add_dynamic_items(
            OrderPaidPersistentButton,
            OrderCancelPersistentButton,
            TicketArchivePersistentButton,
            TicketDeletePersistentButton,
        )

        if self.keepalive_task is None or self.keepalive_task.done():
            self.keepalive_task = asyncio.create_task(self._keepalive_loop(), name="kira-keepalive")

        try:
            synced = await self.tree.sync()
            print(f"[INFO] Slash commands synced: {len(synced)}")
        except Exception:
            traceback.print_exc()

    async def _keepalive_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(240)
            print(
                f"[KEEPALIVE] {datetime.now(timezone.utc).isoformat()} "
                f"ready={self.is_ready()} closed={self.is_closed()} machines={len(config.get('machines', {}))}"
            )


bot = KiraBot(command_prefix="!", intents=intents, help_command=None)
ready_once = False


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="admin", description="管理者専用の自動販売機管理パネルを表示")
    async def admin(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine_count = len(config.get("machines", {}))
        embed = discord.Embed(
            title="⚙️ キラの自動販売機 管理パネル",
            description=(
                f"現在の自販機: **{machine_count}台**\n\n"
                "🏪 **自販機管理**\n"
                "自販機ごとに商品・在庫・デザイン・購入チャンネルを管理\n\n"
                "📨 **メッセージ送信**\n"
                "送信先チャンネルを毎回選択してBotとして送信"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=AdminPanelView(), ephemeral=True)

    @app_commands.command(name="setup_vending", description="自販機を設置・更新。自販機未指定なら全台を更新")
    @app_commands.describe(vending="自販機ID（省略すると全台）")
    async def setup_vending(self, interaction: discord.Interaction, vending: str = ""):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if vending.strip():
                machine = get_machine(vending.strip())
                if not machine:
                    await interaction.followup.send("❌ 指定された自販機IDが見つかりません。", ephemeral=True)
                    return
                message = await deploy_purchase_panel(vending.strip(), interaction.guild)
                await interaction.followup.send(f"✅ **{machine['name']}** を設置・更新しました。\n{message.jump_url}", ephemeral=True)
            else:
                results = await deploy_all_machines(interaction.guild)
                await interaction.followup.send("\n".join(results)[:1900], ephemeral=True)
        except Exception:
            traceback.print_exc()
            await interaction.followup.send("❌ 販売機の設置・更新に失敗しました。", ephemeral=True)

    @setup_vending.autocomplete("vending")
    async def setup_vending_autocomplete(self, interaction, current: str):
        current = current.lower().strip()
        results = []
        for mid, machine in config.get("machines", {}).items():
            name = str(machine.get("name", mid))
            if current in mid.lower() or current in name.lower():
                results.append(app_commands.Choice(name=f"{name} [{mid}]"[:100], value=mid))
            if len(results) >= 25:
                break
        return results

    @app_commands.command(name="send_message", description="管理者専用：指定チャンネルへBotとして文章を送信")
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
            await interaction.followup.send("❌ 送信できませんでした。", ephemeral=True)

    @app_commands.command(name="product_add", description="管理者専用：指定した自販機へ商品を追加")
    @app_commands.describe(
        name="商品名",
        price="価格",
        stock="在庫数",
        description="商品説明",
        emoji="表示用絵文字",
        vending="自販機ID（自販機が1台なら省略可）",
        image="商品画像（任意）",
    )
    async def product_add(
        self,
        interaction: discord.Interaction,
        name: str,
        price: int,
        stock: int,
        description: str = "",
        emoji: str = "🛍️",
        vending: str = "",
        image: Optional[discord.Attachment] = None,
    ):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        machine_id = vending.strip()
        if not machine_id:
            machine_id = next(iter(config["machines"])) if len(config["machines"]) == 1 else ""
        machine = get_machine(machine_id)
        if not machine:
            await interaction.response.send_message("❌ 対象の自販機を指定してください。複数台ある場合は `vending` を選択します。", ephemeral=True)
            return
        if price < 0 or stock < 0:
            await interaction.response.send_message("❌ 価格と在庫数は0以上で指定してください。", ephemeral=True)
            return
        if image and (not image.content_type or not str(image.content_type).startswith("image/")):
            await interaction.response.send_message("❌ 商品画像には画像ファイルを指定してください。", ephemeral=True)
            return

        pid = unique_product_id(machine_id, name)
        machine["products"][pid] = {
            "id": pid,
            "name": name.strip()[:80],
            "description": description.strip()[:1000],
            "price": price,
            "stock": stock,
            "active": True,
            "image_url": image.url if image else "",
            "emoji": emoji.strip()[:20] or "🛍️",
        }
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(machine_id)
        await interaction.followup.send(
            f"✅ **{machine['name']}** に商品を追加しました！\n"
            f"**{machine['products'][pid]['name']}** / {money(price)} / 在庫 {stock}",
            ephemeral=True,
        )

    @product_add.autocomplete("vending")
    async def product_add_vending_autocomplete(self, interaction, current: str):
        current = current.lower().strip()
        results = []
        for mid, machine in config.get("machines", {}).items():
            name = str(machine.get("name", mid))
            if current in mid.lower() or current in name.lower():
                results.append(app_commands.Choice(name=f"{name} [{mid}]"[:100], value=mid))
            if len(results) >= 25:
                break
        return results

    @app_commands.command(name="product_image", description="管理者専用：商品画像を設定")
    @app_commands.describe(target="自販機/商品を選択", image="設定する画像ファイル")
    async def product_image(self, interaction: discord.Interaction, target: str, image: discord.Attachment):
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
            return
        parts = target.split("::", 1)
        if len(parts) != 2:
            await interaction.response.send_message("❌ 対象商品の選択肢を選んでください。", ephemeral=True)
            return
        machine_id, product_id = parts
        product = find_product(machine_id, product_id)
        if not product:
            await interaction.response.send_message("❌ 指定された商品が見つかりません。", ephemeral=True)
            return
        if not image.content_type or not str(image.content_type).startswith("image/"):
            await interaction.response.send_message("❌ 画像ファイルを指定してください。", ephemeral=True)
            return
        product["image_url"] = image.url
        save_json(CONFIG_FILE, config)
        await interaction.response.defer(ephemeral=True)
        await update_purchase_panel(machine_id)
        await interaction.followup.send(f"🖼️ **{product.get('name', product_id)}** の画像を設定しました。", ephemeral=True)

    @product_image.autocomplete("target")
    async def product_image_autocomplete(self, interaction, current: str):
        current = current.lower().strip()
        results = []
        for mid, machine in config.get("machines", {}).items():
            for pid, product in machine.get("products", {}).items():
                label = f"{machine.get('name', mid)} / {product.get('name', pid)}"
                value = f"{mid}::{pid}"
                if current in label.lower() or current in value.lower():
                    results.append(app_commands.Choice(name=label[:100], value=value[:100]))
                if len(results) >= 25:
                    return results
        return results


@bot.event
async def on_connect():
    print(f"[CONNECT] Discord Gateway connected / {BOT_NAME}")


@bot.event
async def on_resumed():
    print(f"[RESUMED] Discord Gateway session resumed / {BOT_NAME}")


@bot.event
async def on_disconnect():
    print(f"[DISCONNECT] Discord Gateway disconnected / {BOT_NAME}")


@bot.event
async def on_ready():
    global ready_once
    print(f"[READY] {bot.user} / {BOT_NAME} / machines={len(config.get('machines', {}))}")
    if ready_once:
        return
    ready_once = True

    guild_id = config.get("guild_id", 0)
    if guild_id:
        guild = bot.get_guild(int(guild_id))
        if guild:
            try:
                await get_or_create_order_channel(guild)
            except Exception:
                traceback.print_exc()
            try:
                await refresh_all_purchase_panels(guild)
            except Exception:
                traceback.print_exc()


@bot.event
async def on_guild_join(guild):
    if not config.get("guild_id"):
        config["guild_id"] = guild.id
        save_json(CONFIG_FILE, config)


@bot.event
async def on_error(event, *args, **kwargs):
    print(f"[ERROR] event={event}")
    traceback.print_exc()


async def main():
    token = os.getenv("DORD_TOKEN")
    if not token:
        raise RuntimeError("DORD_TOKEN が環境変数に設定されていません。")
    await bot.add_cog(AdminCog(bot))
    await bot.start(token, reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
