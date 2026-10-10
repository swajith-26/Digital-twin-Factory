import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Environment, Html, Lightformer, RoundedBox } from "@react-three/drei";
import { STATUS_LABEL, uiStatus } from "../lib/format";

function FactoryMachine({ position, label, status, color, selected, onClick, scale = 1, shake = 0, heat = 0, health = null }) {
  const ref = useRef();
  // The machine physically trembles with its REAL vibration reading.
  useFrame(({ clock }) => {
    if (ref.current) ref.current.position.x = position[0] + Math.sin(clock.elapsedTime * 48) * shake;
  });
  const glow = status === "critical" ? "#ef4444" : status === "warning" ? "#f59e0b" : status === "offline" ? "#64748b" : "#22c55e";
  return (
    <group ref={ref} position={position} scale={scale} onClick={(e) => { e.stopPropagation(); onClick?.(); }}>
      <RoundedBox args={[1.65, 1.25, 1.25]} radius={0.08} smoothness={4} castShadow>
        <meshStandardMaterial color={selected ? "#172554" : "#111827"} metalness={0.72} roughness={0.28} />
      </RoundedBox>
      <mesh position={[0, 0.66, 0]}>
        <boxGeometry args={[1.2, 0.08, 0.9]} />
        <meshStandardMaterial color={heat > 0.35 ? "#ef4444" : color} emissive={heat > 0.35 ? "#ef4444" : color} emissiveIntensity={0.25 + heat * 2.2} />
      </mesh>
      <mesh position={[0, 0.05, 0.64]}>
        <boxGeometry args={[0.28, 0.28, 0.04]} />
        <meshStandardMaterial color={glow} emissive={glow} emissiveIntensity={status === "critical" ? 5 : 2.5} />
      </mesh>
      <mesh position={[0.46, 0.12, 0.65]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.17, 0.17, 0.05, 24]} />
        <meshStandardMaterial color="#64748b" metalness={0.9} />
      </mesh>
      <Html position={[0, 1.1, 0]} center distanceFactor={7}>
        <div className={`machine-tag ${status}`}><strong>{label}</strong><span><i />{STATUS_LABEL[status]}{health !== null && health !== undefined ? ` · ${health}%` : ""}</span></div>
      </Html>
    </group>
  );
}

function Conveyor({ position = [0, 0, 0], scale = [1, 1, 1], animated = false }) {
  const ref = useRef();
  useFrame((_, delta) => { if (animated && ref.current) ref.current.rotation.x -= delta * 1.7; });
  return (
    <group position={position} scale={scale}>
      <mesh position={[0, 0.16, 0]} receiveShadow><boxGeometry args={[7.8, 0.22, 1.35]} /><meshStandardMaterial color="#1e293b" metalness={0.8} roughness={0.35} /></mesh>
      {[-3.1, -2.2, -1.3, -0.4, 0.5, 1.4, 2.3, 3.2].map((x) => <mesh key={x} position={[x, 0.31, 0]}><boxGeometry args={[0.62, 0.05, 1.12]} /><meshStandardMaterial color="#64748b" metalness={0.9} roughness={0.25} /></mesh>)}
      {[-3.6, 3.6].map((x) => <mesh key={x} ref={x === -3.6 ? ref : undefined} position={[x, 0.15, 0]} rotation={[0, 0, Math.PI / 2]}><cylinderGeometry args={[0.55, 0.55, 1.5, 24]} /><meshStandardMaterial color="#0f172a" metalness={0.9} roughness={0.25} /></mesh>)}
    </group>
  );
}

function RobotArm({ position = [0, 0, 0], scale = 1 }) {
  return <group position={position} scale={scale}>
    <mesh position={[0, 0.55, 0]} castShadow><cylinderGeometry args={[0.45, 0.52, 0.25, 24]} /><meshStandardMaterial color="#f59e0b" metalness={0.75} roughness={0.28} /></mesh>
    <mesh position={[0, 1.05, 0]} rotation={[0, 0, -0.22]} castShadow><boxGeometry args={[0.28, 1.05, 0.28]} /><meshStandardMaterial color="#fbbf24" metalness={0.65} /></mesh>
    <mesh position={[0.28, 1.52, 0]} rotation={[0, 0, 0.7]} castShadow><boxGeometry args={[0.25, 0.85, 0.25]} /><meshStandardMaterial color="#f59e0b" metalness={0.65} /></mesh>
    <mesh position={[0.57, 1.86, 0]}><boxGeometry args={[0.45, 0.12, 0.3]} /><meshStandardMaterial color="#fbbf24" metalness={0.65} /></mesh>
  </group>;
}

function FactoryBase({ detailed = false }) {
  return <>
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow><planeGeometry args={detailed ? [22, 16] : [18, 13]} /><meshStandardMaterial color="#0b1728" metalness={0.25} roughness={0.7} /></mesh>
    <gridHelper args={detailed ? [22, 22] : [18, 18]} position={[0, 0.02, 0]} />
    {detailed && <>
      <mesh position={[0, 4.3, -6.6]}><boxGeometry args={[21, 7.5, 0.25]} /><meshStandardMaterial color="#111f31" metalness={0.35} roughness={0.55} /></mesh>
      {[-9, -4.5, 0, 4.5, 9].map((x) => <mesh key={x} position={[x, 2.2, -6.25]}><boxGeometry args={[0.18, 4.4, 0.18]} /><meshStandardMaterial color="#334155" metalness={0.8} /></mesh>)}
      {[-8, -4, 0, 4, 8].map((x) => <mesh key={x} position={[x, 6.8, 0]}><boxGeometry args={[0.18, 0.18, 13]} /><meshStandardMaterial color="#26384d" metalness={0.8} /></mesh>)}
      <mesh position={[0, 6.9, 0]}><boxGeometry args={[21, 0.18, 13]} /><meshStandardMaterial color="#17263a" metalness={0.5} roughness={0.7} transparent opacity={0.55} /></mesh>
      <Html position={[-8.5, 4.7, -6.0]} center distanceFactor={10}><div className="plant-label">PRODUCTION HALL · ZONE A</div></Html>
      <Html position={[8.0, 4.7, -6.0]} center distanceFactor={10}><div className="plant-label">ASSEMBLY · ZONE B</div></Html>
    </>}
  </>;
}

function FactoryScene({ machines, selectedMachine, setSelectedMachine, detailed = false }) {
  const info = (id) => {
    const m = machines.find((x) => x.id === id);
    if (!m) return { status: "offline" };
    const status = uiStatus(m.status);
    const vibration = m.sensors?.vibration;
    const temperature = m.sensors?.temperature;
    const nominal = temperature?.nominal ?? temperature?.value;
    const span = temperature?.limits?.critical_high ? temperature.limits.critical_high - nominal : 0;
    return {
      status,
      health: m.health,
      shake: status === "offline" || !vibration ? 0 : Math.min(0.045, vibration.value * 0.0045),
      heat: status === "offline" || span <= 0 ? 0 : Math.min(1, Math.max(0, (temperature.value - nominal) / span)),
    };
  };
  return <div className={detailed ? "scene-wrap detailed-scene" : "scene-wrap"}>
    <Canvas shadows dpr={[1, 1.5]} camera={{ position: detailed ? [12, 9, 14] : [9, 8, 11], fov: detailed ? 40 : 42 }}>
      <color attach="background" args={["#07111f"]} />
      <ambientLight intensity={0.55} />
      <directionalLight position={[5, 9, 5]} intensity={2.2} castShadow />
      <pointLight position={[-4, 4, 3]} intensity={18} distance={16} color="#22d3ee" />
      <pointLight position={[5, 3, -3]} intensity={12} distance={15} color="#6366f1" />
      {/* Procedural reflections: drei's "city" preset downloads an HDR file from a
          public CDN, which breaks on an offline / firewalled factory network. */}
      <Environment resolution={256}>
        <Lightformer form="rect" intensity={2.4} position={[0, 6, -6]} scale={[14, 4, 1]} color="#cfe8ff" />
        <Lightformer form="rect" intensity={1.6} position={[-7, 3, 4]} scale={[7, 3, 1]} color="#22d3ee" />
        <Lightformer form="rect" intensity={1.3} position={[7, 3, 4]} scale={[7, 3, 1]} color="#818cf8" />
        <Lightformer form="ring" intensity={1.2} position={[0, 8, 0]} rotation-x={Math.PI / 2} scale={6} color="#ffffff" />
      </Environment>
      <FactoryBase detailed={detailed} />
      <Conveyor position={[0, 0, 0]} scale={detailed ? [1.02, 1, 1] : [0.82, 1, 1]} animated={detailed} />
      <Conveyor position={[0, 0, -3.2]} scale={detailed ? [0.72, 1, 0.8] : [0.72, 1, 0.8]} animated={detailed} />
      <RobotArm position={[detailed ? 6.1 : 3.8, 0, -2.2]} scale={detailed ? 1.25 : 1} />
      <FactoryMachine position={detailed ? [-6.2, 0.8, 2.15] : [-4.2, 0.8, 2.15]} label="M01" color="#06b6d4" {...info(1)} selected={selectedMachine === 1} onClick={() => setSelectedMachine(1)} />
      <FactoryMachine position={detailed ? [-1.9, 0.8, 2.15] : [0, 0.8, 2.15]} label="M02" color="#3b82f6" {...info(2)} selected={selectedMachine === 2} onClick={() => setSelectedMachine(2)} />
      <FactoryMachine position={detailed ? [-4.3, 0.8, -2.4] : [-2.9, 0.8, -2.25]} label="M03" color="#8b5cf6" {...info(3)} selected={selectedMachine === 3} onClick={() => setSelectedMachine(3)} />
      <FactoryMachine position={detailed ? [1.9, 0.8, -0.15] : [2.4, 0.8, -0.15]} label="M04" color="#14b8a6" {...info(4)} selected={selectedMachine === 4} onClick={() => setSelectedMachine(4)} />
      {detailed && <>
        <mesh position={[7.7, 1.2, 2.8]} castShadow><boxGeometry args={[1.6, 2.4, 2.2]} /><meshStandardMaterial color="#334155" metalness={0.65} roughness={0.4} /></mesh>
        <mesh position={[7.7, 2.45, 2.8]}><boxGeometry args={[1.25, 0.06, 1.8]} /><meshStandardMaterial color="#f59e0b" emissive="#f59e0b" emissiveIntensity={0.2} /></mesh>
        <Html position={[7.7, 2.85, 2.8]} center distanceFactor={10}><div className="plant-label">QUALITY STATION</div></Html>
      </>}
      {!detailed && <><mesh position={[-6.5, 1.5, -3.2]} castShadow><boxGeometry args={[1.2, 3, 1.4]} /><meshStandardMaterial color="#334155" metalness={0.7} roughness={0.35} /></mesh><Html position={[-6.5, 3.2, -3.2]} center distanceFactor={8}><div className="plant-label">FACTORY ZONE A</div></Html></>}
      <OrbitControls enablePan={false} minDistance={detailed ? 9 : 8} maxDistance={detailed ? 24 : 18} maxPolarAngle={Math.PI / 2.15} />
    </Canvas>
    <div className="scene-hint"><span>↻</span> Drag to rotate · Scroll to zoom · Click a machine</div>
  </div>;
}

export default FactoryScene;
