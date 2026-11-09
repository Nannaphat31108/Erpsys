"""Teak furniture shop ERP — ระบบบริหารร้านขายเฟอร์นิเจอร์ไม้สัก

Modules: products (finished goods), raw materials (teak lumber etc.), suppliers,
purchases, customers, sales orders with line items, payments (deposit/balance),
production orders (workshop) and a dashboard.

Stock rules
- Purchase of material      -> material stock +qty, unit cost = weighted average
- Production order created  -> materials are reserved (deducted) immediately
- Production status 'done'  -> finished product stock +qty
- Production 'cancelled'    -> reserved materials are returned
- Sales order 'delivered'   -> product stock -qty (blocked if not enough stock)
"""
from datetime import date, timedelta

from common import ApiError, clean_fields, now_iso, rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS teak_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'table',
    wood_grade TEXT DEFAULT 'A',
    finish TEXT DEFAULT 'natural',
    dimensions TEXT,
    unit_price REAL NOT NULL DEFAULT 0,
    unit_cost REAL DEFAULT 0,
    stock_qty INTEGER DEFAULT 0,
    reorder_level INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS teak_suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT,
    province TEXT,
    supplies TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS teak_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    grade TEXT DEFAULT 'A',
    unit TEXT DEFAULT 'cu_ft',
    qty REAL DEFAULT 0,
    unit_cost REAL DEFAULT 0,
    reorder_level REAL DEFAULT 0,
    supplier_id INTEGER REFERENCES teak_suppliers(id)
);
CREATE TABLE IF NOT EXISTS teak_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES teak_suppliers(id),
    material_id INTEGER NOT NULL REFERENCES teak_materials(id),
    qty REAL NOT NULL,
    unit_cost REAL NOT NULL,
    purchase_date TEXT,
    invoice_no TEXT
);
CREATE TABLE IF NOT EXISTS teak_customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'retail',
    phone TEXT,
    line_id TEXT,
    address TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS teak_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES teak_customers(id),
    order_date TEXT NOT NULL,
    due_date TEXT,
    status TEXT DEFAULT 'confirmed',
    discount REAL DEFAULT 0,
    delivery_fee REAL DEFAULT 0,
    delivered_date TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS teak_order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES teak_orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES teak_products(id),
    qty INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    unit_cost REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS teak_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES teak_orders(id) ON DELETE CASCADE,
    amount REAL NOT NULL,
    method TEXT DEFAULT 'transfer',
    kind TEXT DEFAULT 'deposit',
    paid_date TEXT
);
CREATE TABLE IF NOT EXISTS teak_production (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES teak_products(id),
    order_id INTEGER REFERENCES teak_orders(id) ON DELETE SET NULL,
    qty INTEGER NOT NULL,
    status TEXT DEFAULT 'planned',
    craftsman TEXT,
    start_date TEXT,
    due_date TEXT,
    completed_date TEXT,
    labor_cost REAL DEFAULT 0,
    note TEXT
);
CREATE TABLE IF NOT EXISTS teak_production_materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    production_id INTEGER NOT NULL REFERENCES teak_production(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES teak_materials(id),
    qty REAL NOT NULL,
    unit_cost REAL DEFAULT 0
);
"""

ENUMS = {
    "products.category": ["table", "chair", "sofa", "bed", "cabinet", "shelf", "door", "outdoor", "decor"],
    "products.wood_grade": ["A", "B", "C", "reclaimed"],
    "products.finish": ["natural", "oiled", "lacquer", "stained", "painted"],
    "materials.grade": ["A", "B", "C", "reclaimed", "-"],
    "materials.unit": ["cu_ft", "board", "piece", "litre", "kg", "set"],
    "customers.type": ["retail", "wholesale", "hotel", "designer", "online"],
    "orders.status": ["quote", "confirmed", "in_production", "ready", "delivered", "cancelled"],
    "payments.method": ["cash", "transfer", "promptpay", "card", "cheque"],
    "payments.kind": ["deposit", "balance", "full", "refund"],
    "production.status": ["planned", "cutting", "assembling", "finishing", "done", "cancelled"],
}

SPEC = {
    "products": dict(table="teak_products", required=["sku", "name", "unit_price"],
                     fields=["sku", "name", "category", "wood_grade", "finish", "dimensions", "unit_price",
                             "unit_cost", "stock_qty", "reorder_level", "active"]),
    "suppliers": dict(table="teak_suppliers", required=["name"],
                      fields=["name", "phone", "province", "supplies", "notes"]),
    "materials": dict(table="teak_materials", required=["name"],
                      fields=["name", "grade", "unit", "qty", "unit_cost", "reorder_level", "supplier_id"]),
    "purchases": dict(table="teak_purchases", required=["supplier_id", "material_id", "qty", "unit_cost"],
                      fields=["supplier_id", "material_id", "qty", "unit_cost", "purchase_date", "invoice_no"]),
    "customers": dict(table="teak_customers", required=["name"],
                      fields=["name", "type", "phone", "line_id", "address"]),
    "orders": dict(table="teak_orders", required=["customer_id"],
                   fields=["customer_id", "order_date", "due_date", "status", "discount", "delivery_fee", "note"]),
    "payments": dict(table="teak_payments", required=["order_id", "amount"],
                     fields=["order_id", "amount", "method", "kind", "paid_date"]),
    "production": dict(table="teak_production", required=["product_id", "qty"],
                       fields=["product_id", "order_id", "qty", "status", "craftsman", "start_date", "due_date",
                               "labor_cost", "note"]),
}
NUMERIC = {"unit_price", "unit_cost", "stock_qty", "reorder_level", "active", "qty", "supplier_id",
           "material_id", "customer_id", "discount", "delivery_fee", "order_id", "amount", "product_id",
           "labor_cost"}
INTEGERS = {"stock_qty", "active", "supplier_id", "material_id", "customer_id", "order_id", "product_id"}
OPEN_ORDER = ("quote", "confirmed", "in_production", "ready")
ACTIVE_ORDER = ("confirmed", "in_production", "ready")


def _date(v, name):
    if v is None:
        return None
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise ApiError(f"{name} ต้องอยู่ในรูปแบบ YYYY-MM-DD")


class TeakERP:
    def __init__(self, conn):
        self.conn = conn

    # ---------- helpers ----------
    def _clean(self, res, data, partial=False):
        s = SPEC[res]
        enums = {k.split(".", 1)[1]: v for k, v in ENUMS.items() if k.startswith(res + ".")}
        out = clean_fields(data, s["fields"], s["required"], enums, NUMERIC, INTEGERS, partial)
        for f in ("order_date", "due_date", "start_date", "purchase_date", "paid_date"):
            if f in out:
                out[f] = _date(out[f], f)
        for f in ("qty", "unit_price", "unit_cost", "amount", "discount", "delivery_fee", "labor_cost", "stock_qty"):
            if out.get(f) is not None and out[f] < 0:
                raise ApiError(f"{f} ต้องไม่ติดลบ")
        return out

    def _get(self, res, rid):
        r = self.conn.execute(f"SELECT * FROM {SPEC[res]['table']} WHERE id=?", (rid,)).fetchone()
        if not r:
            raise ApiError(f"ไม่พบ {res} id={rid}", 404)
        return dict(r)

    def _insert(self, table, data):
        cur = self.conn.execute(f"INSERT INTO {table} ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                                list(data.values()))
        return cur.lastrowid

    def _set(self, table, rid, data):
        if data:
            self.conn.execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in data)} WHERE id=?",
                              [*data.values(), rid])

    def _tx(self, fn):
        try:
            result = fn()
            self.conn.commit()
            return result
        except Exception:
            self.conn.rollback()
            raise

    # ---------- routing ----------
    def route(self, method, parts, body_fn):
        if parts == ["dashboard"] and method == "GET":
            return 200, self.dashboard()
        if parts == ["meta"] and method == "GET":
            return 200, {"enums": ENUMS}
        if not parts or parts[0] not in SPEC or len(parts) > 2:
            raise ApiError("ไม่พบ resource", 404)
        res = parts[0]
        rid = None
        if len(parts) == 2:
            if not parts[1].isdigit():
                raise ApiError("id ไม่ถูกต้อง")
            rid = int(parts[1])
        if method == "GET":
            return 200, (self.detail(res, rid) if rid else self.list(res))
        if method == "POST" and rid is None:
            return 201, self._tx(lambda: self.create(res, body_fn()))
        if method in ("PUT", "PATCH") and rid:
            return 200, self._tx(lambda: self.update(res, rid, body_fn()))
        if method == "DELETE" and rid:
            return 200, self._tx(lambda: self.delete(res, rid))
        raise ApiError("Method not allowed", 405)

    # ---------- read ----------
    def _orders_query(self, where="", args=()):
        data = rows(self.conn.execute(f"""
            SELECT o.*, c.name AS customer_name, c.type AS customer_type,
              COALESCE((SELECT SUM(qty*unit_price) FROM teak_order_items i WHERE i.order_id=o.id),0) AS subtotal,
              COALESCE((SELECT SUM(qty*unit_cost) FROM teak_order_items i WHERE i.order_id=o.id),0) AS cost,
              COALESCE((SELECT SUM(CASE WHEN kind='refund' THEN -amount ELSE amount END)
                        FROM teak_payments p WHERE p.order_id=o.id),0) AS paid,
              (SELECT GROUP_CONCAT(pr.name || ' ×' || i.qty, ', ') FROM teak_order_items i
                 JOIN teak_products pr ON pr.id=i.product_id WHERE i.order_id=o.id) AS items_summary
            FROM teak_orders o JOIN teak_customers c ON c.id=o.customer_id {where}
            ORDER BY o.order_date DESC, o.id DESC""", args))
        today = date.today().isoformat()
        for o in data:
            o["total"] = round(o["subtotal"] - (o["discount"] or 0) + (o["delivery_fee"] or 0), 2)
            o["balance"] = round(o["total"] - o["paid"], 2) if o["status"] != "cancelled" else round(-o["paid"], 2)
            o["overdue"] = bool(o["due_date"] and o["due_date"] < today and o["status"] in OPEN_ORDER)
        return data

    def list(self, res):
        q = self.conn.execute
        if res == "products":
            data = rows(q("SELECT * FROM teak_products ORDER BY category, name"))
            for p in data:
                p["low_stock"] = p["active"] == 1 and p["stock_qty"] <= p["reorder_level"]
                p["margin_pct"] = round((p["unit_price"] - p["unit_cost"]) / p["unit_price"] * 100, 1) \
                    if p["unit_price"] else 0
            return data
        if res == "materials":
            data = rows(q("""SELECT m.*, s.name AS supplier_name FROM teak_materials m
                             LEFT JOIN teak_suppliers s ON s.id=m.supplier_id ORDER BY m.name"""))
            for m in data:
                m["low_stock"] = m["qty"] <= m["reorder_level"]
                m["value"] = round(m["qty"] * m["unit_cost"], 2)
            return data
        if res == "suppliers":
            return rows(q("""SELECT s.*, COUNT(p.id) AS purchase_count,
                               COALESCE(SUM(p.qty*p.unit_cost),0) AS purchase_total
                             FROM teak_suppliers s LEFT JOIN teak_purchases p ON p.supplier_id=s.id
                             GROUP BY s.id ORDER BY s.name"""))
        if res == "purchases":
            return rows(q("""SELECT p.*, s.name AS supplier_name, m.name AS material_name, m.unit,
                               ROUND(p.qty*p.unit_cost,2) AS total
                             FROM teak_purchases p JOIN teak_suppliers s ON s.id=p.supplier_id
                             JOIN teak_materials m ON m.id=p.material_id
                             ORDER BY p.purchase_date DESC, p.id DESC"""))
        if res == "customers":
            data = rows(q("SELECT * FROM teak_customers ORDER BY name"))
            orders = self._orders_query()
            for c in data:
                mine = [o for o in orders if o["customer_id"] == c["id"] and o["status"] != "cancelled"]
                c["order_count"] = len(mine)
                c["total_spent"] = round(sum(o["total"] for o in mine), 2)
                c["balance_due"] = round(sum(o["balance"] for o in mine), 2)
            return data
        if res == "orders":
            return self._orders_query()
        if res == "payments":
            return rows(q("""SELECT p.*, c.name AS customer_name FROM teak_payments p
                             JOIN teak_orders o ON o.id=p.order_id JOIN teak_customers c ON c.id=o.customer_id
                             ORDER BY p.paid_date DESC, p.id DESC"""))
        if res == "production":
            data = rows(q("""SELECT w.*, p.name AS product_name, p.sku,
                               (SELECT COALESCE(SUM(qty*unit_cost),0) FROM teak_production_materials x
                                WHERE x.production_id=w.id) AS material_cost,
                               (SELECT GROUP_CONCAT(m.name || ' ' || x.qty || ' ' || m.unit, ', ')
                                  FROM teak_production_materials x JOIN teak_materials m ON m.id=x.material_id
                                  WHERE x.production_id=w.id) AS materials_summary
                             FROM teak_production w JOIN teak_products p ON p.id=w.product_id
                             ORDER BY CASE w.status WHEN 'done' THEN 2 WHEN 'cancelled' THEN 3 ELSE 1 END,
                                      w.due_date"""))
            today = date.today().isoformat()
            for w in data:
                w["total_cost"] = round(w["material_cost"] + (w["labor_cost"] or 0), 2)
                w["overdue"] = bool(w["due_date"] and w["due_date"] < today
                                    and w["status"] not in ("done", "cancelled"))
            return data
        raise ApiError("ไม่พบ resource", 404)

    def detail(self, res, rid):
        if res == "orders":
            found = self._orders_query("WHERE o.id=?", (rid,))
            if not found:
                raise ApiError(f"ไม่พบ orders id={rid}", 404)
            o = found[0]
            o["items"] = rows(self.conn.execute(
                """SELECT i.*, p.name AS product_name, p.sku FROM teak_order_items i
                   JOIN teak_products p ON p.id=i.product_id WHERE i.order_id=?""", (rid,)))
            o["payments"] = rows(self.conn.execute("SELECT * FROM teak_payments WHERE order_id=? ORDER BY id", (rid,)))
            return o
        rec = self._get(res, rid)
        if res == "production":
            rec["materials"] = rows(self.conn.execute(
                "SELECT material_id, qty, unit_cost FROM teak_production_materials WHERE production_id=?", (rid,)))
        return rec

    # ---------- create ----------
    def create(self, res, data):
        clean = self._clean(res, data)
        if res == "orders":
            return self._create_order(clean, data.get("items"))
        if res == "production":
            return self._create_production(clean, data.get("materials") or [])
        if res == "purchases":
            return self._create_purchase(clean)
        if res == "payments":
            order = self.detail("orders", clean["order_id"])
            if order["status"] == "cancelled" and clean.get("kind") != "refund":
                raise ApiError("ออเดอร์ถูกยกเลิกแล้ว รับได้เฉพาะการคืนเงิน (refund)")
            if clean["amount"] <= 0:
                raise ApiError("amount ต้องมากกว่า 0")
            clean.setdefault("paid_date", date.today().isoformat())
        if res == "customers":
            clean["created_at"] = now_iso()
        if res == "products" and self.conn.execute("SELECT 1 FROM teak_products WHERE sku=?", (clean["sku"],)).fetchone():
            raise ApiError("SKU นี้มีอยู่แล้ว", 409)
        rid = self._insert(SPEC[res]["table"], clean)
        return self.detail(res, rid)

    def _clean_items(self, items):
        if not isinstance(items, list) or not items:
            raise ApiError("ออเดอร์ต้องมีสินค้าอย่างน้อย 1 รายการ")
        out = []
        for it in items:
            try:
                pid = int(it["product_id"])
                qty = float(it["qty"])
            except (KeyError, TypeError, ValueError):
                raise ApiError("รายการสินค้าไม่ถูกต้อง (ต้องมี product_id และ qty)")
            if qty <= 0 or not qty.is_integer():
                raise ApiError("จำนวนสินค้าต้องเป็นจำนวนเต็มมากกว่า 0")
            prod = self._get("products", pid)
            price = it.get("unit_price")
            price = prod["unit_price"] if price in (None, "") else float(price)
            if price < 0:
                raise ApiError("ราคาต้องไม่ติดลบ")
            out.append({"product_id": pid, "qty": int(qty), "unit_price": price, "unit_cost": prod["unit_cost"]})
        return out

    def _create_order(self, o, items):
        items = self._clean_items(items)
        o.setdefault("order_date", date.today().isoformat())
        status = o.get("status") or "confirmed"
        o["status"] = "confirmed" if status == "delivered" else status
        self._get("customers", o["customer_id"])
        oid = self._insert("teak_orders", o)
        for it in items:
            self._insert("teak_order_items", {"order_id": oid, **it})
        if status == "delivered":
            self._deliver(oid)
        return self.detail("orders", oid)

    def _deliver(self, oid):
        items = rows(self.conn.execute(
            """SELECT i.product_id, SUM(i.qty) AS qty, p.name, p.stock_qty FROM teak_order_items i
               JOIN teak_products p ON p.id=i.product_id WHERE i.order_id=? GROUP BY i.product_id""", (oid,)))
        short = [f"{i['name']} (มี {i['stock_qty']}, ต้องการ {i['qty']})" for i in items if i["stock_qty"] < i["qty"]]
        if short:
            raise ApiError("สต็อกสินค้าไม่พอส่งมอบ: " + "; ".join(short), 409)
        for i in items:
            self.conn.execute("UPDATE teak_products SET stock_qty=stock_qty-? WHERE id=?", (i["qty"], i["product_id"]))
        self._set("teak_orders", oid, {"status": "delivered", "delivered_date": date.today().isoformat()})

    def _create_purchase(self, p):
        if p["qty"] <= 0:
            raise ApiError("qty ต้องมากกว่า 0")
        self._get("suppliers", p["supplier_id"])
        m = self._get("materials", p["material_id"])
        p.setdefault("purchase_date", date.today().isoformat())
        new_qty = m["qty"] + p["qty"]
        avg = (m["qty"] * m["unit_cost"] + p["qty"] * p["unit_cost"]) / new_qty
        self._set("teak_materials", m["id"], {"qty": round(new_qty, 4), "unit_cost": round(avg, 2)})
        return self.detail("purchases", self._insert("teak_purchases", p))

    def _create_production(self, w, materials):
        if w["qty"] <= 0 or not float(w["qty"]).is_integer():
            raise ApiError("qty ต้องเป็นจำนวนเต็มมากกว่า 0")
        w["qty"] = int(w["qty"])
        self._get("products", w["product_id"])
        if w.get("order_id"):
            self._get("orders", w["order_id"])
        status = w.get("status") or "planned"
        w["status"] = "planned" if status == "done" else status
        if status == "cancelled":
            raise ApiError("ไม่สามารถสร้างใบสั่งผลิตที่ยกเลิกแล้ว")
        w.setdefault("start_date", date.today().isoformat())
        wid = self._insert("teak_production", w)
        for m in materials:
            try:
                mid, qty = int(m["material_id"]), float(m["qty"])
            except (KeyError, TypeError, ValueError):
                raise ApiError("รายการวัตถุดิบไม่ถูกต้อง")
            if qty <= 0:
                raise ApiError("จำนวนวัตถุดิบต้องมากกว่า 0")
            mat = self._get("materials", mid)
            if mat["qty"] < qty:
                raise ApiError(f"วัตถุดิบไม่พอ: {mat['name']} คงเหลือ {mat['qty']} {mat['unit']}", 409)
            self.conn.execute("UPDATE teak_materials SET qty=qty-? WHERE id=?", (qty, mid))
            self._insert("teak_production_materials",
                         {"production_id": wid, "material_id": mid, "qty": qty, "unit_cost": mat["unit_cost"]})
        if w.get("order_id"):
            self.conn.execute("UPDATE teak_orders SET status='in_production' WHERE id=? AND status IN ('quote','confirmed')",
                              (w["order_id"],))
        if status == "done":
            self._finish_production(wid)
        return self.detail("production", wid)

    def _finish_production(self, wid):
        w = self._get("production", wid)
        mat_cost = self.conn.execute("SELECT COALESCE(SUM(qty*unit_cost),0) FROM teak_production_materials "
                                     "WHERE production_id=?", (wid,)).fetchone()[0]
        p = self._get("products", w["product_id"])
        unit_cost = (mat_cost + (w["labor_cost"] or 0)) / w["qty"]
        upd = {"stock_qty": p["stock_qty"] + w["qty"]}
        if unit_cost > 0:  # weighted average cost of finished goods
            total = p["stock_qty"] + w["qty"]
            upd["unit_cost"] = round((p["stock_qty"] * p["unit_cost"] + w["qty"] * unit_cost) / total, 2)
        self._set("teak_products", p["id"], upd)
        self._set("teak_production", wid, {"status": "done", "completed_date": date.today().isoformat()})
        if w["order_id"]:
            self.conn.execute("UPDATE teak_orders SET status='ready' WHERE id=? AND status='in_production' AND NOT EXISTS "
                              "(SELECT 1 FROM teak_production WHERE order_id=? AND status NOT IN ('done','cancelled'))",
                              (w["order_id"], w["order_id"]))

    def _return_materials(self, wid):
        for m in rows(self.conn.execute("SELECT material_id, qty FROM teak_production_materials WHERE production_id=?", (wid,))):
            self.conn.execute("UPDATE teak_materials SET qty=qty+? WHERE id=?", (m["qty"], m["material_id"]))

    # ---------- update ----------
    def update(self, res, rid, data):
        clean = self._clean(res, data, partial=True)
        if res == "orders":
            o = self._get("orders", rid)
            if o["status"] == "delivered":
                if set(clean) - {"note"} or data.get("items"):
                    raise ApiError("ออเดอร์ส่งมอบแล้ว แก้ไขได้เฉพาะหมายเหตุ")
            if data.get("items"):
                items = self._clean_items(data["items"])
                self.conn.execute("DELETE FROM teak_order_items WHERE order_id=?", (rid,))
                for it in items:
                    self._insert("teak_order_items", {"order_id": rid, **it})
            new_status = clean.pop("status", None)
            self._set("teak_orders", rid, clean)
            if new_status == "delivered" and o["status"] != "delivered":
                self._deliver(rid)
            elif new_status and o["status"] != "delivered":
                self._set("teak_orders", rid, {"status": new_status})
            return self.detail("orders", rid)
        if res == "production":
            w = self._get("production", rid)
            if w["status"] in ("done", "cancelled"):
                if set(clean) - {"note", "craftsman"}:
                    raise ApiError("ใบสั่งผลิตปิดแล้ว แก้ไขได้เฉพาะหมายเหตุ/ช่าง")
            if "product_id" in clean and clean["product_id"] != w["product_id"]:
                raise ApiError("เปลี่ยนสินค้าในใบสั่งผลิตไม่ได้ ให้ยกเลิกแล้วสร้างใหม่")
            if "qty" in clean:
                if clean["qty"] <= 0 or not float(clean["qty"]).is_integer():
                    raise ApiError("qty ต้องเป็นจำนวนเต็มมากกว่า 0")
                clean["qty"] = int(clean["qty"])
            new_status = clean.pop("status", None)
            self._set("teak_production", rid, clean)
            if new_status and new_status != w["status"] and w["status"] not in ("done", "cancelled"):
                if new_status == "done":
                    self._finish_production(rid)
                elif new_status == "cancelled":
                    self._return_materials(rid)
                    self._set("teak_production", rid, {"status": "cancelled"})
                else:
                    self._set("teak_production", rid, {"status": new_status})
            return self.detail("production", rid)
        if res == "purchases":
            raise ApiError("แก้ไขใบรับซื้อไม่ได้ ให้ลบแล้วบันทึกใหม่")
        if res == "products" and "sku" in clean:
            dup = self.conn.execute("SELECT 1 FROM teak_products WHERE sku=? AND id!=?", (clean["sku"], rid)).fetchone()
            if dup:
                raise ApiError("SKU นี้มีอยู่แล้ว", 409)
        self._get(res, rid)
        self._set(SPEC[res]["table"], rid, clean)
        return self.detail(res, rid)

    # ---------- delete ----------
    def delete(self, res, rid):
        rec = self._get(res, rid)
        if res == "orders":
            if rec["status"] == "delivered":
                raise ApiError("ลบออเดอร์ที่ส่งมอบแล้วไม่ได้", 409)
            if self.conn.execute("SELECT 1 FROM teak_payments WHERE order_id=?", (rid,)).fetchone():
                raise ApiError("ออเดอร์มีการรับชำระแล้ว ให้เปลี่ยนสถานะเป็นยกเลิกแทน", 409)
        if res == "production":
            if rec["status"] == "done":
                raise ApiError("ลบใบสั่งผลิตที่ผลิตเสร็จแล้วไม่ได้", 409)
            if rec["status"] != "cancelled":
                self._return_materials(rid)
        if res == "purchases":
            m = self._get("materials", rec["material_id"])
            if m["qty"] < rec["qty"]:
                raise ApiError("วัตถุดิบถูกใช้ไปแล้ว ลบใบรับซื้อนี้ไม่ได้", 409)
            remaining = m["qty"] - rec["qty"]
            cost = ((m["qty"] * m["unit_cost"] - rec["qty"] * rec["unit_cost"]) / remaining) if remaining else m["unit_cost"]
            self._set("teak_materials", m["id"], {"qty": round(remaining, 4), "unit_cost": round(max(cost, 0), 2)})
        self.conn.execute(f"DELETE FROM {SPEC[res]['table']} WHERE id=?", (rid,))
        return {"deleted": rid}

    # ---------- dashboard ----------
    def dashboard(self):
        orders = self._orders_query()
        today = date.today()
        month = today.isoformat()[:7]
        live = [o for o in orders if o["status"] != "cancelled"]
        sold = [o for o in live if o["status"] != "quote"]
        delivered = [o for o in orders if o["status"] == "delivered"]
        products = self.list("products")
        materials = self.list("materials")
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        sales = sum(o["total"] for o in delivered)
        cogs = sum(o["cost"] for o in delivered)
        top = rows(self.conn.execute("""
            SELECT p.name, SUM(i.qty) AS qty, SUM(i.qty*i.unit_price) AS revenue
            FROM teak_order_items i JOIN teak_orders o ON o.id=i.order_id JOIN teak_products p ON p.id=i.product_id
            WHERE o.status NOT IN ('cancelled','quote') GROUP BY p.id ORDER BY revenue DESC LIMIT 6"""))
        by_type = {}
        for o in sold:
            by_type[o["customer_type"]] = by_type.get(o["customer_type"], 0) + o["total"]
        months = []
        for k in range(5, -1, -1):
            y, m = today.year, today.month - k
            while m <= 0:
                m += 12
                y -= 1
            key = f"{y}-{m:02d}"
            months.append({"month": key, "total": round(sum(o["total"] for o in sold if o["order_date"][:7] == key), 2)})
        return {
            "kpis": {
                "sales_delivered": round(sales, 2),
                "gross_profit": round(sales - cogs, 2),
                "gross_margin_pct": round((sales - cogs) / sales * 100, 1) if sales else 0,
                "orders_this_month": sum(1 for o in sold if o["order_date"][:7] == month),
                "pipeline_value": round(sum(o["total"] for o in live if o["status"] in ACTIVE_ORDER), 2),
                "quote_value": round(sum(o["total"] for o in live if o["status"] == "quote"), 2),
                "receivable": round(sum(o["balance"] for o in live if o["balance"] > 0 and o["status"] != "quote"), 2),
                "received_this_month": round(q("SELECT COALESCE(SUM(CASE WHEN kind='refund' THEN -amount ELSE amount END),0) "
                                               "FROM teak_payments WHERE substr(paid_date,1,7)=?", month), 2),
                "overdue_orders": sum(1 for o in orders if o["overdue"]),
                "production_active": q("SELECT COUNT(*) FROM teak_production WHERE status NOT IN ('done','cancelled')"),
                "inventory_value": round(sum(p["stock_qty"] * p["unit_cost"] for p in products)
                                         + sum(m["value"] for m in materials), 2),
            },
            "monthly_sales": months,
            "top_products": top,
            "sales_by_customer_type": [{"type": k, "total": round(v, 2)} for k, v in
                                       sorted(by_type.items(), key=lambda x: -x[1])],
            "low_stock_products": [{"name": p["name"], "stock_qty": p["stock_qty"], "reorder_level": p["reorder_level"]}
                                   for p in products if p["low_stock"]],
            "low_stock_materials": [{"name": m["name"], "qty": m["qty"], "unit": m["unit"],
                                     "reorder_level": m["reorder_level"]} for m in materials if m["low_stock"]],
            "overdue": [{"id": o["id"], "customer_name": o["customer_name"], "due_date": o["due_date"],
                         "status": o["status"]} for o in orders if o["overdue"]],
        }


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM teak_products").fetchone()[0]:
        return
    erp = TeakERP(conn)
    t = date.today()
    d = lambda n: (t - timedelta(days=n)).isoformat()
    c = lambda res, data: erp._tx(lambda: erp.create(res, data))
    for s in [dict(name="สักทองแพร่ ค้าไม้", phone="054-511-222", province="แพร่", supplies="ไม้สักแปรรูป เกรด A/B"),
              dict(name="ลำปางไม้เก่า", phone="054-322-111", province="ลำปาง", supplies="ไม้สักเก่ารื้อบ้าน"),
              dict(name="เคมีภัณฑ์งานไม้ บางบัวทอง", phone="02-555-0101", province="นนทบุรี", supplies="น้ำมันรักษาเนื้อไม้ แลกเกอร์ อุปกรณ์")]:
        c("suppliers", s)
    for m in [dict(name="ไม้สักแปรรูป เกรด A", grade="A", unit="cu_ft", qty=0, unit_cost=0, reorder_level=40, supplier_id=1),
              dict(name="ไม้สักแปรรูป เกรด B", grade="B", unit="cu_ft", qty=0, unit_cost=0, reorder_level=30, supplier_id=1),
              dict(name="ไม้สักเก่า (Reclaimed)", grade="reclaimed", unit="cu_ft", qty=0, unit_cost=0, reorder_level=20, supplier_id=2),
              dict(name="น้ำมันรักษาเนื้อไม้", grade="-", unit="litre", qty=0, unit_cost=0, reorder_level=10, supplier_id=3),
              dict(name="ชุดน็อต/บานพับทองเหลือง", grade="-", unit="set", qty=0, unit_cost=0, reorder_level=15, supplier_id=3)]:
        c("materials", m)
    for p in [(1, 1, 120, 950, d(60), "PR-2401"), (2, 1, 80, 650, d(45), "PR-2417"), (3, 2, 60, 900, d(40), "LP-0098"),
              (4, 3, 25, 280, d(30), "BB-551"), (5, 3, 40, 150, d(30), "BB-551")]:
        c("purchases", dict(material_id=p[0], supplier_id=p[1], qty=p[2], unit_cost=p[3], purchase_date=p[4], invoice_no=p[5]))
    for p in [dict(sku="TB-180", name="โต๊ะอาหารไม้สัก 180 ซม.", category="table", wood_grade="A", finish="oiled",
                   dimensions="180×90×75 ซม.", unit_price=28500, unit_cost=14200, stock_qty=3, reorder_level=2),
              dict(sku="CH-01", name="เก้าอี้ไม้สักพนักพิงโค้ง", category="chair", wood_grade="A", finish="oiled",
                   dimensions="45×50×95 ซม.", unit_price=3900, unit_cost=1700, stock_qty=14, reorder_level=8),
              dict(sku="BD-06", name="เตียงไม้สัก 6 ฟุต", category="bed", wood_grade="A", finish="lacquer",
                   dimensions="190×210×110 ซม.", unit_price=35900, unit_cost=18500, stock_qty=1, reorder_level=1),
              dict(sku="SF-3S", name="โซฟาไม้สัก 3 ที่นั่ง พร้อมเบาะ", category="sofa", wood_grade="B", finish="natural",
                   dimensions="200×80×85 ซม.", unit_price=24900, unit_cost=12000, stock_qty=2, reorder_level=1),
              dict(sku="CB-4D", name="ตู้เสื้อผ้าไม้สัก 4 บาน", category="cabinet", wood_grade="A", finish="lacquer",
                   dimensions="200×60×200 ซม.", unit_price=42000, unit_cost=21500, stock_qty=0, reorder_level=1),
              dict(sku="OD-LG", name="เก้าอี้สนามไม้สักเก่า", category="outdoor", wood_grade="reclaimed", finish="natural",
                   dimensions="70×80×90 ซม.", unit_price=6500, unit_cost=2900, stock_qty=6, reorder_level=4),
              dict(sku="DC-TR", name="ถาดไม้สักแกะลาย", category="decor", wood_grade="C", finish="oiled",
                   dimensions="45×30×5 ซม.", unit_price=890, unit_cost=320, stock_qty=25, reorder_level=10)]:
        c("products", p)
    for cu in [dict(name="คุณสมชาย ใจดี", type="retail", phone="081-234-5678", address="เชียงใหม่"),
               dict(name="บ้านริมน้ำ รีสอร์ท", type="hotel", phone="053-888-999", line_id="riverside.resort", address="อ.แม่ริม เชียงใหม่"),
               dict(name="Studio Wood Interior", type="designer", phone="02-111-2233", line_id="studiowood", address="กรุงเทพฯ"),
               dict(name="ร้านค้าออนไลน์ TeakHome", type="online", phone="089-999-0000", address="นนทบุรี")]:
        c("customers", cu)
    o1 = c("orders", dict(customer_id=1, order_date=d(50), due_date=d(40), discount=500, delivery_fee=800,
                          items=[{"product_id": 1, "qty": 1}, {"product_id": 2, "qty": 6}]))
    c("payments", dict(order_id=o1["id"], amount=15000, kind="deposit", method="transfer", paid_date=d(50)))
    erp._tx(lambda: erp.update("orders", o1["id"], {"status": "delivered"}))
    c("payments", dict(order_id=o1["id"], amount=37200, kind="balance", method="cash", paid_date=d(40)))
    o2 = c("orders", dict(customer_id=2, order_date=d(20), due_date=(t + timedelta(days=15)).isoformat(), discount=10000,
                          delivery_fee=3000, items=[{"product_id": 6, "qty": 10, "unit_price": 6000},
                                                    {"product_id": 1, "qty": 2, "unit_price": 27000}]))
    c("payments", dict(order_id=o2["id"], amount=50000, kind="deposit", method="transfer", paid_date=d(20)))
    c("production", dict(product_id=6, order_id=o2["id"], qty=4, status="assembling", craftsman="ช่างสมพร",
                         due_date=(t + timedelta(days=7)).isoformat(), labor_cost=4800,
                         materials=[{"material_id": 3, "qty": 18}, {"material_id": 4, "qty": 2}]))
    o3 = c("orders", dict(customer_id=3, order_date=d(8), due_date=d(1), items=[{"product_id": 5, "qty": 1}, {"product_id": 3, "qty": 1}]))
    c("payments", dict(order_id=o3["id"], amount=30000, kind="deposit", method="transfer", paid_date=d(8)))
    c("production", dict(product_id=5, order_id=o3["id"], qty=1, status="finishing", craftsman="ช่างบุญมี",
                         due_date=d(1), labor_cost=7000,
                         materials=[{"material_id": 1, "qty": 22}, {"material_id": 5, "qty": 2}, {"material_id": 4, "qty": 1.5}]))
    o4 = c("orders", dict(customer_id=4, order_date=d(3), items=[{"product_id": 7, "qty": 12, "unit_price": 750},
                                                                  {"product_id": 2, "qty": 4}]))
    erp._tx(lambda: erp.update("orders", o4["id"], {"status": "delivered"}))
    c("payments", dict(order_id=o4["id"], amount=24600, kind="full", method="promptpay", paid_date=d(3)))
    c("production", dict(product_id=2, qty=8, status="done", craftsman="ช่างสมพร", labor_cost=6400,
                         materials=[{"material_id": 2, "qty": 16}, {"material_id": 4, "qty": 2}]))
    c("orders", dict(customer_id=2, status="quote", order_date=d(1), items=[{"product_id": 3, "qty": 8, "unit_price": 33000}]))
