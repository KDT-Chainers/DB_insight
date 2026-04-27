# Admin UI 통합 계획서 — Doc/Img + Movie/Rec

> 현재 `/api/admin/ui` (admin.html) 는 `doc_page` / `image` 두 도메인에 대한
> 전수(top-N) 검사 UI를 제공한다. Wave-6 에서 도입된 **Movie/Music (AV)** 도메인도
> 동일 UI에서 검색·미리보기·신뢰도 확인할 수 있도록 통합한다.

## 0. 현황 스냅샷 (2026-04-24)

| 항목 | Doc/Img | Movie/Rec |
|---|---|---|
| 검색 API | `/api/trichef/search` (unified) | `/api/trichef/search` (AV 분기) |
| 관리자 API | `/api/admin/inspect` (per-row) | **없음 — 추가 필요** |
| 프리뷰 API | `/api/admin/file` (image / doc PDF page) | **없음 — 추가 필요** |
| UI 카드 | 썸네일 + 지표 + 원문 excerpt | **없음** |
| 결과 단위 | 페이지/이미지 1장 | 파일 1건 + 상위 세그먼트 N개 |
| 지표 | dense/lexical/ASF/RRF/conf | dense/conf + segment[start,end,text] |

## 1. 목표

1. **단일 검색창** — 쿼리 1개로 doc_page / image / movie / music 모두 검색.
2. **도메인별 토글** — 체크박스 4개 (doc_page / image / movie / music).
3. **AV 카드** — 썸네일 대신 `<audio>` / `<video>` 플레이어, 상위 세그먼트 타임라인(클릭 → seek).
4. **미리듣기/미리보기 시간 제한** — 30s 세그먼트 단위로 `#t=start,end` fragment.
5. **통합 도메인 현황** — 상단 N / vocab / sparse / asf 뱃지 + AV 는 `segments` 수.
6. **기존 Doc/Img 동작 회귀 없음** — 동일 쿼리·도메인에서 기존 결과 unchanged.

## 2. 비목표 (Out of Scope)

- AV 도메인의 lexical / ASF 채널 (현재 없음 — dense only).
- AV reranker (BGE-reranker-v2-m3 는 text 전용 → STT text 는 가능하나 별도 wave).
- 영상 frame 썸네일 (movie 썸네일 추출 파이프라인 미구현 — Wave-7).

## 3. 아키텍처

```
┌─────────────────── admin.html (single page) ──────────────────┐
│ [검색창] [도메인 토글 ×4]  [top-N]  [옵션 (lex/asf/rerank)]   │
│ ─────────────────────────────────────────────────────────────  │
│  domains = [...checked]                                        │
│                                                                │
│  ┌── doc_page in domains ──┐                                   │
│  │ POST /api/admin/inspect │→ rows[] (기존)                   │
│  └──────────────────────────┘                                   │
│  ┌── image in domains ─────┐                                   │
│  │ POST /api/admin/inspect │→ rows[] (기존)                   │
│  └──────────────────────────┘                                   │
│  ┌── movie|music in domains ┐                                  │
│  │ POST /api/admin/inspect_av│→ files[] + segments[]  (신규)  │
│  └───────────────────────────┘                                  │
│                                                                │
│  merge & sort by confidence → render cards                    │
│    · doc_page / image  → image thumb + excerpt                │
│    · movie / music     → <video>/<audio> + timeline           │
└────────────────────────────────────────────────────────────────┘
```

## 4. 백엔드 변경 (trichef_admin.py)

### 4.1 신규 엔드포인트 `POST /api/admin/inspect_av`

요청:
```json
{ "query": "공부 방법", "domain": "music", "top_n": 30, "top_segments": 5 }
```

응답:
```json
{
  "domain": "music",
  "query": "공부 방법",
  "total": 270,           // 전체 segment 수
  "returned": 12,         // 집계된 파일 수
  "calibration": {"mu_null": 0.44, "sigma_null": 0.08, "abs_threshold": 0.57},
  "files": [
    {
      "rank": 1,
      "file_path": "YS_1주/공부 방법 요청 교수님 답변 - 민호.m4a",
      "file_name": "공부 방법 요청 교수님 답변 - 민호.m4a",
      "score": 0.678,
      "confidence": 0.751,
      "z_score": 2.95,
      "segments": [
        {"rank":1, "start_sec": 0.0, "end_sec": 30.0,
         "score": 0.678, "text": "안녕하세요…", "type":"stt"},
        ...
      ]
    },
    ...
  ]
}
```

구현 요지:
```python
@bp_admin.post("/inspect_av")
def inspect_av():
    body = request.get_json(force=True)
    q = body.get("query","").strip()
    dom = body.get("domain","music")
    top_n = int(body.get("top_n", 30))
    top_segs = int(body.get("top_segments", 5))
    if dom not in ("movie","music"):
        return jsonify({"error":"AV domain only"}), 400
    e = _engine()
    if dom not in e._cache:
        return jsonify({"error": f"domain {dom} 캐시 없음"}), 400
    res = e.search_av(q, domain=dom, topk=top_n, top_segments=top_segs)
    cal = calibration.get_thresholds(dom)
    mu, sig = cal["mu_null"], max(cal["sigma_null"], 1e-9)
    files = []
    for rank, r in enumerate(res, 1):
        z = (r.score - mu) / sig
        files.append({
            "rank": rank,
            "file_path": r.file_path,
            "file_name": r.file_name,
            "score": r.score, "confidence": r.confidence, "z_score": z,
            "segments": [dict(rank=i+1, **s) for i, s in enumerate(r.segments)],
        })
    N_total = len(e._cache[dom]["segments"])
    return jsonify({"domain":dom, "query":q, "total":N_total,
                    "returned":len(files),
                    "calibration": {"mu_null":mu, "sigma_null":sig,
                                    "abs_threshold": cal["abs_threshold"]},
                    "files": files})
```

### 4.2 `GET /api/admin/file` 확장 — AV 파일 서빙

현재 `image` / `doc_page` 만 지원. `movie` / `music` 추가:
```python
if domain == "music":
    cand = Path(PATHS["RAW_DB"]) / "Rec" / doc_id
elif domain == "movie":
    cand = Path(PATHS["RAW_DB"]) / "Movie" / doc_id
```
- mimetype 은 `mimetypes.guess_type` 으로 판정 (`audio/mp4`, `audio/wav`, `video/mp4`, …).
- `send_file` 에 `conditional=True` 설정 → 브라우저 HTTP Range 요청 지원 (seek 가능).

### 4.3 `GET /api/admin/domains` 확장

기존 image/doc_page 만 나열. AV 추가:
```python
for dom in ("movie","music"):
    if dom in e._cache:
        d = e._cache[dom]
        out[dom] = {"count": len(d["segments"]),
                    "vocab_size": 0, "has_sparse": False, "has_asf": False,
                    "kind": "av"}
```

## 5. 프론트엔드 변경 (admin.html)

### 5.1 옵션 영역 확장
```html
<label><input type="checkbox" id="d-doc_page" checked> doc_page</label>
<label><input type="checkbox" id="d-image" checked> image</label>
<label><input type="checkbox" id="d-movie"> movie</label>       <!-- 신규 -->
<label><input type="checkbox" id="d-music"> music</label>       <!-- 신규 -->
<label>세그먼트 N <input type="number" id="topseg" value="5" min="1" max="20"></label>
```

### 5.2 검색 로직 분기
```js
const AV_DOMAINS = new Set(['movie','music']);
for (const dom of domains) {
  if (AV_DOMAINS.has(dom)) {
    const r = await fetch(`${API_BASE}/api/admin/inspect_av`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({query:q, domain:dom, top_n:topN, top_segments:topSeg}),
    });
    const data = await r.json();
    perDom[dom] = {count:data.total, returned:data.returned, cal:data.calibration};
    for (const f of data.files) {
      results.push({...f, domain:dom, kind:'av', id:f.file_path,
                    filename:f.file_name, rrf:0});
    }
  } else {
    /* 기존 inspect 로직 */
  }
}
// 정렬 기준을 confidence 로 변경 (rrf 는 AV 없음)
results.sort((a,b) => (b.confidence||0) - (a.confidence||0));
```

### 5.3 카드 렌더 분기
```js
function card(it){
  if (it.kind === 'av') return avCard(it);
  /* 기존 image/doc_page 카드 */
}

function avCard(it){
  const isVideo = it.domain === 'movie';
  const url = `${API_BASE}/api/admin/file?domain=${it.domain}&id=${encodeURIComponent(it.id)}`;
  const player = isVideo
    ? `<video src="${url}" controls preload="metadata" style="width:100%;max-height:200px"></video>`
    : `<audio src="${url}" controls preload="metadata" style="width:100%"></audio>`;
  const segs = (it.segments||[]).map(s =>
    `<button class="seg-btn" data-t="${s.start_sec}"
       title="${escapeHtml(s.text||'').slice(0,200)}">
       ${fmtTime(s.start_sec)}-${fmtTime(s.end_sec)}
       · s=${s.score.toFixed(3)}
     </button>`
  ).join('');
  return `<div class="card av-card" data-url="${url}">
    <div class="rank">#${it.global_rank}</div>
    <div class="av-player">${player}</div>
    <div class="body">
      <div class="badges">
        <span class="badge domain-${it.domain}">${it.domain}</span>
      </div>
      <div class="title">${escapeHtml(it.filename)}</div>
      <div class="path">${escapeHtml(it.file_path)}</div>
      <div class="metrics">
        <div class="metric"><span class="k">신뢰도</span> <span class="v">${(it.confidence*100).toFixed(1)}%</span></div>
        <div class="metric"><span class="k">score</span> <span class="v">${it.score.toFixed(3)}</span></div>
        <div class="metric"><span class="k">z</span> <span class="v">${(it.z_score||0).toFixed(2)}</span></div>
      </div>
      <div class="segments">${segs}</div>
    </div>
  </div>`;
}
```

### 5.4 세그먼트 클릭 → 플레이어 seek
```js
output.addEventListener('click', ev => {
  const btn = ev.target.closest('.seg-btn');
  if (!btn) return;
  const card = btn.closest('.card');
  const p = card.querySelector('audio, video');
  if (p) { p.currentTime = parseFloat(btn.dataset.t); p.play(); }
});
```

### 5.5 스타일 추가
```css
.av-player{padding:8px 12px;background:#0b1220}
.av-card .segments{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.seg-btn{font-size:10px;padding:3px 8px;background:#0b1220;color:#cbd5e1;
         border:1px solid var(--border);border-radius:4px;cursor:pointer;font-family:monospace}
.seg-btn:hover{background:var(--accent);color:#fff}
.badge.domain-movie{background:#7c2d12;color:#ffedd5;border-color:#ea580c}
.badge.domain-music{background:#1e40af;color:#dbeafe;border-color:#3b82f6}
```

### 5.6 `fmtTime` 유틸
```js
function fmtTime(s){const m=Math.floor(s/60), r=Math.floor(s%60);
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`;}
```

## 6. 테스트 계획

### 6.1 Unit / Route
- [ ] `curl -X POST /api/admin/inspect_av -d '{"query":"공부","domain":"music","top_n":5}'`
  → `files[0].confidence > 0.5` AND `segments[0].text.length > 0`.
- [ ] `curl -I /api/admin/file?domain=music&id=<path>` → `Accept-Ranges: bytes` 헤더 존재.
- [ ] `curl /api/admin/domains` 응답에 `movie`, `music` 키 포함.

### 6.2 UI 수동
- [ ] 브라우저 `/api/admin/ui` → music 체크박스 ON → "공부 방법" 검색 → 카드 하나 이상 표시.
- [ ] 카드의 `<audio>` 플레이 → 소리 재생. 첫 세그먼트 버튼 클릭 → 해당 구간으로 seek.
- [ ] doc_page / image / music 동시 선택 시 4종류 카드가 confidence 순으로 interleave.
- [ ] music 미체크 시 기존 Doc/Img UI 동작 동일 (회귀 없음).

### 6.3 회귀 벤치
- `scripts/bench_w5.py --regression` PASS 유지.
- AV 전용 벤치 `scripts/bench_av.py` (신규) — music 고정 쿼리 5개에 대해
  `top1 hits ≥ 1 AND confidence ≥ 0.5` 통과.

## 7. 단계별 구현 (3 commits 권장)

| # | 커밋 | 범위 |
|---|---|---|
| 1 | feat(admin): add `/api/admin/inspect_av` + file serving for AV | 백엔드만, curl 테스트 |
| 2 | feat(admin-ui): movie/music 카드·플레이어·세그먼트 버튼 추가 | admin.html |
| 3 | test(admin): bench_av.py + regression 통합 | scripts |

## 8. 리스크 & 완화

| 리스크 | 완화책 |
|---|---|
| 대용량 동영상(>100MB) 로딩으로 UI 지연 | `<video preload="metadata">`, Range 요청 기본값 |
| 파일명 한글 URL 인코딩 깨짐 | `encodeURIComponent(id)` 필수 + 서버 `send_file(conditional=True)` |
| music calibration 없음 → abs_thr=0.5 로 zero-hit | Wave-6 내 `calibrate_crossmodal("music", …)` 선행 |
| STT 텍스트에 비한글(영어/중국어) 혼입 | type 뱃지(`stt`) 유지. Wave-7 에서 언어 필터 추가 |
| 영상 썸네일 부재 → 카드 비어 보임 | `<video poster>` 없이 브라우저 기본 프레임. 추후 ffmpeg 추출 |

## 9. 의존성 & 전제

- `segments.json` 에 `file_path`, `file_name`, `start_sec`, `end_sec`, `stt_text` 필드 존재
  (`_build_av_entry` 가 schema 정규화하여 보장).
- 원본 오디오/영상이 `Data/raw_DB/Rec/`, `Data/raw_DB/Movie/` 하위에 존재.
- Flask `send_file(..., conditional=True)` 가 Range 응답 생성 (Flask ≥ 0.12).

## 10. 완료 정의 (DoD)

1. 동일 검색어로 4개 도메인 혼합 검색 결과가 confidence 순으로 정렬되어 표시.
2. AV 카드에서 재생·시크 가능. 세그먼트 타임라인 클릭 시 해당 구간 즉시 재생.
3. `bench_w5.py --regression` PASS + `bench_av.py` PASS.
4. Doc/Img 기존 카드 표시 내용·지표 동일 (회귀 없음).
