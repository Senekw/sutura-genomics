import React, { useMemo, useRef, useState, useEffect, useLayoutEffect } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";
import data from "./data.json";

// render instance colors at their exact hex values (no linear/sRGB surprises)
THREE.ColorManagement.enabled = false;

const N = data.n;
const DISP = 1.35; // display scale
const ZSCALE = 3.0; // exaggerate slab depth so 3D reads
const COLORS = data.layerColors.map((c) => new THREE.Color(c));

// build a Float32 position array for a given state key
function statePositions(key) {
  const src = data[key];
  const z = data.z;
  const a = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    a[i * 3] = src[i][0] * DISP;
    a[i * 3 + 1] = -src[i][1] * DISP; // flip image-y
    a[i * 3 + 2] = z[i] * DISP * ZSCALE;
  }
  return a;
}

const STATE_POS = {
  clean: statePositions("clean"),
  torn: statePositions("torn"),
  paste2: statePositions("paste2"),
  sutura: statePositions("sutura"),
};

const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

function Tissue({ targetKey }) {
  const meshRef = useRef();
  const groupRef = useRef();
  const dummy = useMemo(() => new THREE.Object3D(), []);
  // live displayed positions (start clean)
  const cur = useRef(Float32Array.from(STATE_POS.clean));
  const from = useRef(Float32Array.from(STATE_POS.clean));
  const anim = useRef({ t: 1, key: targetKey });

  // per-instance colors, built once and attached declaratively so the buffer
  // exists at mount (otherwise the shader compiles without the color path)
  const colorArray = useMemo(() => {
    const c = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const col = COLORS[data.layer[i]];
      c[i * 3] = col.r;
      c[i * 3 + 1] = col.g;
      c[i * 3 + 2] = col.b;
    }
    return c;
  }, []);

  // assign per-instance colors before first paint
  useLayoutEffect(() => {
    const m = meshRef.current;
    if (!m) return;
    m.instanceColor = new THREE.InstancedBufferAttribute(colorArray, 3);
    m.instanceColor.needsUpdate = true;
    m.material.needsUpdate = true;
  }, [colorArray]);

  // when target changes, snapshot current as "from" and restart the morph
  useEffect(() => {
    from.current = Float32Array.from(cur.current);
    anim.current = { t: 0, key: targetKey };
  }, [targetKey]);

  useFrame((state, dt) => {
    const g = groupRef.current;
    const m = meshRef.current;
    if (!m) return;
    // gentle oscillation — shows 3D depth without ever going edge-on
    const tt = state.clock.elapsedTime;
    if (g) {
      g.rotation.y = 0.6 * Math.sin(tt * 0.32);
      g.rotation.x = -0.45 + 0.12 * Math.sin(tt * 0.24);
    }

    const a = anim.current;
    if (a.t < 1) {
      a.t = Math.min(1, a.t + dt / 1.25);
      const e = easeInOut(a.t);
      const tgt = STATE_POS[a.key];
      const c = cur.current;
      const f = from.current;
      for (let i = 0; i < N * 3; i++) c[i] = f[i] + (tgt[i] - f[i]) * e;
      for (let i = 0; i < N; i++) {
        dummy.position.set(c[i * 3], c[i * 3 + 1], c[i * 3 + 2]);
        dummy.updateMatrix();
        m.setMatrixAt(i, dummy.matrix);
      }
      m.instanceMatrix.needsUpdate = true;
    }
  });

  // initial matrices
  useEffect(() => {
    const m = meshRef.current;
    if (!m) return;
    const c = cur.current;
    for (let i = 0; i < N; i++) {
      dummy.position.set(c[i * 3], c[i * 3 + 1], c[i * 3 + 2]);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
  }, []);

  return (
    <group ref={groupRef}>
      <instancedMesh ref={meshRef} args={[undefined, undefined, N]}>
        <sphereGeometry args={[0.015, 10, 10]} />
        <meshLambertMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

function Scene({ targetKey }) {
  return (
    <Canvas camera={{ position: [0, 0, 3.1], fov: 42 }} dpr={[1, 2]}>
      <color attach="background" args={["#070b16"]} />
      <fog attach="fog" args={["#070b16", 3.2, 6.5]} />
      <ambientLight intensity={0.95} />
      <directionalLight position={[3, 4, 5]} intensity={0.5} />
      <directionalLight position={[-4, -2, 2]} intensity={0.25} color="#8fd4ff" />
      <Tissue targetKey={targetKey} />
    </Canvas>
  );
}

const STEPS = [
  {
    key: "clean",
    kicker: "Real DLPFC tissue",
    title: "Human cortex, mapped in 3D",
    body: `${N.toLocaleString()} real Visium spots from a DLPFC section, colored by cortical layer (L1–L6, white matter).`,
    button: "Simulate a tear",
  },
  {
    key: "torn",
    kicker: "The problem",
    title: "The tissue tears",
    body: "This is what happens during sectioning — a chunk shears away along a cut line. Existing tools can't handle it.",
    button: "Try PASTE2",
  },
  {
    key: "paste2",
    kicker: "Existing method",
    title: "PASTE2 fails",
    body: "PASTE2 smears the tear. The tissue geometry is broken and layers no longer line up.",
    button: "Try Sutura",
    metric: { val: data.paste2_px, tone: "bad", label: "median error" },
  },
  {
    key: "sutura",
    kicker: "Sutura",
    title: "Sutura works",
    body: "7× more accurate. Sutura recovers the true tissue geometry straight through the tear.",
    metric: { val: data.sutura_px, tone: "good", label: "median error" },
  },
];

export default function App() {
  const initStep = (() => {
    const p = new URLSearchParams(window.location.search).get("step");
    const n = parseInt(p, 10);
    return Number.isFinite(n) && n >= 0 && n < 4 ? n : 0;
  })();
  const [step, setStep] = useState(initStep);
  const s = STEPS[step];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="dot" />
          Sutura Genomics
        </div>
        <div className="tagline">alignment that handles torn tissue</div>
      </header>

      <div className="stage">
        <Scene targetKey={s.key} />

        <div className="overlay-text">
          <div className="kicker">{s.kicker}</div>
          <h1>{s.title}</h1>
          <p>{s.body}</p>
        </div>

        {s.metric && (
          <div className={`metric ${s.metric.tone}`} key={s.key}>
            <div className="num">
              {s.metric.val}
              <span className="unit">px</span>
            </div>
            <div className="mlabel">{s.metric.label}</div>
          </div>
        )}

        <Legend />
      </div>

      <div className="dock">
        <div className="steps">
          {STEPS.map((st, i) => (
            <div
              key={st.key}
              className={`chip ${i === step ? "active" : ""} ${
                i < step ? "done" : ""
              }`}
            >
              <span className="idx">{i + 1}</span>
              {st.kicker}
            </div>
          ))}
        </div>

        <div className="actions">
          {step > 0 && (
            <button className="btn ghost" onClick={() => setStep(0)}>
              ↺ Reset
            </button>
          )}
          {s.button ? (
            <button className="btn primary" onClick={() => setStep(step + 1)}>
              {s.button} →
            </button>
          ) : (
            <div className="links">
              <a className="btn primary" href="https://www.biorxiv.org/" target="_blank" rel="noreferrer">
                Read the paper →
              </a>
              <a className="btn ghost" href="https://suturagenomics.bio" target="_blank" rel="noreferrer">
                Learn more
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      {data.layers.map((name, i) => (
        <span key={name}>
          <i style={{ background: data.layerColors[i] }} />
          {name.replace("Layer", "L")}
        </span>
      ))}
    </div>
  );
}
