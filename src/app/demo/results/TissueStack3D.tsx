"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

type Slice = { id: string; n: number; xy: [number, number][]; layer: number[] };
type StackData = {
  dataset: string;
  layers: string[];
  layerColors: string[];
  spacing: number;
  slices: Slice[];
};

const XY_SCALE = 46; // maps normalized [-1,1] tissue coords into world units

// Soft round glowing point — reads as coherent tissue volume, not scattered dots.
const VERT = `
  attribute float aSize;
  attribute vec3 aColor;
  varying vec3 vColor;
  void main() {
    vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * (260.0 / -mv.z);
    gl_Position = projectionMatrix * mv;
  }
`;
const FRAG = `
  varying vec3 vColor;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float d = length(c);
    if (d > 0.5) discard;
    // bright core + soft halo
    float a = smoothstep(0.5, 0.08, d);
    float core = smoothstep(0.32, 0.0, d) * 0.35;
    gl_FragColor = vec4(vColor + core, a);
  }
`;

function easeInOut(t: number) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

// deterministic 0..1 hash for per-point size variation
function hash01(i: number) {
  const x = Math.sin(i * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

function PointCloud({ data, aligned }: { data: StackData; aligned: boolean }) {
  const pointsRef = useRef<THREE.Points>(null);
  // progress: 0 = unaligned, 1 = aligned. Eases toward the target each frame.
  const progress = useRef(aligned ? 1 : 0);

  // Positions/colors/sizes depend only on the data — NOT on `aligned` — so the
  // bound buffers stay stable across toggles and useFrame can animate between
  // the two position sets instead of the geometry snapping.
  const { alignedPos, unalignedPos, colors, sizes, curPos } = useMemo(() => {
    const cols = data.layerColors.map((c) => new THREE.Color(c));
    const N = data.slices.reduce((s, sl) => s + sl.xy.length, 0);
    const aPos = new Float32Array(N * 3);
    const uPos = new Float32Array(N * 3);
    const col = new Float32Array(N * 3);
    const siz = new Float32Array(N);
    const centerY = ((data.slices.length - 1) * data.spacing) / 2;
    const mid = (data.slices.length - 1) / 2;

    let k = 0;
    data.slices.forEach((sl, si) => {
      const y = si * data.spacing - centerY;
      // per-slice misalignment: fan rotation + lateral offset (dramatic)
      const theta = (si - mid) * 0.22;
      const ct = Math.cos(theta);
      const st = Math.sin(theta);
      const ox = (si - mid) * 0.3;
      const oy = (si - mid) * 0.05;
      for (let i = 0; i < sl.xy.length; i++) {
        const ax = sl.xy[i][0];
        const az = sl.xy[i][1];
        // aligned world position
        aPos[k * 3] = ax * XY_SCALE;
        aPos[k * 3 + 1] = y;
        aPos[k * 3 + 2] = az * XY_SCALE;
        // unaligned: tear the right half, then rotate + offset the whole section
        let tx = ax;
        let tz = az;
        if (ax > 0) {
          tx += 0.42 + 0.05 * si;
          tz += 0.12;
        }
        const rx = tx * ct - tz * st + ox;
        const rz = tx * st + tz * ct + oy;
        uPos[k * 3] = rx * XY_SCALE;
        uPos[k * 3 + 1] = y;
        uPos[k * 3 + 2] = rz * XY_SCALE;

        const c = cols[sl.layer[i]] ?? cols[0];
        col[k * 3] = c.r;
        col[k * 3 + 1] = c.g;
        col[k * 3 + 2] = c.b;
        // deterministic size variation for a tissue-like texture
        siz[k] = 3.4 + 2.6 * hash01(k + 1);
        k++;
      }
    });

    const cur = new Float32Array(aPos.length);
    cur.set(uPos); // view opens unaligned, then eases toward aligned (auto-heal)
    return { alignedPos: aPos, unalignedPos: uPos, colors: col, sizes: siz, curPos: cur };
  }, [data]);

  useFrame((_, dt) => {
    const pts = pointsRef.current;
    if (!pts) return;
    const target = aligned ? 1 : 0;
    const p = progress.current;
    if (Math.abs(p - target) < 0.001) {
      if (p !== target) {
        progress.current = target;
      } else {
        return; // settled — leave positions static, OrbitControls keeps rotating
      }
    } else {
      progress.current = p + (target - p) * Math.min(1, dt * 2.6);
    }
    const e = easeInOut(progress.current);
    const pos = pts.geometry.attributes.position.array as Float32Array;
    for (let i = 0; i < pos.length; i++) {
      pos[i] = unalignedPos[i] + (alignedPos[i] - unalignedPos[i]) * e;
    }
    pts.geometry.attributes.position.needsUpdate = true;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[curPos, 3]} />
        <bufferAttribute attach="attributes-aColor" args={[colors, 3]} />
        <bufferAttribute attach="attributes-aSize" args={[sizes, 1]} />
      </bufferGeometry>
      <shaderMaterial
        vertexShader={VERT}
        fragmentShader={FRAG}
        transparent
        depthWrite={false}
        depthTest
      />
    </points>
  );
}

export default function TissueStack3D({
  src,
  aligned = true,
}: {
  src: string;
  aligned?: boolean;
}) {
  const [data, setData] = useState<StackData | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    setData(null);
    setErr(false);
    fetch(src)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => alive && setData(d))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, [src]);

  if (err) {
    return (
      <div className="grid h-full w-full place-items-center text-[13px] font-light text-muted-foreground">
        Could not load the tissue volume.
      </div>
    );
  }
  if (!data) {
    return (
      <div className="grid h-full w-full place-items-center">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-[#e7e1ff] border-t-[#6633ee]" />
      </div>
    );
  }

  return (
    <Canvas
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      camera={{ position: [95, 92, 95], fov: 40, near: 0.1, far: 2000 }}
    >
      <PointCloud data={data} aligned={aligned} />
      <OrbitControls
        enablePan={false}
        enableZoom
        enableRotate
        autoRotate
        autoRotateSpeed={0.85}
        minDistance={60}
        maxDistance={340}
        target={[0, 0, 0]}
      />
    </Canvas>
  );
}
