#!/usr/bin/env bash
# scripts/run_all_miracl_baselines.sh
# MIRACL-ko 5개 baseline 순차 실행 wrapper.
#
# 사용법:
#   bash scripts/run_all_miracl_baselines.sh [--top-k 100] [--batch-size 32]
#
# 전제 조건:
#   pip install -r requirements_miracl.txt
#   (BM25) Java 11+ 설치 및 BM25 인덱스 사전 빌드 필요
#
# 결과 파일: bench_results/miracl_ko_{system}_{YYYYMMDD_HHMMSS}.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="${PYTHON:-python}"

# ── 인자 파싱 ─────────────────────────────────────────────────────────────────
TOP_K=100
BATCH_SIZE=32
SYSTEMS=("bgem3" "me5" "mcontriever" "mdpr" "bm25")

while [[ $# -gt 0 ]]; do
    case "$1" in
        --top-k)      TOP_K="$2";      shift 2 ;;
        --batch-size) BATCH_SIZE="$2"; shift 2 ;;
        --systems)    IFS=',' read -r -a SYSTEMS <<< "$2"; shift 2 ;;
        *)            echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo "========================================================"
echo "  MIRACL-ko Baseline Evaluation Suite"
echo "  systems   : ${SYSTEMS[*]}"
echo "  top_k     : $TOP_K"
echo "  batch_size: $BATCH_SIZE"
echo "  results → $ROOT_DIR/bench_results/"
echo "========================================================"

FAILED=()
PASSED=()

# ── 5개 baseline 순차 실행 ─────────────────────────────────────────────────────
for SYS in "${SYSTEMS[@]}"; do
    echo ""
    echo "-------- [$SYS] 시작 $(date '+%H:%M:%S') --------"
    if $PYTHON "$SCRIPT_DIR/eval_miracl_ko.py" \
        --system "$SYS" \
        --top-k "$TOP_K" \
        --batch-size "$BATCH_SIZE"; then
        echo "[$SYS] 완료 ✓"
        PASSED+=("$SYS")
    else
        echo "[$SYS] 실패 ✗ (종료 코드: $?)"
        FAILED+=("$SYS")
    fi
done

# ── 결과 표 생성 ────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  결과 요약"
echo "========================================================"

RESULTS_DIR="$ROOT_DIR/bench_results"
printf "%-15s %-12s %-12s %-12s  %s\n" \
    "System" "nDCG@10" "R@${TOP_K}" "MRR" "File"
printf "%-15s %-12s %-12s %-12s  %s\n" \
    "---------------" "------------" "------------" "------------" "----"

for SYS in "${SYSTEMS[@]}"; do
    # 가장 최근 결과 파일 탐색
    LATEST=$(ls -t "$RESULTS_DIR"/miracl_ko_"${SYS}"_*.json 2>/dev/null | head -1 || true)
    if [[ -z "$LATEST" ]]; then
        printf "%-15s %-12s %-12s %-12s  %s\n" \
            "$SYS" "N/A" "N/A" "N/A" "(결과 없음)"
        continue
    fi

    NDCG=$(python -c "
import json, sys
d = json.load(open('$LATEST', encoding='utf-8'))
print(d.get('aggregated', {}).get('ndcg@10', 'N/A'))
" 2>/dev/null || echo "N/A")

    RECALL=$(python -c "
import json, sys
d = json.load(open('$LATEST', encoding='utf-8'))
agg = d.get('aggregated', {})
key = [k for k in agg if k.startswith('r@')]
print(agg[key[0]] if key else 'N/A')
" 2>/dev/null || echo "N/A")

    MRR=$(python -c "
import json, sys
d = json.load(open('$LATEST', encoding='utf-8'))
print(d.get('aggregated', {}).get('mrr', 'N/A'))
" 2>/dev/null || echo "N/A")

    printf "%-15s %-12s %-12s %-12s  %s\n" \
        "$SYS" "$NDCG" "$RECALL" "$MRR" "$(basename "$LATEST")"
done

echo ""
echo "========================================================"
echo "  Paper TBD placeholder"
echo "========================================================"
echo "  아래 수치를 논문 Table 에 채워 넣으세요:"
echo ""
echo "  | System       | nDCG@10 | R@${TOP_K} | MRR    |"
echo "  |--------------|---------|--------|--------|"
for SYS in "${SYSTEMS[@]}"; do
    echo "  | $SYS$(printf '%*s' $((12-${#SYS})) '') | TBD     | TBD    | TBD    |"
done
echo ""

# ── 완료/실패 요약 ─────────────────────────────────────────────────────────────
echo "성공: ${PASSED[*]:-없음}"
echo "실패: ${FAILED[*]:-없음}"

if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo ""
    echo "일부 baseline 실패. 로그를 확인하고 재실행하세요:"
    for SYS in "${FAILED[@]}"; do
        echo "  python scripts/eval_miracl_ko.py --system $SYS --top-k $TOP_K"
    done
    exit 1
fi

echo ""
echo "모든 baseline 평가 완료."
