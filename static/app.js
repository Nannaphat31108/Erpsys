// DeskHop ERP front-end — vanilla JS, config-driven CRUD screens.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const baht = (n) => "฿" + Number(n || 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
const yesno = (v) => (Number(v) ? "✔" : "—");

const LABELS = {
  cafe: "คาเฟ่", coworking: "Co-working", quiet: "เงียบ", moderate: "ปานกลาง", loud: "เสียงดัง",
  normal: "ปกติ", call_booth: "ห้องโทรศัพท์", active: "ใช้งาน", maintenance: "ซ่อมบำรุง", inactive: "ปิด",
  confirmed: "ยืนยันแล้ว", checked_in: "เช็กอินแล้ว", completed: "เสร็จสิ้น", cancelled: "ยกเลิก", desk_not_ready: "โต๊ะไม่พร้อม",
  card: "บัตร", promptpay: "PromptPay", truemoney: "TrueMoney", promo: "โปรโมชัน",
  wifi: "Wi-fi ช้า", noise: "เสียงดัง", outdated_photos: "รูป/ข้อมูลไม่ตรง", staff_unaware: "พนักงานไม่รู้จักระบบ",
  hidden_cost: "ค่าใช้จ่ายแฝง", app_bug: "แอปขัดข้อง", other: "อื่นๆ", open: "รอตอบกลับ", responded: "ตอบแล้ว", resolved: "ปิดเรื่อง",
  instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", referral: "เพื่อนแนะนำ", google: "Google", walk_in: "Walk-in",
};
const L = (v) => LABELS[v] ?? v ?? "";
const statusClass = { confirmed: "", checked_in: "ok", completed: "ok", cancelled: "bad", desk_not_ready: "bad", open: "bad", responded: "warn", resolved: "ok", active: "ok", maintenance: "warn", inactive: "bad" };
const badge = (v) => `<span class="badge ${statusClass[v] || ""}">${esc(L(v))}</span>`;

let META = { enums: {} };
const cache = {};

async function api(path, opts = {}) {
  const res = await fetch("/api/" + path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 2200); }

// lookups for <select> fields referencing other tables
const ref = (table, label) => ({ type: "ref", table, label });

const SCREENS = {
  dashboard: { title: "แดชบอร์ด" },
  bookings: {
    title: "การจอง", table: "bookings", searchKeys: ["customer_name", "venue_name", "desk_code", "status"],
    filter: { key: "status", enum: "bookings.status" },
    columns: [["#", (r) => r.id], ["วันที่", (r) => r.date], ["เวลา", (r) => `${r.start_time} (${r.hours} ชม.)`],
      ["ลูกค้า", (r) => esc(r.customer_name)], ["สถานที่ / โต๊ะ", (r) => `${esc(r.venue_name)} · ${esc(r.desk_code)}`],
      ["ส่วนลด", (r) => (r.discount ? baht(r.discount) : "—"), "num"], ["ยอดสุทธิ", (r) => baht(r.amount), "num"],
      ["ชำระ", (r) => L(r.payment_method)], ["สถานะ", (r) => badge(r.status)]],
    fields: [["customer_id", "ลูกค้า", ref("customers", (c) => c.name)], ["desk_id", "โต๊ะ", ref("desks", (d) => `${d.venue_name} · ${d.code}`)],
      ["date", "วันที่", "date"], ["start_time", "เวลาเริ่ม", "time"], ["hours", "จำนวนชั่วโมง", "number"],
      ["payment_method", "วิธีชำระเงิน", "enum"], ["status", "สถานะ", "enum"], ["note", "หมายเหตุ", "textarea"]],
    quick: (r) => r.status === "confirmed" ? [["เช็กอิน", { status: "checked_in" }], ["ยกเลิก", { status: "cancelled" }]]
      : r.status === "checked_in" ? [["เสร็จสิ้น", { status: "completed" }]] : [],
  },
  venues: {
    title: "สถานที่พาร์ทเนอร์", table: "venues", searchKeys: ["name", "area", "bts_station"],
    columns: [["ชื่อ", (r) => `<b>${esc(r.name)}</b> ${r.verified ? '<span class="badge ok">✔ Verified</span>' : '<span class="badge warn">รอตรวจ</span>'}`],
      ["ประเภท", (r) => L(r.type)], ["ย่าน / BTS", (r) => `${esc(r.area)} · ${esc(r.bts_station)} (${r.bts_walk_min} นาที)`],
      ["ราคา/ชม.", (r) => baht(r.hourly_rate), "num"], ["ค่าใช้จ่ายจริง/ชม.*", (r) => baht(r.true_hourly_cost), "num"],
      ["Wi-fi", (r) => `${r.wifi_mbps} Mbps`, "num"], ["เสียง", (r) => L(r.noise_level)], ["โต๊ะ", (r) => r.desk_count, "num"],
      ["คะแนน", (r) => r.avg_rating ?? "—", "num"], ["พนักงานรู้ระบบ", (r) => yesno(r.staff_trained)],
      ["ค่าคอม", (r) => r.commission_pct + "%", "num"], ["ตรวจล่าสุด", (r) => r.last_verified || "—"], ["สถานะ", (r) => badge(r.active ? "active" : "inactive")]],
    note: "* ค่าใช้จ่ายจริง = ราคาต่อชั่วโมง + (ยอดซื้อขั้นต่ำที่ร้านคาดหวัง ÷ 3 ชม.) — ช่วยให้ลูกค้าเห็นราคาที่แท้จริง",
    fields: [["name", "ชื่อสถานที่", "text"], ["type", "ประเภท", "enum"], ["area", "ย่าน", "text"], ["bts_station", "สถานี BTS/MRT", "text"],
      ["bts_walk_min", "เดินจากสถานี (นาที)", "number"], ["hourly_rate", "ราคา/ชั่วโมง (บาท)", "number"],
      ["expected_min_spend", "ยอดซื้อขั้นต่ำที่ร้านคาดหวัง (บาท)", "number"], ["wifi_mbps", "Wi-fi (Mbps)", "number"],
      ["noise_level", "ระดับเสียง", "enum"], ["commission_pct", "ค่าคอมมิชชัน (%)", "number"],
      ["staff_trained", "พนักงานรู้จัก DeskHop", "bool"], ["contact_line", "LINE ร้าน", "text"], ["active", "เปิดใช้งาน", "bool"]],
  },
  desks: {
    title: "โต๊ะ", table: "desks", searchKeys: ["venue_name", "code"],
    columns: [["สถานที่", (r) => esc(r.venue_name)], ["รหัสโต๊ะ", (r) => `<b>${esc(r.code)}</b>`], ["โซน", (r) => L(r.zone)],
      ["ปลั๊กไฟ", (r) => yesno(r.has_socket)], ["สถานะ", (r) => badge(r.status)]],
    fields: [["venue_id", "สถานที่", ref("venues", (v) => v.name)], ["code", "รหัสโต๊ะ", "text"], ["zone", "โซน", "enum"],
      ["has_socket", "มีปลั๊กไฟที่โต๊ะ", "bool"], ["status", "สถานะ", "enum"]],
  },
  customers: {
    title: "ลูกค้า (CRM)", table: "customers", searchKeys: ["name", "occupation", "phone", "line_id", "email"],
    columns: [["ชื่อ", (r) => `<b>${esc(r.name)}</b>`], ["อาชีพ", (r) => esc(r.occupation)], ["ติดต่อ", (r) => esc([r.phone, r.line_id && "LINE: " + r.line_id, r.email].filter(Boolean).join(" · "))],
      ["ช่องทางที่รู้จัก", (r) => L(r.channel)], ["จำนวนจอง", (r) => r.booking_count, "num"], ["ยอดใช้จ่ายรวม", (r) => baht(r.lifetime_value), "num"]],
    fields: [["name", "ชื่อ", "text"], ["occupation", "อาชีพ", "text"], ["phone", "โทรศัพท์", "text"], ["line_id", "LINE ID", "text"],
      ["email", "อีเมล", "text"], ["channel", "ช่องทางที่รู้จัก", "enum"]],
  },
  issues: {
    title: "รีวิวและข้อร้องเรียน", table: "issues", searchKeys: ["venue_name", "customer_name", "description"],
    filter: { key: "status", enum: "issues.status" },
    columns: [["#", (r) => r.id], ["วันที่", (r) => (r.created_at || "").slice(0, 10)], ["สถานที่", (r) => esc(r.venue_name)],
      ["ลูกค้า", (r) => esc(r.customer_name || "—")], ["คะแนน", (r) => (r.rating ? "★".repeat(r.rating) : "—")],
      ["หมวด", (r) => L(r.category)], ["รายละเอียด", (r) => `<span title="${esc(r.description)}">${esc((r.description || "").slice(0, 50))}</span>`],
      ["การตอบกลับ", (r) => esc((r.response || "").slice(0, 40)) || '<span class="muted">ยังไม่ตอบ</span>'], ["สถานะ", (r) => badge(r.status)]],
    fields: [["venue_id", "สถานที่", ref("venues", (v) => v.name)], ["customer_id", "ลูกค้า", ref("customers", (c) => c.name, true)],
      ["booking_id", "เลขที่การจอง (ถ้ามี)", "number"], ["rating", "คะแนน (1–5)", "number"], ["category", "หมวด", "enum"],
      ["status", "สถานะ", "enum"], ["description", "รายละเอียด", "textarea"], ["response", "ข้อความตอบกลับลูกค้า", "textarea"]],
  },
  verifications: {
    title: "ตรวจสอบสถานที่ (Verified)", table: "verifications", searchKeys: ["venue_name", "inspector"],
    note: "บันทึกการตรวจจะอัปเดต Wi-fi / ระดับเสียงของสถานที่ และให้ป้าย Verified อายุ 30 วัน",
    columns: [["วันที่ตรวจ", (r) => r.checked_at], ["สถานที่", (r) => esc(r.venue_name)], ["Wi-fi", (r) => (r.wifi_mbps ?? "—") + " Mbps", "num"],
      ["เสียง", (r) => L(r.noise_level)], ["อัปเดตรูป", (r) => yesno(r.photos_updated)], ["บรีฟพนักงาน", (r) => yesno(r.staff_briefed)],
      ["ผู้ตรวจ", (r) => esc(r.inspector)], ["หมายเหตุ", (r) => esc(r.notes)]],
    fields: [["venue_id", "สถานที่", ref("venues", (v) => v.name)], ["checked_at", "วันที่ตรวจ", "date"], ["wifi_mbps", "Wi-fi ที่วัดได้ (Mbps)", "number"],
      ["noise_level", "ระดับเสียง", "enum"], ["photos_updated", "อัปเดตรูปแล้ว", "bool"], ["staff_briefed", "บรีฟพนักงานแล้ว", "bool"],
      ["inspector", "ผู้ตรวจ", "text"], ["notes", "หมายเหตุ", "textarea"]],
    readonly: true,
  },
  finance: { title: "การเงินและส่วนแบ่งร้าน" },
};

let current = "dashboard";
function renderNav() {
  $("#nav").innerHTML = Object.entries(SCREENS).map(([k, s]) => `<a data-k="${k}" class="${k === current ? "active" : ""}">${s.title}</a>`).join("");
  $("#nav").querySelectorAll("a").forEach((a) => (a.onclick = () => go(a.dataset.k)));
}
async function go(k) {
  if (k !== current) tableState = { q: "", f: "" };
  current = k; location.hash = k; renderNav();
  const s = SCREENS[k];
  $("#page-title").textContent = s.title;
  $("#add-btn").hidden = !s.table;
  $("#content").innerHTML = '<p class="muted">กำลังโหลด…</p>';
  try {
    if (k === "dashboard") await renderDashboard();
    else if (k === "finance") await renderFinance();
    else await renderTable(s);
  } catch (e) { $("#content").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
}

function kpi(label, value) { return `<div class="kpi"><div class="label">${label}</div><div class="value">${value}</div></div>`; }
function bars(list, key, labelFn, valFn = (r) => r.count) {
  const max = Math.max(1, ...list.map(valFn));
  return `<table>${list.map((r) => `<tr><td>${esc(labelFn(r))}</td><td style="width:55%"><div class="bar" style="width:${(valFn(r) / max) * 100}%"></div></td><td class="num">${valFn(r)}</td></tr>`).join("") || '<tr><td class="muted">ไม่มีข้อมูล</td></tr>'}</table>`;
}
async function renderDashboard() {
  const d = await api("dashboard"); const k = d.kpis;
  $("#content").innerHTML = `
  <div class="kpis">
    ${kpi("ยอดจองรวม (GMV)", baht(k.gross_revenue))}${kpi("รายได้ค่าคอมมิชชัน", baht(k.commission_revenue))}
    ${kpi("ส่วนลดโปรฯ 2 ชม.แรกฟรี", baht(k.promo_discount))}${kpi("การจองวันนี้", k.bookings_today)}
    ${kpi("ลูกค้าทั้งหมด", k.customers)}${kpi("อัตราลูกค้ากลับมาจองซ้ำ", k.repeat_customer_rate + "%")}
    ${kpi("สถานที่ Verified", `${k.verified_venues} / ${k.active_venues}`)}${kpi("เรื่องร้องเรียนรอตอบ", k.open_issues)}
    ${kpi("อัตราการตอบรีวิว", k.response_rate + "%")}${kpi("คะแนนเฉลี่ย", k.avg_rating ?? "—")}
    ${kpi("โต๊ะไม่พร้อมเมื่อมาถึง", k.desk_not_ready_rate + "%")}
  </div>
  <div class="grid2">
    <div class="card"><h3>ยอดจองตามสถานที่</h3>${bars(d.revenue_by_venue, "gross", (r) => r.name, (r) => r.gross)}</div>
    <div class="card"><h3>ข้อร้องเรียนตามหมวด</h3>${bars(d.issues_by_category, "count", (r) => L(r.category))}</div>
    <div class="card"><h3>ลูกค้าตามช่องทางที่รู้จัก</h3>${bars(d.customers_by_channel, "count", (r) => L(r.channel))}</div>
    <div class="card"><h3>สถานที่ที่ต้องตรวจซ้ำ (เกิน 30 วัน)</h3>
      ${d.verification_due.length ? `<table>${d.verification_due.map((v) => `<tr><td>${esc(v.name)}</td><td class="num muted">${v.last_verified || "ยังไม่เคยตรวจ"}</td></tr>`).join("")}</table>` : '<p class="muted">ทุกสถานที่ผ่านการตรวจแล้ว 👍</p>'}</div>
  </div>`;
}
async function renderFinance() {
  const d = await api("dashboard"); const r = d.revenue_by_venue;
  const sum = (k) => r.reduce((a, x) => a + x[k], 0);
  $("#content").innerHTML = `<div class="table-wrap"><table><thead><tr><th>สถานที่</th><th class="num">จำนวนจอง</th><th class="num">ชั่วโมง</th>
    <th class="num">ยอดจอง</th><th class="num">ค่าคอม %</th><th class="num">รายได้ DeskHop</th><th class="num">โอนให้ร้าน</th></tr></thead><tbody>
    ${r.map((x) => `<tr><td>${esc(x.name)}</td><td class="num">${x.bookings}</td><td class="num">${x.hours}</td><td class="num">${baht(x.gross)}</td>
      <td class="num">${x.commission_pct}%</td><td class="num">${baht(x.commission)}</td><td class="num">${baht(x.payout)}</td></tr>`).join("")}
    <tr><td><b>รวม</b></td><td class="num"><b>${sum("bookings")}</b></td><td class="num"><b>${sum("hours")}</b></td><td class="num"><b>${baht(sum("gross"))}</b></td><td></td>
      <td class="num"><b>${baht(sum("commission"))}</b></td><td class="num"><b>${baht(sum("payout"))}</b></td></tr></tbody></table></div>
    <p class="muted">นับเฉพาะการจองสถานะ ยืนยันแล้ว / เช็กอินแล้ว / เสร็จสิ้น</p>`;
}

let tableState = { q: "", f: "" };
async function renderTable(s) {
  const data = await api(s.table); cache[s.table] = data;
  const filterHtml = s.filter ? `<select id="f"><option value="">ทุกสถานะ</option>${(META.enums[s.filter.enum] || []).map((v) => `<option value="${v}" ${tableState.f === v ? "selected" : ""}>${L(v)}</option>`).join("")}</select>` : "";
  $("#content").innerHTML = `<div class="toolbar"><input id="q" placeholder="ค้นหา…" value="${esc(tableState.q)}">${filterHtml}</div>
    <div class="table-wrap"><table><thead><tr>${s.columns.map((c) => `<th class="${c[2] || ""}">${c[0]}</th>`).join("")}<th></th></tr></thead><tbody id="tb"></tbody></table></div>
    ${s.note ? `<p class="muted">${s.note}</p>` : ""}`;
  const draw = () => {
    const q = tableState.q.toLowerCase();
    const list = data.filter((r) => (!q || s.searchKeys.some((k) => String(r[k] ?? "").toLowerCase().includes(q))) && (!s.filter || !tableState.f || r[s.filter.key] === tableState.f));
    $("#tb").innerHTML = list.map((r) => `<tr>${s.columns.map((c) => `<td class="${c[2] || ""}">${c[1](r)}</td>`).join("")}
      <td>${(s.quick ? s.quick(r) : []).map((qk, i) => `<button class="btn sm" data-quick="${r.id}:${i}">${qk[0]}</button> `).join("")}
      ${s.readonly ? "" : `<button class="btn sm" data-edit="${r.id}">แก้ไข</button>`} <button class="btn sm danger" data-del="${r.id}">ลบ</button></td></tr>`).join("")
      || `<tr><td colspan="${s.columns.length + 1}" class="muted">ไม่พบข้อมูล</td></tr>`;
    $("#tb").querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => openForm(s, data.find((r) => r.id == b.dataset.edit))));
    $("#tb").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!confirm("ยืนยันการลบรายการนี้?")) return;
      try { await api(`${s.table}/${b.dataset.del}`, { method: "DELETE" }); toast("ลบแล้ว"); go(current); } catch (e) { alert(e.message); }
    }));
    $("#tb").querySelectorAll("[data-quick]").forEach((b) => (b.onclick = async () => {
      const [id, i] = b.dataset.quick.split(":"); const row = data.find((r) => r.id == id);
      try { await api(`${s.table}/${id}`, { method: "PUT", body: s.quick(row)[i][1] }); toast("อัปเดตแล้ว"); go(current); } catch (e) { alert(e.message); }
    }));
  };
  $("#q").oninput = (e) => { tableState.q = e.target.value; draw(); };
  if ($("#f")) $("#f").onchange = (e) => { tableState.f = e.target.value; draw(); };
  draw();
}

async function openForm(s, row) {
  const dlg = $("#dlg");
  $("#dlg-title").textContent = (row ? "แก้ไข" : "เพิ่ม") + s.title;
  $("#dlg-error").textContent = "";
  const parts = [];
  for (const [key, label, type] of s.fields) {
    const v = row ? row[key] ?? "" : "";
    let input;
    if (typeof type === "object" && type.type === "ref") {
      const opts = cache[type.table] || (cache[type.table] = await api(type.table));
      input = `<select name="${key}"><option value="">— เลือก —</option>${opts.map((o) => `<option value="${o.id}" ${o.id == v ? "selected" : ""}>${esc(type.label(o))}</option>`).join("")}</select>`;
    } else if (type === "enum") {
      const vals = META.enums[`${s.table}.${key}`] || [];
      input = `<select name="${key}">${row ? "" : '<option value="">(ค่าเริ่มต้น)</option>'}${vals.map((x) => `<option value="${x}" ${x === v ? "selected" : ""}>${L(x)}</option>`).join("")}</select>`;
    } else if (type === "bool") {
      input = `<select name="${key}"><option value="1" ${Number(v) || (!row && key === "active") ? "selected" : ""}>ใช่</option><option value="0" ${row && !Number(v) || (!row && key !== "active") ? "selected" : ""}>ไม่ใช่</option></select>`;
    } else if (type === "textarea") {
      input = `<textarea name="${key}" rows="3">${esc(v)}</textarea>`;
    } else {
      input = `<input name="${key}" type="${type}" ${type === "number" ? 'step="any"' : ""} value="${esc(v)}">`;
    }
    parts.push(`<label class="${type === "textarea" ? "full" : ""}">${label}${input}</label>`);
  }
  $("#dlg-fields").innerHTML = parts.join("");
  $("#dlg-form").onsubmit = async (e) => {
    e.preventDefault();
    const body = {};
    new FormData(e.target).forEach((val, k) => { if (val !== "" || row) body[k] = val; });
    try {
      await api(row ? `${s.table}/${row.id}` : s.table, { method: row ? "PUT" : "POST", body });
      dlg.close(); toast("บันทึกแล้ว");
      Object.keys(cache).forEach((k) => delete cache[k]);
      go(current);
    } catch (err) { $("#dlg-error").textContent = err.message; }
  };
  dlg.showModal();
}
$("#dlg-cancel").onclick = () => $("#dlg").close();
$("#add-btn").onclick = () => openForm(SCREENS[current]);

(async () => {
  META = await api("meta");
  const h = location.hash.slice(1);
  go(SCREENS[h] ? h : "dashboard");
})();
window.addEventListener("hashchange", () => {
  const h = location.hash.slice(1);
  if (SCREENS[h] && h !== current) go(h);
});
