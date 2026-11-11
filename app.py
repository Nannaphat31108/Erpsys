"""DeskHop ERP — ระบบบริหารจัดการธุรกิจจองโต๊ะทำงานรายชั่วโมง

Zero-dependency backend (Python standard library only): http.server + sqlite3.
Run:  python3 app.py [--port 8000] [--db deskhop.db] [--seed]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import mala
import teak
from common import ApiError, now_iso, rows

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
VERIFY_VALID_DAYS = 30          # "verified" badge lasts 30 days after an inspection
FIRST_BOOKING_FREE_HOURS = 2    # acquisition promo: first two hours free

SCHEMA = """
CREATE TABLE IF NOT EXISTS venues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'cafe',
    area TEXT,
    bts_station TEXT,
    bts_walk_min INTEGER DEFAULT 0,
    hourly_rate REAL NOT NULL DEFAULT 0,
    expected_min_spend REAL DEFAULT 0,
    wifi_mbps REAL DEFAULT 0,
    noise_level TEXT DEFAULT 'moderate',
    commission_pct REAL DEFAULT 20,
    staff_trained INTEGER DEFAULT 0,
    last_verified TEXT,
    contact_line TEXT,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS desks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    zone TEXT DEFAULT 'normal',
    has_socket INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    occupation TEXT,
    phone TEXT,
    line_id TEXT,
    email TEXT,
    channel TEXT DEFAULT 'other',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    desk_id INTEGER NOT NULL REFERENCES desks(id),
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    hours REAL NOT NULL,
    rate REAL NOT NULL,
    discount REAL DEFAULT 0,
    amount REAL NOT NULL,
    payment_method TEXT DEFAULT 'card',
    status TEXT DEFAULT 'confirmed',
    note TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL REFERENCES venues(id),
    customer_id INTEGER REFERENCES customers(id),
    booking_id INTEGER REFERENCES bookings(id),
    rating INTEGER,
    category TEXT DEFAULT 'other',
    description TEXT,
    status TEXT DEFAULT 'open',
    response TEXT,
    created_at TEXT,
    responded_at TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id INTEGER NOT NULL REFERENCES venues(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL,
    wifi_mbps REAL,
    noise_level TEXT,
    photos_updated INTEGER DEFAULT 0,
    staff_briefed INTEGER DEFAULT 0,
    inspector TEXT,
    notes TEXT
);
"""

# Allowed values / field definitions used for validation of generic CRUD.
ENUMS = {
    "venues.type": ["cafe", "coworking"],
    "venues.noise_level": ["quiet", "moderate", "loud"],
    "desks.zone": ["quiet", "normal", "call_booth"],
    "desks.status": ["active", "maintenance", "inactive"],
    "customers.channel": ["instagram", "facebook", "tiktok", "referral", "google", "walk_in", "other"],
    "bookings.status": ["confirmed", "checked_in", "completed", "cancelled", "desk_not_ready"],
    "bookings.payment_method": ["card", "promptpay", "truemoney", "promo"],
    "issues.category": ["wifi", "noise", "outdated_photos", "desk_not_ready", "staff_unaware",
                        "hidden_cost", "app_bug", "other"],
    "issues.status": ["open", "responded", "resolved"],
    "verifications.noise_level": ["quiet", "moderate", "loud"],
}

TABLES = {
    "venues": {"required": ["name", "hourly_rate"],
               "fields": ["name", "type", "area", "bts_station", "bts_walk_min", "hourly_rate",
                          "expected_min_spend", "wifi_mbps", "noise_level", "commission_pct",
                          "staff_trained", "last_verified", "contact_line", "active"]},
    "desks": {"required": ["venue_id", "code"],
              "fields": ["venue_id", "code", "zone", "has_socket", "status"]},
    "customers": {"required": ["name"],
                  "fields": ["name", "occupation", "phone", "line_id", "email", "channel"]},
    "bookings": {"required": ["customer_id", "desk_id", "date", "start_time", "hours"],
                 "fields": ["customer_id", "desk_id", "date", "start_time", "hours",
                            "payment_method", "status", "note"]},
    "issues": {"required": ["venue_id"],
               "fields": ["venue_id", "customer_id", "booking_id", "rating", "category",
                          "description", "status", "response"]},
    "verifications": {"required": ["venue_id"],
                      "fields": ["venue_id", "checked_at", "wifi_mbps", "noise_level",
                                 "photos_updated", "staff_briefed", "inspector", "notes"]},
}

NUMERIC = {"bts_walk_min", "hourly_rate", "expected_min_spend", "wifi_mbps", "commission_pct",
           "staff_trained", "active", "venue_id", "has_socket", "customer_id", "desk_id", "hours",
           "booking_id", "rating", "photos_updated", "staff_briefed"}


def connect(db_path):
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.executescript(teak.SCHEMA)
    conn.executescript(mala.SCHEMA)
    return conn


def to_minutes(hhmm):
    if not isinstance(hhmm, str) or not re.fullmatch(r"\d{2}:\d{2}", hhmm):
        raise ApiError("start_time ต้องอยู่ในรูปแบบ HH:MM")
    h, m = map(int, hhmm.split(":"))
    if h > 23 or m > 59:
        raise ApiError("start_time ไม่ถูกต้อง")
    return h * 60 + m


def is_verified(last_verified, today=None):
    if not last_verified:
        return False
    today = today or date.today()
    try:
        d = date.fromisoformat(last_verified[:10])
    except ValueError:
        return False
    return (today - d).days <= VERIFY_VALID_DAYS


class ERP:
    """Business logic layer. All methods return JSON-serialisable data."""

    def __init__(self, conn):
        self.conn = conn

    # ---------- generic helpers ----------
    def _clean(self, table, data, partial=False):
        spec = TABLES[table]
        out = {}
        for f in spec["fields"]:
            if f in data:
                v = data[f]
                if v == "":
                    v = None
                if v is not None and f in NUMERIC:
                    try:
                        v = float(v)
                        if v.is_integer() and f not in {"hours", "hourly_rate", "expected_min_spend",
                                                        "wifi_mbps", "commission_pct"}:
                            v = int(v)
                    except (TypeError, ValueError):
                        raise ApiError(f"{f} ต้องเป็นตัวเลข")
                allowed = ENUMS.get(f"{table}.{f}")
                if allowed and v is not None and v not in allowed:
                    raise ApiError(f"{f} ต้องเป็นหนึ่งใน {', '.join(allowed)}")
                out[f] = v
        if not partial:
            missing = [f for f in spec["required"] if out.get(f) in (None, "")]
            if missing:
                raise ApiError("ข้อมูลที่จำเป็นยังไม่ครบ: " + ", ".join(missing))
        return out

    def _get(self, table, rid):
        r = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (rid,)).fetchone()
        if not r:
            raise ApiError(f"ไม่พบ {table} id={rid}", 404)
        return dict(r)

    def _insert(self, table, data):
        cols = ", ".join(data)
        qs = ", ".join("?" for _ in data)
        cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(data.values()))
        self.conn.commit()
        return self._get(table, cur.lastrowid)

    def _update(self, table, rid, data):
        self._get(table, rid)
        if data:
            sets = ", ".join(f"{k} = ?" for k in data)
            self.conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), rid])
            self.conn.commit()
        return self._get(table, rid)

    # ---------- listing (with joins for display) ----------
    def list(self, table):
        if table == "venues":
            data = rows(self.conn.execute("""
                SELECT v.*,
                  (SELECT COUNT(*) FROM desks d WHERE d.venue_id = v.id AND d.status = 'active') AS desk_count,
                  (SELECT ROUND(AVG(rating), 2) FROM issues i WHERE i.venue_id = v.id AND rating IS NOT NULL) AS avg_rating
                FROM venues v ORDER BY v.name"""))
            for v in data:
                v["verified"] = is_verified(v["last_verified"])
                v["true_hourly_cost"] = round(v["hourly_rate"] + (v["expected_min_spend"] or 0) / 3, 2)
            return data
        if table == "desks":
            return rows(self.conn.execute("""
                SELECT d.*, v.name AS venue_name FROM desks d
                JOIN venues v ON v.id = d.venue_id ORDER BY v.name, d.code"""))
        if table == "customers":
            return rows(self.conn.execute("""
                SELECT c.*, COUNT(b.id) AS booking_count,
                  COALESCE(SUM(CASE WHEN b.status IN ('confirmed','checked_in','completed') THEN b.amount END), 0) AS lifetime_value
                FROM customers c LEFT JOIN bookings b ON b.customer_id = c.id
                GROUP BY c.id ORDER BY c.name"""))
        if table == "bookings":
            return rows(self.conn.execute("""
                SELECT b.*, c.name AS customer_name, d.code AS desk_code, v.name AS venue_name, v.id AS venue_id
                FROM bookings b JOIN customers c ON c.id = b.customer_id
                JOIN desks d ON d.id = b.desk_id JOIN venues v ON v.id = d.venue_id
                ORDER BY b.date DESC, b.start_time DESC"""))
        if table == "issues":
            return rows(self.conn.execute("""
                SELECT i.*, v.name AS venue_name, c.name AS customer_name FROM issues i
                JOIN venues v ON v.id = i.venue_id LEFT JOIN customers c ON c.id = i.customer_id
                ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'responded' THEN 1 ELSE 2 END, i.created_at DESC"""))
        if table == "verifications":
            return rows(self.conn.execute("""
                SELECT x.*, v.name AS venue_name FROM verifications x
                JOIN venues v ON v.id = x.venue_id ORDER BY x.checked_at DESC"""))
        raise ApiError("ไม่พบ resource", 404)

    def get(self, table, rid):
        return self._get(table, rid)

    # ---------- create / update ----------
    def create(self, table, data):
        clean = self._clean(table, data)
        if table == "bookings":
            return self._create_booking(clean)
        if table == "customers":
            clean["created_at"] = now_iso()
        if table == "issues":
            clean["created_at"] = now_iso()
            if clean.get("rating") is not None and not 1 <= clean["rating"] <= 5:
                raise ApiError("rating ต้องอยู่ระหว่าง 1–5")
            if clean.get("response"):
                clean["responded_at"] = now_iso()
                clean.setdefault("status", "responded")
            # a "desk not ready" complaint flags the related booking
            if clean.get("booking_id") and clean.get("category") == "desk_not_ready":
                self.conn.execute("UPDATE bookings SET status='desk_not_ready' WHERE id=?",
                                  (clean["booking_id"],))
        if table == "verifications":
            return self._create_verification(clean)
        if table == "desks":
            self._get("venues", clean["venue_id"])
        return self._insert(table, clean)

    def update(self, table, rid, data):
        clean = self._clean(table, data, partial=True)
        if table == "bookings":
            current = self._get("bookings", rid)
            merged = {**current, **clean}
            if any(k in clean for k in ("desk_id", "date", "start_time", "hours")):
                self._check_booking(merged, exclude_id=rid)
                price = self._price(merged, exclude_id=rid)
                clean.update(price)
        if table == "issues":
            current = self._get("issues", rid)
            if clean.get("response") and clean["response"] != current["response"]:
                clean["responded_at"] = now_iso()
                if "status" not in clean or clean["status"] == "open":
                    clean["status"] = "responded"
        return self._update(table, rid, clean)

    def delete(self, table, rid):
        self._get(table, rid)
        try:
            self.conn.execute(f"DELETE FROM {table} WHERE id = ?", (rid,))
            self.conn.commit()
        except sqlite3.IntegrityError:
            self.conn.rollback()
            raise ApiError("ลบไม่ได้: มีข้อมูลอื่นอ้างอิงรายการนี้อยู่ (ให้ปิดการใช้งานแทน)", 409)
        return {"deleted": rid}

    # ---------- bookings ----------
    def _check_booking(self, b, exclude_id=None):
        try:
            date.fromisoformat(b["date"])
        except (TypeError, ValueError):
            raise ApiError("date ต้องอยู่ในรูปแบบ YYYY-MM-DD")
        if not b["hours"] or b["hours"] <= 0 or b["hours"] > 16:
            raise ApiError("hours ต้องมากกว่า 0 และไม่เกิน 16")
        start = to_minutes(b["start_time"])
        end = start + b["hours"] * 60
        if end > 24 * 60:
            raise ApiError("การจองต้องจบภายในวันเดียวกัน")
        desk = self._get("desks", b["desk_id"])
        if desk["status"] != "active":
            raise ApiError("โต๊ะนี้ไม่พร้อมให้บริการ")
        venue = self._get("venues", desk["venue_id"])
        if not venue["active"]:
            raise ApiError("สถานที่นี้ปิดการใช้งานอยู่")
        self._get("customers", b["customer_id"])
        others = self.conn.execute(
            "SELECT id, start_time, hours FROM bookings WHERE desk_id=? AND date=? "
            "AND status NOT IN ('cancelled','desk_not_ready') AND id != ?",
            (b["desk_id"], b["date"], exclude_id or -1)).fetchall()
        for o in others:
            os_ = to_minutes(o["start_time"])
            oe = os_ + o["hours"] * 60
            if start < oe and os_ < end:
                raise ApiError(f"โต๊ะนี้ถูกจองแล้วในช่วงเวลาดังกล่าว (booking #{o['id']})", 409)
        return venue

    def _price(self, b, exclude_id=None):
        desk = self._get("desks", b["desk_id"])
        venue = self._get("venues", desk["venue_id"])
        rate = venue["hourly_rate"]
        prior = self.conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE customer_id=? AND status != 'cancelled' AND id != ?",
            (b["customer_id"], exclude_id or -1)).fetchone()[0]
        discount = round(min(b["hours"], FIRST_BOOKING_FREE_HOURS) * rate, 2) if prior == 0 else 0
        amount = round(b["hours"] * rate - discount, 2)
        return {"rate": rate, "discount": discount, "amount": amount}

    def _create_booking(self, b):
        b.setdefault("status", "confirmed")
        b.setdefault("payment_method", "card")
        self._check_booking(b)
        b.update(self._price(b))
        if b["amount"] == 0:
            b["payment_method"] = "promo"
        b["created_at"] = now_iso()
        return self._insert("bookings", b)

    def availability(self, venue_id, day, start_time, hours):
        start = to_minutes(start_time)
        end = start + float(hours) * 60
        result = []
        for d in rows(self.conn.execute("SELECT * FROM desks WHERE venue_id=? AND status='active'", (venue_id,))):
            busy = False
            for o in self.conn.execute(
                    "SELECT start_time, hours FROM bookings WHERE desk_id=? AND date=? "
                    "AND status NOT IN ('cancelled','desk_not_ready')", (d["id"], day)):
                os_ = to_minutes(o["start_time"])
                if start < os_ + o["hours"] * 60 and os_ < end:
                    busy = True
                    break
            d["available"] = not busy
            result.append(d)
        return result

    # ---------- verification ----------
    def _create_verification(self, v):
        venue = self._get("venues", v["venue_id"])
        v.setdefault("checked_at", date.today().isoformat())
        rec = self._insert("verifications", v)
        upd = {"last_verified": v["checked_at"]}
        if v.get("wifi_mbps") is not None:
            upd["wifi_mbps"] = v["wifi_mbps"]
        if v.get("noise_level"):
            upd["noise_level"] = v["noise_level"]
        if v.get("staff_briefed"):
            upd["staff_trained"] = 1
        self._update("venues", venue["id"], upd)
        return rec

    # ---------- reports ----------
    def dashboard(self, today=None):
        today = today or date.today().isoformat()
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        paid = "status IN ('confirmed','checked_in','completed')"
        venues = self.list("venues")
        revenue_by_venue = rows(self.conn.execute(f"""
            SELECT v.id, v.name, v.commission_pct,
              COALESCE(SUM(b.amount), 0) AS gross, COUNT(b.id) AS bookings,
              COALESCE(SUM(b.hours), 0) AS hours
            FROM venues v LEFT JOIN desks d ON d.venue_id = v.id
            LEFT JOIN bookings b ON b.desk_id = d.id AND b.{paid}
            GROUP BY v.id ORDER BY gross DESC"""))
        for r in revenue_by_venue:
            r["commission"] = round(r["gross"] * (r["commission_pct"] or 0) / 100, 2)
            r["payout"] = round(r["gross"] - r["commission"], 2)
        total_bookings = q("SELECT COUNT(*) FROM bookings")
        not_ready = q("SELECT COUNT(*) FROM bookings WHERE status='desk_not_ready'")
        issues = q("SELECT COUNT(*) FROM issues")
        responded = q("SELECT COUNT(*) FROM issues WHERE status != 'open'")
        repeat = q("SELECT COUNT(*) FROM (SELECT customer_id FROM bookings WHERE status != 'cancelled' "
                   "GROUP BY customer_id HAVING COUNT(*) > 1)")
        customers = q("SELECT COUNT(*) FROM customers")
        return {
            "kpis": {
                "gross_revenue": round(q(f"SELECT COALESCE(SUM(amount),0) FROM bookings WHERE {paid}"), 2),
                "commission_revenue": round(sum(r["commission"] for r in revenue_by_venue), 2),
                "promo_discount": round(q("SELECT COALESCE(SUM(discount),0) FROM bookings WHERE status!='cancelled'"), 2),
                "bookings_today": q("SELECT COUNT(*) FROM bookings WHERE date=? AND status!='cancelled'", today),
                "total_bookings": total_bookings,
                "customers": customers,
                "repeat_customer_rate": round(repeat / customers * 100, 1) if customers else 0,
                "active_venues": sum(1 for v in venues if v["active"]),
                "verified_venues": sum(1 for v in venues if v["active"] and v["verified"]),
                "open_issues": q("SELECT COUNT(*) FROM issues WHERE status='open'"),
                "response_rate": round(responded / issues * 100, 1) if issues else 100.0,
                "avg_rating": q("SELECT ROUND(AVG(rating),2) FROM issues WHERE rating IS NOT NULL"),
                "desk_not_ready_rate": round(not_ready / total_bookings * 100, 1) if total_bookings else 0,
            },
            "revenue_by_venue": revenue_by_venue,
            "issues_by_category": rows(self.conn.execute(
                "SELECT category, COUNT(*) AS count FROM issues GROUP BY category ORDER BY count DESC")),
            "customers_by_channel": rows(self.conn.execute(
                "SELECT channel, COUNT(*) AS count FROM customers GROUP BY channel ORDER BY count DESC")),
            "verification_due": [
                {"id": v["id"], "name": v["name"], "last_verified": v["last_verified"]}
                for v in venues if v["active"] and not v["verified"]],
        }


def seed(conn):
    teak.seed(conn)
    mala.seed(conn)
    erp = ERP(conn)
    if conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0]:
        return
    t = date.today()
    d = lambda n: (t - timedelta(days=n)).isoformat()
    venues = [
        dict(name="Bean There Café", type="cafe", area="Thong Lo", bts_station="Thong Lo", bts_walk_min=4,
             hourly_rate=60, expected_min_spend=90, wifi_mbps=45, noise_level="moderate", commission_pct=20,
             staff_trained=1, last_verified=d(10), contact_line="@beanthere"),
        dict(name="Slow Drip Thong Lo", type="cafe", area="Thong Lo", bts_station="Thong Lo", bts_walk_min=9,
             hourly_rate=50, expected_min_spend=120, wifi_mbps=8, noise_level="loud", commission_pct=20,
             staff_trained=0, last_verified=d(380), contact_line="@slowdrip"),
        dict(name="Ari Hub Co-working", type="coworking", area="Ari", bts_station="Ari", bts_walk_min=3,
             hourly_rate=90, expected_min_spend=0, wifi_mbps=300, noise_level="quiet", commission_pct=15,
             staff_trained=1, last_verified=d(5), contact_line="@arihub"),
        dict(name="On Nut Workshop", type="coworking", area="On Nut", bts_station="On Nut", bts_walk_min=6,
             hourly_rate=70, expected_min_spend=0, wifi_mbps=150, noise_level="quiet", commission_pct=15,
             staff_trained=1, last_verified=d(45), contact_line="@onnutws"),
    ]
    for v in venues:
        erp.create("venues", v)
    desks = [(1, "A1", "normal", 1), (1, "A2", "quiet", 1), (1, "A3", "normal", 0),
             (2, "B1", "normal", 1), (2, "B2", "normal", 0),
             (3, "H1", "quiet", 1), (3, "H2", "quiet", 1), (3, "CB1", "call_booth", 1),
             (4, "W1", "quiet", 1), (4, "W2", "normal", 1)]
    for vid, code, zone, sock in desks:
        erp.create("desks", dict(venue_id=vid, code=code, zone=zone, has_socket=sock))
    customers = [
        dict(name="Ploy S.", occupation="Freelance graphic designer", phone="081-111-2222",
             line_id="ploy.design", channel="instagram"),
        dict(name="Nat K.", occupation="Freelance developer", phone="089-333-4444", channel="referral"),
        dict(name="Mint P.", occupation="Content writer", line_id="mintwrites", channel="referral"),
        dict(name="Tom R.", occupation="Remote marketer", email="tom@example.com", channel="google"),
    ]
    for c in customers:
        erp.create("customers", c)
    bookings = [
        (1, 1, d(14), "13:00", 4), (1, 4, d(13), "10:00", 5), (1, 6, d(2), "09:00", 6),
        (2, 6, d(2), "15:30", 3), (3, 9, d(1), "10:00", 4), (1, 2, d(0), "10:00", 5),
        (4, 7, d(0), "09:00", 8), (2, 1, d(0), "16:00", 2),
    ]
    for cid, did, day, st, h in bookings:
        erp.create("bookings", dict(customer_id=cid, desk_id=did, date=day, start_time=st, hours=h))
    for bid in (1, 2, 3, 4, 5):
        erp.update("bookings", bid, {"status": "completed"})
    erp.create("issues", dict(venue_id=2, customer_id=1, booking_id=2, rating=1, category="outdated_photos",
                              description="Listing said quiet zone & fast wi-fi; there was a party and wi-fi was too slow."))
    erp.create("issues", dict(venue_id=1, customer_id=2, rating=3, category="staff_unaware",
                              description="Staff did not know about DeskHop booking."))
    erp.create("issues", dict(venue_id=3, customer_id=3, rating=5, category="other",
                              description="Great place, fast wi-fi.", response="Thank you! See you again.",
                              status="resolved"))
    erp.create("verifications", dict(venue_id=3, checked_at=d(5), wifi_mbps=300, noise_level="quiet",
                                     photos_updated=1, staff_briefed=1, inspector="Ops team"))


# ---------------- HTTP layer ----------------
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


def make_handler(erp):
    teak_erp = teak.TeakERP(erp.conn)
    mala_erp = mala.MalaERP(erp.conn)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quieter logs
            pass

        def _send(self, status, payload, ctype="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                data = json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                raise ApiError("JSON ไม่ถูกต้อง")
            if not isinstance(data, dict):
                raise ApiError("ต้องส่งเป็น JSON object")
            return data

        def _route(self, method):
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            if not parts or parts[0] != "api":
                if method != "GET":
                    raise ApiError("Not found", 404)
                return self._static(url.path)
            parts = parts[1:]
            if parts and parts[0] in ("teak", "mala"):
                mod = teak_erp if parts[0] == "teak" else mala_erp
                status, payload = mod.route(method, parts[1:], self._body)
                return self._send(status, payload)
            if parts == ["dashboard"] and method == "GET":
                return self._send(200, erp.dashboard())
            if parts == ["meta"] and method == "GET":
                return self._send(200, {"enums": ENUMS, "verify_valid_days": VERIFY_VALID_DAYS,
                                        "first_booking_free_hours": FIRST_BOOKING_FREE_HOURS})
            if len(parts) == 3 and parts[0] == "venues" and parts[2] == "availability" and method == "GET":
                from urllib.parse import parse_qs
                qs = {k: v[0] for k, v in parse_qs(url.query).items()}
                if not all(k in qs for k in ("date", "start_time", "hours")):
                    raise ApiError("ต้องระบุ date, start_time, hours")
                return self._send(200, erp.availability(int(parts[1]), qs["date"], qs["start_time"], qs["hours"]))
            if not parts or parts[0] not in TABLES:
                raise ApiError("ไม่พบ resource", 404)
            table = parts[0]
            rid = None
            if len(parts) == 2:
                if not parts[1].isdigit():
                    raise ApiError("id ไม่ถูกต้อง")
                rid = int(parts[1])
            elif len(parts) > 2:
                raise ApiError("ไม่พบ resource", 404)
            if method == "GET":
                return self._send(200, erp.get(table, rid) if rid else erp.list(table))
            if method == "POST" and rid is None:
                return self._send(201, erp.create(table, self._body()))
            if method in ("PUT", "PATCH") and rid:
                return self._send(200, erp.update(table, rid, self._body()))
            if method == "DELETE" and rid:
                return self._send(200, erp.delete(table, rid))
            raise ApiError("Method not allowed", 405)

        def _static(self, path):
            path = "/index.html" if path in ("", "/") else path
            full = os.path.realpath(os.path.join(STATIC_DIR, path.lstrip("/")))
            if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
                raise ApiError("Not found", 404)
            with open(full, "rb") as f:
                self._send(200, f.read(), MIME.get(os.path.splitext(full)[1], "application/octet-stream"))

        def _handle(self, method):
            try:
                self._route(method)
            except ApiError as e:
                self._send(e.status, {"error": str(e)})
            except sqlite3.IntegrityError as e:
                self._send(409, {"error": f"ข้อมูลขัดแย้งกับฐานข้อมูล: {e}"})
            except Exception as e:  # pragma: no cover
                self._send(500, {"error": f"Server error: {e}"})

        def do_GET(self): self._handle("GET")
        def do_POST(self): self._handle("POST")
        def do_PUT(self): self._handle("PUT")
        def do_PATCH(self): self._handle("PATCH")
        def do_DELETE(self): self._handle("DELETE")

    return Handler


def main():
    ap = argparse.ArgumentParser(description="DeskHop ERP server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    # On hosts like Render, PORT is set and we must listen on all interfaces.
    ap.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"))
    ap.add_argument("--db", default=os.environ.get("DB_PATH", os.path.join(BASE_DIR, "deskhop.db")))
    ap.add_argument("--seed", action="store_true", help="load demo data if the database is empty")
    # Tolerate "—seed" / "–seed" when "--" was auto-converted to a dash character.
    argv = [re.sub(r"^[\u2012\u2013\u2014\u2015]+", "--", a) for a in sys.argv[1:]]
    args = ap.parse_args(argv)
    conn = connect(args.db)
    if args.seed or os.environ.get("SEED", "").lower() in ("1", "true", "yes"):
        seed(conn)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(ERP(conn)))
    print(f"DeskHop ERP running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
