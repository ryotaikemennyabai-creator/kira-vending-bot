
    @app_commands.command(name="setup_vending", description="販売機の初期セットアップ")
    @app_commands.default_permissions(administrator=True)
    async def setup_vending(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_admin(interaction.user):
            return await interaction.response.send_message("🔒 管理者専用です。", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild

        try:
            # 注文通知を必ずBot側で確保
            order_channel = await get_or_create_order_channel(guild)

            # 専用チャットカテゴリ
            ticket_category = await get_or_create_ticket_category(guild)

            # 購入チャンネルが未設定なら、管理者が現在いるチャンネルを候補にする
            if not config.get("purchase_channel_id"):
                if isinstance(interaction.channel, discord.TextChannel):
                    config["purchase_channel_id"] = interaction.channel.id
                    save_json(CONFIG_FILE, config)

            purchase = guild.get_channel(int(config.get("purchase_channel_id", 0) or 0))

            await interaction.followup.send(
                "✅ 初期セットアップ完了\n\n"
                f"📦 注文通知: {order_channel.mention}\n"
                f"💬 専用チャットカテゴリ: `{ticket_category.name}`\n"
                f"🛒 購入チャンネル: {purchase.mention if purchase else '未設定'}\n\n"
                "`販売機を設置/更新` から販売機を設置してください。",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ セットアップ失敗:\n`{e}`", ephemeral=True)


class KiraBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(AdminCog(self))

        # 再起動後も既存のボタンが動くように登録。
        self.add_view(PurchaseView())
        # OrderAdminView/TicketViewは注文IDを持つため、
        # 起動時に保存済み注文を読み込んで再登録する。
        for oid, order in orders.items():
            try:
                self.add_view(OrderAdminView(oid))
                if order.get("ticket_channel_id"):
                    self.add_view(TicketView(oid))
            except Exception as e:
                print(f"[STARTUP] view登録失敗 #{oid}: {e}")

        try:
            synced = await self.tree.sync()
            print(f"✅ スラッシュコマンドを {len(synced)} 個同期しました")
        except Exception as e:
            print(f"❌ コマンド同期失敗: {e}")


intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

bot = KiraBot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


@bot.event
async def on_ready():
    print("=" * 55)
    print(f"✅ ログインしました: {bot.user}")
    print("🛒 キラの自動販売機 起動完了")
    print("=" * 55)

    # 設定済みサーバーがあれば注文通知チャンネルを確認。
    gid = int(config.get("guild_id", 0) or 0)
    if gid:
        guild = bot.get_guild(gid)
        if guild:
            try:
                await get_or_create_order_channel(guild)
            except Exception as e:
                print(f"[STARTUP] 注文通知チャンネル確認失敗: {e}")


@bot.event
async def on_guild_join(guild):
    # Bot参加時に最初のサーバーを設定。
    if not config.get("guild_id"):
        config["guild_id"] = guild.id
        save_json(CONFIG_FILE, config)


@bot.event
async def on_message(message: discord.Message):
    # 管理者専用メディアチャンネルに添付されたファイルを自動認識。
    if message.author.bot or not message.guild:
        return

    media_id = int(config.get("media_channel_id", 0) or 0)
    if media_id and message.channel.id == media_id:
        if isinstance(message.author, discord.Member) and is_admin(message.author):
            urls = []
            for a in message.attachments:
                if a.content_type and (
                    a.content_type.startswith("image/")
                    or a.filename.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp"))
                ):
                    urls.append(a.url)
            if urls:
                print(f"[MEDIA] {message.author} がメディアを追加: {urls}")

    await bot.process_commands(message)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN が設定されていません。")

    bot.run(token)

