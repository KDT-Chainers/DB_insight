# Qwen2-VL-2B-Instruct vs Qwen2.5-3B-Instruct 비교

## 핵심 특성 요약

| 항목 | Qwen2-VL-2B-Instruct | Qwen2.5-3B-Instruct |
|------|----------------------|---------------------|
| **모달리티** | 멀티모달 (텍스트 + 이미지 + 영상) | 텍스트 전용 LLM |
| **파라미터** | ~2B (ViT 포함 시 실질적으로 더 큼) | 3.09B (비임베딩 2.77B) |
| **컨텍스트** | 이미지 해상도 가변 (4~16384 토큰) | 32,768 토큰 |
| **레이어 수** | — | 36 |
| **Attention** | M-ROPE (멀티모달) | GQA (16Q / 2KV) |
| **라이선스** | Apache 2.0 | Apache 2.0 |
| **월간 다운로드** | 360만 | 961만 |

---

## 모달리티 (결정적 차이)

| | Qwen2-VL-2B | Qwen2.5-3B |
|---|---|---|
| **이미지 입력** | ✅ 핵심 강점 | ❌ 불가 |
| **영상 입력** | ✅ 20분 이상 지원 | ❌ 불가 |
| **순수 텍스트 처리** | 가능하나 비효율 | ✅ 최적화 |
| **RAG / 텍스트 챗봇** | 제한적 | ✅ 최적 |
| **주 용도** | 이미지·문서 내 텍스트 이해, OCR, 영상 분석 | 텍스트 생성·이해·추론 |

---

## 한국어 성능

| | Qwen2-VL-2B | Qwen2.5-3B |
|---|---|---|
| **이미지 내 한국어 OCR** | ✅ 지원 (MTVQA SOTA) | — |
| **KMMLU (한국어 지식)** | 미공개 (VLM 특화) | ~40점 중반 추정 (7B=46.59) |
| **한국어 생성 유창성** | 기본 수준 | 상대적으로 우수 |
| **다국어 IFEval** | MTVQA 기준 SOTA | 8개 언어 지원 (한국어 포함) |

> **시나리오별 우위**
> - 이미지/문서 내 한국어 추출 → **Qwen2-VL-2B**
> - 한국어 텍스트 생성·요약·QA → **Qwen2.5-3B**

---

## 영어 성능 벤치마크

| 벤치마크 | Qwen2-VL-2B | Qwen2.5-3B |
|---------|:-----------:|:----------:|
| MMLU | — | 65.6 |
| MMLU-Pro | — | 34.6 |
| BBH | — | 56.3 |
| MATH | — | 42.6 |
| GSM8K | — | 79.1 |
| HumanEval (코딩) | — | 42.1 |
| MBPP | — | 57.1 |
| DocVQA | **90.1** | — |
| OCRBench | **794/1000** | — |
| TextVQA | 79.7 | — |
| MMBench-EN | 74.9 | — |
| RealWorldQA | 62.9 | — |
| MMMU | 41.1 | — |

> 두 모델은 서로 다른 도메인을 커버하므로 직접 수치 비교보다 **용도별 선택**이 중요함

---

## 효율성 / 경량성

| | Qwen2-VL-2B | Qwen2.5-3B |
|---|---|---|
| **실질 메모리** | ViT 포함으로 실제 메모리 더 큼 | 순수 LLM → 더 가벼움 |
| **추론 속도** | 이미지 토큰 처리 오버헤드 존재 | 텍스트만 처리 → 빠름 |
| **모바일/엣지** | 설계 목표이나 ViT로 제약 있음 | 양자화(4-bit) 시 매우 작음 |
| **Flash Attention 2** | ✅ 지원 | ✅ 지원 |
| **BF16** | ✅ | ✅ |
| **동적 해상도** | ✅ (min/max_pixels 조절 가능) | — |

---

## 아키텍처 특징

### Qwen2-VL-2B-Instruct
- **Naive Dynamic Resolution**: 임의 해상도 이미지를 동적 토큰 수로 변환
- **M-ROPE (Multimodal Rotary Position Embedding)**: 1D 텍스트, 2D 이미지, 3D 영상 위치 정보 통합
- 이미지 토큰 범위: 4~16,384 (기본값 256~1280 조절 권장)

### Qwen2.5-3B-Instruct
- **RoPE + SwiGLU + RMSNorm**: 최신 LLM 표준 아키텍처
- **GQA (Grouped Query Attention)**: 16 Q heads / 2 KV heads → 메모리 효율
- **Tied word embeddings**: 파라미터 절약
- 컨텍스트 32,768 토큰 (생성 8,192 토큰)

---

## 한계점

### Qwen2-VL-2B
- 영상 내 오디오 미지원
- 학습 데이터 컷오프: 2023년 6월
- 복잡한 다단계 지시 처리 약함
- 복잡한 장면에서 객체 계수 부정확
- 3D 공간 추론 약함

### Qwen2.5-3B
- 이미지/영상 입력 불가
- 소형 모델 특성상 복잡한 추론에 한계
- KMMLU 기준 한국어 전문 지식은 대형 모델 대비 약함

---

## 선택 가이드

```
이미지/PDF/문서에서 한국어 텍스트 추출  → Qwen2-VL-2B-Instruct
영상 분석, 표 OCR, 이미지 QA           → Qwen2-VL-2B-Instruct

한국어 텍스트 QA / 요약 / 생성         → Qwen2.5-3B-Instruct
RAG 파이프라인 (텍스트 임베딩)         → Qwen2.5-3B-Instruct
코딩 / 수학 추론                       → Qwen2.5-3B-Instruct
메모리 최소화 / 엣지 배포              → Qwen2.5-3B-Instruct
```

---

## 결론

| 판단 기준 | 우위 모델 |
|---------|---------|
| 이미지·문서 처리 | **Qwen2-VL-2B** |
| 한국어 텍스트 생성 품질 | **Qwen2.5-3B** |
| 순수 언어 추론 성능 | **Qwen2.5-3B** |
| 메모리 효율 (텍스트 전용) | **Qwen2.5-3B** |
| 멀티모달 경량 배포 | **Qwen2-VL-2B** |

**Qwen2-VL-2B**는 "시각 정보 + 텍스트"가 결합된 업무(OCR, 문서 파싱, 표 인식)에 특화되어 있고,
**Qwen2.5-3B**는 순수 텍스트 파이프라인에서 동급 파라미터 모델 대비 뛰어난 언어 능력과 경량성을 제공한다.

한국어 텍스트 처리 품질 단독 비교로는 **Qwen2.5-3B**가 우세하지만,
이미지 내 한국어 인식이 필요한 경우 **Qwen2-VL-2B**가 유일한 선택이다.

---

## 참고 자료

- [Qwen2-VL-2B-Instruct - Hugging Face](https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct)
- [Qwen2.5-3B-Instruct - Hugging Face](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)
- [Qwen2.5-LLM 공식 블로그 (벤치마크)](https://qwenlm.github.io/blog/qwen2.5-llm/)
- [Qwen2-VL 공식 블로그](https://qwenlm.github.io/blog/qwen2-vl/)
- [Qwen2.5 Technical Report (arXiv:2412.15115)](https://arxiv.org/abs/2412.15115)
- [Qwen2-VL Technical Report (arXiv:2409.12191)](https://arxiv.org/abs/2409.12191)
