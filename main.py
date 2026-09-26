from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import re


MACHINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")
CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")
JST = ZoneInfo("Asia/Tokyo")

DEFAULT_DESIGN: Dict[str, Any] = {
    "title": "キラの自動販売機",
    "subtitle": "安全・簡単・スピーディー",
    "description": "商品を選択して購入してください。",
    "notice": "お支払いはPayPayに対応しています。",
    "footer": "キラの自動販売機",
    "color": "purple",
    "banner_url": "",
    "show_stock": True,
    "button_style": "green",
    "button_label": "購入する",
    "maintenance": False,
    "news": "",
}

DEFAULT_PRODUCT: Dict[str, Any] = {
    "id": "sample",
    "name": "サンプル商品",
    "description": "商品説明を設定してください。",
    "price": 100,
    "stock": 0,
    "active": True,
    "image_url": "",
    "emoji": "📦",
    "category": "その他",
    "purchase_limit": 0,
}

DEFAULT_MACHINE: Dict[str, Any] = {
    "id": "main",
    "name": "メイン自販機",
    "purchase_channel_id": 0,
    "panel_channel_id": 0,
    "panel_message_id": 0,
    "ticket_category_id": 0,
    "design": deepcopy(DEFAULT_DESIGN),
    "products": {},
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "guild_id": 0,
    "order_channel_id": 0,
    "archive_category_id": 0,
    "order_counter": 0,
    "machines": {"main": deepcopy(DEFAULT_MACHINE)},
}

DEFAULT_COUPONS: Dict[str, Dict[str, Any]] = {}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def normalize_id(value: Any, fallback: str = "main") -> str:
    raw = str(value or fallback).strip().lower()
    raw = re.sub(r"[^a-z0-9_-]+", "-", raw)
    raw = raw.strip("-_") or fallback
    if not re.match(r"^[a-z0-9]", raw):
        raw = "m-" + raw
    return raw[:32]


def normalize_product(product: Any, fallback_id: str = "product") -> Dict[str, Any]:
    if not isinstance(product, dict):
        product = {}
    pid = str(product.get("id") or fallback_id).strip()[:50]
    name = str(product.get("name") or "商品").strip()[:100]
    description = str(product.get("description") or "").strip()[:1000]
    try:
        price = max(0, int(product.get("price", 0)))
    except (ValueError, TypeError):
        price = 0
    try:
        stock = max(0, int(product.get("stock", 0)))
    except (ValueError, TypeError):
        stock = 0
    try:
        limit = max(0, int(product.get("purchase_limit", 0)))
    except (ValueError, TypeError):
        limit = 0
    emoji = str(product.get("emoji") or "📦")[:32]
    category = str(product.get("category") or "その他").strip()[:50] or "その他"
    image_url = str(product.get("image_url") or "").strip()[:2048]
    active = bool(product.get("active", True))
    return {
        "id": pid,
        "name": name,
        "description": description,
        "price": price,
        "stock": stock,
        "active": active,
        "image_url": image_url,
        "emoji": emoji,
        "category": category,
        "purchase_limit": limit,
    }


def normalize_design(design: Any, machine_name: str = "メイン自販機") -> Dict[str, Any]:
    result = deepcopy(DEFAULT_DESIGN)
    if isinstance(design, dict):
        for key in result:
            if key in design:
                result[key] = design[key]
    result["title"] = str(result.get("title") or machine_name)[:256]
    result["subtitle"] = str(result.get("subtitle") or "")[:256]
    result["description"] = str(result.get("description") or "")[:4000]
    result["notice"] = str(result.get("notice") or "")[:4000]
    result["footer"] = str(result.get("footer") or "")[:256]
    result["banner_url"] = str(result.get("banner_url") or "")[:2048]
    result["button_label"] = str(result.get("button_label") or "購入する")[:80]
    result["news"] = str(result.get("news") or "")[:1500]
    result["show_stock"] = bool(result.get("show_stock", True))
    result["maintenance"] = bool(result.get("maintenance", False))
    result["color"] = str(result.get("color") or "purple")
    result["button_style"] = str(result.get("button_style") or "green")
    return result


def _looks_like_product_dict(value: Any) -> bool:
    return isinstance(value, dict) and any(
        isinstance(v, dict) and ("name" in v or "price" in v or "stock" in v)
        for v in value.values()
    )


def normalize_data(
    config: Optional[Dict[str, Any]],
    products: Optional[Dict[str, Any]],
    orders: Optional[List[Any]],
    coupons: Optional[Dict[str, Any]] = None,
    logs: Optional[List[Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    cfg = deepcopy(DEFAULT_CONFIG)
    if isinstance(config, dict):
        cfg.update({k: deepcopy(v) for k, v in config.items() if k != "machines"})

    raw_machines = config.get("machines") if isinstance(config, dict) else None
    machines: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw_machines, dict) and raw_machines:
        source_items = raw_machines.items()
    else:
        source_items = [("main", {})]

    legacy_design = config.get("design", {}) if isinstance(config, dict) else {}
    legacy_name = "メイン自販機"
    if isinstance(config, dict):
        legacy_name = str(config.get("vending_name") or config.get("name") or legacy_name)
        if isinstance(legacy_design, dict) and legacy_design.get("title") and legacy_name == "メイン自販機":
            legacy_name = str(legacy_design.get("title"))

    for raw_id, raw_machine in source_items:
        mid = normalize_id(raw_id)
        m = deepcopy(DEFAULT_MACHINE)
        if isinstance(raw_machine, dict):
            m.update({k: deepcopy(v) for k, v in raw_machine.items() if k not in ("design", "products")})
            m["name"] = str(raw_machine.get("name") or legacy_name)[:100]
            raw_design = raw_machine.get("design") if isinstance(raw_machine, dict) else None
            m["design"] = normalize_design(raw_design if raw_design is not None else legacy_design, m["name"])
        else:
            m["name"] = legacy_name
            m["design"] = normalize_design(legacy_design, m["name"])
        machine_products = raw_machine.get("products", {}) if isinstance(raw_machine, dict) else {}
        if isinstance(machine_products, list):
            machine_products = {str(i.get("id") or f"product-{n}"): i for n, i in enumerate(machine_products) if isinstance(i, dict)}
        m["products"] = {}
        if isinstance(machine_products, dict):
            for pid, pdata in machine_products.items():
                p = normalize_product(pdata, str(pid))
                m["products"][p["id"]] = p
        machines[mid] = m

    if "main" not in machines:
        machines["main"] = deepcopy(DEFAULT_MACHINE)
        machines["main"]["name"] = legacy_name
        machines["main"]["design"] = normalize_design(legacy_design, legacy_name)

    # Migrate legacy top-level products into main when machines did not contain any.
    if _looks_like_product_dict(products) and not machines["main"].get("products"):
        for pid, pdata in products.items():
            p = normalize_product(pdata, str(pid))
            machines["main"]["products"][p["id"]] = p

    cfg["machines"] = machines
    try:
        cfg["guild_id"] = int(cfg.get("guild_id", 0) or 0)
        cfg["order_channel_id"] = int(cfg.get("order_channel_id", 0) or 0)
        cfg["archive_category_id"] = int(cfg.get("archive_category_id", 0) or 0)
        cfg["order_counter"] = int(cfg.get("order_counter", 0) or 0)
    except (TypeError, ValueError):
        cfg["guild_id"] = cfg["order_channel_id"] = cfg["archive_category_id"] = 0
        cfg["order_counter"] = 0

    out_products: Dict[str, Any] = {mid: deepcopy(m["products"]) for mid, m in machines.items()}

    out_orders: List[Dict[str, Any]] = []
    if isinstance(orders, list):
        for order in orders:
            if not isinstance(order, dict):
                continue
            o = deepcopy(order)
            o.setdefault("status", "pending")
            o.setdefault("created_at", now_iso())
            o.setdefault("quantity", 1)
            o.setdefault("discount", 0)
            o.setdefault("original_price", int(o.get("price", 0) or 0))
            o.setdefault("total_price", int(o.get("price", 0) or 0))
            o.setdefault("coupon_code", "")
            o.setdefault("paid_at", "")
            o.setdefault("cancelled_at", "")
            o.setdefault("buyer_id", str(o.get("user_id", "")))
            o.setdefault("product_id", "")
            o.setdefault("product_name", "商品")
            o.setdefault("product_emoji", "📦")
            o.setdefault("vending_id", "main")
            o.setdefault("vending_name", machines.get(str(o.get("vending_id")), machines["main"])["name"])
            out_orders.append(o)

    out_coupons: Dict[str, Any] = {}
    if isinstance(coupons, dict):
        for raw_code, raw in coupons.items():
            if not isinstance(raw, dict):
                continue
            code = str(raw.get("code") or raw_code).strip().upper()
            if not code:
                continue
            try:
                amount = max(0, int(raw.get("amount", 0)))
            except (ValueError, TypeError):
                amount = 0
            try:
                max_uses = max(0, int(raw.get("max_uses", 0)))
            except (ValueError, TypeError):
                max_uses = 0
            try:
                uses = max(0, int(raw.get("uses", 0)))
            except (ValueError, TypeError):
                uses = 0
            ctype = "percent" if str(raw.get("type", "percent")) == "percent" else "fixed"
            try:
                reserved_uses = max(0, int(raw.get("reserved_uses", 0) or 0))
            except (ValueError, TypeError):
                reserved_uses = 0
            out_coupons[code] = {
                "code": code,
                "type": ctype,
                "amount": amount,
                "max_uses": max_uses,
                "uses": uses,
                "reserved_uses": reserved_uses,
                "expires_at": str(raw.get("expires_at") or ""),
                "active": bool(raw.get("active", True)),
                "created_at": str(raw.get("created_at") or now_iso()),
            }

    out_logs: List[Dict[str, Any]] = []
    if isinstance(logs, list):
        for item in logs[-5000:]:
            if isinstance(item, dict):
                out_logs.append(deepcopy(item))

    return cfg, out_products, out_orders, out_coupons, out_logs


class VendingStore:
    """Discordに依存しない販売ロジック。状態遷移を一元管理する。"""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        products: Optional[Dict[str, Any]] = None,
        orders: Optional[List[Any]] = None,
        coupons: Optional[Dict[str, Any]] = None,
        logs: Optional[List[Any]] = None,
    ) -> None:
        self.config, self.products, self.orders, self.coupons, self.logs = normalize_data(
            config, products, orders, coupons, logs
        )

    @property
    def machines(self) -> Dict[str, Dict[str, Any]]:
        return self.config["machines"]

    def get_machine(self, machine_id: str) -> Optional[Dict[str, Any]]:
        return self.machines.get(str(machine_id))

    def machine_products(self, machine_id: str) -> Dict[str, Dict[str, Any]]:
        machine = self.get_machine(machine_id)
        return machine["products"] if machine else {}

    def ensure_unique_machine_id(self, base: str) -> str:
        candidate = normalize_id(base)
        if candidate not in self.machines:
            return candidate
        for i in range(2, 1000):
            suffix = f"-{i}"
            trimmed = candidate[: 32 - len(suffix)]
            test = trimmed + suffix
            if test not in self.machines:
                return test
        raise RuntimeError("自販機IDを生成できませんでした")

    def ensure_unique_product_id(self, machine_id: str, base: str) -> str:
        products = self.machine_products(machine_id)
        candidate = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(base or "product")).strip("-_")[:45] or "product"
        if candidate not in products:
            return candidate
        for i in range(2, 1000):
            suffix = f"-{i}"
            test = candidate[: 50 - len(suffix)] + suffix
            if test not in products:
                return test
        raise RuntimeError("商品IDを生成できませんでした")

    def next_order_id(self) -> str:
        self.config["order_counter"] = int(self.config.get("order_counter", 0)) + 1
        return f"KIRA-{self.config['order_counter']:06d}"

    def add_log(self, action: str, actor_id: int | str, detail: str = "", **extra: Any) -> Dict[str, Any]:
        item = {
            "timestamp": now_iso(),
            "action": str(action)[:100],
            "actor_id": str(actor_id),
            "detail": str(detail)[:2000],
        }
        item.update(extra)
        self.logs.append(item)
        if len(self.logs) > 5000:
            self.logs = self.logs[-5000:]
        return item

    def create_machine(self, name: str, base_id: str = "machine") -> Dict[str, Any]:
        mid = self.ensure_unique_machine_id(base_id)
        machine = deepcopy(DEFAULT_MACHINE)
        machine["id"] = mid
        machine["name"] = str(name or mid)[:100]
        machine["design"] = normalize_design({}, machine["name"])
        self.machines[mid] = machine
        self.products[mid] = machine["products"]
        return machine

    def delete_machine(self, machine_id: str) -> bool:
        if machine_id not in self.machines or len(self.machines) <= 1:
            return False
        if any(o.get("vending_id") == machine_id and o.get("status") == "pending" for o in self.orders):
            return False
        del self.machines[machine_id]
        self.products.pop(machine_id, None)
        return True

    def update_machine_design(self, machine_id: str, **changes: Any) -> Dict[str, Any]:
        machine = self.machines[machine_id]
        design = machine.setdefault("design", deepcopy(DEFAULT_DESIGN))
        design.update(changes)
        machine["design"] = normalize_design(design, machine["name"])
        return machine["design"]

    def add_product(self, machine_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        machine = self.machines[machine_id]
        pid = self.ensure_unique_product_id(machine_id, data.get("id") or data.get("name") or "product")
        product = normalize_product({**data, "id": pid})
        machine["products"][pid] = product
        self.products[machine_id] = machine["products"]
        return product

    def edit_product(self, machine_id: str, product_id: str, **changes: Any) -> Dict[str, Any]:
        product = self.machines[machine_id]["products"][product_id]
        product.update(changes)
        self.machines[machine_id]["products"][product_id] = normalize_product(product, product_id)
        return self.machines[machine_id]["products"][product_id]

    def set_stock(self, machine_id: str, product_id: str, stock: int) -> Dict[str, Any]:
        return self.edit_product(machine_id, product_id, stock=max(0, int(stock)))

    def change_stock(self, machine_id: str, product_id: str, delta: int) -> Dict[str, Any]:
        product = self.machines[machine_id]["products"][product_id]
        return self.set_stock(machine_id, product_id, max(0, int(product["stock"]) + int(delta)))

    def delete_product(self, machine_id: str, product_id: str) -> bool:
        products = self.machines[machine_id]["products"]
        if product_id not in products:
            return False
        if any(
            o.get("vending_id") == machine_id
            and o.get("product_id") == product_id
            and o.get("status") == "pending"
            for o in self.orders
        ):
            return False
        del products[product_id]
        return True

    def set_product_active(self, machine_id: str, product_id: str, active: bool) -> Dict[str, Any]:
        return self.edit_product(machine_id, product_id, active=bool(active))

    def create_coupon(
        self,
        code: str,
        coupon_type: str,
        amount: int,
        max_uses: int = 0,
        expires_at: str = "",
    ) -> Dict[str, Any]:
        code = str(code or "").strip().upper()
        if not CODE_RE.fullmatch(code):
            raise ValueError("クーポンコードは3～32文字の英数字・_・-で指定してください")
        if code in self.coupons:
            raise ValueError("そのクーポンは既に存在します")
        coupon_type = "percent" if coupon_type == "percent" else "fixed"
        amount = int(amount)
        max_uses = max(0, int(max_uses))
        if amount <= 0:
            raise ValueError("割引値は1以上にしてください")
        if coupon_type == "percent" and amount > 100:
            raise ValueError("割引率は100%以下にしてください")
        coupon = {
            "code": code,
            "type": coupon_type,
            "amount": amount,
            "max_uses": max_uses,
            "uses": 0,
            "reserved_uses": 0,
            "expires_at": expires_at,
            "active": True,
            "created_at": now_iso(),
        }
        self.coupons[code] = coupon
        return coupon

    def delete_coupon(self, code: str) -> bool:
        code = str(code).strip().upper()
        if any(o.get("coupon_code") == code and o.get("status") == "pending" for o in self.orders):
            return False
        return self.coupons.pop(code, None) is not None

    def coupon_status(self, code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        code = str(code or "").strip().upper()
        if not code:
            return True, "", None
        coupon = self.coupons.get(code)
        if not coupon:
            return False, "クーポンが見つかりません", None
        if not coupon.get("active", True):
            return False, "このクーポンは無効です", coupon
        if coupon.get("max_uses", 0) and (int(coupon.get("uses", 0)) + int(coupon.get("reserved_uses", 0))) >= coupon["max_uses"]:
            return False, "このクーポンは利用上限に達しています", coupon
        expires_at = parse_iso(str(coupon.get("expires_at", "")))
        if expires_at and utc_now() >= expires_at:
            return False, "このクーポンは期限切れです", coupon
        return True, "OK", coupon

    def calculate_discount(self, base_price: int, coupon_code: str = "") -> Tuple[int, str]:
        base_price = max(0, int(base_price))
        if not coupon_code:
            return 0, ""
        ok, reason, coupon = self.coupon_status(coupon_code)
        if not ok or coupon is None:
            raise ValueError(reason)
        if coupon["type"] == "percent":
            discount = base_price * int(coupon["amount"]) // 100
        else:
            discount = int(coupon["amount"])
        discount = min(base_price, max(0, discount))
        return discount, str(coupon["code"])

    def user_product_count_today(self, user_id: int | str, machine_id: str, product_id: str) -> int:
        today = utc_now().astimezone(JST).date()
        count = 0
        for order in self.orders:
            if str(order.get("buyer_id", order.get("user_id", ""))) != str(user_id):
                continue
            if str(order.get("vending_id", "")) != str(machine_id):
                continue
            if str(order.get("product_id", "")) != str(product_id):
                continue
            status = str(order.get("status", "cancelled"))
            if status == "cancelled":
                continue
            dt = parse_iso(str(order.get("created_at", "")))
            if dt and dt.date() == today:
                count += int(order.get("quantity", 1) or 1)
        return count

    def validate_purchase(self, user_id: int | str, machine_id: str, product_id: str, coupon_code: str = "") -> Dict[str, Any]:
        machine = self.get_machine(machine_id)
        if machine is None:
            raise ValueError("自販機が見つかりません")
        design = machine.get("design", {})
        if design.get("maintenance"):
            raise ValueError("現在メンテナンス中です")
        product = machine["products"].get(product_id)
        if product is None:
            raise ValueError("商品が見つかりません")
        if not product.get("active", True):
            raise ValueError("現在販売停止中の商品です")
        if int(product.get("stock", 0)) <= 0:
            raise ValueError("売り切れです")
        limit = int(product.get("purchase_limit", 0) or 0)
        if limit > 0:
            count = self.user_product_count_today(user_id, machine_id, product_id)
            if count >= limit:
                raise ValueError(f"本日の購入上限 {limit}個 に達しています")
        discount, coupon_code = self.calculate_discount(int(product["price"]), coupon_code)
        return {
            "machine": machine,
            "product": product,
            "original_price": int(product["price"]),
            "discount": discount,
            "total_price": int(product["price"]) - discount,
            "coupon_code": coupon_code,
        }

    def reserve_purchase(
        self,
        user_id: int | str,
        machine_id: str,
        product_id: str,
        coupon_code: str = "",
        paypay_url: str = "",
    ) -> Dict[str, Any]:
        info = self.validate_purchase(user_id, machine_id, product_id, coupon_code)
        product = info["product"]
        # A second live check keeps accidental double-submit from going negative.
        if int(product["stock"]) <= 0:
            raise ValueError("売り切れです")
        if paypay_url:
            parsed = urlparse(paypay_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("PayPay URLはhttp/https形式で入力してください")
        product["stock"] = int(product["stock"]) - 1
        order_id = self.next_order_id()
        order = {
            "order_id": order_id,
            "status": "pending" if info["total_price"] > 0 else "paid",
            "buyer_id": str(user_id),
            "user_id": str(user_id),
            "vending_id": machine_id,
            "vending_name": info["machine"]["name"],
            "product_id": product["id"],
            "product_name": product["name"],
            "product_emoji": product.get("emoji", "📦"),
            "price": int(info["total_price"]),
            "original_price": int(info["original_price"]),
            "discount": int(info["discount"]),
            "total_price": int(info["total_price"]),
            "coupon_code": info["coupon_code"],
            "paypay_url": paypay_url,
            "created_at": now_iso(),
            "paid_at": now_iso() if info["total_price"] == 0 else "",
            "cancelled_at": "",
            "ticket_channel_id": 0,
            "order_message_id": 0,
        }
        self.orders.append(order)
        if order["coupon_code"]:
            code = order["coupon_code"]
            if order["status"] == "paid":
                self.coupons[code]["uses"] = int(self.coupons[code].get("uses", 0)) + 1
            else:
                self.coupons[code]["reserved_uses"] = int(self.coupons[code].get("reserved_uses", 0)) + 1
        return order

    def mark_paid(self, order_id: str, actor_id: int | str) -> Dict[str, Any]:
        order = self.get_order(order_id)
        if order is None:
            raise ValueError("注文が見つかりません")
        if order["status"] == "paid":
            return order
        if order["status"] == "cancelled":
            raise ValueError("キャンセル済みの注文は支払い完了にできません")
        order["status"] = "paid"
        order["paid_at"] = now_iso()
        code = order.get("coupon_code", "")
        if code and code in self.coupons:
            coupon = self.coupons[code]
            coupon["reserved_uses"] = max(0, int(coupon.get("reserved_uses", 0)) - 1)
            coupon["uses"] = int(coupon.get("uses", 0)) + 1
        self.add_log("order_paid", actor_id, f"注文 {order_id} を支払い完了", order_id=order_id)
        return order

    def cancel_order(self, order_id: str, actor_id: int | str) -> Dict[str, Any]:
        order = self.get_order(order_id)
        if order is None:
            raise ValueError("注文が見つかりません")
        if order["status"] == "cancelled":
            return order
        if order["status"] == "paid":
            raise ValueError("支払い完了済みの注文は通常のキャンセルでは戻せません")
        product = self.machine_products(order.get("vending_id", "main")).get(order.get("product_id", ""))
        if product is not None:
            product["stock"] = int(product.get("stock", 0)) + int(order.get("quantity", 1) or 1)
        code = order.get("coupon_code", "")
        if code and code in self.coupons:
            self.coupons[code]["reserved_uses"] = max(0, int(self.coupons[code].get("reserved_uses", 0)) - 1)
        order["status"] = "cancelled"
        order["cancelled_at"] = now_iso()
        self.add_log("order_cancel", actor_id, f"注文 {order_id} をキャンセル", order_id=order_id)
        return order

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        for order in self.orders:
            if str(order.get("order_id", "")) == str(order_id):
                return order
        return None

    def history(self, user_id: int | str, page: int = 0, per_page: int = 8) -> Tuple[List[Dict[str, Any]], int]:
        rows = [o for o in self.orders if str(o.get("buyer_id", o.get("user_id", ""))) == str(user_id)]
        rows.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
        total_pages = max(1, (len(rows) + per_page - 1) // per_page)
        page = max(0, min(int(page), total_pages - 1))
        return rows[page * per_page : (page + 1) * per_page], total_pages

    def stats(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now = (now or utc_now()).astimezone(JST)
        today = now.date()
        month = (now.year, now.month)
        paid = [o for o in self.orders if o.get("status") == "paid"]
        def total(rows: List[Dict[str, Any]]) -> int:
            return sum(int(o.get("total_price", o.get("price", 0)) or 0) for o in rows)
        today_rows = [o for o in paid if (parse_iso(str(o.get("paid_at", ""))) or parse_iso(str(o.get("created_at", "")))) and (parse_iso(str(o.get("paid_at", ""))) or parse_iso(str(o.get("created_at", "")))).date() == today]
        month_rows = []
        for o in paid:
            dt = parse_iso(str(o.get("paid_at", ""))) or parse_iso(str(o.get("created_at", "")))
            if dt and (dt.year, dt.month) == month:
                month_rows.append(o)
        return {
            "today_revenue": total(today_rows),
            "month_revenue": total(month_rows),
            "total_revenue": total(paid),
            "today_orders": len(today_rows),
            "month_orders": len(month_rows),
            "total_orders": len(paid),
            "pending_orders": sum(1 for o in self.orders if o.get("status") == "pending"),
            "cancelled_orders": sum(1 for o in self.orders if o.get("status") == "cancelled"),
            "reserved_units": sum(int(o.get("quantity", 1) or 1) for o in self.orders if o.get("status") == "pending"),
        }

    def ranking(self, limit: int = 10) -> List[Dict[str, Any]]:
        counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for order in self.orders:
            if order.get("status") != "paid":
                continue
            key = (str(order.get("vending_id", "main")), str(order.get("product_id", "")))
            row = counts.setdefault(
                key,
                {
                    "vending_id": key[0],
                    "product_id": key[1],
                    "name": order.get("product_name", "商品"),
                    "emoji": order.get("product_emoji", "📦"),
                    "units": 0,
                    "revenue": 0,
                },
            )
            row["units"] += int(order.get("quantity", 1) or 1)
            row["revenue"] += int(order.get("total_price", order.get("price", 0)) or 0)
        return sorted(counts.values(), key=lambda x: (-x["units"], -x["revenue"], x["name"]))[:limit]

    def low_stock(self, threshold: int = 5) -> List[Tuple[str, Dict[str, Any]]]:
        rows: List[Tuple[str, Dict[str, Any]]] = []
        for machine_id, machine in self.machines.items():
            for product in machine["products"].values():
                if product.get("active", True) and 0 < int(product.get("stock", 0)) <= threshold:
                    rows.append((machine_id, product))
        return rows

    def orders_filtered(self, status: str = "all", machine_id: str = "all") -> List[Dict[str, Any]]:
        rows = []
        for order in self.orders:
            if status != "all" and order.get("status") != status:
                continue
            if machine_id != "all" and order.get("vending_id") != machine_id:
                continue
            rows.append(order)
        return sorted(rows, key=lambda x: str(x.get("created_at", "")), reverse=True)

    def dump_config(self) -> Dict[str, Any]:
        return deepcopy(self.config)

    def dump_products(self) -> Dict[str, Any]:
        return {mid: deepcopy(machine["products"]) for mid, machine in self.machines.items()}

    def dump_orders(self) -> List[Dict[str, Any]]:
        return deepcopy(self.orders)

    def dump_coupons(self) -> Dict[str, Any]:
        return deepcopy(self.coupons)

    def dump_logs(self) -> List[Dict[str, Any]]:
        return deepcopy(self.logs)


import asyncio
import json
import os
import re
import traceback
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands


BOT_NAME = "キラの自動販売機"
CONFIG_FILE = Path("config.json")
PRODUCTS_FILE = Path("products.json")
ORDERS_FILE = Path("orders.json")
COUPONS_FILE = Path("coupons.json")
LOGS_FILE = Path("logs.json")
TOKEN_ENV = "DORD_TOKEN"
JST = ZoneInfo("Asia/Tokyo")
DATA_LOCK = asyncio.Lock()
STORE: Optional[VendingStore] = None


# -----------------------------
# JSON / persistence
# -----------------------------

def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return deepcopy(default)
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        print(f"[WARN] Could not load {path}; using default")
        return deepcopy(default)


def save_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_store() -> VendingStore:
    config = load_json(CONFIG_FILE, {})
    products = load_json(PRODUCTS_FILE, {})
    orders = load_json(ORDERS_FILE, [])
    coupons = load_json(COUPONS_FILE, {})
    logs = load_json(LOGS_FILE, [])
    return VendingStore(config, products, orders, coupons, logs)


STORE = load_store()


def get_store() -> VendingStore:
    assert STORE is not None
    return STORE


async def persist_store() -> None:
    store = get_store()
    async with DATA_LOCK:
        save_json(CONFIG_FILE, store.dump_config())
        save_json(PRODUCTS_FILE, store.dump_products())
        save_json(ORDERS_FILE, store.dump_orders())
        save_json(COUPONS_FILE, store.dump_coupons())
        save_json(LOGS_FILE, store.dump_logs())


# -----------------------------
# Generic helpers
# -----------------------------

COLOR_MAP = {
    "purple": 0x9B59B6,
    "blue": 0x3498DB,
    "cyan": 0x1ABC9C,
    "green": 0x2ECC71,
    "yellow": 0xF1C40F,
    "orange": 0xE67E22,
    "red": 0xE74C3C,
    "pink": 0xFF69B4,
    "dark": 0x2F3136,
    "light": 0x95A5A6,
}

BUTTON_STYLE_MAP = {
    "blue": discord.ButtonStyle.primary,
    "green": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
    "gray": discord.ButtonStyle.secondary,
}

STATUS_LABELS = {
    "pending": "🟡 支払い確認待ち",
    "paid": "🟢 完了",
    "cancelled": "🔴 キャンセル",
}


def money(value: int) -> str:
    return f"¥{int(value):,}"


def dt_jst(value: str) -> str:
    dt = parse_iso(value)
    if not dt:
        return "不明"
    return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")


def design_color(machine: dict[str, Any]) -> discord.Color:
    key = str(machine.get("design", {}).get("color", "purple"))
    return discord.Color(COLOR_MAP.get(key, COLOR_MAP["purple"]))


def button_style(machine: dict[str, Any]) -> discord.ButtonStyle:
    key = str(machine.get("design", {}).get("button_style", "green"))
    return BUTTON_STYLE_MAP.get(key, discord.ButtonStyle.success)


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(
        interaction.guild
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


def admin_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return is_admin(interaction)
    return app_commands.check(predicate)


def get_machine(machine_id: str) -> Optional[dict[str, Any]]:
    return get_store().get_machine(machine_id)


def product_list(machine_id: str, category: Optional[str] = None) -> list[dict[str, Any]]:
    machine = get_machine(machine_id)
    if not machine:
        return []
    products = [p for p in machine["products"].values() if p.get("active", True)]
    if category and category != "__all__":
        products = [p for p in products if p.get("category", "その他") == category]
    return sorted(products, key=lambda p: (p.get("category", ""), p.get("name", "")))


def product_categories(machine_id: str) -> list[str]:
    cats = sorted({str(p.get("category", "その他")) for p in get_store().machine_products(machine_id).values() if p.get("active", True)})
    return cats


def safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or fallback)
    return text.replace("@everyone", "@​everyone").replace("@here", "@​here")


def stock_label(product: dict[str, Any], show_stock: bool = True) -> str:
    stock = int(product.get("stock", 0))
    if stock <= 0:
        return "🔴 売り切れ"
    if not show_stock:
        return "🟢 在庫あり"
    if stock <= 5:
        return f"🟠 残り {stock}個"
    return f"🟢 在庫 {stock}個"


def order_embed(order: dict[str, Any], machine: Optional[dict[str, Any]] = None) -> discord.Embed:
    color = design_color(machine) if machine else discord.Color.blurple()
    embed = discord.Embed(title=f"🧾 注文 {order['order_id']}", color=color)
    embed.add_field(name="購入者", value=f"<@{order['buyer_id']}>", inline=True)
    embed.add_field(name="商品", value=f"{order.get('product_emoji', '📦')} {safe_text(order.get('product_name', '商品'))}", inline=True)
    embed.add_field(name="金額", value=money(int(order.get('total_price', 0))), inline=True)
    original = int(order.get("original_price", order.get("price", 0)))
    discount = int(order.get("discount", 0))
    if discount:
        embed.add_field(name="割引", value=f"-{money(discount)}", inline=True)
    embed.add_field(name="状態", value=STATUS_LABELS.get(order.get("status"), order.get("status", "不明")), inline=True)
    embed.add_field(name="日時", value=dt_jst(order.get("created_at", "")), inline=True)
    if order.get("coupon_code"):
        embed.add_field(name="クーポン", value=f"`{order['coupon_code']}`", inline=True)
    if order.get("paypay_url"):
        embed.add_field(name="PayPay URL", value=f"{order['paypay_url']}", inline=False)
    if original != int(order.get("total_price", 0)):
        embed.set_footer(text=f"通常価格 {money(original)}")
    return embed


def vending_embed(machine_id: str) -> discord.Embed:
    machine = get_machine(machine_id)
    if not machine:
        return discord.Embed(title=BOT_NAME, description="自販機が見つかりません")
    design = machine["design"]
    title = safe_text(design.get("title"), machine["name"])
    description = safe_text(design.get("description"))
    embed = discord.Embed(title=title, description=description, color=design_color(machine))
    if design.get("subtitle"):
        embed.add_field(name="✨", value=safe_text(design["subtitle"]), inline=False)
    if design.get("news"):
        embed.add_field(name="📢 お知らせ", value=safe_text(design["news"]), inline=False)
    if design.get("notice"):
        embed.add_field(name="⚠️ ご案内", value=safe_text(design["notice"]), inline=False)
    status = "🔴 メンテナンス中" if design.get("maintenance") else "🟢 営業中"
    embed.add_field(name="ステータス", value=status, inline=True)
    cats = product_categories(machine_id)
    embed.add_field(name="カテゴリー", value=str(len(cats)), inline=True)
    active = product_list(machine_id)
    available = sum(1 for p in active if int(p.get("stock", 0)) > 0)
    embed.add_field(name="販売中", value=f"{available}/{len(active)} 商品", inline=True)
    if design.get("footer"):
        embed.set_footer(text=safe_text(design["footer"]))
    if design.get("banner_url"):
        embed.set_image(url=design["banner_url"])
    return embed


def product_embed(machine_id: str, product_id: str, coupon_code: str = "") -> discord.Embed:
    machine = get_machine(machine_id)
    product = get_store().machine_products(machine_id).get(product_id)
    if not machine or not product:
        return discord.Embed(title="商品エラー", description="商品が見つかりません")
    embed = discord.Embed(
        title=f"{product.get('emoji', '📦')} {safe_text(product.get('name'))}",
        description=safe_text(product.get('description')) or "説明はありません。",
        color=design_color(machine),
    )
    price = int(product.get("price", 0))
    embed.add_field(name="価格", value=money(price), inline=True)
    embed.add_field(name="在庫", value=stock_label(product, machine["design"].get("show_stock", True)), inline=True)
    embed.add_field(name="カテゴリー", value=safe_text(product.get("category", "その他")), inline=True)
    limit = int(product.get("purchase_limit", 0) or 0)
    embed.add_field(name="購入上限", value=f"1日 {limit}個" if limit else "制限なし", inline=True)
    if coupon_code:
        try:
            discount, code = get_store().calculate_discount(price, coupon_code)
            embed.add_field(name="適用クーポン", value=f"`{code}` / -{money(discount)}", inline=True)
            embed.add_field(name="割引後", value=money(price - discount), inline=True)
        except ValueError:
            pass
    if product.get("image_url"):
        embed.set_thumbnail(url=product["image_url"])
    return embed


def machine_autocomplete(current: str) -> list[app_commands.Choice[str]]:
    query = (current or "").lower()
    choices = []
    for mid, m in get_store().machines.items():
        label = f"{m['name']} ({mid})"
        if query in label.lower() or query in mid.lower():
            choices.append(app_commands.Choice(name=label[:100], value=mid))
    return choices[:25]


def product_autocomplete(machine_id: str, current: str) -> list[app_commands.Choice[str]]:
    query = (current or "").lower()
    choices = []
    for pid, p in get_store().machine_products(machine_id).items():
        label = f"{p['name']} [{pid}]"
        if query in label.lower() or query in pid.lower():
            choices.append(app_commands.Choice(name=label[:100], value=pid))
    return choices[:25]


# -----------------------------
# Discord channel helpers
# -----------------------------

async def secure_channel(channel: discord.TextChannel, buyer: Optional[discord.Member] = None) -> None:
    overwrites = dict(channel.overwrites)
    if channel.guild.me:
        overwrites[channel.guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
    if buyer:
        overwrites[buyer] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    await channel.edit(overwrites=overwrites)


async def get_or_create_order_channel(guild: discord.Guild) -> discord.TextChannel:
    store = get_store()
    cid = int(store.config.get("order_channel_id", 0) or 0)
    channel = guild.get_channel(cid) if cid else None
    if isinstance(channel, discord.TextChannel):
        return channel
    category = discord.utils.get(guild.categories, name="📦 注文管理")
    if category is None:
        category = await guild.create_category("📦 注文管理", reason="キラ自販機初期設定")
    channel = await guild.create_text_channel("注文通知", category=category, reason="キラ自販機初期設定")
    await secure_channel(channel)
    store.config["order_channel_id"] = channel.id
    await persist_store()
    return channel


async def get_or_create_archive_category(guild: discord.Guild) -> discord.CategoryChannel:
    store = get_store()
    cid = int(store.config.get("archive_category_id", 0) or 0)
    category = guild.get_channel(cid) if cid else None
    if isinstance(category, discord.CategoryChannel):
        return category
    category = discord.utils.get(guild.categories, name="📁 購入履歴")
    if category is None:
        category = await guild.create_category("📁 購入履歴", reason="キラ自販機初期設定")
    store.config["archive_category_id"] = category.id
    await persist_store()
    return category


async def get_or_create_ticket_category(guild: discord.Guild, machine_id: str) -> discord.CategoryChannel:
    store = get_store()
    machine = get_machine(machine_id)
    assert machine
    cid = int(machine.get("ticket_category_id", 0) or 0)
    category = guild.get_channel(cid) if cid else None
    if isinstance(category, discord.CategoryChannel):
        return category
    category = discord.utils.get(guild.categories, name=f"💬 {machine['name']} 購入チャット")
    if category is None:
        category = await guild.create_category(f"💬 {machine['name']} 購入チャット", reason="キラ自販機購入カテゴリ")
    machine["ticket_category_id"] = category.id
    await persist_store()
    return category


async def create_ticket(guild: discord.Guild, order: dict[str, Any]) -> Optional[discord.TextChannel]:
    try:
        buyer = guild.get_member(int(order["buyer_id"]))
        if buyer is None:
            return None
        category = await get_or_create_ticket_category(guild, order["vending_id"])
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            buyer: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
        safe_order = re.sub(r"[^0-9A-Za-z_-]", "-", order["order_id"].lower())[:35]
        channel = await guild.create_text_channel(
            f"購入-{safe_order}", category=category, overwrites=overwrites, reason="キラ自販機注文チケット"
        )
        order["ticket_channel_id"] = channel.id
        machine = get_machine(order["vending_id"])
        embed = order_embed(order, machine)
        embed.add_field(name="📌 ご案内", value="管理者が支払いを確認後、注文を完了します。", inline=False)
        await channel.send(content=f"<@{order['buyer_id']}>", embed=embed, view=TicketMessageView(order["order_id"]))
        return channel
    except Exception:
        traceback.print_exc()
        return None


# -----------------------------
# Purchase UI
# -----------------------------

class PurchaseView(discord.ui.View):
    def __init__(self, machine_id: str, page: int = 0, category: Optional[str] = None):
        super().__init__(timeout=None)
        self.machine_id = machine_id
        self.page = max(0, int(page))
        self.category = category or "__all__"
        self._build()

    def _build(self) -> None:
        machine = get_machine(self.machine_id)
        if not machine:
            return
        categories = product_categories(self.machine_id)
        opts = [discord.SelectOption(label="すべての商品", value="__all__", default=self.category == "__all__")]
        for cat in categories[:24]:
            opts.append(discord.SelectOption(label=cat[:100], value=cat, default=self.category == cat))
        self.add_item(CategorySelect(self.machine_id, self.category, opts))
        products = product_list(self.machine_id, self.category)
        per_page = 15
        pages = max(1, (len(products) + per_page - 1) // per_page)
        self.page = min(self.page, pages - 1)
        start = self.page * per_page
        current = products[start : start + per_page]
        for index, product in enumerate(current):
            row = 2 + index // 5
            self.add_item(ProductButton(self.machine_id, product["id"], row=row))
        self.add_item(PageButton(self.machine_id, self.page - 1, self.category, "◀ 前へ", disabled=self.page <= 0, row=1))
        self.add_item(PageButton(self.machine_id, self.page + 1, self.category, f"次へ ▶ ({self.page+1}/{pages})", disabled=self.page >= pages - 1, row=1))
        self.add_item(RefreshPanelButton(self.machine_id, "🔄 更新", row=1))


class CategorySelect(discord.ui.Select):
    def __init__(self, machine_id: str, category: str, options: list[discord.SelectOption]):
        super().__init__(placeholder="カテゴリーを選択", options=options, min_values=1, max_values=1, custom_id=f"kira:category:{machine_id}", row=0)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=vending_embed(self.machine_id), view=PurchaseView(self.machine_id, 0, self.values[0]))


class ProductButton(discord.ui.Button):
    def __init__(self, machine_id: str, product_id: str, row: int):
        store = get_store()
        p = store.machine_products(machine_id).get(product_id) or DEFAULT_PRODUCT
        machine = get_machine(machine_id) or {"design": deepcopy(DEFAULT_DESIGN)}
        style = button_style(machine)
        label = f"{p.get('name','商品')[:45]} {money(int(p.get('price',0)))}"
        if int(p.get("stock", 0)) <= 0:
            style = discord.ButtonStyle.secondary
        super().__init__(label=label[:80], emoji=p.get("emoji", "📦"), style=style, disabled=int(p.get("stock", 0)) <= 0, custom_id=f"kira:product:{machine_id}:{product_id}", row=row)
        self.machine_id = machine_id
        self.product_id = product_id

    async def callback(self, interaction: discord.Interaction) -> None:
        product = get_store().machine_products(self.machine_id).get(self.product_id)
        machine = get_machine(self.machine_id)
        if not product or not machine:
            await interaction.response.send_message("商品が見つかりません。", ephemeral=True)
            return
        if machine["design"].get("maintenance"):
            await interaction.response.send_message("現在メンテナンス中です。", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=product_embed(self.machine_id, self.product_id),
            view=ProductDetailView(self.machine_id, self.product_id),
            ephemeral=True,
        )


class PageButton(discord.ui.Button):
    def __init__(self, machine_id: str, page: int, category: str, label: str, disabled: bool, row: int):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled, custom_id=f"kira:page:{machine_id}:{page}:{category}", row=row)
        self.machine_id = machine_id
        self.page = page
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=vending_embed(self.machine_id), view=PurchaseView(self.machine_id, self.page, self.category))


class RefreshPanelButton(discord.ui.Button):
    def __init__(self, machine_id: str, label: str = "🔄 更新", row: int = 1):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, custom_id=f"kira:refresh:{machine_id}", row=row)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=vending_embed(self.machine_id), view=PurchaseView(self.machine_id, 0, "__all__"))


class ProductDetailView(discord.ui.View):
    def __init__(self, machine_id: str, product_id: str):
        super().__init__(timeout=180)
        self.machine_id = machine_id
        self.product_id = product_id
        machine = get_machine(machine_id)
        if machine:
            self.buy.label = safe_text(machine["design"].get("button_label", "🛒 購入する"), "🛒 購入する")[:80]

    @discord.ui.button(label="🛒 購入する", style=discord.ButtonStyle.success, row=0)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            info = get_store().validate_purchase(interaction.user.id, self.machine_id, self.product_id, "")
            await interaction.response.send_message(
                embed=purchase_confirm_embed(info),
                view=PurchaseConfirmView(self.machine_id, self.product_id),
                ephemeral=True,
            )
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="❌ 閉じる", style=discord.ButtonStyle.secondary, row=0)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="閉じました。", embed=None, view=None)


def purchase_confirm_embed(info: dict[str, Any], coupon_code: str = "") -> discord.Embed:
    machine = info["machine"]
    product = info["product"]
    embed = discord.Embed(
        title="🛒 購入内容の確認",
        description=f"**{product.get('emoji','📦')} {safe_text(product['name'])}**",
        color=design_color(machine),
    )
    embed.add_field(name="通常価格", value=money(info["original_price"]), inline=True)
    embed.add_field(name="割引", value=f"-{money(info['discount'])}" if info["discount"] else "なし", inline=True)
    embed.add_field(name="お支払い", value=money(info["total_price"]), inline=True)
    if coupon_code:
        embed.add_field(name="クーポン", value=f"`{coupon_code}`", inline=False)
    embed.add_field(name="確認", value="内容を確認してから購入してください。", inline=False)
    return embed


class PurchaseConfirmView(discord.ui.View):
    def __init__(self, machine_id: str, product_id: str, coupon_code: str = ""):
        super().__init__(timeout=180)
        self.machine_id = machine_id
        self.product_id = product_id
        self.coupon_code = coupon_code

    @discord.ui.button(label="✅ この内容で購入", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            info = get_store().validate_purchase(interaction.user.id, self.machine_id, self.product_id, self.coupon_code)
            if info["total_price"] <= 0:
                await interaction.response.defer(ephemeral=True)
                order = await reserve_order(interaction.user.id, self.machine_id, self.product_id, self.coupon_code, "")
                await notify_order(interaction.guild, order)
                await purchase_animation(interaction, order, already_deferred=True)
                return
            await interaction.response.send_modal(PayPayModal(self.machine_id, self.product_id, self.coupon_code))
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @discord.ui.button(label="🎟️ クーポン", style=discord.ButtonStyle.primary, row=0)
    async def coupon(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CouponApplyModal(self.machine_id, self.product_id, self.coupon_code))

    @discord.ui.button(label="↩ 戻る", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=product_embed(self.machine_id, self.product_id, self.coupon_code),
            view=ProductDetailView(self.machine_id, self.product_id),
        )


class CouponApplyModal(discord.ui.Modal, title="クーポンを適用"):
    code = discord.ui.TextInput(label="クーポンコード", placeholder="例: WELCOME10", max_length=32, required=False)

    def __init__(self, machine_id: str, product_id: str, current_code: str = ""):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        self.current_code = current_code
        self.code.default = current_code

    async def on_submit(self, interaction: discord.Interaction) -> None:
        code = str(self.code.value or "").strip().upper()
        try:
            info = get_store().validate_purchase(interaction.user.id, self.machine_id, self.product_id, code)
            await interaction.response.edit_message(
                embed=purchase_confirm_embed(info, code),
                view=PurchaseConfirmView(self.machine_id, self.product_id, code),
            )
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class PayPayModal(discord.ui.Modal, title="PayPayお支払い"):
    paypay_url = discord.ui.TextInput(
        label="PayPay送金URL",
        placeholder="https://pay.paypay.ne.jp/...",
        max_length=2048,
        required=True,
    )

    def __init__(self, machine_id: str, product_id: str, coupon_code: str = ""):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        self.coupon_code = coupon_code

    async def on_submit(self, interaction: discord.Interaction) -> None:
        url = str(self.paypay_url.value or "").strip()
        if not valid_http_url(url):
            await interaction.response.send_message("❌ 正しいhttp/httpsのURLを入力してください。", ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True)
            order = await reserve_order(interaction.user.id, self.machine_id, self.product_id, self.coupon_code, url)
        except ValueError as e:
            if interaction.response.is_done():
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        await notify_order(interaction.guild, order)
        await purchase_animation(interaction, order, already_deferred=True)
        await safe_dm(
            interaction.user,
            content=f"🧾 {BOT_NAME}\n注文 `{order['order_id']}` を受け付けました。支払い確認待ちです。",
            embed=order_embed(order, get_machine(self.machine_id)),
        )


async def purchase_animation(interaction: discord.Interaction, order: dict[str, Any], already_deferred: bool = False) -> None:
    # 短い演出。長時間待たせず、処理自体を遅くしない。
    if not already_deferred:
        await interaction.response.defer(ephemeral=True)
    message = await interaction.followup.send("⏳ 注文を処理しています…", ephemeral=True, wait=True)
    await asyncio.sleep(0.25)
    await message.edit(content="📦 商品を確保しました…")
    await asyncio.sleep(0.25)
    await message.edit(content=f"✅ 購入完了！\n注文番号: `{order['order_id']}`")


def valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


async def reserve_order(user_id: int, machine_id: str, product_id: str, coupon_code: str, paypay_url: str) -> dict[str, Any]:
    async with DATA_LOCK:
        order = get_store().reserve_purchase(user_id, machine_id, product_id, coupon_code, paypay_url)
        save_json(CONFIG_FILE, get_store().dump_config())
        save_json(PRODUCTS_FILE, get_store().dump_products())
        save_json(ORDERS_FILE, get_store().dump_orders())
        save_json(COUPONS_FILE, get_store().dump_coupons())
        return deepcopy(order)


async def safe_dm(user: discord.User | discord.Member, content: str = "", embed: Optional[discord.Embed] = None) -> bool:
    try:
        await user.send(content=content, embed=embed)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def notify_order(guild: Optional[discord.Guild], order: dict[str, Any]) -> None:
    if not guild:
        return
    try:
        channel = await get_or_create_order_channel(guild)
        message = await channel.send(
            content="📥 **新しい注文**",
            embed=order_embed(order, get_machine(order["vending_id"])),
            view=OrderActionView(order["order_id"]),
        )
        order_obj = get_store().get_order(order["order_id"])
        if order_obj:
            order_obj["order_message_id"] = message.id
            await persist_store()
        await create_ticket(guild, order)
        await persist_store()
        await maybe_update_panel(order["vending_id"])
        await low_stock_alert(guild)
    except Exception:
        traceback.print_exc()


async def low_stock_alert(guild: discord.Guild) -> None:
    rows = get_store().low_stock(5)
    if not rows:
        return
    channel = guild.get_channel(int(get_store().config.get("order_channel_id", 0) or 0))
    if not isinstance(channel, discord.TextChannel):
        return
    # Avoid repeated spam: alert only if the same product was not warned in the last 6h.
    now = datetime.now(timezone.utc)
    recent = [
        x for x in get_store().logs
        if x.get("action") == "low_stock_alert"
        and parse_iso(x.get("timestamp", ""))
        and now - parse_iso(x.get("timestamp", "")) < timedelta(hours=6)
    ]
    already = {(x.get("vending_id"), x.get("product_id")) for x in recent}
    for machine_id, product in rows:
        key = (machine_id, product["id"])
        if key in already:
            continue
        machine = get_machine(machine_id)
        await channel.send(
            f"⚠️ **在庫警告**\n{machine['name']} / {product.get('emoji','📦')} {product['name']}\n残り **{product['stock']}個**"
        )
        get_store().add_log("low_stock_alert", guild.me.id if guild.me else "bot", "低在庫通知", vending_id=machine_id, product_id=product["id"])
    await persist_store()


# -----------------------------
# Order action UI / global interaction fallback
# -----------------------------

class RawActionButtonView(discord.ui.View):
    def __init__(self, order_id: str, include_ticket: bool = False):
        super().__init__(timeout=None)
        if include_ticket:
            self.add_item(discord.ui.Button(label="📁 履歴へ移動", style=discord.ButtonStyle.secondary, custom_id=f"kira:ticket_archive:{order_id}"))
            self.add_item(discord.ui.Button(label="🗑️ チケット削除", style=discord.ButtonStyle.danger, custom_id=f"kira:ticket_delete:{order_id}"))
        else:
            self.add_item(discord.ui.Button(label="✅ 支払い確認", style=discord.ButtonStyle.success, custom_id=f"kira:order_paid:{order_id}"))
            self.add_item(discord.ui.Button(label="❌ キャンセル", style=discord.ButtonStyle.danger, custom_id=f"kira:order_cancel:{order_id}"))


OrderActionView = RawActionButtonView
TicketMessageView = lambda order_id: RawActionButtonView(order_id, include_ticket=True)


async def handle_order_paid(interaction: discord.Interaction, order_id: str) -> None:
    if not is_admin(interaction):
        await interaction.response.send_message("管理者のみ操作できます。", ephemeral=True)
        return
    try:
        order = get_store().mark_paid(order_id, interaction.user.id)
        await persist_store()
    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return
    embed = order_embed(order, get_machine(order["vending_id"]))
    embed.set_footer(text="✅ 支払い確認済み")
    await interaction.response.edit_message(embed=embed, view=OrderActionView(order_id))
    await update_order_ticket(order)
    await safe_dm(
        interaction.client.get_user(int(order["buyer_id"])) or await interaction.client.fetch_user(int(order["buyer_id"])),
        content=f"✅ ご購入ありがとうございます！\n注文 `{order_id}` の支払いを確認しました。",
        embed=embed,
    )
    await maybe_update_panel(order["vending_id"])


async def handle_order_cancel(interaction: discord.Interaction, order_id: str) -> None:
    if not is_admin(interaction):
        await interaction.response.send_message("管理者のみ操作できます。", ephemeral=True)
        return
    try:
        order = get_store().cancel_order(order_id, interaction.user.id)
        await persist_store()
    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        return
    embed = order_embed(order, get_machine(order["vending_id"]))
    embed.set_footer(text="❌ 注文はキャンセルされました")
    await interaction.response.edit_message(embed=embed, view=OrderActionView(order_id))
    await update_order_ticket(order)
    user = interaction.client.get_user(int(order["buyer_id"]))
    if user is None:
        try:
            user = await interaction.client.fetch_user(int(order["buyer_id"]))
        except Exception:
            user = None
    if user:
        await safe_dm(user, content=f"❌ 注文 `{order_id}` がキャンセルされました。", embed=embed)
    await maybe_update_panel(order["vending_id"])


async def update_order_ticket(order: dict[str, Any]) -> None:
    channel_id = int(order.get("ticket_channel_id", 0) or 0)
    if not channel_id:
        return
    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    embed = order_embed(order, get_machine(order["vending_id"]))
    await channel.send(embed=embed)


async def handle_ticket_archive(interaction: discord.Interaction, order_id: str) -> None:
    if not is_admin(interaction):
        await interaction.response.send_message("管理者のみ操作できます。", ephemeral=True)
        return
    category = await get_or_create_archive_category(interaction.guild)
    if isinstance(interaction.channel, discord.TextChannel):
        await interaction.channel.edit(category=category, reason=f"注文 {order_id} を履歴へ移動")
    await interaction.response.send_message("📁 購入履歴へ移動しました。", ephemeral=True)


async def handle_ticket_delete(interaction: discord.Interaction, order_id: str) -> None:
    if not is_admin(interaction):
        await interaction.response.send_message("管理者のみ操作できます。", ephemeral=True)
        return
    await interaction.response.send_message("🗑️ チケットを削除します。", ephemeral=True)
    await asyncio.sleep(1)
    if isinstance(interaction.channel, discord.TextChannel):
        await interaction.channel.delete(reason=f"注文 {order_id} チケット削除")


# -----------------------------
# History / ranking UI
# -----------------------------

class HistoryView(discord.ui.View):
    def __init__(self, user_id: int, page: int = 0):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.page = page
        rows, total_pages = get_store().history(user_id, page, 8)
        self.total_pages = total_pages
        self.add_item(HistoryPageButton(user_id, page - 1, "◀", page <= 0))
        self.add_item(HistoryPageButton(user_id, page + 1, "▶", page >= total_pages - 1))


class HistoryPageButton(discord.ui.Button):
    def __init__(self, user_id: int, page: int, label: str, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.user_id = user_id
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("この履歴は本人のみ操作できます。", ephemeral=True)
            return
        await interaction.response.edit_message(embed=history_embed(self.user_id, self.page), view=HistoryView(self.user_id, self.page))


def history_embed(user_id: int, page: int = 0) -> discord.Embed:
    rows, total_pages = get_store().history(user_id, page, 8)
    embed = discord.Embed(title="🧾 購入履歴", color=discord.Color.blurple())
    if not rows:
        embed.description = "購入履歴はありません。"
        return embed
    lines = []
    for o in rows:
        lines.append(
            f"`{o['order_id']}` **{o.get('product_emoji','📦')} {o.get('product_name','商品')}** — {money(int(o.get('total_price',0)))}\n"
            f"{STATUS_LABELS.get(o.get('status'), o.get('status'))} / {dt_jst(o.get('created_at',''))}"
        )
    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"ページ {page+1}/{total_pages}")
    return embed


class RankingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(discord.ui.Button(label="🔄 更新", style=discord.ButtonStyle.secondary, custom_id="kira:ranking_refresh"))


def ranking_embed() -> discord.Embed:
    embed = discord.Embed(title="🏆 人気商品ランキング", color=discord.Color.gold())
    rows = get_store().ranking(10)
    if not rows:
        embed.description = "まだ完了した注文がありません。"
        return embed
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows, 1):
        prefix = medals[i - 1] if i <= 3 else f"**{i}位**"
        vending = get_machine(row["vending_id"])
        vending_name = vending["name"] if vending else row["vending_id"]
        lines.append(f"{prefix} {row['emoji']} **{row['name']}**\n└ {vending_name} / {row['units']}個 / {money(row['revenue'])}")
    embed.description = "\n\n".join(lines)
    return embed


# -----------------------------
# Admin panels
# -----------------------------

class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🛠️ 自販機管理", style=discord.ButtonStyle.primary, row=0)
    async def machines(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content="自販機を選択してください。", embed=None, view=MachineManagerView())

    @discord.ui.button(label="📊 売上・統計", style=discord.ButtonStyle.success, row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content=None, embed=stats_embed(), view=AdminStatsView())

    @discord.ui.button(label="🧾 注文管理", style=discord.ButtonStyle.primary, row=0)
    async def orders(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content=None, embed=order_management_embed(), view=OrderManagementView())

    @discord.ui.button(label="🎫 クーポン管理", style=discord.ButtonStyle.secondary, row=1)
    async def coupons(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content=None, embed=coupon_list_embed(), view=CouponAdminView())

    @discord.ui.button(label="📜 操作ログ", style=discord.ButtonStyle.secondary, row=1)
    async def logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content=None, embed=log_embed(), view=LogView())

    @discord.ui.button(label="🏆 売上ランキング", style=discord.ButtonStyle.secondary, row=1)
    async def ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみです。", ephemeral=True)
            return
        await interaction.response.edit_message(content=None, embed=ranking_embed(), view=AdminBackView())


class AdminBackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="↩ 管理画面へ", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="管理パネル", embed=None, view=AdminPanelView())


def stats_embed() -> discord.Embed:
    s = get_store().stats()
    embed = discord.Embed(title="📊 売上・統計", color=discord.Color.green())
    embed.add_field(name="今日の売上", value=money(s["today_revenue"]), inline=True)
    embed.add_field(name="今月の売上", value=money(s["month_revenue"]), inline=True)
    embed.add_field(name="総売上", value=money(s["total_revenue"]), inline=True)
    embed.add_field(name="今日の注文", value=f"{s['today_orders']}件", inline=True)
    embed.add_field(name="今月の注文", value=f"{s['month_orders']}件", inline=True)
    embed.add_field(name="完了注文", value=f"{s['total_orders']}件", inline=True)
    embed.add_field(name="未処理", value=f"{s['pending_orders']}件", inline=True)
    embed.add_field(name="キャンセル", value=f"{s['cancelled_orders']}件", inline=True)
    embed.add_field(name="予約中在庫", value=f"{s['reserved_units']}個", inline=True)
    return embed


class AdminStatsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🔄 更新", style=discord.ButtonStyle.success)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=stats_embed(), view=self)

    @discord.ui.button(label="🏆 ランキング", style=discord.ButtonStyle.secondary)
    async def ranking(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=ranking_embed(), view=AdminBackView())

    @discord.ui.button(label="↩ 戻る", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="管理パネル", embed=None, view=AdminPanelView())


class MachineManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        options = []
        for mid, m in list(get_store().machines.items())[:25]:
            options.append(discord.SelectOption(label=m["name"][:100], value=mid, description=f"ID: {mid}") )
        if options:
            self.add_item(MachineSelect(options))
        self.add_item(CreateMachineButton())
        self.add_item(AdminHomeButton())


class MachineSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="編集する自販機を選択", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content=None, embed=machine_admin_embed(self.values[0]), view=MachineAdminView(self.values[0]))


class CreateMachineButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➕ 自販機を追加", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(MachineCreateModal())


class AdminHomeButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="↩ 管理画面", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="管理パネル", embed=None, view=AdminPanelView())


class MachineCreateModal(discord.ui.Modal, title="自販機を作成"):
    name = discord.ui.TextInput(label="自販機名", placeholder="例: ゲーム自販機", max_length=100)
    machine_id = discord.ui.TextInput(label="自販機ID", placeholder="例: game", max_length=32)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        store = get_store()
        try:
            async with DATA_LOCK:
                machine = store.create_machine(str(self.name.value), str(self.machine_id.value))
                store.add_log("machine_create", interaction.user.id, f"自販機 {machine['id']} を作成")
                save_json(CONFIG_FILE, store.dump_config())
                save_json(PRODUCTS_FILE, store.dump_products())
                save_json(LOGS_FILE, store.dump_logs())
            await interaction.response.edit_message(content=f"✅ `{machine['name']}` を作成しました。", embed=machine_admin_embed(machine["id"]), view=MachineAdminView(machine["id"]))
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


def machine_admin_embed(machine_id: str) -> discord.Embed:
    machine = get_machine(machine_id)
    if not machine:
        return discord.Embed(title="自販機が見つかりません")
    p = list(machine["products"].values())
    sold = sum(1 for x in p if int(x.get("stock", 0)) == 0)
    embed = discord.Embed(title=f"🛠️ {machine['name']}", description=f"ID: `{machine_id}`", color=design_color(machine))
    embed.add_field(name="商品数", value=f"{len(p)}", inline=True)
    embed.add_field(name="売り切れ", value=f"{sold}", inline=True)
    embed.add_field(name="状態", value="🔴 メンテナンス" if machine["design"].get("maintenance") else "🟢 営業中", inline=True)
    embed.add_field(name="購入チャンネル", value=f"<#{machine['purchase_channel_id']}>" if machine.get("purchase_channel_id") else "未設定", inline=True)
    embed.add_field(name="パネル", value=f"<#{machine['panel_channel_id']}>" if machine.get("panel_channel_id") else "未設置", inline=True)
    return embed


class MachineAdminView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id

    @discord.ui.button(label="📦 商品管理", style=discord.ButtonStyle.primary, row=0)
    async def products(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=product_admin_embed(self.machine_id), view=ProductAdminView(self.machine_id))

    @discord.ui.button(label="🎨 デザイン", style=discord.ButtonStyle.primary, row=0)
    async def design(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))

    @discord.ui.button(label="📺 パネル設置", style=discord.ButtonStyle.success, row=0)
    async def deploy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await deploy_purchase_panel(interaction.guild, self.machine_id)
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=self)

    @discord.ui.button(label="🔧 購入チャンネル", style=discord.ButtonStyle.secondary, row=1)
    async def channel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="購入チャンネルを選択してください。", embed=None, view=MachineChannelView(self.machine_id, interaction.guild))

    @discord.ui.button(label="🔴/🟢 メンテナンス", style=discord.ButtonStyle.secondary, row=1)
    async def maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
        machine = get_machine(self.machine_id)
        machine["design"]["maintenance"] = not bool(machine["design"].get("maintenance"))
        get_store().add_log("maintenance_toggle", interaction.user.id, f"{self.machine_id}: {machine['design']['maintenance']}")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=self)

    @discord.ui.button(label="📢 お知らせ", style=discord.ButtonStyle.secondary, row=1)
    async def news(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NewsModal(self.machine_id))

    @discord.ui.button(label="🗑️ 自販機削除", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MachineDeleteConfirmModal(self.machine_id))

    @discord.ui.button(label="↩ 自販機一覧", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="自販機を選択してください。", embed=None, view=MachineManagerView())


class MachineDeleteConfirmModal(discord.ui.Modal, title="自販機を削除"):
    confirmation = discord.ui.TextInput(label="確認", placeholder="DELETE と入力", required=True, max_length=20)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.confirmation.value).strip().upper() != "DELETE":
            await interaction.response.send_message("❌ `DELETE` と入力してください。", ephemeral=True)
            return
        async with DATA_LOCK:
            if not get_store().delete_machine(self.machine_id):
                await interaction.response.send_message("❌ 最後の1台、または支払い確認待ちの注文がある自販機は削除できません。", ephemeral=True)
                return
            get_store().add_log("machine_delete", interaction.user.id, f"自販機 {self.machine_id} を削除")
            save_json(CONFIG_FILE, get_store().dump_config())
            save_json(PRODUCTS_FILE, get_store().dump_products())
            save_json(LOGS_FILE, get_store().dump_logs())
        await interaction.response.edit_message(content="✅ 自販機を削除しました。", embed=None, view=MachineManagerView())


class NewsModal(discord.ui.Modal, title="お知らせ設定"):
    news = discord.ui.TextInput(label="お知らせ", style=discord.TextStyle.paragraph, required=False, max_length=1500)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.news.default = get_machine(machine_id)["design"].get("news", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        get_store().update_machine_design(self.machine_id, news=str(self.news.value or ""))
        get_store().add_log("news_update", interaction.user.id, f"{self.machine_id} お知らせ更新")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=MachineAdminView(self.machine_id))


class MachineChannelView(discord.ui.View):
    def __init__(self, machine_id: str, guild: discord.Guild):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        channels = [c for c in guild.text_channels if c.category is not None or c.category is None]
        options = [discord.SelectOption(label=c.name[:100], value=str(c.id)) for c in channels[:25]]
        if options:
            self.add_item(MachineChannelSelect(machine_id, options))
        self.add_item(MachineChannelBack(machine_id))


class MachineChannelSelect(discord.ui.Select):
    def __init__(self, machine_id: str, options: list[discord.SelectOption]):
        super().__init__(placeholder="購入チャンネル", options=options, min_values=1, max_values=1)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        channel_id = int(self.values[0])
        machine = get_machine(self.machine_id)
        machine["purchase_channel_id"] = channel_id
        get_store().add_log("purchase_channel_set", interaction.user.id, f"{self.machine_id}: {channel_id}")
        await persist_store()
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=MachineAdminView(self.machine_id))


class MachineChannelBack(discord.ui.Button):
    def __init__(self, machine_id: str):
        super().__init__(label="↩ 戻る", style=discord.ButtonStyle.secondary)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=MachineAdminView(self.machine_id))


# Product admin

def product_admin_embed(machine_id: str) -> discord.Embed:
    machine = get_machine(machine_id)
    embed = discord.Embed(title=f"📦 商品管理 - {machine['name']}", color=design_color(machine))
    products = list(machine["products"].values())
    if not products:
        embed.description = "商品がありません。"
        return embed
    lines = []
    for p in products[:25]:
        lines.append(f"{p.get('emoji','📦')} **{p['name']}** — {money(p['price'])} / {stock_label(p)} / `{p['id']}`")
    embed.description = "\n".join(lines)
    if len(products) > 25:
        embed.set_footer(text=f"先頭25件を表示 / 全{len(products)}件")
    return embed


class ProductAdminView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        options = []
        for pid, p in list(get_store().machine_products(machine_id).items())[:25]:
            options.append(discord.SelectOption(label=p["name"][:100], value=pid, description=f"{money(p['price'])} / 在庫 {p['stock']}"))
        if options:
            self.add_item(ProductAdminSelect(machine_id, options))
        self.add_item(ProductAddButton(machine_id))
        self.add_item(ProductBackButton(machine_id))


class ProductAdminSelect(discord.ui.Select):
    def __init__(self, machine_id: str, options: list[discord.SelectOption]):
        super().__init__(placeholder="商品を選択", options=options, min_values=1, max_values=1)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content=None, embed=product_detail_admin_embed(self.machine_id, self.values[0]), view=ProductEditView(self.machine_id, self.values[0]))


class ProductAddButton(discord.ui.Button):
    def __init__(self, machine_id: str):
        super().__init__(label="➕ 商品追加", style=discord.ButtonStyle.success)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ProductAddModal(self.machine_id))


class ProductBackButton(discord.ui.Button):
    def __init__(self, machine_id: str):
        super().__init__(label="↩ 自販機へ", style=discord.ButtonStyle.secondary)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=MachineAdminView(self.machine_id))


class ProductAddModal(discord.ui.Modal, title="商品を追加"):
    name = discord.ui.TextInput(label="商品名", max_length=100)
    price = discord.ui.TextInput(label="価格(円)", placeholder="1000", max_length=12)
    stock = discord.ui.TextInput(label="在庫", placeholder="10", max_length=10)
    category = discord.ui.TextInput(label="カテゴリー", placeholder="ゲーム", max_length=50, required=False)
    purchase_limit = discord.ui.TextInput(label="1日の購入上限", placeholder="0=無制限", max_length=10, required=False)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = int(self.price.value)
            stock = int(self.stock.value)
            limit = int(self.purchase_limit.value or 0)
            if price < 0 or stock < 0 or limit < 0:
                raise ValueError
            async with DATA_LOCK:
                product = get_store().add_product(
                    self.machine_id,
                    {
                        "name": str(self.name.value),
                        "price": price,
                        "stock": stock,
                        "category": str(self.category.value or "その他"),
                        "purchase_limit": limit,
                        "active": True,
                    },
                )
                get_store().add_log("product_add", interaction.user.id, f"{self.machine_id}/{product['id']} を追加")
                save_json(CONFIG_FILE, get_store().dump_config())
                save_json(PRODUCTS_FILE, get_store().dump_products())
                save_json(LOGS_FILE, get_store().dump_logs())
            await interaction.response.edit_message(embed=product_detail_admin_embed(self.machine_id, product["id"]), view=ProductEditView(self.machine_id, product["id"]))
        except (ValueError, KeyError) as e:
            await interaction.response.send_message(f"❌ 入力を確認してください。{e}", ephemeral=True)


def product_detail_admin_embed(machine_id: str, product_id: str) -> discord.Embed:
    p = get_store().machine_products(machine_id).get(product_id)
    machine = get_machine(machine_id)
    embed = discord.Embed(title=f"📦 {p['name']}", description=safe_text(p.get("description")), color=design_color(machine))
    embed.add_field(name="価格", value=money(p["price"]), inline=True)
    embed.add_field(name="在庫", value=str(p["stock"]), inline=True)
    embed.add_field(name="状態", value="販売中" if p["active"] else "停止", inline=True)
    embed.add_field(name="カテゴリー", value=p.get("category", "その他"), inline=True)
    embed.add_field(name="1日上限", value=str(p.get("purchase_limit", 0) or "無制限"), inline=True)
    embed.add_field(name="画像", value="設定済み" if p.get("image_url") else "未設定", inline=True)
    return embed


class ProductEditView(discord.ui.View):
    def __init__(self, machine_id: str, product_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        self.product_id = product_id

    @discord.ui.button(label="✏️ 編集", style=discord.ButtonStyle.primary, row=0)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProductEditModal(self.machine_id, self.product_id))

    @discord.ui.button(label="📊 在庫変更", style=discord.ButtonStyle.success, row=0)
    async def stock(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StockModal(self.machine_id, self.product_id))

    @discord.ui.button(label="🖼️ 画像URL", style=discord.ButtonStyle.secondary, row=0)
    async def image(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProductImageModal(self.machine_id, self.product_id))

    @discord.ui.button(label="🔄 販売ON/OFF", style=discord.ButtonStyle.secondary, row=1)
    async def toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        p = get_store().machine_products(self.machine_id)[self.product_id]
        get_store().set_product_active(self.machine_id, self.product_id, not p["active"])
        get_store().add_log("product_toggle", interaction.user.id, f"{self.machine_id}/{self.product_id}: {not p['active']}")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=product_detail_admin_embed(self.machine_id, self.product_id), view=self)

    @discord.ui.button(label="🗑️ 削除", style=discord.ButtonStyle.danger, row=1)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProductDeleteModal(self.machine_id, self.product_id))

    @discord.ui.button(label="↩ 商品一覧", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=product_admin_embed(self.machine_id), view=ProductAdminView(self.machine_id))


class ProductEditModal(discord.ui.Modal, title="商品を編集"):
    name = discord.ui.TextInput(label="商品名", max_length=100)
    price = discord.ui.TextInput(label="価格(円)", max_length=12)
    description = discord.ui.TextInput(label="説明", style=discord.TextStyle.paragraph, required=False, max_length=1000)
    emoji = discord.ui.TextInput(label="絵文字", max_length=32, required=False)
    category = discord.ui.TextInput(label="カテゴリー", max_length=50, required=False)
    purchase_limit = discord.ui.TextInput(label="1日の購入上限", placeholder="0=無制限", max_length=10, required=False)

    def __init__(self, machine_id: str, product_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        p = get_store().machine_products(machine_id)[product_id]
        self.name.default = p["name"]
        self.price.default = str(p["price"])
        self.description.default = p.get("description", "")
        self.emoji.default = p.get("emoji", "📦")
        self.category.default = p.get("category", "その他")
        self.purchase_limit.default = str(p.get("purchase_limit", 0) or 0)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = int(self.price.value)
            limit = int(self.purchase_limit.value or 0)
            if price < 0 or limit < 0:
                raise ValueError
            get_store().edit_product(
                self.machine_id,
                self.product_id,
                name=str(self.name.value),
                price=price,
                description=str(self.description.value or ""),
                emoji=str(self.emoji.value or "📦"),
                category=str(self.category.value or "その他"),
                purchase_limit=limit,
            )
            get_store().add_log("product_edit", interaction.user.id, f"{self.machine_id}/{self.product_id} を編集")
            await persist_store()
            await maybe_update_panel(self.machine_id)
            await interaction.response.edit_message(embed=product_detail_admin_embed(self.machine_id, self.product_id), view=ProductEditView(self.machine_id, self.product_id))
        except ValueError:
            await interaction.response.send_message("❌ 入力が正しくありません。", ephemeral=True)


class StockModal(discord.ui.Modal, title="在庫変更"):
    stock = discord.ui.TextInput(label="新しい在庫数", placeholder="10", max_length=10)

    def __init__(self, machine_id: str, product_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        self.stock.default = str(get_store().machine_products(machine_id)[product_id].get("stock", 0))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            value = max(0, int(self.stock.value))
            get_store().set_stock(self.machine_id, self.product_id, value)
            get_store().add_log("stock_change", interaction.user.id, f"{self.machine_id}/{self.product_id}: {value}")
            await persist_store()
            await maybe_update_panel(self.machine_id)
            await low_stock_alert(interaction.guild)
            await interaction.response.edit_message(embed=product_detail_admin_embed(self.machine_id, self.product_id), view=ProductEditView(self.machine_id, self.product_id))
        except ValueError:
            await interaction.response.send_message("❌ 数字を入力してください。", ephemeral=True)


class ProductImageModal(discord.ui.Modal, title="商品画像URL"):
    image_url = discord.ui.TextInput(label="画像URL", placeholder="https://...", required=False, max_length=2048)

    def __init__(self, machine_id: str, product_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id
        self.image_url.default = get_store().machine_products(machine_id)[product_id].get("image_url", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        url = str(self.image_url.value or "").strip()
        if url and not valid_http_url(url):
            await interaction.response.send_message("❌ http/https のURLを入力してください。", ephemeral=True)
            return
        get_store().edit_product(self.machine_id, self.product_id, image_url=url)
        get_store().add_log("product_image", interaction.user.id, f"{self.machine_id}/{self.product_id} 画像設定")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=product_detail_admin_embed(self.machine_id, self.product_id), view=ProductEditView(self.machine_id, self.product_id))


class ProductDeleteModal(discord.ui.Modal, title="商品削除"):
    confirm = discord.ui.TextInput(label="確認", placeholder="DELETE と入力", max_length=20)

    def __init__(self, machine_id: str, product_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.product_id = product_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if str(self.confirm.value).strip().upper() != "DELETE":
            await interaction.response.send_message("❌ `DELETE` と入力してください。", ephemeral=True)
            return
        if not get_store().delete_product(self.machine_id, self.product_id):
            await interaction.response.send_message("❌ 商品が見つからないか、支払い確認待ちの注文があります。", ephemeral=True)
            return
        get_store().add_log("product_delete", interaction.user.id, f"{self.machine_id}/{self.product_id} を削除")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=product_admin_embed(self.machine_id), view=ProductAdminView(self.machine_id))


# Design

def design_embed(machine_id: str) -> discord.Embed:
    machine = get_machine(machine_id)
    d = machine["design"]
    embed = discord.Embed(title=f"🎨 デザイン - {machine['name']}", color=design_color(machine))
    embed.add_field(name="タイトル", value=d.get("title", ""), inline=False)
    embed.add_field(name="サブタイトル", value=d.get("subtitle", "") or "なし", inline=False)
    embed.add_field(name="説明", value=d.get("description", "")[:1000] or "なし", inline=False)
    embed.add_field(name="色", value=d.get("color", "purple"), inline=True)
    embed.add_field(name="ボタン", value=d.get("button_style", "green"), inline=True)
    embed.add_field(name="バナー", value="設定済み" if d.get("banner_url") else "なし", inline=True)
    embed.add_field(name="購入ボタン", value=d.get("button_label", "購入する"), inline=True)
    embed.add_field(name="在庫表示", value="ON" if d.get("show_stock") else "OFF", inline=True)
    return embed


class DesignView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id

    @discord.ui.button(label="✏️ 文字", style=discord.ButtonStyle.primary, row=0)
    async def text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DesignTextModal(self.machine_id))

    @discord.ui.button(label="🎨 色", style=discord.ButtonStyle.primary, row=0)
    async def color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=ColorView(self.machine_id))

    @discord.ui.button(label="🔘 ボタン色", style=discord.ButtonStyle.secondary, row=0)
    async def button_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=ButtonStyleView(self.machine_id))

    @discord.ui.button(label="🖼️ バナー", style=discord.ButtonStyle.secondary, row=1)
    async def banner(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BannerModal(self.machine_id))

    @discord.ui.button(label="✨ プリセット", style=discord.ButtonStyle.success, row=1)
    async def preset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=PresetView(self.machine_id))

    @discord.ui.button(label="✍️ 購入ボタン文字", style=discord.ButtonStyle.secondary, row=2)
    async def button_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ButtonLabelModal(self.machine_id))

    @discord.ui.button(label="👁️ プレビュー", style=discord.ButtonStyle.secondary, row=2)
    async def preview(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=vending_embed(self.machine_id), view=PreviewBackView(self.machine_id))

    @discord.ui.button(label="↩ 戻る", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=machine_admin_embed(self.machine_id), view=MachineAdminView(self.machine_id))


class DesignTextModal(discord.ui.Modal, title="自販機テキスト"):
    title_text = discord.ui.TextInput(label="タイトル", max_length=256)
    subtitle = discord.ui.TextInput(label="サブタイトル", max_length=256, required=False)
    description = discord.ui.TextInput(label="説明", style=discord.TextStyle.paragraph, max_length=2000, required=False)
    notice = discord.ui.TextInput(label="注意文", style=discord.TextStyle.paragraph, max_length=2000, required=False)
    footer = discord.ui.TextInput(label="フッター", max_length=256, required=False)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id
        d = get_machine(machine_id)["design"]
        self.title_text.default = d.get("title", "")
        self.subtitle.default = d.get("subtitle", "")
        self.description.default = d.get("description", "")
        self.notice.default = d.get("notice", "")
        self.footer.default = d.get("footer", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        get_store().update_machine_design(
            self.machine_id,
            title=str(self.title_text.value),
            subtitle=str(self.subtitle.value or ""),
            description=str(self.description.value or ""),
            notice=str(self.notice.value or ""),
            footer=str(self.footer.value or ""),
        )
        get_store().add_log("design_text", interaction.user.id, f"{self.machine_id} テキスト更新")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class ColorView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        options = [discord.SelectOption(label=k.capitalize(), value=k) for k in COLOR_MAP]
        self.add_item(ColorSelect(machine_id, options))
        self.add_item(DesignBackButton(machine_id))


class ColorSelect(discord.ui.Select):
    def __init__(self, machine_id: str, options: list[discord.SelectOption]):
        super().__init__(placeholder="色を選択", options=options, min_values=1, max_values=1)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        get_store().update_machine_design(self.machine_id, color=self.values[0])
        get_store().add_log("design_color", interaction.user.id, f"{self.machine_id}: {self.values[0]}")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class ButtonStyleView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        opts = [discord.SelectOption(label=k, value=k) for k in BUTTON_STYLE_MAP]
        self.add_item(ButtonStyleSelect(machine_id, opts))
        self.add_item(DesignBackButton(machine_id))


class ButtonStyleSelect(discord.ui.Select):
    def __init__(self, machine_id: str, options: list[discord.SelectOption]):
        super().__init__(placeholder="ボタン色", options=options, min_values=1, max_values=1)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        get_store().update_machine_design(self.machine_id, button_style=self.values[0])
        get_store().add_log("design_button_style", interaction.user.id, f"{self.machine_id}: {self.values[0]}")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class BannerModal(discord.ui.Modal, title="バナーURL"):
    banner_url = discord.ui.TextInput(label="URL", placeholder="https://...", required=False, max_length=2048)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.banner_url.default = get_machine(machine_id)["design"].get("banner_url", "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        url = str(self.banner_url.value or "").strip()
        if url and not valid_http_url(url):
            await interaction.response.send_message("❌ URLを確認してください。", ephemeral=True)
            return
        get_store().update_machine_design(self.machine_id, banner_url=url)
        get_store().add_log("design_banner", interaction.user.id, f"{self.machine_id} バナー更新")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class PresetView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        self.add_item(PresetSelect(machine_id))
        self.add_item(DesignBackButton(machine_id))


class PresetSelect(discord.ui.Select):
    def __init__(self, machine_id: str):
        options = [
            discord.SelectOption(label="シンプル", value="simple"),
            discord.SelectOption(label="パープル", value="purple"),
            discord.SelectOption(label="レッド", value="red"),
            discord.SelectOption(label="ブルー", value="blue"),
            discord.SelectOption(label="ダーク", value="dark"),
        ]
        super().__init__(placeholder="プリセット", options=options, min_values=1, max_values=1)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        presets = {
            "simple": {"color": "light", "button_style": "blue"},
            "purple": {"color": "purple", "button_style": "green"},
            "red": {"color": "red", "button_style": "red"},
            "blue": {"color": "blue", "button_style": "blue"},
            "dark": {"color": "dark", "button_style": "gray"},
        }
        get_store().update_machine_design(self.machine_id, **presets[self.values[0]])
        get_store().add_log("design_preset", interaction.user.id, f"{self.machine_id}: {self.values[0]}")
        await persist_store()
        await maybe_update_panel(self.machine_id)
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class ButtonLabelModal(discord.ui.Modal, title="購入ボタン文字"):
    label = discord.ui.TextInput(label="ボタンに表示する文字", max_length=80)

    def __init__(self, machine_id: str):
        super().__init__()
        self.machine_id = machine_id
        self.label.default = get_machine(machine_id)["design"].get("button_label", "購入する")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        get_store().update_machine_design(self.machine_id, button_label=str(self.label.value or "購入する"))
        get_store().add_log("design_button_label", interaction.user.id, f"{self.machine_id} 購入ボタン文字更新")
        await persist_store()
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class DesignBackButton(discord.ui.Button):
    def __init__(self, machine_id: str):
        super().__init__(label="↩ デザインへ", style=discord.ButtonStyle.secondary)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


class PreviewBackView(discord.ui.View):
    def __init__(self, machine_id: str):
        super().__init__(timeout=300)
        self.machine_id = machine_id
        self.add_item(PreviewBackButton(machine_id))


class PreviewBackButton(discord.ui.Button):
    def __init__(self, machine_id: str):
        super().__init__(label="↩ デザインへ", style=discord.ButtonStyle.secondary)
        self.machine_id = machine_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=design_embed(self.machine_id), view=DesignView(self.machine_id))


# Coupon admin

class CouponAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="➕ クーポン作成", style=discord.ButtonStyle.success, row=0)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CouponCreateModal())

    @discord.ui.button(label="🗑️ クーポン削除", style=discord.ButtonStyle.danger, row=0)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CouponDeleteModal())

    @discord.ui.button(label="🔄 更新", style=discord.ButtonStyle.secondary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=coupon_list_embed(), view=self)

    @discord.ui.button(label="↩ 戻る", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="管理パネル", embed=None, view=AdminPanelView())


class CouponCreateModal(discord.ui.Modal, title="クーポン作成"):
    code = discord.ui.TextInput(label="コード", placeholder="WELCOME10", max_length=32)
    kind = discord.ui.TextInput(label="種類", placeholder="percent または fixed", max_length=10)
    amount = discord.ui.TextInput(label="割引値", placeholder="10", max_length=10)
    max_uses = discord.ui.TextInput(label="最大利用回数", placeholder="0=無制限", max_length=10, required=False)
    expires_hours = discord.ui.TextInput(label="期限(時間)", placeholder="0=無期限", max_length=10, required=False)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            hours = max(0, int(self.expires_hours.value or 0))
            expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat() if hours else ""
            c = get_store().create_coupon(
                str(self.code.value),
                str(self.kind.value).strip().lower(),
                int(self.amount.value),
                max(0, int(self.max_uses.value or 0)),
                expires,
            )
            get_store().add_log("coupon_create", interaction.user.id, f"クーポン {c['code']} を作成")
            await persist_store()
            await interaction.response.edit_message(embed=coupon_list_embed(), view=CouponAdminView())
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)


class CouponDeleteModal(discord.ui.Modal, title="クーポン削除"):
    code = discord.ui.TextInput(label="コード", max_length=32)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        code = str(self.code.value).strip().upper()
        if not get_store().delete_coupon(code):
            await interaction.response.send_message("❌ 見つからないか、支払い確認待ちの注文で使用中です。", ephemeral=True)
            return
        get_store().add_log("coupon_delete", interaction.user.id, f"クーポン {code} を削除")
        await persist_store()
        await interaction.response.edit_message(embed=coupon_list_embed(), view=CouponAdminView())


def coupon_list_embed() -> discord.Embed:
    embed = discord.Embed(title="🎫 クーポン一覧", color=discord.Color.blurple())
    if not get_store().coupons:
        embed.description = "クーポンはありません。"
        return embed
    lines = []
    for code, c in sorted(get_store().coupons.items()):
        value = f"{c['amount']}% OFF" if c["type"] == "percent" else f"{money(c['amount'])} OFF"
        uses = f"{c['uses']}/{c['max_uses']}" if c.get("max_uses") else f"{c['uses']}/∞"
        expiry = dt_jst(c.get("expires_at")) if c.get("expires_at") else "無期限"
        lines.append(f"`{code}` — **{value}** / 使用 {uses} / {expiry}")
    embed.description = "\n".join(lines)
    return embed


# Order management

class OrderManagementView(discord.ui.View):
    def __init__(self, status: str = "pending", page: int = 0):
        super().__init__(timeout=300)
        self.status = status
        self.page = page
        statuses = [
            discord.SelectOption(label="未処理", value="pending", default=status == "pending"),
            discord.SelectOption(label="完了", value="paid", default=status == "paid"),
            discord.SelectOption(label="キャンセル", value="cancelled", default=status == "cancelled"),
            discord.SelectOption(label="すべて", value="all", default=status == "all"),
        ]
        self.add_item(OrderStatusSelect(statuses))
        rows = get_store().orders_filtered(status=status)
        pages = max(1, (len(rows) + 8 - 1) // 8)
        self.add_item(OrderPageButton(status, page - 1, "◀", page <= 0))
        self.add_item(OrderPageButton(status, page + 1, "▶", page >= pages - 1))
        self.add_item(AdminBackButton())


class OrderStatusSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(placeholder="状態で絞り込み", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=order_management_embed(self.values[0]), view=OrderManagementView(self.values[0]))


class OrderPageButton(discord.ui.Button):
    def __init__(self, status: str, page: int, label: str, disabled: bool):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, disabled=disabled)
        self.status = status
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=order_management_embed(self.status, self.page), view=OrderManagementView(self.status, self.page))


class AdminBackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="↩ 管理画面", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content="管理パネル", embed=None, view=AdminPanelView())


def order_management_embed(status: str = "pending", page: int = 0) -> discord.Embed:
    rows = get_store().orders_filtered(status=status)
    start = page * 8
    current = rows[start : start + 8]
    pages = max(1, (len(rows) + 7) // 8)
    embed = discord.Embed(title="🧾 注文管理", color=discord.Color.blurple())
    if not current:
        embed.description = "対象注文はありません。"
        return embed
    lines = []
    for o in current:
        lines.append(f"`{o['order_id']}` <@{o['buyer_id']}> / **{o['product_name']}** / {money(o['total_price'])}\n{STATUS_LABELS.get(o['status'], o['status'])} / {dt_jst(o['created_at'])}")
    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"{status} / ページ {page+1}/{pages} / 全{len(rows)}件")
    return embed


# Logs
class LogView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(AdminBackButton())


def log_embed() -> discord.Embed:
    embed = discord.Embed(title="📜 操作ログ", color=discord.Color.dark_grey())
    rows = list(reversed(get_store().logs[-20:]))
    if not rows:
        embed.description = "ログはありません。"
        return embed
    lines = []
    for item in rows:
        lines.append(f"`{dt_jst(item.get('timestamp',''))}` **{item.get('action')}** / <@{item.get('actor_id')}>\n{safe_text(item.get('detail',''))}")
    embed.description = "\n\n".join(lines)
    return embed


# -----------------------------
# Panel deployment / refresh
# -----------------------------

async def deploy_purchase_panel(guild: discord.Guild, machine_id: str, channel: Optional[discord.TextChannel] = None) -> Optional[discord.Message]:
    machine = get_machine(machine_id)
    if not machine:
        return None
    if channel is None:
        cid = int(machine.get("panel_channel_id", 0) or 0)
        ch = guild.get_channel(cid) if cid else None
        channel = ch if isinstance(ch, discord.TextChannel) else None
    if channel is None:
        channel = guild.get_channel(int(machine.get("purchase_channel_id", 0) or 0))
        if not isinstance(channel, discord.TextChannel):
            channel = await guild.create_text_channel(f"購入-{machine['id']}", reason="キラ自販機購入チャンネル")
        machine["purchase_channel_id"] = channel.id
    message_id = int(machine.get("panel_message_id", 0) or 0)
    if message_id:
        try:
            old = await channel.fetch_message(message_id)
            await old.edit(embed=vending_embed(machine_id), view=PurchaseView(machine_id))
            machine["panel_channel_id"] = channel.id
            await persist_store()
            return old
        except discord.NotFound:
            pass
        except discord.HTTPException:
            pass
    message = await channel.send(embed=vending_embed(machine_id), view=PurchaseView(machine_id))
    machine["panel_channel_id"] = channel.id
    machine["panel_message_id"] = message.id
    get_store().add_log("panel_deploy", guild.me.id if guild.me else "bot", f"{machine_id} パネル設置")
    await persist_store()
    return message


async def maybe_update_panel(machine_id: str) -> None:
    guild_id = int(get_store().config.get("guild_id", 0) or 0)
    guild = bot.get_guild(guild_id) if guild_id else None
    if guild:
        try:
            await deploy_purchase_panel(guild, machine_id)
        except Exception:
            traceback.print_exc()


async def refresh_all_purchase_panels() -> None:
    guild_id = int(get_store().config.get("guild_id", 0) or 0)
    guild = bot.get_guild(guild_id) if guild_id else None
    if not guild:
        return
    for machine_id in list(get_store().machines):
        try:
            await deploy_purchase_panel(guild, machine_id)
        except Exception:
            traceback.print_exc()


# -----------------------------
# Commands
# -----------------------------

class AdminCog(commands.Cog):
    def __init__(self, bot_: commands.Bot):
        self.bot = bot_

    @app_commands.command(name="admin", description="管理パネルを開く")
    async def admin(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await interaction.response.send_message("管理者のみ使用できます。", ephemeral=True)
            return
        await interaction.response.send_message("🛠️ **キラの自動販売機 管理パネル**", view=AdminPanelView(), ephemeral=True)

    @app_commands.command(name="setup_vending", description="自販機パネルを設置/更新")
    @app_commands.describe(vending_id="自販機ID", channel="設置チャンネル")
    @admin_only()
    async def setup_vending(self, interaction: discord.Interaction, vending_id: str, channel: Optional[discord.TextChannel] = None):
        machine = get_machine(vending_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await deploy_purchase_panel(interaction.guild, vending_id, channel)
        await interaction.followup.send("✅ パネルを設置/更新しました。", ephemeral=True)

    @app_commands.command(name="send_message", description="指定チャンネルへメッセージ送信")
    @app_commands.describe(channel="送信先", content="内容")
    @admin_only()
    async def send_message(self, interaction: discord.Interaction, channel: discord.TextChannel, content: str):
        await channel.send(safe_text(content))
        get_store().add_log("send_message", interaction.user.id, f"#{channel.name} へ送信")
        await persist_store()
        await interaction.response.send_message(f"✅ {channel.mention} に送信しました。", ephemeral=True)

    @app_commands.command(name="product_add", description="商品を追加")
    @app_commands.describe(vending_id="自販機ID", name="商品名", price="価格", stock="在庫")
    @admin_only()
    async def product_add(self, interaction: discord.Interaction, vending_id: str, name: str, price: int, stock: int):
        if not get_machine(vending_id):
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        try:
            p = get_store().add_product(vending_id, {"name": name, "price": price, "stock": stock})
            get_store().add_log("product_add", interaction.user.id, f"{vending_id}/{p['id']}")
            await persist_store()
            await maybe_update_panel(vending_id)
            await interaction.response.send_message(f"✅ 商品 `{p['name']}` を追加しました。", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ 価格・在庫を確認してください。", ephemeral=True)

    @app_commands.command(name="product_image", description="商品画像URLを設定")
    @app_commands.describe(vending_id="自販機ID", product_id="商品ID", image_url="画像URL")
    @admin_only()
    async def product_image(self, interaction: discord.Interaction, vending_id: str, product_id: str, image_url: str):
        p = get_store().machine_products(vending_id).get(product_id)
        if not p:
            await interaction.response.send_message("❌ 商品が見つかりません。", ephemeral=True)
            return
        if image_url and not valid_http_url(image_url):
            await interaction.response.send_message("❌ URLを確認してください。", ephemeral=True)
            return
        get_store().edit_product(vending_id, product_id, image_url=image_url)
        get_store().add_log("product_image", interaction.user.id, f"{vending_id}/{product_id}")
        await persist_store()
        await maybe_update_panel(vending_id)
        await interaction.response.send_message("✅ 商品画像を更新しました。", ephemeral=True)

    @app_commands.command(name="history", description="自分の購入履歴")
    async def history(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=history_embed(interaction.user.id), view=HistoryView(interaction.user.id), ephemeral=True)

    @app_commands.command(name="ranking", description="人気商品ランキング")
    async def ranking(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=ranking_embed(), view=RankingView(), ephemeral=True)

    @app_commands.command(name="product_search", description="商品を検索")
    @app_commands.describe(keyword="商品名・カテゴリー・商品IDで検索")
    async def product_search(self, interaction: discord.Interaction, keyword: str):
        q = str(keyword or "").strip().lower()
        embed = discord.Embed(title="🔎 商品検索", color=discord.Color.blurple())
        rows = []
        for mid, machine in get_store().machines.items():
            for p in machine["products"].values():
                hay = " ".join([p.get("name", ""), p.get("category", ""), p.get("id", "")]).lower()
                if q in hay and p.get("active", True):
                    rows.append((machine, p))
        if not rows:
            embed.description = "該当商品はありません。"
        else:
            lines = []
            for machine, p in rows[:20]:
                lines.append(f"{p.get('emoji','📦')} **{p['name']}** / {machine['name']} / {money(p['price'])} / {stock_label(p)}")
            embed.description = "\n".join(lines)
            if len(rows) > 20:
                embed.set_footer(text=f"{len(rows)}件中20件を表示")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="coupon_create", description="クーポンを作成")
    @app_commands.describe(code="コード", kind="percent または fixed", amount="割引値", max_uses="最大利用回数(0=無制限)", expires_hours="期限時間(0=無期限)")
    @admin_only()
    async def coupon_create(self, interaction: discord.Interaction, code: str, kind: str, amount: int, max_uses: int = 0, expires_hours: int = 0):
        try:
            expires = (datetime.now(timezone.utc) + timedelta(hours=max(0, expires_hours))).replace(microsecond=0).isoformat() if expires_hours else ""
            c = get_store().create_coupon(code, kind, amount, max_uses, expires)
            get_store().add_log("coupon_create", interaction.user.id, f"{c['code']} を作成")
            await persist_store()
            await interaction.response.send_message(f"✅ クーポン `{c['code']}` を作成しました。", ephemeral=True)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="coupon_delete", description="クーポンを削除")
    @admin_only()
    async def coupon_delete(self, interaction: discord.Interaction, code: str):
        if not get_store().delete_coupon(code):
            await interaction.response.send_message("❌ 見つからないか、支払い確認待ちの注文で使用中です。", ephemeral=True)
            return
        get_store().add_log("coupon_delete", interaction.user.id, f"{code.upper()} を削除")
        await persist_store()
        await interaction.response.send_message("✅ 削除しました。", ephemeral=True)

    @app_commands.command(name="coupon_list", description="クーポン一覧")
    @admin_only()
    async def coupon_list(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=coupon_list_embed(), ephemeral=True)

    @app_commands.command(name="stats", description="売上統計")
    @admin_only()
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=stats_embed(), ephemeral=True)

    @app_commands.command(name="order", description="注文番号を詳細表示")
    @app_commands.describe(order_id="注文番号")
    @admin_only()
    async def order(self, interaction: discord.Interaction, order_id: str):
        o = get_store().get_order(order_id)
        if not o:
            await interaction.response.send_message("❌ 注文が見つかりません。", ephemeral=True)
            return
        await interaction.response.send_message(embed=order_embed(o, get_machine(o["vending_id"])), ephemeral=True)

    @app_commands.command(name="maintenance", description="自販機をメンテナンスモード切替")
    @app_commands.describe(vending_id="自販機ID")
    @admin_only()
    async def maintenance(self, interaction: discord.Interaction, vending_id: str):
        machine = get_machine(vending_id)
        if not machine:
            await interaction.response.send_message("❌ 自販機が見つかりません。", ephemeral=True)
            return
        machine["design"]["maintenance"] = not bool(machine["design"].get("maintenance"))
        get_store().add_log("maintenance_toggle", interaction.user.id, f"{vending_id}: {machine['design']['maintenance']}")
        await persist_store()
        await maybe_update_panel(vending_id)
        await interaction.response.send_message(f"✅ メンテナンス: `{machine['design']['maintenance']}`", ephemeral=True)


# -----------------------------
# Bot
# -----------------------------

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True


class KiraBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.ready_once = False
        self.keepalive_task: Optional[asyncio.Task] = None

    async def setup_hook(self):
        # Reattach purchase panels so restart-safe buttons keep working.
        for machine_id in get_store().machines:
            self.add_view(PurchaseView(machine_id))
        try:
            await self.add_cog(AdminCog(self))
        except commands.errors.ExtensionFailed:
            traceback.print_exc()
        try:
            synced = await self.tree.sync()
            print(f"[INFO] Slash commands synced: {len(synced)}")
        except Exception:
            traceback.print_exc()
        self.keepalive_task = asyncio.create_task(self.keepalive_loop())

    async def keepalive_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                # No external ping here; sleeping keeps task alive and avoids unnecessary traffic.
                await asyncio.sleep(240)
            except asyncio.CancelledError:
                break
            except Exception:
                traceback.print_exc()

    async def close(self):
        if self.keepalive_task:
            self.keepalive_task.cancel()
        await super().close()


bot = KiraBot()


@bot.event
async def on_ready():
    store = get_store()
    if not store.config.get("guild_id") and bot.guilds:
        store.config["guild_id"] = bot.guilds[0].id
        await persist_store()
    if not bot.ready_once:
        bot.ready_once = True
        await refresh_all_purchase_panels()
    print(f"[READY] {bot.user} / {BOT_NAME}")


@bot.event
async def on_guild_join(guild: discord.Guild):
    get_store().config["guild_id"] = guild.id
    get_store().add_log("guild_join", bot.user.id if bot.user else "bot", f"Guild {guild.id}")
    await persist_store()


@bot.event
async def on_interaction(interaction: discord.Interaction):
    # These handlers deliberately live at the interaction level too, so old
    # order/ticket messages continue to work even after a bot restart.
    try:
        data = interaction.data or {}
        custom_id = str(data.get("custom_id", ""))
        if custom_id.startswith("kira:order_paid:"):
            order_id = custom_id.split(":", 2)[2]
            await handle_order_paid(interaction, order_id)
            return
        if custom_id.startswith("kira:order_cancel:"):
            order_id = custom_id.split(":", 2)[2]
            await handle_order_cancel(interaction, order_id)
            return
        if custom_id.startswith("kira:ticket_archive:"):
            order_id = custom_id.split(":", 2)[2]
            await handle_ticket_archive(interaction, order_id)
            return
        if custom_id.startswith("kira:ticket_delete:"):
            order_id = custom_id.split(":", 2)[2]
            await handle_ticket_delete(interaction, order_id)
            return
        if custom_id == "kira:ranking_refresh":
            await interaction.response.edit_message(embed=ranking_embed(), view=RankingView())
            return
    except Exception:
        traceback.print_exc()
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message("❌ 処理中にエラーが発生しました。", ephemeral=True)
            except Exception:
                pass


@bot.event
async def on_error(event_method, *args, **kwargs):
    print(f"[ERROR] event={event_method}")
    traceback.print_exc()


async def main() -> None:
    token = os.getenv(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"環境変数 {TOKEN_ENV} が設定されていません")
    async with bot:
        await bot.start(token, reconnect=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[STOP] Bot stopped")
