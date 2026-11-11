"""ทังทังซุป (Tang Tang Soup) mala shop — stock & staff ERP.

- items       : ingredients / skewers with stock, cost, selling price, reorder & par levels
- receipts    : รับสินค้าเข้า  -> stock +qty, weighted-average cost
- sales       : ขาย (bill with lines) -> stock -qty, blocked when stock is short
- waste       : ตัดของเสีย/ปรับยอด -> stock -qty
- reorder     : สินค้าต้องสั่งเพิ่ม = qty <= reorder_level, suggest up to par_level
- staff       : พนักงาน + รับสมัคร (applicant -> interview -> hired / rejected / resigned)
"""
from datetime import date, timedelta

from common import ApiError, clean_fields, now_iso, rows

SCHEMA = """
CREATE TABLE IF NOT EXISTS mala_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT DEFAULT 'meat',
    unit TEXT DEFAULT 'skewer',
    qty REAL DEFAULT 0,
    unit_cost REAL DEFAULT 0,
    sell_price REAL DEFAULT 0,
    reorder_level REAL DEFAULT 0,
    par_level REAL DEFAULT 0,
    supplier TEXT,
    sellable INTEGER DEFAULT 1,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS mala_staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    nickname TEXT,
    position TEXT DEFAULT 'server',
    employment TEXT DEFAULT 'full_time',
    wage REAL DEFAULT 0,
    wage_type TEXT DEFAULT 'day',
    phone TEXT,
    line_id TEXT,
    status TEXT DEFAULT 'applicant',
    applied_date TEXT,
    interview_date TEXT,
    start_date TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS mala_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES mala_items(id),
    qty REAL NOT NULL,
    unit_cost REAL NOT NULL,
    supplier TEXT,
    received_date TEXT,
    staff_id INTEGER REFERENCES mala_staff(id),
    note TEXT
);
CREATE TABLE IF NOT EXISTS mala_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_date TEXT NOT NULL,
    sale_time TEXT,
    channel TEXT DEFAULT 'dine_in',
    payment TEXT DEFAULT 'cash',
    discount REAL DEFAULT 0,
    staff_id INTEGER REFERENCES mala_staff(id),
    note TEXT
);
CREATE TABLE IF NOT EXISTS mala_sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES mala_sales(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES mala_items(id),
    qty REAL NOT NULL,
    unit_price REAL NOT NULL,
    unit_cost REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mala_waste (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES mala_items(id),
    qty REAL NOT NULL,
    reason TEXT DEFAULT 'spoiled',
    waste_date TEXT,
    staff_id INTEGER REFERENCES mala_staff(id),
    note TEXT
);
"""

ENUMS = {
    "items.category": ["meat", "seafood", "meatball", "vegetable", "tofu", "noodle", "soup_base", "sauce", "drink", "other"],
    "items.unit": ["skewer", "kg", "g", "pack", "piece", "bottle", "litre", "bag", "box"],
    "staff.position": ["manager", "cook", "prep", "server", "cashier", "delivery", "dishwasher"],
    "staff.employment": ["full_time", "part_time"],
    "staff.wage_type": ["hour", "day", "month"],
    "staff.status": ["applicant", "interview", "hired", "rejected", "resigned"],
    "sales.channel": ["dine_in", "takeaway", "grab", "lineman", "shopee", "robinhood"],
    "sales.payment": ["cash", "promptpay", "card", "app"],
    "waste.reason": ["spoiled", "expired", "dropped", "stock_count", "staff_meal"],
}

SPEC = {
    "items": dict(table="mala_items", required=["name"],
                  fields=["name", "category", "unit", "qty", "unit_cost", "sell_price", "reorder_level",
                          "par_level", "supplier", "sellable", "active"]),
    "staff": dict(table="mala_staff", required=["name"],
                  fields=["name", "nickname", "position", "employment", "wage", "wage_type", "phone", "line_id",
                          "status", "applied_date", "interview_date", "start_date", "note"]),
    "receipts": dict(table="mala_receipts", required=["item_id", "qty"],
                     fields=["item_id", "qty", "unit_cost", "supplier", "received_date", "staff_id", "note"]),
    "sales": dict(table="mala_sales", required=[],
                  fields=["sale_date", "sale_time", "channel", "payment", "discount", "staff_id", "note"]),
    "waste": dict(table="mala_waste", required=["item_id", "qty"],
                  fields=["item_id", "qty", "reason", "waste_date", "staff_id", "note"]),
}
NUMERIC = {"qty", "unit_cost", "sell_price", "reorder_level", "par_level", "sellable", "active", "wage",
           "item_id", "staff_id", "discount"}
INTEGERS = {"sellable", "active", "item_id", "staff_id"}
DATES = ("applied_date", "interview_date", "start_date", "received_date", "sale_date", "waste_date")


class MalaERP:
    def __init__(self, conn):
        self.conn = conn

    # ---------- helpers ----------
    def _clean(self, res, data, partial=False):
        s = SPEC[res]
        enums = {k.split(".", 1)[1]: v for k, v in ENUMS.items() if k.startswith(res + ".")}
        out = clean_fields(data, s["fields"], s["required"], enums, NUMERIC, INTEGERS, partial)
        for f in DATES:
            if out.get(f) is not None:
                try:
                    out[f] = date.fromisoformat(str(out[f])).isoformat()
                except ValueError:
                    raise ApiError(f"{f} ต้องอยู่ในรูปแบบ YYYY-MM-DD")
        for f in ("qty", "unit_cost", "sell_price", "reorder_level", "par_level", "wage", "discount"):
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

    def _staff_ok(self, sid):
        if sid:
            self._get("staff", sid)

    # ---------- routing ----------
    def route(self, method, parts, body_fn):
        if method == "GET" and parts == ["dashboard"]:
            return 200, self.dashboard()
        if method == "GET" and parts == ["meta"]:
            return 200, {"enums": ENUMS}
        if method == "GET" and parts == ["reorder"]:
            return 200, self.reorder()
        if not parts or parts[0] not in SPEC or len(parts) > 2:
            raise ApiError("ไม่พบ resource", 404)
        res, rid = parts[0], None
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
    def _item_status(self, i):
        if i["qty"] <= 0:
            return "out"
        if i["qty"] <= i["reorder_level"]:
            return "low"
        return "ok"

    def list(self, res):
        q = self.conn.execute
        if res == "items":
            data = rows(q("SELECT * FROM mala_items ORDER BY category, name"))
            week = (date.today() - timedelta(days=6)).isoformat()
            sold = {r["item_id"]: r["qty"] for r in rows(q(
                """SELECT si.item_id, SUM(si.qty) AS qty FROM mala_sale_items si JOIN mala_sales s ON s.id=si.sale_id
                   WHERE s.sale_date >= ? GROUP BY si.item_id""", (week,)))}
            for i in data:
                i["stock_status"] = self._item_status(i)
                i["value"] = round(i["qty"] * i["unit_cost"], 2)
                i["sold_7d"] = sold.get(i["id"], 0)
            return data
        if res == "staff":
            return rows(q("""SELECT * FROM mala_staff ORDER BY
                CASE status WHEN 'hired' THEN 0 WHEN 'interview' THEN 1 WHEN 'applicant' THEN 2 ELSE 3 END, name"""))
        if res == "receipts":
            return rows(q("""SELECT r.*, i.name AS item_name, i.unit, st.nickname AS staff_name,
                               ROUND(r.qty*r.unit_cost,2) AS total
                             FROM mala_receipts r JOIN mala_items i ON i.id=r.item_id
                             LEFT JOIN mala_staff st ON st.id=r.staff_id
                             ORDER BY r.received_date DESC, r.id DESC"""))
        if res == "waste":
            return rows(q("""SELECT w.*, i.name AS item_name, i.unit, ROUND(w.qty*i.unit_cost,2) AS value,
                               st.nickname AS staff_name
                             FROM mala_waste w JOIN mala_items i ON i.id=w.item_id
                             LEFT JOIN mala_staff st ON st.id=w.staff_id ORDER BY w.waste_date DESC, w.id DESC"""))
        if res == "sales":
            return self._sales()
        raise ApiError("ไม่พบ resource", 404)

    def _sales(self, where="", args=()):
        data = rows(self.conn.execute(f"""
            SELECT s.*, st.nickname AS staff_name,
              COALESCE((SELECT SUM(qty*unit_price) FROM mala_sale_items x WHERE x.sale_id=s.id),0) AS subtotal,
              COALESCE((SELECT SUM(qty*unit_cost) FROM mala_sale_items x WHERE x.sale_id=s.id),0) AS cost,
              COALESCE((SELECT SUM(qty) FROM mala_sale_items x WHERE x.sale_id=s.id),0) AS item_qty,
              (SELECT GROUP_CONCAT(i.name || ' ×' || x.qty, ', ') FROM mala_sale_items x
                 JOIN mala_items i ON i.id=x.item_id WHERE x.sale_id=s.id) AS items_summary
            FROM mala_sales s LEFT JOIN mala_staff st ON st.id=s.staff_id {where}
            ORDER BY s.sale_date DESC, s.sale_time DESC, s.id DESC""", args))
        for s in data:
            s["total"] = round(s["subtotal"] - (s["discount"] or 0), 2)
            s["profit"] = round(s["total"] - s["cost"], 2)
        return data

    def detail(self, res, rid):
        if res == "sales":
            found = self._sales("WHERE s.id=?", (rid,))
            if not found:
                raise ApiError(f"ไม่พบ sales id={rid}", 404)
            s = found[0]
            s["items"] = rows(self.conn.execute(
                """SELECT x.*, i.name AS item_name, i.unit FROM mala_sale_items x
                   JOIN mala_items i ON i.id=x.item_id WHERE x.sale_id=?""", (rid,)))
            return s
        return self._get(res, rid)

    def reorder(self):
        out = []
        for i in self.list("items"):
            if i["active"] and i["stock_status"] != "ok":
                target = i["par_level"] if i["par_level"] > i["reorder_level"] else i["reorder_level"] * 2
                suggest = max(round(target - i["qty"], 2), 0)
                if suggest == 0:
                    suggest = max(i["reorder_level"], 1)
                out.append({**i, "suggest_qty": suggest, "suggest_cost": round(suggest * i["unit_cost"], 2)})
        out.sort(key=lambda i: (i["stock_status"] != "out", i["supplier"] or "", i["name"]))
        return out

    # ---------- create ----------
    def create(self, res, data):
        clean = self._clean(res, data)
        if res == "receipts":
            return self._receive(clean)
        if res == "sales":
            return self._sell(clean, data.get("items"))
        if res == "waste":
            return self._waste(clean)
        if res == "staff":
            clean.setdefault("applied_date", date.today().isoformat())
            if clean.get("status") == "hired":
                clean.setdefault("start_date", date.today().isoformat())
        if res == "items" and self.conn.execute("SELECT 1 FROM mala_items WHERE name=?", (clean["name"],)).fetchone():
            raise ApiError("มีสินค้าชื่อนี้อยู่แล้ว", 409)
        return self.detail(res, self._insert(SPEC[res]["table"], clean))

    def _receive(self, r):
        if r["qty"] <= 0:
            raise ApiError("จำนวนรับเข้าต้องมากกว่า 0")
        item = self._get("items", r["item_id"])
        self._staff_ok(r.get("staff_id"))
        if r.get("unit_cost") is None:
            r["unit_cost"] = item["unit_cost"]
        r.setdefault("received_date", date.today().isoformat())
        if not r.get("supplier"):
            r["supplier"] = item["supplier"]
        new_qty = item["qty"] + r["qty"]
        avg = (item["qty"] * item["unit_cost"] + r["qty"] * r["unit_cost"]) / new_qty
        self._set("mala_items", item["id"], {"qty": round(new_qty, 4), "unit_cost": round(avg, 2)})
        return self.detail("receipts", self._insert("mala_receipts", r))

    def _waste(self, w):
        if w["qty"] <= 0:
            raise ApiError("จำนวนต้องมากกว่า 0")
        item = self._get("items", w["item_id"])
        self._staff_ok(w.get("staff_id"))
        if item["qty"] < w["qty"]:
            raise ApiError(f"ตัดได้ไม่เกินคงเหลือ ({item['qty']})", 409)
        w.setdefault("waste_date", date.today().isoformat())
        self._set("mala_items", item["id"], {"qty": round(item["qty"] - w["qty"], 4)})
        return self.detail("waste", self._insert("mala_waste", w))

    def _sell(self, s, items):
        if not isinstance(items, list) or not items:
            raise ApiError("บิลต้องมีสินค้าอย่างน้อย 1 รายการ")
        self._staff_ok(s.get("staff_id"))
        need = {}
        lines = []
        for it in items:
            try:
                iid, qty = int(it["item_id"]), float(it["qty"])
            except (KeyError, TypeError, ValueError):
                raise ApiError("รายการสินค้าไม่ถูกต้อง")
            if qty <= 0:
                raise ApiError("จำนวนต้องมากกว่า 0")
            item = self._get("items", iid)
            if not item["active"]:
                raise ApiError(f"{item['name']} ปิดการขายอยู่")
            price = it.get("unit_price")
            price = item["sell_price"] if price in (None, "") else float(price)
            if price < 0:
                raise ApiError("ราคาต้องไม่ติดลบ")
            need[iid] = need.get(iid, 0) + qty
            lines.append({"item_id": iid, "qty": qty, "unit_price": price, "unit_cost": item["unit_cost"]})
        short = []
        for iid, qty in need.items():
            item = self._get("items", iid)
            if item["qty"] < qty:
                short.append(f"{item['name']} (เหลือ {item['qty']:g})")
        if short:
            raise ApiError("สินค้าไม่พอขาย: " + ", ".join(short), 409)
        now = now_iso()
        s.setdefault("sale_date", now[:10])
        s.setdefault("sale_time", now[11:16])
        sid = self._insert("mala_sales", s)
        for ln in lines:
            self._insert("mala_sale_items", {"sale_id": sid, **ln})
            self.conn.execute("UPDATE mala_items SET qty=ROUND(qty-?,4) WHERE id=?", (ln["qty"], ln["item_id"]))
        sale = self.detail("sales", sid)
        if sale["total"] < 0:
            raise ApiError("ส่วนลดมากกว่ายอดขาย")
        return sale

    # ---------- update / delete ----------
    def update(self, res, rid, data):
        if res in ("receipts", "sales", "waste"):
            raise ApiError("รายการเคลื่อนไหวสต็อกแก้ไขไม่ได้ ให้ลบ (ยกเลิก) แล้วบันทึกใหม่")
        clean = self._clean(res, data, partial=True)
        cur = self._get(res, rid)
        if res == "items" and "name" in clean and \
                self.conn.execute("SELECT 1 FROM mala_items WHERE name=? AND id!=?", (clean["name"], rid)).fetchone():
            raise ApiError("มีสินค้าชื่อนี้อยู่แล้ว", 409)
        if res == "staff" and clean.get("status") == "hired" and cur["status"] != "hired" and not cur["start_date"]:
            clean.setdefault("start_date", date.today().isoformat())
        self._set(SPEC[res]["table"], rid, clean)
        return self.detail(res, rid)

    def delete(self, res, rid):
        rec = self._get(res, rid)
        if res == "receipts":
            item = self._get("items", rec["item_id"])
            if item["qty"] < rec["qty"]:
                raise ApiError("สินค้าล็อตนี้ถูกขาย/ใช้ไปแล้ว ยกเลิกการรับเข้าไม่ได้", 409)
            remaining = item["qty"] - rec["qty"]
            cost = (item["qty"] * item["unit_cost"] - rec["qty"] * rec["unit_cost"]) / remaining if remaining else item["unit_cost"]
            self._set("mala_items", item["id"], {"qty": round(remaining, 4), "unit_cost": round(max(cost, 0), 2)})
        elif res == "sales":  # void bill -> return stock
            for x in rows(self.conn.execute("SELECT item_id, qty FROM mala_sale_items WHERE sale_id=?", (rid,))):
                self.conn.execute("UPDATE mala_items SET qty=ROUND(qty+?,4) WHERE id=?", (x["qty"], x["item_id"]))
        elif res == "waste":
            self.conn.execute("UPDATE mala_items SET qty=ROUND(qty+?,4) WHERE id=?", (rec["qty"], rec["item_id"]))
        elif res == "items":
            used = self.conn.execute(
                "SELECT (SELECT COUNT(*) FROM mala_receipts WHERE item_id=?)+(SELECT COUNT(*) FROM mala_sale_items WHERE item_id=?)"
                "+(SELECT COUNT(*) FROM mala_waste WHERE item_id=?)", (rid, rid, rid)).fetchone()[0]
            if used:
                raise ApiError("สินค้านี้มีประวัติรับเข้า/ขายแล้ว ให้ปิดการใช้งานแทนการลบ", 409)
        elif res == "staff":
            self.conn.execute("UPDATE mala_receipts SET staff_id=NULL WHERE staff_id=?", (rid,))
            self.conn.execute("UPDATE mala_sales SET staff_id=NULL WHERE staff_id=?", (rid,))
            self.conn.execute("UPDATE mala_waste SET staff_id=NULL WHERE staff_id=?", (rid,))
        self.conn.execute(f"DELETE FROM {SPEC[res]['table']} WHERE id=?", (rid,))
        return {"deleted": rid}

    # ---------- dashboard ----------
    def dashboard(self):
        t = date.today()
        today, month, week = t.isoformat(), t.isoformat()[:7], (t - timedelta(days=6)).isoformat()
        sales = self._sales()
        s_today = [s for s in sales if s["sale_date"] == today]
        s_month = [s for s in sales if s["sale_date"][:7] == month]
        items = self.list("items")
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        daily = []
        for k in range(6, -1, -1):
            d = (t - timedelta(days=k)).isoformat()
            daily.append({"date": d, "total": round(sum(s["total"] for s in sales if s["sale_date"] == d), 2)})
        by_channel = {}
        for s in s_month:
            by_channel[s["channel"]] = by_channel.get(s["channel"], 0) + s["total"]
        staff = self.list("staff")
        reorder = self.reorder()
        return {
            "kpis": {
                "sales_today": round(sum(s["total"] for s in s_today), 2),
                "bills_today": len(s_today),
                "profit_today": round(sum(s["profit"] for s in s_today), 2),
                "sales_month": round(sum(s["total"] for s in s_month), 2),
                "profit_month": round(sum(s["profit"] for s in s_month), 2),
                "received_month": round(q("SELECT COALESCE(SUM(qty*unit_cost),0) FROM mala_receipts "
                                          "WHERE substr(received_date,1,7)=?", month), 2),
                "waste_month": round(q("SELECT COALESCE(SUM(w.qty*i.unit_cost),0) FROM mala_waste w JOIN mala_items i "
                                       "ON i.id=w.item_id WHERE substr(w.waste_date,1,7)=?", month), 2),
                "stock_value": round(sum(i["value"] for i in items if i["active"]), 2),
                "reorder_count": len(reorder),
                "out_of_stock": sum(1 for i in reorder if i["stock_status"] == "out"),
                "staff_active": sum(1 for s in staff if s["status"] == "hired"),
                "applicants": sum(1 for s in staff if s["status"] in ("applicant", "interview")),
            },
            "daily_sales": daily,
            "top_items": rows(self.conn.execute(
                """SELECT i.name, i.unit, SUM(x.qty) AS qty, SUM(x.qty*x.unit_price) AS revenue
                   FROM mala_sale_items x JOIN mala_sales s ON s.id=x.sale_id JOIN mala_items i ON i.id=x.item_id
                   WHERE s.sale_date >= ? GROUP BY i.id ORDER BY qty DESC LIMIT 8""", (week,))),
            "sales_by_channel": [{"channel": k, "total": round(v, 2)} for k, v in sorted(by_channel.items(), key=lambda x: -x[1])],
            "reorder": [{"name": i["name"], "qty": i["qty"], "unit": i["unit"], "suggest_qty": i["suggest_qty"],
                         "stock_status": i["stock_status"]} for i in reorder[:8]],
            "applicants": [{"name": s["name"], "nickname": s["nickname"], "position": s["position"],
                            "status": s["status"], "interview_date": s["interview_date"]}
                           for s in staff if s["status"] in ("applicant", "interview")],
        }


def seed(conn):
    if conn.execute("SELECT COUNT(*) FROM mala_items").fetchone()[0]:
        return
    e = MalaERP(conn)
    c = lambda res, data: e._tx(lambda: e.create(res, data))
    t = date.today()
    d = lambda n: (t - timedelta(days=n)).isoformat()
    for s in [dict(name="สมศักดิ์ แซ่ลี้", nickname="เฮียศักดิ์", position="manager", employment="full_time", wage=18000,
                   wage_type="month", phone="081-000-1111", status="hired", start_date=d(400)),
              dict(name="วิภา ทองดี", nickname="ภา", position="cook", employment="full_time", wage=500, wage_type="day",
                   phone="082-000-2222", status="hired", start_date=d(200)),
              dict(name="ธนา ใจงาม", nickname="ต้น", position="cashier", employment="part_time", wage=60, wage_type="hour",
                   phone="083-000-3333", status="hired", start_date=d(60)),
              dict(name="กมลชนก ศรีสุข", nickname="มิว", position="server", employment="part_time", wage=55, wage_type="hour",
                   phone="084-000-4444", status="interview", interview_date=(t + timedelta(days=2)).isoformat(),
                   note="นักศึกษา ว่างเย็นและเสาร์-อาทิตย์"),
              dict(name="ประยูร มีสุข", nickname="ยูร", position="prep", employment="full_time", wage=450, wage_type="day",
                   phone="085-000-5555", status="applicant", note="เคยทำร้านหม้อไฟ 1 ปี")]:
        c("staff", s)
    items = [  # name, category, unit, sell, cost, reorder, par, supplier, sellable
        ("หมูสามชั้น", "meat", "skewer", 15, 6, 40, 150, "แม็คโคร", 1),
        ("เนื้อวัวสไลซ์", "meat", "skewer", 20, 9, 30, 120, "แม็คโคร", 1),
        ("ไส้กรอกไก่", "meat", "skewer", 10, 4, 40, 150, "แม็คโคร", 1),
        ("กุ้งสด", "seafood", "skewer", 25, 12, 20, 80, "ตลาดไท", 1),
        ("ปลาหมึก", "seafood", "skewer", 20, 9, 20, 80, "ตลาดไท", 1),
        ("ลูกชิ้นปลา", "meatball", "skewer", 10, 3.5, 50, 200, "โรงงานลูกชิ้นแม่กลอง", 1),
        ("ลูกชิ้นกุ้งไส้ไข่เค็ม", "meatball", "skewer", 15, 6, 30, 120, "โรงงานลูกชิ้นแม่กลอง", 1),
        ("เต้าหู้ปลา", "tofu", "skewer", 10, 3, 40, 150, "โรงงานลูกชิ้นแม่กลอง", 1),
        ("เห็ดเข็มทอง", "vegetable", "skewer", 10, 3, 30, 120, "ตลาดไท", 1),
        ("ผักกาดขาว", "vegetable", "skewer", 10, 2, 30, 100, "ตลาดไท", 1),
        ("วุ้นเส้น", "noodle", "skewer", 10, 2, 30, 100, "แม็คโคร", 1),
        ("น้ำซุปหม่าล่า", "soup_base", "litre", 0, 35, 5, 20, "ทำเองในร้าน", 0),
        ("พริกหม่าล่า (ผงหม่าล่า)", "sauce", "kg", 0, 380, 1, 4, "ร้านเครื่องเทศเยาวราช", 0),
        ("ชาไทย", "drink", "bottle", 35, 14, 12, 48, "ส่งตรงซัพพลายเออร์", 1),
        ("น้ำเปล่า", "drink", "bottle", 15, 5, 24, 96, "แม็คโคร", 1),
    ]
    for name, cat, unit, sell, cost, rl, par, sup, sellable in items:
        c("items", dict(name=name, category=cat, unit=unit, sell_price=sell, unit_cost=cost, reorder_level=rl,
                        par_level=par, supplier=sup, sellable=sellable))
    stock_in = {1: 160, 2: 120, 3: 150, 4: 60, 5: 80, 6: 220, 7: 120, 8: 150, 9: 110, 10: 100, 11: 100,
                12: 18, 13: 3, 14: 30, 15: 80}
    costs = {i + 1: it[4] for i, it in enumerate(items)}
    for iid, qty in stock_in.items():
        c("receipts", dict(item_id=iid, qty=qty, unit_cost=costs[iid], received_date=d(7), staff_id=1))
    import random
    rnd = random.Random(7)
    channels = ["dine_in"] * 5 + ["takeaway", "takeaway", "grab", "lineman"]
    sellable = [i + 1 for i, it in enumerate(items) if it[8] and i + 1 not in (4,)]
    for day in range(6, -1, -1):
        for b in range(rnd.randint(3, 6)):
            lines = [{"item_id": iid, "qty": rnd.randint(1, 4)} for iid in rnd.sample(sellable, rnd.randint(3, 6))]
            try:
                c("sales", dict(sale_date=d(day), sale_time=f"{rnd.randint(16, 22)}:{rnd.choice(['05', '20', '35', '50'])}",
                                channel=rnd.choice(channels), payment=rnd.choice(["cash", "promptpay", "promptpay", "app"]),
                                staff_id=3, items=lines))
            except ApiError:
                pass
    # make a couple of items clearly need re-ordering
    c("sales", dict(sale_date=d(0), sale_time="18:00", channel="dine_in", staff_id=3,
                    items=[{"item_id": 4, "qty": 50}]))
    c("waste", dict(item_id=10, qty=12, reason="spoiled", waste_date=d(1), staff_id=2, note="ผักเหี่ยว"))
    c("waste", dict(item_id=12, qty=6, reason="staff_meal", waste_date=d(0), staff_id=2))
