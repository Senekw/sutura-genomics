/*
 * Sutura live-alignment UI: upload a pair (or stack) of .h5ad sections, poll the
 * async backend, render the aligned result in 3D, and transparently show which
 * method produced it + metrics + a download link.
 *
 * Additive component (does not modify the scripted demo in App.jsx). Point it at
 * the deployed backend with VITE_SUTURA_API (falls back to http://localhost:8000).
 * Mount via demo/align.html -> src/align-main.jsx, or import <Align/> into a route.
 */
import React, { useMemo, useRef, useState, useEffect } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

const API = import.meta.env?.VITE_SUTURA_API || "http://localhost:8000";

const METHOD_COPY = {
  sutura: ["Sutura", "Your data is in-distribution for our model — aligned with Sutura."],
  "sutura_zeroshot": ["Sutura (zero-shot)", "Aligned with the pretrained Sutura model."],
  "sutura_adapted": ["Sutura (auto-adapted to your data)",
    "Off-distribution input — we fine-tuned Sutura on your own sections, and this won."],
  paste2: ["PASTE2", "Off-distribution input — PASTE2 gave the best alignment on your data."],
};

function Points({ coords }) {
  const ref = useRef();
  const { positions, center, scale } = useMemo(() => {
    const n = coords.length;
    const xs = coords.map((c) => c[0]), ys = coords.map((c) => c[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs),
                          Math.max(...ys) - Math.min(...ys)) || 1;
    const s = 2.4 / span;
    const a = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      a[i * 3] = (coords[i][0] - cx) * s;
      a[i * 3 + 1] = -(coords[i][1] - cy) * s;
      a[i * 3 + 2] = 0;
    }
    return { positions: a, center: [cx, cy], scale: s };
  }, [coords]);

  useFrame((state) => {
    if (ref.current) ref.current.rotation.y = 0.5 * Math.sin(state.clock.elapsedTime * 0.3);
  });
  return (
    <group ref={ref}>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" count={positions.length / 3}
            array={positions} itemSize={3} />
        </bufferGeometry>
        <pointsMaterial size={0.02} color="#5ac8fa" sizeAttenuation />
      </points>
    </group>
  );
}

export default function Align() {
  const [files, setFiles] = useState([]);
  const [job, setJob] = useState(null);      // {id}
  const [status, setStatus] = useState(null); // poll payload
  const [error, setError] = useState(null);
  const [drag, setDrag] = useState(false);

  const onDrop = (e) => {
    e.preventDefault(); setDrag(false);
    const fs = [...e.dataTransfer.files].filter((f) => f.name.endsWith(".h5ad"));
    setFiles(fs); setError(fs.length ? null : "Please drop .h5ad Visium files.");
  };

  const submit = async () => {
    setError(null); setStatus(null); setJob(null);
    if (files.length < 2) { setError("Upload at least 2 sections (reference + moving)."); return; }
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    try {
      const r = await fetch(`${API}/api/align`, { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) { setError(j.detail || "Upload rejected."); return; }
      setJob({ id: j.job_id });
    } catch (e) { setError(`Could not reach the backend at ${API}. ${e}`); }
  };

  // poll while running
  useEffect(() => {
    if (!job) return;
    let live = true;
    const tick = async () => {
      try {
        const r = await fetch(`${API}/api/result/${job.id}`);
        const st = await r.json();
        if (!live) return;
        setStatus(st);
        if (st.status !== "done" && st.status !== "failed") setTimeout(tick, 2500);
        else if (st.status === "failed") setError(st.error || "Alignment failed.");
      } catch (e) { if (live) setError(`Lost connection to backend. ${e}`); }
    };
    tick();
    return () => { live = false; };
  }, [job]);

  const res = status?.status === "done" ? status.result : null;
  const [label, why] = res ? (METHOD_COPY[res.method] || [res.method_label, res.reason]) : [];

  return (
    <div className="align-wrap">
      <h1>Align your spatial data</h1>
      <p className="sub">Upload a pair of adjacent Visium sections (.h5ad). Add more
        sections from the same sample to enable auto-adaptation.</p>

      {!job && (
        <>
          <div className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)} onDrop={onDrop}
            onClick={() => document.getElementById("filepick").click()}>
            <input id="filepick" type="file" multiple accept=".h5ad" hidden
              onChange={(e) => setFiles([...e.target.files])} />
            {files.length
              ? <ul>{files.map((f) => <li key={f.name}>{f.name} ({(f.size/1e6).toFixed(0)} MB)</li>)}</ul>
              : <p>Drag &amp; drop .h5ad files here, or click to choose</p>}
          </div>
          <button className="btn primary" onClick={submit} disabled={files.length < 2}>
            Align →
          </button>
        </>
      )}

      {error && <div className="err">⚠ {error}</div>}

      {job && status && status.status !== "done" && status.status !== "failed" && (
        <div className="progress">
          <div className="bar"><div className="fill" style={{ width: `${status.progress || 5}%` }} /></div>
          <div className="stage">{status.status} — {status.stage} ({status.progress || 0}%)</div>
          <p className="hint">Alignment runs real inference and can take a few minutes.</p>
        </div>
      )}

      {res && (
        <div className="result">
          <div className={`method-banner ${res.method.startsWith("sutura") ? "sutura" : "paste2"}`}>
            <strong>Aligned using {label}</strong>
            <span>{why}</span>
          </div>
          <div className="viewer">
            <Canvas camera={{ position: [0, 0, 3.2], fov: 42 }}>
              <color attach="background" args={["#070b16"]} />
              <ambientLight intensity={0.9} />
              <Points coords={res.aligned_coords} />
            </Canvas>
          </div>
          <div className="metrics">
            <div><span className="k">Method</span><span className="v">{label}</span></div>
            <div><span className="k">In-distribution</span>
              <span className="v">{res.in_distribution ? "yes" : "no"} (conf {res.in_dist_confidence})</span></div>
            <div><span className="k">{res.has_ground_truth ? "Median error" : "Footprint coverage"}</span>
              <span className="v">{res.score}{res.has_ground_truth ? " spot-pitches" : ""}</span></div>
            <div><span className="k">Runtime</span><span className="v">{res.runtime_seconds}s</span></div>
            {res.retry && <div><span className="k">Auto-retry</span><span className="v">yes</span></div>}
          </div>
          <a className="btn primary" href={`${API}/api/download/${job.id}`}>
            Download aligned .h5ad
          </a>
          <button className="btn ghost" onClick={() => { setJob(null); setStatus(null); setFiles([]); }}>
            Align another
          </button>
        </div>
      )}
    </div>
  );
}
