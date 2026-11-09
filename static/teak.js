// Teak furniture shop ERP front-end — vanilla JS.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const baht = (n) => "฿" + Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
const num = (n) => Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);

const LABELS = {
  table: "โต๊ะ", chair: "เก้าอี้", sofa: "โซฟา", bed: "เตียง", cabinet: "ตู้", shelf: "ชั้นวาง", door: "ประตู/หน้าต่าง", outdoor: "เฟอร์นิเจอร์สนาม", decor: "ของตกแต่ง",
  A: "เกรด A", B: "เกรด B", C: "เกรด C", reclaimed: "ไม้เก่า", "-": "—",
  natural: "สีธรรมชาติ", oiled: "ทาน้ำมัน", lacquer: "แลกเกอร์", stained: "ย้อมสี", painted: "ทำสี",
  cu_ft: "ลบ.ฟุต", board: "แผ่น", piece: "ชิ้น", litre: "ลิตร", kg: "กก.", set: "ชุด",
  retail: "ลูกค้าทั่วไป", wholesale: "ขายส่ง", hotel: "โรงแรม/รีสอร์ท", designer: "อินทีเรีย/ดีไซเนอร์", online: "ร้านออนไลน์",
  quote: "ใบเสนอราคา", confirmed: "ยืนยันแล้ว", in_production: "กำลังผลิต", ready: "พร้อมส่ง", delivered: "ส่งมอบแล้ว", cancelled: "ยกเลิก",
  cash: "เงินสด", transfer: "โอนเงิน", promptpay: "PromptPay", card: "บัตร", cheque: "เช็ค",
  deposit: "มัดจำ", balance: "ชำระส่วนที่เหลือ", full: "ชำระเต็ม", refund: "คืนเงิน",
  planned: "วางแผน", cutting: "ตัดไม้", assembling: "ประกอบ", finishing: "ขัด/ทำสี", done: "ผลิตเสร็จ",
};
const L = (v) => LABELS[v] ?? v ?? "";
const CLS = { quote: "", confirmed: "", in_production: "warn", ready: "ok", delivered: "ok", cancelled: "bad",
  planned: "", cutting: "warn", assembling: "warn", finishing: "warn", done: "ok", deposit: "", balance: "ok", full: "ok", refund: "bad" };
const badge = (v) => `<span class="badge ${CLS[v] || ""}">${esc(L(v))}</span>`;

let META = { enums: {} };
const cache = {};
async function api(path, opts = {}) {
  const res = await fetch("/api/teak/" + path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const load = async (t) => cache[t] || (cache[t] = await api(t));
const clearCache = () => Object.keys(cache).forEach((k) => delete cache[k]);
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2400); }

const ref = (table, label, optional) => ({ type: "ref", table, label, optional });
const productLabel = (p) => `${p.sku} · ${p.name} (คงเหลือ ${p.stock_qty})`;
const materialLabel = (m) => `${m.name} (คงเหลือ ${num(m.qty)} ${L(m.unit)})`;

const SCREENS = {
  dashboard: { title: "แดชบอร์ด" },
  orders: {
    title: "ออเดอร์ขาย", res: "orders", search: ["customer_name", "items_summary", "id"], filter: "orders.status",
    columns: [["เลขที่", (r) => "SO-" + String(r.id).padStart(4, "0")], ["วันที่", (r) => r.order_date],
      ["กำหนดส่ง", (r) => (r.due_date || "—") + (r.overdue ? ' <span class="badge bad">เลยกำหนด</span>' : "")],
      ["ลูกค้า", (r) => esc(r.customer_name)], ["สินค้า", (r) => `<span title="${esc(r.items_summary)}">${esc((r.items_summary || "").slice(0, 45))}</span>`],
      ["ยอดรวม", (r) => baht(r.total), "num"], ["ชำระแล้ว", (r) => baht(r.paid), "num"],
      ["ค้างชำระ", (r) => (r.balance > 0 ? `<b>${baht(r.balance)}</b>` : r.balance < 0 ? `<span class="badge bad">ต้องคืน ${baht(-r.balance)}</span>` : "✔"), "num"],
      ["สถานะ", (r) => badge(r.status)]],
    fields: [["customer_id", "ลูกค้า", ref("customers", (c) => c.name)], ["status", "สถานะ", "enum"],
      ["order_date", "วันที่สั่ง", "date"], ["due_date", "กำหนดส่ง", "date"],
      ["items", "รายการสินค้า", { type: "lines", table: "products", key: "product_id", label: productLabel, priceField: "unit_price", qtyLabel: "จำนวน", priceLabel: "ราคา/ชิ้น" }],
      ["discount", "ส่วนลด (บาท)", "number"], ["delivery_fee", "ค่าขนส่ง (บาท)", "number"], ["note", "หมายเหตุ", "textarea"]],
    actions: (r) => [
      ["รายละเอียด", () => showOrder(r.id)],
      ...(r.status !== "cancelled" && r.status !== "quote" && r.balance > 0 ? [["รับชำระ", () => receivePayment(r)]] : []),
      ...(r.status === "quote" ? [["ยืนยันออเดอร์", () => quick("orders", r.id, { status: "confirmed" })]] : []),
      ...(["confirmed", "ready", "in_production"].includes(r.status) ? [["ส่งมอบ", () => quick("orders", r.id, { status: "delivered" }, "ยืนยันการส่งมอบ? ระบบจะตัดสต็อกสินค้า")]] : []),
    ],
    editable: (r) => r.status !== "delivered",
  },
  production: {
    title: "ผลิต / โรงงาน", res: "production", search: ["product_name", "craftsman", "sku"], filter: "production.status",
    columns: [["เลขที่", (r) => "WO-" + String(r.id).padStart(4, "0")], ["สินค้า", (r) => `${esc(r.sku)} · ${esc(r.product_name)}`],
      ["จำนวน", (r) => r.qty, "num"], ["ออเดอร์", (r) => (r.order_id ? "SO-" + String(r.order_id).padStart(4, "0") : "ผลิตเข้าสต็อก")],
      ["ช่าง", (r) => esc(r.craftsman)], ["กำหนดเสร็จ", (r) => (r.due_date || "—") + (r.overdue ? ' <span class="badge bad">เลยกำหนด</span>' : "")],
      ["วัตถุดิบ", (r) => `<span title="${esc(r.materials_summary)}">${esc((r.materials_summary || "—").slice(0, 40))}</span>`],
      ["ต้นทุนรวม", (r) => baht(r.total_cost), "num"], ["สถานะ", (r) => badge(r.status)]],
    fields: [["product_id", "สินค้าที่ผลิต", ref("products", (p) => `${p.sku} · ${p.name}`)], ["qty", "จำนวน", "number"],
      ["order_id", "ผลิตให้ออเดอร์ (ถ้ามี)", ref("orders", (o) => `SO-${String(o.id).padStart(4, "0")} · ${o.customer_name}`, true)],
      ["status", "สถานะ", "enum"], ["craftsman", "ช่างผู้รับผิดชอบ", "text"], ["labor_cost", "ค่าแรง (บาท)", "number"],
      ["start_date", "วันเริ่ม", "date"], ["due_date", "กำหนดเสร็จ", "date"],
      ["materials", "วัตถุดิบที่เบิกใช้ (ตัดสต็อกทันที)", { type: "lines", table: "materials", key: "material_id", label: materialLabel, qtyLabel: "ปริมาณ", createOnly: true }],
      ["note", "หมายเหตุ", "textarea"]],
    actions: (r) => {
      const flow = ["planned", "cutting", "assembling", "finishing", "done"];
      const i = flow.indexOf(r.status);
      return i >= 0 && i < flow.length - 1 ? [[`→ ${L(flow[i + 1])}`, () => quick("production", r.id, { status: flow[i + 1] },
        flow[i + 1] === "done" ? "ยืนยันผลิตเสร็จ? ระบบจะเพิ่มสต็อกสินค้า" : null)],
        ["ยกเลิก", () => quick("production", r.id, { status: "cancelled" }, "ยกเลิกใบสั่งผลิต? วัตถุดิบจะถูกคืนเข้าสต็อก")]] : [];
    },
    editable: (r) => !["done", "cancelled"].includes(r.status),
  },
  products: {
    title: "สินค้า / สต็อก", res: "products", search: ["sku", "name", "dimensions"], filter: "products.category", filterKey: "category",
    columns: [["SKU", (r) => `<b>${esc(r.sku)}</b>`], ["ชื่อสินค้า", (r) => esc(r.name)], ["หมวด", (r) => L(r.category)],
      ["ไม้", (r) => L(r.wood_grade)], ["ผิว", (r) => L(r.finish)], ["ขนาด", (r) => esc(r.dimensions)],
      ["ราคาขาย", (r) => baht(r.unit_price), "num"], ["ต้นทุน", (r) => baht(r.unit_cost), "num"], ["กำไร", (r) => r.margin_pct + "%", "num"],
      ["คงเหลือ", (r) => (r.low_stock ? `<span class="badge bad">${r.stock_qty}</span>` : r.stock_qty), "num"]],
    rowClass: (r) => (r.low_stock ? "row-warn" : ""),
    fields: [["sku", "รหัสสินค้า (SKU)", "text"], ["name", "ชื่อสินค้า", "text"], ["category", "หมวด", "enum"], ["wood_grade", "เกรดไม้", "enum"],
      ["finish", "การทำผิว", "enum"], ["dimensions", "ขนาด (กว้าง×ลึก×สูง)", "text"], ["unit_price", "ราคาขาย (บาท)", "number"],
      ["unit_cost", "ต้นทุน/ชิ้น (บาท)", "number"], ["stock_qty", "จำนวนคงเหลือ", "number"], ["reorder_level", "จุดสั่งผลิตเพิ่ม", "number"],
      ["active", "เปิดขาย", "bool"]],
  },
  materials: {
    title: "วัตถุดิบ", res: "materials", search: ["name", "supplier_name"],
    columns: [["วัตถุดิบ", (r) => `<b>${esc(r.name)}</b>`], ["เกรด", (r) => L(r.grade)], ["คงเหลือ", (r) => (r.low_stock ? `<span class="badge bad">${num(r.qty)}</span>` : num(r.qty)), "num"],
      ["หน่วย", (r) => L(r.unit)], ["ต้นทุนเฉลี่ย/หน่วย", (r) => baht(r.unit_cost), "num"], ["มูลค่าคงคลัง", (r) => baht(r.value), "num"],
      ["จุดสั่งซื้อ", (r) => num(r.reorder_level), "num"], ["ผู้ขายหลัก", (r) => esc(r.supplier_name || "—")]],
    rowClass: (r) => (r.low_stock ? "row-warn" : ""),
    note: "จำนวนคงเหลือจะเพิ่มอัตโนมัติเมื่อบันทึก “รับซื้อวัตถุดิบ” และลดเมื่อเปิดใบสั่งผลิต · ต้นทุนคิดแบบถัวเฉลี่ย",
    fields: [["name", "ชื่อวัตถุดิบ", "text"], ["grade", "เกรด", "enum"], ["unit", "หน่วย", "enum"], ["qty", "คงเหลือ (ปรับยอด)", "number"],
      ["unit_cost", "ต้นทุน/หน่วย", "number"], ["reorder_level", "จุดสั่งซื้อ", "number"], ["supplier_id", "ผู้ขายหลัก", ref("suppliers", (s) => s.name, true)]],
  },
  purchases: {
    title: "รับซื้อวัตถุดิบ", res: "purchases", search: ["supplier_name", "material_name", "invoice_no"],
    columns: [["วันที่", (r) => r.purchase_date], ["เลขที่บิล", (r) => esc(r.invoice_no || "—")], ["ผู้ขาย", (r) => esc(r.supplier_name)],
      ["วัตถุดิบ", (r) => esc(r.material_name)], ["จำนวน", (r) => `${num(r.qty)} ${L(r.unit)}`, "num"], ["ราคา/หน่วย", (r) => baht(r.unit_cost), "num"], ["รวม", (r) => baht(r.total), "num"]],
    fields: [["supplier_id", "ผู้ขาย", ref("suppliers", (s) => s.name)], ["material_id", "วัตถุดิบ", ref("materials", materialLabel)],
      ["qty", "จำนวน", "number"], ["unit_cost", "ราคา/หน่วย (บาท)", "number"], ["purchase_date", "วันที่รับของ", "date"], ["invoice_no", "เลขที่บิล", "text"]],
    editable: () => false,
  },
  customers: {
    title: "ลูกค้า", res: "customers", search: ["name", "phone", "line_id", "address"], filter: "customers.type", filterKey: "type",
    columns: [["ชื่อ", (r) => `<b>${esc(r.name)}</b>`], ["ประเภท", (r) => L(r.type)], ["โทร", (r) => esc(r.phone)], ["LINE", (r) => esc(r.line_id)],
      ["ที่อยู่", (r) => esc(r.address)], ["ออเดอร์", (r) => r.order_count, "num"], ["ยอดซื้อรวม", (r) => baht(r.total_spent), "num"],
      ["ค้างชำระ", (r) => (r.balance_due > 0 ? `<b>${baht(r.balance_due)}</b>` : "—"), "num"]],
    fields: [["name", "ชื่อลูกค้า / บริษัท", "text"], ["type", "ประเภท", "enum"], ["phone", "โทรศัพท์", "text"], ["line_id", "LINE ID", "text"], ["address", "ที่อยู่จัดส่ง", "textarea"]],
  },
  suppliers: {
    title: "ผู้ขาย / ซัพพลายเออร์", res: "suppliers", search: ["name", "province", "supplies"],
    columns: [["ชื่อ", (r) => `<b>${esc(r.name)}</b>`], ["จังหวัด", (r) => esc(r.province)], ["โทร", (r) => esc(r.phone)], ["สินค้าที่ขาย", (r) => esc(r.supplies)],
      ["จำนวนบิล", (r) => r.purchase_count, "num"], ["ยอดซื้อรวม", (r) => baht(r.purchase_total), "num"]],
    fields: [["name", "ชื่อ", "text"], ["phone", "โทรศัพท์", "text"], ["province", "จังหวัด", "text"], ["supplies", "สินค้าที่ขาย", "text"], ["notes", "หมายเหตุ", "textarea"]],
  },
  payments: {
    title: "รับชำระเงิน", res: "payments", search: ["customer_name", "order_id"],
    columns: [["วันที่", (r) => r.paid_date], ["ออเดอร์", (r) => "SO-" + String(r.order_id).padStart(4, "0")], ["ลูกค้า", (r) => esc(r.customer_name)],
      ["ประเภท", (r) => badge(r.kind)], ["ช่องทาง", (r) => L(r.method)], ["จำนวนเงิน", (r) => (r.kind === "refund" ? "−" : "") + baht(r.amount), "num"]],
    fields: [["order_id", "ออเดอร์", ref("orders", (o) => `SO-${String(o.id).padStart(4, "0")} · ${o.customer_name} (ค้าง ${baht(o.balance)})`)],
      ["amount", "จำนวนเงิน", "number"], ["kind", "ประเภท", "enum"], ["method", "ช่องทาง", "enum"], ["paid_date", "วันที่รับเงิน", "date"]],
  },
};

let current = "dashboard";
let state = { q: "", f: "" };
function renderNav() {
  $("#nav").innerHTML = Object.entries(SCREENS).map(([k, s]) => `<a data-k="${k}" class="${k === current ? "active" : ""}">${s.title}</a>`).join("");
  $("#nav").querySelectorAll("a").forEach((a) => (a.onclick = () => go(a.dataset.k)));
}
async function go(k) {
  if (k !== current) state = { q: "", f: "" };
  current = k; if (location.hash.slice(1) !== k) location.hash = k; renderNav();
  const s = SCREENS[k];
  $("#page-title").textContent = s.title; $("#add-btn").hidden = !s.res;
  $("#content").innerHTML = '<p class="muted">กำลังโหลด…</p>';
  try { k === "dashboard" ? await renderDashboard() : await renderTable(s); }
  catch (e) { $("#content").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

const kpi = (l, v) => `<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`;
function bars(list, labelFn, valFn, fmt = num) {
  const max = Math.max(1, ...list.map(valFn));
  return `<table>${list.map((r) => `<tr><td>${esc(labelFn(r))}</td><td style="width:50%"><div class="bar" style="width:${(valFn(r) / max) * 100}%"></div></td><td class="num">${fmt(valFn(r))}</td></tr>`).join("") || '<tr><td class="muted">ไม่มีข้อมูล</td></tr>'}</table>`;
}
const listCard = (title, items, fn, empty) => `<div class="card"><h3>${title}</h3>${items.length ? `<table>${items.map(fn).join("")}</table>` : `<p class="muted">${empty}</p>`}</div>`;
async function renderDashboard() {
  const d = await api("dashboard"); const k = d.kpis;
  $("#content").innerHTML = `<div class="kpis">
    ${kpi("ยอดขายที่ส่งมอบแล้ว", baht(k.sales_delivered))}${kpi("กำไรขั้นต้น", `${baht(k.gross_profit)} <small class="muted" style="font-size:14px">(${k.gross_margin_pct}%)</small>`)}
    ${kpi("ออเดอร์ที่กำลังดำเนินการ", baht(k.pipeline_value))}${kpi("ใบเสนอราคารอยืนยัน", baht(k.quote_value))}
    ${kpi("ลูกหนี้ค้างชำระ", baht(k.receivable))}${kpi("รับเงินเดือนนี้", baht(k.received_this_month))}
    ${kpi("ออเดอร์เดือนนี้", k.orders_this_month)}${kpi("ออเดอร์เลยกำหนดส่ง", k.overdue_orders)}
    ${kpi("งานผลิตที่กำลังทำ", k.production_active)}${kpi("มูลค่าสินค้า+วัตถุดิบคงคลัง", baht(k.inventory_value))}
  </div>
  <div class="grid2">
    <div class="card"><h3>ยอดสั่งซื้อ 6 เดือนล่าสุด</h3>${bars(d.monthly_sales, (r) => r.month, (r) => r.total, baht)}</div>
    <div class="card"><h3>สินค้าขายดี (ตามยอดขาย)</h3>${bars(d.top_products, (r) => `${r.name} (${r.qty})`, (r) => r.revenue, baht)}</div>
    <div class="card"><h3>ยอดขายตามประเภทลูกค้า</h3>${bars(d.sales_by_customer_type, (r) => L(r.type), (r) => r.total, baht)}</div>
    ${listCard("⚠️ สินค้าใกล้หมด", d.low_stock_products, (p) => `<tr><td>${esc(p.name)}</td><td class="num">${p.stock_qty} / จุดสั่ง ${p.reorder_level}</td></tr>`, "สต็อกสินค้าเพียงพอ")}
    ${listCard("⚠️ วัตถุดิบใกล้หมด", d.low_stock_materials, (m) => `<tr><td>${esc(m.name)}</td><td class="num">${num(m.qty)} ${L(m.unit)}</td></tr>`, "วัตถุดิบเพียงพอ")}
    ${listCard("⏰ ออเดอร์เลยกำหนดส่ง", d.overdue, (o) => `<tr><td>SO-${String(o.id).padStart(4, "0")} · ${esc(o.customer_name)}</td><td class="num">${badge(o.status)} ${o.due_date}</td></tr>`, "ไม่มีออเดอร์ล่าช้า 👍")}
  </div>`;
}

async function renderTable(s) {
  const data = await api(s.res); cache[s.res] = data;
  const fk = s.filterKey || "status";
  const fopts = s.filter ? `<select id="f"><option value="">ทั้งหมด</option>${(META.enums[s.filter] || []).map((v) => `<option value="${v}" ${state.f === v ? "selected" : ""}>${esc(L(v))}</option>`).join("")}</select>` : "";
  $("#content").innerHTML = `<div class="toolbar"><input id="q" placeholder="ค้นหา…" value="${esc(state.q)}">${fopts}</div>
    <div class="table-wrap"><table><thead><tr>${s.columns.map((c) => `<th class="${c[2] || ""}">${c[0]}</th>`).join("")}<th></th></tr></thead><tbody id="tb"></tbody></table></div>
    ${s.note ? `<p class="muted">${s.note}</p>` : ""}`;
  const draw = () => {
    const q = state.q.toLowerCase();
    const list = data.filter((r) => (!q || s.search.some((k) => String(r[k] ?? "").toLowerCase().includes(q))) && (!state.f || r[fk] === state.f));
    const handlers = [];
    $("#tb").innerHTML = list.map((r) => {
      const acts = [...(s.actions ? s.actions(r) : [])];
      if (!s.editable || s.editable(r)) acts.push(["แก้ไข", () => openForm(s, r)]);
      acts.push(["ลบ", () => del(s, r), "danger"]);
      const btns = acts.map(([label, fn, cls]) => { handlers.push(fn); return `<button type="button" class="btn sm ${cls || ""}" data-h="${handlers.length - 1}">${label}</button>`; }).join(" ");
      return `<tr class="${s.rowClass ? s.rowClass(r) : ""}">${s.columns.map((c) => `<td class="${c[2] || ""}">${c[1](r)}</td>`).join("")}<td>${btns}</td></tr>`;
    }).join("") || `<tr><td colspan="${s.columns.length + 1}" class="muted">ไม่พบข้อมูล</td></tr>`;
    $("#tb").querySelectorAll("[data-h]").forEach((b) => (b.onclick = () => handlers[b.dataset.h]()));
  };
  $("#q").oninput = (e) => { state.q = e.target.value; draw(); };
  if ($("#f")) $("#f").onchange = (e) => { state.f = e.target.value; draw(); };
  draw();
}

async function quick(res, id, body, confirmMsg) {
  if (confirmMsg && !confirm(confirmMsg)) return;
  try { await api(`${res}/${id}`, { method: "PUT", body }); clearCache(); toast("อัปเดตแล้ว"); go(current); } catch (e) { alert(e.message); }
}
async function del(s, r) {
  if (!confirm("ยืนยันการลบรายการนี้?")) return;
  try { await api(`${s.res}/${r.id}`, { method: "DELETE" }); clearCache(); toast("ลบแล้ว"); go(current); } catch (e) { alert(e.message); }
}

// ---------- forms ----------
function lineRow(cfg, opts, line = {}) {
  return `<div class="line"><select data-k="${cfg.key}"><option value="">— เลือก —</option>${opts.map((o) => `<option value="${o.id}" ${o.id == line[cfg.key] ? "selected" : ""}>${esc(cfg.label(o))}</option>`).join("")}</select>
    <input data-k="qty" type="number" step="any" min="0" placeholder="${cfg.qtyLabel}" value="${esc(line.qty ?? "")}">
    ${cfg.priceField ? `<input data-k="unit_price" type="number" step="any" min="0" placeholder="ราคาตั้ง" value="${esc(line.unit_price ?? "")}">` : "<span></span>"}
    <button type="button" class="btn sm danger" data-rm>✕</button></div>`;
}
async function linesField(key, label, cfg, existing) {
  const opts = await load(cfg.table);
  const id = "lines-" + key;
  setTimeout(() => {
    const box = document.getElementById(id);
    const bind = () => box.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => b.parentElement.remove()));
    box.parentElement.querySelector("[data-add]").onclick = () => { box.insertAdjacentHTML("beforeend", lineRow(cfg, opts)); bind(); };
    bind();
  });
  const rowsHtml = (existing && existing.length ? existing : [{}]).map((l) => lineRow(cfg, opts, l)).join("");
  return `<div class="lines" data-lines="${key}"><div class="hdr">${label} — ${cfg.qtyLabel}${cfg.priceField ? " / " + cfg.priceLabel + " (เว้นว่าง = ราคาตั้ง)" : ""}</div>
    <div id="${id}" class="lines">${rowsHtml}</div><div><button type="button" class="btn sm" data-add>+ เพิ่มรายการ</button></div></div>`;
}
async function openForm(s, row) {
  const dlg = $("#dlg");
  $("#dlg-title").textContent = (row ? "แก้ไข" : "เพิ่ม") + s.title;
  $("#dlg-error").textContent = ""; $("#dlg-save").hidden = false;
  if (row && s.res === "orders") row = await api(`orders/${row.id}`);
  const parts = [];
  for (const [key, label, type] of s.fields) {
    const v = row ? row[key] ?? "" : (type === "date" && /date/.test(key) && key !== "due_date" ? today() : "");
    if (typeof type === "object" && type.type === "lines") {
      if (row && type.createOnly) continue;
      parts.push(await linesField(key, label, type, row && row[key]));
      continue;
    }
    let input;
    if (typeof type === "object" && type.type === "ref") {
      const opts = await load(type.table);
      input = `<select name="${key}"><option value="">${type.optional ? "— ไม่ระบุ —" : "— เลือก —"}</option>${opts.map((o) => `<option value="${o.id}" ${o.id == v ? "selected" : ""}>${esc(type.label(o))}</option>`).join("")}</select>`;
    } else if (type === "enum") {
      const vals = META.enums[`${s.res}.${key}`] || [];
      input = `<select name="${key}">${row ? "" : '<option value="">(ค่าเริ่มต้น)</option>'}${vals.map((x) => `<option value="${x}" ${x === v ? "selected" : ""}>${esc(L(x))}</option>`).join("")}</select>`;
    } else if (type === "bool") {
      const on = row ? Number(v) === 1 : true;
      input = `<select name="${key}"><option value="1" ${on ? "selected" : ""}>ใช่</option><option value="0" ${on ? "" : "selected"}>ไม่ใช่</option></select>`;
    } else if (type === "textarea") input = `<textarea name="${key}" rows="2">${esc(v)}</textarea>`;
    else input = `<input name="${key}" type="${type}" ${type === "number" ? 'step="any"' : ""} value="${esc(v)}">`;
    parts.push(`<label class="${type === "textarea" ? "full" : ""}">${label}${input}</label>`);
  }
  $("#dlg-fields").innerHTML = parts.join("");
  $("#dlg-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(e.target).forEach((val, k) => { if (val !== "" || row) body[k] = val; });
    e.target.querySelectorAll("[data-lines]").forEach((box) => {
      body[box.dataset.lines] = [...box.querySelectorAll(".line")].map((ln) => {
        const o = {}; ln.querySelectorAll("[data-k]").forEach((el) => { if (el.value !== "") o[el.dataset.k] = el.value; }); return o;
      }).filter((o) => Object.keys(o).length);
    });
    try {
      await api(row ? `${s.res}/${row.id}` : s.res, { method: row ? "PUT" : "POST", body });
      dlg.close(); clearCache(); toast("บันทึกแล้ว"); go(current);
    } catch (err) { $("#dlg-error").textContent = err.message; }
  };
  dlg.showModal();
}
async function receivePayment(o) {
  const s = SCREENS.payments;
  await openForm(s);
  $("#dlg-title").textContent = `รับชำระ SO-${String(o.id).padStart(4, "0")} · ${o.customer_name}`;
  $("#dlg-form").order_id.value = o.id;
  $("#dlg-form").amount.value = o.balance;
  $("#dlg-form").kind.value = o.paid > 0 ? "balance" : "full";
}
async function showOrder(id) {
  const o = await api(`orders/${id}`);
  $("#dlg-title").textContent = `ออเดอร์ SO-${String(o.id).padStart(4, "0")}`;
  $("#dlg-error").textContent = ""; $("#dlg-save").hidden = true;
  $("#dlg-fields").innerHTML = `<div class="detail">
    <p><b>${esc(o.customer_name)}</b> · ${esc(L(o.customer_type))}<br>วันที่สั่ง ${o.order_date} · กำหนดส่ง ${o.due_date || "—"}${o.delivered_date ? " · ส่งมอบ " + o.delivered_date : ""} · ${badge(o.status)}</p>
    <table><thead><tr><th>สินค้า</th><th class="num">จำนวน</th><th class="num">ราคา</th><th class="num">รวม</th></tr></thead><tbody>
    ${o.items.map((i) => `<tr><td>${esc(i.sku)} · ${esc(i.product_name)}</td><td class="num">${i.qty}</td><td class="num">${baht(i.unit_price)}</td><td class="num">${baht(i.qty * i.unit_price)}</td></tr>`).join("")}
    <tr><td colspan="3">ส่วนลด</td><td class="num">−${baht(o.discount)}</td></tr><tr><td colspan="3">ค่าขนส่ง</td><td class="num">${baht(o.delivery_fee)}</td></tr>
    <tr><td colspan="3"><b>ยอดรวม</b></td><td class="num"><b>${baht(o.total)}</b></td></tr></tbody></table>
    <table><thead><tr><th>วันที่ชำระ</th><th>ประเภท</th><th>ช่องทาง</th><th class="num">จำนวน</th></tr></thead><tbody>
    ${o.payments.map((p) => `<tr><td>${p.paid_date}</td><td>${badge(p.kind)}</td><td>${L(p.method)}</td><td class="num">${baht(p.amount)}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">ยังไม่มีการชำระ</td></tr>'}
    <tr><td colspan="3"><b>คงค้าง</b></td><td class="num"><b>${baht(o.balance)}</b></td></tr></tbody></table>
    ${o.note ? `<p class="muted">หมายเหตุ: ${esc(o.note)}</p>` : ""}</div>`;
  $("#dlg").showModal();
}
$("#dlg-cancel").onclick = () => $("#dlg").close();
$("#add-btn").onclick = () => openForm(SCREENS[current]);
window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (SCREENS[h] && h !== current) go(h); });
(async () => { META = await api("meta"); const h = location.hash.slice(1); go(SCREENS[h] ? h : "dashboard"); })();
