#!/usr/bin/env bash
# 7시간 무인 자동 chain — Doc 재구축 완료 후 다음 단계 순차 진행.
#
# 작업 순서:
#   1. Doc Im_body 재구축 완료 대기 (현재 진행 중)
#   2. Img 3-stage BLIP 캡션 재구축
#   3. ASF vocab + token_sets 4 도메인 재구축
#   4. Qwen 한국어 캡션 보강 (시간 여유 시)
#   5. 정합성 검증
#
# 각 단계 .bak 자동 백업. 한 단계 실패 시 다음 단계 그대로 진행 (||으로 연결).
# 사용자 절전 모드 진입 시 작업 중단되며 부팅 후 resume 가능.

set -u
cd "C:/yssong/KDT-FT-team3-Chainers/DB_insight"
export PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

LOG_DIR="md"
mkdir -p "$LOG_DIR"

echo "[auto_chain] 시작 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"

# === Step 1: Doc 재구축 완료 대기 ===
echo "[auto_chain] Step 1: Doc Im_body 재구축 완료 대기..." | tee -a "$LOG_DIR/_chain_master.log"
DOC_LOG="$LOG_DIR/_log_rebuild_doc.txt"
SECONDS=0
WAIT_LIMIT=$((180 * 60))   # 최대 3시간 대기
while ! grep -q "rc=" "$DOC_LOG" 2>/dev/null; do
    sleep 30
    if [ $SECONDS -ge $WAIT_LIMIT ]; then
        echo "[auto_chain] Doc 대기 timeout (3시간) — chain 중단" | tee -a "$LOG_DIR/_chain_master.log"
        exit 1
    fi
done
DOC_RC=$(grep "^rc=" "$DOC_LOG" | tail -1 | sed 's/rc=//')
echo "[auto_chain] Doc 재구축 종료 rc=$DOC_RC ($(date '+%H:%M:%S'))" | tee -a "$LOG_DIR/_chain_master.log"

# === Step 2: Img 3-stage 재구축 ===
echo "[auto_chain] Step 2: Img 3-stage BLIP 캡션 재구축 시작 $(date '+%H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"
python -u scripts/rebuild_img_3stage_caption.py > "$LOG_DIR/_log_img_3stage.txt" 2>&1
IMG_RC=$?
echo "[auto_chain] Img 3-stage 종료 rc=$IMG_RC ($(date '+%H:%M:%S'))" | tee -a "$LOG_DIR/_chain_master.log"

# === Step 3: ASF vocab 재구축 ===
echo "[auto_chain] Step 3: ASF vocab 4 도메인 재구축 시작 $(date '+%H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"
python -u scripts/rebuild_asf_vocab.py > "$LOG_DIR/_log_asf_vocab.txt" 2>&1
ASF_RC=$?
echo "[auto_chain] ASF vocab 종료 rc=$ASF_RC ($(date '+%H:%M:%S'))" | tee -a "$LOG_DIR/_chain_master.log"

# === Step 4: Qwen 한국어 캡션 보강 (스크립트 있을 때만) ===
if [ -f scripts/rebuild_qwen_korean_captions.py ]; then
    echo "[auto_chain] Step 4: Qwen 한국어 캡션 보강 시작 $(date '+%H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"
    python -u scripts/rebuild_qwen_korean_captions.py > "$LOG_DIR/_log_qwen_korean.txt" 2>&1
    QWEN_RC=$?
    echo "[auto_chain] Qwen 한국어 종료 rc=$QWEN_RC ($(date '+%H:%M:%S'))" | tee -a "$LOG_DIR/_chain_master.log"
fi

# === Step 5: 정합성 검증 ===
echo "[auto_chain] Step 5: 정합성 검증 $(date '+%H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"
python -u scripts/diagnose_consistency.py > "$LOG_DIR/_log_consistency_final.txt" 2>&1
DIAG_RC=$?
echo "[auto_chain] 정합성 검증 종료 rc=$DIAG_RC" | tee -a "$LOG_DIR/_chain_master.log"

echo "[auto_chain] 전체 chain 완료 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG_DIR/_chain_master.log"
echo "  Doc:  rc=$DOC_RC" | tee -a "$LOG_DIR/_chain_master.log"
echo "  Img:  rc=$IMG_RC" | tee -a "$LOG_DIR/_chain_master.log"
echo "  ASF:  rc=$ASF_RC" | tee -a "$LOG_DIR/_chain_master.log"
echo "  Diag: rc=$DIAG_RC" | tee -a "$LOG_DIR/_chain_master.log"
