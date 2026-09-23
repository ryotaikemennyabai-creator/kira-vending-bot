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

# PayPay送金URLの正規表現（厳格化）
PAYPAY_URL_PATTERN = re.compile(r"^https://(paypay\.ne\.jp|paypay\.me)/(page/link/[A-Za-z0-9_]+|[A-Za-z0-9_]+)$")

# 排他制御用ロック（データ破損防止）
data_lock = asyncio.Lock()


# ==========================================
# JSONヘルパー関数
# ==========================================
def load_json(filepath: str, default_data: Any) -> Any:
    """JSONファイルを読み込む。存在しない場合はデフォルト値を保存して返す。"""
    if not os.path.exists(filepath):
        save_json(filepath, default_data)
        return default_data
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Error] {filepath} の読み込みに失敗しました: {e}")
        return default_data


def save_json(filepath: str, data: Any) -> None:
    """データをJSONファイルに書き込む。"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[Error] {filepath} の保存に失敗しました: {e}")


# 初期データのロード
config_data = load_json(CONFIG_FILE, {
    "ticket_category_id": None,
    "manager_role_id": None,
    "log_channel_id": None
})

shop_data = load_json(SHOP_FILE, {
    "panel_message_id": None,
    "products": {},  # "product_id": {"name": "商品名", "price": 100, "stock": ["code1", "code2"]}
    "tickets": {}    # "ticket_id": {"channel_id": 123, "user_id": 456, "product_id": "p1", "count": 1, "status": "CREATED"}
})


# ==========================================
# 権限チェック用ヘルパー関数
# ==========================================
def is_manager(interaction: discord.Interaction) -> bool:
    """実行者が管理者権限を持っているか、または設定された管理者ロールを持っているかチェック"""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    
    # サーバー管理者権限を所有しているか
    if interaction.user.guild_permissions.administrator:
        return True
    
    # 管理者ロールが設定されており、それを保持しているか
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
        # 永続View・DynamicItemの登録
        self.add_view(ShopPanelView())
        self.add_dynamic_items(TicketPayButton)
        self.add_dynamic_items(AdminApproveButton)
        self.add_dynamic_items(AdminRejectButton)
        self.add_dynamic_items(CloseTicketButton)
        print("[System] UIコンポーネントおよびDynamicItemを正常に再登録しました。")


bot = VendBot()


# ==========================================
# Modal UI Components (入力フォーム)
# ==========================================
class QuantityModal(discord.ui.Modal, title="🛒 商品の購入個数入力"):
    quantity_input = discord.ui.TextInput(
        label="購入する数量を入力してください",
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
            await interaction.followup.send("❌ 数量は1以上の有効な整数を入力してください。", ephemeral=True)
            return

        async with data_lock:
            product = shop_data["products"].get(self.product_id)
            if not product:
                await interaction.followup.send("❌ 指定された商品が見つかりません。", ephemeral=True)
                return

            stock_list = product.get("stock", [])
            if len(stock_list) < count:
                await interaction.followup.send(
                    f"❌ 在庫が不足しています。（現在の在庫: {len(stock_list)}個）", 
                    ephemeral=True
                )
                return

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ サーバー内で実行してください。", ephemeral=True)
                return

            # カテゴリの取得と存在確認
            category_id = config_data.get("ticket_category_id")
            category = guild.get_channel(int(category_id)) if category_id else None

            # カテゴリ内チャンネル上限チェック（Discord制限：最大50個）
            if category and len(category.channels) >= 48:
                await interaction.followup.send(
                    "❌ 現在購入問い合わせが混み合っております。時間を置いて再度お試しください。", 
                    ephemeral=True
                )
                return

            # 専用チャット（チケット）のパーミッション設定
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }

            # 管理者ロールがあれば閲覧・書き込み権限を追加
            manager_role_id = config_data.get("manager_role_id")
            if manager_role_id:
                manager_role = guild.get_role(int(manager_role_id))
                if manager_role:
                    overwrites[manager_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            # 専用チャンネル作成
            channel_name = f"cart-{interaction.user.name}"
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"自動販売機購入チケット: {interaction.user.display_name}"
            )

            # チケット情報の書き込み
            ticket_id = str(ticket_channel.id)
            shop_data["tickets"][ticket_id] = {
                "channel_id": ticket_channel.id,
                "user_id": interaction.user.id,
                "product_id": self.product_id,
                "count": count,
                "status": "WAITING_PAYMENT"
            }
            save_json(SHOP_FILE, shop_data)

        # チケットチャンネル内への案内画面生成
        total_price = product["price"] * count
        embed = discord.Embed(
            title="🛍️ ご購入手続き（専用チャット）",
            description=(
                f"**{interaction.user.mention} 様、ご購入申請ありがとうございます！**\n"
                f"以下の内容をご確認の上、**「💳 PayPayで送金する」** ボタンを押して送金URLを入力してください。"
            ),
            color=0x2b2d31
        )
        embed.add_field(name="📦 ご購入商品", value=f"```\n{product['name']}\n```", inline=False)
        embed.add_field(name="🔢 数量", value=f"` {count} 個 `", inline=True)
        embed.add_field(name="💰 お支払い合計", value=f"` ¥{total_price:,} `", inline=True)
        embed.add_field(
            name="📌 お手続き手順", 
            value=(
                "1️⃣ 下の **「💳 PayPayで送金する」** ボタンを押す\n"
                "2️⃣ PayPayの送金リンク（受け取りURL）を入力する\n"
                "3️⃣ 管理者の確認・承認完了後、こちらに自動で納品されます"
            ), 
            inline=False
        )
        embed.set_footer(text="※間違いがないか確認してから送金を行ってください。")

        view = discord.ui.View(timeout=None)
        view.add_item(TicketPayButton(ticket_id=ticket_id))
        view.add_item(CloseTicketButton(ticket_id=ticket_id))

        await ticket_channel.send(content=f"{interaction.user.mention}", embed=embed, view=view)
        await interaction.followup.send(
            f"✅ 専用購入チャットを作成しました！\n➡️ {ticket_channel.mention} にてお手続きを完了させてください。", 
            ephemeral=True
        )


class PayPaySubmitModal(discord.ui.Modal, title="💳 PayPay送金URLの入力"):
    paypay_url_input = discord.ui.TextInput(
        label="PayPayの送金リンクを貼り付けてください",
        placeholder="https://paypay.ne.jp/page/link/...",
        min_length=15,
        max_length=150,
        required=True
    )

    def __init__(self, ticket_id: str):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        paypay_url = self.paypay_url_input.value.strip()

        # 正規表現による厳格なURLバリデーション
        if not PAYPAY_URL_PATTERN.match(paypay_url):
            await interaction.followup.send(
                "❌ 無効なPayPay送金URLです。\n"
                "`https://paypay.ne.jp/` または `https://paypay.me/` から始まる正しく有効なリンクを入力してください。", 
                ephemeral=True
            )
            return

        async with data_lock:
            ticket = shop_data["tickets"].get(self.ticket_id)
            if not ticket:
                await interaction.followup.send("❌ チケット情報が見つかりません。", ephemeral=True)
                return

            ticket["status"] = "PAYMENT_SUBMITTED"
            ticket["paypay_url"] = paypay_url
            save_json(SHOP_FILE, shop_data)

            product = shop_data["products"].get(ticket["product_id"], {})

        # 送金完了通知および管理者への承認案内メッセージ作成
        total_price = product.get("price", 0) * ticket["count"]

        user_embed = discord.Embed(
            title="⏳ 送金リンクを受領しました",
            description="送金URLの送信が完了しました！管理者が確認を行うまでしばらくお待ちください。",
            color=0xf1c40f
        )
        user_embed.add_field(name="🔗 提出されたリンク", value=f"```{paypay_url}```", inline=False)
        await interaction.channel.send(embed=user_embed)

        # 管理者承認パネル Embed
        admin_embed = discord.Embed(
            title="🛡️ 支払い承認待ち（管理者専用）",
            description="ユーザーよりPayPayの送金URLが提出されました。受取確認後、承認を行ってください。",
            color=0x3498db
        )
        admin_embed.add_field(name="👤 購入者", value=f"<@{ticket['user_id']}>", inline=True)
        admin_embed.add_field(name="📦 商品名", value=product.get("name", "不明"), inline=True)
        admin_embed.add_field(name="💰 請求額", value=f"¥{total_price:,} ({ticket['count']}個)", inline=True)
        admin_embed.add_field(name="🔗 PayPay送金URL", value=f"{paypay_url}", inline=False)

        admin_view = discord.ui.View(timeout=None)
        admin_view.add_item(AdminApproveButton(ticket_id=self.ticket_id))
        admin_view.add_item(AdminRejectButton(ticket_id=self.ticket_id))

        # 管理者通知（メンション付与）
        manager_role_id = config_data.get("manager_role_id")
        mention_text = f"<@&{manager_role_id}>" if manager_role_id else "@here"
        
        await interaction.channel.send(content=f"🔔 **【管理者通知】** {mention_text}", embed=admin_embed, view=admin_view)
        await interaction.followup.send("✅ 送金リンクを送信しました。そのまま管理者からの対応をお待ちください。", ephemeral=True)


# ==========================================
# Dynamic UI Components (動的ボタン)
# ==========================================
class TicketPayButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_pay:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="💳 PayPayで送金する",
                style=discord.ButtonStyle.primary,
                custom_id=f"btn_pay:{ticket_id}"
            )
        )
        self.ticket_id = ticket_id

    # DynamicItemの引数再構築処理
    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        ticket = shop_data["tickets"].get(self.ticket_id)
        if not ticket or interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("❌ ご本人様のみ操作可能です。", ephemeral=True)
            return
        await interaction.response.send_modal(PayPaySubmitModal(ticket_id=self.ticket_id))


class AdminApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_approve:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="✅ 承認して納品",
                style=discord.ButtonStyle.success,
                custom_id=f"btn_approve:{ticket_id}"
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction):
            await interaction.response.send_message("❌ この操作を行う権限がありません（管理者専用）。", ephemeral=True)
            return

        await interaction.response.defer()

        async with data_lock:
            ticket = shop_data["tickets"].get(self.ticket_id)
            if not ticket:
                await interaction.followup.send("❌ チケットデータが見つかりません。", ephemeral=True)
                return

            if ticket["status"] == "COMPLETED":
                await interaction.followup.send("⚠️ このチケットは既に納品処理が完了しています。", ephemeral=True)
                return

            product_id = ticket["product_id"]
            count = ticket["count"]
            product = shop_data["products"].get(product_id)

            if not product or len(product.get("stock", [])) < count:
                await interaction.followup.send("❌ 在庫が不足しているため、承認して納品できません。", ephemeral=True)
                return

            # 在庫切り出し（納品データの取り出し）
            delivered_items = product["stock"][:count]
            product["stock"] = product["stock"][count:]
            ticket["status"] = "COMPLETED"
            save_json(SHOP_FILE, shop_data)

        # 納品テキストの生成
        items_text = "\n".join(delivered_items)

        # 納品Embed作成
        delivery_embed = discord.Embed(
            title="🎉 お買い上げありがとうございます！【商品納品】",
            description="お支払いが正常に承認されました。以下の枠内に記載されているのが商品データとなります。",
            color=0x2ecc71
        )
        delivery_embed.add_field(name="📦 納品内容", value=f"```\n{items_text}\n```", inline=False)
        delivery_embed.set_footer(text="※商品の取り扱いには十分ご注意ください。サポートが必要な場合は管理職へお申し付けください。")

        # チケットチャンネル内で納品
        await interaction.channel.send(content=f"<@{ticket['user_id']}>", embed=delivery_embed)

        # DM宛てにもバックアップとして送付
        try:
            buyer = await interaction.guild.fetch_member(ticket["user_id"])
            if buyer:
                await buyer.send(embed=delivery_embed)
        except Exception:
            pass # DMが閉じられている場合はスキップ

        # ログチャンネルへの結果記録
        log_channel_id = config_data.get("log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if log_channel:
                log_embed = discord.Embed(title="📝 【取引完了ログ】", color=0x2ecc71)
                log_embed.add_field(name="購入者", value=f"<@{ticket['user_id']}>", inline=True)
                log_embed.add_field(name="承認者", value=f"{interaction.user.mention}", inline=True)
                log_embed.add_field(name="商品名", value=product['name'], inline=True)
                log_embed.add_field(name="個数", value=f"{count}個", inline=True)
                await log_channel.send(embed=log_embed)

        # ボタン無効化等の更新
        for item in self.view.children:
            item.disabled = True
        await interaction.message.edit(view=self.view)
        await interaction.followup.send("✅ 承認および商品の発送処理が完了しました。", ephemeral=True)


class AdminRejectButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_reject:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="❌ 送金を拒否・却下",
                style=discord.ButtonStyle.danger,
                custom_id=f"btn_reject:{ticket_id}"
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        if not is_manager(interaction):
            await interaction.response.send_message("❌ この操作を行う権限がありません（管理者専用）。", ephemeral=True)
            return

        async with data_lock:
            ticket = shop_data["tickets"].get(self.ticket_id)
            if ticket:
                ticket["status"] = "WAITING_PAYMENT"
                save_json(SHOP_FILE, shop_data)

        reject_embed = discord.Embed(
            title="⚠️ 送金リンクが却下されました",
            description="提出されたPayPayリンクの受取が行えませんでした。金額をご確認の上、正しいリンクを再提出してください。",
            color=0xe74c3c
        )
        await interaction.channel.send(content=f"<@{ticket['user_id']}>", embed=reject_embed)
        await interaction.response.send_message("❌ 提出された送金リンクを却下しました。", ephemeral=True)


class CloseTicketButton(discord.ui.DynamicItem[discord.ui.Button], template=r"btn_close:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: str):
        super().__init__(
            discord.ui.Button(
                label="🔒 専用チャットを閉じる",
                style=discord.ButtonStyle.secondary,
                custom_id=f"btn_close:{ticket_id}"
            )
        )
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(ticket_id=match.group("ticket_id"))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("⚠️ 5秒後にこのチャンネルを削除して終了します...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason="自動販売機チケット完了による自動削除")
        except Exception as e:
            print(f"[Error] チャンネル削除エラー: {e}")


# ==========================================
# ショップメインパネル (Dropdown & View)
# ==========================================
class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = []
        products = shop_data.get("products", {})

        for p_id, p_data in products.items():
            stock_count = len(p_data.get("stock", []))
            status_emoji = "🟢" if stock_count > 0 else "🔴"
            options.append(
                discord.SelectOption(
                    label=f"{p_data['name']}",
                    value=p_id,
                    description=f"価格: ¥{p_data['price']:,} | 在庫: {stock_count}個",
                    emoji=status_emoji
                )
            )

        if not options:
            options.append(discord.SelectOption(label="現在販売中の商品はございません", value="none"))

        super().__init__(
            placeholder="🛒 ご希望の商品をメニューから選択してください...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="shop_product_select"
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = self.values[0]
        if selected_id == "none":
            await interaction.response.send_message("現在選択可能な商品がありません。", ephemeral=True)
            return

        product = shop_data["products"].get(selected_id)
        if not product or len(product.get("stock", [])) == 0:
            await interaction.response.send_message("❌ 申し訳ありません。この商品は現在売り切れです。", ephemeral=True)
            return

        # 購入個数入力 Modal を開く
        await interaction.response.send_modal(QuantityModal(product_id=selected_id))


class ShopPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())


# ==========================================
# 管理用スラッシュコマンド (管理者限定)
# ==========================================

# 1. パネル設置コマンド
@bot.tree.command(name="set_panel", description="【管理者専用】指定したチャットに自動販売機パネルを設置・更新します")
@app_commands.describe(image_url="パネル上部に配置するGIFまたは画像URL（任意）")
async def set_panel(interaction: discord.Interaction, image_url: Optional[str] = None):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    embed = discord.Embed(
        title="🛒 ONLINE AUTOMATIC SHOP",
        description=(
            "当自動販売機にお越しいただきありがとうございます！\n"
            "以下のメニューからご希望の商品を選択の上、お手続きを行なってください。\n\n"
            "**【ご利用手順】**\n"
            "1️⃣ 下記のドロップダウンより商品を選択\n"
            "2️⃣ ご希望の購入個数をフォームに入力\n"
            "3️⃣ 自動作成された専用チャット（チケット）にてPayPay送金"
        ),
        color=0x2b2d31
    )

    # GIF / 動く画像の表示対応
    if image_url:
        embed.set_image(url=image_url)
    
    embed.set_footer(text="🔒 Secure Transaction System | PayPay決済対応")

    await interaction.channel.send(embed=embed, view=ShopPanelView())
    await interaction.response.send_message("✅ 販売パネルをこのチャンネルに正常設置しました！", ephemeral=True)


# 2. 商品追加コマンド
@bot.tree.command(name="add_product", description="【管理者専用】新しい商品を登録します")
@app_commands.describe(product_id="商品識別ID (例: item01)", name="商品名", price="価格（数値）")
async def add_product(interaction: discord.Interaction, product_id: str, name: str, price: int):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    async with data_lock:
        if product_id in shop_data["products"]:
            await interaction.response.send_message(f"❌ 商品ID `{product_id}` は既に登録されています。", ephemeral=True)
            return

        shop_data["products"][product_id] = {
            "name": name,
            "price": price,
            "stock": []
        }
        save_json(SHOP_FILE, shop_data)

    await interaction.response.send_message(f"✅ 商品 `{name}` (ID: {product_id}, 価格: ¥{price:,}) を登録しました！", ephemeral=True)


# 3. 在庫追加コマンド
@bot.tree.command(name="add_stock", description="【管理者専用】商品に在庫（シリアルコード等）を追加します")
@app_commands.describe(product_id="対象の製品ID", stock_data="追加するデータ（複数ある場合はカンマ `,` で区切る）")
async def add_stock(interaction: discord.Interaction, product_id: str, stock_data: str):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    async with data_lock:
        product = shop_data["products"].get(product_id)
        if not product:
            await interaction.response.send_message(f"❌ 商品ID `{product_id}` が見つかりません。", ephemeral=True)
            return

        new_items = [item.strip() for item in stock_data.split(",") if item.strip()]
        product["stock"].extend(new_items)
        save_json(SHOP_FILE, shop_data)

    await interaction.response.send_message(
        f"✅ 商品 `{product['name']}` に {len(new_items)} 件の在庫を追加しました。（現在合計: {len(product['stock'])}個）", 
        ephemeral=True
    )


# 4. システム設定コマンド
@bot.tree.command(name="config_shop", description="【管理者専用】チケットカテゴリ・管理者ロール・ログチャンネルを設定します")
@app_commands.describe(
    category_id="チケット（専用チャット）を作成するカテゴリのID",
    manager_role_id="送金承認等の権限を持つ管理者ロールのID",
    log_channel_id="取引完了ログを出力する専用チャンネルのID"
)
async def config_shop(
    interaction: discord.Interaction, 
    category_id: Optional[str] = None, 
    manager_role_id: Optional[str] = None, 
    log_channel_id: Optional[str] = None
):
    if not is_manager(interaction):
        await interaction.response.send_message("❌ このコマンドを実行する権限がありません。", ephemeral=True)
        return

    if category_id:
        config_data["ticket_category_id"] = category_id
    if manager_role_id:
        config_data["manager_role_id"] = manager_role_id
    if log_channel_id:
        config_data["log_channel_id"] = log_channel_id

    save_json(CONFIG_FILE, config_data)
    
    await interaction.response.send_message(
        f"✅ システム設定を更新しました！\n"
        f"・カテゴリID: `{config_data.get('ticket_category_id')}`\n"
        f"・管理者ロールID: `{config_data.get('manager_role_id')}`\n"
        f"・ログチャンネルID: `{config_data.get('log_channel_id')}`",
        ephemeral=True
    )


# ==========================================
# 起動処理 & スラッシュコマンド同期
# ==========================================
@bot.event
async def on_ready():
    print(f"==========================================")
    print(f" Bot Online: {bot.user.name} ({bot.user.id})")
    print(f"==========================================")
    try:
        synced = await bot.tree.sync()
        print(f"[System] {len(synced)} 個のスラッシュコマンドを正常に同期・適用しました。")
    except Exception as e:
        print(f"[Error] コマンド同期失敗: {e}")


# ==========================================
# Bot 起動用メインエントリー
# ==========================================
if __name__ == "__main__":
    TOKEN = "YOUR_BOT_TOKEN_HERE"  # ご自身のDiscord Botトークンに置き換えてください
    bot.run(TOKEN)
