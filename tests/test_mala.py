import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import mala  # noqa: E402
from common import ApiError  # noqa: E402


class MalaTest(unittest.TestCase):
    def setUp(self):
        self.e = mala.MalaERP(app.connect(":memory:"))
        self.item = self.c("items", {"name": "หมูสามชั้น", "sell_price": 15, "unit_cost": 6, "reorder_level": 10, "par_level": 50})
        self.staff = self.c("staff", {"name": "ต้น", "status": "hired"})

    def c(self, res, data):
        return self.e._tx(lambda: self.e.create(res, data))

    def qty(self):
        return self.e._get("items", self.item["id"])["qty"]

    def receive(self, qty, cost=6):
        return self.c("receipts", {"item_id": self.item["id"], "qty": qty, "unit_cost": cost})

    def test_receive_sell_remaining(self):
        self.receive(40)
        sale = self.c("sales", {"items": [{"item_id": self.item["id"], "qty": 5}], "discount": 5, "staff_id": self.staff["id"]})
        self.assertEqual(sale["total"], 70)
        self.assertEqual(sale["profit"], 40)
        self.assertEqual(self.qty(), 35)

    def test_cannot_oversell_and_void_returns_stock(self):
        self.receive(3)
        with self.assertRaises(ApiError):
            self.c("sales", {"items": [{"item_id": self.item["id"], "qty": 2}, {"item_id": self.item["id"], "qty": 2}]})
        self.assertEqual(self.qty(), 3)
        s = self.c("sales", {"items": [{"item_id": self.item["id"], "qty": 3}]})
        self.assertEqual(self.qty(), 0)
        self.e._tx(lambda: self.e.delete("sales", s["id"]))
        self.assertEqual(self.qty(), 3)

    def test_reorder_suggestion(self):
        self.receive(30)
        self.assertEqual(self.e.reorder(), [])
        self.c("sales", {"items": [{"item_id": self.item["id"], "qty": 22}]})
        r = self.e.reorder()
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["stock_status"], r[0]["suggest_qty"]), ("low", 42))

    def test_weighted_cost_and_cancel_receipt(self):
        self.receive(10, 6)
        r = self.receive(10, 8)
        self.assertEqual(self.e._get("items", self.item["id"])["unit_cost"], 7)
        self.e._tx(lambda: self.e.delete("receipts", r["id"]))
        self.assertEqual((self.qty(), self.e._get("items", self.item["id"])["unit_cost"]), (10, 6))
        self.c("sales", {"items": [{"item_id": self.item["id"], "qty": 10}]})
        first = self.e.list("receipts")[0]
        with self.assertRaises(ApiError):
            self.e._tx(lambda: self.e.delete("receipts", first["id"]))

    def test_waste(self):
        self.receive(10)
        w = self.c("waste", {"item_id": self.item["id"], "qty": 4, "reason": "spoiled"})
        self.assertEqual(self.qty(), 6)
        with self.assertRaises(ApiError):
            self.c("waste", {"item_id": self.item["id"], "qty": 7})
        self.e._tx(lambda: self.e.delete("waste", w["id"]))
        self.assertEqual(self.qty(), 10)

    def test_hiring_flow(self):
        a = self.c("staff", {"name": "มิว", "position": "server"})
        self.assertEqual(a["status"], "applicant")
        a = self.e._tx(lambda: self.e.update("staff", a["id"], {"status": "interview", "interview_date": "2026-12-01"}))
        a = self.e._tx(lambda: self.e.update("staff", a["id"], {"status": "hired"}))
        self.assertEqual(a["status"], "hired")
        self.assertIsNotNone(a["start_date"])
        with self.assertRaises(ApiError):
            self.c("staff", {"name": "x", "status": "boss"})

    def test_seed_dashboard(self):
        conn = app.connect(":memory:")
        app.seed(conn)
        k = mala.MalaERP(conn).dashboard()["kpis"]
        self.assertGreater(k["sales_today"], 0)
        self.assertGreater(k["reorder_count"], 0)
        self.assertEqual(k["applicants"], 2)


if __name__ == "__main__":
    unittest.main()
