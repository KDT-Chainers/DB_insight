# Tri-CHEF: Korean Multimodal Retrieval System

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
![Language](https://img.shields.io/badge/Language-Korean%20%2B%20Multilingual-brightgreen)
![Domains](https://img.shields.io/badge/Domains-4-blue)
![Status](https://img.shields.io/badge/Status-Research%20Prototype-orange)

**Tri-CHEF**: Complex-Hermitian Fusion of Heterogeneous Encoders for Korean Multimodal Retrieval

A deployed Korean multimodal retrieval system that fuses SigLIP2, BGE-M3, and DINOv2 encoders across four domains (Document, Image, Movie, Music) using complex-Hermitian representations and cross-modal calibration.

---

## Key Features

- **4-Domain Coverage**: Documents (PDF/HWP/Office), Images, Movies (MP4/AVI), and Music (WAV/MP3)
- **Complex-Hermitian Fusion**: 3-axis (Re/Im/Z) orthogonal representation with Gram-Schmidt orthogonalization
- **Heterogeneous Encoders**: SigLIP2 (Re), BGE-M3 (Im), DINOv2 (Z) with per-domain L₂-normalization
- **Cross-Modal Calibration**: Query-document mutual calibration with adaptive thresholds (μ/σ bounds)
- **Reproducible on 12GB GPU**: Tested with NVIDIA RTX 3060 (consumer-grade)
- **Korean-Aware Evaluation**: MIRACL-Ko corpus + in-house evaluation suite
- **Production Desktop App**: Electron + React frontend, Flask backend with ChromaDB vector store

---

## Architecture Overview

```
Raw Files (Doc/Img/Movie/Rec)
    │
    ├─→ [Ingest Pipeline]
    │   ├─ Text extraction (PDFMiner, python-docx, STT)
    │   ├─ Caption generation (Qwen2-VL)
    │   ├─ Frame sampling (adaptive for video)
    │   └─ 3-axis embedding
    │
    ├─→ [3-Axis Embedding]
    │   ├─ Re-axis: SigLIP2 (image-text alignment)
    │   ├─ Im-axis: BGE-M3 (multilingual dense + sparse)
    │   └─ Z-axis: DINOv2 (label-free visual structure)
    │
    ├─→ [Hermitian Scoring]
    │   └─ s(q,d) = √(A² + (αB)² + (βC)²) for Doc/Img
    │      or s(q,d) = √(A² + (αB)²)      for Movie/Rec
    │
    └─→ [Calibration & Ranking]
        ├─ Query-document mutual null calibration
        ├─ Adaptive thresholds (σ-bounded)
        └─ Top-K retrieval with confidence scores
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- CUDA 11.8+ (for GPU acceleration)
- 12GB+ GPU VRAM recommended (tested on RTX 3060)
- Node.js 18+ (for desktop app only)

### Installation

Clone the repository:
```bash
git clone https://github.com/Team-Chainers/DB_insight.git
cd DB_insight
```

Install Python dependencies:
```bash
pip install -r App/backend/requirements.txt
```

### Running the Backend

```bash
cd App/backend
python app.py
```

The backend will start on `http://127.0.0.1:5001`.

### Running the Desktop Application

Build and run the Electron app:
```bash
cd App/frontend
npm install
npm run dist
```

Execute the generated `.exe`:
```bash
./out/DB_insight\ 0.1.0.exe
```

Or for development mode:
```bash
npm run electron:dev
```

---

## Evaluation Results

### MIRACL-Ko (Korean Multilingual IR)

| Model | nDCG@10 | Recall@100 |
|-------|---------|------------|
| BM25  | 0.352   | 0.654      |
| BGE-M3 Dense | 0.441 | 0.748 |
| Tri-CHEF (This Work) | **0.452** | **0.763** |

**In-House Corpus (4 Domains, n=45,647 documents)**:

- Doc: nDCG=0.78 (caption-aware evaluation)
- Image: nDCG=0.76
- Movie: nDCG=0.67 (adaptive frame sampling)
- Music: nDCG=0.62 (Whisper-based STT)

---

## Repository Structure

```
DB_insight/
├── App/
│   ├── backend/                    # Flask API + embedders
│   │   ├── routes/                 # API endpoints
│   │   ├── embedders/              # Domain-specific pipelines
│   │   ├── db/                     # ChromaDB interface
│   │   └── app.py                  # Entry point
│   ├── frontend/                   # Electron + React UI
│   │   ├── src/                    # React components
│   │   ├── electron/               # Electron main/preload
│   │   └── package.json
│   └── admin_ui/                   # Calibration management UI
│
├── DI_TriCHEF/                     # Doc/Image domain implementation
│   ├── ingest/                     # Text extraction, captioning
│   ├── embedders/                  # SigLIP2/BGE-M3/DINOv2 loaders
│   ├── auto_calibration/           # Threshold adaptation
│   ├── reranker/                   # Post-processing
│   └── scripts/                    # Evaluation scripts
│
├── MR_TriCHEF/                     # Movie/Music domain implementation
│   ├── ingest/                     # Video frame sampling, STT
│   ├── embedders/                  # Audio/visual pipelines
│   ├── pipeline/                   # Incremental runners
│   └── docs/                       # Technical specs
│
├── Data/
│   ├── raw_DB/                     # User files (Doc/Img/Movie/Rec)
│   ├── extracted_DB/               # Text/caption cache
│   └── embedded_DB/                # ChromaDB + .npy vectors
│
├── publication/
│   ├── paper/                      # Academic papers (PDF)
│   │   ├── Tri-CHEF_paper_v1-2.pdf
│   │   └── figures/
│   └── slides/
│
├── scripts/
│   ├── baselines/                  # BM25, BGE-M3 baselines
│   └── eval_miracl_ko.py           # MIRACL-Ko evaluation
│
└── Docs/
    ├── Knowledge/                  # API specs, data contracts
    └── Agents/                     # Development guidelines
```

---

## API Endpoints Summary

### Search
- `GET /api/search?q=<query>` — Natural language search across all domains
- `GET /api/search?q=<query>&domain=<doc|img|movie|rec>` — Domain-specific search

### Indexing
- `POST /api/index/scan` — Scan folder for files
- `POST /api/index/start` — Start embedding pipeline
- `GET /api/index/status/{job_id}` — Check progress
- `POST /api/index/stop/{job_id}` — Cancel indexing

### File Management
- `GET /api/files/indexed` — List all indexed files
- `GET /api/files/stats` — Domain statistics (count by type)
- `GET /api/files/detail?path=<path>` — File chunks and metadata
- `POST /api/files/open` — Open file with system application
- `POST /api/files/open-folder` — Open folder in explorer

### Authentication
- `GET /api/auth/status` — Check password setup state
- `POST /api/auth/setup` — Initialize master password
- `POST /api/auth/verify` — Verify password
- `POST /api/auth/reset` — Change password

### History
- `GET /api/history` — Retrieve search history
- `DELETE /api/history` — Clear search history

Full API specification: See `Docs/Knowledge/API.md`

---

## Model Specifications

| Encoder | Axis | Dim | Domain | Purpose |
|---------|------|-----|--------|---------|
| SigLIP2 | Re | 768 | All | Cross-modal alignment |
| BGE-M3 | Im | 1024 | All | Multilingual dense + sparse |
| DINOv2 | Z | 1024 | Doc/Img/Movie | Label-free visual structure |
| Qwen2-VL | - | - | Doc/Img/Movie | Image captioning |
| Whisper-large-v3 | - | - | Movie/Music | Speech-to-text (Korean) |

All models are cached locally with SHA-256 verification. Per-domain gating excludes sparse (ASF) indexing on visual queries.

---

## Configuration

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|------------|
| GPU VRAM | 8GB | 12GB+ |
| CPU | Intel i5-10th Gen | Intel i7-12th Gen+ |
| RAM | 16GB | 32GB |
| Storage | 500GB | 1TB SSD |
| Network | WiFi 5G | Ethernet |

### Environment Variables

```bash
# Flask backend
export FLASK_ENV=production
export FLASK_PORT=5001
export CHROMA_DB_PATH=./Data/embedded_DB
export MAX_WORKERS=4

# GPU
export CUDA_VISIBLE_DEVICES=0
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
```

---

## Evaluation & Benchmarking

### Running MIRACL-Ko Evaluation

```bash
python scripts/eval_miracl_ko.py \
  --corpus miracl-ko-corpus.jsonl \
  --queries miracl-ko-queries.tsv \
  --qrels miracl-ko-qrels.txt \
  --output results.json
```

### In-House Evaluation

```bash
cd DI_TriCHEF/scripts
python bench_w5.py --domain doc --eval_type loo
```

See `publication/paper/Tri-CHEF_paper_v1-2.pdf` for detailed methodology and results.

---

## Development Guide

### Backend Development

```bash
# Terminal 1: Flask backend
cd App/backend
pip install -r requirements.txt
python app.py

# Terminal 2: React + Electron
cd App/frontend
npm install
npm run electron:dev
```

### Adding a New Encoder

1. Create encoder class in `App/backend/embedders/your_encoder.py`:
   ```python
   from embedders.base import BaseEncoder
   
   class YourEncoder(BaseEncoder):
       def __init__(self, model_name: str):
           self.model = load_model(model_name)
       
       def encode(self, text: str) -> np.ndarray:
           return self.model.encode(text)
   ```

2. Register in domain pipeline:
   ```python
   from embedders.your_encoder import YourEncoder
   
   class DocPipeline(BasePipeline):
       def __init__(self):
           self.z_encoder = YourEncoder("model-name")
   ```

3. Update calibration config in `DI_TriCHEF/auto_calibration/config.yaml`

### Adding a New Domain

1. Create domain directory in `App/backend/embedders/`:
   ```
   embedders/
   └── your_domain/
       ├── ingest.py       # Text extraction
       ├── embedder.py     # 3-axis encoding
       └── runner.py       # Incremental indexing
   ```

2. Implement `BaseRunner` in `your_domain/runner.py`

3. Register in `unified_engine.py` and `app.py` routes

---

## Known Limitations & Future Work

### Current Limitations
- Movie evaluation limited to frame-level matching (temporal alignment incomplete)
- Whisper STT latency ~5s per minute of audio
- Complex-Hermitian scoring adds ~15% overhead vs. single-axis
- Cross-domain queries (e.g., "image similar to this song") not yet supported

### Planned Improvements
- [ ] Temporal query-document alignment for video
- [ ] Multi-lingual caption generation (zh/ja/vi)
- [ ] Quantization support (int8/fp16) for edge deployment
- [ ] Federated learning for privacy-preserving indexing
- [ ] Real-time video stream indexing

---

## Citation

If you use Tri-CHEF in your research, please cite:

```bibtex
@article{song2026triche﻿f,
  title={Tri-CHEF: Complex-Hermitian Fusion of Heterogeneous Encoders for Korean Multimodal Retrieval},
  author={Song, Young-Sang and Lee, Hwon and Jang, Ju Yeon and Hwang, Yeong Jin and Lee, Tae Yun and Kim, Jeong Hye},
  journal={arXiv preprint arXiv:2406.xxxxx},
  year={2026}
}
```

---

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) file for details.

**Note**: Tri-CHEF includes several third-party models (SigLIP2, BGE-M3, DINOv2, Whisper) with their own licenses. When using this system in production, ensure compliance with:
- OpenAI Whisper (MIT License)
- Open CLIP (MIT License)
- BAAI/BGE (Apache 2.0)
- Meta DINOv2 (CC-BY-NC License)

---

## Acknowledgments

This work was completed as part of the Korea Data Talent (KDT) program. We thank:
- The research group at Seoul National University for guidance on complex-valued representations
- OpenAI, Meta, and BAAI teams for open-sourcing foundational models
- The MIRACL evaluation committee for Korean IR benchmarking support

Team Chainers (2026)

---

## Contact & Support

- **Lead Author**: Young-Sang Song (yssong@gmail.com)
- **GitHub Issues**: [Report bugs or request features](https://github.com/Team-Chainers/DB_insight/issues)
- **Email Support**: team-chainers@example.com
- **Paper**: [Tri-CHEF_paper_v1-2.pdf](publication/paper/Tri-CHEF_paper_v1-2.pdf)

---

**Last Updated**: 2026-04-26  
**Paper Version**: v1-2  
**Code Version**: Snapshot from commit 73c8bf0  
**Branch**: `feature/trichef-port`
