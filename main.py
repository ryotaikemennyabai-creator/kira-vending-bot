import os
import json
import asyncio
import hashlib
from datetime import datetime, timezone

import discord
from discord.ext import commands

BOT_NAME = "キラの自動販売機"
PRODUCTS_FILE = "products.json"
CONFIG_FILE = "config.json"
ORDERS_FILE = "orders.json"

DEFAULT_PRODUCTS = {
    "コーラ": {"price": 100, "stock": 10, "emoji": "🥤"},
    "お茶": {"price": 100, "stock": 10, "emoji": "🍵"},
    "水": {"price": 80, "stock": 10, "emoji": "💧"},
}

DEFAULT_CONFIG = {
    "purchase_channel_id": None,
    "purchase_message_id": None,
    "order_channel_id": None,
    "ticket_category_id": None,
    "archive_category_id": None,
    "panel_color": 0x5865F2,
    "panel_title": "🛒 キラの自動販売機",
    "panel_description": "下のボタンから商品を選択してください。",
    "order_counter": 0,
}


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
        return json.loads(json.dumps(default))

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        save_json(path, default)
        return json.loads(json.dumps(default))


PRODUCTS = load_json(
    PRODUCTS_FILE,
    DEFAULT_PRODUCTS
)

CONFIG = load_json(
    CONFIG_FILE,
    DEFAULT_CONFIG
)

ORDERS = load_json(
    ORDERS_FILE,
    []
)


for name, data in PRODUCTS.items():

    if not isinstance(data, dict):

        PRODUCTS[name] = {
            "price": 0,
            "stock": 0,
            "emoji": "🛒"
        }

    else:

        data.setdefault(
            "price",
            0
        )

        data.setdefault(
            "stock",
            0
        )

        data.setdefault(
            "emoji",
            "🛒"
        )


for key, value in DEFAULT_CONFIG.items():

    CONFIG.setdefault(
        key,
        value
    )


save_json(
    PRODUCTS_FILE,
    PRODUCTS
)

save_json(
    CONFIG_FILE,
    CONFIG
)


intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

purchase_lock = asyncio.Lock()


def is_admin(interaction):

    return bool(
        interaction.guild
        and interaction.user.guild_permissions.administrator
    )


def order_by_id(order_id):

    return next(
        (
            order
            for order in ORDERS
            if order.get("order_id") == order_id
        ),
        None
    )


def product_key(name):

    return hashlib.sha256(
        name.encode("utf-8")
    ).hexdigest()[:16]


def next_order_id():

    CONFIG["order_counter"] = int(
        CONFIG.get(
            "order_counter",
            0
        )
    ) + 1

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return f"KIRA-{CONFIG['order_counter']:05d}"


def make_panel_embed():

    lines = []

    for name, data in PRODUCTS.items():

        price = int(
            data.get(
                "price",
                0
            )
        )

        stock = int(
            data.get(
                "stock",
                0
            )
        )

        emoji = data.get(
            "emoji",
            "🛒"
        )

        status = (
            f"🟢 在庫 {stock}個"
            if stock > 0
            else
            "🔴 SOLD OUT"
        )

        lines.append(
            f"{emoji} **{name}** "
            f"` {price:,}円 ` "
            f"{status}"
        )

    embed = discord.Embed(
        title=CONFIG.get(
            "panel_title",
            "🛒 キラの自動販売機"
        ),
        description=(
            CONFIG.get(
                "panel_description",
                "下のボタンから商品を選択してください。"
            )
            + "\n\n"
            "💳 **PayPay送金URLで支払い**"
            + "\n"
            "💬 購入後は専用チャットを自動作成します。"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    embed.add_field(
        name="🛍️ 商品一覧",
        value=(
            "\n".join(lines)[:1024]
            if lines
            else
            "商品がありません。"
        ),
        inline=False
    )

    embed.set_footer(
        text="KIRA VENDING"
    )

    return embed


def make_vending_view():

    view = discord.ui.View(
        timeout=None
    )

    for i, (
        name,
        data
    ) in enumerate(
        list(PRODUCTS.items())[:25]
    ):

        stock = int(
            data.get(
                "stock",
                0
            )
        )

        price = int(
            data.get(
                "price",
                0
            )
        )

        button = discord.ui.Button(
            label=(
                f"{name} • {price:,}円"
                if stock > 0
                else
                f"{name} • SOLD OUT"
            )[:80],

            emoji=data.get(
                "emoji",
                "🛒"
            ),

            style=(
                discord.ButtonStyle.green
                if stock > 0
                else
                discord.ButtonStyle.gray
            ),

            disabled=(
                stock <= 0
            ),

            custom_id=(
                f"kira:product:"
                f"{product_key(name)}"
            ),

            row=i // 5
        )

        view.add_item(
            button
        )

    return view


class ProductButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=r"kira:product:(?P<key>[0-9a-f]{16})"
):

    def __init__(
        self,
        item,
        key
    ):

        super().__init__(
            item
        )

        self.key = key

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            match["key"]
        )

    async def callback(
        self,
        interaction
    ):

        name = next(
            (
                n
                for n in PRODUCTS
                if product_key(n) == self.key
            ),
            None
        )

        if not name:

            await interaction.response.send_message(
                "❌ この商品は現在販売されていません。",
                ephemeral=True
            )

            return

        data = PRODUCTS[name]

        if int(
            data.get(
                "stock",
                0
            )
        ) <= 0:

            await interaction.response.send_message(
                "🔴 この商品は売り切れです。",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title=(
                f"{data.get('emoji', '🛒')} 購入確認"
            ),
            description=(
                f"## {data.get('emoji', '🛒')} {name}\n\n"
                f"💴 **価格** "
                f"` {int(data.get('price', 0)):,}円 `\n"
                f"📦 **在庫** "
                f"` {int(data.get('stock', 0))}個 `\n\n"
                "この商品を購入しますか？"
            ),
            color=int(
                CONFIG.get(
                    "panel_color",
                    0x5865F2
                )
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=PurchaseConfirmView(
                name
            ),
            ephemeral=True
        )


class PurchaseConfirmView(
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
        emoji="🛒",
        style=discord.ButtonStyle.green
    )
    async def buy(
        self,
        interaction,
        button
    ):

        product = PRODUCTS.get(
            self.product_name
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
                "🔴 売り切れです。",
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
        emoji="✖️",
        style=discord.ButtonStyle.gray
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

        self.url = discord.ui.TextInput(
            label="PayPay送金URL",
            placeholder="https://pay.paypay.ne.jp/...",
            required=True,
            max_length=500
        )

        self.add_item(
            self.url
        )

    async def on_submit(
        self,
        interaction
    ):

        # 最初に応答してタイムアウトを防止
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        if not interaction.guild:

            await interaction.followup.send(
                "❌ サーバー内でのみ購入できます。",
                ephemeral=True
            )

            return

        async with purchase_lock:

            product = PRODUCTS.get(
                self.product_name
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

                await interaction.followup.send(
                    "🔴 売り切れです。",
                    ephemeral=True
                )

                return

            url = self.url.value.strip()

            if not (
                url.startswith(
                    "https://"
                )
                or
                url.startswith(
                    "http://"
                )
            ):

                await interaction.followup.send(
                    "❌ PayPay送金URLの形式が正しくありません。",
                    ephemeral=True
                )

                return

            oid = next_order_id()

            order = {
                "order_id": oid,
                "user_id": interaction.user.id,
                "username": str(
                    interaction.user
                ),
                "guild_id": interaction.guild.id,
                "product": self.product_name,
                "price": int(
                    product.get(
                        "price",
                        0
                    )
                ),
                "paypay_url": url,
                "status": "支払い確認待ち",
                "created_at": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
                "ticket_channel_id": None,
                "ticket_created": False
            }

            product["stock"] = (
                int(
                    product.get(
                        "stock",
                        0
                    )
                ) - 1
            )

            ORDERS.append(
                order
            )

            save_json(
                PRODUCTS_FILE,
                PRODUCTS
            )

            save_json(
                ORDERS_FILE,
                ORDERS
            )

        try:

            await update_vending_panel()

        except Exception as e:

            print(
                f"[PANEL] 更新失敗: {repr(e)}"
            )

        ticket = None

        try:

            ticket = await create_ticket(
                interaction.guild,
                interaction.user,
                order
            )

            order[
                "ticket_created"
            ] = True

            save_json(
                ORDERS_FILE,
                ORDERS
            )

        except Exception as e:

            print(
                f"[PURCHASE] 専用チャット作成失敗 "
                f"#{oid}: {repr(e)}"
            )

        try:

            ch = await ensure_order_channel(
                interaction.guild
            )

            embed = discord.Embed(
                title="🛒 新しい注文",
                description=(
                    f"🧾 注文番号：`{oid}`\n"
                    f"👤 購入者："
                    f"<@{interaction.user.id}>\n"
                    f"🛍️ 商品："
                    f"**{self.product_name}**\n"
                    f"💴 金額："
                    f"`{order['price']:,}円`\n\n"
                    "🟡 支払い確認待ち"
                ),
                color=0xF1C40F
            )

            embed.add_field(
                name="💳 PayPay送金URL",
                value=url[:1024],
                inline=False
            )

            await ch.send(
                embed=embed,
                view=OrderView(
                    oid
                )
            )

        except Exception as e:

            print(
                f"[PURCHASE] 注文通知失敗 "
                f"#{oid}: {repr(e)}"
            )

        try:

            await interaction.user.send(
                "🛒 **キラの自動販売機**\n\n"
                f"注文番号：`{oid}`\n"
                f"商品：{self.product_name}\n"
                f"金額：`{order['price']:,}円`\n"
                "状態：🟡 支払い確認待ち\n"
                f"専用チャット："
                f"{ticket.mention if ticket else '⚠️ 作成失敗'}"
            )

        except Exception:
            pass

        msg = (
            f"✅ **注文 {oid} を受け付けました！**\n"
            f"🛍️ 商品：**{self.product_name}**\n"
            f"💴 金額：`{order['price']:,}円`\n"
        )

        if ticket:

            msg += (
                f"💬 専用チャット："
                f"{ticket.mention}"
            )

        else:

            msg += (
                "⚠️ 専用チャットの作成に失敗しました。"
            )

        await interaction.followup.send(
            msg,
            ephemeral=True
        )


async def get_or_create_category(
    guild,
    config_key,
    name
):

    saved = CONFIG.get(
        config_key
    )

    if saved:

        try:

            ch = guild.get_channel(
                int(saved)
            )

            if isinstance(
                ch,
                discord.CategoryChannel
            ):

                return ch

        except Exception:
            pass

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
        overwrites={
            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            me:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
        },
        reason=f"{BOT_NAME} 自動作成"
    )

    CONFIG[
        config_key
    ] = category.id

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return category


async def create_ticket(
    guild,
    user,
    order
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
            "ticket_category_id",
            "💬 購入チャット"
        )

    except Exception as e:

        print(
            f"[TICKET] カテゴリ作成失敗、"
            f"サーバー直下で作成: {repr(e)}"
        )

    channel_name = (
        f"chat-{order['order_id'].lower()}"
    )

    try:

        channel = await guild.create_text_channel(
            channel_name,
            category=category,
            topic=(
                f"{BOT_NAME} | "
                f"注文 {order['order_id']} | "
                f"購入者 {user.id}"
            ),
            reason=(
                f"注文 {order['order_id']} "
                "専用チャット"
            )
        )

    except discord.Forbidden:

        channel = await guild.create_text_channel(
            channel_name,
            topic=(
                f"{BOT_NAME} | "
                f"注文 {order['order_id']} | "
                f"購入者 {user.id}"
            ),
            reason=(
                f"注文 {order['order_id']} "
                "専用チャット再試行"
            )
        )

    # 一般ユーザーには見せない
    await channel.set_permissions(
        guild.default_role,
        view_channel=False
    )

    # Bot
    await channel.set_permissions(
        me,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True,
        manage_channels=True,
        manage_messages=True
    )

    # 購入者
    await channel.set_permissions(
        user,
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        embed_links=True
    )

    order[
        "ticket_channel_id"
    ] = channel.id

    save_json(
        ORDERS_FILE,
        ORDERS
    )

    embed = discord.Embed(
        title="💬 購入専用チャット",
        description=(
            f"🧾 注文番号："
            f"`{order['order_id']}`\n"
            f"🛍️ 商品："
            f"**{order['product']}**\n"
            f"💴 価格："
            f"`{order['price']:,}円`\n\n"
            "🟡 支払い確認待ち\n\n"
            "このチャットは"
            "購入者・管理者・Botのみが利用できます。"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    await channel.send(
        content=user.mention,
        embed=embed,
        view=TicketView(
            order["order_id"]
        ),
        allowed_mentions=(
            discord.AllowedMentions(
                users=True
            )
        )
    )

    return channel


async def ensure_order_channel(
    guild
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

    channel = None

    saved = CONFIG.get(
        "order_channel_id"
    )

    if saved:

        try:

            c = guild.get_channel(
                int(saved)
            )

            if isinstance(
                c,
                discord.TextChannel
            ):

                channel = c

        except Exception:
            pass

    if channel is None:

        channel = next(
            (
                c
                for c in guild.text_channels
                if c.name == "注文通知"
            ),
            None
        )

    if channel is None:

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
                        manage_channels=True
                    )
            },
            topic=(
                f"{BOT_NAME} "
                "注文通知（管理者専用）"
            ),
            reason=(
                f"{BOT_NAME} "
                "注文通知チャンネル自動作成"
            )
        )

    else:

        # 既存の #注文通知 も一般ユーザーから隠す
        await channel.set_permissions(
            guild.default_role,
            view_channel=False
        )

        await channel.set_permissions(
            me,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            manage_channels=True
        )

    CONFIG[
        "order_channel_id"
    ] = channel.id

    save_json(
        CONFIG_FILE,
        CONFIG
    )

    return channel


class OrderView(
    discord.ui.View
):

    def __init__(
        self,
        order_id
    ):

        super().__init__(
            timeout=None
        )

        self.add_item(
            discord.ui.Button(
                label="支払い確認済み",
                emoji="✅",
                style=discord.ButtonStyle.green,
                custom_id=(
                    f"kira:order:"
                    f"paid:{order_id}"
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="キャンセル",
                emoji="❌",
                style=discord.ButtonStyle.red,
                custom_id=(
                    f"kira:order:"
                    f"cancel:{order_id}"
                )
            )
        )


class OrderActionButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=(
        r"kira:order:"
        r"(?P<action>paid|cancel):"
        r"(?P<oid>KIRA-\d{5})"
    )
):

    def __init__(
        self,
        item,
        action,
        oid
    ):

        super().__init__(
            item
        )

        self.action = action
        self.oid = oid

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            match["action"],
            match["oid"]
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        order = order_by_id(
            self.oid
        )

        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return

        if self.action == "paid":

            order[
                "status"
            ] = "支払い確認済み"

            save_json(
                ORDERS_FILE,
                ORDERS
            )

            await interaction.response.send_message(
                "✅ 支払い確認済みにしました。",
                ephemeral=True
            )

            try:

                user = await bot.fetch_user(
                    int(
                        order["user_id"]
                    )
                )

                await user.send(
                    "✅ **支払い確認済み**\n\n"
                    f"注文番号："
                    f"`{order['order_id']}`\n"
                    f"商品："
                    f"{order['product']}\n"
                    f"価格："
                    f"`{order['price']:,}円`"
                )

            except Exception:
                pass

        else:

            if not order.get(
                "cancelled_stock_returned",
                False
            ):

                product = PRODUCTS.get(
                    order["product"]
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
                        PRODUCTS
                    )

                order[
                    "cancelled_stock_returned"
                ] = True

            order[
                "status"
            ] = "キャンセル"

            save_json(
                ORDERS_FILE,
                ORDERS
            )

            await update_vending_panel()

            await interaction.response.send_message(
                "❌ キャンセルしました。\n"
                "在庫を1個戻しました。",
                ephemeral=True
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

        self.add_item(
            discord.ui.Button(
                label="履歴として保存",
                emoji="🗃️",
                style=discord.ButtonStyle.blurple,
                custom_id=(
                    f"kira:ticket:"
                    f"archive:{order_id}"
                )
            )
        )

        self.add_item(
            discord.ui.Button(
                label="チャット削除",
                emoji="🗑️",
                style=discord.ButtonStyle.red,
                custom_id=(
                    f"kira:ticket:"
                    f"delete:{order_id}"
                )
            )
        )


class TicketActionButton(
    discord.ui.DynamicItem[
        discord.ui.Button
    ],
    template=(
        r"kira:ticket:"
        r"(?P<action>archive|delete):"
        r"(?P<oid>KIRA-\d{5})"
    )
):

    def __init__(
        self,
        item,
        action,
        oid
    ):

        super().__init__(
            item
        )

        self.action = action
        self.oid = oid

    @classmethod
    async def from_custom_id(
        cls,
        interaction,
        item,
        match
    ):

        return cls(
            item,
            match["action"],
            match["oid"]
        )

    async def callback(
        self,
        interaction
    ):

        order = order_by_id(
            self.oid
        )

        if not order:

            await interaction.response.send_message(
                "❌ 注文が見つかりません。",
                ephemeral=True
            )

            return

        allowed = (
            is_admin(interaction)
            or
            interaction.user.id
            == int(
                order["user_id"]
            )
        )

        if not allowed:

            await interaction.response.send_message(
                "🔒 権限がありません。",
                ephemeral=True
            )

            return

        if self.action == "delete":

            await interaction.response.send_message(
                "🗑️ チャットを削除します。",
                ephemeral=True
            )

            await asyncio.sleep(
                1
            )

            try:

                await interaction.channel.delete(
                    reason=(
                        f"注文 {self.oid} "
                        "チャット削除"
                    )
                )

            except Exception as e:

                print(
                    f"[TICKET DELETE] "
                    f"{repr(e)}"
                )

        else:

            try:

                category = (
                    await get_or_create_category(
                        interaction.guild,
                        "archive_category_id",
                        "📁 購入履歴"
                    )
                )

                await interaction.channel.edit(
                    category=category,
                    name=(
                        f"history-"
                        f"{self.oid.lower()}"
                    )
                )

                await interaction.response.send_message(
                    "🗃️ 履歴として保存しました。",
                    ephemeral=True
                )

            except Exception as e:

                await interaction.response.send_message(
                    f"❌ 保存失敗: `{e}`",
                    ephemeral=True
                )


class AddProductModal(
    discord.ui.Modal
):

    def __init__(self):

        super().__init__(
            title="🛍️ 商品追加"
        )

        self.name = discord.ui.TextInput(
            label="商品名",
            required=True,
            max_length=40
        )

        self.price = discord.ui.TextInput(
            label="価格",
            required=True
        )

        self.stock = discord.ui.TextInput(
            label="在庫",
            required=True
        )

        self.emoji = discord.ui.TextInput(
            label="絵文字",
            required=True,
            max_length=10
        )

        for item in (
            self.name,
            self.price,
            self.stock,
            self.emoji
        ):

            self.add_item(
                item
            )

    async def on_submit(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        try:

            price = int(
                self.price.value
            )

            stock = int(
                self.stock.value
            )

            if price <= 0 or stock < 0:

                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                "❌ 価格/在庫が正しくありません。",
                ephemeral=True
            )

            return

        name = self.name.value.strip()

        PRODUCTS[name] = {
            "price": price,
            "stock": stock,
            "emoji": (
                self.emoji.value.strip()
                or
                "🛒"
            )
        }

        save_json(
            PRODUCTS_FILE,
            PRODUCTS
        )

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ 商品を追加しました。",
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

        options = [
            discord.SelectOption(
                label=name,
                emoji=data.get(
                    "emoji",
                    "🛒"
                ),
                value=name
            )

            for name, data
            in list(
                PRODUCTS.items()
            )[:25]
        ]

        super().__init__(
            placeholder="商品を選択",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        name = self.values[0]

        if self.mode == "delete":

            PRODUCTS.pop(
                name,
                None
            )

            save_json(
                PRODUCTS_FILE,
                PRODUCTS
            )

            await update_vending_panel()

            await interaction.response.send_message(
                f"🗑️ **{name}** を削除しました。",
                ephemeral=True
            )

        else:

            await interaction.response.send_modal(
                StockModal(
                    name
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
            timeout=120
        )

        if PRODUCTS:

            self.add_item(
                ProductSelect(
                    mode
                )
            )


class StockModal(
    discord.ui.Modal
):

    def __init__(
        self,
        name
    ):

        super().__init__(
            title=f"📦 {name} 在庫"
        )

        self.name = name

        self.stock = discord.ui.TextInput(
            label="新しい在庫数",
            default=str(
                PRODUCTS[name].get(
                    "stock",
                    0
                )
            ),
            required=True
        )

        self.add_item(
            self.stock
        )

    async def on_submit(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        try:

            stock = int(
                self.stock.value
            )

            if stock < 0:

                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                "❌ 0以上の数字を入力してください。",
                ephemeral=True
            )

            return

        PRODUCTS[
            self.name
        ][
            "stock"
        ] = stock

        save_json(
            PRODUCTS_FILE,
            PRODUCTS
        )

        await update_vending_panel()

        await interaction.response.send_message(
            "✅ 在庫を変更しました。",
            ephemeral=True
        )


class AdminView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        self.add_item(
            AdminInstallButton()
        )

        self.add_item(
            AdminOrderButton()
        )

        self.add_item(
            AdminAddButton()
        )

        self.add_item(
            AdminStockButton()
        )

        self.add_item(
            AdminDeleteButton()
        )

        self.add_item(
            AdminRefreshButton()
        )


class AdminInstallButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="自販機を設置",
            emoji="🛒",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:install"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        msg = await interaction.channel.send(
            embed=make_panel_embed(),
            view=make_vending_view()
        )

        CONFIG[
            "purchase_channel_id"
        ] = interaction.channel.id

        CONFIG[
            "purchase_message_id"
        ] = msg.id

        save_json(
            CONFIG_FILE,
            CONFIG
        )

        await interaction.response.send_message(
            "✅ 自販機を設置しました。",
            ephemeral=True
        )


class AdminOrderButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="注文通知を作成/確認",
            emoji="📩",
            style=discord.ButtonStyle.blurple,
            custom_id="kira:admin:order"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        try:

            ch = await ensure_order_channel(
                interaction.guild
            )

            await interaction.response.send_message(
                f"📩 注文通知：{ch.mention}",
                ephemeral=True
            )

        except Exception as e:

            await interaction.response.send_message(
                f"❌ 作成失敗：`{e}`",
                ephemeral=True
            )


class AdminAddButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="商品追加",
            emoji="➕",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:add"
        )

    async def callback(
        self,
        interaction
    ):

        if is_admin(
            interaction
        ):

            await interaction.response.send_modal(
                AddProductModal()
            )

        else:

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )


class AdminStockButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="在庫変更",
            emoji="📦",
            style=discord.ButtonStyle.gray,
            custom_id="kira:admin:stock"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "📦 商品を選択してください。",
            view=ProductSelectView(
                "stock"
            ),
            ephemeral=True
        )


class AdminDeleteButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="商品削除",
            emoji="🗑️",
            style=discord.ButtonStyle.red,
            custom_id="kira:admin:delete"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🗑️ 商品を選択してください。",
            view=ProductSelectView(
                "delete"
            ),
            ephemeral=True
        )


class AdminRefreshButton(
    discord.ui.Button
):

    def __init__(self):

        super().__init__(
            label="パネル更新",
            emoji="🔄",
            style=discord.ButtonStyle.green,
            custom_id="kira:admin:refresh"
        )

    async def callback(
        self,
        interaction
    ):

        if not is_admin(
            interaction
        ):

            await interaction.response.send_message(
                "🔒 管理者専用です。",
                ephemeral=True
            )

            return

        ok = await update_vending_panel()

        await interaction.response.send_message(
            (
                "✅ パネルを更新しました。"
                if ok
                else
                "⚠️ パネルが設定されていません。"
            ),
            ephemeral=True
        )


async def update_vending_panel():

    cid = CONFIG.get(
        "purchase_channel_id"
    )

    mid = CONFIG.get(
        "purchase_message_id"
    )

    if not cid or not mid:

        return False

    try:

        channel = (
            bot.get_channel(
                int(cid)
            )
            or
            await bot.fetch_channel(
                int(cid)
            )
        )

        msg = await channel.fetch_message(
            int(mid)
        )

        await msg.edit(
            embed=make_panel_embed(),
            view=make_vending_view()
        )

        return True

    except Exception as e:

        print(
            f"[PANEL] 更新失敗: {repr(e)}"
        )

        return False


@bot.event
async def setup_hook():

    print(
        "🔧 Persistent UIを登録しています..."
    )

    bot.add_dynamic_items(
        ProductButton,
        OrderActionButton,
        TicketActionButton
    )

    bot.add_view(
        AdminView()
    )

    try:

        synced = await bot.tree.sync()

        print(
            f"✅ コマンドを "
            f"{len(synced)} 個同期しました。"
        )

    except Exception as e:

        print(
            f"❌ コマンド同期失敗: "
            f"{repr(e)}"
        )


@bot.event
async def on_ready():

    print(
        f"✅ ログインしました: "
        f"{bot.user}"
    )

    for guild in bot.guilds:

        try:

            await ensure_order_channel(
                guild
            )

        except Exception as e:

            print(
                f"[STARTUP] 注文通知チャンネル失敗: "
                f"{repr(e)}"
            )

    print(
        "🛒 キラの自動販売機 起動完了"
    )


@bot.tree.command(
    name="ping",
    description="Botの動作確認"
)
async def ping(
    interaction
):

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🏓 Pong!",
        ephemeral=True
    )


@bot.tree.command(
    name="admin",
    description="キラの自動販売機 管理画面"
)
async def admin(
    interaction
):

    if not is_admin(
        interaction
    ):

        await interaction.response.send_message(
            "🔒 管理者専用です。",
            ephemeral=True
        )

        return

    embed = discord.Embed(
        title="👑 KIRA VENDING",
        description=(
            "🛒 自販機設置\n"
            "📩 注文通知\n"
            "➕ 商品追加\n"
            "📦 在庫変更\n"
            "🗑️ 商品削除\n"
            "🔄 パネル更新"
        ),
        color=int(
            CONFIG.get(
                "panel_color",
                0x5865F2
            )
        )
    )

    await interaction.response.send_message(
        embed=embed,
        view=AdminView(),
        ephemeral=True
    )


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
