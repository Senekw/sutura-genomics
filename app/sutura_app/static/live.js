"use strict";
// Live alignment view. Connects to the CLI's real pipeline over SSE and animates
// each stage. The before->after motion uses the ACTUAL moving-spot coordinates
// and the ACTUAL aligned output — the animation illustrates the real result.

const PURPLE = "#b78bff", PURPLE_HI = "#d9c4ff", DIMSPOT = "#585070";
const STAGES = [
  ["load", "Load sections"], ["qc", "Quality control"], ["route", "Routing"],
  ["align", "Alignment"], ["postqc", "Post-QC"],
  ["reconstruct", "3D reconstruction"], ["report", "Report"],
];

const $ = (id) => document.getElementById(id);
const stagesEl = $("stages"), pairsEl = $("pairs"), sumEl = $("summary");
const titleEl = $("title"), instrEl = $("instr"), capEl = $("caption"), legendEl = $("legend");

let stageState = {};          // key -> "active"|"done"|"error"
let curStageSub = {};
let mode = "idle";            // idle | align | done3d
let anim = null;              // current pair animation
let recon = null;             // final reconstruction points
let nPairs = 0;
let activeStage = null;       // current active stage key (for heartbeat/error)
let finished = false;         // done or errored — stop heartbeat chatter

// ---- timeline ----------------------------------------------------------- //
function renderStages() {
  stagesEl.innerHTML = STAGES.map(([k, label]) => {
    const st = stageState[k] || "";
    const sub = curStageSub[k] ? `<div class="sub">${esc(curStageSub[k])}</div>` : "";
    return `<div class="stage ${st}"><div class="dot"></div>
      <div><div class="lbl">${label}</div>${sub}</div></div>`;
  }).join("");
}
function setStage(k, state, sub) {
  if (state === "active") { for (const s in stageState) if (stageState[s] === "active") stageState[s] = "done"; activeStage = k; }
  stageState[k] = state;
  if (sub !== undefined) curStageSub[k] = sub;
  renderStages();
}

// ---- SSE ---------------------------------------------------------------- //
function connect() {
  const es = new EventSource("/api/live/stream");
  es.onmessage = (e) => { try { dispatch(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => {};
}

function dispatch(m) {
  switch (m.type) {
    case "start":
      titleEl.textContent = "Aligning your sections…";
      instrEl.textContent = m.instruction || "";
      break;
    case "stage":
      if (m.phase === "start") setStage(m.stage, "active", m.detail || "");
      else setStage(m.stage, "done", m.summary || "");
      if (m.stage === "load" && m.phase === "done") caption(m.summary || "");
      break;
    case "progress":
      curStageSub[m.stage] = `${m.message} ${m.pct}%`; renderStages(); break;
    case "routing":
      caption(`Routing <span class="m">${esc(m.pair)}</span> — chose ` +
              `<span class="m">${esc(m.method)}</span> ` +
              `<span style="color:var(--dim)">(${m.in_distribution ? "in" : "off"}-distribution, ` +
              `Mahalanobis ${m.mahalanobis})</span>`);
      break;
    case "pair":
      nPairs++; addPair(m);
      if (m.geom) startAnim(m); break;
    case "heartbeat":
      // liveness on a slow/stalled stage: the align canvas already animates, so
      // only surface a keepalive when nothing else is moving.
      if (!finished && mode !== "align" && m.idle >= 5) {
        const label = (STAGES.find(s => s[0] === m.stage) || [,"working"])[1];
        caption(`<span style="color:var(--dim)">still working — ${esc(label)} · ` +
                `${m.elapsed}s elapsed</span>`);
      }
      break;
    case "done":
      finished = true; finish(m); break;
    case "error":
      finished = true;
      if (activeStage && stageState[activeStage] !== "done") setStage(activeStage, "error");
      titleEl.textContent = "Live run interrupted";
      caption(`<span style="color:var(--bad)">✗ ${esc(m.text)}</span>`);
      break;
    case "end":
      // stream closed. if it ended without a clean 'done' and no error was
      // shown, say so rather than leaving the last stage spinning forever.
      if (!finished && m.status && m.status !== "complete") {
        finished = true;
        if (activeStage && stageState[activeStage] !== "done") setStage(activeStage, "error");
        caption(`<span style="color:var(--bad)">✗ run ended without completing (${esc(m.status)})</span>`);
      }
      break;
  }
}

function caption(html) { capEl.innerHTML = html; }

// ---- pairs panel -------------------------------------------------------- //
function addPair(m) {
  const err = m.has_ground_truth ? `${m.score.toFixed(2)} spot-pitch`
                                 : `${m.score.toFixed(2)} coverage`;
  const route = m.in_distribution == null ? "forced"
    : `${m.in_distribution ? "in" : "off"}-dist${m.mahalanobis != null ? " · maha " + m.mahalanobis : ""}`;
  document.querySelectorAll(".pair.cur").forEach(e => e.classList.remove("cur"));
  const div = document.createElement("div");
  div.className = "pair cur";
  div.innerHTML =
    `<div class="p">${esc(short(m.ref))} → ${esc(short(m.mov))}<span class="badge">${route}</span></div>
     <div class="row"><span class="method">${esc(m.method)}</span>
       <span class="err">${err} <span class="qc-${m.verdict}">· ${m.verdict}</span></span></div>`;
  pairsEl.appendChild(div);
  $("side").scrollTop = $("side").scrollHeight;
}

// ---- canvas ------------------------------------------------------------- //
const cv = $("stage"), ctx = cv.getContext("2d");
let W = 0, H = 0, DPR = Math.min(devicePixelRatio || 1, 2);
function resize() {
  const r = cv.parentElement.getBoundingClientRect();
  W = r.width; H = r.height; cv.width = W * DPR; cv.height = H * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
addEventListener("resize", resize);

function bounds(...sets) {
  let mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;
  for (const s of sets) for (const p of s) {
    mnx = Math.min(mnx, p[0]); mxx = Math.max(mxx, p[0]);
    mny = Math.min(mny, p[1]); mxy = Math.max(mxy, p[1]);
  }
  return { cx: (mnx + mxx) / 2, cy: (mny + mxy) / 2,
           span: Math.max(mxx - mnx, mxy - mny) || 1 };
}

function startAnim(m) {
  mode = "align";
  const g = m.geom;
  const b = bounds(g.ref, g.mov, g.aligned);
  anim = { g, b, t0: performance.now(), dur: 2200, method: m.method,
           err: m.has_ground_truth ? `${m.score.toFixed(2)} spot-pitch median error`
                                    : `${m.score.toFixed(2)} coverage`,
           verdict: m.verdict, ref: m.ref, mov: m.mov, held: false };
}

function project(b, x, y) {
  const s = Math.min(W, H) * 0.8 / b.span;
  return [W / 2 + (x - b.cx) * s, H / 2 - (y - b.cy) * s];
}
const easeInOut = (t) => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

function drawAlign(now) {
  const a = anim; if (!a) return;
  let t = (now - a.t0) / a.dur;
  let done = t >= 1; if (done) t = 1;
  const e = easeInOut(t);
  ctx.clearRect(0, 0, W, H);
  // reference spots (static, dim)
  ctx.fillStyle = DIMSPOT; ctx.globalAlpha = 0.5;
  for (const p of a.g.ref) { const [x, y] = project(a.b, p[0], p[1]);
    ctx.beginPath(); ctx.arc(x, y, 1.5, 0, 6.283); ctx.fill(); }
  // moving spots: lerp from torn (mov) -> aligned
  ctx.globalAlpha = 0.92;
  for (let i = 0; i < a.g.mov.length; i++) {
    const m = a.g.mov[i], al = a.g.aligned[i];
    const [x, y] = project(a.b, m[0] + (al[0] - m[0]) * e, m[1] + (al[1] - m[1]) * e);
    ctx.fillStyle = PURPLE; ctx.beginPath(); ctx.arc(x, y, 1.7, 0, 6.283); ctx.fill();
  }
  ctx.globalAlpha = 1;
  if (done) {
    caption(`<span class="m">${esc(a.method)}</span> — ` +
            `<span class="e">${a.err}</span> · ${a.verdict}   ` +
            `<span style="color:var(--dim)">${esc(short(a.ref))} → ${esc(short(a.mov))}</span>`);
    legendEl.innerHTML =
      `<div class="i"><span class="sw" style="background:${DIMSPOT}"></span>reference section</div>
       <div class="i"><span class="sw" style="background:${PURPLE}"></span>moving section (spots animate torn → aligned)</div>`;
  } else {
    caption(`Aligning <span style="color:var(--dim)">${esc(short(a.ref))} → ${esc(short(a.mov))}</span> with ` +
            `<span class="m">${esc(a.method)}</span>… <span style="color:var(--dim)">${Math.round(t * 100)}%</span>`);
  }
}

// final 3D volume (real reconstruction points), rotating
let ang = 0.5, tilt = 0.5;
function draw3d() {
  if (!recon || !recon.points || !recon.points.length) return;
  const P = recon.points;
  let mnx=1e9,mxx=-1e9,mny=1e9,mxy=-1e9,mnz=1e9,mxz=-1e9;
  for (const p of P){mnx=Math.min(mnx,p[0]);mxx=Math.max(mxx,p[0]);mny=Math.min(mny,p[1]);mxy=Math.max(mxy,p[1]);mnz=Math.min(mnz,p[2]);mxz=Math.max(mxz,p[2]);}
  const cx=(mnx+mxx)/2,cy=(mny+mxy)/2,cz=(mnz+mxz)/2;
  const spanXY=Math.max(mxx-mnx,mxy-mny)||1, spanZ=(mxz-mnz)||1;
  ang += 0.006;
  const cA=Math.cos(ang),sA=Math.sin(ang),cT=Math.cos(tilt),sT=Math.sin(tilt);
  const R=Math.min(W,H)*0.4, ox=W/2, oy=H/2;
  const pts=[];
  for (const p of P){
    const x=(p[0]-cx)/spanXY*1.7, y=-(p[1]-cy)/spanXY*1.7, z=(p[2]-cz)/spanZ*0.75;
    const x1=x*cA+z*sA, z1=-x*sA+z*cA;
    const y2=y*cT-z1*sT, z2=y*sT+z1*cT;
    const persp=3.4/(3.4-z2);
    pts.push([ox+x1*persp*R, oy+y2*persp*R, z2, persp]);
  }
  pts.sort((a,b)=>a[2]-b[2]);
  ctx.clearRect(0,0,W,H);
  for (const q of pts){
    const d=q[2]+0.5;
    ctx.globalAlpha=Math.max(0.3,Math.min(0.95,0.5+d*0.5));
    // depth-shaded purple: deeper = whiter
    const t=Math.max(0,Math.min(1,(q[2]+0.4)/0.8));
    ctx.fillStyle=`rgb(${Math.round(140+90*t)},${Math.round(110+120*t)},255)`;
    ctx.beginPath(); ctx.arc(q[0],q[1],Math.max(0.8,1.6*q[3]),0,6.283); ctx.fill();
  }
  ctx.globalAlpha=1;
}

function loop() {
  requestAnimationFrame(loop);
  const now = performance.now();
  if (mode === "align") drawAlign(now);
  else if (mode === "done3d") draw3d();
  else idle();
}
function idle() { ctx.clearRect(0,0,W,H); }

// ---- finish ------------------------------------------------------------- //
async function finish(m) {
  const s = m.summary || {};
  titleEl.textContent = "Alignment complete";
  // fetch the real composed reconstruction for the final rotating volume
  if (m.job_id) {
    try {
      const run = await fetch("/api/runs/" + encodeURIComponent(m.job_id)).then(r => r.json());
      recon = run.reconstruction;
    } catch (_) {}
  }
  mode = recon && recon.points && recon.points.length ? "done3d" : mode;
  caption(`<span class="m">Done.</span> ${s.n_pairs || nPairs} pair(s) aligned · ` +
          `${(s.n_points || 0).toLocaleString()} points in the 3D volume`);
  legendEl.innerHTML =
    `<div class="i"><span class="sw" style="background:${PURPLE}"></span>aligned 3D volume — drag is optional; rotating the real reconstruction</div>`;
  const methods = (s.methods || []).map(x => `<span class="method">${esc(x)}</span>`).join("  ");
  sumEl.classList.remove("hidden");
  sumEl.innerHTML =
    `<div class="stat"><span>sections</span><b>${s.n_sections || ""}</b></div>
     <div class="stat"><span>pairs</span><b>${s.n_pairs || nPairs}</b></div>
     <div class="stat"><span>3D points</span><b>${(s.n_points || 0).toLocaleString()}</b></div>
     <div class="stat"><span>composition</span><b>${(s.composition || "").replace(/_/g," ")}</b></div>
     <div class="stat"><span>methods</span></div><div>${methods}</div>
     <div class="cta">▶ real result — final positions & metrics come from the actual pipeline</div>`;
  for (const [k] of STAGES) if (stageState[k] !== "done") stageState[k] = "done";
  renderStages();
}

// ---- drag to rotate the final volume ------------------------------------ //
let drag=false, px=0, py=0;
cv.addEventListener("pointerdown", e=>{drag=true;px=e.clientX;py=e.clientY;});
addEventListener("pointerup", ()=>drag=false);
addEventListener("pointermove", e=>{ if(!drag||mode!=="done3d")return;
  ang+=(e.clientX-px)*0.008; tilt=Math.max(-1.3,Math.min(1.3,tilt+(e.clientY-py)*0.006));
  px=e.clientX; py=e.clientY; });

// ---- utils -------------------------------------------------------------- //
function short(s){ return String(s).replace(/^DLPFC_/,""); }
function esc(s){ return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }

renderStages(); resize(); loop(); connect();
