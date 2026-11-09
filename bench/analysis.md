# ANALYZE — measured hotspot map for mojo-easyexif

Phase: ANALYZE. No algorithm was changed. No file in `src/` or `tests/` was
touched. This report contains only numbers measured in this session
(2026-11-09, `perf_counter`, best-of-5 unless noted) plus structural counts
(loops, allocations, IFD entries) read from `src/easyexif.mojo`,
`python/mojo_easyexif/api.py`, and `vendor/easyexif/exif.cpp`.

## 0. Machine and toolchain (measured here)

| Item | Value |
|---|---|
| Host | `Linux 6.8.0-147-generic`, `x86_64`, Intel Xeon E5-2697 v4, 72 threads (36 physical cores, 2 sockets) |
| Mojo | `1.2.0.dev2026092605` (`pixi run mojo --version`) |
| C++ reference | GCC 14.3.0, `-O3`, from `bench/bench.py` + `bench/reference.cpp` |
| numpy / Python (pixi) | numpy 2.5.1, Python 3.13 |
| Load | shared machine, `/proc/loadavg` ~7–9 during probes — treat `±10–20%` absolute wobble as noise; *ratios* within one interleaved run are tighter |
| Upstream Python binding | **Not importable** — `easyexif`, `pyeasyexif`, `piexif`, `exifread` all `ModuleNotFoundError` in the pixi env. Upstream comparison is the vendored C++ `EXIFInfo::parseFrom` via `bench/reference.cpp`, compiled from unmodified `vendor/easyexif/exif.cpp` |
| Profiling limit | `perf stat` unavailable (`perf_event_paranoid=4`, no `CAP_PERFMON`). Cycle/instruction counters could not be collected; the map below uses timer splits + disassembly + structural counts instead |
| Git HEAD | `504716e` |

Method: every row below is a timed run in this session. The headline
`pixi run bench` (flock-wrapped) was run three times; the last run is quoted
verbatim in §1. The `Time`/`Bytes` ledgers in §2–§3 are separate probe
processes (`perf_counter`, best-of-5) that report both best and average.

## 1. Headline: `pixi run bench` (final run, verbatim)

```
| case | Mojo (us/image) | EasyEXIF C++ (us/image) | C++ / Mojo |
|---|---:|---:|---:|
| single GPS JPEG | 4.714 | 7.535 | 1.60x |
| batch 1,000 GPS JPEGs | 0.197 | 2.428 | 12.31x |
| batch 1,000 mixed fixtures | 0.123 | 1.773 | 14.36x |
```

Two earlier runs the same day gave `4.883 / 0.196 / 0.128 µs` (1.45× / 13.25× / 15.17×)
and `4.292 / 0.189 / 0.128 µs` (1.66× / 13.79× / 14.59×) — stable ratios, ±15%
absolute wobble from machine load.

**Critical reading:** `bench/bench.py` passes buffers as `.ctypes.data`
(integers) and reuses pre-built numpy arrays. The shipped Python API
(`api.py`) passes `source.ctypes.data_as(ctypes.c_void_p)` built fresh on
every call. Measured delta at the same image: `data_as` costs **+3.7 µs/call**
for the 2-pointer single call (3 pointers in `parse_many`: ~+9.7 µs/call).
So `bench.py` *understates* glue cost vs. the real user path by that amount.
All "kernel" numbers below are quoted in three conventions so the phases
act on the right figure:

- **(A) bench convention** — `.ctypes.data` ints, arrays pre-made (bench.py).
- **(B) api convention** — `data_as(c_void_p)` fresh per call (api.py).
- **(C) pre-wrapped `c_void_p`** — pointers built once, kernel+ctypes-machinery only
  (closest thing to kernel-only time measurable from Python).

## 2. Real caller sizes (what the sizes actually are)

All eight fixtures in `tests/data/` (the project's own corpus):

| Fixture | Full JPEG | APP1/EXIF segment payload | IFD structure walked |
|---|---:|---:|---|
| `lens_info.jpg` | 897 B | 262 B | IFD0 5 + EXIF 8, **no GPS** |
| `right.jpg` | 5,990 B | 96 B | IFD0 5, **no EXIF/GPS** |
| `test2.jpg` | 11,260 B | 790 B | IFD0 + EXIF + GPS |
| `bb-android.jpg` (the bench "GPS JPEG") | 11,921 B | 9,066 B | IFD0 12 + EXIF 29 + GPS 9 = **50 entries** |
| `down-mirrored.jpg` | 15,437 B | 96 B | IFD0 5, **no EXIF/GPS** |
| `test1.jpg` | 27,521 B | 12,284 B | IFD0 11 + EXIF 24 + GPS 9 = 44 entries |
| `short-ascii-MM.jpg` | 31,818 B | 6,730 B | IFD0 + EXIF + GPS |
| `evil1.jpg` | 86,490 B | 7,361 B | IFD0 + EXIF + GPS |

Real caller sizes: **0.9–86 KB per image**. But the kernel does **not** touch
the whole file. Measured (Python emulation of `parse_jpeg` + disassembly):

- Backward EOI scan (`H15` loop): **0 steps** on all 8 fixtures (EOI is at the
  last two bytes).
- Forward APP1 scan: **22 bytes** on all 8 fixtures (`FF D8 FF E1` at offset 20).
- IFD walks touch **50 × 12 B = 600 B** of entries (bb-android), plus ~30 B of
  TIFF headers, plus the 9 external rationals actually decoded (72 B), plus the
  136 B result row. **Kernel-touched ledger: 860 B** for the bench GPS image —
  7.2% of the 11,921 B file. File size is nearly irrelevant to kernel time
  (a synthetic APP1-at-offset-8000 image did cost more — 8.2 µs vs 3.8 µs —
  proving the scan *is* per-byte, but real files put APP1 at 22 B).
- `evil1.jpg` (86 KB) parses in the same ~4 µs as `lens_info.jpg` (897 B)
  because it is a 7,361 B segment with the same ~600 B of entries. Anyone
  extrapolating "36 s/MB scan" from file size is wrong; the scan is ~24 B.

### Arithmetic counts (bb-android, derived from the measured structure)

- IFD entries: 50 (12 + 29 + 9) — each `read_u16(tag)` + `entry_is_valid`
  where covered + stride.
- Rationals decoded by the port: **9** (focal 1, lat 3, lon 3, alt 1, DOP 1).
- FP64 flops: 9 divides + lat (`d + m/60 + s/3600` = 2 divides + 2 adds) + lon
  (same) = **17 flops**, plus ≤3 conditional negations = **~20 flops/image**.
- Integer ops (for the roofline caveat): ~10/entry ≈ 500 + rationals ~144 +
  scan ~88 ≈ **~730 int ops/image**, dominated by loads/shifts/branches.
- **Flops/byte (kernel-touched 860 B): 20/860 = 0.023 flops/B.**
  **Flops/byte (full 11,921 B file): 0.0014–0.0017 flops/B.**
  Counting int ops as "ops": 750/860 = **0.87 ops/B — still below 2 ops/B,**
  and those ops are data-dependent branches (`entry_is_valid`, `has_range`,
  GPS sign flags), not dense arithmetic.

## 3. Ranked hotspot table

Rank is by **share of user-visible time** at the size real callers pass
(single-image path; batch is §3.2). `Time` is in µs/call (single) or per-image
in batch. `~` marks a range measured across runs; all numbers are
best-of-5 in-session runs (probes at 20,000 calls, API at 2,000).

### 3.1 Single-image path (`parse`, `parse_exif_segment`)

| # | Function / stage | Input size | Time | Bytes touched | Flops | Flops/byte | Memory-bound or compute-bound | Python/ctypes glue or kernel |
|---:|---|---:|---:|---:|---:|---:|---|---|
| 1 | **`api._decode` — 4 dataclass objects/image** (`api.py:79`) `ExifInfo+GPSInfo+2×Coordinate`, ~9×`float()`/`int()` + `chr()` | 136 B result row | **~7.1–7.5 µs/img** (~37–39% of `parse`) | 136 B | ~0 (object construction) | ~0 | **Neither — latency/object-allocation-bound** (Python heap, `__init__`) | **Python glue** (pure Python, zero ctypes). Tuple-decode of same fields measured at 0.77 µs → ~9× cheaper |
| 2 | **Single ctypes call, api convention (B)** (`api.py:116–122`) — `data_as × 2` + C ABI + `clear_result` + scan + IFD | 11,921 B file / 860 B touched | **~7.5–8.6 µs/call** (~41% of `parse`) | 860 B (136 B write + ~724 B read) | ~20 | 0.023 (0.0014/MB) | Latency-bound (branchy pointer chase) | **Mixed: ~3.7 µs is `data_as` attribute construction (glue), ~0.95 µs pure ctypes floor, ~0.25 µs kernel work** (split §5) |
| 3 | Kernel **IFD walks + 9 rationals** — `parse_exif_segment/parse_sub_ifd/parse_gps_ifd` (`src/easyexif.mojo:146–358`) | 860 B touched of 11,921 B | **~0.22–0.30 µs/img** (full-`C` minus tiny-4B floor; batch-amortized 0.18–0.30) | 860 B | ~20 | 0.023 | **Latency/branch-bound, not bandwidth-bound** (3.0–3.5 GB/s effective vs 13.9 GB/s memcpy) | **Kernel.** ~1.3% of `api.parse` |
| 4 | **`api._as_u8` — `np.frombuffer` view** (`api.py:64`, contiguous `bytes`) | 897 B–86,490 B | **~0.75–1.20 µs/call** (size-independent) | 0-copy view (payload not touched) | 0 | 0 | Metadata-only | **Python glue** |
| 5 | `api._parse` wrapper remainder — `parse()`→`_parse()` call, `tuple`, `int()` wrap, `lib()` fetch, error-path branch | — | **~3.9 µs/call** (full `parse` 20.2 − ᵀ1–4) | 0 | 0 | — | Overhead (interpreter) | **Python glue** (attr fetch `lib()` itself is 0.09 µs cached; the rest is function-call/tuple/`ExifParseError` machinery) |
| 6 | `clear_result` (17×f64) + SOI/EOI 4 B scan | 136 B + 4 B | **≲0.05–0.1 µs** (tiny-4B − null = −0.004 µs, i.e. unmeasurable at timer resolution; disasm shows 4× `vmovupd` ymm = full clear) | 140 B | 0 | 0 | Negligible | Kernel, but invisible inside the 0.95 µs ctypes floor |
| 7 | `lib()` lookup (cached CDLL) | — | 0.09 µs/call | 0 | 0 | — | Negligible | Python glue |

**End-to-end `exif.parse` (bb-android 11,921 B): ~19–20 µs** (measured
18.3–24.1 µs across sessions on the shared machine; decomposition run gave
20.2 µs). Of that: `_decode` 37%, ctypes-with-`data_as` 41%, kernel IFD work
**~1.3%**. `parse_exif_segment` is flat at **~18.8–19.3 µs** for every
fixture (96 B–12,284 B segments) — the Python delta is constant, confirming
the time is glue, not segment size.

Full per-fixture `parse` (bytes path, best-of-5): 18.9–19.5 µs for **every**
fixture from 897 B to 86,490 B. The GPS vs non-GPS kernel delta
(pre-wrapped: 1.02–1.05 µs non-GPS vs 1.19–1.20 µs GPS) is real but buried
under ~19 µs of glue.

### 3.2 Batch path (`parse_many`)

`tiled offsets` convention = `bench.py:84–125` (pre-packed). `api.parse_many`
additionally packs with `b"".join`. Kernel row uses pre-packed (C) numbers.

| # | Function / stage | Input size | Time | Bytes touched | Flops | Flops/byte | Memory-bound or compute-bound | Glue or kernel |
|---:|---|---:|---:|---:|---:|---:|---|---|
| 8 | **`N × _decode`** (`api.py:179` list-comp, pure-Python per-row) | 136 B/row | **7.4–7.8 ms per N=1000** (7.5 µs/img, ~75% of `api.parse_many`) | 136 KB | ~0 | ~0 | Object/loop-bound | **Python glue, per-element** |
| 9 | **`b"".join(chunks)` copy** (`api.py:161`, N>1 only) | 11.92 MB (N=1000) | **590–660 µs per N=1000** (0.6 µs/img) @ ~20 GB/s | 11.92 MB written | 0 | 0 | **Bandwidth-bound** (the only truly bandwidth-bound row) | **Python glue copy** (callers' buffers concatenated before entering Mojo) |
| 10 | Batch **kernel** `easyexif_parse_many` (`src/easyexif.mojo:418`, serial loop) | 1.02 MB kernel-touched (N=1000: 1000×860 + 24 KB offsets/lens + 136 KB results) | **269–303 µs per N=1000** (0.27–0.30 µs/img) | 1.02 MB | 17,000 (20/img) | 0.017–0.023 | Latency/branch-bound per image; amortized effective ~3.0 GB/s | **Kernel** (~2.6% of `api.parse_many`) |
| 11 | `np.asarray([chunk.size …])` (list-comp + array) | 8 KB (N=1000) | 51–55 µs per N=1000 | 8 KB | 0 | 0 | Python overhead | Glue |
| 12 | `b"".join` neighbor allocs: `np.empty(values)` 136 KB + `statuses` 8 KB + `offsets` | 152 KB | 0.6 µs each class (`np.empty` is O(1)) | 152 KB (uninitialized) | 0 | 0 | Negligible (no touch) | Glue |
| 13 | 7-arg ctypes floor (count=0 measured) | — | **9.4 µs / call** (bench-A) / **19.5 µs** (api-B) — paid **once per batch**, not per image | 0 | 0 | — | Amortized away at N≥100 | Glue |

**End-to-end `api.parse_many` (bb-android ×1000): ~10.3–12.0 ms**
(10.3–12.0 µs/img). Kernel share: **~2.6%**. `_decode` alone is ~75%.
The bench headline batch number (`0.197 µs/img`) is kernel+pre-packed only —
a `api.parse_many` caller sees **~50×** that figure. The README's "13×"
batch ratio compares kernels, not Python paths (pre-packed batch:
mojo 0.287 µs/img vs C++ 2.619 µs/img = 9.1×; mixed: 0.178 vs 1.826 = 10.3×).

**`parse_file`:** 70.5–75.3 µs (bb-android). `Path.read_bytes` alone 28.9–31.9 µs
(~40%). `parse` is ~19 µs; read+parse ≈ 48 µs, leaving **~23 µs unexplained**
per `parse_file` call (Path construction + dispatch on this build — the
delta is stable across repeats, not transient load). It is the only public
entry point whose queue outside `_parse` is material; it is not a
byte-processing cost.

**Strided/non-contiguous input (worst real-caller case):** `api._as_u8` falls
back to `view.tobytes()` — a full copy — and `parse` on a strided
`memoryview` costs **119 µs** (copy ~102 µs) vs **19.8 µs** on `bytes`.
That is the costliest *per-call copy* in the project and is input-layout
dependent, not size dependent.

## 4. Upstream comparison (EasyEXIF C++, vendored build)

No row is slower than upstream. That is the whole comparison — checked two
ways (bench convention and kernel-isolated):

Per fixture, raw `easyexif_parse_jpeg` vs `easyexif_reference_parse_jpeg`
(bench-A convention):

| Fixture | Size | Mojo | C++ | C++/Mojo |
|---|---:|---:|---:|---:|
| bb-android | 11,921 B | 4.51 µs | 7.11 µs | 1.58× |
| test1 | 27,521 B | 4.48 µs | 6.96 µs | 1.55× |
| test2 | 11,260 B | 4.44 µs | 6.93 µs | 1.56× |
| short-ascii-MM | 31,818 B | 4.43 µs | 7.23 µs | 1.63× |
| evil1 | 86,490 B | 4.44 µs | 7.38 µs | 1.66× |
| lens_info | 897 B | 4.33 µs | 5.40 µs | 1.25× |
| right | 5,990 B | 4.31 µs | 4.98 µs | 1.15× |
| down-mirrored | 15,437 B | 4.19 µs | 4.96 µs | 1.19× |

Kernel-isolated (pre-wrapped C): mojo 1.02–1.20 µs vs C++ 1.52–3.73 µs
(**1.48×–3.27×**; GPS images 2.89×–3.27×, non-GPS 1.48×–1.56×). No
fixture is slower than upstream at kernel or at bench-A level. **No row is
flagged "slower than upstream" — there are none to flag.** (Rows where the
*Python glue* dominates are marked in §3; they do not make the kernel
slower, they make the shipped single-call path slower than its own
`bench.py` number suggests.)

Why upstream is slower (structural, from `vendor/easyexif/exif.cpp`):
`IFEntry` allocates a fresh `vector`/`string` per tag (`new_union` per
entry, 818+ symbols in the reference `.so` vs 3 exports in the Mojo `.so`)
and `extract_values` copies every value — strings, shorts, longs,
rationals — for all 50 entries. The port decodes **only covered tags**
(orientation, pointers, focal, GPS subset) and writes 17 floats in place with
zero allocation. The measured gap is allocation avoidance, not arithmetic.
A side note: `bytes.find(b"\xff\xe1")` measures 0.10 µs — a C memchr-type
scan is already faster than either byte loop; neither port uses it.

The same holds for the segment path (pre-wrapped `easyexif_parse_segment`:
0.83–4.0 µs range in bench-A across fixtures; raw 3.75–4.02 µs with C
convention) and for batch (9–15× — single FFI crossing plus unparsed
fields). No input size in the 0.9–86 KB range reverses this.

## 5. Glue analysis (the "where does the time go" core)

### 5.1 `data_as` vs `.ctypes.data` vs pre-wrapped (single call, bb-android)

| Convention | Per call | Δ vs pre-wrapped |
|---|---:|---:|
| (B) `data_as(c_void_p)` fresh (api.py) | 7.5–8.6 µs | +6.2–7.3 µs |
| (A) `.ctypes.data` ints (bench.py) | 4.2–4.6 µs | +3.0–3.3 µs |
| (C) pre-wrapped `c_void_p` | 1.20 µs | baseline |
| `2× .ctypes.data` property fetch alone | 3.15 µs | — |
| `1× data_as(c_void_p)` alone | 3.47 µs | — |
| Pure ctypes floor (pre-built `NULLP`, count-valid) | 0.95 µs | — |

Every `.ctypes.data` / `data_as` access constructs a Python object
(`int` / `c_void_p`) on the heap. `api.py` constructs **two per single call,
five per batch call**, fresh, every call. That is the largest single
`parse`-path cost after `_decode` and it is pure overhead — the kernel
receives the same address either way.

### 5.2 Kernel split (pre-wrapped, bb-android)

- Null call (pure ctypes floor): **0.95 µs**.
- Tiny 4 B (`FF D8 FF D9`, clear + 4 B scan + `NO_EXIF`): **0.95 µs**
  → `clear_result` + 4 B scan ≈ 0 µs at timer resolution (disasm: 4×
  `vmovupd`, not a loop).
- Full bb-android: **1.20 µs** → **IFD walks + 9 rationals ≈ 0.25 µs.**
- Synthetic scan-length sweep (APP1 at 22 / 2,000 / 8,000): 3.80 / 4.90 / 8.21 µs
  (bench-A) → scan is ~0.55 µs per 1,000 bytes *when the marker is far*;
  real fixtures: 22 B → ~0.01 µs. Scan is not the hotspot as shipped.
- Batch amortization (N=1000, kernel-only): **0.27–0.30 µs/img** (pre-packed)
  vs 1.20 µs single-shot → ~0.9 µs/calls of ctypes overhead is amortized to
  ~0.001 µs/img. The batch kernel is the honest kernel-time measure.

### 5.3 Per-element ctypes re-entry: **absent**

- `parse_many` (`api.py:146–179`): **one** native call per batch. No Python
  loop calls into ctypes per image. The per-image Python work is
  `_as_u8` views, the `lengths` list-comp, the `statuses` check loop
  (pure Python), and `[_decode(row) for row in values]` (pure Python) —
  none re-enters the FFI.
- Single-image `parse`/`parse_exif_segment`: exactly one native call each.
- Contrast (measured, user-code baseline): `N × exif.parse` on 100 images is
  2,119 µs (21.2 µs/img) vs `parse_many` 995 µs (9.9 µs/img) — the batch API
  saves 2.1× by avoiding 99 ctypes crossings and 99 `_as_u8`/`empty`
  allocations, *despite* the 590 µs `join` copy. A Python per-element FFI
  loop is a baseline, not a shipped pattern.
- `_decode` **is** a Python per-element loop (`[... for row in values]`):
  7.5 µs/row, no ctypes, but it is the correct label for "Python-level loop
  that re-enters per-element work" — it re-enters *Python object
  construction*, not ctypes.

### 5.4 Per-call allocations / copies (code-read + measured sizes)

| Site (`api.py`) | Per call | Bytes | Cost (N=1000 where noted) |
|---|---|---|---|
| `_as_u8` (`:64`) | 1 view (0-copy) or 1 `tobytes()` copy if non-contiguous | 0 (**or full input, 11,921 B measured at ~102 µs**) | 1.0 µs contiguous / ~102 µs strided |
| `np.empty(17)` (`:114`) | 1 array | 136 B | 0.47 µs |
| `np.empty((N,17))` + `statuses` + `offsets` (`:154,163,164`) | 3 arrays | 152 KB (N=1000) | 0.6 µs each (uninitialized) |
| `b"".join(chunks)` (`:161`) | 1 copy (N>1) | **11.92 MB** (N=1000) | **590–660 µs** |
| `np.asarray([chunk.size …])` (`:153`) | 1 list-comp + array | 8 KB | 51–55 µs |
| `_decode` (`:79`, per row) | 4 dataclasses | — | 7.5 µs/row |
| Mojo kernel | **0 allocations** (`clear_result` in place, writers to `FPtr`) | — | — |
| C++ reference (for contrast) | 1 `EXIFInfo` + ~50 `IFEntry` + ~50 `vector`/`string` allocs/image | ~1–1.5 KB touched | allocation churn = measured gap |

### 5.5 Numpy / Python baselines (whole-image work on the same bytes)

| Baseline | Time on bb-android (11,921 B) | Reading |
|---|---:|---|
| `np.frombuffer` (view creation) | 0.75 µs | The `_as_u8` cost — unavoidable but tiny |
| `a.copy()` (memcpy) | 0.86 µs (13.9 GB/s) | Bandwidth reference: kernel at 3.0 GB/s is 4.6× below BW |
| `bytes.find(b"\xff\xe1")` (C search) | 0.10 µs | Real scan idiom; beats both byte loops |
| Python head-scan (22 B, mirroring `parse_jpeg`) | 2.0 µs | Measured ~2 µs on **every** fixture — flat because only ~24 B are scanned |
| NumPy full-image `where` (APP1+EOI, 2 passes) | 10–90 µs (scales with file size) | **Slower than the kernel it would replace** — broadcasts over the whole file; allocates temporaries |
| NumPy head-64 B search | 5.35 µs | Even head-only numpy loses to `bytes.find` |
| 50× `struct.unpack_from` (per-entry Python loop) | 9.85 µs | What an IFD walk in Python would cost — 40× the kernel's 0.25 µs |
| `np.empty((1000,17))` | 0.62 µs | Allocation is not the batch cost; `_decode` and `join` are |

There is no numpy "EXIF parse" baseline to quote: no pure-numpy
equivalent exists, and fabricating one with `where` + per-entry loops
would be slower than both ports by an order of magnitude. The baselines
above bound what each line of glue *could* cost.

## 6. Roofline / GPU verdicts (with the flops-per-byte behind each)

Kernel flops/byte = **0.023 (860 B denominator) / 0.0014 (full file) /
0.87 ops/byte counting int ops**. Threshold from `MOJO_NOTES.md` §5: GPU
justifiable when arithmetic intensity is well above ~2 flops/byte
(transfer + launch dominated below that).

| Hotspot | Flops/byte (measured §2) | Verdict | Reason |
|---|---|---|---|
| IFD walks + 9 rationals (kernel) | 0.023 flops/B (0.87 ops/B) | **gpu: no** | Two orders below threshold, and the "ops" are serial pointer-chases with `has_range`/`entry_is_valid` branches — a GPU would serialize on the first `read_u16` and pay PCIe copy-in of 11.9 KB + launch (~5–10 µs) to save 0.25 µs |
| JPEG scan (head ~22 B) | ~0.02 flops/B | **gpu: no** | `bytes.find` does it in 0.10 µs on CPU; GPU round-trip is 50× the whole kernel |
| `clear_result` (136 B) | 0 flops/B | **simd: already SIMD** (4× `vmovupd`, verified disasm) | — |
| `_decode` (dataclasses) | ~0 flops/B | **none** | Pure-Python object construction; GPU-irrelevant; it is a Python API cost, not a kernel cost |
| `b"".join` (11.92 MB) | 0 flops/B, ~20 GB/s measured | **none** | Already saturates bandwidth; not Mojo code |
| Batch loop (N images, serial in `easyexif_parse_many`) | 0.017 flops/B per image | **parallel: yes (kernel-level)** | Images are independent (verified: no cross-image state in `src/easyexif.mojo:446–456`); 36 physical cores + observed batch kernel 0.27 µs/img serial → same roofline per core. GPU: no (same 0.02 flops/B; `mojo-easyexif` should stay CPU-only). Unroll: no (loop body is the IFD walk, already branchy). SIMD: only `clear_result` (already present) |

## 7. Next-phase assignment (per hotspot)

| Hotspot (rank §3) | Next phase that should act | Why (evidence) |
|---|---|---|
| 1. `_decode` 7.5 µs/img Python dataclasses (§3.1 row 1, §3.2 row 8) | **none** (for this port's phases: `unroll`/`simd`/`parallel`/`gpu` do not apply) | It is Python object construction outside Mojo. A future phase may add a batched/structured return or lazify decode, but it is not an unroll/simd/parallel/gpu kernel change. It should be recorded as the dominant user-visible cost so kernel work is not mistaken for user cost |
| 2. ctypes `data_as` construction 3.7 µs/call (§5.1) | **none** (Python glue fix belongs to API hygiene, not kernel phases) | Pre-wrapped pointers drop the call from 8.6 → 1.2 µs with identical kernel results (verified lat/lon). Not a kernel phase; benefit is in `api.py`, out of scope for the four kernel phases |
| 3. Serial batch loop 0.27 µs/img (§3.2 row 10) | **parallel** (next *kernel* phase) | Independent images, 36 cores, 0.02 flops/B → classic parallel-not-GPU. Gate behind N threshold; single-image path unaffected (ctypes floor dominates there) |
| 4. IFD/rationals inner walk 0.25 µs/img (§3.1 row 3) | **none** (currently); **unroll** only if profiled hungry | 0.25 µs is 1.3% of user time. Unrolling helps code that is loop-bound; this is branch/pointer-chase-bound. Re-measure after 1–3 are addressed; do not predict |
| 5. JPEG EOI/APP1 byte scan (~0.01 µs real, 0.55 µs/KB far-marker) | **simd** (conditional) | Only becomes a hotspot if callers pass images with late APP1 (synthetic 8 KB: 8.2 µs). A SIMD/word-at-a-time scan or `memmem`-style search is the phase *if* such sizes are in scope. As shipped (22 B), verdict is **none** |
| 6. `b"".join` pack 11.92 MB (§3.2 row 9) | **none** | Bandwidth-saturating copy in Python glue; a Mojo-side gather is an API change, not a kernel phase |
| 7. `parse_file` +23 µs non-compute delta (§3.2) | **none** | Path/read dispatch, not byte work; read_bytes (29 µs) is the OS, not the port |
| 8. Strided-input `tobytes()` copy 102 µs (§3.2) | **none** | Input-layout copy in glue; kernel sees the same bytes either way |

**Slower-than-upstream rows: none.** Every kernel comparison against the
vendored upstream C++ build favors the port (1.15×–1.73× single raw,
1.48×–3.27× kernel-isolated, 9–15× batch). No row is dropped.

## 8. What next phases should not chase (negative results)

- Do not vectorize the IFD loop: the port already skips undecoded entries
  (C++ allocates for all 50); SIMD applies only to the already-SIMD
  `clear_result`.
- Do not GPU-port anything: max GPU arithmetic intensity entry is
  0.023 flops/B; the full kernel is 0.25 µs vs ~5–10 µs launch+copy.
- Do not "fix" file-size scaling: kernel time is flat across 0.9–86 KB
  (760 B entries); only the `join` buffer scales with total input.
- Do not treat `bench.py` batch numbers as user-visible: they exclude
  `_decode` (75%) and `join` and the `data_as` construction, understating
  `api.parse_many` by ~50×.

## 9. Reproduction

```bash
pixi run bench          # flock-wrapped, single-runner; headline §1
pixi run python /tmp/probe12.py   # per-fixture ladder in one process
```

All numbers were captured in-session; no external benchmark was run
alongside (`pixi run bench` is flock-wrapped — it was the only bench
running each time). `src/`, `tests/`, `bench/bench.py`, `README.md`,
`MOJO_NOTES.md`, and `pixi.toml` were left unmodified (`git status` clean
except this file).
