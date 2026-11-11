// ทังทังซุป mala shop ERP front-end — vanilla JS.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const baht = (n) => "฿" + Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
const num = (n) => Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
const today = () => new Date().toISOString().slice(0, 10);

const LABELS = {
  meat: "เนื้อสัตว์", seafood: "ทะเล", meatball: "ลูกชิ้น", vegetable: "ผัก/เห็ด", tofu: "เต้าหู้", noodle: "เส้น", soup_base: "น้ำซุป", sauce: "เครื่องปรุง", drink: "เครื่องดื่ม", other: "อื่นๆ",
  skewer: "ไม้", kg: "กก.", g: "กรัม", pack: "แพ็ก", piece: "ชิ้น", bottle: "ขวด", litre: "ลิตร", bag: "ถุง", box: "กล่อง",
  manager: "ผู้จัดการ", cook: "พ่อครัว/แม่ครัว", prep: "เตรียมวัตถุดิบ", server: "พนักงานเสิร์ฟ", cashier: "แคชเชียร์", delivery: "ส่งของ", dishwasher: "ล้างจาน",
  full_time: "ประจำ", part_time: "พาร์ทไทม์", hour: "ชั่วโมง", day: "วัน", month: "เดือน",
  applicant: "ผู้สมัครใหม่", interview: "นัดสัมภาษณ์", hired: "ทำงานอยู่", rejected: "ไม่ผ่าน", resigned: "ลาออก",
  dine_in: "ทานที่ร้าน", takeaway: "กลับบ้าน", grab: "Grab", lineman: "LINE MAN", shopee: "ShopeeFood", robinhood: "Robinhood",
  cash: "เงินสด", promptpay: "PromptPay", card: "บัตร", app: "ผ่านแอป",
  spoiled: "เน่า/เสีย", expired: "หมดอายุ", dropped: "ตก/เสียหาย", stock_count: "ปรับยอดนับสต็อก", staff_meal: "อาหารพนักงาน",
  ok: "ปกติ", low: "ใกล้หมด", out: "หมด",
};
const L = (v) => LABELS[v] ?? v ?? "";
const CLS = { ok: "ok", low: "warn", out: "bad", hired: "ok", interview: "warn", applicant: "", rejected: "bad", resigned: "bad" };
const badge = (v) => `<span class="badge ${CLS[v] || ""}">${esc(L(v))}</span>`;
const bill = (id) => "B" + String(id).padStart(5, "0");

let META = { enums: {} };
const cache = {};
async function api(path, opts = {}) {
  const res = await fetch("/api/mala/" + path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const load = async (t) => cache[t] || (cache[t] = await api(t));
const clearCache = () => Object.keys(cache).forEach((k) => delete cache[k]);
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2400); }

const ref = (table, label, optional, filter) => ({ type: "ref", table, label, optional, filter });
const itemLabel = (i) => `${i.name} (เหลือ ${num(i.qty)} ${L(i.unit)})`;
const staffLabel = (s) => `${s.nickname || s.name} · ${L(s.position)}`;
const hiredOnly = (s) => s.status === "hired";

const SCREENS = {
  dashboard: { title: "แดชบอร์ด" },
  pos: { title: "ขายสินค้า (POS)" },
  receipts: {
    title: "รับสินค้าเข้า", res: "receipts", addLabel: "+ รับสินค้าเข้า", search: ["item_name", "supplier", "note"],
    columns: [["วันที่", (r) => r.received_date], ["สินค้า", (r) => `<b>${esc(r.item_name)}</b>`], ["จำนวน", (r) => `${num(r.qty)} ${L(r.unit)}`, "num"],
      ["ทุน/หน่วย", (r) => baht(r.unit_cost), "num"], ["รวม", (r) => baht(r.total), "num"], ["ร้านที่ซื้อ", (r) => esc(r.supplier || "—")],
      ["ผู้รับ", (r) => esc(r.staff_name || "—")], ["หมายเหตุ", (r) => esc(r.note)]],
    fields: [["item_id", "สินค้า/วัตถุดิบ", ref("items", itemLabel)], ["qty", "จำนวนที่รับเข้า", "number"], ["unit_cost", "ราคาทุน/หน่วย (เว้นว่าง = ทุนเดิม)", "number"],
      ["supplier", "ร้านที่ซื้อ", "text"], ["received_date", "วันที่รับ", "date"], ["staff_id", "ผู้รับของ", ref("staff", staffLabel, true, hiredOnly)], ["note", "หมายเหตุ", "textarea"]],
    deleteLabel: "ยกเลิก", note: "ยกเลิกการรับเข้าได้เฉพาะล็อตที่ยังไม่ถูกขายออกไป · ต้นทุนคิดแบบถัวเฉลี่ย",
  },
  sales: {
    title: "สินค้าขายไป", res: "sales", search: ["items_summary", "staff_name", "id"], filter: "sales.channel", filterKey: "channel",
    columns: [["บิล", (r) => bill(r.id)], ["วันที่", (r) => `${r.sale_date} ${r.sale_time || ""}`], ["ช่องทาง", (r) => L(r.channel)],
      ["รายการ", (r) => `<span title="${esc(r.items_summary)}">${esc((r.items_summary || "").slice(0, 55))}</span>`],
      ["จำนวนชิ้น", (r) => num(r.item_qty), "num"], ["ยอดขาย", (r) => `<b>${baht(r.total)}</b>`, "num"], ["กำไร", (r) => baht(r.profit), "num"],
      ["ชำระ", (r) => L(r.payment)], ["พนักงาน", (r) => esc(r.staff_name || "—")]],
    actions: (r) => [["ดูบิล", () => showBill(r.id)]],
    noEdit: true, deleteLabel: "ยกเลิกบิล", deleteConfirm: "ยกเลิกบิลนี้? สินค้าจะถูกคืนเข้าสต็อก",
  },
  items: {
    title: "สินค้าคงเหลือ", res: "items", addLabel: "+ เพิ่มสินค้า", search: ["name", "supplier"], filter: "items.category", filterKey: "category",
    columns: [["สินค้า", (r) => `<b>${esc(r.name)}</b>${r.active ? "" : ' <span class="badge">ปิด</span>'}`], ["หมวด", (r) => L(r.category)],
      ["คงเหลือ", (r) => `<b>${num(r.qty)}</b> ${L(r.unit)}`, "num"], ["สถานะ", (r) => badge(r.stock_status)],
      ["จุดสั่ง / สต็อกเต็ม", (r) => `${num(r.reorder_level)} / ${num(r.par_level)}`, "num"], ["ขาย 7 วัน", (r) => num(r.sold_7d), "num"],
      ["ทุน", (r) => baht(r.unit_cost), "num"], ["ราคาขาย", (r) => (r.sellable ? baht(r.sell_price) : '<span class="muted">วัตถุดิบ</span>'), "num"],
      ["มูลค่าคงเหลือ", (r) => baht(r.value), "num"], ["ร้านที่ซื้อ", (r) => esc(r.supplier)]],
    rowClass: (r) => (r.stock_status === "out" ? "row-warn" : ""),
    actions: (r) => [["รับเข้า", () => receiveItem(r)], ["ตัดของเสีย", () => wasteItem(r)]],
    fields: [["name", "ชื่อสินค้า", "text"], ["category", "หมวด", "enum"], ["unit", "หน่วย", "enum"], ["qty", "คงเหลือ (ปรับยอด)", "number"],
      ["unit_cost", "ราคาทุน/หน่วย", "number"], ["sell_price", "ราคาขาย/หน่วย", "number"], ["reorder_level", "จุดสั่งซื้อ (เหลือเท่านี้ให้สั่ง)", "number"],
      ["par_level", "สต็อกเต็ม (สั่งให้ถึงเท่านี้)", "number"], ["supplier", "ร้านที่ซื้อประจำ", "text"], ["sellable", "ขายหน้าร้าน (แสดงใน POS)", "bool"], ["active", "เปิดใช้งาน", "bool"]],
  },
  reorder: { title: "สินค้าต้องสั่งเพิ่ม" },
  waste: {
    title: "ของเสีย / ปรับยอด", res: "waste", addLabel: "+ ตัดของเสีย", search: ["item_name", "note"], filter: "waste.reason", filterKey: "reason",
    columns: [["วันที่", (r) => r.waste_date], ["สินค้า", (r) => esc(r.item_name)], ["จำนวน", (r) => `${num(r.qty)} ${L(r.unit)}`, "num"],
      ["มูลค่า", (r) => baht(r.value), "num"], ["สาเหตุ", (r) => L(r.reason)], ["ผู้บันทึก", (r) => esc(r.staff_name || "—")], ["หมายเหตุ", (r) => esc(r.note)]],
    fields: [["item_id", "สินค้า", ref("items", itemLabel)], ["qty", "จำนวน", "number"], ["reason", "สาเหตุ", "enum"], ["waste_date", "วันที่", "date"],
      ["staff_id", "ผู้บันทึก", ref("staff", staffLabel, true, hiredOnly)], ["note", "หมายเหตุ", "textarea"]],
    noEdit: true, deleteLabel: "ยกเลิก",
  },
  staff: {
    title: "พนักงาน & รับสมัคร", res: "staff", addLabel: "+ รับสมัครพนักงาน", search: ["name", "nickname", "phone", "note"], filter: "staff.status", filterKey: "status",
    columns: [["ชื่อ", (r) => `<b>${esc(r.nickname || "")}</b> ${esc(r.name)}`], ["ตำแหน่ง", (r) => L(r.position)], ["ประเภท", (r) => L(r.employment)],
      ["ค่าจ้าง", (r) => `${baht(r.wage)}/${L(r.wage_type)}`, "num"], ["โทร", (r) => esc(r.phone)],
      ["วันที่", (r) => (r.status === "interview" ? "สัมภาษณ์ " + (r.interview_date || "—") : r.status === "hired" ? "เริ่มงาน " + (r.start_date || "—") : "สมัคร " + (r.applied_date || "—"))],
      ["สถานะ", (r) => badge(r.status)], ["หมายเหตุ", (r) => esc(r.note)]],
    actions: (r) => ({
      applicant: [["นัดสัมภาษณ์", () => interview(r)], ["รับเข้าทำงาน", () => quick("staff", r.id, { status: "hired" }, `รับ ${r.nickname || r.name} เข้าทำงาน?`)], ["ไม่ผ่าน", () => quick("staff", r.id, { status: "rejected" })]],
      interview: [["รับเข้าทำงาน", () => quick("staff", r.id, { status: "hired" }, `รับ ${r.nickname || r.name} เข้าทำงาน?`)], ["ไม่ผ่าน", () => quick("staff", r.id, { status: "rejected" })]],
      hired: [["ลาออก", () => quick("staff", r.id, { status: "resigned" }, "บันทึกว่าพนักงานลาออก?")]],
    }[r.status] || []),
    fields: [["name", "ชื่อ-นามสกุล", "text"], ["nickname", "ชื่อเล่น", "text"], ["position", "ตำแหน่งที่สมัคร", "enum"], ["employment", "ประเภทการจ้าง", "enum"],
      ["wage", "ค่าจ้าง (บาท)", "number"], ["wage_type", "ค่าจ้างต่อ", "enum"], ["phone", "เบอร์โทร", "text"], ["line_id", "LINE ID", "text"],
      ["status", "สถานะ", "enum"], ["applied_date", "วันที่สมัคร", "date"], ["interview_date", "วันนัดสัมภาษณ์", "date"], ["start_date", "วันเริ่มงาน", "date"],
      ["note", "หมายเหตุ (ประสบการณ์ / วันเวลาที่สะดวก)", "textarea"]],
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
  $("#page-title").textContent = s.title;
  $("#add-btn").hidden = !s.res || !s.fields; $("#add-btn").textContent = s.addLabel || "+ เพิ่มรายการ";
  $("#content").innerHTML = '<p class="muted">กำลังโหลด…</p>';
  try {
    if (k === "dashboard") await renderDashboard();
    else if (k === "pos") await renderPOS();
    else if (k === "reorder") await renderReorder();
    else await renderTable(s);
  } catch (e) { $("#content").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

// ---------- dashboard ----------
const kpi = (l, v, hot) => `<div class="kpi ${hot ? "hot" : ""}"><div class="label">${l}</div><div class="value">${v}</div></div>`;
function bars(list, labelFn, valFn, fmt = num) {
  const max = Math.max(1, ...list.map(valFn));
  return `<table>${list.map((r) => `<tr><td>${esc(labelFn(r))}</td><td style="width:50%"><div class="bar" style="width:${(valFn(r) / max) * 100}%"></div></td><td class="num">${fmt(valFn(r))}</td></tr>`).join("") || '<tr><td class="muted">ไม่มีข้อมูล</td></tr>'}</table>`;
}
async function renderDashboard() {
  const d = await api("dashboard"); const k = d.kpis;
  $("#content").innerHTML = `<div class="kpis">
    ${kpi("ยอดขายวันนี้", baht(k.sales_today))}${kpi("บิลวันนี้", k.bills_today)}${kpi("กำไรขั้นต้นวันนี้", baht(k.profit_today))}
    ${kpi("ยอดขายเดือนนี้", baht(k.sales_month))}${kpi("กำไรขั้นต้นเดือนนี้", baht(k.profit_month))}${kpi("รับสินค้าเข้าเดือนนี้", baht(k.received_month))}
    ${kpi("ของเสียเดือนนี้", baht(k.waste_month))}${kpi("มูลค่าสต็อกคงเหลือ", baht(k.stock_value))}
    ${kpi("สินค้าต้องสั่งเพิ่ม", `${k.reorder_count} <small class="muted" style="font-size:14px">(หมด ${k.out_of_stock})</small>`, k.reorder_count > 0)}
    ${kpi("พนักงานปัจจุบัน", k.staff_active)}${kpi("ผู้สมัครรอพิจารณา", k.applicants)}
  </div>
  <div class="grid2">
    <div class="card"><h3>ยอดขาย 7 วันล่าสุด</h3>${bars(d.daily_sales, (r) => r.date.slice(5), (r) => r.total, baht)}</div>
    <div class="card"><h3>🔥 ขายดี 7 วัน (จำนวน)</h3>${bars(d.top_items, (r) => r.name, (r) => r.qty)}</div>
    <div class="card"><h3>ยอดขายตามช่องทาง (เดือนนี้)</h3>${bars(d.sales_by_channel, (r) => L(r.channel), (r) => r.total, baht)}</div>
    <div class="card"><h3>⚠️ ต้องสั่งเพิ่ม</h3>${d.reorder.length ? `<table>${d.reorder.map((i) => `<tr><td>${esc(i.name)} ${badge(i.stock_status)}</td><td class="num">เหลือ ${num(i.qty)} · สั่ง ${num(i.suggest_qty)} ${L(i.unit)}</td></tr>`).join("")}</table><p><a href="#reorder" class="btn sm">ดูรายการสั่งซื้อ →</a></p>` : '<p class="muted">สต็อกเพียงพอทุกรายการ 👍</p>'}</div>
    <div class="card"><h3>👥 ผู้สมัครงาน</h3>${d.applicants.length ? `<table>${d.applicants.map((a) => `<tr><td>${esc(a.nickname || a.name)} · ${L(a.position)}</td><td class="num">${badge(a.status)} ${a.interview_date || ""}</td></tr>`).join("")}</table>` : '<p class="muted">ไม่มีผู้สมัครค้างพิจารณา</p>'}</div>
  </div>`;
}

// ---------- POS ----------
let cart = [];
let posCat = "";
async function renderPOS() {
  const items = (await api("items")).filter((i) => i.active && i.sellable);
  cache.items = null;
  const staff = (await load("staff")).filter(hiredOnly);
  const cats = [...new Set(items.map((i) => i.category))];
  const drawTiles = () => {
    $("#tiles").innerHTML = items.filter((i) => !posCat || i.category === posCat).map((i) => {
      const inCart = cart.find((c) => c.item.id === i.id)?.qty || 0;
      const left = i.qty - inCart;
      return `<button class="tile" data-id="${i.id}" ${left <= 0 ? "disabled" : ""}><b>${esc(i.name)}</b><span class="p">${baht(i.sell_price)}</span>
        <div class="s">เหลือ ${num(left)} ${L(i.unit)}${i.stock_status !== "ok" ? " ⚠️" : ""}</div></button>`;
    }).join("");
    $("#tiles").querySelectorAll(".tile").forEach((b) => (b.onclick = () => {
      const it = items.find((i) => i.id == b.dataset.id); const line = cart.find((c) => c.item.id === it.id);
      line ? line.qty++ : cart.push({ item: it, qty: 1 }); draw();
    }));
  };
  const drawCart = () => {
    const sub = cart.reduce((a, c) => a + c.qty * c.item.sell_price, 0);
    const disc = Number($("#disc")?.value || 0);
    $("#lines").innerHTML = cart.map((c, idx) => `<div class="line"><span>${esc(c.item.name)}<br><small class="muted">${baht(c.item.sell_price)}</small></span>
      <span class="qtyc"><button class="btn sm" data-m="${idx}">−</button>${c.qty}<button class="btn sm" data-p="${idx}">+</button></span><b>${baht(c.qty * c.item.sell_price)}</b></div>`).join("")
      || '<p class="muted">กดเลือกสินค้าทางซ้ายเพื่อเพิ่มลงบิล</p>';
    $("#total").textContent = baht(Math.max(sub - disc, 0));
    $("#lines").querySelectorAll("[data-m]").forEach((b) => (b.onclick = () => { const c = cart[b.dataset.m]; c.qty--; if (c.qty <= 0) cart.splice(b.dataset.m, 1); draw(); }));
    $("#lines").querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => { const c = cart[b.dataset.p]; if (c.qty < c.item.qty) c.qty++; draw(); }));
  };
  const draw = () => { drawTiles(); drawCart(); };
  const opt = (name, vals) => `<select id="${name}">${vals.map((v) => `<option value="${v}">${L(v)}</option>`).join("")}</select>`;
  $("#content").innerHTML = `<div class="pos"><div>
      <div class="cats"><button class="btn sm chip ${posCat ? "" : "on"}" data-c="">ทั้งหมด</button>${cats.map((c) => `<button class="btn sm chip ${posCat === c ? "on" : ""}" data-c="${c}">${L(c)}</button>`).join("")}</div>
      <div class="tiles" id="tiles"></div></div>
    <div class="card cart"><h3>บิลปัจจุบัน</h3><div id="lines"></div>
      <label class="muted">ส่วนลด (บาท)<input id="disc" type="number" min="0" step="any" value="0"></label>
      <div class="total" id="total">฿0</div>
      ${opt("channel", META.enums["sales.channel"])}${opt("payment", META.enums["sales.payment"])}
      <select id="staff"><option value="">— พนักงานขาย —</option>${staff.map((s) => `<option value="${s.id}">${esc(staffLabel(s))}</option>`).join("")}</select>
      <p id="pos-err" class="error"></p>
      <button class="btn primary" id="checkout" style="width:100%;padding:12px">💰 ชำระเงิน / บันทึกการขาย</button>
      <button class="btn" id="clear" style="width:100%;margin-top:6px">ล้างบิล</button></div></div>`;
  $("#content").querySelectorAll("[data-c]").forEach((b) => (b.onclick = () => { posCat = b.dataset.c; renderPOS(); }));
  $("#disc").oninput = drawCart;
  $("#clear").onclick = () => { cart = []; draw(); };
  $("#checkout").onclick = async () => {
    if (!cart.length) { $("#pos-err").textContent = "ยังไม่มีสินค้าในบิล"; return; }
    try {
      const s = await api("sales", { method: "POST", body: { channel: $("#channel").value, payment: $("#payment").value, staff_id: $("#staff").value || undefined,
        discount: $("#disc").value || 0, items: cart.map((c) => ({ item_id: c.item.id, qty: c.qty })) } });
      cart = []; toast(`บันทึกบิล ${bill(s.id)} · ${baht(s.total)}`); clearCache(); renderPOS();
    } catch (e) { $("#pos-err").textContent = e.message; }
  };
  draw();
}

// ---------- reorder ----------
async function renderReorder() {
  const list = await api("reorder");
  const groups = {};
  list.forEach((i) => (groups[i.supplier || "ไม่ระบุร้าน"] ||= []).push(i));
  const total = list.reduce((a, i) => a + i.suggest_cost, 0);
  $("#content").innerHTML = list.length ? `<p class="muted">รายการที่คงเหลือถึงจุดสั่งซื้อ · จำนวนแนะนำ = สั่งให้ถึง “สต็อกเต็ม” · ประมาณการรวม <b>${baht(total)}</b></p>
    ${Object.entries(groups).map(([sup, items], gi) => `<div class="card" style="margin-bottom:12px"><h3>🛒 ${esc(sup)}
      <button class="btn sm" data-copy="${gi}" style="float:right">คัดลอกรายการส่ง LINE</button></h3>
      <table><thead><tr><th>สินค้า</th><th class="num">คงเหลือ</th><th class="num">จุดสั่ง</th><th class="num">แนะนำให้สั่ง</th><th class="num">ประมาณการ</th><th>สถานะ</th><th></th></tr></thead><tbody>
      ${items.map((i) => `<tr><td><b>${esc(i.name)}</b></td><td class="num">${num(i.qty)} ${L(i.unit)}</td><td class="num">${num(i.reorder_level)}</td>
        <td class="num"><b>${num(i.suggest_qty)} ${L(i.unit)}</b></td><td class="num">${baht(i.suggest_cost)}</td><td>${badge(i.stock_status)}</td>
        <td><button class="btn sm primary" data-recv="${i.id}">รับเข้าแล้ว</button></td></tr>`).join("")}</tbody></table></div>`).join("")}`
    : '<div class="card"><p>✅ ไม่มีสินค้าที่ต้องสั่งเพิ่ม สต็อกเพียงพอทุกรายการ</p></div>';
  const groupList = Object.entries(groups);
  $("#content").querySelectorAll("[data-copy]").forEach((b) => (b.onclick = async () => {
    const [sup, items] = groupList[b.dataset.copy];
    const text = `สั่งของ ร้านทังทังซุป (${today()})\nถึง: ${sup}\n` + items.map((i, n) => `${n + 1}. ${i.name} ${num(i.suggest_qty)} ${L(i.unit)}`).join("\n");
    try { await navigator.clipboard.writeText(text); toast("คัดลอกแล้ว วางใน LINE ได้เลย"); } catch { prompt("คัดลอกข้อความนี้", text); }
  }));
  $("#content").querySelectorAll("[data-recv]").forEach((b) => (b.onclick = () => { const i = list.find((x) => x.id == b.dataset.recv); receiveItem(i, i.suggest_qty); }));
}

// ---------- generic table ----------
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
      if (!s.noEdit) acts.push(["แก้ไข", () => openForm(s, r)]);
      acts.push([s.deleteLabel || "ลบ", () => del(s, r), "danger"]);
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
  if (!confirm(s.deleteConfirm || "ยืนยันการลบ/ยกเลิกรายการนี้?")) return;
  try { await api(`${s.res}/${r.id}`, { method: "DELETE" }); clearCache(); toast("เรียบร้อย"); go(current); } catch (e) { alert(e.message); }
}

// ---------- forms ----------
async function openForm(s, row, preset = {}) {
  const dlg = $("#dlg");
  $("#dlg-title").textContent = row ? "แก้ไข" + s.title : (s.addLabel || "+ เพิ่ม" + s.title).replace("+ ", "");
  $("#dlg-error").textContent = ""; $("#dlg-save").hidden = false;
  const parts = [];
  for (const [key, label, type] of s.fields) {
    const v = row ? row[key] ?? "" : preset[key] ?? (type === "date" && ["received_date", "waste_date", "applied_date"].includes(key) ? today() : "");
    let input;
    if (typeof type === "object" && type.type === "ref") {
      let opts = await load(type.table);
      if (type.filter) opts = opts.filter((o) => type.filter(o) || o.id == v);
      input = `<select name="${key}"><option value="">${type.optional ? "— ไม่ระบุ —" : "— เลือก —"}</option>${opts.map((o) => `<option value="${o.id}" ${o.id == v ? "selected" : ""}>${esc(type.label(o))}</option>`).join("")}</select>`;
    } else if (type === "enum") {
      const vals = META.enums[`${s.res}.${key}`] || [];
      input = `<select name="${key}">${row || v ? "" : '<option value="">(ค่าเริ่มต้น)</option>'}${vals.map((x) => `<option value="${x}" ${x === v ? "selected" : ""}>${esc(L(x))}</option>`).join("")}</select>`;
    } else if (type === "bool") {
      const on = row ? Number(v) === 1 : true;
      input = `<select name="${key}"><option value="1" ${on ? "selected" : ""}>ใช่</option><option value="0" ${on ? "" : "selected"}>ไม่ใช่</option></select>`;
    } else if (type === "textarea") input = `<textarea name="${key}" rows="2">${esc(v)}</textarea>`;
    else input = `<input name="${key}" type="${type}" ${type === "number" ? 'step="any" min="0"' : ""} value="${esc(v)}">`;
    parts.push(`<label class="${type === "textarea" ? "full" : ""}">${label}${input}</label>`);
  }
  $("#dlg-fields").innerHTML = parts.join("");
  $("#dlg-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(e.target).forEach((val, k) => { if (val !== "" || row) body[k] = val; });
    try {
      await api(row ? `${s.res}/${row.id}` : s.res, { method: row ? "PUT" : "POST", body });
      dlg.close(); clearCache(); toast("บันทึกแล้ว"); go(current);
    } catch (err) { $("#dlg-error").textContent = err.message; }
  };
  dlg.showModal();
}
const receiveItem = (i, qty) => openForm(SCREENS.receipts, null, { item_id: i.id, qty: qty ?? "", unit_cost: i.unit_cost, supplier: i.supplier || "" });
const wasteItem = (i) => openForm(SCREENS.waste, null, { item_id: i.id, reason: "spoiled" });
const interview = (r) => {
  const d = prompt("วันนัดสัมภาษณ์ (YYYY-MM-DD)", today());
  if (d) quick("staff", r.id, { status: "interview", interview_date: d });
};
async function showBill(id) {
  const s = await api(`sales/${id}`);
  $("#dlg-title").textContent = `บิล ${bill(s.id)}`; $("#dlg-error").textContent = ""; $("#dlg-save").hidden = true;
  $("#dlg-fields").innerHTML = `<div class="detail"><p>${s.sale_date} ${s.sale_time || ""} · ${L(s.channel)} · ${L(s.payment)} · พนักงาน ${esc(s.staff_name || "—")}</p>
    <table><thead><tr><th>รายการ</th><th class="num">จำนวน</th><th class="num">ราคา</th><th class="num">รวม</th></tr></thead><tbody>
    ${s.items.map((i) => `<tr><td>${esc(i.item_name)}</td><td class="num">${num(i.qty)}</td><td class="num">${baht(i.unit_price)}</td><td class="num">${baht(i.qty * i.unit_price)}</td></tr>`).join("")}
    <tr><td colspan="3">ส่วนลด</td><td class="num">−${baht(s.discount)}</td></tr>
    <tr><td colspan="3"><b>ยอดสุทธิ</b></td><td class="num"><b>${baht(s.total)}</b></td></tr>
    <tr><td colspan="3" class="muted">ต้นทุน / กำไรขั้นต้น</td><td class="num muted">${baht(s.cost)} / ${baht(s.profit)}</td></tr></tbody></table></div>`;
  $("#dlg").showModal();
}
$("#dlg-cancel").onclick = () => $("#dlg").close();
$("#add-btn").onclick = () => openForm(SCREENS[current]);
window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (SCREENS[h] && h !== current) go(h); });
(async () => { META = await api("meta"); const h = location.hash.slice(1); go(SCREENS[h] ? h : "dashboard"); })();
