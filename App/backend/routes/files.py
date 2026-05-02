"""
파일 관련 유틸리티 API

GET  /api/files/indexed       — 인덱싱된 파일 목록 (레거시 + TRI-CHEF)
GET  /api/files/stats         — 타입별 청크 수 통계
GET  /api/files/detail?path=  — 특정 파일의 전체 청크 텍스트

※ /api/files/open, /api/files/open-folder 는 routes/search.py 에 있음
"""

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

files_bp = Blueprint("files", __name__, url_prefix="/api/files")


# ── TRI-CHEF 레지스트리 헬퍼 ──────────────────────────────

def _trichef_indexed_files() -> list[dict]:
    """TRI-CHEF 이미지/문서 레지스트리에서 인덱싱된 파일 목록 반환."""
    from config import PATHS

    items: list[dict] = []

    # 이미지
    img_reg_path = Path(PATHS["TRICHEF_IMG_CACHE"]) / "registry.json"
    if img_reg_path.exists():
        try:
            reg = json.loads(img_reg_path.read_text(encoding="utf-8"))
            for _key, info in reg.items():
                orig = info.get("abs") or info.get("staged", "")
                items.append({
                    "file_path":  orig,
                    "file_name":  Path(orig).name if orig else _key,
                    "file_type":  "image",
                    "chunk_count": 1,
                    "source":     "trichef",
                })
        except Exception:
            pass

    # 문서
    doc_reg_path = Path(PATHS["TRICHEF_DOC_CACHE"]) / "registry.json"
    if doc_reg_path.exists():
        try:
            reg = json.loads(doc_reg_path.read_text(encoding="utf-8"))
            for _key, info in reg.items():
                orig = info.get("abs") or info.get("staged", "")
                items.append({
                    "file_path":  orig,
                    "file_name":  Path(orig).name if orig else _key,
                    "file_type":  "doc",
                    "chunk_count": info.get("pages", 1),
                    "source":     "trichef",
                })
        except Exception:
            pass

    return items


def _trichef_stats() -> dict[str, dict]:
    """TRI-CHEF image/doc/video/audio 파일 수 / 청크 수 통계."""
    from config import PATHS
    import numpy as np

    files = _trichef_indexed_files()
    stats: dict[str, dict] = {
        "image": {"file_count": 0, "chunk_count": 0},
        "doc":   {"file_count": 0, "chunk_count": 0},
        "video": {"file_count": 0, "chunk_count": 0},
        "audio": {"file_count": 0, "chunk_count": 0},
    }
    for f in files:
        t = f["file_type"]
        if t in stats:
            stats[t]["file_count"]  += 1
            stats[t]["chunk_count"] += f.get("chunk_count", 1)

    # Movie (TRI-CHEF AV) — npy 캐시에서 직접 집계
    try:
        movie_dir = Path(PATHS["TRICHEF_MOVIE_CACHE"])
        re_npy = movie_dir / "cache_movie_Re.npy"
        reg_path = movie_dir / "registry.json"
        if re_npy.exists():
            arr = np.load(re_npy)
            chunk_count = int(arr.shape[0])
            file_count = 0
            if reg_path.exists():
                reg = json.loads(reg_path.read_text(encoding="utf-8"))
                file_count = len(reg)
            stats["video"] = {"file_count": file_count, "chunk_count": chunk_count}
    except Exception:
        pass

    # Music (TRI-CHEF AV) — npy 캐시에서 직접 집계
    try:
        music_dir = Path(PATHS["TRICHEF_MUSIC_CACHE"])
        re_npy = music_dir / "cache_music_Re.npy"
        reg_path = music_dir / "registry.json"
        if re_npy.exists():
            arr = np.load(re_npy)
            chunk_count = int(arr.shape[0])
            file_count = 0
            if reg_path.exists():
                reg = json.loads(reg_path.read_text(encoding="utf-8"))
                file_count = len(reg)
            stats["audio"] = {"file_count": file_count, "chunk_count": chunk_count}
    except Exception:
        pass

    return stats


# ── 인덱싱된 파일 목록 ────────────────────────────────────

@files_bp.get("/indexed")
def indexed():
    """인덱싱된 모든 파일 목록 (레거시 + TRI-CHEF, 파일별 청크 수 포함)."""
    from db.vector_store import get_indexed_files
    try:
        data = get_indexed_files()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # TRI-CHEF 파일 병합 (중복 방지: file_path 기준)
    try:
        trichef = _trichef_indexed_files()
        existing_paths = {f["file_path"] for f in data}
        for f in trichef:
            if f["file_path"] not in existing_paths:
                data.append(f)
    except Exception:
        pass

    # 파일 크기·존재 여부 추가
    for item in data:
        fp = item.get("file_path", "")
        try:
            stat = os.stat(fp)
            item["size"]   = stat.st_size
            item["exists"] = True
        except OSError:
            item["size"]   = None
            item["exists"] = False
    return jsonify({"files": data, "total": len(data)})


# ── 타입별 통계 ──────────────────────────────────────────

@files_bp.get("/stats")
def stats():
    """타입별 파일 수·청크 수 통계 (레거시 + TRI-CHEF 합산)."""
    from db.vector_store import get_indexed_files, count, COLLECTION_MAP
    try:
        all_files = get_indexed_files()
        by_type: dict[str, dict] = {}
        for t in COLLECTION_MAP:
            by_type[t] = {"file_count": 0, "chunk_count": 0}
        for f in all_files:
            t = f["file_type"]
            if t not in by_type:
                by_type[t] = {"file_count": 0, "chunk_count": 0}
            by_type[t]["file_count"]  += 1
            by_type[t]["chunk_count"] += f.get("chunk_count", 0)

        # TRI-CHEF image/doc 통계 병합
        tc_stats = _trichef_stats()
        for t, s in tc_stats.items():
            if t not in by_type:
                by_type[t] = {"file_count": 0, "chunk_count": 0}
            by_type[t]["file_count"]  += s["file_count"]
            by_type[t]["chunk_count"] += s["chunk_count"]

        # TRI-CHEF 파일들 (chunk_count 합산에서 제외되지 않도록 all_files 에도 합산)
        tc_files = _trichef_indexed_files()
        existing_paths = {f["file_path"] for f in all_files}
        for f in tc_files:
            if f["file_path"] not in existing_paths:
                all_files.append(f)

        # by_type 가 권위 있는 카운트 — total 도 동일 합산으로 일치 보장.
        # (legacy all_files 와 tc_files dedup 결과가 by_type 합과 어긋날 수 있어
        #  사용자 UI 가 '서로 다른 두 합' 을 보게 되는 P1 버그를 차단)
        total_chunks = sum(v["chunk_count"] for v in by_type.values())
        total_files  = sum(v["file_count"]  for v in by_type.values())
        return jsonify({
            "by_type":      by_type,
            "total_files":  total_files,
            "total_chunks": total_chunks,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── 파일 상세 (전체 청크 텍스트) ─────────────────────────

@files_bp.get("/detail")
def detail():
    """
    GET /api/files/detail?path=C:/...

    해당 파일의 모든 청크 텍스트를 반환.
    video는 blip/stt 소스를 구분해서 반환.
    """
    file_path = request.args.get("path", "").strip()
    if not file_path:
        return jsonify({"error": "path is required"}), 400

    from db.vector_store import _get_collection, COLLECTION_MAP
    chunks: list[dict] = []
    file_type = None

    for t in COLLECTION_MAP:
        try:
            col = _get_collection(t)
            if col.count() == 0:
                continue
            res = col.get(
                where={"file_path": file_path},
                include=["metadatas"],
            )
            metas = res.get("metadatas") or []
            if metas:
                file_type = t
                for m in metas:
                    chunks.append({
                        "chunk_index":  m.get("chunk_index", 0),
                        "chunk_text":   m.get("chunk_text", ""),
                        "chunk_source": m.get("chunk_source", ""),  # video: blip|stt
                    })
        except Exception:
            continue

    if not chunks:
        return jsonify({"file_path": file_path, "file_type": file_type, "chunks": [], "full_text": ""})

    # 청크 순서 정렬
    chunks.sort(key=lambda c: (c.get("chunk_source", ""), c.get("chunk_index", 0)))

    # 중복 제거 (양방향 청킹으로 겹치는 텍스트 존재)
    seen: set[str] = set()
    unique: list[dict] = []
    for c in chunks:
        key = c["chunk_text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    # 전체 텍스트 조합
    if file_type == "video":
        blip_parts = [c["chunk_text"] for c in unique if c.get("chunk_source") == "blip"]
        stt_parts  = [c["chunk_text"] for c in unique if c.get("chunk_source") != "blip"]
        full_text = ""
        if blip_parts:
            full_text += "[프레임 캡션]\n" + " ".join(blip_parts)
        if stt_parts:
            if full_text:
                full_text += "\n\n"
            full_text += "[음성 텍스트]\n" + " ".join(stt_parts)
    else:
        full_text = " ".join(c["chunk_text"] for c in unique)

    return jsonify({
        "file_path": file_path,
        "file_type": file_type,
        "chunks":    unique,
        "full_text": full_text,
    })


# ── 파일 삭제 (ChromaDB에서 해당 파일 청크 전부 제거) ────────────

@files_bp.delete("/delete")
def delete():
    """
    DELETE /api/files/delete
    Body: { "file_path": "C:/..." }

    ChromaDB에서 해당 파일의 모든 청크를 삭제한다.
    TRI-CHEF 파일이면 레지스트리와 스테이징 파일도 정리한다.
    원본 파일 자체는 건드리지 않는다.
    """
    data = request.get_json(silent=True) or {}
    file_path = data.get("file_path", "").strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    # TRI-CHEF 파일 삭제 시도 (레지스트리에서 찾으면 TRI-CHEF 경로로 처리)
    trichef_deleted = _delete_trichef_file(file_path)

    # 레거시 ChromaDB 삭제도 시도
    from db.vector_store import delete_file
    try:
        delete_file(file_path)
    except Exception:
        pass

    return jsonify({"ok": True, "file_path": file_path, "trichef": trichef_deleted})


def _delete_trichef_file(orig_path: str) -> bool:
    """TRI-CHEF 레지스트리에서 원본 경로로 항목 찾아 삭제."""
    import shutil
    from config import PATHS

    deleted = False
    for cache_name, is_doc in (("TRICHEF_IMG_CACHE", False), ("TRICHEF_DOC_CACHE", True)):
        reg_path = Path(PATHS[cache_name]) / "registry.json"
        if not reg_path.exists():
            continue
        try:
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            # 원본 경로가 일치하는 항목 찾기
            to_remove = [k for k, v in reg.items()
                         if v.get("abs") == orig_path or v.get("staged") == orig_path]
            if not to_remove:
                continue
            for k in to_remove:
                info = reg.pop(k)
                # 스테이징 파일 삭제
                staged = info.get("staged")
                if staged:
                    try:
                        Path(staged).unlink(missing_ok=True)
                    except Exception:
                        pass
            reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
            deleted = True
        except Exception:
            continue
    return deleted


