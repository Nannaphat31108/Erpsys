"""Helpers shared by the DeskHop and Teak furniture ERP modules."""
from datetime import datetime


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def clean_fields(data, fields, required, enums, numeric, integers, partial=False):
    """Validate/convert an input dict against a simple field spec."""
    out = {}
    for f in fields:
        if f not in data:
            continue
        v = data[f]
        if v == "":
            v = None
        if v is not None and f in numeric:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ApiError(f"{f} ต้องเป็นตัวเลข")
            if f in integers:
                if not v.is_integer():
                    raise ApiError(f"{f} ต้องเป็นจำนวนเต็ม")
                v = int(v)
        allowed = enums.get(f)
        if allowed and v is not None and v not in allowed:
            raise ApiError(f"{f} ต้องเป็นหนึ่งใน {', '.join(allowed)}")
        out[f] = v
    if not partial:
        missing = [f for f in required if out.get(f) in (None, "")]
        if missing:
            raise ApiError("ข้อมูลที่จำเป็นยังไม่ครบ: " + ", ".join(missing))
    return out
