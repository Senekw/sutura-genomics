import * as THREE from "/vendor/three.module.min.js";

// ---- palette (reused from the Sutura web demo) --------------------------- //
const LAYERS = ["Layer1", "Layer2", "Layer3", "Layer4", "Layer5", "Layer6", "WM"];
const LAYER_COLORS = ["#8ecae6", "#219ebc", "#4cc9f0", "#90be6d", "#f9c74f",
                      "#f8961e", "#e63946"];
const SECTION_COLORS = ["#a78bfa", "#6ee7ff", "#f472b6", "#4ade80", "#fbbf24",
                        "#60a5fa", "#fb7185", "#34d399"];
const NA = "#5a5a6e";

function layerColor(l) {
  const i = LAYERS.indexOf(l);
  return i >= 0 ? LAYER_COLORS[i] : NA;
}
function sectionColor(i) { return SECTION_COLORS[i % SECTION_COLORS.length]; }
function methodColor(m) {
  if (!m) return NA;
  if (/paste/i.test(m)) return "#6ee7ff";
  if (/sutura|graph/i.test(m)) return "#a78bfa";
  if (/reference/i.test(m)) return "#9a9ab0";
  return NA;
}

// ---- state --------------------------------------------------------------- //
let currentRun = null;
let viewer = null;

// ---- run list ------------------------------------------------------------ //
async function loadRuns() {
  const r = await fetch("/api/runs").then((x) => x.json());
  document.getElementById("store-line").textContent = "store: " + r.store;
  const list = document.getElementById("run-list");
  list.innerHTML = "";
  if (!r.runs.length) {
    document.getElementById("empty-hint").textContent =
      "No runs found in " + r.store + ". Produce one with the Sutura CLI: " +
      'sutura -H "align ./data and reconstruct in 3D".';
    return;
  }
  for (const run of r.runs) {
    const el = document.createElement("div");
    el.className = "run-item";
    el.dataset.id = run.job_id;
    const when = (run.created_utc || "").replace("T", " ").replace("+00:00", "");
    el.innerHTML =
      `<div class="rid">${run.n_sections} sections · ${run.n_pairs} pair(s)</div>
       <div class="rsub">${run.job_id}</div>
       <div class="rsub">${when} · ${run.status || ""}</div>
       <div class="rmethods">${(run.methods || [])
         .map((m) => `<span class="badge method">${esc(m)}</span>`).join("")}</div>`;
    el.onclick = () => selectRun(run.job_id, el);
    list.appendChild(el);
  }
}

async function selectRun(jobId, el) {
  document.querySelectorAll(".run-item").forEach((x) => x.classList.remove("active"));
  if (el) el.classList.add("active");
  const run = await fetch("/api/runs/" + encodeURIComponent(jobId)).then((x) => x.json());
  currentRun = run;
  renderRun(run);
}

// ---- render one run ------------------------------------------------------ //
function renderRun(run) {
  document.getElementById("empty").classList.add("hidden");
  document.getElementById("run-view").classList.remove("hidden");
  const m = run.metadata || {};
  const pairs = (run.metrics || {}).pairs || m.pairs || [];
  const rec = run.reconstruction || {};

  document.getElementById("run-title").textContent = m.job_id || "run";
  document.getElementById("run-meta").textContent =
    `${(m.instruction || "").slice(0, 90)}  ·  backend ${m.backend || "?"}`;

  const badges = [];
  badges.push(`<span class="badge status-${m.status}">${m.status || ""}</span>`);
  for (const meth of runMethods(pairs))
    badges.push(`<span class="badge method">${esc(meth)}</span>`);
  document.getElementById("run-badges").innerHTML = badges.join("");

  // summary stats
  document.getElementById("summary-cards").innerHTML = [
    stat(m.sections ? m.sections.length : 0, "sections"),
    stat(pairs.length, "pairs"),
    stat(rec.n_points || 0, "3D points"),
  ].join("");

  renderPairs(pairs);
  renderCandidates(pairs);
  renderQC(run.qc || {});
  document.getElementById("report").textContent = run.report_md || "(no report)";
  document.getElementById("recon-note").textContent = rec.note ? "3D: " + rec.note : "";

  // 3D
  if (!viewer) viewer = makeViewer(document.getElementById("viewer"));
  viewer.setData(rec);
  renderLegend(rec, document.getElementById("color-mode").value);
}

function runMethods(pairs) {
  return [...new Set(pairs.map((p) => p.method_label || p.method))];
}

function stat(v, k) {
  return `<div class="stat"><div class="v">${v}</div><div class="k">${k}</div></div>`;
}

function renderPairs(pairs) {
  let h = `<table><thead><tr><th>Pair</th><th>Method</th><th>Result</th>
           <th>QC</th></tr></thead><tbody>`;
  for (const p of pairs) {
    const score = p.has_ground_truth
      ? `${fmt(p.score)} spot-pitch err` : `${fmt(p.score)} coverage`;
    const verdict = (p.post_qc || {}).verdict || "-";
    h += `<tr>
      <td>${esc(p.ref)} → ${esc(p.mov)}<div class="why">${esc(p.reason || "")}</div></td>
      <td class="method">${esc(p.method_label || p.method)}</td>
      <td>${score}</td>
      <td class="verdict-${verdict}">${verdict}</td></tr>`;
  }
  document.getElementById("pairs-table").innerHTML = h + "</tbody></table>";
}

function renderCandidates(pairs) {
  // show the comparison only when at least one pair compared >= 2 methods
  const rows = [];
  for (const p of pairs) {
    const cands = (p.candidates || []).filter(
      ([n]) => ["sutura", "sutura_zeroshot", "sutura_adapted", "paste2"].includes(n));
    if (cands.length < 2) continue;
    const lower = p.has_ground_truth !== false;
    const best = cands.reduce((a, b) => (lower ? b[1] < a[1] : b[1] > a[1]) ? b : a)[0];
    const cells = cands.map(([n, v]) =>
      `${CAND_LABEL[n]} ${fmt(v)}${n === best ? ' <span class="kept">← kept</span>' : ""}`);
    rows.push(`<tr><td>${esc(p.ref)} → ${esc(p.mov)}</td><td>${cells.join(" · ")}</td></tr>`);
  }
  const card = document.getElementById("candidates-card");
  if (!rows.length) {
    card.classList.add("hidden");
    return;
  }
  card.classList.remove("hidden");
  document.getElementById("candidates-table").innerHTML =
    `<table><thead><tr><th>Pair</th><th>Methods compared (lower = better)</th>
     </tr></thead><tbody>${rows.join("")}</tbody></table>`;
}
const CAND_LABEL = { sutura: "Sutura", sutura_zeroshot: "Sutura (zero-shot)",
  sutura_adapted: "Sutura (adapted)", paste2: "PASTE2" };

function renderQC(qc) {
  const secs = qc.sections || [];
  let h = `<table><thead><tr><th>Section</th><th>Spots</th><th>Genes</th>
           <th>Layers</th><th>QC</th></tr></thead><tbody>`;
  for (const s of secs) {
    h += `<tr><td>${esc(s.name)}</td><td>${s.n_spots}</td><td>${s.n_genes}</td>
      <td>${s.has_layers ? "yes" : "no"}</td>
      <td class="${s.pass ? "pass" : "fail"}">${s.pass ? "pass" : "fail"}
      ${s.issue ? "· " + esc(s.issue) : ""}</td></tr>`;
  }
  document.getElementById("qc-table").innerHTML = h + "</tbody></table>";
}

function renderLegend(rec, mode) {
  const el = document.getElementById("legend");
  const items = [];
  if (mode === "layer") {
    const present = new Set();
    for (const p of rec.points || []) present.add(p[4]);
    for (const l of LAYERS) if (present.has(l)) items.push([l, layerColor(l)]);
    if (present.has("NA")) items.push(["NA", NA]);
  } else if (mode === "section") {
    for (const s of rec.sections || []) items.push([s.name, sectionColor(s.index)]);
  } else {
    const seen = new Map();
    for (const s of rec.sections || []) seen.set(s.method, methodColor(s.method));
    for (const [k, v] of seen) items.push([k, v]);
  }
  el.innerHTML = items.map(([name, c]) =>
    `<div class="item"><span class="swatch" style="background:${c}"></span>${esc(name)}</div>`
  ).join("");
}

// ---- three.js viewer ----------------------------------------------------- //
function makeViewer(container) {
  const w = container.clientWidth, h = container.clientHeight || 420;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100);
  camera.position.set(0, 0, 3.4);
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(w, h);
  container.innerHTML = "";
  container.appendChild(renderer.domElement);

  const group = new THREE.Group();
  scene.add(group);
  let points = null, rec = null;
  let yaw = 0.5, pitch = -0.35, autov = 0.0025, dragging = false, autorotate = true;

  function setData(reconstruction) {
    rec = reconstruction;
    if (points) { group.remove(points); points.geometry.dispose(); }
    const pts = (rec && rec.points) || [];
    if (!pts.length) { points = null; return; }
    const n = pts.length;
    const pos = new Float32Array(n * 3);
    let cx = 0, cy = 0, cz = 0, mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9,
        mnz = 1e9, mxz = -1e9;
    for (const p of pts) {
      mnx = Math.min(mnx, p[0]); mxx = Math.max(mxx, p[0]);
      mny = Math.min(mny, p[1]); mxy = Math.max(mxy, p[1]);
      mnz = Math.min(mnz, p[2]); mxz = Math.max(mxz, p[2]);
    }
    cx = (mnx + mxx) / 2; cy = (mny + mxy) / 2; cz = (mnz + mxz) / 2;
    const span = Math.max(mxx - mnx, mxy - mny, mxz - mnz) || 1;
    const s = 2.0 / span;
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (pts[i][0] - cx) * s;
      pos[i * 3 + 1] = -(pts[i][1] - cy) * s;   // flip y (image coords)
      pos[i * 3 + 2] = (pts[i][2] - cz) * s;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    const mat = new THREE.PointsMaterial({ size: 0.02, vertexColors: true,
      sizeAttenuation: true });
    points = new THREE.Points(geo, mat);
    group.add(points);
    recolor(document.getElementById("color-mode").value);
    yaw = 0.5; pitch = -0.35; camera.position.z = 3.4;
  }

  function recolor(mode) {
    if (!points || !rec) return;
    const pts = rec.points, col = points.geometry.getAttribute("color");
    for (let i = 0; i < pts.length; i++) {
      let hex;
      if (mode === "layer") hex = layerColor(pts[i][4]);
      else if (mode === "section") hex = sectionColor(pts[i][3]);
      else hex = methodColor((rec.sections[pts[i][3]] || {}).method);
      const c = new THREE.Color(hex);
      col.setXYZ(i, c.r, c.g, c.b);
    }
    col.needsUpdate = true;
  }

  // interaction
  const el = renderer.domElement;
  let px = 0, py = 0;
  el.addEventListener("pointerdown", (e) => { dragging = true; autorotate = false;
    px = e.clientX; py = e.clientY; el.setPointerCapture(e.pointerId); });
  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    yaw += (e.clientX - px) * 0.008; pitch += (e.clientY - py) * 0.008;
    pitch = Math.max(-1.4, Math.min(1.4, pitch)); px = e.clientX; py = e.clientY;
  });
  el.addEventListener("pointerup", () => { dragging = false; });
  el.addEventListener("wheel", (e) => { e.preventDefault();
    camera.position.z = Math.max(1.2, Math.min(8, camera.position.z + e.deltaY * 0.002));
  }, { passive: false });

  function resize() {
    const W = container.clientWidth, H = container.clientHeight || 420;
    camera.aspect = W / H; camera.updateProjectionMatrix(); renderer.setSize(W, H);
  }
  window.addEventListener("resize", resize);

  (function loop() {
    requestAnimationFrame(loop);
    if (autorotate) yaw += autov;
    group.rotation.y = yaw; group.rotation.x = pitch;
    renderer.render(scene, camera);
  })();

  return {
    setData, recolor,
    resetView() { yaw = 0.5; pitch = -0.35; camera.position.z = 3.4; autorotate = true; },
  };
}

// ---- chat ---------------------------------------------------------------- //
function initChat() {
  const toggle = document.getElementById("chat-toggle");
  const panel = document.getElementById("chat");
  toggle.onclick = () => { panel.classList.remove("hidden"); toggle.classList.add("hidden");
    if (!panel.dataset.greeted) { botMsg("Ask me about this run — the method used and "
      + "why, the metrics, or how PASTE2 compares. I only use this run's data.");
      panel.dataset.greeted = "1"; } };
  document.getElementById("chat-close").onclick = () => {
    panel.classList.add("hidden"); toggle.classList.remove("hidden"); };
  document.getElementById("chat-form").onsubmit = async (e) => {
    e.preventDefault();
    const inp = document.getElementById("chat-input");
    const q = inp.value.trim(); if (!q) return;
    if (!currentRun) { botMsg("Open a run first."); return; }
    userMsg(q); inp.value = "";
    const typing = botMsg("…");
    try {
      const r = await fetch("/api/chat", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: currentRun.metadata.job_id, question: q }) })
        .then((x) => x.json());
      typing.querySelector(".txt").textContent = r.text || r.error || "(no answer)";
      if (r.source) typing.querySelector(".src").textContent = "source: " + r.source;
    } catch (err) { typing.querySelector(".txt").textContent = "error: " + err; }
  };
}
function userMsg(t) { const d = mk("user"); d.querySelector(".txt").textContent = t;
  return d; }
function botMsg(t) { const d = mk("bot"); d.querySelector(".txt").textContent = t;
  return d; }
function mk(kind) {
  const log = document.getElementById("chat-log");
  const d = document.createElement("div"); d.className = "msg " + kind;
  d.innerHTML = `<div class="txt"></div>${kind === "bot" ? '<div class="src"></div>' : ""}`;
  log.appendChild(d); log.scrollTop = log.scrollHeight; return d;
}

// ---- utils --------------------------------------------------------------- //
function esc(s) { return String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function fmt(v) { return typeof v === "number" ? v.toFixed(2) : v; }

// ---- boot ---------------------------------------------------------------- //
document.getElementById("color-mode").onchange = (e) => {
  if (viewer) viewer.recolor(e.target.value);
  if (currentRun) renderLegend(currentRun.reconstruction || {}, e.target.value);
};
document.getElementById("reset-view").onclick = () => viewer && viewer.resetView();
initChat();
loadRuns();
