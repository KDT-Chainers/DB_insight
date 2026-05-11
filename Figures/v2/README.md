# Figures / v2  —  Tri-CHEF 발표용 시각화 자료

> v1 대비 콘텐츠 밀도·정교도·수학적 충실도를 업그레이드한 publication-grade
> 도면 묶음. 2D + 3D 혼합. DPI=300, Malgun Gothic + matplotlib mathtext.

## 도면 색인 (총 10장)

| # | 파일 | 주제 | 형식 |
|---|------|------|------|
| 01 | `fig01_re_im_z_rationale.png` | Re=SigLIP2 / Im=BGE-M3 / Z=DINOv2-L 선택 근거 (3-card) | 2D |
| 02 | `fig02_di_mr_pipeline.png` | DI_TriCHEF vs MR_TriCHEF 파이프라인 좌우 비교 | 2D |
| 03 | `fig03_domain_feature_matrix.png` | 도메인 × 기능 적용 매트릭스 + hit@5 막대 | 2D |
| 04 | `fig04_gram_schmidt_3d.png` | Gram-Schmidt 직교화 before/after | **3D** + 2D |
| 05 | `fig05_hermitian_landscape_3d.png` | Hermitian 점수 지형 + α 등고선 + α-β 격자 | **3D** + 2D |
| 06 | `fig06_calibration_null_dist.png` | Null vs Match 분포 + z-score sigmoid + 파라미터 표 | 2D |
| 07 | `fig07_beta_distribution.png` | Beta(α,β) 적합 — relevant vs irrelevant 결정 경계 | 2D |
| 08 | `fig08_phase_argand_3d.png` | Argand 위상 게이팅 + 신뢰도 표면 + θ 분포 | 2D + **3D** |
| 09 | `fig09_ablation_grouped.png` | ASF · Rerank · LangGraph ablation + 결론 패널 | 2D |
| 10 | `fig10_phase_polar_3d.png` | Phase Ridge polar (4 도메인) + 3D 분리도 막대 | 2D + **3D** |

## 적용한 핵심 수학적 원리

- **Hermitian Score**: $s(q,d)=\sqrt{A^2+(\alpha B)^2+(\beta C)^2}$,  $\alpha=0.4$, $\beta=0.2$
- **Gram-Schmidt 직교화**: $Im_\perp$, $Z_\perp$ 로 채널 중복 제거 (fig04)
- **Calibration**: $\tau = \mu_{null} + 1.645\,\sigma_{null}$  (FAR=0.05, fig06)
- **Beta MLE**: scipy.stats.beta로 relevant/irrelevant 분포 적합 (fig07)
- **Phase 게이팅**: $\theta = \mathrm{arctan2}(Im_\perp\cdot q,\; Re\cdot q)$  (fig08, 10)

## 데이터 출처 (실측)

```
publication/paper/_asf_ablation_results.json
publication/paper/_rerank_ablation_results.json
publication/paper/_langgraph_ablation_results.json
publication/paper/_phase_ridge_results.json
```

## 재생성

```powershell
cd Figures/v2
python fig01_re_im_z_rationale.py
python fig02_di_mr_pipeline.py
# ... 또는 한 번에:
ls fig*.py | ForEach-Object { python $_ }
```

## 디자인 표준

- DPI 300, A4·발표용 16:9 양립
- 도메인 색상 (`_common.py:DOMAIN_COLORS`):
  - Doc `#4C72B0` · Img `#DD8452` · Movie `#55A868` · Rec `#C44E52` · BGM `#8172B3`
- 축 색상 (`_common.py:AXIS_COLORS`):
  - Re `#2E7D52` · Im `#1565C0` · Z `#8E24AA`
- 한글 폰트: Malgun Gothic, 수식: matplotlib mathtext

— Team Chainers · 2026
