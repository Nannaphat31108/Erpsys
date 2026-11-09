import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402


class ERPLogicTest(unittest.TestCase):
    def setUp(self):
        self.conn = app.connect(":memory:")
        self.erp = app.ERP(self.conn)
        self.v = self.erp.create("venues", {"name": "Test Café", "hourly_rate": 60, "commission_pct": 20})
        self.d = self.erp.create("desks", {"venue_id": self.v["id"], "code": "A1"})
        self.c = self.erp.create("customers", {"name": "Ploy"})
        self.day = date.today().isoformat()

    def book(self, start="10:00", hours=3, **kw):
        return self.erp.create("bookings", {"customer_id": self.c["id"], "desk_id": self.d["id"],
                                            "date": self.day, "start_time": start, "hours": hours, **kw})

    def test_first_booking_gets_two_free_hours(self):
        b = self.book(hours=3)
        self.assertEqual(b["discount"], 120)
        self.assertEqual(b["amount"], 60)
        b2 = self.book(start="14:00", hours=2)
        self.assertEqual(b2["discount"], 0)
        self.assertEqual(b2["amount"], 120)

    def test_fully_free_booking_marked_promo(self):
        self.assertEqual(self.book(hours=1)["payment_method"], "promo")

    def test_overlapping_booking_rejected(self):
        self.book("10:00", 3)
        with self.assertRaises(app.ApiError) as ctx:
            self.book("12:00", 2)
        self.assertEqual(ctx.exception.status, 409)
        self.book("13:00", 2)  # back-to-back is fine

    def test_cancelled_booking_frees_desk(self):
        b = self.book("10:00", 3)
        self.erp.update("bookings", b["id"], {"status": "cancelled"})
        self.book("11:00", 1)

    def test_invalid_input(self):
        for bad in ({"start_time": "25:00"}, {"hours": 0}, {"start_time": "22:00", "hours": 4}):
            with self.assertRaises(app.ApiError):
                self.book(**{"start": bad.get("start_time", "10:00"), "hours": bad.get("hours", 1)})
        with self.assertRaises(app.ApiError):
            self.erp.create("venues", {"name": "x", "hourly_rate": 1, "type": "hotel"})

    def test_verification_updates_venue_and_badge(self):
        self.assertFalse(self.erp.list("venues")[0]["verified"])
        self.erp.create("verifications", {"venue_id": self.v["id"], "wifi_mbps": 120, "noise_level": "quiet",
                                          "staff_briefed": 1})
        v = self.erp.list("venues")[0]
        self.assertTrue(v["verified"])
        self.assertEqual(v["wifi_mbps"], 120)
        self.assertEqual(v["staff_trained"], 1)
        old = (date.today() - timedelta(days=31)).isoformat()
        self.assertFalse(app.is_verified(old))

    def test_issue_response_and_desk_not_ready(self):
        b = self.book()
        i = self.erp.create("issues", {"venue_id": self.v["id"], "booking_id": b["id"], "rating": 2,
                                       "category": "desk_not_ready"})
        self.assertEqual(self.erp.get("bookings", b["id"])["status"], "desk_not_ready")
        i = self.erp.update("issues", i["id"], {"response": "Sorry, refund issued."})
        self.assertEqual(i["status"], "responded")
        self.assertIsNotNone(i["responded_at"])

    def test_dashboard_commission(self):
        self.book(hours=2)                 # free
        self.book(start="13:00", hours=5)  # 300
        k = self.erp.dashboard()["kpis"]
        self.assertEqual(k["gross_revenue"], 300)
        self.assertEqual(k["commission_revenue"], 60)
        self.assertEqual(k["promo_discount"], 120)

    def test_availability(self):
        self.book("10:00", 2)
        self.assertFalse(self.erp.availability(self.v["id"], self.day, "11:00", 1)[0]["available"])
        self.assertTrue(self.erp.availability(self.v["id"], self.day, "12:00", 1)[0]["available"])

    def test_delete_referenced_row_blocked(self):
        self.book()
        with self.assertRaises(app.ApiError) as ctx:
            self.erp.delete("customers", self.c["id"])
        self.assertEqual(ctx.exception.status, 409)


class HTTPTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        conn = app.connect(":memory:")
        app.seed(conn)
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.make_handler(app.ERP(conn)))
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_endpoints(self):
        st, body = self.call("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b"DeskHop ERP", body)
        st, body = self.call("GET", "/api/dashboard")
        self.assertEqual(st, 200)
        self.assertIn("kpis", json.loads(body))
        st, body = self.call("POST", "/api/customers", {"name": "New", "channel": "tiktok"})
        self.assertEqual(st, 201)
        st, _ = self.call("POST", "/api/customers", {})
        self.assertEqual(st, 400)
        st, _ = self.call("GET", "/api/nope")
        self.assertEqual(st, 404)
        st, _ = self.call("GET", "/../app.py")
        self.assertEqual(st, 404)


if __name__ == "__main__":
    unittest.main()
