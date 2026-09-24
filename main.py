import os
import json
import asyncio
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "キラの自動販売機"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.path.join(BASE_DIR, "products.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
ORDERS_FILE = os.path.join(BASE_DIR, "orders.json")

DEFAULT_CONFIG = {
    "guild_id": 0,
    "purchase_channel_id": 0,
    "order_channel_id": 0,
    "admin_category_id": 0,
    "ticket_category_id": 0,
    "media_channel_id": 0,
    "panel_message_id": 0,
    "panel_channel_id": 0,
    "order_counter": 0,
    "media_library": [],
    "design": {
        "title": "🛒 キラの自動販売機",
        "subtitle": "✨ 商品を選択してお買い物をお楽しみください ✨",
        "description": "下のボタンから商品を選択してください。",
        "notice": "📢 ご購入前に商品内容をご確認ください。",
        "footer": "KIRA VENDING",
        "color": 0x8B5CF6,
        "banner_url": "",
        "show_stock": True,
    },
}

DEFAULT_PRODUCTS = [
    {
        "id": "sample-1",
        "name": "サンプル商品",
        "description": "管理画面から商品情報を変更できます。",
        "price": 500,
        "stock": 10,
        "emoji": "🛍️",
        "image_url": "",
        "enabled": True,
    }
]


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_json(path, default):
    if not os.path.exists(path):
        save_json(path, default)
        return json.loads(json.dumps(default, ensure_ascii=False))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        save_json(path, default)
        return json.loads(json.dumps(default, ensure_ascii=False))


config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
products = load_json(PRODUCTS_FILE, DEFAULT_PRODUCTS)
orders = load_json(ORDERS_FILE, {})

if not isinstance(products, list):
    products = DEFAULT_PRODUCTS.copy()
if not isinstance(orders, dict):
    orders = {}

for key, value in DEFAULT_CONFIG.items():
    if key not in config:
        config[key] = json.loads(json.dumps(value)) if isinstance(value, dict) else value
for key, value in DEFAULT_CONFIG["design"].items():
    config.setdefault("design", {}).setdefault(key, value)
config.setdefault("media_library", [])

for p in products:
    p.setdefault("id", f"product-{len(products) + 1}")
    p.setdefault("name", "商品")
    p.setdefault("description", "")
    p.setdefault("price", 0)
    p.setdefault("stock", 0)
    p.setdefault("emoji", "🛒")
    p.setdefault("image_url", "")
    p.setdefault("enabled", True)

save_json(PRODUCTS_FILE, products)
save_json(CONFIG_FILE, config)
save_json(ORDERS_FILE, orders)

purchase_lock = asyncio.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def money(value):
    return f"¥{int(value):,}"


def is_admin(member):
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def find_product(product_id):
    for p in products:
        if p.get("id") == product_id:
            return p
    return None


def next_order_id():
    config["order_counter"] = int(config.get("order_counter", 0)) + 1
    save_json(CONFIG_FILE, config)
    return f"{config['order_counter']:05d}"


def channel_mention(guild, cid):
    ch = guild.get_channel(int(cid or 0)) if guild else None
    return ch.mention if ch else "未設定"


def category_mention(guild, cid):
    ch = guild.get_channel(int(cid or 0)) if guild else None
    return f"`{ch.name}`" if isinstance(ch, discord.CategoryChannel) else "未設定"


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


# ============================================================
# デザイン
# ============================================================


def design_embed():
    d = config["design"]
    embed = discord.Embed(
        title=d["title"],
        description=(
            f"**{d['subtitle']}**\n\n"
            f"{d['description']}\n\n"
            f"{d['notice']}"
        ),
        color=int(d["color"]),
    )

    active = [p for p in products if p.get("enabled", True)]
    if not active:
        embed.add_field(
            name="📦 商品",
            value="現在販売中の商品はありません。",
            inline=False,
        )
    else:
        chunks = []
        for p in active[:25]:
            stock = int(p.get("stock", 0))
            stock_text = f"在庫: **{stock}**" if d.get("show_stock", True) else "在庫あり"
            if stock <= 0:
                stock_text = "🔴 売り切れ"
            chunks.append(
                f"{p.get('emoji', '🛒')} **{p['name']}** — {money(p['price'])}\n"
                f"{p.get('description', '')[:120]}\n{stock_text}"
            )
        embed.add_field(
            name="🛍️ 商品一覧",
            value="\n\n".join(chunks)[:1024],
            inline=False,
        )

    if d.get("footer"):
        embed.set_footer(text=d["footer"])
    return embed


# ============================================================
# 非公開チャンネル権限
# ============================================================

async def secure_private_channel(channel, guild, buyer=None):
    """一般ユーザーから隠し、Botと購入者だけが使えるようにする。"""
    me = guild.me
    if me is None:
        raise RuntimeError("BotのMember情報を取得できません。")

    if not me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    # @everyoneを非表示にする。AdministratorはDiscord側でこの拒否を迂回する。
    await channel.set_permissions(
        guild.default_role,
        view_channel=False,
        reason=f"{BOT_NAME} 非公開設定",
    )

    # Administratorなら余計なBot用overwrite APIを呼ばない。
    if not me.guild_permissions.administrator:
        await channel.set_permissions(
            me,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            manage_messages=True,
            manage_channels=True,
            reason=f"{BOT_NAME} Bot権限",
        )

    if buyer is not None:
        await channel.set_permissions(
            buyer,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            reason=f"{BOT_NAME} 購入者権限",
        )

    perms = channel.permissions_for(me)
    if not perms.view_channel or not perms.send_messages:
        raise RuntimeError(
            "作成した非公開チャンネルでBotが閲覧/送信できません。"
            f" (view={perms.view_channel}, send={perms.send_messages})"
        )


async def get_or_create_category(guild, name, config_key):
    cid = int(config.get(config_key, 0) or 0)
    if cid:
        category = guild.get_channel(cid)
        if isinstance(category, discord.CategoryChannel):
            return category

    me = guild.me
    if not me or not me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    category = await guild.create_category(
        name,
        reason=f"{BOT_NAME} 自動作成",
    )
    config[config_key] = category.id
    save_json(CONFIG_FILE, config)
    return category


# ============================================================
# 注文通知
# ============================================================

async def get_or_create_order_channel(guild: discord.Guild):
    """管理者専用 #注文通知 を取得し、なければBot自身で作成する。"""
    if guild is None:
        raise RuntimeError("サーバー情報を取得できません。")

    me = guild.me
    if me is None:
        raise RuntimeError("BotのMember情報を取得できません。")
    if not me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    saved_id = int(config.get("order_channel_id", 0) or 0)
    channel = guild.get_channel(saved_id) if saved_id else None

    if not isinstance(channel, discord.TextChannel):
        channel = next((c for c in guild.text_channels if c.name == "注文通知"), None)

    if isinstance(channel, discord.TextChannel):
        try:
            await secure_private_channel(channel, guild)
        except discord.Forbidden as e:
            raise RuntimeError(
                "既存の #注文通知 の非公開設定に失敗しました。"
                "Botの「チャンネルの管理」権限を確認してください。"
            ) from e
        config["order_channel_id"] = channel.id
        save_json(CONFIG_FILE, config)
        return channel

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if not me.guild_permissions.administrator:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            manage_messages=True,
        )

    try:
        channel = await guild.create_text_channel(
            "注文通知",
            overwrites=overwrites,
            topic=f"{BOT_NAME} 注文通知（管理者専用）",
            reason=f"{BOT_NAME} 注文通知チャンネル自動作成",
        )
    except discord.Forbidden as e:
        raise RuntimeError(
            "#注文通知を作成できませんでした。"
            "Botの「チャンネルの管理」権限とロール位置を確認してください。"
        ) from e

    # 作成直後にも必ず検証。
    try:
        await secure_private_channel(channel, guild)
    except discord.Forbidden as e:
        raise RuntimeError(
            "#注文通知は作成できましたが、非公開設定に失敗しました。"
            "Botの「チャンネルの管理」権限を確認してください。"
        ) from e

    config["order_channel_id"] = channel.id
    save_json(CONFIG_FILE, config)
    return channel


async def get_or_create_ticket_category(guild):
    return await get_or_create_category(
        guild,
        "💬 購入チャット",
        "ticket_category_id",
    )


async def create_ticket(order, guild: discord.Guild, buyer: discord.Member):
    """購入ごとに、購入者・Botだけが使える専用チャットを作る。管理者はAdministratorで閲覧可能。"""
    me = guild.me
    if me is None:
        raise RuntimeError("BotのMember情報を取得できません。")
    if not me.guild_permissions.manage_channels:
        raise RuntimeError("Botに「チャンネルの管理」権限がありません。")

    # カテゴリは見つかれば使う。カテゴリ作成/取得が失敗してもサーバー直下で続行。
    category = None
    try:
        category = await get_or_create_ticket_category(guild)
    except Exception as e:
        print(f"[TICKET] カテゴリを使わず作成します: {e}")

    channel_name = f"chat-kira-{clean_channel_name(str(order['id']))}"

    # まずチャンネルだけ作る。複雑なoverwriteで作成時403になる可能性を下げる。
    try:
        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            topic=f"キラ注文 #{order['id']} / {order['product_name']}",
            reason=f"注文 #{order['id']} 専用チャット",
        )
    except discord.Forbidden as first_error:
        if category is None:
            raise RuntimeError(
                f"専用チャットの作成に失敗しました: {first_error}"
            ) from first_error
        print(f"[TICKET] カテゴリ付き作成失敗。直下で再試行: {first_error}")
        try:
            channel = await guild.create_text_channel(
                channel_name,
                topic=f"キラ注文 #{order['id']} / {order['product_name']}",
                reason=f"注文 #{order['id']} 専用チャット再試行",
            )
        except discord.Forbidden as second_error:
            raise RuntimeError(
                f"専用チャットの作成に失敗しました: {second_error}"
            ) from second_error

    try:
        await secure_private_channel(channel, guild, buyer)
    except Exception:
        # チャンネル自体は残す。注文データから管理者が確認できるようにする。
        raise

    embed = discord.Embed(
        title=f"💬 注文 #{order['id']} 専用チャット",
        description=(
            f"**商品:** {order['product_name']}\n"
            f"**金額:** {money(order['price'])}\n"
            f"**購入者:** {buyer.mention}\n\n"
            "PayPay送金URLを受け取りました。\n"
            "管理者が入金確認後、注文処理を進めます。"
        ),
        color=discord.Color(config["design"].get("color", 0x8B5CF6)),
    )
    embed.add_field(
        name="💳 PayPay送金URL",
        value=order["paypay_url"][:1024],
        inline=False,
    )
    embed.set_footer(text=f"{BOT_NAME} • #{order['id']}")

    await channel.send(
        content=buyer.mention,
        embed=embed,
        view=TicketView(order["id"]),
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    order["ticket_channel_id"] = channel.id
    save_json(ORDERS_FILE, orders)
    return channel


# ============================================================
# 販売ボタン
# ============================================================

def make_purchase_view():
    return PurchaseView()


class PurchaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        active = [p for p in products if p.get("enabled", True)]
        for p in active[:25]:
            self.add_item(
                ProductButton(
                    p["id"],
                    p.get("name", "商品"),
                    p.get("emoji", "🛒"),
                )
            )


class ProductButton(discord.ui.Button):
    def __init__(self, product_id, name, emoji):
        product = find_product(product_id)
        stock = int(product.get("stock", 0)) if product else 0
        super().__init__(
            label=(name[:77] + (" • SOLD OUT" if stock <= 0 else ""))[:80],
            emoji=emoji[:10] if emoji else "🛒",
            style=(
                discord.ButtonStyle.secondary
                if stock <= 0
                else discord.ButtonStyle.primary
            ),
            disabled=stock <= 0,
            custom_id=f"kira:buy:{product_id}",
        )
        self.product_id = product_id

    async def callback(self, interaction: discord.Interaction):
        product = find_product(self.product_id)
        if not product or not product.get("enabled", True):
            return await interaction.response.send_message(
                "❌ この商品は現在販売されていません。",
                ephemeral=True,
            )
        if int(product.get("stock", 0)) <= 0:
            return await interaction.response.send_message(
                "❌ この商品は売り切れです。",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"{product.get('emoji', '🛒')} {product['name']}",
            description=(
                f"{product.get('description', '')}\n\n"
                f"💰 **価格**　{money(product['price'])}\n"
                f"📦 **在庫**　{product['stock']}"
            ),
            color=discord.Color(config["design"].get("color", 0x8B5CF6)),
        )

        image_url = product.get("image_url", "")
        if image_url.startswith("http"):
            embed.set_image(url=image_url)

        await interaction.response.send_message(
            embed=embed,
            view=ProductDetailView(self.product_id),
            ephemeral=True,
        )


class ProductPersistentButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"kira:buy:(?P<pid>[A-Za-z0-9_-]{1,64})",
):
    """古い販売パネルに残っている商品ボタンも再起動後に復元する。"""

    def __init__(self, item, pid):
        super().__init__(item)
        self.product_id = pid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(item, match["pid"])

    async def callback(self, interaction: discord.Interaction):
        product = find_product(self.product_id)
        if not product or not product.get("enabled", True):
            return await interaction.response.send_message(
                "❌ この商品は現在販売されていません。",
                ephemeral=True,
            )
        if int(product.get("stock", 0)) <= 0:
            return await interaction.response.send_message(
                "❌ この商品は売り切れです。",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"{product.get('emoji', '🛒')} {product['name']}",
            description=(
                f"{product.get('description', '')}\n\n"
                f"💰 **価格**　{money(product['price'])}\n"
                f"📦 **在庫**　{product['stock']}"
            ),
            color=discord.Color(config["design"].get("color", 0x8B5CF6)),
        )
        if product.get("image_url", "").startswith("http"):
            embed.set_image(url=product["image_url"])

        await interaction.response.send_message(
            embed=embed,
            view=ProductDetailView(self.product_id),
            ephemeral=True,
        )


class ProductDetailView(discord.ui.View):
    def __init__(self, product_id):
        super().__init__(timeout=120)
        self.product_id = product_id

    @discord.ui.button(label="購入する", emoji="🛒", style=discord.ButtonStyle.success)
    async def buy(self, interaction, button):
        product = find_product(self.product_id)
        if not product or int(product.get("stock", 0)) <= 0:
            return await interaction.response.send_message(
                "❌ 売り切れです。",
                ephemeral=True,
            )
        await interaction.response.send_modal(
            PayPayModal(self.product_id)
        )

    @discord.ui.button(label="閉じる", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def close(self, interaction, button):
        await interaction.response.edit_message(
            content="閉じました。",
            embed=None,
            view=None,
        )



class PayPayModal(discord.ui.Modal, title="💳 PayPay送金URL"):
    paypay_url = discord.ui.TextInput(
        label="PayPay送金URL",
        placeholder="https://pay.paypay.ne.jp/...",
        required=True,
        max_length=1000,
    )

    def __init__(self, product_id):
        super().__init__()
        self.product_id = product_id

    async def on_submit(self, interaction):
        # Discordの3秒制限対策として、最初に応答を確定。
        await interaction.response.defer(ephemeral=True, thinking=True)

        guild = interaction.guild
        buyer = interaction.user
        if guild is None or not isinstance(buyer, discord.Member):
            await interaction.followup.send(
                "❌ サーバー内でのみ購入できます。",
                ephemeral=True,
            )
            return

        url = str(self.paypay_url.value).strip()
        if not re.match(r"^https?://", url, re.I):
            await interaction.followup.send(
                "❌ URL形式が正しくありません。",
                ephemeral=True,
            )
            return

        async with purchase_lock:
            product = find_product(self.product_id)
            if not product or not product.get("enabled", True):
                await interaction.followup.send(
                    "❌ この商品は販売停止になりました。",
                    ephemeral=True,
                )
                return

            stock = int(product.get("stock", 0))
            if stock <= 0:
                await interaction.followup.send(
                    "❌ 売り切れになりました。",
                    ephemeral=True,
                )
                return

            oid = next_order_id()
            order = {
                "id": oid,
                "guild_id": guild.id,
                "buyer_id": buyer.id,
                "buyer_name": str(buyer),
                "product_id": product["id"],
                "product_name": product["name"],
                "price": int(product["price"]),
                "paypay_url": url,
                "status": "pending",
                "created_at": now_iso(),
                "ticket_channel_id": 0,
                "cancelled_stock_returned": False,
            }

            product["stock"] = stock - 1
            orders[oid] = order
            save_json(PRODUCTS_FILE, products)
            save_json(ORDERS_FILE, orders)

        await update_purchase_panel()

        ticket = None
        ticket_error = None
        try:
            ticket = await create_ticket(order, guild, buyer)
        except Exception as e:
            ticket_error = str(e)
            print(f"[PURCHASE] 専用チャット作成失敗 #{oid}: {e}")

        notify_error = None
        try:
            order_channel = await get_or_create_order_channel(guild)
            await order_channel.send(
                embed=order_embed(order),
                view=OrderAdminView(oid),
            )
        except Exception as e:
            notify_error = str(e)
            print(f"[PURCHASE] 注文通知送信失敗 #{oid}: {e}")

        try:
            await buyer.send(
                embed=discord.Embed(
                    title=f"🧾 注文 #{oid}",
                    description=(
                        f"**{order['product_name']}**\n"
                        f"金額: **{money(order['price'])}**\n\n"
                        "注文を受け付けました。\n"
                        "管理者の入金確認をお待ちください。"
                    ),
                    color=int(config["design"]["color"]),
                )
            )
        except discord.HTTPException:
            pass

        message = (
            f"✅ 注文 **#{oid}** を受け付けました！\n"
            f"商品: **{order['product_name']}**\n"
            f"金額: **{money(order['price'])}**"
        )
        if ticket:
            message += f"\n💬 専用チャット: {ticket.mention}"
        else:
            message += "\n⚠️ 専用チャット作成に失敗しました。管理者へ通知されています。"
        if ticket_error:
            print(f"[PURCHASE] ticket_error #{oid}: {ticket_error}")
        if notify_error:
            message += "\n⚠️ 管理通知の送信にも失敗しています。"

        await interaction.followup.send(
            message,
            ephemeral=True,
        )


# ============================================================
# 注文通知UI
# ============================================================


def order_embed(order):
    status = {
        "pending": "🟡 入金確認待ち",
        "paid": "🟢 支払い確認済み",
        "cancelled": "🔴 キャンセル",
        "completed": "🔵 完了",
    }.get(order.get("status"), order.get("status", "不明"))

    embed = discord.Embed(
        title=f"🛒 新しい注文 #{order['id']}",
        color=discord.Color.orange() if order.get("status") == "pending" else discord.Color.green(),
    )
    embed.add_field(
        name="👤 購入者",
        value=f"<@{order['buyer_id']}>",
        inline=True,
    )
    embed.add_field(
        name="📦 商品",
        value=order["product_name"],
        inline=True,
    )
    embed.add_field(
        name="💰 金額",
        value=money(order["price"]),
        inline=True,
    )
    embed.add_field(
        name="📌 状態",
        value=status,
        inline=False,
    )
    embed.add_field(
        name="💳 PayPay URL",
        value=order["paypay_url"][:1024],
        inline=False,
    )
    embed.set_footer(text=f"注文日時: {order['created_at']}")
    return embed


class OrderPaidButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(
            label="支払い確認",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"kira:order:paid:{order_id}",
        )
        self.order_id = order_id

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return

        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return
        if order.get("status") in ("cancelled", "completed"):
            await interaction.response.send_message("❌ この注文はすでに処理済みです。", ephemeral=True)
            return

        order["status"] = "paid"
        order["paid_at"] = now_iso()
        save_json(ORDERS_FILE, orders)

        await interaction.response.edit_message(
            embed=order_embed(order),
            view=ProcessedOrderView(),
        )

        try:
            buyer = await interaction.client.fetch_user(int(order["buyer_id"]))
            await buyer.send(f"✅ 注文 #{self.order_id} の支払いを確認しました。")
        except discord.HTTPException:
            pass


class OrderCancelButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(
            label="キャンセル",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=f"kira:order:cancel:{order_id}",
        )
        self.order_id = order_id

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return

        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return
        if order.get("status") in ("cancelled", "completed"):
            await interaction.response.send_message("❌ この注文はすでに処理済みです。", ephemeral=True)
            return

        if not order.get("cancelled_stock_returned", False):
            product = find_product(order.get("product_id"))
            if product:
                product["stock"] = int(product.get("stock", 0)) + 1
                save_json(PRODUCTS_FILE, products)
            order["cancelled_stock_returned"] = True

        order["status"] = "cancelled"
        order["cancelled_at"] = now_iso()
        save_json(ORDERS_FILE, orders)

        await update_purchase_panel()
        await interaction.response.edit_message(
            embed=order_embed(order),
            view=ProcessedOrderView(),
        )


class OrderAdminView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.add_item(OrderPaidButton(order_id))
        self.add_item(OrderCancelButton(order_id))

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True


# ============================================================
# Ticket UI
# ============================================================

class TicketArchiveButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(
            label="履歴として保存",
            emoji="🗃️",
            style=discord.ButtonStyle.primary,
            custom_id=f"kira:ticket:archive:{order_id}",
        )
        self.order_id = order_id

    async def callback(self, interaction):
        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return

        if not (
            is_admin(interaction.user)
            or interaction.user.id == int(order["buyer_id"])
        ):
            await interaction.response.send_message("🔒 権限がありません。", ephemeral=True)
            return

        try:
            category = await get_or_create_category(
                interaction.guild,
                "📁 購入履歴",
                "archive_category_id",
            )
            await interaction.channel.edit(
                category=category,
                name=f"history-kira-{self.order_id}",
            )
            await interaction.response.send_message(
                "🗃️ 履歴として保存しました。",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ 履歴保存に失敗しました: `{e}`",
                ephemeral=True,
            )


class TicketDeleteButton(discord.ui.Button):
    def __init__(self, order_id):
        super().__init__(
            label="チャット削除",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            custom_id=f"kira:ticket:delete:{order_id}",
        )
        self.order_id = order_id

    async def callback(self, interaction):
        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return

        if not (
            is_admin(interaction.user)
            or interaction.user.id == int(order["buyer_id"])
        ):
            await interaction.response.send_message("🔒 権限がありません。", ephemeral=True)
            return

        await interaction.response.send_message(
            "🗑️ 専用チャットを削除します。",
            ephemeral=True,
        )
        await asyncio.sleep(1)
        try:
            await interaction.channel.delete(
                reason=f"注文 #{self.order_id} 専用チャット削除"
            )
        except discord.HTTPException as e:
            print(f"[TICKET DELETE] {e}")


class TicketView(discord.ui.View):
    def __init__(self, order_id):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.add_item(TicketArchiveButton(order_id))
        self.add_item(TicketDeleteButton(order_id))

    async def interaction_check(self, interaction):
        order = orders.get(self.order_id)
        if not order:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return False

        if not (
            is_admin(interaction.user)
            or interaction.user.id == int(order["buyer_id"])
        ):
            await interaction.response.send_message("🔒 権限がありません。", ephemeral=True)
            return False
        return True


# ============================================================
# 商品管理
# ============================================================

class ProductModal(discord.ui.Modal, title="➕ 商品追加"):
    name = discord.ui.TextInput(label="商品名", max_length=80)
    price = discord.ui.TextInput(label="価格", placeholder="500")
    stock = discord.ui.TextInput(label="在庫数", placeholder="10")
    emoji = discord.ui.TextInput(label="絵文字（通常/カスタム）", required=False, default="🛒", max_length=100)
    description = discord.ui.TextInput(
        label="説明",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    async def on_submit(self, interaction):
        try:
            price = int(str(self.price.value).replace(",", ""))
            stock = int(str(self.stock.value))
            if price <= 0 or stock < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ 価格は1以上、在庫は0以上の数字で入力してください。",
                ephemeral=True,
            )
            return

        pid = re.sub(r"[^a-z0-9_-]", "-", str(self.name.value).lower())[:30]
        pid = pid or f"product-{len(products)+1}"
        if find_product(pid):
            pid = f"{pid}-{len(products)+1}"

        products.append(
            {
                "id": pid,
                "name": str(self.name.value),
                "description": str(self.description.value),
                "price": price,
                "stock": stock,
                "emoji": str(self.emoji.value) or "🛒",
                "image_url": "",
                "enabled": True,
            }
        )
        save_json(PRODUCTS_FILE, products)
        await update_purchase_panel()
        await interaction.response.send_message(
            f"✅ 商品を追加しました。\n商品ID: `{pid}`",
            ephemeral=True,
        )


class ProductEditModal(discord.ui.Modal, title="✏️ 商品編集"):
    def __init__(self, pid):
        super().__init__()
        self.pid = pid
        p = find_product(pid)
        self.name = discord.ui.TextInput(label="商品名", default=p["name"], max_length=80)
        self.price = discord.ui.TextInput(label="価格", default=str(p["price"]))
        self.stock = discord.ui.TextInput(label="在庫", default=str(p["stock"]))
        self.emoji = discord.ui.TextInput(label="絵文字（通常/カスタム）", default=p.get("emoji", "🛒"), max_length=100)
        self.description = discord.ui.TextInput(
            label="説明",
            default=p.get("description", ""),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500,
        )
        for item in [self.name, self.price, self.stock, self.emoji, self.description]:
            self.add_item(item)

    async def on_submit(self, interaction):
        p = find_product(self.pid)
        if not p:
            await interaction.response.send_message("❌ 商品がありません。", ephemeral=True)
            return
        try:
            price = int(str(self.price.value).replace(",", ""))
            stock = int(str(self.stock.value))
            if price <= 0 or stock < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 価格/在庫が正しくありません。", ephemeral=True)
            return

        p["name"] = str(self.name.value)
        p["price"] = price
        p["stock"] = stock
        p["emoji"] = str(self.emoji.value) or "🛒"
        p["description"] = str(self.description.value)
        save_json(PRODUCTS_FILE, products)
        await update_purchase_panel()
        await interaction.response.send_message("✅ 商品を更新しました。", ephemeral=True)


class ProductSelect(discord.ui.Select):
    def __init__(self, mode):
        self.mode = mode
        options = [
            discord.SelectOption(
                label=p["name"][:100],
                value=p["id"],
                description=f"{money(p['price'])} / 在庫 {p['stock']}",
            )
            for p in products[:25]
        ]
        super().__init__(
            placeholder="商品を選択",
            options=options,
        )

    async def callback(self, interaction):
        pid = self.values[0]
        if self.mode == "edit":
            await interaction.response.send_modal(ProductEditModal(pid))
            return

        if self.mode == "delete":
            p = find_product(pid)
            if p:
                products.remove(p)
                save_json(PRODUCTS_FILE, products)
                await update_purchase_panel()
                await interaction.response.send_message(
                    f"🗑️ `{p['name']}` を削除しました。",
                    ephemeral=True,
                )
            return

        if self.mode == "stock":
            await interaction.response.send_modal(StockModal(pid))
            return

        if self.mode == "toggle":
            product = find_product(pid)
            if not product:
                return await interaction.response.send_message("❌ 商品がありません。", ephemeral=True)
            product["enabled"] = not product.get("enabled", True)
            save_json(PRODUCTS_FILE, products)
            await update_purchase_panel()
            state = "販売中" if product["enabled"] else "販売停止"
            await interaction.response.send_message(
                f"✅ `{product['name']}` を **{state}** にしました。",
                ephemeral=True,
            )


class ProductSelectView(discord.ui.View):
    def __init__(self, mode):
        super().__init__(timeout=180)
        if products:
            self.add_item(ProductSelect(mode))


class StockModal(discord.ui.Modal, title="📦 在庫変更"):
    stock = discord.ui.TextInput(label="新しい在庫数", placeholder="10")

    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    async def on_submit(self, interaction):
        p = find_product(self.pid)
        if not p:
            await interaction.response.send_message("❌ 商品がありません。", ephemeral=True)
            return
        try:
            value = int(str(self.stock.value))
            if value < 0:
                raise ValueError
        except ValueError:
            await interaction.response.send_message("❌ 0以上の数字を入力してください。", ephemeral=True)
            return

        p["stock"] = value
        save_json(PRODUCTS_FILE, products)
        await update_purchase_panel()
        await interaction.response.send_message("✅ 在庫を変更しました。", ephemeral=True)


class ProductAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="商品追加", emoji="➕", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction, button):
        await interaction.response.send_modal(ProductModal())

    @discord.ui.button(label="商品編集", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "編集する商品を選択してください。",
            view=ProductSelectView("edit"),
            ephemeral=True,
        )

    @discord.ui.button(label="在庫変更", emoji="📦", style=discord.ButtonStyle.secondary, row=0)
    async def stock(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "在庫を変更する商品を選択してください。",
            view=ProductSelectView("stock"),
            ephemeral=True,
        )

    @discord.ui.button(label="販売ON/OFF", emoji="🔘", style=discord.ButtonStyle.secondary, row=1)
    async def toggle(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "販売状態を変更する商品を選択してください。",
            view=ProductSelectView("toggle"),
            ephemeral=True,
        )

    @discord.ui.button(label="商品削除", emoji="🗑️", style=discord.ButtonStyle.danger, row=0)
    async def delete(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "削除する商品を選択してください。",
            view=ProductSelectView("delete"),
            ephemeral=True,
        )

    @discord.ui.button(label="画像/GIF", emoji="🖼️", style=discord.ButtonStyle.secondary, row=1)
    async def image(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "画像/GIFを設定する商品を選択してください。",
            view=ProductMediaProductSelectView(),
            ephemeral=True,
        )

    @discord.ui.button(label="商品プレビュー", emoji="👁️", style=discord.ButtonStyle.secondary, row=1)
    async def preview(self, interaction, button):
        if not products:
            return await interaction.response.send_message("商品がありません。", ephemeral=True)
        await interaction.response.send_message(
            "プレビューする商品を選択してください。",
            view=ProductPreviewSelectView(),
            ephemeral=True,
        )



# ============================================================
# デザイン管理
# ============================================================

class DesignTextModal(discord.ui.Modal, title="✏️ 販売機テキスト"):
    def __init__(self):
        super().__init__()
        d = config["design"]
        self.title_text = discord.ui.TextInput(
            label="タイトル",
            default=d.get("title", "🛒 キラの自動販売機"),
            max_length=256,
        )
        self.subtitle = discord.ui.TextInput(
            label="サブタイトル",
            default=d.get("subtitle", ""),
            max_length=256,
        )
        self.description = discord.ui.TextInput(
            label="説明",
            default=d.get("description", ""),
            style=discord.TextStyle.paragraph,
            max_length=1000,
        )
        self.notice = discord.ui.TextInput(
            label="お知らせ",
            default=d.get("notice", ""),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000,
        )
        self.footer = discord.ui.TextInput(
            label="フッター",
            default=d.get("footer", ""),
            required=False,
            max_length=256,
        )
        for item in (
            self.title_text,
            self.subtitle,
            self.description,
            self.notice,
            self.footer,
        ):
            self.add_item(item)

    async def on_submit(self, interaction):
        d = config["design"]
        d["title"] = str(self.title_text.value)
        d["subtitle"] = str(self.subtitle.value)
        d["description"] = str(self.description.value)
        d["notice"] = str(self.notice.value)
        d["footer"] = str(self.footer.value)
        save_json(CONFIG_FILE, config)
        await update_purchase_panel()
        await interaction.response.send_message("✅ デザインを保存しました。", ephemeral=True)


class ColorModal(discord.ui.Modal, title="🎨 色設定"):
    def __init__(self):
        super().__init__()
        current = int(config["design"].get("color", 0x8B5CF6))
        self.hex_color = discord.ui.TextInput(
            label="16進カラー",
            placeholder="#8B5CF6",
            default=f"#{current:06X}",
        )
        self.add_item(self.hex_color)

    async def on_submit(self, interaction):
        value = str(self.hex_color.value).strip().replace("#", "")
        try:
            number = int(value, 16)
            if number < 0 or number > 0xFFFFFF:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ `#8B5CF6` のような形式で入力してください。",
                ephemeral=True,
            )
            return

        config["design"]["color"] = number
        save_json(CONFIG_FILE, config)
        await update_purchase_panel()
        await interaction.response.send_message("✅ 色を変更しました。", ephemeral=True)


class BannerModal(discord.ui.Modal, title="🖼️ バナー/GIF"):
    def __init__(self):
        super().__init__()
        self.url = discord.ui.TextInput(
            label="画像/GIF URL",
            placeholder="https://...",
            default=config["design"].get("banner_url", ""),
            required=False,
            max_length=1000,
        )
        self.add_item(self.url)

    async def on_submit(self, interaction):
        value = str(self.url.value).strip()
        if value and not re.match(r"^https?://", value, re.I):
            await interaction.response.send_message(
                "❌ http(s) のURLを入力してください。",
                ephemeral=True,
            )
            return

        config["design"]["banner_url"] = value
        save_json(CONFIG_FILE, config)
        await update_purchase_panel()
        await interaction.response.send_message("✅ バナー/GIFを保存しました。", ephemeral=True)


class DesignPresetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="現在のデザインを維持", emoji="✅", style=discord.ButtonStyle.success, row=0)
    async def keep(self, interaction, button):
        await interaction.response.send_message(
            "✅ 現在のデザインを維持します。",
            ephemeral=True,
        )

    @discord.ui.button(label="紫", emoji="🟣", style=discord.ButtonStyle.secondary, row=0)
    async def purple(self, interaction, button):
        config["design"]["color"] = 0x8B5CF6
        save_json(CONFIG_FILE, config)
        await update_purchase_panel()
        await interaction.response.send_message("🟣 紫にしました。", ephemeral=True)

    @discord.ui.button(label="青", emoji="🔵", style=discord.ButtonStyle.secondary, row=0)
    async def blue(self, interaction, button):
        config["design"]["color"] = 0x5865F2
        save_json(CONFIG_FILE, config)
        await update_purchase_panel()
        await interaction.response.send_message("🔵 青にしました。", ephemeral=True)


class DesignView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="文字を設定", emoji="✏️", style=discord.ButtonStyle.primary, row=0)
    async def text(self, interaction, button):
        await interaction.response.send_modal(DesignTextModal())

    @discord.ui.button(label="色を設定", emoji="🎨", style=discord.ButtonStyle.secondary, row=0)
    async def color(self, interaction, button):
        await interaction.response.send_modal(ColorModal())

    @discord.ui.button(label="バナー/GIF", emoji="🖼️", style=discord.ButtonStyle.secondary, row=0)
    async def banner(self, interaction, button):
        await interaction.response.send_modal(BannerModal())

    @discord.ui.button(label="かんたん色変更", emoji="✨", style=discord.ButtonStyle.secondary, row=1)
    async def presets(self, interaction, button):
        await interaction.response.send_message(
            "かんたんな色設定です。現在の他のデザインは変更しません。",
            view=DesignPresetView(),
            ephemeral=True,
        )

    @discord.ui.button(label="プレビュー", emoji="👁️", style=discord.ButtonStyle.success, row=1)
    async def preview(self, interaction, button):
        banner = config["design"].get("banner_url", "")
        await interaction.response.send_message(
            content=banner if banner.startswith("http") else None,
            embed=design_embed(),
            view=PurchaseView(),
            ephemeral=True,
        )



# ============================================================
# チャンネル / メディア
# ============================================================

class ChannelIdModal(discord.ui.Modal):
    def __init__(self, key, title):
        super().__init__(title=title)
        self.key = key
        self.value = discord.ui.TextInput(
            label="チャンネルID",
            placeholder="123456789012345678",
        )
        self.add_item(self.value)

    async def on_submit(self, interaction):
        try:
            cid = int(str(self.value.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ チャンネルIDが正しくありません。", ephemeral=True)
            return

        ch = interaction.guild.get_channel(cid)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message("❌ そのチャンネルが見つかりません。", ephemeral=True)
            return

        perms = ch.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.response.send_message("❌ Botがそのチャンネルを使用できません。", ephemeral=True)
            return

        config[self.key] = cid
        save_json(CONFIG_FILE, config)
        await interaction.response.send_message(
            f"✅ {ch.mention} を設定しました。",
            ephemeral=True,
        )


class ChannelSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="購入チャンネルを設定", emoji="🛒", style=discord.ButtonStyle.primary)
    async def purchase(self, interaction, button):
        await interaction.response.send_modal(
            ChannelIdModal("purchase_channel_id", "購入チャンネルID")
        )

    @discord.ui.button(label="注文通知を作成/確認", emoji="📦", style=discord.ButtonStyle.success)
    async def order(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ch = await get_or_create_order_channel(interaction.guild)
            await interaction.followup.send(
                f"✅ 注文通知チャンネル: {ch.mention}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ 注文通知チャンネル作成失敗: `{e}`",
                ephemeral=True,
            )

    @discord.ui.button(label="メディアチャンネル作成", emoji="🎞️", style=discord.ButtonStyle.secondary)
    async def media(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        try:
            existing = next(
                (c for c in guild.text_channels if c.name == "vending-media"),
                None,
            )
            if existing:
                await secure_private_channel(existing, guild)
                config["media_channel_id"] = existing.id
                save_json(CONFIG_FILE, config)
                await interaction.followup.send(
                    f"✅ メディアチャンネル: {existing.mention}",
                    ephemeral=True,
                )
                return

            category = None
            try:
                category = await get_or_create_category(
                    guild,
                    "🔒 管理者エリア",
                    "admin_category_id",
                )
            except Exception:
                pass

            try:
                ch = await guild.create_text_channel(
                    "vending-media",
                    category=category,
                    reason=f"{BOT_NAME} メディア保管チャンネル",
                )
            except discord.Forbidden:
                ch = await guild.create_text_channel(
                    "vending-media",
                    reason=f"{BOT_NAME} メディア保管チャンネル再試行",
                )

            await secure_private_channel(ch, guild)
            config["media_channel_id"] = ch.id
            save_json(CONFIG_FILE, config)
            await interaction.followup.send(
                f"✅ メディアチャンネルを作成しました: {ch.mention}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ メディアチャンネル作成失敗: `{e}`",
                ephemeral=True,
            )


class MediaView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="メディアチャンネルを開く", emoji="🎞️", style=discord.ButtonStyle.primary)
    async def open_media(self, interaction, button):
        ch = interaction.guild.get_channel(int(config.get("media_channel_id", 0) or 0))
        if isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(
                f"ここにGIF/画像をドラッグ＆ドロップしてください: {ch.mention}\n"
                "アップロードされた画像/GIFはメディアライブラリに自動登録されます。",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "❌ 先にチャンネル設定からメディアチャンネルを作成してください。",
                ephemeral=True,
            )

    @discord.ui.button(label="保存済みメディア", emoji="📚", style=discord.ButtonStyle.secondary)
    async def library(self, interaction, button):
        if not config.get("media_library", []):
            return await interaction.response.send_message("❌ まだ画像/GIFがありません。メディアチャンネルへアップロードしてください。", ephemeral=True)
        await interaction.response.send_message(
            "バナー/GIFに使うメディアを選択してください。",
            view=MediaLibraryView("banner"),
            ephemeral=True,
        )

    @discord.ui.button(label="バナーURL設定", emoji="🖼️", style=discord.ButtonStyle.secondary)
    async def banner(self, interaction, button):
        await interaction.response.send_modal(BannerModal())


# ============================================================
# メディアライブラリ / 商品画像設定
# ============================================================

class MediaLibrarySelect(discord.ui.Select):
    def __init__(self, mode, product_id=0):
        self.mode = mode
        self.product_id = product_id
        library = config.get("media_library", [])
        options = []
        for i, item in enumerate(library[:25]):
            options.append(
                discord.SelectOption(
                    label=str(item.get("name", f"media-{i+1}"))[:100],
                    description=str(item.get("type", "image"))[:100],
                    value=str(i),
                )
            )
        if not options:
            options = [discord.SelectOption(label="メディアがありません", value="none")]
        super().__init__(
            placeholder="使用する画像/GIFを選択",
            options=options,
        )

    async def callback(self, interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("❌ メディアがありません。", ephemeral=True)
        library = config.get("media_library", [])
        item = library[int(self.values[0])]
        url = item.get("url", "")
        if self.mode == "banner":
            config["design"]["banner_url"] = url
            save_json(CONFIG_FILE, config)
            await update_purchase_panel()
            await interaction.response.send_message("✅ バナー/GIFに設定しました。", ephemeral=True)
            return
        product = find_product(self.product_id)
        if not product:
            return await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
        product["image_url"] = url
        save_json(PRODUCTS_FILE, products)
        await interaction.response.send_message(
            f"✅ `{product['name']}` の画像/GIFを設定しました。",
            ephemeral=True,
        )


class MediaLibraryView(discord.ui.View):
    def __init__(self, mode, product_id=0):
        super().__init__(timeout=300)
        self.add_item(MediaLibrarySelect(mode, product_id))


class ProductMediaProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=p["name"][:100],
                value=p["id"],
                description="メディアを設定",
            )
            for p in products[:25]
        ]
        super().__init__(placeholder="商品を選択", options=options)

    async def callback(self, interaction):
        await interaction.response.send_message(
            "使用する画像/GIFを選択してください。",
            view=MediaLibraryView("product", self.values[0]),
            ephemeral=True,
        )


class ProductMediaProductSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        if products:
            self.add_item(ProductMediaProductSelect())


class ProductPreviewSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=p["name"][:100],
                value=p["id"],
            )
            for p in products[:25]
        ]
        super().__init__(placeholder="プレビューする商品を選択", options=options)

    async def callback(self, interaction):
        p = find_product(self.values[0])
        if not p:
            return await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
        embed = discord.Embed(
            title=f"{p.get('emoji', '🛒')} {p['name']}",
            description=(
                f"{p.get('description', '')}\n\n"
                f"💰 {money(p['price'])}\n"
                f"📦 在庫 {p['stock']}"
            ),
            color=int(config["design"]["color"]),
        )
        if p.get("image_url", "").startswith("http"):
            embed.set_image(url=p["image_url"])
        await interaction.response.send_message(
            embed=embed,
            view=ProductDetailView(p["id"]),
            ephemeral=True,
        )


class ProductPreviewSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        if products:
            self.add_item(ProductPreviewSelect())


# ============================================================
# 管理画面
# ============================================================

async def find_purchase_channel(guild):
    cid = int(config.get("purchase_channel_id", 0) or 0)
    if cid:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.TextChannel):
            return ch

    ch = next(
        (c for c in guild.text_channels if c.name == "購入"),
        None,
    )
    if isinstance(ch, discord.TextChannel):
        config["purchase_channel_id"] = ch.id
        save_json(CONFIG_FILE, config)
        return ch
    return None


class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="販売機を設置/更新", emoji="🛒", style=discord.ButtonStyle.primary, row=0, custom_id="kira:admin:deploy")
    async def deploy(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        ch = await find_purchase_channel(interaction.guild)
        if not ch:
            await interaction.followup.send(
                "❌ `#購入` が見つかりません。先に #購入 チャンネルを作成してください。",
                ephemeral=True,
            )
            return

        perms = ch.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            await interaction.followup.send(
                "❌ Botが #購入 に投稿できません。",
                ephemeral=True,
            )
            return

        banner = config["design"].get("banner_url", "")
        content = banner if banner.startswith("http") else None

        existing = None
        mid = int(config.get("panel_message_id", 0) or 0)
        if mid:
            try:
                existing = await ch.fetch_message(mid)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                existing = None

        if existing:
            await existing.edit(
                content=content,
                embed=design_embed(),
                view=PurchaseView(),
            )
            msg = existing
        else:
            msg = await ch.send(
                content=content,
                embed=design_embed(),
                view=PurchaseView(),
            )

        config["panel_message_id"] = msg.id
        config["panel_channel_id"] = ch.id
        save_json(CONFIG_FILE, config)

        await interaction.followup.send(
            f"✅ {ch.mention} の販売機を設置/更新しました。",
            ephemeral=True,
        )

    @discord.ui.button(label="商品管理", emoji="📦", style=discord.ButtonStyle.secondary, row=0, custom_id="kira:admin:products")
    async def product_manage(self, interaction, button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📦 商品管理",
                description="追加・編集・削除・在庫変更を選択してください。",
                color=int(config["design"]["color"]),
            ),
            view=ProductAdminView(),
            ephemeral=True,
        )

    @discord.ui.button(label="デザイン", emoji="🎨", style=discord.ButtonStyle.secondary, row=0, custom_id="kira:admin:design")
    async def design(self, interaction, button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎨 デザイン設定",
                description="販売機の見た目を変更できます。",
                color=int(config["design"]["color"]),
            ),
            view=DesignView(),
            ephemeral=True,
        )

    @discord.ui.button(label="チャンネル設定", emoji="⚙️", style=discord.ButtonStyle.secondary, row=1, custom_id="kira:admin:channels")
    async def channels(self, interaction, button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚙️ チャンネル設定",
                description=(
                    f"🛒 購入: {channel_mention(interaction.guild, config.get('purchase_channel_id'))}\n"
                    f"📦 注文通知: {channel_mention(interaction.guild, config.get('order_channel_id'))}\n"
                    f"💬 専用チャットカテゴリ: {category_mention(interaction.guild, config.get('ticket_category_id'))}\n"
                    f"🎞️ メディア: {channel_mention(interaction.guild, config.get('media_channel_id'))}"
                ),
                color=int(config["design"]["color"]),
            ),
            view=ChannelSettingsView(),
            ephemeral=True,
        )

    @discord.ui.button(label="メディア/GIF", emoji="🎞️", style=discord.ButtonStyle.secondary, row=1, custom_id="kira:admin:media")
    async def media(self, interaction, button):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎞️ メディア管理",
                description=(
                    "管理者専用メディアチャンネルにGIF/画像をドラッグ＆ドロップできます。\n\n"
                    "Discordのメッセージに本物の背景画像を設定する機能はないため、"
                    "バナー/GIF・商品画像・Embedを組み合わせて見た目を作ります。"
                ),
                color=int(config["design"]["color"]),
            ),
            view=MediaView(),
            ephemeral=True,
        )


# ============================================================
# パネル更新
# ============================================================

async def update_purchase_panel():
    cid = int(config.get("panel_channel_id", 0) or config.get("purchase_channel_id", 0) or 0)
    mid = int(config.get("panel_message_id", 0) or 0)
    if not cid or not mid:
        return False

    try:
        channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
        if not isinstance(channel, discord.TextChannel):
            return False
        message = await channel.fetch_message(mid)
        banner = config["design"].get("banner_url", "")
        content = banner if banner.startswith("http") else None
        await message.edit(
            content=content,
            embed=design_embed(),
            view=PurchaseView(),
        )
        return True
    except Exception as e:
        print(f"[PANEL] 更新失敗: {e}")
        return False


# ============================================================
# Bot / Events
# ============================================================

class KiraBot(commands.Bot):
    async def setup_hook(self):
        # 現在のパネル用View
        self.add_view(PurchaseView())
        self.add_view(AdminPanelView())

        # 古い販売パネルの購入ボタンを再起動後も処理
        try:
            self.add_dynamic_items(ProductPersistentButton)
        except Exception as e:
            print(f"[STARTUP] ProductPersistentButton登録失敗: {e}")

        for oid, order in orders.items():
            try:
                self.add_view(OrderAdminView(oid))
                if order.get("ticket_channel_id"):
                    self.add_view(TicketView(oid))
            except Exception as e:
                print(f"[STARTUP] 永続View登録失敗 #{oid}: {e}")

        await self.add_cog(AdminCog(self))

        try:
            synced = await self.tree.sync()
            print(f"✅ スラッシュコマンドを {len(synced)} 個同期しました")
        except Exception as e:
            print(f"❌ コマンド同期失敗: {e}")


bot = KiraBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="admin",
        description="キラの自動販売機 管理パネル",
    )
    @app_commands.default_permissions(administrator=True)
    async def admin(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="⚙️ キラの自動販売機 — 管理パネル",
            description=(
                "ここから販売機・商品・デザイン・メディア・チャンネルを管理できます。\n\n"
                "🔒 この画面は管理者にだけ表示されます。"
            ),
            color=int(config["design"]["color"]),
        )
        await interaction.response.send_message(
            embed=embed,
            view=AdminPanelView(),
            ephemeral=True,
        )

    @app_commands.command(
        name="setup_vending",
        description="販売機の初期セットアップ",
    )
    @app_commands.default_permissions(administrator=True)
    async def setup_vending(self, interaction):
        if not is_admin(interaction.user):
            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild

        try:
            if not config.get("guild_id"):
                config["guild_id"] = guild.id
                save_json(CONFIG_FILE, config)

            order_channel = await get_or_create_order_channel(guild)
            ticket_category = await get_or_create_ticket_category(guild)
            purchase = await find_purchase_channel(guild)

            await interaction.followup.send(
                "✅ 初期セットアップ完了\n\n"
                f"📦 注文通知: {order_channel.mention}\n"
                f"💬 専用チャットカテゴリ: `{ticket_category.name}`\n"
                f"🛒 購入チャンネル: {purchase.mention if purchase else '未設定'}\n\n"
                "管理画面の `販売機を設置/更新` から販売機を設置してください。",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ セットアップ失敗: `{e}`",
                ephemeral=True,
            )


@bot.event
async def on_ready():
    print("=" * 55)
    print(f"✅ ログインしました: {bot.user}")
    print("🛒 キラの自動販売機 起動完了")
    print("=" * 55)

    if config.get("guild_id"):
        guild = bot.get_guild(int(config["guild_id"]))
        if guild:
            try:
                await get_or_create_order_channel(guild)
            except Exception as e:
                print(f"[STARTUP] 注文通知チャンネル確認失敗: {e}")


@bot.event
async def on_guild_join(guild):
    if not config.get("guild_id"):
        config["guild_id"] = guild.id
        save_json(CONFIG_FILE, config)


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    media_id = int(config.get("media_channel_id", 0) or 0)
    if media_id and message.channel.id == media_id and is_admin(message.author):
        library = config.setdefault("media_library", [])
        changed = False

        for attachment in message.attachments:
            filename = attachment.filename.lower()
            is_image = bool(
                (attachment.content_type and attachment.content_type.startswith("image/"))
                or filename.endswith((".gif", ".png", ".jpg", ".jpeg", ".webp"))
            )
            if not is_image:
                continue

            # 同じURLは重複登録しない。
            if not any(item.get("url") == attachment.url for item in library):
                library.insert(
                    0,
                    {
                        "name": attachment.filename,
                        "url": attachment.url,
                        "type": attachment.content_type or "image",
                        "created_at": now_iso(),
                    },
                )
                changed = True

        if changed:
            del library[50:]
            save_json(CONFIG_FILE, config)
            print(f"[MEDIA] {message.author} の画像/GIFを保存しました。")

    await bot.process_commands(message)


@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    print(f"[BOT ERROR] event={event}")
    traceback.print_exc()


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN が設定されていません。")
    bot.run(token)
