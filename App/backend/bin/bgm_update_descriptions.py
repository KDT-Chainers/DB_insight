"""
Update BGM descriptions with explicit mood labels for better CLAP text search.

Key improvement: tag-based + param-based mood classification
(dark-timbre + slow → dark brooding, warm-timbre + fast + loud → energetic)
Only updates audio_meta.json descriptions + text index; audio index unchanged.
"""
import sys, io, json, time
import numpy as np
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BGM_DIR = Path(__file__).resolve().parents[3] / "Data" / "embedded_DB" / "Bgm"


def classify_mood(tags: list, params: dict) -> list[str]:
    """Derive mood labels from librosa tags + audio params."""
    tag_set = set(tags)
    bpm = params.get('tempo_bpm', 120)
    rms = params.get('rms_mean', 0.1)
    sc = params.get('spectral_centroid_mean', 2000)
    hp = params.get('harm_perc_ratio', 1.0)
    dur = params.get('duration_sec', 30)

    moods = []

    # Timbre × Tempo combinations
    is_dark_timbre = 'dark-timbre' in tag_set
    is_fast = 'fast' in tag_set or bpm >= 120
    is_slow = 'slow' in tag_set or bpm < 80
    is_loud = 'loud' in tag_set or rms > 0.15
    is_melodic = 'melodic' in tag_set or hp > 1.2
    is_rhythmic = 'rhythmic' in tag_set or hp < 0.8
    is_very_low_sc = sc < 1200  # very bassy

    if is_dark_timbre and is_slow:
        moods += ["dark atmospheric brooding melancholic haunting"]
    elif is_dark_timbre and is_fast and is_loud:
        moods += ["intense dramatic tense dark powerful"]
    elif is_dark_timbre and is_fast:
        moods += ["dark driving cinematic suspenseful tense"]
    elif is_dark_timbre:
        moods += ["dark somber gloomy mysterious"]

    if not is_dark_timbre and is_slow and is_melodic:
        moods += ["calm peaceful serene relaxing soothing"]
    elif not is_dark_timbre and is_slow:
        moods += ["slow gentle quiet ambient relaxing"]

    if not is_dark_timbre and is_fast and is_loud:
        moods += ["energetic upbeat exciting lively powerful"]
    elif not is_dark_timbre and is_fast and is_melodic:
        moods += ["upbeat cheerful bright lively melodic"]
    elif not is_dark_timbre and is_fast:
        moods += ["fast upbeat energetic driving"]

    if is_very_low_sc and is_dark_timbre:
        moods += ["heavy bass dark deep ominous"]
    elif is_very_low_sc:
        moods += ["warm bass deep resonant"]

    if is_loud and is_fast and is_dark_timbre:
        moods += ["dramatic cinematic epic"]

    if is_rhythmic and is_fast:
        moods += ["rhythmic percussive groove beat"]

    if not moods:
        moods += ["background instrumental music neutral moderate"]

    return moods


def make_description_v2(fname: str, lib_entry: dict) -> str:
    """Generate rich description v2 with explicit mood labels."""
    p = lib_entry.get('params', {})
    tags = lib_entry.get('tags', [])

    bpm = p.get('tempo_bpm', 120)
    rms = p.get('rms_mean', 0.1)
    sc = p.get('spectral_centroid_mean', 2000)
    dur = p.get('duration_sec', 30)
    hp = p.get('harm_perc_ratio', 1.0)

    # Tempo
    if bpm < 70:
        tempo_s = f"slow tempo {bpm:.0f} BPM"
    elif bpm < 100:
        tempo_s = f"medium tempo {bpm:.0f} BPM"
    elif bpm < 130:
        tempo_s = f"upbeat tempo {bpm:.0f} BPM"
    elif bpm < 160:
        tempo_s = f"fast tempo {bpm:.0f} BPM"
    else:
        tempo_s = f"very fast tempo {bpm:.0f} BPM"

    # Brightness
    if sc < 1500:
        bright_s = "dark low-frequency heavy bass"
    elif sc < 2500:
        bright_s = "warm mid-range balanced tones"
    else:
        bright_s = "bright high-frequency crisp"

    # Dynamics
    if rms < 0.05:
        dyn_s = "very soft quiet delicate"
    elif rms < 0.10:
        dyn_s = "soft gentle subtle"
    elif rms < 0.15:
        dyn_s = "moderate balanced volume"
    else:
        dyn_s = "loud strong powerful"

    # Texture
    if hp > 1.4:
        tex_s = "melodic harmonic smooth"
    elif hp < 0.7:
        tex_s = "percussive rhythmic"
    else:
        tex_s = "balanced melodic rhythmic"

    # Duration
    dur_s = f"{dur:.0f}s clip"

    # Mood labels (most important for CLAP text search)
    moods = classify_mood(tags, p)
    mood_s = " ".join(moods)

    return (
        f"background music {tempo_s} {bright_s} {dyn_s} {tex_s} "
        f"{mood_s} {dur_s}"
    )


# ── Load data ──────────────────────────────────────────────────────────────
print("Loading audio_meta.json and librosa_features.json...")
meta_list = json.loads((BGM_DIR / "audio_meta.json").read_text('utf-8'))
lib_list = json.loads((BGM_DIR / "librosa_features.json").read_text('utf-8'))
lib_map = {item['filename']: item for item in lib_list}

# ── Generate new descriptions ──────────────────────────────────────────────
print("Generating mood-enhanced descriptions...")
new_descriptions = {}
updated_meta = []
for entry in meta_list:
    fname = entry.get('filename', '') if isinstance(entry, dict) else str(entry)
    lib_entry = lib_map.get(fname, {})
    desc = make_description_v2(fname, lib_entry)
    new_descriptions[fname] = desc
    new_entry = dict(entry) if isinstance(entry, dict) else {'filename': fname}
    new_entry['description'] = desc
    updated_meta.append(new_entry)

unique_descs = len(set(new_descriptions.values()))
print(f"  {len(new_descriptions)} descriptions, unique: {unique_descs}")

# Check mood distribution
dark_files = [f for f, d in new_descriptions.items() if 'dark' in d and 'brooding' in d or 'tense' in d]
calm_files = [f for f, d in new_descriptions.items() if 'calm peaceful' in d or 'serene' in d]
energetic_files = [f for f, d in new_descriptions.items() if 'energetic upbeat' in d or 'lively' in d]
print(f"  dark/tense: {len(dark_files)}, calm/serene: {len(calm_files)}, energetic: {len(energetic_files)}")

# Sample dark descriptions
print("\nSample dark descriptions:")
dark_check = [f for f, d in new_descriptions.items() if 'dark' in d and ('brooding' in d or 'tense' in d or 'suspens' in d)][:5]
for f in dark_check:
    print(f"  {f}: {new_descriptions[f][:100]}")

# ── Save updated audio_meta.json ───────────────────────────────────────────
(BGM_DIR / "audio_meta.json").write_text(
    json.dumps(updated_meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"\nSaved audio_meta.json ({len(updated_meta)} entries)")

# ── Re-embed descriptions with CLAP text encoder ──────────────────────────
print("\nRe-encoding descriptions with CLAP text encoder...")
from services.bgm import clap_encoder
clap_encoder._ensure_loaded()

desc_list = [new_descriptions[e.get('filename', '') if isinstance(e, dict) else str(e)]
             for e in updated_meta]

t0 = time.time()
BATCH = 32
rows = []
for i in range(0, len(desc_list), BATCH):
    batch = desc_list[i:i+BATCH]
    rows.append(clap_encoder.encode_text(batch))
    print(f"  {min(i+BATCH, len(desc_list))}/{len(desc_list)}...")

text_emb = np.vstack(rows).astype(np.float32)
print(f"  Done in {time.time()-t0:.1f}s, shape={text_emb.shape}")

np.save(str(BGM_DIR / "text_emb.npy"), text_emb)

# Rebuild text FAISS index
import faiss
d = text_emb.shape[1]
text_idx = faiss.IndexFlatIP(d)
text_idx.add(text_emb)  # already L2 normalized by encode_text
faiss.write_index(text_idx, str(BGM_DIR / "text_index.faiss"))
print(f"  text_index.faiss rebuilt: {text_idx.ntotal} vectors")

# ── Quick validation ────────────────────────────────────────────────────────
print("\n=== Quick BGM search validation ===")
from services.bgm.search_engine import get_engine, reload_engine
reload_engine()
bgm = get_engine()
bgm._ensure_loaded()

for q in ["어두운 긴장감", "dark tense dramatic music",
          "잔잔한 피아노", "calm piano music",
          "신나는 빠른 음악", "upbeat fast energetic music"]:
    r = bgm.search(q, top_k=3)['results']
    files = [x['filename'] for x in r]
    scores = [round(x['score'], 3) for x in r]
    print(f"  {q!r:35s}: {files}  {scores}")

print("\nDone!")
