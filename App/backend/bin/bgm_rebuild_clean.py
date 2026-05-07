"""
BGM catalog cleanup + rich description rebuild + index filter.

Steps:
  1. Restore audio_meta.json to 102 numeric BGM entries (from backup)
  2. Generate per-file unique descriptions using librosa params
  3. Filter clap_emb.npy[0:102] → rebuild CLAP FAISS index
  4. Re-embed 102 descriptions with CLAP text encoder → text_emb.npy + text FAISS index
  5. Update text_ids.json
  6. Re-calibrate confidence thresholds
"""
import sys, io, json, shutil, time
import numpy as np
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BGM_DIR = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB" / "Bgm"

# ── Step 1: Restore audio_meta.json from 102-entry backup ─────────────────
print("=" * 60)
print("STEP 1: Restore audio_meta.json (102 entries)")
print("=" * 60)

meta_path = BGM_DIR / "audio_meta.json"
backup_path = BGM_DIR / "audio_meta.json.bak.1777723414"

# Backup current state first
ts = int(time.time())
shutil.copy(meta_path, BGM_DIR / f"audio_meta.json.bak.{ts}")
print(f"  backed up current → audio_meta.json.bak.{ts}")

backup_data = json.loads(backup_path.read_text('utf-8'))
print(f"  backup entries: {len(backup_data)}")

# Verify all are numeric
def get_stem(k):
    fname = str(k).replace('\\', '/').split('/')[-1]
    return fname.rsplit('.', 1)[0]

if isinstance(backup_data, list):
    numeric_check = all(get_stem(e.get('filename','') if isinstance(e,dict) else e).isdigit() for e in backup_data)
elif isinstance(backup_data, dict):
    numeric_check = all(get_stem(k).isdigit() for k in backup_data)
print(f"  all numeric: {numeric_check}")

# Load librosa features for rich descriptions
print()
print("=" * 60)
print("STEP 2: Generate rich per-file descriptions")
print("=" * 60)

lib_path = BGM_DIR / "librosa_features.json"
lib_data = json.loads(lib_path.read_text('utf-8'))
lib_map = {}
for item in lib_data:
    fname = item['filename']
    lib_map[fname] = item

def make_rich_description(filename, meta_entry, lib_entry):
    """Generate a unique description using all available features."""
    p = lib_entry.get('params', {}) if lib_entry else {}
    tags = lib_entry.get('tags', []) if lib_entry else []

    bpm = p.get('tempo_bpm', 0)
    rms = p.get('rms_mean', 0)
    sc = p.get('spectral_centroid_mean', 0)
    sr = p.get('spectral_rolloff_mean', 0)
    zcr = p.get('zcr_mean', 0)
    dur = p.get('duration_sec', 0)
    hp_ratio = p.get('harm_perc_ratio', 1.0)

    # Tempo descriptor
    if bpm < 70:
        tempo_desc = f"slow tempo {bpm:.0f} BPM"
        energy_desc = "calm relaxing"
    elif bpm < 100:
        tempo_desc = f"medium tempo {bpm:.0f} BPM"
        energy_desc = "moderate flowing"
    elif bpm < 130:
        tempo_desc = f"upbeat tempo {bpm:.0f} BPM"
        energy_desc = "energetic lively"
    elif bpm < 160:
        tempo_desc = f"fast tempo {bpm:.0f} BPM"
        energy_desc = "dynamic driving"
    else:
        tempo_desc = f"very fast tempo {bpm:.0f} BPM"
        energy_desc = "intense racing"

    # Brightness (spectral centroid)
    if sc < 1500:
        bright_desc = "dark low-frequency heavy bass"
    elif sc < 2500:
        bright_desc = "warm mid-range balanced tones"
    elif sc < 4000:
        bright_desc = "bright mid-high clarity"
    else:
        bright_desc = "crisp high-frequency airy treble"

    # Dynamics (RMS)
    if rms < 0.03:
        dyn_desc = "very soft quiet delicate"
    elif rms < 0.07:
        dyn_desc = "soft gentle subtle"
    elif rms < 0.12:
        dyn_desc = "moderate volume balanced"
    elif rms < 0.18:
        dyn_desc = "loud prominent strong"
    else:
        dyn_desc = "very loud powerful intense"

    # Harmonic vs percussive
    if hp_ratio > 1.5:
        texture_desc = "melodic harmonic smooth"
    elif hp_ratio < 0.7:
        texture_desc = "percussive rhythmic punchy"
    else:
        texture_desc = "balanced melodic rhythmic"

    # Duration
    if dur < 30:
        dur_desc = f"short clip {dur:.0f}s"
    elif dur < 90:
        dur_desc = f"medium length {dur:.0f}s"
    else:
        dur_desc = f"extended piece {dur:.0f}s"

    # Tag-based mood
    tag_set = set(tags)
    mood_parts = []
    if 'calm' in tag_set or 'slow' in tag_set:
        mood_parts.append("peaceful ambient background")
    if 'fast' in tag_set or 'energetic' in tag_set:
        mood_parts.append("upbeat motivational cinematic")
    if 'dark' in tag_set:
        mood_parts.append("dark dramatic tense suspense")
    if 'rhythmic' in tag_set:
        mood_parts.append("rhythmic groove beat")
    if not mood_parts:
        mood_parts.append("background instrumental music")

    mood_desc = " ".join(mood_parts)

    # ZCR for texture
    if zcr > 0.08:
        zcr_desc = "noisy complex texture"
    elif zcr > 0.04:
        zcr_desc = "moderate harmonic texture"
    else:
        zcr_desc = "smooth tonal texture"

    desc = (
        f"background music {tempo_desc} {energy_desc} "
        f"{bright_desc} {dyn_desc} {texture_desc} "
        f"{mood_desc} {zcr_desc} {dur_desc}"
    )
    return desc

# Generate descriptions
descriptions = {}
for item in backup_data:
    if isinstance(item, dict):
        fname = item.get('filename', '')
    else:
        fname = str(item)

    lib_entry = lib_map.get(fname)
    desc = make_rich_description(fname, item, lib_entry)
    descriptions[fname] = desc

# Check uniqueness
unique_descs = len(set(descriptions.values()))
print(f"  Generated {len(descriptions)} descriptions, unique: {unique_descs}")

# Update audio_meta entries with new descriptions
if isinstance(backup_data, list):
    updated_meta = []
    for item in backup_data:
        if isinstance(item, dict):
            fname = item.get('filename', '')
            updated = dict(item)
            updated['description'] = descriptions.get(fname, '')
            updated_meta.append(updated)
        else:
            updated_meta.append(item)
else:
    updated_meta = {}
    for k, v in backup_data.items():
        fname = get_stem(k)
        entry = dict(v) if isinstance(v, dict) else {'filename': k}
        entry['description'] = descriptions.get(k, descriptions.get(fname + '.mp4', ''))
        updated_meta[k] = entry

# Write updated audio_meta.json
meta_path.write_text(json.dumps(updated_meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"  Written audio_meta.json ({len(updated_meta)} entries)")

# Show sample descriptions
print("\n  Sample descriptions (first 6):")
for fname, desc in list(descriptions.items())[:6]:
    print(f"    {fname}: {desc[:90]}")

# ── Step 3: Filter CLAP audio embeddings to 102 files ─────────────────────
print()
print("=" * 60)
print("STEP 3: Filter CLAP audio index to 102 BGM files")
print("=" * 60)

# Load current text_ids to find index positions of numeric files
text_ids_data = json.loads((BGM_DIR / "text_ids.json").read_text('utf-8'))
all_ids = text_ids_data['ids'] if isinstance(text_ids_data, dict) else text_ids_data

# Build position map
id_to_pos = {fname: i for i, fname in enumerate(all_ids)}
print(f"  Current index has {len(all_ids)} entries")

# Get positions of the 102 numeric files (in order)
numeric_fnames = [e.get('filename', str(e)) if isinstance(e, dict) else str(e)
                  for e in (updated_meta if isinstance(updated_meta, list) else [{'filename': k} for k in updated_meta])]
print(f"  Numeric BGM files: {len(numeric_fnames)}")

# Load existing CLAP audio embeddings
clap_emb = np.load(str(BGM_DIR / "clap_emb.npy"))
print(f"  clap_emb shape: {clap_emb.shape}")

# Extract rows for numeric BGM files
clap_filtered = []
found = 0
for fname in numeric_fnames:
    pos = id_to_pos.get(fname)
    if pos is not None:
        clap_filtered.append(clap_emb[pos])
        found += 1
    else:
        # Try without path
        stem_fname = fname.replace('\\','/').split('/')[-1]
        pos2 = id_to_pos.get(stem_fname)
        if pos2 is not None:
            clap_filtered.append(clap_emb[pos2])
            found += 1
        else:
            print(f"  WARNING: {fname} not found in index, using zero vector")
            clap_filtered.append(np.zeros(clap_emb.shape[1], dtype=np.float32))

clap_filtered = np.array(clap_filtered, dtype=np.float32)
print(f"  Filtered CLAP embeddings: {clap_filtered.shape}, found={found}/{len(numeric_fnames)}")

# Save filtered CLAP embeddings
np.save(str(BGM_DIR / "clap_emb.npy"), clap_filtered)

# Rebuild CLAP FAISS index
import faiss
norm = np.linalg.norm(clap_filtered, axis=1, keepdims=True)
norm = np.where(norm == 0, 1.0, norm)
clap_normed = (clap_filtered / norm).astype(np.float32)
d = clap_normed.shape[1]
clap_idx = faiss.IndexFlatIP(d)
clap_idx.add(clap_normed)
faiss.write_index(clap_idx, str(BGM_DIR / "clap_index.faiss"))
print(f"  Rebuilt clap_index.faiss: {clap_idx.ntotal} vectors, dim={d}")

# ── Step 4: Rebuild text embeddings with new descriptions ─────────────────
print()
print("=" * 60)
print("STEP 4: Rebuild text embeddings (new rich descriptions)")
print("=" * 60)

from services.bgm import clap_encoder
clap_encoder._ensure_loaded()
print(f"  CLAP encoder loaded")

# Encode all 102 descriptions (batch for efficiency)
desc_list = [descriptions[fname] for fname in numeric_fnames]
print(f"  Encoding {len(desc_list)} descriptions...")

t0 = time.time()
BATCH = 32
all_rows = []
for i in range(0, len(desc_list), BATCH):
    batch = desc_list[i:i+BATCH]
    batch_emb = clap_encoder.encode_text(batch)  # (B, 512) already L2-normed
    all_rows.append(batch_emb)
    print(f"    {min(i+BATCH, len(desc_list))}/{len(desc_list)}...")

text_emb_arr = np.vstack(all_rows).astype(np.float32)
print(f"  Encoded in {time.time()-t0:.1f}s, shape: {text_emb_arr.shape}")

# Save text embeddings
np.save(str(BGM_DIR / "text_emb.npy"), text_emb_arr)

# Rebuild text FAISS index (encode_text already L2-normalized → use directly)
text_idx = faiss.IndexFlatIP(d)
text_idx.add(text_emb_arr)
faiss.write_index(text_idx, str(BGM_DIR / "text_index.faiss"))
print(f"  Rebuilt text_index.faiss: {text_idx.ntotal} vectors")

# ── Step 5: Update text_ids.json ──────────────────────────────────────────
print()
print("STEP 5: Update text_ids.json")
new_ids = {'ids': numeric_fnames}
(BGM_DIR / "text_ids.json").write_text(json.dumps(new_ids, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"  Written text_ids.json: {len(numeric_fnames)} IDs")

# ── Step 6: Re-calibrate ──────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 6: Re-calibrate confidence thresholds")
print("=" * 60)

# Reload engine with fresh data
from services.bgm.search_engine import get_engine, reload_engine
reload_engine()
bgm = get_engine()
bgm._ensure_loaded()

NULL_QUERIES = [
    # Completely unrelated queries
    "invoice payment receipt", "database schema migration",
    "python error traceback", "weather forecast tomorrow",
    "recipe ingredients list", "traffic jam highway",
    "tax filing deadline", "election candidate debate",
    "stock market crash", "newspaper headline politics",
    "homework assignment math", "hospital appointment",
    "shipping address form", "password reset email",
    "flight departure gate", "hotel check-in time",
    "car insurance renewal", "grocery shopping list",
    "wifi password router", "printer driver install",
    # Slightly closer but still null
    "news documentary film", "sports game highlights",
    "interview transcript text", "cooking tutorial video",
    "nature wildlife documentary",
]

MUSIC_QUERIES = [
    "calm piano background music",
    "upbeat fast energetic music",
    "dark tense dramatic music",
    "slow relaxing ambient",
    "exciting action cinematic",
    "sad emotional piano",
    "happy cheerful melody",
    "mysterious atmospheric",
    "romantic gentle strings",
    "rhythmic groove beat",
    "잔잔한 피아노 음악",
    "신나는 빠른 음악",
    "어두운 긴장감 음악",
    "편안한 배경음악",
    "활기찬 경쾌한 음악",
]

null_scores = []
for q in NULL_QUERIES:
    res = bgm.search(q, top_k=1)
    if res['results']:
        null_scores.append(res['results'][0]['score'])

music_scores = []
for q in MUSIC_QUERIES:
    res = bgm.search(q, top_k=1)
    if res['results']:
        music_scores.append(res['results'][0]['score'])

mu = float(np.mean(null_scores))
sigma = float(np.std(null_scores))
p95_null = float(np.percentile(null_scores, 95))
music_mean = float(np.mean(music_scores))
separation = (music_mean - mu) / sigma if sigma > 0 else 0

print(f"  Null  : μ={mu:.4f}  σ={sigma:.4f}  p95={p95_null:.4f}  n={len(null_scores)}")
print(f"  Music : μ={music_mean:.4f}  separation={separation:.2f}σ")

cal = {
    "mu_null": mu,
    "sigma_null": sigma,
    "p95_null": p95_null,
    "music_mean": music_mean,
    "separation_sigma": separation,
    "n_null": len(null_scores),
    "n_music": len(music_scores),
}
(BGM_DIR / "calibration.json").write_text(json.dumps(cal, indent=2), encoding='utf-8')
print(f"  Written calibration.json")

# ── Final summary ─────────────────────────────────────────────────────────
print()
print("=" * 60)
print("REBUILD COMPLETE")
print("=" * 60)
print(f"  audio_meta.json : {len(updated_meta)} entries (cleaned)")
print(f"  clap_emb.npy    : {clap_filtered.shape}")
print(f"  text_emb.npy    : {text_emb_arr.shape}")
print(f"  Unique descs    : {unique_descs} / {len(descriptions)}")
print(f"  Calibration     : μ={mu:.4f}  σ={sigma:.4f}  sep={separation:.2f}σ")
