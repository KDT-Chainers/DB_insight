import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

/** 레이아웃은 `size`×`size` 유지. 캔버스만 키워 호버 스트레치 시 뷰포트 클리핑 완화 (시각 스케일은 카메라로 보정) */
const VIEW_BLEED = 1.48;
const CAM_Z_BASE = 2.85;

/**
 * 흰 점 구름 구체(위도·경도 격자 + 스캐터). 배경은 페이지와 동일(추가 레이어 없음).
 * 부드러운 Y 회전 + 마우스 기울기. 호버 시 커서 방향으로 점이 늘어났다가 이탈 시 복귀.
 *
 * @param {{
 *   text?: string
 *   autoProgress?: boolean
 *   initialProgress?: number
 *   size?: number
 *   className?: string
 *   interactive?: boolean
 *   colorMode?: 'default' | 'ai' — ai: 네트워크 그래프 톤(블루·핑크·민트·코랄) 점 색
 *   hideCenterUI?: boolean — true면 중앙 마이크/캡션 오버레이 숨김
 *   pointScaleMul?: number — 점 픽셀 크기 배율(기본 1). 존재감 올릴 때 1.15~1.35
 *   particleCount?: number
 *   onMicClick?: () => void
 *   listening?: boolean
 *   assembleIntro?: boolean — true면 점이 바깥에서 구면으로 모이는 인트로
 *   assembleDuration?: number — 인트로 길이(초), 기본 ~8
 *   layout?: 'fixed' | 'fill' — fill이면 부모 전체를 캔버스로 채움(AI 홈 전역 오브 등)
 * }} [props]
 */

function smoothstep(edge0, edge1, x) {
  const t = Math.min(1, Math.max(0, (x - edge0) / (Math.abs(edge1 - edge0) < 1e-8 ? 1e-8 : edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

/** AI 모드: 신경망 톤 — 허브(격자) vs 노드(스캐터) + 전기 시안 통로 하이라이트 */
function aiPointColor(nx, ny, nz, rnd, isScatter) {
  const navy = [0.18, 0.42, 1.0];
  const pink = [1.0, 0.35, 0.88];
  const mint = [0.32, 0.98, 0.78];
  const coral = [1.0, 0.38, 0.26];
  const electric = [0.55, 0.95, 1.0];
  const lerp3 = (a, b, t) => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
  if (isScatter) {
    const roll = rnd();
    const base = roll < 0.3 ? mint : roll < 0.62 ? pink : roll < 0.88 ? navy : electric;
    const hot = rnd() < 0.22 ? 1.12 : 1.0;
    return [
      Math.min(1, base[0] * (0.9 + rnd() * 0.18) * hot),
      Math.min(1, base[1] * (0.9 + rnd() * 0.18) * hot),
      Math.min(1, base[2] * (0.9 + rnd() * 0.18) * hot),
    ];
  }
  let c = [...navy];
  const wTop = smoothstep(0.12, 0.82, ny) * 0.78;
  const wRight = smoothstep(0.18, 0.72, nx) * (0.45 + 0.55 * smoothstep(-0.35, 0.45, nz));
  const wLeft = smoothstep(-0.72, -0.18, nx) * 0.72;
  c = lerp3(c, pink, wTop);
  c = lerp3(c, mint, wRight * 0.62);
  c = lerp3(c, coral, wLeft * 0.55);
  const corridor = Math.abs(Math.sin(nx * 7.2 + nz * 5.1 + ny * 3.3));
  c = lerp3(c, electric, smoothstep(0.55, 0.98, corridor) * 0.28);
  const n = (rnd() - 0.5) * 0.09;
  return [
    Math.min(1, Math.max(0, c[0] + n)),
    Math.min(1, Math.max(0, c[1] + n)),
    Math.min(1, Math.max(0, c[2] + n)),
  ];
}

const VERT = /* glsl */ `
uniform float uTime;
uniform float uPointScale;
uniform float uPixelRatio;
uniform vec3 uAimDir;
uniform float uStretch;
uniform float uAssemble;
uniform float uNeural;
attribute vec3 aSpread;
attribute float aJitter;
attribute float aPhase;
attribute float aScatter;
attribute vec3 aColor;
varying float vRim;
varying float vPhase;
varying float vScatter;
varying float vJitter;
varying vec3 vColor;

void main() {
  vec3 S = position;
  vec3 dir = normalize(S);
  float breathe = sin(uTime * 1.15 + dot(dir, vec3(2.1, 0.7, 1.3))) * 0.018;
  breathe += sin(uTime * 2.4 - dot(dir, vec3(-1.2, 1.9, 0.5))) * 0.01;
  breathe += uNeural * sin(uTime * 2.9 + dot(dir, vec3(4.2, -2.1, 1.7)) * 3.0) * 0.017;
  breathe += uNeural * sin(aPhase * 4.0 + uTime * 4.35) * 0.01 * (0.55 + 0.45 * aScatter);
  vec3 Sb = S * (1.0 + breathe);
  float t0 = clamp(uAssemble, 0.0, 1.0);
  float te = 1.0 - pow(1.0 - t0, 4.0);
  vec3 pos = mix(aSpread, Sb, te);

  vec3 A = normalize(uAimDir + vec3(0.0001));
  float align = max(dot(dir, A), 0.0);
  float pull = pow(align, 2.2) * (1.0 - 0.1 * aScatter);
  pos += A * uStretch * pull * 0.68;
  pos -= dir * uStretch * pull * 0.14;

  vec3 ax = normalize(cross(dir, vec3(0.12, 0.93, 0.1)) + vec3(0.0001));
  vec3 bi = normalize(cross(dir, ax));
  float syn = sin(uTime * 3.25 + aPhase * 7.5 + dot(dir, vec3(5.1, 2.2, -3.4)));
  pos += uNeural * (ax * syn + bi * cos(syn * 1.35)) * 0.0135 * (0.42 + 0.58 * aScatter);

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  vec3 nView = normalize((modelViewMatrix * vec4(dir, 0.0)).xyz);
  vec3 vDir = normalize(-mvPosition.xyz);
  float nd = clamp(abs(dot(nView, vDir)), 0.0, 1.0);
  vRim = pow(1.0 - nd, 0.42);
  vPhase = aPhase;
  vScatter = aScatter;
  vJitter = aJitter;
  vColor = aColor;

  float z = max(-mvPosition.z, 0.32);
  float basePx = uPointScale * uPixelRatio / z;
  float szVar = mix(0.78, 1.22, aJitter * 0.5 + 0.5);
  if (aScatter > 0.5) szVar *= 0.88;
  float ps = clamp(basePx * szVar * (0.92 + vRim * 0.55), 1.0, 7.2);
  ps *= 1.0 + uNeural * (0.06 + 0.1 * aScatter) * (0.5 + 0.5 * sin(uTime * 2.1 + aPhase * 6.0));
  gl_PointSize = ps;
  gl_Position = projectionMatrix * mvPosition;
}
`;

const FRAG = /* glsl */ `
uniform float uTime;
uniform float uNeural;
varying float vRim;
varying float vPhase;
varying float vScatter;
varying float vJitter;
varying vec3 vColor;

void main() {
  vec2 q = gl_PointCoord - vec2(0.5);
  float r = length(q) * 2.0;
  if (r > 0.92) discard;

  float dotMask = 1.0 - smoothstep(0.0, 0.88, r);
  dotMask *= 1.0 - smoothstep(0.55, 0.95, r) * 0.35;

  float spd = mix(4.2, 8.5, vScatter) * (1.0 + uNeural * 0.55);
  float tw1 = 0.5 + 0.5 * sin(uTime * spd + vPhase);
  float tw2 = 0.5 + 0.5 * sin(uTime * 6.8 - vPhase * 1.9 + vJitter * 6.28318);
  float tw3 = 0.5 + 0.5 * sin(uTime * 11.2 + vPhase * 9.0 + vJitter * 12.56);
  float sparkle = 0.58 + 0.42 * tw1 * mix(0.75, 1.0, tw2);
  sparkle += uNeural * (0.12 + 0.22 * vScatter) * tw3 * tw3;
  sparkle = clamp(pow(sparkle, 0.88), 0.35, 1.58);

  float rimBoost = mix(0.48, 1.38, vRim);
  float halo = mix(0.65, 1.15, vScatter);

  float wave = sin(uTime * 2.65 + vPhase * 13.0 + dot(vColor, vec3(4.2, 2.7, 1.9)));
  float fire = uNeural * smoothstep(0.45, 0.98, wave * 0.5 + 0.5) * mix(0.35, 0.95, vScatter);
  float burst = uNeural * pow(max(0.0, sin(uTime * 4.35 + vPhase * 17.0 + vJitter * 9.0)), 12.0) * 0.95;

  float alpha = dotMask * rimBoost * sparkle * halo * 0.82;
  alpha *= 1.0 + 0.42 * fire + 0.65 * burst;
  alpha = clamp(alpha, 0.0, 1.0);

  vec3 col = vColor * (1.0 + 0.28 * fire + 0.75 * burst);
  gl_FragColor = vec4(col, alpha);
}
`;

/** 격자 구면 + 스캐터 셸 */
function buildWhiteOrbPoints(total, radius, palette = "default") {
  const scatterFrac = palette === "ai" ? 0.38 : 0.32;
  const scatterN = Math.min(Math.floor(total * scatterFrac), 10000);
  let gridN = total - scatterN;
  const lonBands = Math.max(36, Math.ceil(Math.sqrt(gridN * 2.05)));
  const latBands = Math.max(16, Math.ceil(gridN / lonBands));
  gridN = latBands * lonBands;

  const count = gridN + scatterN;
  const positions = new Float32Array(count * 3);
  const jitter = new Float32Array(count);
  const phase = new Float32Array(count);
  const scatter = new Float32Array(count);
  const colors = new Float32Array(count * 3);
  const spread = new Float32Array(count * 3);

  let seed = 9.876;
  const rnd = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };

  let idx = 0;
  for (let lat = 0; lat < latBands; lat++) {
    const tv = latBands > 1 ? lat / (latBands - 1) : 0.5;
    const theta = tv * Math.PI;
    const sinT = Math.sin(theta);
    const cosT = Math.cos(theta);
    for (let lon = 0; lon < lonBands; lon++) {
      const phi = (lon / lonBands) * Math.PI * 2;
      const jx = (rnd() - 0.5) * 0.004;
      const jy = (rnd() - 0.5) * 0.004;
      const jz = (rnd() - 0.5) * 0.004;
      const x = radius * sinT * Math.cos(phi) + jx;
      const y = radius * cosT + jy;
      const z = radius * sinT * Math.sin(phi) + jz;
      const len = Math.hypot(x, y, z) || 1;
      positions[idx * 3] = (x / len) * radius;
      positions[idx * 3 + 1] = (y / len) * radius;
      positions[idx * 3 + 2] = (z / len) * radius;
      jitter[idx] = rnd();
      phase[idx] = rnd() * Math.PI * 2;
      scatter[idx] = 0;
      const nx = positions[idx * 3] / radius;
      const ny = positions[idx * 3 + 1] / radius;
      const nz = positions[idx * 3 + 2] / radius;
      if (palette === "ai") {
        const rgb = aiPointColor(nx, ny, nz, rnd, false);
        colors[idx * 3] = rgb[0];
        colors[idx * 3 + 1] = rgb[1];
        colors[idx * 3 + 2] = rgb[2];
      } else {
        colors[idx * 3] = 1;
        colors[idx * 3 + 1] = 1;
        colors[idx * 3 + 2] = 1;
      }
      const vx = (rnd() - 0.5) * 1.05;
      const vy = (rnd() - 0.5) * 1.05;
      const vz = (rnd() - 0.5) * 1.05;
      const px = positions[idx * 3] + vx;
      const py = positions[idx * 3 + 1] + vy;
      const pz = positions[idx * 3 + 2] + vz;
      const plen = Math.hypot(px, py, pz) || 1;
      const spreadR = radius * (3.35 + rnd() * 1.25);
      spread[idx * 3] = (px / plen) * spreadR;
      spread[idx * 3 + 1] = (py / plen) * spreadR;
      spread[idx * 3 + 2] = (pz / plen) * spreadR;
      idx++;
    }
  }

  for (let s = 0; s < scatterN; s++) {
    const u = rnd() * Math.PI * 2;
    const v = Math.acos(2 * rnd() - 1);
    const rr = radius * (0.84 + rnd() * 0.26);
    const sx = rr * Math.sin(v) * Math.cos(u);
    const sy = rr * Math.cos(v);
    const sz = rr * Math.sin(v) * Math.sin(u);
    const slen = Math.hypot(sx, sy, sz) || 1;
    const snx = sx / slen;
    const sny = sy / slen;
    const snz = sz / slen;
    positions[idx * 3] = sx;
    positions[idx * 3 + 1] = sy;
    positions[idx * 3 + 2] = sz;
    jitter[idx] = rnd();
    phase[idx] = rnd() * Math.PI * 2;
    scatter[idx] = 1;
    if (palette === "ai") {
      const nx = sx / (rr || 1);
      const ny = sy / (rr || 1);
      const nz = sz / (rr || 1);
      const rgb = aiPointColor(nx, ny, nz, rnd, true);
      colors[idx * 3] = rgb[0];
      colors[idx * 3 + 1] = rgb[1];
      colors[idx * 3 + 2] = rgb[2];
    } else {
      colors[idx * 3] = 1;
      colors[idx * 3 + 1] = 1;
      colors[idx * 3 + 2] = 1;
    }
    const jx = (rnd() - 0.5) * 0.95;
    const jy = (rnd() - 0.5) * 0.95;
    const jz = (rnd() - 0.5) * 0.95;
    const qx = snx + jx;
    const qy = sny + jy;
    const qz = snz + jz;
    const qlen = Math.hypot(qx, qy, qz) || 1;
    const sOuter = radius * (3.2 + rnd() * 1.15);
    spread[idx * 3] = (qx / qlen) * sOuter;
    spread[idx * 3 + 1] = (qy / qlen) * sOuter;
    spread[idx * 3 + 2] = (qz / qlen) * sOuter;
    idx++;
  }

  return { positions, jitter, phase, scatter, colors, spread, count: idx };
}

/** AI 모드: 격자 이웃만 연결하는 얇은 시냅스 선(과하지 않게 stride로 희소) */
function buildNeuralSynapseLines(particleCount, radius, palette) {
  if (palette !== "ai") return null;
  const scatterFrac = 0.38;
  const scatterN = Math.min(Math.floor(particleCount * scatterFrac), 10000);
  let gridN = particleCount - scatterN;
  const lonBands = Math.max(36, Math.ceil(Math.sqrt(gridN * 2.05)));
  const latBands = Math.max(16, Math.ceil(gridN / lonBands));
  gridN = latBands * lonBands;

  const strideLon = 5;
  const strideLat = 4;
  const tuck = 0.996;

  const vert = (lat, lon) => {
    const L = ((lon % lonBands) + lonBands) % lonBands;
    const la = Math.min(Math.max(0, lat), latBands - 1);
    const tv = latBands > 1 ? la / (latBands - 1) : 0.5;
    const theta = tv * Math.PI;
    const phi = (L / lonBands) * Math.PI * 2;
    const sinT = Math.sin(theta);
    const cosT = Math.cos(theta);
    let x = radius * sinT * Math.cos(phi);
    let y = radius * cosT;
    let z = radius * sinT * Math.sin(phi);
    const len = Math.hypot(x, y, z) || 1;
    return [
      (x / len) * radius * tuck,
      (y / len) * radius * tuck,
      (z / len) * radius * tuck,
    ];
  };

  const segments = [];
  for (let lat = 0; lat < latBands - strideLat; lat += strideLat) {
    for (let lon = 0; lon < lonBands; lon += strideLon) {
      const a = vert(lat, lon);
      const b = vert(lat, lon + strideLon);
      segments.push(a[0], a[1], a[2], b[0], b[1], b[2]);
      const c = vert(lat + strideLat, lon);
      segments.push(a[0], a[1], a[2], c[0], c[1], c[2]);
    }
  }
  if (segments.length === 0) return null;
  return new Float32Array(segments);
}

const LINE_VERT = /* glsl */ `
attribute float aPhase;
varying float vPulse;
void main() {
  vPulse = aPhase;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const LINE_FRAG = /* glsl */ `
uniform float uTime;
uniform float uAssemble;
varying float vPulse;
void main() {
  float vis = smoothstep(0.88, 1.0, uAssemble);
  float pulse = 0.55 + 0.45 * sin(uTime * 1.65 + vPulse);
  float a = 0.065 * pulse * vis;
  vec3 col = vec3(0.48, 0.62, 0.98);
  gl_FragColor = vec4(col, a);
}
`;

export default function AnimatedOrb({
  text = "",
  autoProgress = false,
  initialProgress = 0,
  size = 320,
  className = "",
  interactive = true,
  colorMode = "default",
  hideCenterUI = false,
  pointScaleMul = 1,
  particleCount = 9000,
  onMicClick,
  listening = false,
  /** true면 첫 진입 시 점이 바깥에서 구면으로 모임 (AI 홈 등) */
  assembleIntro = false,
  /** assembleIntro 진행 시간(초) */
  assembleDuration = 8,
  /** fixed: size×size 박스. fill: 부모 100%×100% (min 크기는 size로 uPointScale 폴백) */
  layout = "fixed",
}) {
  const [progress, setProgress] = useState(initialProgress);
  const containerRef = useRef(null);
  const drawWrapRef = useRef(null);
  const canvasRef = useRef(null);
  const mouseRef = useRef({ x: 0, y: 0 });
  const mouseSmoothRef = useRef({ x: 0, y: 0 });
  const idleAngleRef = useRef(0);
  const pointerInRef = useRef(false);
  const stretchRef = useRef(0);
  const aimLocalRef = useRef(new THREE.Vector3(0, 1, 0));

  useEffect(() => {
    if (!autoProgress) return;
    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          return 100;
        }
        const increment = prev < 20 ? 0.3 : prev < 80 ? 0.5 : 0.2;
        return Math.min(100, prev + increment + Math.random() * 0.3);
      });
    }, 50);
    return () => clearInterval(interval);
  }, [autoProgress]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const draw = drawWrapRef.current;
    if (!canvas || !draw) return;

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
      powerPreference: "high-performance",
    });
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    renderer.setPixelRatio(dpr);
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;

    const scene = new THREE.Scene();
    scene.background = null;
    const camera = new THREE.PerspectiveCamera(42, 1, 0.08, 100);
    camera.position.set(0, 0, CAM_Z_BASE * VIEW_BLEED);

    const n = Math.max(2500, Math.min(16000, Math.floor(particleCount)));
    const radius = 1.0;
    const palette = colorMode === "ai" ? "ai" : "default";
    const { positions, jitter, phase, scatter, colors, spread } =
      buildWhiteOrbPoints(n, radius, palette);

    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const introActive = assembleIntro && !reduceMotion;
    const introDur = Math.max(0.4, assembleDuration);
    let introT0 = -1;

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("aSpread", new THREE.BufferAttribute(spread, 3));
    geo.setAttribute("aJitter", new THREE.BufferAttribute(jitter, 1));
    geo.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
    geo.setAttribute("aScatter", new THREE.BufferAttribute(scatter, 1));
    geo.setAttribute("aColor", new THREE.BufferAttribute(colors, 3));

    const isNeural = palette === "ai";
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uPointScale: { value: 5.82 },
        uPixelRatio: { value: dpr },
        uAimDir: { value: new THREE.Vector3(0, 1, 0) },
        uStretch: { value: 0 },
        uAssemble: { value: introActive ? 0 : 1 },
        uNeural: { value: isNeural ? 1.0 : 0.0 },
      },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthWrite: false,
      depthTest: true,
      blending: THREE.NormalBlending,
      premultipliedAlpha: false,
    });

    const points = new THREE.Points(geo, material);
    const root = new THREE.Group();
    root.add(points);

    let lineGeo = null;
    let lineMat = null;
    const linePos = buildNeuralSynapseLines(n, radius, palette);
    if (linePos && linePos.length > 0) {
      lineGeo = new THREE.BufferGeometry();
      lineGeo.setAttribute("position", new THREE.BufferAttribute(linePos, 3));
      const nVerts = linePos.length / 3;
      const linePhase = new Float32Array(nVerts);
      for (let i = 0; i < nVerts; i++) {
        linePhase[i] = Math.random() * Math.PI * 2;
      }
      lineGeo.setAttribute("aPhase", new THREE.BufferAttribute(linePhase, 1));
      lineMat = new THREE.ShaderMaterial({
        uniforms: {
          uTime: { value: 0 },
          uAssemble: { value: introActive ? 0 : 1 },
        },
        vertexShader: LINE_VERT,
        fragmentShader: LINE_FRAG,
        transparent: true,
        depthWrite: false,
        depthTest: true,
        blending: THREE.NormalBlending,
      });
      root.add(new THREE.LineSegments(lineGeo, lineMat));
    }

    scene.add(root);

    const clock = new THREE.Clock();
    const rafRef = { id: 0 };
    const raycaster = new THREE.Raycaster();
    const sphereWorld = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 1.02);
    const invQuat = new THREE.Quaternion();
    const sphereHit = new THREE.Vector3();
    const tmpHit = new THREE.Vector3();

    const onEnter = () => {
      pointerInRef.current = true;
    };

    const onMove = (e) => {
      const rect = draw.getBoundingClientRect();
      const cx = rect.left + rect.width * 0.5;
      const cy = rect.top + rect.height * 0.5;
      mouseRef.current.x = (e.clientX - cx) / (rect.width * 0.5);
      mouseRef.current.y = (e.clientY - cy) / (rect.height * 0.5);
      mouseRef.current.x = THREE.MathUtils.clamp(mouseRef.current.x, -1.2, 1.2);
      mouseRef.current.y = THREE.MathUtils.clamp(mouseRef.current.y, -1.2, 1.2);
    };

    const onLeave = () => {
      pointerInRef.current = false;
      mouseRef.current.x = 0;
      mouseRef.current.y = 0;
    };

    draw.addEventListener("mouseenter", onEnter);
    draw.addEventListener("mousemove", onMove);
    draw.addEventListener("mouseleave", onLeave);

    const resize = () => {
      const w = draw.clientWidth || size * VIEW_BLEED;
      const h = draw.clientHeight || size * VIEW_BLEED;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
      const pr = Math.min(window.devicePixelRatio || 1, 2);
      material.uniforms.uPixelRatio.value = pr;
      const effSize =
        layout === "fill" ? Math.min(w, h) || size : size;
      // Idle 구는 `effSize` 기준과 동일하게 보이도록: 큰 캔버스 + 뒤로 뺀 카메라에 맞춰 점 스케일만 bleed 보정
      material.uniforms.uPointScale.value =
        effSize * 0.0092 * VIEW_BLEED * 1.4 * pointScaleMul;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(draw);

    const animate = () => {
      const dt = clock.getDelta();
      const t = clock.elapsedTime;
      material.uniforms.uTime.value = t;
      if (lineMat) {
        lineMat.uniforms.uTime.value = t;
      }

      if (introActive) {
        if (introT0 < 0) introT0 = t;
        const as = Math.min(1, (t - introT0) / introDur);
        material.uniforms.uAssemble.value = as;
        if (lineMat) lineMat.uniforms.uAssemble.value = as;
      } else {
        material.uniforms.uAssemble.value = 1;
        if (lineMat) lineMat.uniforms.uAssemble.value = 1;
      }

      mouseSmoothRef.current.x +=
        (mouseRef.current.x - mouseSmoothRef.current.x) * 0.12;
      mouseSmoothRef.current.y +=
        (mouseRef.current.y - mouseSmoothRef.current.y) * 0.12;

      const neuralSpin = isNeural ? 0.56 : 0.38;
      idleAngleRef.current += dt * neuralSpin;
      const mx = mouseSmoothRef.current.x;
      const my = mouseSmoothRef.current.y;
      const mxMul = isNeural ? 1.08 : 0.95;
      const myMul = isNeural ? 0.82 : 0.72;
      root.rotation.y = idleAngleRef.current + mx * mxMul;
      root.rotation.x = my * -myMul;
      root.rotation.z = mx * my * (isNeural ? 0.12 : 0.08);

      if (!reduceMotion) {
        const target = pointerInRef.current ? 1 : 0;
        let s = stretchRef.current;
        const rate = pointerInRef.current ? 32 : 6.2;
        s += (target - s) * (1 - Math.exp(-dt * rate));
        stretchRef.current = s;
        material.uniforms.uStretch.value = s * s * 0.82;

        if (pointerInRef.current || s > 0.025) {
          raycaster.setFromCamera(new THREE.Vector2(mx, -my), camera);
          if (raycaster.ray.intersectSphere(sphereWorld, sphereHit) !== null) {
            invQuat.copy(root.quaternion).invert();
            tmpHit.copy(sphereHit).applyQuaternion(invQuat).normalize();
            aimLocalRef.current.copy(tmpHit);
          }
        }
        material.uniforms.uAimDir.value.copy(aimLocalRef.current);
      } else {
        material.uniforms.uStretch.value = 0;
      }

      renderer.render(scene, camera);
      rafRef.id = requestAnimationFrame(animate);
    };
    rafRef.id = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(rafRef.id);
      draw.removeEventListener("mouseenter", onEnter);
      draw.removeEventListener("mousemove", onMove);
      draw.removeEventListener("mouseleave", onLeave);
      ro.disconnect();
      geo.dispose();
      material.dispose();
      if (lineGeo) lineGeo.dispose();
      if (lineMat) lineMat.dispose();
      renderer.dispose();
    };
  }, [
    particleCount,
    size,
    colorMode,
    pointScaleMul,
    assembleIntro,
    assembleDuration,
    layout,
  ]);

  const displayProgress = Math.min(100, Math.round(progress));
  const captionLines = text
    .replace(/\r/g, "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  /* 호버 box-shadow는 사각 프레임처럼 보여 제거 — 피드백은 scale/translate만 */
  const shellInteractive =
    interactive &&
    "group origin-center cursor-pointer transition-[transform] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] hover:scale-[1.05] hover:-translate-y-0.5 active:scale-[1.02] active:translate-y-0 motion-reduce:transition-none motion-reduce:hover:scale-100 motion-reduce:hover:translate-y-0 motion-reduce:active:scale-100";

  const fill = layout === "fill";

  return (
    <div
      ref={containerRef}
      className={`relative select-none overflow-visible bg-transparent shadow-none ring-0 ${fill ? "h-full w-full min-h-0" : "mx-auto block"} ${shellInteractive || ""} ${className}`}
      style={fill ? { width: "100%", height: "100%" } : { width: size, height: size }}
    >
      <div
        ref={drawWrapRef}
        className={`absolute bg-transparent shadow-none ${interactive ? "pointer-events-auto" : "pointer-events-none"} ${fill ? "inset-0 left-0 top-0" : "left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"}`}
        style={
          fill
            ? { width: "100%", height: "100%" }
            : {
                width: size * VIEW_BLEED,
                height: size * VIEW_BLEED,
              }
        }
      >
        <canvas
          ref={canvasRef}
          className="block h-full w-full bg-transparent"
          style={{ touchAction: "none", backgroundColor: "transparent" }}
        />
      </div>

      {!hideCenterUI && (
      <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center">
        {onMicClick ? (
          <button
            type="button"
            onClick={onMicClick}
            className={`pointer-events-auto rounded-full p-1 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 ${
              listening
                ? "text-red-400 drop-shadow-[0_0_12px_rgba(248,113,113,0.5)]"
                : "text-white drop-shadow-[0_0_10px_rgba(255,255,255,0.45)] hover:text-primary"
            }`}
            style={{
              fontSize: Math.round(size * 0.12),
            }}
            aria-label={listening ? "음성 입력 끄기" : "음성 입력"}
          >
            <span
              className="material-symbols-outlined block"
              style={{
                fontSize: "inherit",
                fontVariationSettings: '"FILL" 1',
              }}
            >
              mic
            </span>
          </button>
        ) : (
          <span
            className="material-symbols-outlined text-white drop-shadow-[0_0_10px_rgba(255,255,255,0.45)]"
            style={{
              fontSize: Math.round(size * 0.12),
              fontVariationSettings: '"FILL" 1',
            }}
            aria-hidden
          >
            mic
          </span>
        )}
        {captionLines.length > 0 && (
          <div className="mt-1 max-w-[85%] text-center text-xs leading-snug text-white/55 transition-colors duration-300 group-hover:text-white/75 md:text-sm">
            {captionLines.map((line, i) => (
              <span key={i}>
                {line}
                {i < captionLines.length - 1 && <br />}
              </span>
            ))}
          </div>
        )}
        {(autoProgress || displayProgress > 0) && (
          <p className="mt-0.5 text-2xl font-light tracking-tight text-white/85 md:text-3xl">
            {displayProgress}%
          </p>
        )}
      </div>
      )}
    </div>
  );
}
