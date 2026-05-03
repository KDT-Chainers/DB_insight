/**
 * 팀 로고(DB 모노그램). 사이드바 등에서 기존 그라데이션+dataset 마크 대신 사용.
 */
export default function TeamLogoMark({ className = "" }) {
  return (
    <img
      src="/teamlogo.png"
      alt=""
      width={32}
      height={32}
      draggable={false}
      className={`h-8 w-8 shrink-0 rounded-lg bg-transparent object-contain ${className}`}
    />
  );
}
