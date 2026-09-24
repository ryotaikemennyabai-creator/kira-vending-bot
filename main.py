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


# ============================================================
# JSON
# ============================================================

def save_json(path, data):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(tmp, path)


def load_json(path, default):
    if not os.path.exists(path):
        save_json(path, default)

        return json.loads(
            json.dumps(
                default,
                ensure_ascii=False
            )
        )

    try:

        with open(
            path,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        save_json(
            path,
            default
        )

        return json.loads(
            json.dumps(
                default,
                ensure_ascii=False
            )
        )


config = load_json(
    CONFIG_FILE,
    DEFAULT_CONFIG
)

products = load_json(
    PRODUCTS_FILE,
    DEFAULT_PRODUCTS
)

orders = load_json(
    ORDERS_FILE,
    {}
)

if not isinstance(products, list):

    products = json.loads(
        json.dumps(
            DEFAULT_PRODUCTS,
            ensure_ascii=False
        )
    )


if not isinstance(orders, dict):

    orders = {}


for key, value in DEFAULT_CONFIG.items():

    if key not in config:

        config[key] = (
            json.loads(
                json.dumps(value)
            )
            if isinstance(value, dict)
            else value
        )


for key, value in DEFAULT_CONFIG["design"].items():

    config.setdefault(
        "design",
        {}
    ).setdefault(
        key,
        value
    )


for index, product in enumerate(products):

    if not isinstance(product, dict):

        products[index] = {
            "id": f"product-{index + 1}",
            "name": "商品",
            "description": "",
            "price": 0,
            "stock": 0,
            "emoji": "🛒",
            "image_url": "",
            "enabled": True
        }

        continue

    product.setdefault(
        "id",
        f"product-{index + 1}"
    )

    product.setdefault(
        "name",
        "商品"
    )

    product.setdefault(
        "description",
        ""
    )

    product.setdefault(
        "price",
        0
    )

    product.setdefault(
        "stock",
        0
    )

    product.setdefault(
        "emoji",
        "🛒"
    )

    product.setdefault(
        "image_url",
        ""
    )

    product.setdefault(
        "enabled",
        True
    )


save_json(
    PRODUCTS_FILE,
    products
)

save_json(
    CONFIG_FILE,
    config
)

save_json(
    ORDERS_FILE,
    orders
)


# ============================================================
# 共通
# ============================================================

purchase_lock = asyncio.Lock()


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def money(value):

    return f"¥{int(value):,}"


def is_admin(member):

    return (
        isinstance(
            member,
            discord.Member
        )
        and member.guild_permissions.administrator
    )


def find_product(product_id):

    for product in products:

        if product.get("id") == product_id:

            return product

    return None


def next_order_id():

    config["order_counter"] = (
        int(
            config.get(
                "order_counter",
                0
            )
        ) + 1
    )

    save_json(
        CONFIG_FILE,
        config
    )

    return (
        f"{config['order_counter']:05d}"
    )


def channel_mention(guild, channel_id):

    if not guild:

        return "未設定"

    try:

        channel = guild.get_channel(
            int(channel_id or 0)
        )

    except Exception:

        return "未設定"

    if isinstance(
        channel,
        discord.TextChannel
    ):

        return channel.mention

    return "未設定"


def category_mention(guild, category_id):

    if not guild:

        return "未設定"

    try:

        category = guild.get_channel(
            int(category_id or 0)
        )

    except Exception:

        return "未設定"

    if isinstance(
        category,
        discord.CategoryChannel
    ):

        return f"`{category.name}`"

    return "未設定"


# ============================================================
# Discord
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


class KiraBot(
    commands.Bot
):

    async def setup_hook(
        self
    ):

        # 永続販売パネル
        try:

            self.add_view(
                PurchaseView()
            )

            print(
                "✅ PurchaseView登録完了"
            )

        except Exception as e:

            print(
                f"❌ PurchaseView登録失敗: {repr(e)}"
            )


        # 永続管理パネル
        try:

            self.add_view(
                AdminPanelView()
            )

            print(
                "✅ AdminPanelView登録完了"
            )

        except Exception as e:

            print(
                f"❌ AdminPanelView登録失敗: {repr(e)}"
            )


        # 保存済み注文のボタンを復元
        for order_id in list(
            orders.keys()
        ):

            try:

                self.add_view(
                    OrderAdminView(
                        order_id
                    )
                )

                self.add_view(
                    TicketView(
                        order_id
                    )
                )

            except Exception as e:

                print(
                    f"[STARTUP] 注文View登録失敗 "
                    f"#{order_id}: {repr(e)}"
                )


        # Cog
        await self.add_cog(
            AdminCog(self)
        )


        # Slash Commands
        try:

            synced = await self.tree.sync()

            print(
                f"✅ スラッシュコマンドを "
                f"{len(synced)} 個同期しました"
            )

        except Exception as e:

            print(
                f"❌ コマンド同期失敗: {repr(e)}"
            )


bot = KiraBot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# ============================================================
# デザイン
# ============================================================

def design_embed():

    design = config["design"]

    embed = discord.Embed(
        title=design["title"],
        description=(
            f"**{design['subtitle']}**\n\n"
            f"{design['description']}\n\n"
            f"{design['notice']}"
        ),
        color=int(
            design["color"]
        )
    )


    active_products = [
        product
        for product in products
        if product.get(
            "enabled",
            True
        )
    ]


    if not active_products:

        embed.add_field(
            name="📦 商品",
            value=(
                "現在販売中の商品はありません。"
            ),
            inline=False
        )

    else:

        product_lines = []

        for product in active_products[:25]:

            stock = int(
                product.get(
                    "stock",
                    0
                )
            )

            if design.get(
                "show_stock",
                True
            ):

                if stock > 0:

                    stock_text = (
                        f"🟢 在庫: **{stock}**"
                    )

                else:

                    stock_text = (
                        "🔴 売り切れ"
                    )

            else:

                stock_text = (
                    "🟢 在庫あり"
                    if stock > 0
                    else
                    "🔴 売り切れ"
                )


            product_lines.append(
                f"{product.get('emoji', '🛒')} "
                f"**{product['name']}** — "
                f"{money(product['price'])}\n"
                f"{product.get('description', '')[:120]}\n"
                f"{stock_text}"
            )


        value = "\n\n".join(
            product_lines
        )

        if len(value) > 1024:

            value = value[:1000] + "\n…"


        embed.add_field(
            name="🛍️ 商品一覧",
            value=value,
            inline=False
        )


    if design.get(
        "footer"
    ):

        embed.set_footer(
            text=design["footer"]
        )


    return embed


# ============================================================
# 非公開チャンネル
# ============================================================

async def secure_private_channel(
    channel,
    guild,
    buyer=None
):

    me = guild.me

    if me is None:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )


    # 一般ユーザー
    await channel.set_permissions(
        guild.default_role,
        view_channel=False,
        reason=f"{BOT_NAME} 非公開設定"
    )


    # Bot
    await channel.set_permissions(
        me,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True,
        attach_files=True,
        manage_messages=True,
        manage_channels=True,
        reason=f"{BOT_NAME} Bot権限"
    )


    # 購入者
    if buyer is not None:

        await channel.set_permissions(
            buyer,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            reason=f"{BOT_NAME} 購入者権限"
        )


# ============================================================
# カテゴリ
# ============================================================

async def get_or_create_category(
    guild,
    name,
    config_key
):

    saved_id = int(
        config.get(
            config_key,
            0
        ) or 0
    )


    if saved_id:

        category = guild.get_channel(
            saved_id
        )

        if isinstance(
            category,
            discord.CategoryChannel
        ):

            return category


    me = guild.me

    if not me:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )


    if not me.guild_permissions.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )


    category = await guild.create_category(
        name,
        reason=f"{BOT_NAME} 自動作成"
    )


    config[
        config_key
    ] = category.id

    save_json(
        CONFIG_FILE,
        config
    )


    return category


# ============================================================
# 注文通知チャンネル
# ============================================================

async def get_or_create_order_channel(
    guild
):

    if guild is None:

        raise RuntimeError(
            "サーバー情報を取得できません。"
        )


    me = guild.me

    if not me:

        raise RuntimeError(
            "BotのMember情報を取得できません。"
        )


    if not me.guild_permissions.manage_channels:

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )


    # 保存済み
    saved_id = int(
        config.get(
            "order_channel_id",
            0
        ) or 0
    )


    if saved_id:

        channel = guild.get_channel(
            saved_id
        )

        if (
            isinstance(
                channel,
                discord.TextChannel
            )
            and channel.name
            == "注文通知"
        ):

            await secure_private_channel(
                channel,
                guild
            )

            return channel


    # 名前で復旧
    for channel in guild.text_channels:

        if channel.name == "注文通知":

            config[
                "order_channel_id"
            ] = channel.id

            save_json(
                CONFIG_FILE,
                config
            )

            await secure_private_channel(
                channel,
                guild
            )

            return channel


    # カテゴリ
    category = None

    try:

        category = await get_or_create_category(
            guild,
            "🔒 管理者エリア",
            "admin_category_id"
        )

    except Exception as e:

        print(
            "[ORDER] 管理者カテゴリ作成失敗。"
            f"直下で作成します: {repr(e)}"
        )


    # チャンネル作成
    try:

        channel = await guild.create_text_channel(
            "注文通知",
            category=category,
            topic=(
                f"{BOT_NAME} "
                "注文通知（管理者専用）"
            ),
            reason=(
                f"{BOT_NAME} "
                "注文通知チャンネル"
            )
        )

    except discord.Forbidden as e:

        if category is None:

            raise RuntimeError(
                f"注文通知チャンネル作成失敗: {e}"
            ) from e


        print(
            "[ORDER] カテゴリ付き作成失敗。"
            f"直下で再試行: {repr(e)}"
        )


        channel = await guild.create_text_channel(
            "注文通知",
            topic=(
                f"{BOT_NAME} "
                "注文通知（管理者専用）"
            ),
            reason=(
                f"{BOT_NAME} "
                "注文通知チャンネル再試行"
            )
        )


    await secure_private_channel(
        channel,
        guild
    )


    config[
        "order_channel_id"
    ] = channel.id

    save_json(
        CONFIG_FILE,
        config
    )


    # 最初のメッセージ
    try:

        await channel.send(
            embed=discord.Embed(
                title="📦 注文通知チャンネル",
                description=(
                    "このチャンネルは管理者専用です。\n"
                    "新しい注文が入るとここに通知されます。"
                ),
                color=int(
                    config["design"]["color"]
                )
            )
        )

    except discord.HTTPException as e:

        print(
            f"[ORDER] 初期メッセージ送信失敗: {repr(e)}"
        )


    return channel


# ============================================================
# 購入専用チャット
# ============================================================

async def create_ticket(
    order,
    guild,
    buyer
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


    category = None

    try:

        category = await get_or_create_category(
            guild,
            "💬 購入チャット",
            "ticket_category_id"
        )

    except Exception as e:

        print(
            "[TICKET] カテゴリ作成失敗。"
            f"直下で作成します: {repr(e)}"
        )


    name = (
        f"chat-kira-{order['id']}"
    )


    # チャンネル作成
    try:

        channel = await guild.create_text_channel(
            name,
            category=category,
            topic=(
                f"注文 #{order['id']} / "
                f"購入者 {buyer.id}"
            ),
            reason=(
                f"注文 #{order['id']} "
                "専用チャット"
            )
        )

    except discord.Forbidden as e:

        if category is None:

            raise RuntimeError(
                f"専用チャット作成失敗: {e}"
            ) from e


        print(
            "[TICKET] カテゴリ付き作成失敗。"
            f"直下で再試行: {repr(e)}"
        )


        channel = await guild.create_text_channel(
            name,
            topic=(
                f"注文 #{order['id']} / "
                f"購入者 {buyer.id}"
            ),
            reason=(
                f"注文 #{order['id']} "
                "専用チャット再試行"
            )
        )


    # 権限設定
    await secure_private_channel(
        channel,
        guild,
        buyer
    )


    # Bot権限確認
    permissions = channel.permissions_for(
        me
    )


    if not permissions.view_channel:

        raise RuntimeError(
            "専用チャットでBotが閲覧できません。"
        )


    if not permissions.send_messages:

        raise RuntimeError(
            "専用チャットでBotが送信できません。"
        )


    # 注文保存
    order[
        "ticket_channel_id"
    ] = channel.id

    save_json(
        ORDERS_FILE,
        orders
    )


    # メッセージ
    embed = discord.Embed(
        title=(
            f"💬 注文 #{order['id']} "
            "専用チャット"
        ),
        description=(
            f"**商品:** {order['product_name']}\n"
            f"**金額:** {money(order['price'])}\n"
            f"**購入者:** {buyer.mention}\n\n"
            "PayPay URLを受け取りました。\n"
            "管理者が入金確認後、注文処理を進めます。"
        ),
        color=int(
            config["design"]["color"]
        )
    )


    embed.add_field(
        name="💳 PayPay URL",
        value=order["paypay_url"][:1024],
        inline=False
    )


    embed.set_footer(
        text=f"{BOT_NAME} • #{order['id']}"
    )


    try:

        await channel.send(
            content=buyer.mention,
            embed=embed,
            view=TicketView(
                order["id"]
            ),
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True
                )
            )
        )

    except Exception as e:

        print(
            f"[TICKET] 初期メッセージ送信失敗: {repr(e)}"
        )

        raise RuntimeError(
            "専用チャットの初期メッセージ送信に失敗しました。"
        ) from e


    return channel


# ============================================================
# 自販機ボタン
# ============================================================

class PurchaseView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


        active = [
            p
            for p in products
            if p.get(
                "enabled",
                True
            )
        ]


        for product in active[:25]:

            stock = int(
                product.get(
                    "stock",
                    0
                )
            )

            button = ProductButton(
                product_id=product["id"],
                name=product.get(
                    "name",
                    "商品"
                ),
                emoji=product.get(
                    "emoji",
                    "🛒"
                ),
                sold_out=(
                    stock <= 0
                )
            )

            self.add_item(
                button
            )


class ProductButton(
    discord.ui.Button
):

    def __init__(
        self,
        product_id,
        name,
        emoji,
        sold_out=False
    ):

        super().__init__(
            label=name[:80],
            emoji=(
                emoji[:10]
                if emoji
                else
                "🛒"
            ),
            style=(
                discord.ButtonStyle.secondary
                if sold_out
                else
                discord.ButtonStyle.primary
            ),
            disabled=sold_out,
            custom_id=(
                f"kira:buy:{product_id}"
            )
        )


        self.product_id = product_id


    async def callback(
        self,
        interaction
    ):

        try:

            product = find_product(
                self.product_id
            )


            if (
                not product
                or not product.get(
                    "enabled",
                    True
                )
            ):

                await interaction.response.send_message(
                    "❌ この商品は現在販売されていません。",
                    ephemeral=True
                )

                return


            if int(
                product.get(
                    "stock",
                    0
                )
            ) <= 0:

                await interaction.response.send_message(
                    "❌ この商品は売り切れです。",
                    ephemeral=True
                )

                return


            embed = discord.Embed(
                title="🛒 購入確認",
                description=(
                    f"**{product['name']}**\n\n"
                    f"{product.get('description', '')}\n\n"
                    f"💰 価格: "
                    f"**{money(product['price'])}**\n"
                    f"📦 在庫: "
                    f"**{product['stock']}**\n\n"
                    "購入する場合は"
                    "「購入する」を押してください。"
                ),
                color=int(
                    config["design"]["color"]
                )
            )


            if product.get(
                "image_url"
            ):

                embed.set_image(
                    url=product["image_url"]
                )


            await interaction.response.send_message(
                embed=embed,
                view=ConfirmPurchaseView(
                    product["id"]
                ),
                ephemeral=True
            )


        except Exception as e:

            print(
                f"[BUY BUTTON] {repr(e)}"
            )

            try:

                if not interaction.response.is_done():

                    await interaction.response.send_message(
                        "❌ 購入ボタンの処理中にエラーが発生しました。",
                        ephemeral=True
                    )

                else:

                    await interaction.followup.send(
                        "❌ 購入ボタンの処理中にエラーが発生しました。",
                        ephemeral=True
                    )

            except Exception:

                pass


# ============================================================
# 購入確認
# ============================================================

class ConfirmPurchaseView(
    discord.ui.View
):

    def __init__(
        self,
        product_id
    ):

        super().__init__(
            timeout=120
        )

        self.product_id = product_id


    @discord.ui.button(
        label="購入する",
        emoji="🛒",
        style=discord.ButtonStyle.success
    )
    async def confirm(
        self,
        interaction,
        button
    ):

        product = find_product(
            self.product_id
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
                "❌ 売り切れになりました。",
                ephemeral=True
            )

            return


        await interaction.response.send_modal(
            PayPayModal(
                self.product_id
            )
        )


    @discord.ui.button(
        label="キャンセル",
        emoji="✖️",
        style=discord.ButtonStyle.secondary
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


# ============================================================
# PayPay Modal
# ============================================================

class PayPayModal(
    discord.ui.Modal,
    title="💳 PayPay送金URL"
):

    paypay_url = discord.ui.TextInput(
        label="PayPay送金URL",
        placeholder=(
            "https://pay.paypay.ne.jp/..."
        ),
        required=True,
        max_length=1000
    )


    def __init__(
        self,
        product_id
    ):

        super().__init__()

        self.product_id = product_id


    async def on_submit(
        self,
        interaction
    ):

        # 3秒制限対策
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        guild = interaction.guild
        buyer = interaction.user


        if (
            guild is None
            or not isinstance(
                buyer,
                discord.Member
            )
        ):

            await interaction.followup.send(
                "❌ サーバー内でのみ購入できます。",
                ephemeral=True
            )

            return


        url = str(
            self.paypay_url.value
        ).strip()


        if not re.match(
            r"^https?://",
            url,
            re.I
        ):

            await interaction.followup.send(
                "❌ URL形式が正しくありません。",
                ephemeral=True
            )

            return


        # 同時購入防止
        async with purchase_lock:

            product = find_product(
                self.product_id
            )


            if (
                not product
                or not product.get(
                    "enabled",
                    True
                )
            ):

                await interaction.followup.send(
                    "❌ この商品は販売停止になりました。",
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
                    "❌ 売り切れになりました。",
                    ephemeral=True
                )

                return


            order_id = next_order_id()


            order = {
                "id": order_id,
                "guild_id": guild.id,
                "buyer_id": buyer.id,
                "buyer_name": str(buyer),
                "product_id": product["id"],
                "product_name": product["name"],
                "price": int(
                    product["price"]
                ),
                "paypay_url": url,
                "status": "pending",
                "created_at": now_iso(),
                "ticket_channel_id": 0,
                "cancelled_stock_returned": False
            }


            # 在庫を確保
            product["stock"] = (
                stock - 1
            )


            orders[
                order_id
            ] = order


            save_json(
                PRODUCTS_FILE,
                products
            )


            save_json(
                ORDERS_FILE,
                orders
            )


        # パネル更新
        await update_purchase_panel()


        # 専用チャット
        ticket = None
        ticket_error = None


        try:

            ticket = await create_ticket(
                order,
                guild,
                buyer
            )

        except Exception as e:

            ticket_error = str(e)

            print(
                f"[PURCHASE] 専用チャット作成失敗 "
                f"#{order_id}: {repr(e)}"
            )


        # 注文通知
        notify_error = None


        try:

            order_channel = (
                await get_or_create_order_channel(
                    guild
                )
            )


            await order_channel.send(
                embed=order_embed(
                    order
                ),
                view=OrderAdminView(
                    order_id
                )
            )


        except Exception as e:

            notify_error = str(e)

            print(
                f"[PURCHASE] 注文通知失敗 "
                f"#{order_id}: {repr(e)}"
            )


        # 購入者DM
        try:

            await buyer.send(
                embed=discord.Embed(
                    title=f"🧾 注文 #{order_id}",
                    description=(
                        f"**商品:** "
                        f"{order['product_name']}\n"
                        f"**金額:** "
                        f"{money(order['price'])}\n\n"
                        "注文を受け付けました。\n"
                        "管理者の入金確認をお待ちください。"
                    ),
                    color=int(
                        config["design"]["color"]
                    )
                )
            )

        except discord.HTTPException:

            pass


        # 結果
        message = (
            f"✅ 注文 **#{order_id}** "
            "を受け付けました！\n"
            f"🛍️ 商品: "
            f"**{order['product_name']}**\n"
            f"💴 金額: "
            f"**{money(order['price'])}**"
        )


        if ticket:

            message += (
                f"\n💬 専用チャット: "
                f"{ticket.mention}"
            )

        else:

            message += (
                "\n⚠️ 専用チャット作成に失敗しました。"
                "管理者へ通知されています。"
            )


        if ticket_error:

            print(
                f"[PURCHASE] ticket_error "
                f"#{order_id}: {ticket_error}"
            )


        if notify_error:

            message += (
                "\n⚠️ 管理通知の送信にも失敗しています。"
            )


        await interaction.followup.send(
            message,
            ephemeral=True
        )


# ============================================================
# 注文Embed
# ============================================================

def order_embed(
    order
):

    status_map = {

        "pending":
            "🟡 入金確認待ち",

        "paid":
            "🟢 支払い確認済み",

        "cancelled":
            "🔴 キャンセル",

        "completed":
            "🔵 完了"
    }


    embed = discord.Embed(
        title=(
            f"🛒 新しい注文 "
            f"#{order['id']}"
        ),
        color=(
            discord.Color.orange()
            if order.get(
                "status"
            ) == "pending"
            else
            discord.Color.green()
        )
    )


    embed.add_field(
        name="👤 購入者",
        value=(
            f"<@{order['buyer_id']}>"
        ),
        inline=True
    )


    embed.add_field(
        name="📦 商品",
        value=order[
            "product_name"
        ],
        inline=True
    )


    embed.add_field(
        name="💰 金額",
        value=money(
            order["price"]
        ),
        inline=True
    )


    embed.add_field(
        name="📌 状態",
        value=status_map.get(
            order.get(
                "status"
            ),
            "不明"
        ),
        inline=False
    )


    embed.add_field(
        name="💳 PayPay URL",
        value=order[
            "paypay_url"
        ][:1024],
        inline=False
    )


    embed.set_footer(
        text=(
            f"注文日時: "
            f"{order['created_at']}"
        )
    )


    return embed


# ============================================================
# 注文管理
# ============================================================

class OrderPaidButton(
    discord.ui.Button
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            label="支払い確認",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=(
                f"kira:order:paid:{order_id}"
            )
        )

        self.order_id = order_id


    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return


        order = orders.get(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return


        if order.get(
            "status"
        ) in (
            "cancelled",
            "completed"
        ):

            await interaction.response.send_message(
                "❌ この注文はすでに処理済みです。",
                ephemeral=True
            )

            return


        order[
            "status"
        ] = "paid"


        order[
            "paid_at"
        ] = now_iso()


        save_json(
            ORDERS_FILE,
            orders
        )


        await interaction.response.edit_message(
            embed=order_embed(
                order
            ),
            view=ProcessedOrderView()
        )


        try:

            buyer = (
                await interaction.client.fetch_user(
                    int(
                        order["buyer_id"]
                    )
                )
            )


            await buyer.send(
                f"✅ 注文 #{self.order_id} "
                "の支払いを確認しました。"
            )

        except discord.HTTPException:

            pass


class OrderCancelButton(
    discord.ui.Button
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            label="キャンセル",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id=(
                f"kira:order:cancel:{order_id}"
            )
        )

        self.order_id = order_id


    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return


        order = orders.get(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return


        if order.get(
            "status"
        ) in (
            "cancelled",
            "completed"
        ):

            await interaction.response.send_message(
                "❌ この注文はすでに処理済みです。",
                ephemeral=True
            )

            return


        if not order.get(
            "cancelled_stock_returned",
            False
        ):

            product = find_product(
                order.get(
                    "product_id"
                )
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
                    products
                )


            order[
                "cancelled_stock_returned"
            ] = True


        order[
            "status"
        ] = "cancelled"


        order[
            "cancelled_at"
        ] = now_iso()


        save_json(
            ORDERS_FILE,
            orders
        )


        await update_purchase_panel()


        await interaction.response.edit_message(
            embed=order_embed(
                order
            ),
            view=ProcessedOrderView()
        )


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
            OrderPaidButton(
                order_id
            )
        )

        self.add_item(
            OrderCancelButton(
                order_id
            )
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


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
                style=discord.ButtonStyle.secondary,
                disabled=True,
                custom_id="kira:processed"
            )
        )


# ============================================================
# Ticket
# ============================================================

class TicketArchiveButton(
    discord.ui.Button
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            label="履歴として保存",
            emoji="🗃️",
            style=discord.ButtonStyle.primary,
            custom_id=(
                f"kira:ticket:"
                f"archive:{order_id}"
            )
        )

        self.order_id = order_id


    async def callback(
        self,
        interaction
    ):

        order = orders.get(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return


        if not (
            is_admin(
                interaction.user
            )
            or
            interaction.user.id
            == int(
                order["buyer_id"]
            )
        ):

            await interaction.response.send_message(
                "🔒 権限がありません。",
                ephemeral=True
            )

            return


        try:

            category = (
                await get_or_create_category(
                    interaction.guild,
                    "📁 購入履歴",
                    "archive_category_id"
                )
            )


            await interaction.channel.edit(
                category=category,
                name=(
                    f"history-kira-"
                    f"{self.order_id}"
                )
            )


            await interaction.response.send_message(
                "🗃️ 履歴として保存しました。",
                ephemeral=True
            )


        except Exception as e:

            await interaction.response.send_message(
                f"❌ 履歴保存に失敗しました: "
                f"`{e}`",
                ephemeral=True
            )


class TicketDeleteButton(
    discord.ui.Button
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            label="チャット削除",
            emoji="🗑️",
            style=discord.ButtonStyle.danger,
            custom_id=(
                f"kira:ticket:"
                f"delete:{order_id}"
            )
        )

        self.order_id = order_id


    async def callback(
        self,
        interaction
    ):

        order = orders.get(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return


        if not (
            is_admin(
                interaction.user
            )
            or
            interaction.user.id
            == int(
                order["buyer_id"]
            )
        ):

            await interaction.response.send_message(
                "🔒 権限がありません。",
                ephemeral=True
            )

            return


        await interaction.response.send_message(
            "🗑️ 専用チャットを削除します。",
            ephemeral=True
        )


        await asyncio.sleep(
            1
        )


        try:

            await interaction.channel.delete(
                reason=(
                    f"注文 #{self.order_id} "
                    "専用チャット削除"
                )
            )

        except discord.HTTPException as e:

            print(
                f"[TICKET DELETE] {repr(e)}"
            )


class TicketView(
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
            TicketArchiveButton(
                order_id
            )
        )


        self.add_item(
            TicketDeleteButton(
                order_id
            )
        )


    async def interaction_check(
        self,
        interaction
    ):

        order = orders.get(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return False


        if not (
            is_admin(
                interaction.user
            )
            or
            interaction.user.id
            == int(
                order["buyer_id"]
            )
        ):

            await interaction.response.send_message(
                "🔒 権限がありません。",
                ephemeral=True
            )

            return False


        return True


# ============================================================
# 商品管理
# ============================================================

class ProductModal(
    discord.ui.Modal,
    title="➕ 商品追加"
):

    name = discord.ui.TextInput(
        label="商品名",
        max_length=80
    )

    price = discord.ui.TextInput(
        label="価格",
        placeholder="500"
    )

    stock = discord.ui.TextInput(
        label="在庫数",
        placeholder="10"
    )

    emoji = discord.ui.TextInput(
        label="絵文字",
        required=False,
        default="🛒",
        max_length=10
    )

    description = discord.ui.TextInput(
        label="説明",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )


    async def on_submit(
        self,
        interaction
    ):

        try:

            price = int(
                str(
                    self.price.value
                ).replace(
                    ",",
                    ""
                )
            )


            stock = int(
                str(
                    self.stock.value
                )
            )


            if price <= 0:

                raise ValueError


            if stock < 0:

                raise ValueError


        except ValueError:

            await interaction.response.send_message(
                "❌ 価格は1以上、在庫は0以上で入力してください。",
                ephemeral=True
            )

            return


        name = str(
            self.name.value
        ).strip()


        product_id = re.sub(
            r"[^a-z0-9_-]",
            "-",
            name.lower()
        )[:30]


        if not product_id:

            product_id = (
                f"product-{len(products) + 1}"
            )


        if find_product(
            product_id
        ):

            product_id = (
                f"{product_id}-"
                f"{len(products) + 1}"
            )


        products.append(
            {
                "id": product_id,
                "name": name,
                "description": str(
                    self.description.value
                ),
                "price": price,
                "stock": stock,
                "emoji": (
                    str(
                        self.emoji.value
                    )
                    or
                    "🛒"
                ),
                "image_url": "",
                "enabled": True
            }
        )


        save_json(
            PRODUCTS_FILE,
            products
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            f"✅ 商品を追加しました。\n"
            f"商品ID: `{product_id}`",
            ephemeral=True
        )


class ProductEditModal(
    discord.ui.Modal,
    title="✏️ 商品編集"
):

    def __init__(
        self,
        product_id
    ):

        super().__init__()

        self.product_id = product_id

        product = find_product(
            product_id
        )


        if product is None:

            raise RuntimeError(
                "商品が見つかりません。"
            )


        self.name = discord.ui.TextInput(
            label="商品名",
            default=product["name"],
            max_length=80
        )

        self.price = discord.ui.TextInput(
            label="価格",
            default=str(
                product["price"]
            )
        )

        self.stock = discord.ui.TextInput(
            label="在庫",
            default=str(
                product["stock"]
            )
        )

        self.emoji = discord.ui.TextInput(
            label="絵文字",
            default=product.get(
                "emoji",
                "🛒"
            ),
            max_length=10
        )

        self.description = discord.ui.TextInput(
            label="説明",
            default=product.get(
                "description",
                ""
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500
        )


        self.add_item(
            self.name
        )

        self.add_item(
            self.price
        )

        self.add_item(
            self.stock
        )

        self.add_item(
            self.emoji
        )

        self.add_item(
            self.description
        )


    async def on_submit(
        self,
        interaction
    ):

        product = find_product(
            self.product_id
        )


        if not product:

            await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )

            return


        try:

            price = int(
                str(
                    self.price.value
                ).replace(
                    ",",
                    ""
                )
            )


            stock = int(
                str(
                    self.stock.value
                )
            )


            if price <= 0 or stock < 0:

                raise ValueError


        except ValueError:

            await interaction.response.send_message(
                "❌ 価格/在庫が正しくありません。",
                ephemeral=True
            )

            return


        product[
            "name"
        ] = str(
            self.name.value
        )


        product[
            "price"
        ] = price


        product[
            "stock"
        ] = stock


        product[
            "emoji"
        ] = (
            str(
                self.emoji.value
            )
            or
            "🛒"
        )


        product[
            "description"
        ] = str(
            self.description.value
        )


        save_json(
            PRODUCTS_FILE,
            products
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ 商品を更新しました。",
            ephemeral=True
        )


class ProductSelect(
    discord.ui.Select
):

    def __init__(
        self,
        mode
    ):

        self.mode = mode


        options = []


        for product in products[:25]:

            options.append(
                discord.SelectOption(
                    label=product[
                        "name"
                    ][:100],
                    value=product[
                        "id"
                    ],
                    description=(
                        f"{money(product['price'])} "
                        f"/ 在庫 {product['stock']}"
                    )[:100]
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

        if self.mode == "edit":

            try:

                await interaction.response.send_modal(
                    ProductEditModal(
                        self.values[0]
                    )
                )

            except Exception as e:

                await interaction.response.send_message(
                    f"❌ 商品編集を開けませんでした: `{e}`",
                    ephemeral=True
                )

            return


        if self.mode == "delete":

            product = find_product(
                self.values[0]
            )


            if not product:

                await interaction.response.send_message(
                    "❌ 商品が見つかりません。",
                    ephemeral=True
                )

                return


            products.remove(
                product
            )


            save_json(
                PRODUCTS_FILE,
                products
            )


            await update_purchase_panel()


            await interaction.response.send_message(
                f"🗑️ `{product['name']}` を削除しました。",
                ephemeral=True
            )

            return


        if self.mode == "stock":

            await interaction.response.send_modal(
                StockModal(
                    self.values[0]
                )
            )


class ProductSelectView(
    discord.ui.View
):

    def __init__(
        self,
        mode
    ):

        super().__init__(
            timeout=180
        )

        if products:

            self.add_item(
                ProductSelect(
                    mode
                )
            )


class StockModal(
    discord.ui.Modal,
    title="📦 在庫変更"
):

    stock = discord.ui.TextInput(
        label="新しい在庫数",
        placeholder="10"
    )


    def __init__(
        self,
        product_id
    ):

        super().__init__()

        self.product_id = product_id


    async def on_submit(
        self,
        interaction
    ):

        product = find_product(
            self.product_id
        )


        if not product:

            await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )

            return


        try:

            stock = int(
                str(
                    self.stock.value
                )
            )


            if stock < 0:

                raise ValueError


        except ValueError:

            await interaction.response.send_message(
                "❌ 0以上の数字を入力してください。",
                ephemeral=True
            )

            return


        product[
            "stock"
        ] = stock


        save_json(
            PRODUCTS_FILE,
            products
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ 在庫を変更しました。",
            ephemeral=True
        )


class ProductAdminView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="商品追加",
        emoji="➕",
        style=discord.ButtonStyle.success
    )
    async def add(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            ProductModal()
        )


    @discord.ui.button(
        label="商品編集",
        emoji="✏️",
        style=discord.ButtonStyle.primary
    )
    async def edit(
        self,
        interaction,
        button
    ):

        if not products:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return


        await interaction.response.send_message(
            "編集する商品を選択してください。",
            view=ProductSelectView(
                "edit"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="商品削除",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete(
        self,
        interaction,
        button
    ):

        if not products:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return


        await interaction.response.send_message(
            "削除する商品を選択してください。",
            view=ProductSelectView(
                "delete"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="在庫変更",
        emoji="📦",
        style=discord.ButtonStyle.secondary
    )
    async def stock(
        self,
        interaction,
        button
    ):

        if not products:

            await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )

            return


        await interaction.response.send_message(
            "在庫を変更する商品を選択してください。",
            view=ProductSelectView(
                "stock"
            ),
            ephemeral=True
        )


# ============================================================
# デザイン管理
# ============================================================

class DesignTextModal(
    discord.ui.Modal,
    title="✏️ 販売機テキスト"
):

    title_text = discord.ui.TextInput(
        label="タイトル",
        default=DEFAULT_CONFIG[
            "design"
        ]["title"],
        max_length=256
    )

    subtitle = discord.ui.TextInput(
        label="サブタイトル",
        default=DEFAULT_CONFIG[
            "design"
        ]["subtitle"],
        max_length=256
    )

    description = discord.ui.TextInput(
        label="説明",
        default=DEFAULT_CONFIG[
            "design"
        ]["description"],
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    notice = discord.ui.TextInput(
        label="お知らせ",
        default=DEFAULT_CONFIG[
            "design"
        ]["notice"],
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000
    )

    footer = discord.ui.TextInput(
        label="フッター",
        default=DEFAULT_CONFIG[
            "design"
        ]["footer"],
        required=False,
        max_length=256
    )


    async def on_submit(
        self,
        interaction
    ):

        design = config[
            "design"
        ]


        design[
            "title"
        ] = str(
            self.title_text.value
        )


        design[
            "subtitle"
        ] = str(
            self.subtitle.value
        )


        design[
            "description"
        ] = str(
            self.description.value
        )


        design[
            "notice"
        ] = str(
            self.notice.value
        )


        design[
            "footer"
        ] = str(
            self.footer.value
        )


        save_json(
            CONFIG_FILE,
            config
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ デザインを保存しました。",
            ephemeral=True
        )


class ColorModal(
    discord.ui.Modal,
    title="🎨 色設定"
):

    hex_color = discord.ui.TextInput(
        label="16進カラー",
        placeholder="#8B5CF6",
        default="#8B5CF6"
    )


    async def on_submit(
        self,
        interaction
    ):

        value = (
            str(
                self.hex_color.value
            )
            .strip()
            .replace(
                "#",
                ""
            )
        )


        try:

            number = int(
                value,
                16
            )


            if number < 0 or number > 0xFFFFFF:

                raise ValueError


        except ValueError:

            await interaction.response.send_message(
                "❌ `#8B5CF6` のような形式で入力してください。",
                ephemeral=True
            )

            return


        config[
            "design"
        ][
            "color"
        ] = number


        save_json(
            CONFIG_FILE,
            config
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ 色を変更しました。",
            ephemeral=True
        )


class BannerModal(
    discord.ui.Modal,
    title="🖼️ バナー/GIF"
):

    url = discord.ui.TextInput(
        label="画像/GIF URL",
        placeholder="https://...",
        default=config[
            "design"
        ].get(
            "banner_url",
            ""
        ),
        required=False,
        max_length=1000
    )


    async def on_submit(
        self,
        interaction
    ):

        value = str(
            self.url.value
        ).strip()


        if value and not re.match(
            r"^https?://",
            value,
            re.I
        ):

            await interaction.response.send_message(
                "❌ http(s) のURLを入力してください。",
                ephemeral=True
            )

            return


        config[
            "design"
        ][
            "banner_url"
        ] = value


        save_json(
            CONFIG_FILE,
            config
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ バナー/GIFを保存しました。",
            ephemeral=True
        )


class DesignView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="タイトル等",
        emoji="✏️",
        style=discord.ButtonStyle.primary
    )
    async def text(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            DesignTextModal()
        )


    @discord.ui.button(
        label="色を変更",
        emoji="🎨",
        style=discord.ButtonStyle.secondary
    )
    async def color(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            ColorModal()
        )


    @discord.ui.button(
        label="バナー/GIF",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary
    )
    async def banner(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            BannerModal()
        )


    @discord.ui.button(
        label="プレビュー",
        emoji="👁️",
        style=discord.ButtonStyle.success
    )
    async def preview(
        self,
        interaction,
        button
    ):

        banner = config[
            "design"
        ].get(
            "banner_url",
            ""
        )


        await interaction.response.send_message(
            content=(
                banner
                if banner.startswith(
                    "http"
                )
                else
                None
            ),
            embed=design_embed(),
            view=PurchaseView(),
            ephemeral=True
        )


# ============================================================
# チャンネル / メディア
# ============================================================

class ChannelIdModal(
    discord.ui.Modal
):

    def __init__(
        self,
        config_key,
        title
    ):

        super().__init__(
            title=title
        )

        self.config_key = config_key


        self.channel_id = discord.ui.TextInput(
            label="チャンネルID",
            placeholder="123456789012345678"
        )


        self.add_item(
            self.channel_id
        )


    async def on_submit(
        self,
        interaction
    ):

        try:

            channel_id = int(
                str(
                    self.channel_id.value
                ).strip()
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ チャンネルIDが正しくありません。",
                ephemeral=True
            )

            return


        channel = interaction.guild.get_channel(
            channel_id
        )


        if not isinstance(
            channel,
            discord.TextChannel
        ):

            await interaction.response.send_message(
                "❌ そのチャンネルが見つかりません。",
                ephemeral=True
            )

            return


        permissions = channel.permissions_for(
            interaction.guild.me
        )


        if not (
            permissions.view_channel
            and permissions.send_messages
        ):

            await interaction.response.send_message(
                "❌ Botがそのチャンネルを使用できません。",
                ephemeral=True
            )

            return


        config[
            self.config_key
        ] = channel.id


        save_json(
            CONFIG_FILE,
            config
        )


        await interaction.response.send_message(
            f"✅ {channel.mention} を設定しました。",
            ephemeral=True
        )


class ChannelSettingsView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="購入チャンネルを設定",
        emoji="🛒",
        style=discord.ButtonStyle.primary
    )
    async def purchase(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            ChannelIdModal(
                "purchase_channel_id",
                "購入チャンネルID"
            )
        )


    @discord.ui.button(
        label="注文通知を作成/確認",
        emoji="📦",
        style=discord.ButtonStyle.success
    )
    async def order(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        try:

            channel = (
                await get_or_create_order_channel(
                    interaction.guild
                )
            )


            await interaction.followup.send(
                f"✅ 注文通知チャンネル: "
                f"{channel.mention}",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ 注文通知チャンネル作成失敗: "
                f"`{e}`",
                ephemeral=True
            )


    @discord.ui.button(
        label="メディアチャンネル作成",
        emoji="🎞️",
        style=discord.ButtonStyle.secondary
    )
    async def media(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        guild = interaction.guild


        try:

            existing = next(
                (
                    channel
                    for channel in guild.text_channels
                    if channel.name
                    == "vending-media"
                ),
                None
            )


            if existing:

                await secure_private_channel(
                    existing,
                    guild
                )


                config[
                    "media_channel_id"
                ] = existing.id


                save_json(
                    CONFIG_FILE,
                    config
                )


                await interaction.followup.send(
                    f"✅ メディアチャンネル: "
                    f"{existing.mention}",
                    ephemeral=True
                )

                return


            category = None


            try:

                category = (
                    await get_or_create_category(
                        guild,
                        "🔒 管理者エリア",
                        "admin_category_id"
                    )
                )

            except Exception:

                pass


            try:

                channel = (
                    await guild.create_text_channel(
                        "vending-media",
                        category=category,
                        reason=(
                            f"{BOT_NAME} "
                            "メディア保管チャンネル"
                        )
                    )
                )

            except discord.Forbidden:

                channel = (
                    await guild.create_text_channel(
                        "vending-media",
                        reason=(
                            f"{BOT_NAME} "
                            "メディア保管チャンネル再試行"
                        )
                    )
                )


            await secure_private_channel(
                channel,
                guild
            )


            config[
                "media_channel_id"
            ] = channel.id


            save_json(
                CONFIG_FILE,
                config
            )


            await interaction.followup.send(
                f"✅ メディアチャンネルを作成しました: "
                f"{channel.mention}",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ メディアチャンネル作成失敗: "
                f"`{e}`",
                ephemeral=True
            )


class MediaView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=300
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="メディアチャンネルを開く",
        emoji="🎞️",
        style=discord.ButtonStyle.primary
    )
    async def open_media(
        self,
        interaction,
        button
    ):

        channel = interaction.guild.get_channel(
            int(
                config.get(
                    "media_channel_id",
                    0
                ) or 0
            )
        )


        if isinstance(
            channel,
            discord.TextChannel
        ):

            await interaction.response.send_message(
                f"ここにGIF/画像をドラッグ＆ドロップしてください: "
                f"{channel.mention}",
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                "❌ 先にメディアチャンネルを作成してください。",
                ephemeral=True
            )


    @discord.ui.button(
        label="バナーURL設定",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary
    )
    async def banner(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            BannerModal()
        )


# ============================================================
# 管理パネル
# ============================================================

async def find_purchase_channel(
    guild
):

    saved_id = int(
        config.get(
            "purchase_channel_id",
            0
        ) or 0
    )


    if saved_id:

        channel = guild.get_channel(
            saved_id
        )

        if isinstance(
            channel,
            discord.TextChannel
        ):

            return channel


    for channel in guild.text_channels:

        if channel.name == "購入":

            config[
                "purchase_channel_id"
            ] = channel.id

            save_json(
                CONFIG_FILE,
                config
            )

            return channel


    return None


class AdminPanelView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    async def interaction_check(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="販売機を設置/更新",
        emoji="🛒",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="kira:admin:deploy"
    )
    async def deploy(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        channel = await find_purchase_channel(
            interaction.guild
        )


        if not channel:

            await interaction.followup.send(
                "❌ `#購入` が見つかりません。\n"
                "#購入 チャンネルを作成してください。",
                ephemeral=True
            )

            return


        permissions = channel.permissions_for(
            interaction.guild.me
        )


        if not (
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        ):

            await interaction.followup.send(
                "❌ Botが #購入 に投稿できません。",
                ephemeral=True
            )

            return


        banner = config[
            "design"
        ].get(
            "banner_url",
            ""
        )


        content = (
            banner
            if banner.startswith(
                "http"
            )
            else
            None
        )


        message = await channel.send(
            content=content,
            embed=design_embed(),
            view=PurchaseView()
        )


        config[
            "panel_message_id"
        ] = message.id


        config[
            "panel_channel_id"
        ] = channel.id


        save_json(
            CONFIG_FILE,
            config
        )


        await interaction.followup.send(
            f"✅ {channel.mention} に販売機を設置しました。",
            ephemeral=True
        )


    @discord.ui.button(
        label="商品管理",
        emoji="📦",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="kira:admin:products"
    )
    async def product_manage(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            embed=discord.Embed(
                title="📦 商品管理",
                description=(
                    "商品追加・編集・削除・在庫変更"
                ),
                color=int(
                    config["design"]["color"]
                )
            ),
            view=ProductAdminView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="デザイン",
        emoji="🎨",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="kira:admin:design"
    )
    async def design(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎨 デザイン設定",
                description=(
                    "販売機の見た目を変更できます。"
                ),
                color=int(
                    config["design"]["color"]
                )
            ),
            view=DesignView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="チャンネル設定",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="kira:admin:channels"
    )
    async def channels(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            embed=discord.Embed(
                title="⚙️ チャンネル設定",
                description=(
                    f"🛒 購入: "
                    f"{channel_mention(interaction.guild, config.get('purchase_channel_id'))}\n"
                    f"📦 注文通知: "
                    f"{channel_mention(interaction.guild, config.get('order_channel_id'))}\n"
                    f"💬 購入チャット: "
                    f"{category_mention(interaction.guild, config.get('ticket_category_id'))}\n"
                    f"🎞️ メディア: "
                    f"{channel_mention(interaction.guild, config.get('media_channel_id'))}"
                ),
                color=int(
                    config["design"]["color"]
                )
            ),
            view=ChannelSettingsView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="メディア/GIF",
        emoji="🎞️",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="kira:admin:media"
    )
    async def media(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎞️ メディア管理",
                description=(
                    "管理者専用メディアチャンネルに"
                    "GIF・画像をドラッグ＆ドロップできます。\n\n"
                    "バナー/GIF・商品画像・Embedを"
                    "組み合わせて販売機の見た目を作れます。"
                ),
                color=int(
                    config["design"]["color"]
                )
            ),
            view=MediaView(),
            ephemeral=True
        )


# ============================================================
# パネル更新
# ============================================================

async def update_purchase_panel():

    channel_id = int(
        config.get(
            "panel_channel_id",
            0
        )
        or
        config.get(
            "purchase_channel_id",
            0
        )
        or
        0
    )


    message_id = int(
        config.get(
            "panel_message_id",
            0
        ) or 0
    )


    if not channel_id or not message_id:

        return False


    try:

        channel = (
            bot.get_channel(
                channel_id
            )
            or
            await bot.fetch_channel(
                channel_id
            )
        )


        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return False


        message = await channel.fetch_message(
            message_id
        )


        banner = config[
            "design"
        ].get(
            "banner_url",
            ""
        )


        content = (
            banner
            if banner.startswith(
                "http"
            )
            else
            None
        )


        await message.edit(
            content=content,
            embed=design_embed(),
            view=PurchaseView()
        )


        return True


    except Exception as e:

        print(
            f"[PANEL] 更新失敗: {repr(e)}"
        )

        return False


# ============================================================
# Slash Commands
# ============================================================

class AdminCog(
    commands.Cog
):

    def __init__(
        self,
        bot_instance
    ):

        self.bot = bot_instance


    @app_commands.command(
        name="admin",
        description="キラの自動販売機 管理パネル"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def admin(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return


        embed = discord.Embed(
            title=(
                "⚙️ キラの自動販売機 "
                "— 管理パネル"
            ),
            description=(
                "ここから販売機・商品・デザイン・"
                "メディア・チャンネルを管理できます。\n\n"
                "🔒 管理画面は管理者にだけ表示されます。"
            ),
            color=int(
                config["design"]["color"]
            )
        )


        await interaction.response.send_message(
            embed=embed,
            view=AdminPanelView(),
            ephemeral=True
        )


    @app_commands.command(
        name="setup_vending",
        description="販売機の初期セットアップ"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def setup_vending(
        self,
        interaction
    ):

        if not is_admin(
            interaction.user
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return


        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        guild = interaction.guild


        try:

            if not config.get(
                "guild_id"
            ):

                config[
                    "guild_id"
                ] = guild.id

                save_json(
                    CONFIG_FILE,
                    config
                )


            order_channel = (
                await get_or_create_order_channel(
                    guild
                )
            )


            ticket_category = (
                await get_or_create_category(
                    guild,
                    "💬 購入チャット",
                    "ticket_category_id"
                )
            )


            purchase_channel = (
                await find_purchase_channel(
                    guild
                )
            )


            await interaction.followup.send(
                "✅ 初期セットアップ完了\n\n"
                f"📦 注文通知: "
                f"{order_channel.mention}\n"
                f"💬 購入チャットカテゴリ: "
                f"`{ticket_category.name}`\n"
                f"🛒 購入チャンネル: "
                f"{purchase_channel.mention if purchase_channel else '未設定'}\n\n"
                "管理画面の"
                "「販売機を設置/更新」から"
                "販売機を設置してください。",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ セットアップ失敗: `{e}`",
                ephemeral=True
            )


# ============================================================
# Events
# ============================================================

@bot.event
async def on_ready():

    print("=" * 55)

    print(
        f"✅ ログインしました: "
        f"{bot.user}"
    )

    print(
        "🛒 キラの自動販売機 起動完了"
    )

    print("=" * 55)


    # 最初のサーバーを設定
    if (
        not config.get(
            "guild_id"
        )
        and bot.guilds
    ):

        config[
            "guild_id"
        ] = bot.guilds[0].id

        save_json(
            CONFIG_FILE,
            config
        )


    # 自動注文通知チャンネル
    guild = None


    if config.get(
        "guild_id"
    ):

        guild = bot.get_guild(
            int(
                config[
                    "guild_id"
                ]
            )
        )


    if guild:

        try:

            await get_or_create_order_channel(
                guild
            )

        except Exception as e:

            print(
                f"[STARTUP] 注文通知チャンネル確認失敗: "
                f"{repr(e)}"
            )


@bot.event
async def on_guild_join(
    guild
):

    if not config.get(
        "guild_id"
    ):

        config[
            "guild_id"
        ] = guild.id

        save_json(
            CONFIG_FILE,
            config
        )


@bot.event
async def on_message(
    message
):

    if (
        message.author.bot
        or not message.guild
    ):

        return


    media_channel_id = int(
        config.get(
            "media_channel_id",
            0
        ) or 0
    )


    if (
        media_channel_id
        and message.channel.id
        == media_channel_id
    ):

        if is_admin(
            message.author
        ):

            for attachment in (
                message.attachments
            ):

                filename = (
                    attachment.filename.lower()
                )


                if (
                    (
                        attachment.content_type
                        and
                        attachment.content_type.startswith(
                            "image/"
                        )
                    )
                    or
                    filename.endswith(
                        (
                            ".gif",
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".webp"
                        )
                    )
                ):

                    print(
                        "[MEDIA] "
                        f"{message.author} -> "
                        f"{attachment.url}"
                    )


    await bot.process_commands(
        message
    )


# ============================================================
# 起動
# ============================================================

TOKEN = os.getenv(
    "DISCORD_TOKEN"
)


if not TOKEN:

    raise RuntimeError(
        "DISCORD_TOKEN が設定されていません。"
    )


bot.run(
    TOKEN
)
