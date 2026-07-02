import React, { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import data from "./data.json";

// cortical-layer palette: Layer1..Layer6, WM, NA
const LAYER_COLORS = [
  "#f9c74f", // Layer1
  "#f9844a", // Layer2
  "#f3722c", // Layer3
  "#90be6d", // Layer4
  "#43aa8b", // Layer5
  "#577590", // Layer6
  "#9d4edd", // WM
  "#3a3f4b", // NA
];
const COLOR_OBJS = LAYER_COLORS.map((c) => new THREE.Color(c));

function useCloud(spots, layers, tornMask, breakTint) {
  return useMemo(() => {
    const n = spots.length;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = spots[i][0];
      pos[i * 3 + 1] = -spots[i][1]; // image y is top-down
      pos[i * 3 + 2] = 0;
      let c = COLOR_OBJS[layers ? layers[i] : 7];
      if (breakTint && tornMask && tornMask[i]) c = COLOR_OBJS[6];
      col[i * 3] = c.r;
      col[i * 3 + 1] = c.g;
      col[i * 3 + 2] = c.b;
    }
    return { pos, col, n };
  }, [spots, layers, tornMask, breakTint]);
}

function Cloud({ spots, layers, tornMask, size = 0.02, breakTint = false }) {
  const { pos, col } = useCloud(spots, layers, tornMask, breakTint);
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    return g;
  }, [pos, col]);
  return (
    <points geometry={geo}>
      <pointsMaterial
        size={size}
        vertexColors
        sizeAttenuation
        transparent
        opacity={0.92}
        depthWrite={false}
      />
    </points>
  );
}

// -------- landing: four real slices, stacked in depth --------
function StackedSlices() {
  const group = useRef();
  useFrame((_, dt) => {
    if (group.current) group.current.rotation.y += dt * 0.18;
  });
  const slices = data.landing;
  const gap = 0.55;
  return (
    <group ref={group} rotation={[-0.9, 0, 0]}>
      {slices.map((s, i) => (
        <group key={s.id} position={[0, 0, (i - (slices.length - 1) / 2) * gap]}>
          <Cloud spots={s.spots} layers={s.layers} size={0.018} />
        </group>
      ))}
    </group>
  );
}

function LandingCanvas() {
  return (
    <Canvas camera={{ position: [0, 0, 3.2], fov: 42 }} dpr={[1, 2]}>
      <StackedSlices />
    </Canvas>
  );
}

// -------- compare: one aligned/torn cloud, auto-rotating --------
function CompareCanvas({ spots, layers, tornMask, breakTint, tint }) {
  return (
    <Canvas camera={{ position: [0, 0, 2.7], fov: 42 }} dpr={[1, 2]}>
      <group rotation={[-0.35, 0, 0]}>
        <Cloud
          spots={spots}
          layers={layers}
          tornMask={tornMask}
          breakTint={breakTint}
          size={0.019}
        />
      </group>
      <OrbitControls
        autoRotate
        autoRotateSpeed={0.9}
        enablePan={false}
        enableZoom={false}
        minPolarAngle={Math.PI / 2 - 0.6}
        maxPolarAngle={Math.PI / 2 + 0.6}
      />
    </Canvas>
  );
}

export default function App() {
  const [aligned, setAligned] = useState(true);
  const t = data.tear;

  const leftSpots = aligned ? t.paste2 : t.torn;
  const rightSpots = aligned ? t.sutura : t.torn;

  return (
    <div className="wrap">
      <nav className="nav">
        <div className="brand">
          <span className="dot" />
          Sutura Genomics
        </div>
        <a href="https://suturagenomics.bio" target="_blank" rel="noreferrer">
          suturagenomics.bio →
        </a>
      </nav>

      <header className="hero">
        <div className="eyebrow">Spatial transcriptomics · alignment</div>
        <h1>
          Alignment that handles <span className="accent">torn tissue</span>.
        </h1>
        <p className="sub">
          Real tissue tears, folds, and detaches on the slide. Classical
          optimal-transport methods break where the tissue does. Sutura recovers
          the true geometry — even through a tear.
        </p>
      </header>

      <div className="stage">
        <LandingCanvas />
        <div className="caption">
          4 DLPFC Visium slices · real spots, colored by cortical layer · drag to
          explore
        </div>
      </div>

      <Legend />

      <div className="controls">
        <div className="toggle">
          <button
            className={!aligned ? "on" : ""}
            onClick={() => setAligned(false)}
          >
            Show torn
          </button>
          <button
            className={aligned ? "on" : ""}
            onClick={() => setAligned(true)}
          >
            Show aligned
          </button>
        </div>
      </div>

      <p className="section-title">
        {aligned
          ? "Same torn slice, aligned to the reference — two methods, side by side."
          : "A single slice with a tear (severity 5) and a smooth warp — the input both methods must solve."}
      </p>

      <div className="compare">
        <div className="card">
          <div className="head">
            <span className="name">PASTE2</span>
            <span className="tag bad">optimal transport</span>
          </div>
          <div className="canvas-holder">
            <CompareCanvas
              spots={leftSpots}
              layers={t.layers}
              tornMask={t.torn_mask}
              breakTint={!aligned}
            />
          </div>
          <div className="metric">
            <span className="label">median registration error</span>
            <span className="val bad">
              {t.paste2_px}
              <span className="unit">px</span>
            </span>
          </div>
        </div>

        <div className="card">
          <div className="head">
            <span className="name">Sutura</span>
            <span className="tag good">learned, tear-aware</span>
          </div>
          <div className="canvas-holder">
            <CompareCanvas
              spots={rightSpots}
              layers={t.layers}
              tornMask={t.torn_mask}
              breakTint={!aligned}
            />
          </div>
          <div className="metric">
            <span className="label">median registration error</span>
            <span className="val good">
              {t.sutura_px}
              <span className="unit">px</span>
            </span>
          </div>
        </div>
      </div>

      <div className="footer">
        <a
          className="btn primary"
          href="https://www.biorxiv.org/"
          target="_blank"
          rel="noreferrer"
        >
          Read the paper →
        </a>
        <a
          className="btn ghost"
          href="https://suturagenomics.bio"
          target="_blank"
          rel="noreferrer"
        >
          Learn more
        </a>
      </div>

      <div className="tail">
        DLPFC Visium dataset · errors measured against array-bridge ground truth.
        © Sutura Genomics.
      </div>
    </div>
  );
}

function Legend() {
  return (
    <div className="legend">
      {data.layers.map((name, i) => (
        <span key={name}>
          <i style={{ background: LAYER_COLORS[i] }} />
          {name}
        </span>
      ))}
    </div>
  );
}
