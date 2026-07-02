"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

// Render instanced colors at their exact hex (no linear/sRGB shift).
THREE.ColorManagement.enabled = false;

type Slice = { id: string; n: number; xy: [number, number][]; layer: number[] };
type StackData = {
  dataset: string;
  layers: string[];
  layerColors: string[];
  spacing: number;
  slices: Slice[];
};

const XY_SCALE = 46; // maps normalized [-1,1] tissue coords into world units

function Spots({ data }: { data: StackData }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  const { total, positions, colors, centerY } = useMemo(() => {
    const cols = data.layerColors.map((c) => new THREE.Color(c));
    const pos: number[] = [];
    const col: number[] = [];
    data.slices.forEach((s, si) => {
      // Serial sections stack upward (Y); each section lies in the X/Z plane.
      const y = si * data.spacing;
      for (let i = 0; i < s.xy.length; i++) {
        pos.push(s.xy[i][0] * XY_SCALE, y, s.xy[i][1] * XY_SCALE);
        const c = cols[s.layer[i]] ?? cols[0];
        col.push(c.r, c.g, c.b);
      }
    });
    const cy = ((data.slices.length - 1) * data.spacing) / 2;
    return {
      total: pos.length / 3,
      positions: new Float32Array(pos),
      colors: new Float32Array(col),
      centerY: cy,
    };
  }, [data]);

  useLayoutEffect(() => {
    const m = meshRef.current;
    if (!m) return;
    for (let i = 0; i < total; i++) {
      dummy.position.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
    m.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);
    m.instanceColor.needsUpdate = true;
    const mat = Array.isArray(m.material) ? m.material[0] : m.material;
    if (mat) mat.needsUpdate = true;
  }, [total, positions, colors, dummy]);

  return (
    <group position={[0, -centerY, 0]}>
      <instancedMesh ref={meshRef} args={[undefined, undefined, total]}>
        <sphereGeometry args={[0.9, 8, 8]} />
        <meshLambertMaterial toneMapped={false} />
      </instancedMesh>
    </group>
  );
}

export default function TissueStack3D() {
  const [data, setData] = useState<StackData | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/demo/br5292_stack.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => alive && setData(d))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, []);

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
      // 45° elevation: camera lifted above the block, looking down onto it.
      camera={{ position: [95, 95, 95], fov: 40, near: 0.1, far: 2000 }}
    >
      <color attach="background" args={["#ffffff"]} />
      <ambientLight intensity={1.05} />
      <directionalLight position={[60, 90, 40]} intensity={0.55} />
      <directionalLight position={[-50, -20, -40]} intensity={0.25} color="#b9a8ff" />
      <Spots data={data} />
      <OrbitControls
        enablePan={false}
        enableZoom
        enableRotate
        autoRotate
        autoRotateSpeed={0.9}
        minDistance={70}
        maxDistance={320}
        target={[0, 0, 0]}
      />
    </Canvas>
  );
}
