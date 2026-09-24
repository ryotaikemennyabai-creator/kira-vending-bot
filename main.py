import os
import json
import asyncio
import re
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "キラの自動販売機"
BASE = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.path.join(BASE, "products.json")
CONFIG_FILE = os.path.join(BASE, "config.json")
ORDERS_FILE = os.path.join(BASE, "orders.json")

DEFAULT_CONFIG = {
    "guild_id": 0,
    "purchase_channel_id": 0,
    "order_channel_id": 0,
    "admin_category_id": 0,
    "ticket_category_id": 0,
    "media_channel_id": 0,
    "panel_channel_id": 0,
    "panel_message_id": 0,
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
        "description": "商品説明を管理画面から変更できます。",
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

def clone(obj):
    return json.loads(
        json.dumps(
            obj,
            ensure_ascii=False
        )
    )


def save_json(path, data):
    tmp = path + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    os.replace(
        tmp,
        path
    )


def load_json(path, default):
    if not os.path.exists(path):

        save_json(
            path,
            default
        )

        return clone(default)

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

        return clone(default)


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


if not isinstance(
    config,
    dict
):

    config = clone(
        DEFAULT_CONFIG
    )


if not isinstance(
    products,
    list
):

    products = clone(
        DEFAULT_PRODUCTS
    )


if not isinstance(
    orders,
    dict
):

    orders = {}


# 足りない設定を補完
for key, value in DEFAULT_CONFIG.items():

    if key not in config:

        config[key] = (
            clone(value)
            if isinstance(
                value,
                (dict, list)
            )
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


if not isinstance(
    config.get(
        "media_library"
    ),
    list
):

    config[
        "media_library"
    ] = []


# 商品データ補完
for i, product in enumerate(products):

    if not isinstance(
        product,
        dict
    ):

        products[i] = {
            "id": f"product-{i + 1}",
            "name": "商品",
            "description": "",
            "price": 0,
            "stock": 0,
            "emoji": "🛒",
            "image_url": "",
            "enabled": True,
        }

        continue


    product.setdefault(
        "id",
        f"product-{i + 1}"
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

        if (
            product.get("id")
            == product_id
        ):

            return product

    return None


def find_order(order_id):

    return orders.get(
        order_id
    )


def next_order_id():

    config[
        "order_counter"
    ] = (
        int(
            config.get(
                "order_counter",
                0
            )
        )
        + 1
    )

    save_json(
        CONFIG_FILE,
        config
    )

    return (
        f"{config['order_counter']:05d}"
    )


def channel_mention(
    guild,
    channel_id
):

    if not guild:

        return "未設定"

    try:

        channel = guild.get_channel(
            int(
                channel_id or 0
            )
        )

    except Exception:

        return "未設定"

    if channel:

        return channel.mention

    return "未設定"


def category_name(
    guild,
    category_id
):

    if not guild:

        return "未設定"

    try:

        category = guild.get_channel(
            int(
                category_id or 0
            )
        )

    except Exception:

        return "未設定"

    if isinstance(
        category,
        discord.CategoryChannel
    ):

        return category.name

    return "未設定"


# ============================================================
# Discord
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.messages = True


# ============================================================
# デザイン
# ============================================================

def panel_embed():

    d = config[
        "design"
    ]

    embed = discord.Embed(
        title=d.get(
            "title",
            "🛒 キラの自動販売機"
        ),
        description=(
            f"**{d.get('subtitle', '')}**\n\n"
            f"{d.get('description', '')}\n\n"
            f"{d.get('notice', '')}"
        ),
        color=int(
            d.get(
                "color",
                0x8B5CF6
            )
        ),
    )


    active_products = [
        product
        for product in products
        if product.get(
            "enabled",
            True
        )
    ]


    lines = []


    for product in active_products[:25]:

        stock = int(
            product.get(
                "stock",
                0
            )
        )


        if d.get(
            "show_stock",
            True
        ):

            stock_text = (
                f"在庫: **{stock}**"
                if stock > 0
                else
                "🔴 売り切れ"
            )

        else:

            stock_text = (
                "🟢 在庫あり"
                if stock > 0
                else
                "🔴 売り切れ"
            )


        lines.append(
            f"{product.get('emoji', '🛒')} "
            f"**{product['name']}** — "
            f"{money(product['price'])}\n"
            f"{product.get('description', '')[:120]}\n"
            f"{stock_text}"
        )


    if lines:

        text = "\n\n".join(
            lines
        )

    else:

        text = (
            "現在販売中の商品はありません。"
        )


    if len(text) > 1024:

        text = text[:1000] + "\n…"


    embed.add_field(
        name="🛍️ 商品一覧",
        value=text,
        inline=False
    )


    if d.get(
        "footer"
    ):

        embed.set_footer(
            text=d[
                "footer"
            ]
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


    # 一般ユーザーには非公開
    await channel.set_permissions(
        guild.default_role,
        view_channel=False,
        reason=(
            f"{BOT_NAME} "
            "非公開設定"
        ),
    )


    # BotがAdministratorなら
    # 不要なpermission overwriteを増やさない
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


    # 購入者
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
        )
        or 0
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


    if (
        not me
        or
        not me.guild_permissions.manage_channels
    ):

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


    if (
        not me
        or
        not me.guild_permissions.manage_channels
    ):

        raise RuntimeError(
            "Botに「チャンネルの管理」権限がありません。"
        )


    saved_id = int(
        config.get(
            "order_channel_id",
            0
        )
        or 0
    )


    channel = (
        guild.get_channel(
            saved_id
        )
        if saved_id
        else
        None
    )


    # 保存済みが無ければ名前で探す
    if not isinstance(
        channel,
        discord.TextChannel
    ):

        channel = next(
            (
                ch
                for ch in guild.text_channels
                if ch.name
                == "注文通知"
            ),
            None
        )


    # 既存を利用
    if isinstance(
        channel,
        discord.TextChannel
    ):

        try:

            await secure_private_channel(
                channel,
                guild
            )

        except discord.Forbidden as e:

            raise RuntimeError(
                "#注文通知を非公開設定できませんでした。"
                "Botロールのチャンネル権限を確認してください。"
            ) from e


        config[
            "order_channel_id"
        ] = channel.id


        save_json(
            CONFIG_FILE,
            config
        )


        return channel


    # 新規作成
    try:

        channel = await guild.create_text_channel(
            "注文通知",
            overwrites={
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
                        attach_files=True,
                        manage_messages=True
                    )
            },
            topic=(
                f"{BOT_NAME} "
                "注文通知（管理者専用）"
            ),
            reason=(
                f"{BOT_NAME} "
                "注文通知チャンネル"
            ),
        )

    except discord.Forbidden as e:

        raise RuntimeError(
            "#注文通知を作成できませんでした。"
            "Botに「チャンネルの管理」権限が必要です。"
        ) from e


    config[
        "order_channel_id"
    ] = channel.id


    save_json(
        CONFIG_FILE,
        config
    )


    return channel


# ============================================================
# 専用チャット
# ============================================================

async def create_ticket(
    order,
    guild,
    buyer
):

    me = guild.me


    if (
        not me
        or
        not me.guild_permissions.manage_channels
    ):

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
            f"直下で作成します: {e}"
        )


    channel_name = (
        f"chat-kira-{order['id']}"
    )


    # まずチャンネルを作る
    try:

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            topic=(
                f"注文 #{order['id']} / "
                f"{order['product_name']}"
            ),
            reason=(
                f"注文 #{order['id']} "
                "専用チャット"
            ),
        )

    except discord.Forbidden as e:

        print(
            "[TICKET] カテゴリ付き作成失敗。"
            f"直下で再試行: {e}"
        )


        channel = await guild.create_text_channel(
            channel_name,
            topic=(
                f"注文 #{order['id']} / "
                f"{order['product_name']}"
            ),
            reason=(
                f"注文 #{order['id']} "
                "専用チャット再試行"
            ),
        )


    # 権限
    try:

        await secure_private_channel(
            channel,
            guild,
            buyer
        )

    except discord.Forbidden as e:

        print(
            f"[TICKET] 権限設定失敗: {repr(e)}"
        )

        raise RuntimeError(
            "専用チャットの権限設定に失敗しました。"
        ) from e


    # Bot権限確認
    perms = channel.permissions_for(
        me
    )


    if not perms.view_channel:

        raise RuntimeError(
            "専用チャットでBotが閲覧できません。"
        )


    if not perms.send_messages:

        raise RuntimeError(
            "専用チャットでBotが送信できません。"
        )


    # 注文データ保存
    order[
        "ticket_channel_id"
    ] = channel.id


    save_json(
        ORDERS_FILE,
        orders
    )


    embed = discord.Embed(
        title=(
            f"💬 注文 #{order['id']} "
            "専用チャット"
        ),
        description=(
            f"**商品:** "
            f"{order['product_name']}\n"
            f"**金額:** "
            f"{money(order['price'])}\n"
            f"**購入者:** "
            f"{buyer.mention}\n\n"
            "PayPay送金URLを受け取りました。\n"
            "管理者の入金確認をお待ちください。"
        ),
        color=int(
            config["design"].get(
                "color",
                0x8B5CF6
            )
        ),
    )


    embed.add_field(
        name="💳 PayPay送金URL",
        value=(
            order["paypay_url"][:1024]
        ),
        inline=False
    )


    embed.set_footer(
        text=(
            f"{BOT_NAME} "
            f"• #{order['id']}"
        )
    )


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


    return channel


# ============================================================
# 商品パネル
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

            self.add_item(
                ProductButton(
                    product_id=product["id"],
                    name=product.get(
                        "name",
                        "商品"
                    ),
                    emoji=product.get(
                        "emoji",
                        "🛒"
                    )
                )
            )


class ProductButton(
    discord.ui.Button
):

    def __init__(
        self,
        product_id,
        name,
        emoji
    ):

        product = find_product(
            product_id
        )


        stock = (
            int(
                product.get(
                    "stock",
                    0
                )
            )
            if product
            else
            0
        )


        if stock > 0:

            style = (
                discord.ButtonStyle.primary
            )

            disabled = False

        else:

            style = (
                discord.ButtonStyle.secondary
            )

            disabled = True


        super().__init__(
            label=name[:80],
            emoji=(
                emoji[:100]
                if emoji
                else
                "🛒"
            ),
            style=style,
            disabled=disabled,
            custom_id=(
                f"kira:buy:"
                f"{product_id}"
            )
        )


        self.product_id = product_id


    async def callback(
        self,
        interaction
    ):

        await show_product(
            interaction,
            self.product_id
        )


# ============================================================
# 古い購入ボタン復元
# ============================================================

class ProductPersistentButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=(
        r"kira:buy:"
        r"(?P<pid>[A-Za-z0-9_-]{1,64})"
    )
):

    def __init__(
        self,
        item,
        pid
    ):

        super().__init__(
            item
        )

        self.product_id = pid


    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            match["pid"]
        )


    async def callback(
        self,
        interaction
    ):

        await show_product(
            interaction,
            self.product_id
        )


# ============================================================
# 商品詳細
# ============================================================

async def show_product(
    interaction,
    product_id
):

    product = find_product(
        product_id
    )


    if (
        not product
        or
        not product.get(
            "enabled",
            True
        )
    ):

        return await interaction.response.send_message(
            "❌ この商品は現在販売されていません。",
            ephemeral=True
        )


    if int(
        product.get(
            "stock",
            0
        )
    ) <= 0:

        return await interaction.response.send_message(
            "❌ この商品は売り切れです。",
            ephemeral=True
        )


    description = (
        f"{product.get('description', '')}"
        "\n\n"
        f"💰 **価格**　"
        f"{money(product['price'])}\n"
        f"📦 **在庫**　"
        f"{product['stock']}"
    )


    embed = discord.Embed(
        title=(
            f"{product.get('emoji', '🛒')} "
            f"{product['name']}"
        ),
        description=description,
        color=int(
            config["design"].get(
                "color",
                0x8B5CF6
            )
        )
    )


    if product.get(
        "image_url",
        ""
    ).startswith(
        "http"
    ):

        embed.set_image(
            url=product[
                "image_url"
            ]
        )


    await interaction.response.send_message(
        embed=embed,
        view=ProductDetailView(
            product_id
        ),
        ephemeral=True
    )


class ProductDetailView(
    discord.ui.View
):

    def __init__(
        self,
        product_id
    ):

        super().__init__(
            timeout=180
        )

        self.product_id = product_id


    @discord.ui.button(
        label="購入する",
        emoji="🛒",
        style=discord.ButtonStyle.success
    )
    async def buy(
        self,
        interaction,
        button
    ):

        product = find_product(
            self.product_id
        )


        if (
            not product
            or
            int(
                product.get(
                    "stock",
                    0
                )
            ) <= 0
        ):

            return await interaction.response.send_message(
                "❌ 売り切れです。",
                ephemeral=True
            )


        await interaction.response.send_modal(
            PayPayModal(
                self.product_id
            )
        )


    @discord.ui.button(
        label="閉じる",
        emoji="✖️",
        style=discord.ButtonStyle.secondary
    )
    async def close(
        self,
        interaction,
        button
    ):

        await interaction.response.edit_message(
            content="閉じました。",
            embed=None,
            view=None
        )


# ============================================================
# PayPay
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

        self.product_id = (
            product_id
        )


    async def on_submit(
        self,
        interaction
    ):

        url = str(
            self.paypay_url.value
        ).strip()


        if not re.match(
            r"^https?://",
            url,
            re.I
        ):

            return await interaction.response.send_message(
                "❌ URL形式が正しくありません。",
                ephemeral=True
            )


        # 最初に応答して
        # 「アプリケーションが時間内に対応していません」
        # を防ぐ
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        guild = interaction.guild
        buyer = interaction.user


        if (
            guild is None
            or
            not isinstance(
                buyer,
                discord.Member
            )
        ):

            return await interaction.followup.send(
                "❌ サーバー内でのみ購入できます。",
                ephemeral=True
            )


        # 同時購入を防止
        async with purchase_lock:

            product = find_product(
                self.product_id
            )


            if (
                not product
                or
                not product.get(
                    "enabled",
                    True
                )
            ):

                return await interaction.followup.send(
                    "❌ この商品は販売停止になりました。",
                    ephemeral=True
                )


            stock = int(
                product.get(
                    "stock",
                    0
                )
            )


            if stock <= 0:

                return await interaction.followup.send(
                    "❌ 売り切れになりました。",
                    ephemeral=True
                )


            order_id = next_order_id()


            order = {

                "id":
                    order_id,

                "guild_id":
                    guild.id,

                "buyer_id":
                    buyer.id,

                "buyer_name":
                    str(
                        buyer
                    ),

                "product_id":
                    product["id"],

                "product_name":
                    product["name"],

                "price":
                    int(
                        product["price"]
                    ),

                "paypay_url":
                    url,

                "status":
                    "pending",

                "created_at":
                    now_iso(),

                "ticket_channel_id":
                    0,

                "cancelled_stock_returned":
                    False
            }


            # 先に在庫確保
            product[
                "stock"
            ] = (
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
        try:

            await update_purchase_panel()

        except Exception as e:

            print(
                "[PURCHASE] "
                f"パネル更新失敗: {repr(e)}"
            )


        # ====================================================
        # 専用チャット
        # ====================================================

        ticket = None
        ticket_error = None


        try:

            ticket = await create_ticket(
                order,
                guild,
                buyer
            )

        except Exception as e:

            ticket_error = str(
                e
            )

            print(
                "[PURCHASE] "
                f"専用チャット作成失敗 "
                f"#{order_id}: {repr(e)}"
            )


        # ====================================================
        # 注文通知
        # ====================================================

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

            notify_error = str(
                e
            )

            print(
                "[PURCHASE] "
                f"注文通知送信失敗 "
                f"#{order_id}: {repr(e)}"
            )


        # ====================================================
        # DM
        # ====================================================

        try:

            await buyer.send(
                embed=discord.Embed(
                    title=(
                        f"🧾 注文 #{order_id}"
                    ),
                    description=(
                        f"**{order['product_name']}**\n"
                        f"金額: "
                        f"**{money(order['price'])}**\n\n"
                        "注文を受け付けました。\n"
                        "管理者の入金確認をお待ちください。"
                    ),
                    color=int(
                        config["design"].get(
                            "color",
                            0x8B5CF6
                        )
                    )
                )
            )

        except discord.HTTPException:

            pass


        # ====================================================
        # 購入者への最終結果
        # ====================================================

        message = (

            f"✅ **注文 #{order_id} "
            "を受け付けました！**\n"

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
                "\n⚠️ 専用チャットの作成に失敗しました。"
                "管理者へ通知されています。"
            )


        if notify_error:

            message += (
                "\n⚠️ 管理通知の送信にも失敗しています。"
            )


        if ticket_error:

            print(
                f"[PURCHASE] "
                f"ticket_error #{order_id}: "
                f"{ticket_error}"
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

        value=(
            order[
                "product_name"
            ]
        ),

        inline=True
    )


    embed.add_field(

        name="💰 金額",

        value=money(
            order[
                "price"
            ]
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

        value=(
            order[
                "paypay_url"
            ][:1024]
        ),

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
# 注文管理UI
# ============================================================

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
        label="支払い確認",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def paid(
        self,
        interaction,
        button
    ):

        order = find_order(
            self.order_id
        )


        if not order:

            return await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )


        if order.get(
            "status"
        ) in (
            "cancelled",
            "completed"
        ):

            return await interaction.response.send_message(
                "❌ この注文は処理済みです。",
                ephemeral=True
            )


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
                        order[
                            "buyer_id"
                        ]
                    )
                )
            )


            await buyer.send(
                f"✅ 注文 #{self.order_id} "
                "の支払いを確認しました。"
            )

        except discord.HTTPException:

            pass


    @discord.ui.button(
        label="キャンセル",
        emoji="❌",
        style=discord.ButtonStyle.danger
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        order = find_order(
            self.order_id
        )


        if not order:

            return await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )


        if order.get(
            "status"
        ) in (
            "cancelled",
            "completed"
        ):

            return await interaction.response.send_message(
                "❌ この注文は処理済みです。",
                ephemeral=True
            )


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

                product[
                    "stock"
                ] = (
                    int(
                        product.get(
                            "stock",
                            0
                        )
                    )
                    + 1
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


    @discord.ui.button(
        label="専用チャット",
        emoji="💬",
        style=discord.ButtonStyle.primary
    )
    async def ticket(
        self,
        interaction,
        button
    ):

        order = find_order(
            self.order_id
        )


        if not order:

            return await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )


        cid = int(
            order.get(
                "ticket_channel_id",
                0
            )
            or 0
        )


        channel = (
            interaction.guild.get_channel(
                cid
            )
            if cid
            else
            None
        )


        if channel:

            return await interaction.response.send_message(
                channel.mention,
                ephemeral=True
            )


        await interaction.response.send_message(
            "⚠️ 専用チャットがありません。",
            ephemeral=True
        )


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
# Ticket UI
# ============================================================

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


    async def interaction_check(
        self,
        interaction
    ):

        order = find_order(
            self.order_id
        )


        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return False


        allowed = (
            is_admin(
                interaction.user
            )
            or
            interaction.user.id
            == int(
                order[
                    "buyer_id"
                ]
            )
        )


        if not allowed:

            await interaction.response.send_message(
                "🔒 この注文の関係者専用です。",
                ephemeral=True
            )

            return False


        return True


    @discord.ui.button(
        label="アーカイブ",
        emoji="📁",
        style=discord.ButtonStyle.secondary
    )
    async def archive(
        self,
        interaction,
        button
    ):

        if not is_admin(
            interaction.user
        ):

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


        order = find_order(
            self.order_id
        )


        if not order:

            return await interaction.response.send_message(
                "❌ 注文がありません。",
                ephemeral=True
            )


        try:

            category = await get_or_create_category(
                interaction.guild,
                "📁 購入履歴",
                "archive_category_id"
            )


            buyer = (
                interaction.guild.get_member(
                    int(
                        order[
                            "buyer_id"
                        ]
                    )
                )
            )


            if buyer:

                await interaction.channel.set_permissions(
                    buyer,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )


            await interaction.channel.edit(
                category=category,
                name=(
                    f"history-kira-"
                    f"{self.order_id}"
                )
            )


            order[
                "ticket_archived"
            ] = True


            save_json(
                ORDERS_FILE,
                orders
            )


            await interaction.response.send_message(
                "📁 アーカイブしました。",
                ephemeral=True
            )


        except Exception as e:

            await interaction.response.send_message(
                f"❌ アーカイブ失敗: `{e}`",
                ephemeral=True
            )


    @discord.ui.button(
        label="再開",
        emoji="🔓",
        style=discord.ButtonStyle.success
    )
    async def reopen(
        self,
        interaction,
        button
    ):

        if not is_admin(
            interaction.user
        ):

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


        order = find_order(
            self.order_id
        )


        if order:

            buyer = (
                interaction.guild.get_member(
                    int(
                        order[
                            "buyer_id"
                        ]
                    )
                )
            )


            if buyer:

                try:

                    await interaction.channel.set_permissions(
                        buyer,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        embed_links=True,
                        attach_files=True,
                    )

                except discord.HTTPException:

                    pass


        order[
            "ticket_archived"
        ] = False


        save_json(
            ORDERS_FILE,
            orders
        )


        await interaction.response.send_message(
            "🔓 専用チャットを再開しました。",
            ephemeral=True
        )


    @discord.ui.button(
        label="完了",
        emoji="✅",
        style=discord.ButtonStyle.primary
    )
    async def complete(
        self,
        interaction,
        button
    ):

        if not is_admin(
            interaction.user
        ):

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


        order = find_order(
            self.order_id
        )


        if not order:

            return await interaction.response.send_message(
                "❌ 注文がありません。",
                ephemeral=True
            )


        order[
            "status"
        ] = "completed"


        order[
            "completed_at"
        ] = now_iso()


        save_json(
            ORDERS_FILE,
            orders
        )


        await interaction.response.send_message(
            "✅ 注文を完了にしました。",
            ephemeral=True
        )


    @discord.ui.button(
        label="削除",
        emoji="🗑️",
        style=discord.ButtonStyle.danger
    )
    async def delete(
        self,
        interaction,
        button
    ):

        if not is_admin(
            interaction.user
        ):

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


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


# ============================================================
# 商品追加
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
        label="絵文字（通常/カスタム）",
        required=False,
        default="🛒",
        max_length=100
    )

    description = discord.ui.TextInput(
        label="商品説明",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500
    )


    async def on_submit(
        self,
        interaction
    ):

        name = str(
            self.name.value
        ).strip()


        if not name:

            return await interaction.response.send_message(
                "❌ 商品名を入力してください。",
                ephemeral=True
            )


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

            return await interaction.response.send_message(
                "❌ 価格は1以上、在庫は0以上で入力してください。",
                ephemeral=True
            )


        pid = re.sub(
            r"[^a-z0-9_-]",
            "-",
            name.lower()
        )[:30]


        pid = (
            pid
            or
            f"product-{len(products) + 1}"
        )


        if find_product(
            pid
        ):

            pid = (
                f"{pid}-"
                f"{len(products) + 1}"
            )


        products.append(
            {
                "id":
                    pid,

                "name":
                    name,

                "description":
                    str(
                        self.description.value
                    ),

                "price":
                    price,

                "stock":
                    stock,

                "emoji":
                    str(
                        self.emoji.value
                    )
                    or
                    "🛒",

                "image_url":
                    "",

                "enabled":
                    True
            }
        )


        save_json(
            PRODUCTS_FILE,
            products
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            f"✅ 商品を追加しました。\n"
            f"商品ID: `{pid}`",
            ephemeral=True
        )


# ============================================================
# 商品編集
# ============================================================

class ProductEditModal(
    discord.ui.Modal,
    title="✏️ 商品編集"
):

    def __init__(
        self,
        product_id
    ):

        super().__init__()

        self.product_id = (
            product_id
        )


        product = find_product(
            product_id
        )


        if product is None:

            raise RuntimeError(
                "商品が見つかりません。"
            )


        self.name = discord.ui.TextInput(
            label="商品名",
            default=product[
                "name"
            ],
            max_length=80
        )


        self.price = discord.ui.TextInput(
            label="価格",
            default=str(
                product[
                    "price"
                ]
            )
        )


        self.stock = discord.ui.TextInput(
            label="在庫",
            default=str(
                product[
                    "stock"
                ]
            )
        )


        self.emoji = discord.ui.TextInput(
            label="絵文字（通常/カスタム）",
            default=product.get(
                "emoji",
                "🛒"
            ),
            max_length=100
        )


        self.description = discord.ui.TextInput(
            label="商品説明",
            default=product.get(
                "description",
                ""
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=500
        )


        for item in (
            self.name,
            self.price,
            self.stock,
            self.emoji,
            self.description
        ):

            self.add_item(
                item
            )


    async def on_submit(
        self,
        interaction
    ):

        product = find_product(
            self.product_id
        )


        if not product:

            return await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )


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

            return await interaction.response.send_message(
                "❌ 価格/在庫が正しくありません。",
                ephemeral=True
            )


        product[
            "name"
        ] = str(
            self.name.value
        ).strip()


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


# ============================================================
# 在庫変更
# ============================================================

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


        product = find_product(
            product_id
        )


        if product:

            self.stock.default = str(
                product.get(
                    "stock",
                    0
                )
            )


    async def on_submit(
        self,
        interaction
    ):

        product = find_product(
            self.product_id
        )


        if not product:

            return await interaction.response.send_message(
                "❌ 商品がありません。",
                ephemeral=True
            )


        try:

            value = int(
                str(
                    self.stock.value
                )
            )


            if value < 0:

                raise ValueError


        except ValueError:

            return await interaction.response.send_message(
                "❌ 0以上の数字を入力してください。",
                ephemeral=True
            )


        product[
            "stock"
        ] = value


        save_json(
            PRODUCTS_FILE,
            products
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "✅ 在庫を変更しました。",
            ephemeral=True
        )


# ============================================================
# 商品選択
# ============================================================

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
                    label=(
                        product[
                            "name"
                        ][:100]
                    ),
                    value=(
                        product[
                            "id"
                        ]
                    ),
                    description=(
                        f"{money(product['price'])} "
                        f"/ 在庫 {product['stock']}"
                    )[:100]
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

        product_id = (
            self.values[0]
        )


        if self.mode == "edit":

            return await interaction.response.send_modal(
                ProductEditModal(
                    product_id
                )
            )


        if self.mode == "stock":

            return await interaction.response.send_modal(
                StockModal(
                    product_id
                )
            )


        if self.mode == "delete":

            product = find_product(
                product_id
            )


            if not product:

                return await interaction.response.send_message(
                    "❌ 商品が見つかりません。",
                    ephemeral=True
                )


            products.remove(
                product
            )


            save_json(
                PRODUCTS_FILE,
                products
            )


            await update_purchase_panel()


            return await interaction.response.send_message(
                f"🗑️ `{product['name']}` を削除しました。",
                ephemeral=True
            )


        if self.mode == "toggle":

            product = find_product(
                product_id
            )


            if not product:

                return await interaction.response.send_message(
                    "❌ 商品が見つかりません。",
                    ephemeral=True
                )


            product[
                "enabled"
            ] = not product.get(
                "enabled",
                True
            )


            save_json(
                PRODUCTS_FILE,
                products
            )


            await update_purchase_panel()


            state = (
                "販売中"
                if product[
                    "enabled"
                ]
                else
                "販売停止"
            )


            return await interaction.response.send_message(
                f"✅ `{product['name']}` を "
                f"**{state}** にしました。",
                ephemeral=True
            )


# ============================================================
# 商品選択View
# ============================================================

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


# ============================================================
# 商品画像設定
# ============================================================

class ProductMediaProductSelect(
    discord.ui.Select
):

    def __init__(
        self
    ):

        super().__init__(
            placeholder=(
                "画像/GIFを設定する商品を選択"
            ),
            options=[
                discord.SelectOption(
                    label=(
                        product[
                            "name"
                        ][:100]
                    ),
                    value=(
                        product[
                            "id"
                        ]
                    )
                )

                for product
                in products[:25]
            ]
        )


    async def callback(
        self,
        interaction
    ):

        await interaction.response.send_message(
            "使用する画像/GIFを選択してください。",
            view=MediaLibraryView(
                "product",
                self.values[0]
            ),
            ephemeral=True
        )


class ProductMediaProductSelectView(
    discord.ui.View
):

    def __init__(
        self
    ):

        super().__init__(
            timeout=180
        )


        if products:

            self.add_item(
                ProductMediaProductSelect()
            )


# ============================================================
# 商品プレビュー
# ============================================================

class ProductPreviewSelect(
    discord.ui.Select
):

    def __init__(
        self
    ):

        super().__init__(
            placeholder="プレビューする商品を選択",
            options=[
                discord.SelectOption(
                    label=(
                        product[
                            "name"
                        ][:100]
                    ),
                    value=(
                        product[
                            "id"
                        ]
                    )
                )

                for product
                in products[:25]
            ]
        )


    async def callback(
        self,
        interaction
    ):

        await show_product(
            interaction,
            self.values[0]
        )


class ProductPreviewSelectView(
    discord.ui.View
):

    def __init__(
        self
    ):

        super().__init__(
            timeout=180
        )


        if products:

            self.add_item(
                ProductPreviewSelect()
            )


# ============================================================
# 商品管理View
# ============================================================

class ProductAdminView(
    discord.ui.View
):

    def __init__(
        self
    ):

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
        style=discord.ButtonStyle.success,
        row=0
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
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def edit(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "編集する商品を選択してください。",
            view=ProductSelectView(
                "edit"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="在庫変更",
        emoji="📦",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def stock(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "在庫を変更する商品を選択してください。",
            view=ProductSelectView(
                "stock"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="販売ON/OFF",
        emoji="🔘",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def toggle(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "販売状態を変更する商品を選択してください。",
            view=ProductSelectView(
                "toggle"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="商品削除",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def delete(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "削除する商品を選択してください。",
            view=ProductSelectView(
                "delete"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="画像/GIF",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def image(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "画像/GIFを設定する商品を選択してください。",
            view=ProductMediaProductSelectView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="商品プレビュー",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def preview(
        self,
        interaction,
        button
    ):

        if not products:

            return await interaction.response.send_message(
                "商品がありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "プレビューする商品を選択してください。",
            view=ProductPreviewSelectView(),
            ephemeral=True
        )


# ============================================================
# デザイン
# ============================================================

class DesignTextModal(
    discord.ui.Modal,
    title="✏️ 販売機テキスト"
):

    def __init__(
        self
    ):

        super().__init__()


        d = config[
            "design"
        ]


        self.title_text = discord.ui.TextInput(
            label="タイトル",
            default=d.get(
                "title",
                ""
            ),
            max_length=256
        )


        self.subtitle = discord.ui.TextInput(
            label="サブタイトル",
            default=d.get(
                "subtitle",
                ""
            ),
            max_length=256
        )


        self.description = discord.ui.TextInput(
            label="説明",
            default=d.get(
                "description",
                ""
            ),
            style=discord.TextStyle.paragraph,
            max_length=1000
        )


        self.notice = discord.ui.TextInput(
            label="お知らせ",
            default=d.get(
                "notice",
                ""
            ),
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )


        self.footer = discord.ui.TextInput(
            label="フッター",
            default=d.get(
                "footer",
                ""
            ),
            required=False,
            max_length=256
        )


        for item in (
            self.title_text,
            self.subtitle,
            self.description,
            self.notice,
            self.footer
        ):

            self.add_item(
                item
            )


    async def on_submit(
        self,
        interaction
    ):

        d = config[
            "design"
        ]


        d[
            "title"
        ] = str(
            self.title_text.value
        )


        d[
            "subtitle"
        ] = str(
            self.subtitle.value
        )


        d[
            "description"
        ] = str(
            self.description.value
        )


        d[
            "notice"
        ] = str(
            self.notice.value
        )


        d[
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

    def __init__(
        self
    ):

        super().__init__()


        current = int(
            config[
                "design"
            ].get(
                "color",
                0x8B5CF6
            )
        )


        self.value = discord.ui.TextInput(
            label="16進カラー",
            placeholder="#8B5CF6",
            default=(
                f"#{current:06X}"
            )
        )


        self.add_item(
            self.value
        )


    async def on_submit(
        self,
        interaction
    ):

        value = (
            str(
                self.value.value
            )
            .strip()
            .replace(
                "#",
                ""
            )
        )


        try:

            color = int(
                value,
                16
            )


            if not 0 <= color <= 0xFFFFFF:

                raise ValueError


        except ValueError:

            return await interaction.response.send_message(
                "❌ `#8B5CF6` のような形式で入力してください。",
                ephemeral=True
            )


        config[
            "design"
        ][
            "color"
        ] = color


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

    def __init__(
        self
    ):

        super().__init__()


        self.url = discord.ui.TextInput(
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


        self.add_item(
            self.url
        )


    async def on_submit(
        self,
        interaction
    ):

        value = str(
            self.url.value
        ).strip()


        if (
            value
            and
            not re.match(
                r"^https?://",
                value,
                re.I
            )
        ):

            return await interaction.response.send_message(
                "❌ http(s) のURLを入力してください。",
                ephemeral=True
            )


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


class DesignPresetView(
    discord.ui.View
):

    def __init__(
        self
    ):

        super().__init__(
            timeout=180
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
        label="現在の色を維持",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def keep(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "✅ 現在の色を維持します。",
            ephemeral=True
        )


    @discord.ui.button(
        label="紫",
        emoji="🟣",
        style=discord.ButtonStyle.secondary
    )
    async def purple(
        self,
        interaction,
        button
    ):

        config[
            "design"
        ][
            "color"
        ] = 0x8B5CF6


        save_json(
            CONFIG_FILE,
            config
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "🟣 紫にしました。",
            ephemeral=True
        )


    @discord.ui.button(
        label="青",
        emoji="🔵",
        style=discord.ButtonStyle.secondary
    )
    async def blue(
        self,
        interaction,
        button
    ):

        config[
            "design"
        ][
            "color"
        ] = 0x5865F2


        save_json(
            CONFIG_FILE,
            config
        )


        await update_purchase_panel()


        await interaction.response.send_message(
            "🔵 青にしました。",
            ephemeral=True
        )


class DesignView(
    discord.ui.View
):

    def __init__(
        self
    ):

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
        label="文字を設定",
        emoji="✏️",
        style=discord.ButtonStyle.primary,
        row=0
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
        label="色を設定",
        emoji="🎨",
        style=discord.ButtonStyle.secondary,
        row=0
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
        style=discord.ButtonStyle.secondary,
        row=0
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
        label="かんたん色変更",
        emoji="✨",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def presets(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "他の設定は変更せず、色だけ簡単に変更できます。",
            view=DesignPresetView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="プレビュー",
        emoji="👁️",
        style=discord.ButtonStyle.success,
        row=1
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
            embed=panel_embed(),
            view=PurchaseView(),
            ephemeral=True
        )


# ============================================================
# メディア
# ============================================================

class MediaLibrarySelect(
    discord.ui.Select
):

    def __init__(
        self,
        mode,
        product_id=0
    ):

        self.mode = mode
        self.product_id = (
            product_id
        )


        library = config.get(
            "media_library",
            []
        )


        options = []


        for i, item in enumerate(
            library[:25]
        ):

            options.append(
                discord.SelectOption(
                    label=str(
                        item.get(
                            "name",
                            f"media-{i + 1}"
                        )
                    )[:100],

                    description=str(
                        item.get(
                            "type",
                            "image"
                        )
                    )[:100],

                    value=str(i)
                )
            )


        if not options:

            options = [
                discord.SelectOption(
                    label="メディアがありません",
                    value="none"
                )
            ]


        super().__init__(
            placeholder=(
                "保存済みメディアを選択"
            ),
            options=options
        )


    async def callback(
        self,
        interaction
    ):

        value = self.values[0]


        if value == "none":

            return await interaction.response.send_message(
                "❌ メディアがありません。",
                ephemeral=True
            )


        library = config[
            "media_library"
        ]


        if not (
            0 <= int(value)
            < len(library)
        ):

            return await interaction.response.send_message(
                "❌ メディアが見つかりません。",
                ephemeral=True
            )


        item = library[
            int(value)
        ]


        url = item.get(
            "url",
            ""
        )


        if self.mode == "banner":

            config[
                "design"
            ][
                "banner_url"
            ] = url


            save_json(
                CONFIG_FILE,
                config
            )


            await update_purchase_panel()


            return await interaction.response.send_message(
                "✅ バナー/GIFに設定しました。",
                ephemeral=True
            )


        product = find_product(
            self.product_id
        )


        if not product:

            return await interaction.response.send_message(
                "❌ 商品が見つかりません。",
                ephemeral=True
            )


        product[
            "image_url"
        ] = url


        save_json(
            PRODUCTS_FILE,
            products
        )


        await interaction.response.send_message(
            f"✅ `{product['name']}` の画像/GIFを設定しました。",
            ephemeral=True
        )


class MediaLibraryView(
    discord.ui.View
):

    def __init__(
        self,
        mode,
        product_id=0
    ):

        super().__init__(
            timeout=180
        )


        self.add_item(
            MediaLibrarySelect(
                mode,
                product_id
            )
        )


class MediaView(
    discord.ui.View
):

    def __init__(
        self
    ):

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
        label="メディアチャンネル",
        emoji="🎞️",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def media_channel(
        self,
        interaction,
        button
    ):

        cid = int(
            config.get(
                "media_channel_id",
                0
            )
            or 0
        )


        channel = (
            interaction.guild.get_channel(
                cid
            )
            if cid
            else
            None
        )


        if channel:

            return await interaction.response.send_message(
                f"ここへGIF/画像をドラッグ＆ドロップしてください: {channel.mention}",
                ephemeral=True
            )


        await interaction.response.send_message(
            "❌ 先にチャンネル設定からメディアチャンネルを作成してください。",
            ephemeral=True
        )


    @discord.ui.button(
        label="バナーに設定",
        emoji="🖼️",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def banner(
        self,
        interaction,
        button
    ):

        if not config.get(
            "media_library",
            []
        ):

            return await interaction.response.send_message(
                "❌ まだ画像/GIFがありません。",
                ephemeral=True
            )


        await interaction.response.send_message(
            "バナーに使うメディアを選択してください。",
            view=MediaLibraryView(
                "banner"
            ),
            ephemeral=True
        )


    @discord.ui.button(
        label="保存済みメディア",
        emoji="📚",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def library(
        self,
        interaction,
        button
    ):

        library = config.get(
            "media_library",
            []
        )


        if not library:

            return await interaction.response.send_message(
                "❌ まだ画像/GIFがありません。",
                ephemeral=True
            )


        lines = []


        for i, item in enumerate(
            library[:20]
        ):

            lines.append(
                f"{i + 1}. "
                f"**{item.get('name', 'media')}**"
            )


        await interaction.response.send_message(
            "📚 **保存済みメディア**\n"
            + "\n".join(lines),
            ephemeral=True
        )


    @discord.ui.button(
        label="URLから設定",
        emoji="🔗",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def url(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            BannerModal()
        )


# ============================================================
# チャンネル設定
# ============================================================

class ChannelIdModal(
    discord.ui.Modal
):

    def __init__(
        self,
        key,
        title
    ):

        super().__init__(
            title=title
        )


        self.key = key


        self.value = discord.ui.TextInput(
            label="チャンネルID",
            placeholder="123456789012345678"
        )


        self.add_item(
            self.value
        )


    async def on_submit(
        self,
        interaction
    ):

        try:

            channel_id = int(
                str(
                    self.value.value
                ).strip()
            )

        except ValueError:

            return await interaction.response.send_message(
                "❌ チャンネルIDが正しくありません。",
                ephemeral=True
            )


        channel = interaction.guild.get_channel(
            channel_id
        )


        if not isinstance(
            channel,
            discord.TextChannel
        ):

            return await interaction.response.send_message(
                "❌ そのチャンネルが見つかりません。",
                ephemeral=True
            )


        permissions = channel.permissions_for(
            interaction.guild.me
        )


        if not (
            permissions.view_channel
            and
            permissions.send_messages
        ):

            return await interaction.response.send_message(
                "❌ Botがそのチャンネルを使用できません。",
                ephemeral=True
            )


        config[
            self.key
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

    def __init__(
        self
    ):

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
        label="購入チャンネル",
        emoji="🛒",
        style=discord.ButtonStyle.primary,
        row=0
    )
    async def purchase(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            ChannelIdModal(
                "purchase_channel_id",
                "購入チャンネル"
            )
        )


    @discord.ui.button(
        label="注文通知を作成",
        emoji="📦",
        style=discord.ButtonStyle.success,
        row=0
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

            channel = await get_or_create_order_channel(
                interaction.guild
            )


            await interaction.followup.send(
                f"✅ 注文通知: {channel.mention}",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ 作成失敗: `{e}`",
                ephemeral=True
            )


    @discord.ui.button(
        label="専用チャットカテゴリ",
        emoji="💬",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def tickets(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        try:

            category = await get_or_create_category(
                interaction.guild,
                "💬 購入チャット",
                "ticket_category_id"
            )


            await interaction.followup.send(
                f"✅ 専用チャットカテゴリ: `{category.name}`",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ 作成失敗: `{e}`",
                ephemeral=True
            )


    @discord.ui.button(
        label="メディアチャンネル作成",
        emoji="🎞️",
        style=discord.ButtonStyle.secondary,
        row=1
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
                    ch
                    for ch in guild.text_channels
                    if ch.name
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


            channel = await guild.create_text_channel(
                "vending-media",
                overwrites={
                    guild.default_role:
                        discord.PermissionOverwrite(
                            view_channel=False
                        )
                },
                reason=(
                    f"{BOT_NAME} "
                    "メディア保管チャンネル"
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
                f"✅ メディアチャンネル: "
                f"{channel.mention}",
                ephemeral=True
            )


        except Exception as e:

            await interaction.followup.send(
                f"❌ 作成失敗: `{e}`",
                ephemeral=True
            )


# ============================================================
# 管理パネル
# ============================================================

class AdminPanelView(
    discord.ui.View
):

    def __init__(
        self
    ):

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
        label="販売機",
        emoji="🛒",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="kira:admin:shop"
    )
    async def shop(
        self,
        interaction,
        button
    ):

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )


        channel_id = int(
            config.get(
                "purchase_channel_id",
                0
            )
            or 0
        )


        channel = (
            interaction.guild.get_channel(
                channel_id
            )
            if channel_id
            else
            None
        )


        if not isinstance(
            channel,
            discord.TextChannel
        ):

            await interaction.followup.send(
                "❌ `#購入` を先に作成して、"
                "チャンネル設定から指定してください。",
                ephemeral=True
            )

            return


        perms = channel.permissions_for(
            interaction.guild.me
        )


        if not (
            perms.view_channel
            and
            perms.send_messages
            and
            perms.embed_links
        ):

            await interaction.followup.send(
                "❌ Botが購入チャンネルへ投稿できません。",
                ephemeral=True
            )

            return


        existing = None


        message_id = int(
            config.get(
                "panel_message_id",
                0
            )
            or 0
        )


        if message_id:

            try:

                existing = await channel.fetch_message(
                    message_id
                )

            except discord.HTTPException:

                existing = None


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


        if existing:

            await existing.edit(
                content=content,
                embed=panel_embed(),
                view=PurchaseView()
            )


            message = existing

        else:

            message = await channel.send(
                content=content,
                embed=panel_embed(),
                view=PurchaseView()
            )


        config[
            "panel_channel_id"
        ] = channel.id


        config[
            "panel_message_id"
        ] = message.id


        save_json(
            CONFIG_FILE,
            config
        )


        await interaction.followup.send(
            f"✅ {channel.mention} の販売機を設置/更新しました。",
            ephemeral=True
        )


    @discord.ui.button(
        label="商品",
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
                    "商品追加・編集・在庫変更・"
                    "販売ON/OFF・画像/GIF・削除・"
                    "プレビューをここから操作できます。"
                ),
                color=int(
                    config[
                        "design"
                    ][
                        "color"
                    ]
                )
            ),
            view=ProductAdminView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="見た目",
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
                title="🎨 見た目設定",
                description=(
                    "文字・色・バナー/GIF・"
                    "プレビューを簡単に設定できます。\n\n"
                    "現在の基本デザインは"
                    "勝手に変更されません。"
                ),
                color=int(
                    config[
                        "design"
                    ][
                        "color"
                    ]
                )
            ),
            view=DesignView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="メディア",
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
                    "管理者専用メディアチャンネルへ"
                    "GIF・画像をドラッグ＆ドロップすると、"
                    "自動でメディアライブラリへ保存します。\n\n"
                    "保存したメディアは"
                    "バナーや各商品画像に使えます。"
                ),
                color=int(
                    config[
                        "design"
                    ][
                        "color"
                    ]
                )
            ),
            view=MediaView(),
            ephemeral=True
        )


    @discord.ui.button(
        label="チャンネル",
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
                    f"💬 専用チャットカテゴリ: "
                    f"`{category_name(interaction.guild, config.get('ticket_category_id'))}`\n"
                    f"🎞️ メディア: "
                    f"{channel_mention(interaction.guild, config.get('media_channel_id'))}"
                ),
                color=int(
                    config[
                        "design"
                    ][
                        "color"
                    ]
                )
            ),
            view=ChannelSettingsView(),
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
        )
        or
        0
    )


    if not (
        channel_id
        and
        message_id
    ):

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
            embed=panel_embed(),
            view=PurchaseView()
        )


        return True


    except discord.HTTPException as e:

        print(
            f"[PANEL] 更新失敗: {repr(e)}"
        )

        return False


# ============================================================
# Bot
# ============================================================

class KiraBot(
    commands.Bot
):

    async def setup_hook(
        self
    ):

        print(
            "🔧 Persistent UIを登録しています..."
        )


        # 販売機
        self.add_view(
            PurchaseView()
        )


        # 管理画面
        self.add_view(
            AdminPanelView()
        )


        # 古い販売ボタン復元
        try:

            self.add_dynamic_items(
                ProductPersistentButton
            )

        except Exception as e:

            print(
                "[STARTUP] "
                f"ProductPersistentButton登録失敗: "
                f"{repr(e)}"
            )


        # 保存済み注文ボタン復元
        for order_id, order in orders.items():

            try:

                self.add_view(
                    OrderAdminView(
                        order_id
                    )
                )


                if order.get(
                    "ticket_channel_id"
                ):

                    self.add_view(
                        TicketView(
                            order_id
                        )
                    )


            except Exception as e:

                print(
                    "[STARTUP] "
                    f"注文UI復元失敗 "
                    f"#{order_id}: "
                    f"{repr(e)}"
                )


        # Slash Commands
        await self.add_cog(
            AdminCog(self)
        )


        try:

            synced = await self.tree.sync()

            print(
                f"✅ コマンドを "
                f"{len(synced)} 個同期しました。"
            )

        except Exception as e:

            print(
                f"❌ コマンド同期失敗: "
                f"{repr(e)}"
            )


bot = KiraBot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# ============================================================
# Admin Cog
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
        description="キラの自動販売機 管理画面"
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

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


        embed = discord.Embed(
            title=(
                "⚙️ キラの自動販売機 "
                "— 管理画面"
            ),
            description=(
                "ここから販売機・商品・"
                "見た目・メディア・"
                "チャンネルを管理できます。\n\n"
                "🔒 この画面は管理者にだけ表示されます。"
            ),
            color=int(
                config[
                    "design"
                ][
                    "color"
                ]
            )
        )


        await interaction.response.send_message(
            embed=embed,
            view=AdminPanelView(),
            ephemeral=True
        )


    @app_commands.command(
        name="setup_vending",
        description="自動販売機の初期セットアップ"
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

            return await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


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


            purchase_channel = guild.get_channel(
                int(
                    config.get(
                        "purchase_channel_id",
                        0
                    )
                    or
                    0
                )
            )


            await interaction.followup.send(
                "✅ 初期セットアップ完了\n\n"
                f"📦 注文通知: "
                f"{order_channel.mention}\n"
                f"💬 専用チャットカテゴリ: "
                f"`{ticket_category.name}`\n"
                f"🛒 購入チャンネル: "
                f"{purchase_channel.mention if purchase_channel else '未設定'}\n\n"
                "管理画面の「販売機」から"
                "販売機を設置できます。",
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

    print(
        "=" * 55
    )

    print(
        f"✅ ログインしました: "
        f"{bot.user}"
    )

    print(
        "🛒 キラの自動販売機 起動完了"
    )

    print(
        "=" * 55
    )


    # Guild IDが未設定なら
    # 最初のサーバーを保存
    if not config.get(
        "guild_id"
    ) and bot.guilds:

        config[
            "guild_id"
        ] = bot.guilds[0].id

        save_json(
            CONFIG_FILE,
            config
        )


    # 注文通知チャンネル確認
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
                    "[STARTUP] "
                    f"注文通知チャンネル確認失敗: "
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
        or
        not message.guild
    ):

        return


    media_channel_id = int(
        config.get(
            "media_channel_id",
            0
        )
        or
        0
    )


    if (
        media_channel_id
        and
        message.channel.id
        == media_channel_id
        and
        is_admin(
            message.author
        )
    ):

        library = config.setdefault(
            "media_library",
            []
        )


        changed = False


        for attachment in (
            message.attachments
        ):

            filename = (
                attachment.filename
                .lower()
            )


            is_image = bool(

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
            )


            if not is_image:

                continue


            url = attachment.url


            # 重複防止
            already_exists = any(

                item.get(
                    "url"
                ) == url

                for item
                in library
            )


            if already_exists:

                continue


            library.insert(
                0,
                {
                    "name":
                        attachment.filename,

                    "url":
                        url,

                    "type":
                        attachment.content_type
                        or
                        "image",

                    "created_at":
                        now_iso()
                }
            )


            changed = True


        if changed:

            # 最大50件
            del library[50:]


            save_json(
                CONFIG_FILE,
                config
            )


            try:

                await message.add_reaction(
                    "✅"
                )

            except discord.HTTPException:

                pass


            print(
                "[MEDIA] "
                f"{message.author} "
                "の画像/GIFを保存しました。"
            )


# ============================================================
# 起動
# ============================================================

if __name__ == "__main__":

    token = os.getenv(
        "DISCORD_TOKEN"
    )


    if not token:

        raise RuntimeError(
            "DISCORD_TOKEN が設定されていません。"
        )


    bot.run(
        token
    )
