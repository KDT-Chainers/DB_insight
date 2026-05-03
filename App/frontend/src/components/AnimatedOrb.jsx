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
 *   particleCount?: number
 *   onMicClick?: () => void
 *   listening?: boolean
 * }} [props]
 */

const VERT = /* glsl */ `
uniform float uTime;
uniform float uPointScale;
uniform float uPixelRatio;
uniform vec3 uAimDir;
uniform float uStretch;
attribute float aJitter;
attribute float aPhase;
attribute float aScatter;
varying float vRim;
varying float vPhase;
varying float vScatter;
varying float vJitter;

void main() {
  vec3 dir = normalize(position);
  float breathe = sin(uTime * 1.15 + dot(dir, vec3(2.1, 0.7, 1.3))) * 0.018;
  breathe += sin(uTime * 2.4 - dot(dir, vec3(-1.2, 1.9, 0.5))) * 0.01;
  vec3 pos = position * (1.0 + breathe);

  vec3 A = normalize(uAimDir + vec3(0.0001));
  float align = max(dot(dir, A), 0.0);
  float pull = pow(align, 2.2) * (1.0 - 0.1 * aScatter);
  pos += A * uStretch * pull * 0.68;
  pos -= dir * uStretch * pull * 0.14;

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  vec3 nView = normalize((modelViewMatrix * vec4(dir, 0.0)).xyz);
  vec3 vDir = normalize(-mvPosition.xyz);
  float nd = clamp(abs(dot(nView, vDir)), 0.0, 1.0);
  vRim = pow(1.0 - nd, 0.42);
  vPhase = aPhase;
  vScatter = aScatter;
  vJitter = aJitter;

  float z = max(-mvPosition.z, 0.32);
  float basePx = uPointScale * uPixelRatio / z;
  float szVar = mix(0.78, 1.22, aJitter * 0.5 + 0.5);
  if (aScatter > 0.5) szVar *= 0.88;
  gl_PointSize = clamp(basePx * szVar * (0.92 + vRim * 0.55), 1.0, 5.85);
  gl_Position = projectionMatrix * mvPosition;
}
`;

const FRAG = /* glsl */ `
uniform float uTime;
varying float vRim;
varying float vPhase;
varying float vScatter;
varying float vJitter;

void main() {
  vec2 q = gl_PointCoord - vec2(0.5);
  float r = length(q) * 2.0;
  if (r > 0.92) discard;

  float dotMask = 1.0 - smoothstep(0.0, 0.88, r);
  dotMask *= 1.0 - smoothstep(0.55, 0.95, r) * 0.35;

  float spd = mix(4.2, 8.5, vScatter);
  float tw1 = 0.5 + 0.5 * sin(uTime * spd + vPhase);
  float tw2 = 0.5 + 0.5 * sin(uTime * 6.8 - vPhase * 1.9 + vJitter * 6.28318);
  float sparkle = 0.58 + 0.42 * tw1 * mix(0.75, 1.0, tw2);
  sparkle = clamp(pow(sparkle, 0.9), 0.38, 1.45);

  float rimBoost = mix(0.48, 1.38, vRim);
  float halo = mix(0.65, 1.15, vScatter);

  float alpha = dotMask * rimBoost * sparkle * halo * 0.82;
  alpha = clamp(alpha, 0.0, 1.0);

  vec3 col = vec3(1.0);
  gl_FragColor = vec4(col, alpha);
}
`;

/** 격자 구면 + 스캐터 셸 */
function buildWhiteOrbPoints(total, radius) {
  const scatterN = Math.min(Math.floor(total * 0.32), 10000);
  let gridN = total - scatterN;
  const lonBands = Math.max(32, Math.ceil(Math.sqrt(gridN * 1.85)));
  const latBands = Math.max(16, Math.ceil(gridN / lonBands));
  gridN = latBands * lonBands;

  const count = gridN + scatterN;
  const positions = new Float32Array(count * 3);
  const jitter = new Float32Array(count);
  const phase = new Float32Array(count);
  const scatter = new Float32Array(count);

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
      const jx = (rnd() - 0.5) * 0.012;
      const jy = (rnd() - 0.5) * 0.012;
      const jz = (rnd() - 0.5) * 0.012;
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
    positions[idx * 3] = sx;
    positions[idx * 3 + 1] = sy;
    positions[idx * 3 + 2] = sz;
    jitter[idx] = rnd();
    phase[idx] = rnd() * Math.PI * 2;
    scatter[idx] = 1;
    idx++;
  }

  return { positions, jitter, phase, scatter, count: idx };
}

export default function AnimatedOrb({
  text = "",
  autoProgress = false,
  initialProgress = 0,
  size = 320,
  className = "",
  interactive = true,
  particleCount = 9000,
  onMicClick,
  listening = false,
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
    const { positions, jitter, phase, scatter } = buildWhiteOrbPoints(n, radius);

    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("aJitter", new THREE.BufferAttribute(jitter, 1));
    geo.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
    geo.setAttribute("aScatter", new THREE.BufferAttribute(scatter, 1));

    const material = new THREE.ShaderMaterial({
      uniforms: {
        uTime: { value: 0 },
        uPointScale: { value: 5.82 },
        uPixelRatio: { value: dpr },
        uAimDir: { value: new THREE.Vector3(0, 1, 0) },
        uStretch: { value: 0 },
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
    scene.add(points);

    const clock = new THREE.Clock();
    const rafRef = { id: 0 };
    const raycaster = new THREE.Raycaster();
    const sphereWorld = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 1.02);
    const invQuat = new THREE.Quaternion();
    const sphereHit = new THREE.Vector3();
    const tmpHit = new THREE.Vector3();
    const reduceMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
      // Idle 구는 `size` 기준과 동일하게 보이도록: 큰 캔버스 + 뒤로 뺀 카메라에 맞춰 점 스케일만 bleed 보정
      material.uniforms.uPointScale.value = size * 0.0092 * VIEW_BLEED * 1.4;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(draw);

    const animate = () => {
      const dt = clock.getDelta();
      const t = clock.elapsedTime;
      material.uniforms.uTime.value = t;

      mouseSmoothRef.current.x +=
        (mouseRef.current.x - mouseSmoothRef.current.x) * 0.12;
      mouseSmoothRef.current.y +=
        (mouseRef.current.y - mouseSmoothRef.current.y) * 0.12;

      idleAngleRef.current += dt * 0.38;
      const mx = mouseSmoothRef.current.x;
      const my = mouseSmoothRef.current.y;
      points.rotation.y = idleAngleRef.current + mx * 0.95;
      points.rotation.x = my * -0.72;
      points.rotation.z = mx * my * 0.08;

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
            invQuat.copy(points.quaternion).invert();
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
      renderer.dispose();
    };
  }, [particleCount, size]);

  const displayProgress = Math.min(100, Math.round(progress));
  const captionLines = text
    .replace(/\r/g, "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

  const shellInteractive =
    interactive &&
    "group origin-center cursor-pointer transition-[transform,box-shadow,filter] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] hover:scale-[1.05] hover:-translate-y-0.5 hover:shadow-[0_0_28px_rgba(133,173,255,0.18)] active:scale-[1.02] active:translate-y-0 motion-reduce:transition-none motion-reduce:hover:scale-100 motion-reduce:hover:translate-y-0 motion-reduce:hover:shadow-none motion-reduce:active:scale-100";

  return (
    <div
      ref={containerRef}
      className={`relative inline-block select-none overflow-visible ${shellInteractive || ""} ${className}`}
      style={{ width: size, height: size }}
    >
      <div
        ref={drawWrapRef}
        className="pointer-events-auto absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
        style={{
          width: size * VIEW_BLEED,
          height: size * VIEW_BLEED,
        }}
      >
        <canvas
          ref={canvasRef}
          className="block h-full w-full bg-transparent"
          style={{ touchAction: "none", backgroundColor: "transparent" }}
        />
      </div>

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
    </div>
  );
}
