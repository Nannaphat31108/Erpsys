import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
import teak  # noqa: E402
from common import ApiError  # noqa: E402


class TeakTest(unittest.TestCase):
    def setUp(self):
        self.conn = app.connect(":memory:")
        self.e = teak.TeakERP(self.conn)
        self.sup = self.c("suppliers", {"name": "แพร่ค้าไม้"})
        self.mat = self.c("materials", {"name": "ไม้สัก A", "unit": "cu_ft"})
        self.prod = self.c("products", {"sku": "T1", "name": "โต๊ะ", "unit_price": 10000, "unit_cost": 4000, "stock_qty": 2})
        self.cust = self.c("customers", {"name": "ลูกค้า"})

    def c(self, res, data):
        return self.e._tx(lambda: self.e.create(res, data))

    def u(self, res, rid, data):
        return self.e._tx(lambda: self.e.update(res, rid, data))

    def order(self, qty=1, **kw):
        return self.c("orders", {"customer_id": self.cust["id"], "items": [{"product_id": self.prod["id"], "qty": qty}], **kw})

    def stock(self):
        return self.e._get("products", self.prod["id"])["stock_qty"]

    def test_order_totals_and_payments(self):
        o = self.order(2, discount=1000, delivery_fee=500)
        self.assertEqual(o["total"], 19500)
        self.c("payments", {"order_id": o["id"], "amount": 5000})
        self.assertEqual(self.e.detail("orders", o["id"])["balance"], 14500)

    def test_delivery_deducts_stock_and_locks(self):
        o = self.order(2)
        self.u("orders", o["id"], {"status": "delivered"})
        self.assertEqual(self.stock(), 0)
        with self.assertRaises(ApiError):
            self.u("orders", o["id"], {"status": "cancelled"})
        with self.assertRaises(ApiError):
            self.e._tx(lambda: self.e.delete("orders", o["id"]))

    def test_delivery_blocked_when_out_of_stock_and_rolled_back(self):
        o = self.order(5)
        with self.assertRaises(ApiError) as ctx:
            self.u("orders", o["id"], {"status": "delivered", "note": "x"})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.stock(), 2)
        self.assertNotEqual(self.e._get("orders", o["id"])["status"], "delivered")
        self.assertIsNone(self.e._get("orders", o["id"])["note"])  # whole update rolled back

    def test_purchase_weighted_average_and_delete(self):
        self.c("purchases", {"supplier_id": self.sup["id"], "material_id": self.mat["id"], "qty": 10, "unit_cost": 1000})
        p = self.c("purchases", {"supplier_id": self.sup["id"], "material_id": self.mat["id"], "qty": 10, "unit_cost": 2000})
        m = self.e._get("materials", self.mat["id"])
        self.assertEqual((m["qty"], m["unit_cost"]), (20, 1500))
        self.e._tx(lambda: self.e.delete("purchases", p["id"]))
        m = self.e._get("materials", self.mat["id"])
        self.assertEqual((m["qty"], m["unit_cost"]), (10, 1000))

    def test_production_flow(self):
        self.c("purchases", {"supplier_id": self.sup["id"], "material_id": self.mat["id"], "qty": 30, "unit_cost": 1000})
        o = self.order(3)
        w = self.c("production", {"product_id": self.prod["id"], "order_id": o["id"], "qty": 2, "labor_cost": 2000,
                                  "materials": [{"material_id": self.mat["id"], "qty": 10}]})
        self.assertEqual(self.e._get("materials", self.mat["id"])["qty"], 20)
        self.assertEqual(self.e._get("orders", o["id"])["status"], "in_production")
        self.u("production", w["id"], {"status": "done"})
        p = self.e._get("products", self.prod["id"])
        self.assertEqual(p["stock_qty"], 4)
        self.assertEqual(p["unit_cost"], 5000)  # (2*4000 + 2*6000) / 4
        self.assertEqual(self.e._get("orders", o["id"])["status"], "ready")

    def test_production_cancel_returns_materials_and_shortage_blocked(self):
        self.c("purchases", {"supplier_id": self.sup["id"], "material_id": self.mat["id"], "qty": 5, "unit_cost": 1000})
        with self.assertRaises(ApiError):
            self.c("production", {"product_id": self.prod["id"], "qty": 1, "materials": [{"material_id": self.mat["id"], "qty": 6}]})
        self.assertEqual(self.e._get("materials", self.mat["id"])["qty"], 5)
        w = self.c("production", {"product_id": self.prod["id"], "qty": 1, "materials": [{"material_id": self.mat["id"], "qty": 4}]})
        self.u("production", w["id"], {"status": "cancelled"})
        self.assertEqual(self.e._get("materials", self.mat["id"])["qty"], 5)

    def test_validation(self):
        with self.assertRaises(ApiError):
            self.c("orders", {"customer_id": self.cust["id"], "items": []})
        with self.assertRaises(ApiError):
            self.c("products", {"sku": "T1", "name": "dup", "unit_price": 1})
        with self.assertRaises(ApiError):
            self.order(1, due_date="31/12/2026")

    def test_seed_and_dashboard(self):
        conn = app.connect(":memory:")
        app.seed(conn)
        k = teak.TeakERP(conn).dashboard()["kpis"]
        self.assertGreater(k["sales_delivered"], 0)
        self.assertEqual(k["overdue_orders"], 1)


if __name__ == "__main__":
    unittest.main()
