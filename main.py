
# =========================================================
# Discord
# =========================================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# 共通
# =========================================================

def is_admin(interaction: discord.Interaction):
    return bool(interaction.guild and interaction.user.guild_permissions.administrator)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def short_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def product_custom_id(name):
    return f"kira:product:{short_hash(name)}"


def order_id_custom_id(prefix, order_id):
    return f"kira:{prefix}:{order_id}"


def find_order(order_id):
    return next((o for o in ORDERS if o.get("order_id") == order_id), None)


def create_order_id():
    counter = int(CONFIG.get("order_counter", 0))
    existing = {o.get("order_id") for o in ORDERS}
    while True:
        counter += 1
        order_id = f"KIRA-{counter:05d}"
        if order_id not in existing:
            CONFIG["order_counter"] = counter
            save_json(CONFIG_FILE, CONFIG)
            return order_id


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def valid_http_url(url):
    return url.startswith("https://") or url.startswith("http://")


def permission_problem(channel):
    if not getattr(channel, "guild", None) or not channel.guild.me:
        return "Botのメンバー情報を取得できません。"
    perms = channel.permissions_for(channel.guild.me)
    missing = []
    if not perms.view_channel:
        missing.append("チャンネルを見る")
    if not perms.send_messages:
        missing.append("メッセージを送信")
    if not perms.embed_links:
        missing.append("埋め込みリンク")
    if not perms.read_message_history:
        missing.append("メッセージ履歴を読む")
    return "不足権限: " + " / ".join(missing) if missing else None


def color_value():
    return safe_int(CONFIG.get("panel_color"), 0x5865F2)


def product_status(stock):
    return "🟢 在庫あり" if stock > 0 else "🔴 SOLD OUT"

# =========================================================
# パネル / 商品表示
# =========================================================

def create_panel_embed():
    embed = discord.Embed(
        title=CONFIG.get("panel_title", DEFAULT_CONFIG["panel_title"]),
        description=(
            CONFIG.get("panel_description", DEFAULT_CONFIG["panel_description"])
            + "\n\n"
            + CONFIG.get("shop_notice", DEFAULT_CONFIG["shop_notice"])
        ),
        color=color_value(),
    )

    lines = []
    for name, data in PRODUCTS.items():
        price = safe_int(data.get("price"))
        stock = safe_int(data.get("stock"))
        emoji = data.get("emoji") or "🛒"
        lines.append(f"{emoji} **{name}**　`{price:,}円`　{product_status(stock)} `({stock}個)`")

    if lines:
        text = "\n".join(lines)
        if len(text) > 1024:
            text = text[:1000] + "\n…"
        embed.add_field(name="🛍️ 商品一覧", value=text, inline=False)
    else:
        embed.add_field(name="🛍️ 商品一覧", value="現在販売中の商品はありません。", inline=False)

    image_url = CONFIG.get("panel_image_url", "")
    thumbnail_url = CONFIG.get("panel_thumbnail_url", "")
    if valid_http_url(image_url):
        embed.set_image(url=image_url)
    if valid_http_url(thumbnail_url):
        embed.set_thumbnail(url=thumbnail_url)

    embed.set_footer(text=CONFIG.get("panel_footer", DEFAULT_CONFIG["panel_footer"]))
    return embed


BUTTON_STYLES = [
    discord.ButtonStyle.green,
    discord.ButtonStyle.blurple,
    discord.ButtonStyle.gray,
    discord.ButtonStyle.red,
]


class ProductButton(discord.ui.Button):
    def __init__(self, name, data, index):
        stock = safe_int(data.get("stock"))
        price = safe_int(data.get("price"))
        emoji = data.get("emoji") or "🛒"
        sold_out = stock <= 0
        super().__init__(
            label=(f"{name} • SOLD OUT" if sold_out else f"{name} • {price:,}円")[:80],
            emoji=emoji,
            style=discord.ButtonStyle.gray if sold_out else BUTTON_STYLES[index % len(BUTTON_STYLES)],
            disabled=sold_out,
            custom_id=product_custom_id(name),
            row=index // 5,
        )
        self.product_name = name

    async def callback(self, interaction):
        product = PRODUCTS.get(self.product_name)
        if not product:
            return await interaction.response.send_message("❌ この商品は現在販売されていません。", ephemeral=True)
        stock = safe_int(product.get("stock"))
        if stock <= 0:
            return await interaction.response.send_message("🔴 この商品は売り切れです。", ephemeral=True)

        embed = discord.Embed(
            title=f"{product.get('emoji', '🛒')} 購入確認",
            description=(
                f"## {product.get('emoji', '🛒')} {self.product_name}\n\n"
                f"💴 **価格**\n`{safe_int(product.get('price')):,}円`\n\n"
                f"📦 **在庫**\n`{stock}個`\n\n"
                "購入を続けるとPayPay送金URLの入力画面が開きます。"
            ),
            color=color_value(),
        )
        if valid_http_url(product.get("image_url", "")):
            embed.set_image(url=product["image_url"])
        await interaction.response.send_message(embed=embed, view=PurchaseConfirmView(self.product_name), ephemeral=True)


class VendingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for index, (name, data) in enumerate(list(PRODUCTS.items())[:MAX_PRODUCTS]):
            self.add_item(ProductButton(name, data, index))

# =========================================================
# 購入フロー
# =========================================================

class PurchaseConfirmView(discord.ui.View):
    def __init__(self, product_name):
        super().__init__(timeout=120)
        self.product_name = product_name

    @discord.ui.button(label="購入する", emoji="🛒", style=discord.ButtonStyle.green)
    async def confirm(self, interaction, button):
        product = PRODUCTS.get(self.product_name)
        if not product or safe_int(product.get("stock")) <= 0:
            return await interaction.response.send_message("🔴 売り切れです。", ephemeral=True)
        await interaction.response.send_modal(PurchaseModal(self.product_name))
