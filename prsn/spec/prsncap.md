# `.prsncap`: the companion capture file

Status: **Draft v1.1**. Container rules (manifest, hashing, canonical JSON, signature) are
those of [prsn.md](prsn.md); this document fixes what goes inside a capture. A `.prsn`
refers to its captures by manifest hash ([prsn.md, Capture references](prsn.md#companion-capture-file-prsncap)).

The keywords MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Principles

- **P1 Write-once.** A `.prsncap` holds only what sensors and the capture application
  observed during the session. Nothing computed after the session ends goes in. Its
  identity is the SHA-256 of its canonical `manifest.json`.
- **P2 Derived data lives in a cache**, keyed by `action_key`
  ([derivation-recipes.md](derivation-recipes.md)). Masks, poses, fits, undistorted frames,
  HDR merges, splits of the video, proxies: never in the capture. A capture manifest entry
  never carries a `derivation`.
- **P3 One clock per session**, `d0.host`; per-device clock models in `session.json`
  ([frames-and-units.md](frames-and-units.md) §5).
- **P4 Sensor-native first.** Depth, IMU, tracker observations and calibration lookup
  tables are kept in the type and units the OS delivered.
- **P5 Tiers are derivations.** A smaller tier made from a larger one is a new `.prsncap`
  with its own manifest and `derived_from`. Never promote; demotion is a recorded recipe
  and needs the user's confirmation.
- **P6 The assembler signs.** Single device: the capture device seals and signs.
  Several devices: each device seals and signs its own device package; the assembling
  application keeps the device signatures and signs the assembled manifest.

## 2. Two physical forms

- **Directory package** (`<slug>.prsncap/`), also the staging form on the capture
  device. Streams are written as separate files and hashed while written (streaming
  SHA-256), so sealing costs nothing extra.
- **ZIP** for export: same tree, `mimetype` first (STORED, no extra field), everything else
  STORED (media) or DEFLATE (JSON, JSONL, binary arrays), ZIP64 when needed. Mimetype
  `application/vnd.prsn.capture+zip`.

Conversion between the two forms is lossless and leaves `manifest.json` byte-identical, so
the manifest hash is the same in both.

## 3. Layout

```
<person-slug>-<started ISO, compact>.prsncap
├── mimetype                        application/vnd.prsn.capture+zip
├── manifest.json                   every entry: path, type, media, sha256, bytes, stream, device
├── session.json                    §4  (critical)
├── splits.json                     §5  held-out frames, fixed at capture time
├── script/
│   ├── script.json                 capture script id, version, phases and prompts (the plan)
│   └── events.jsonl                what happened: phase start/end, prompts spoken, holds, retakes,
│                                   live QC flags, light events, chirps, sync marks
├── devices/
│   ├── d0/                         primary capture device (front camera faces the subject)
│   │   ├── device.json             model, OS, app build, role, per-stream config, first-sample pts
│   │   ├── probe.json              the capability probe report (§4.1)
│   │   ├── calib/
│   │   │   ├── rgb.front.json      K, ref dims, pixel_center, orientation, extrinsic to device ref,
│   │   │   │                       readout_ns (null if unknown), LUT refs, when captured (pts_ns), lens_pos
│   │   │   ├── rgb.front.lut.f32   forward distortion LUT, float32 LE
│   │   │   ├── rgb.front.ilut.f32  inverse LUT
│   │   │   ├── depth.front.json    same for depth + T_cvcam_rgb_from_cvcam_depth
│   │   │   └── rgb.rear.json …     when the rear camera was used
│   │   ├── rgb.front/
│   │   │   ├── <phase>.mov         one QuickTime file per video phase (ProRes RAW | ProRes 422 HQ | HEVC Main10)
│   │   │   └── frames.jsonl        one line per frame, every phase: pts_ns, phase, file, index_in_file,
│   │   │                           exposure_ns, iso, wb_gains, temp_tint, lens_pos, color_space, dropped
│   │   ├── depth.front/
│   │   │   ├── <phase>/000000.exr  one EXR per depth frame, channel Z, native dtype, unfiltered, ZIP-compressed
│   │   │   └── frames.jsonl        pts_ns, phase, path, kind, units, dtype, quality, accuracy, filtered, calib
│   │   ├── stills/
│   │   │   ├── s-0001.dng | .heic  DNG 1.7 (JPEG XL lossless) when stills.raw, else HEIC 10-bit
│   │   │   └── stills.jsonl        pts_ns, phase, path, kind (raw|proraw|processed), exposure, depth sidecar path,
│   │   │                           calib snapshot path
│   │   ├── tracking.arkit/         only phases that ran ARKit face tracking
│   │   │   ├── frames.jsonl        pts_ns, phase, tracking_state, T_cvcam_from_face (16), T_arkitcam_from_face (16),
│   │   │   │                       T_arkitworld_from_arkitcam (16), K (9), blendshapes (52 floats, fixed order),
│   │   │   │                       T_face_from_eyeL (16), T_face_from_eyeR (16), look_at (3), light {ambient, temp, sh[27]}
│   │   │   ├── video/<phase>.mov   captured image encoded HEVC Main (8-bit source) at ≥ 50 Mb/s
│   │   │   ├── video/frames.jsonl  pts_ns ↔ file/index map plus EXIF
│   │   │   ├── depth/<phase>/000000.exr + frames.jsonl   captured depth (640x480), as above
│   │   │   ├── hires/h-0001.heic + hires.jsonl           high-resolution frame stills
│   │   │   ├── face-verts.f16      N × 1220 × 3 float16 LE, row order = frames.jsonl order
│   │   │   ├── topology.json       the ARKit face topology: triangle indices and UVs (§3.2, always embedded)
│   │   │   └── blendshape-targets.f32  the 52 unit blendshape targets (§3.2, always embedded)
│   │   ├── motion/
│   │   │   ├── imu.bin             packed 80-byte records, layout fixed in §3.1
│   │   │   └── imu.json            §3.1: record_bytes, endian, kinds present, rates, reference frame, counts
│   │   ├── audio/
│   │   │   └── session.flac        48 kHz / 24-bit, whole session; first-sample pts_ns in device.json
│   │   └── signatures/manifest.sig device-level signature (multi-device only)
│   └── d1/ …                       satellite devices, same shape (streams they have)
├── environment/
│   ├── probe/
│   │   ├── p-0001.dng | .heic      bracketed rear-camera stills from the subject's position
│   │   └── probe.jsonl             pts_ns, path, ev, exposure, attitude quaternion (cm-device), heading, gravity
│   ├── arkit-envmap.exr            ARKit environment cube map when available (fallback probe)
│   └── background/                 empty-chair plate: referenced as a phase in rgb.front (no copy)
├── colour/
│   └── chart.json                  chart model, reference Lab D50 values, device, pts_ns range of the chart frames
└── signatures/
    └── manifest.sig                Ed25519 over canonical manifest.json
```

The manifest's top level carries `format: "prsncap"`, `version: 1`, `created`,
`generator`, `session: "session.json"`, `entries` and `signature`
([`prsncap-manifest.schema.json`](../schemas/prsncap-manifest.schema.json)).
`session.json` is listed with `critical: true`.

Entry types (`type` in the manifest): `org.prsn.capture.session`, `.splits`, `.script`,
`.events`, `.device`, `.probe-report`, `.calibration`, `.calibration-lut`, `.video`,
`.video-index`, `.depth`, `.depth-index`, `.still`, `.still-index`, `.tracking`,
`.tracking-mesh`, `.tracking-topology`, `.tracking-targets`, `.motion`, `.motion-schema`, `.audio`, `.probe`,
`.probe-index`, `.envmap`, `.colour-chart`. Every entry carries `stream` (e.g.
`d0/rgb.front`) and `device` (`d0`) where applicable, and `phase` for per-phase files.
Per-frame depth files are listed individually in the manifest (they are hashed
individually); an archival session's manifest has about 10 000 entries, which is fine.

Blendshape order: the 52 `ARFaceAnchor.BlendShapeLocation` names in Apple's documented
list order. Never reorder.

### 3.2 The embedded ARKit face template

A capture that holds face-tracking data (`org.prsn.capture.tracking` or
`.tracking-mesh` entries) MUST embed, for each device that produced it, the ARKit face
template those data are expressed in, so the file is self-contained:

- `devices/<d>/tracking.arkit/topology.json`, type `org.prsn.capture.tracking-topology`:
  `{"topology": "arkit-1220", "vertex_count": 1220, "triangles": [[i, j, k], …], "uvs":
  [[u, v], …]}`.
- `devices/<d>/tracking.arkit/blendshape-targets.f32`, type
  `org.prsn.capture.tracking-targets`: 52 × 1220 × 3 float32 little-endian, the vertex
  positions (metres, `arkit-face`) of each unit blendshape target in blendshape order; the
  entry carries `count: 52` and `vertex_count: 1220`.

Every `.tracking` and `.tracking-mesh` entry carries `topology_sha256` and
`targets_sha256`: the `sha256` of the embedded topology and targets entries of the same
device. A capture whose tracking entries name a template it does not embed is invalid
(rule `tracking-template`). The template is generated by Apple's framework at runtime; the
writer is responsible for having the right to redistribute it.

### 3.1 `motion/imu.bin` record layout

Every record is **80 bytes, little-endian, no padding**, in `pts_ns` order (ties broken by
`kind`):

| Offset | Type | Field | Meaning |
|---|---|---|---|
| 0 | `i64` | `pts_ns` | Device host clock ([frames-and-units.md](frames-and-units.md) §5): the sample timestamp in seconds since boot × 1e9, rounded to nearest |
| 8 | `u8` | `kind` | 0 `device_motion`, 1 `gyro`, 2 `accel`, 3 `mag`, 4 `altimeter` |
| 9 | `u8` | `flags` | bit 0: `mag_calibrated` (device_motion/mag); other bits 0 |
| 10 | `u16` | `reserved` | 0 |
| 12 | `u32` | `seq` | Per-kind sequence number from 0; a gap means a dropped sample |
| 16 | `f32[16]` | `v` | Payload, by `kind` (unused slots are 0.0) |

- `device_motion`: `v[0..4]` attitude quaternion `[x, y, z, w]` of `cm-device` relative to
  the reference frame named in `imu.json` (`xArbitraryZVertical`), `v[4..7]` rotation rate
  rad/s, `v[7..10]` user acceleration in g, `v[10..13]` gravity in g, `v[13..16]` magnetic
  field µT (all in `cm-device`).
- `gyro`: `v[0..3]` raw rotation rate rad/s. `accel`: `v[0..3]` raw acceleration in g.
  `mag`: `v[0..3]` raw field µT. `altimeter`: `v[0]` relative altitude m, `v[1]` pressure
  kPa.

`pts_ns` values can exceed 2^53; read them as 64-bit integers, not doubles.

`imu.json` ([`imu.schema.json`](../schemas/imu.schema.json)): `{"version": 1,
"record_bytes": 80, "endian": "little", "frame": "cm-device", "attitude_reference":
"xArbitraryZVertical", "kinds": ["device_motion", "gyro", "accel", "mag", "altimeter"],
"requested_hz": {"device_motion": 100, …}, "counts": {"device_motion": 23840, …},
"first_pts_ns": …, "last_pts_ns": …}`.

Vectors: [`conformance/imu/`](../conformance/imu/): ten records covering every kind,
including a dropped `seq`. A reader decodes the `.bin` to the JSON exactly; a writer
re-encodes the JSON byte for byte.

## 4. `session.json`

Schema: [`session.schema.json`](../schemas/session.schema.json).

```json
{
  "format": "prsncap", "version": 1,
  "session_id": "urn:uuid:…",
  "person_ref": "urn:uuid:…",
  "started": "2026-10-02T18:04:11.204Z", "duration_s": 238.4,
  "tier": "archival" | "standard" | "minimal",
  "derived_from": null | {"manifest_sha256": "…", "recipe": {"id": "org.example.recipe.tier.demote", "version": "1.0.0"}, "action_key": "sha256:…"},
  "script": {"id": "example-guided", "version": "1.0.0", "kind": "full" | "gap-fill" | "expression-topup" | "voice-topup" | "lighting-variety" | "refresh"},
  "clock": {"session_domain": "d0.host", "units": "ns"},
  "devices": [
    {"id": "d0", "model": "iPhone18,1", "os": "iOS 27.0 (…)", "app": "ExampleCapture 1.0", "role": "primary",
     "clock": {"domain": "d0.host", "to_session": {"offset_ns": 0, "drift_ppm": 0, "method": "identity", "residual_ns": 0}}},
    {"id": "d1", "model": "iPad16,3", "role": "satellite", "placement": "above-front",
     "clock": {"domain": "d1.host", "to_session": {"offset_ns": -18233410221, "drift_ppm": 3.1, "method": "ntp-link+audio-chirp", "residual_ns": 410000}}}
  ],
  "streams": [
    {"id": "d0/rgb.front", "kind": "video", "codec": "prores-raw" | "prores-422hq" | "hevc-main10" | "hevc-main",
     "w": 3840, "h": 3840, "orientation": 6, "fps_nominal": 30, "locked_frame_duration": true,
     "color": {"space": "camera-raw" | "appleLog2" | "hlg-bt2020" | "p3-d65" | "srgb", "bit_depth": 12},
     "stabilization": "off", "distortion_correction": false, "center_stage": false, "crop_ref_px": null},
    {"id": "d0/depth.front", "kind": "depth", "sensor": "truedepth", "w": 640, "h": 480, "fps_nominal": 30,
     "dtype": "float16", "native_kind": "disparity", "units": "1/m", "filtered": false},
    {"id": "d0/tracking.arkit", "kind": "tracking", "fps_nominal": 60, "video_w": 1920, "video_h": 1440},
    {"id": "d0/motion", "kind": "motion", "rate_hz": 100},
    {"id": "d0/audio", "kind": "audio", "rate_hz": 48000, "bits": 24, "channels": 1},
    {"id": "d0/stills", "kind": "stills", "format": "dng-jxl" | "heic10", "max_px": [4032, 4032]}
  ],
  "phases": [
    {"id": "setup", "mode": "avf", "started_ns": 0, "ended_ns": 0},
    {"id": "chart", "mode": "avf"}, {"id": "plate", "mode": "avf"},
    {"id": "probe", "mode": "rear"},
    {"id": "orbit", "mode": "avf"}, {"id": "neck", "mode": "avf"}, {"id": "face", "mode": "avf"},
    {"id": "expr", "mode": "arkit"}, {"id": "speech", "mode": "arkit"},
    {"id": "hair-up", "mode": "avf"}, {"id": "raised", "mode": "avf", "optional": true}
  ],
  "exposure_lock": {"iso": 400, "exposure_ns": 8333333, "wb_gains": [1.92, 1.0, 1.71], "lens_pos": 0.41, "locked_at_ns": 0},
  "capabilities": ["rgb.log2", "depth.truedepth.30", "tracking.arkit-face", "stills.raw", "imu.100hz", "audio.48k",
                   "probe.bracketed", "colour-chart", "background-plate"],
  "coord_conventions": {"camera": "opencv", "pose": "world-to-camera", "units": "m", "pixel_center": "0.5",
                        "matrix_layout": "row-major-16", "quaternion": "xyzw"},
  "consent": {"collected_at": "…", "scopes": ["capture", "transfer"], "cloud_families": [], "voice": true, "expires": null},
  "qc": {"live_flags": 3, "retakes": [{"phase": "orbit", "count": 1}]},
  "notes": "window left, overcast"
}
```

Phase modes: `avf` (camera video capture), `arkit` (face tracking), `rear` (rear camera).
`phases[].id` values come from the capture script (§7). `consent.scopes` records what the
person agreed to; `consent.cloud_families` lists the method families the person allows to
be processed off the local machine, per family; `"*"` means all families.

### 4.1 Capability tags

`capabilities` is the tag list recipes match against
([derivation-recipes.md](derivation-recipes.md) §2). Tags come from the device's capability
probe (copied into the capture as `devices/d0/probe.json`, type
`org.prsn.capture.probe-report`, so a capture carries the evidence it was made with) and
from what the session produced:

| Tag | Condition |
|---|---|
| `rgb.raw` | front ProRes RAW with depth |
| `rgb.log2` | front Log 2 video with depth |
| `rgb.10bit` | any 10-bit front video format with depth |
| `rgb.8bit` | always (fallback) |
| `stills.raw` | front RAW/ProRAW still with depth |
| `stills.18mp` | 18 MP processed still with depth |
| `stills.during-video` | still during video recording with no gap |
| `depth.truedepth` | any depth format on the front camera |
| `depth.truedepth.30` | depth at 30 fps |
| `tracking.arkit-face` | face tracking supported |
| `tracking.arkit-face.hires` | high-resolution frame format exists |
| `tracking.arkit-face.exposure-lock` | exposure/WB/focus lock honoured during face tracking |
| `multicam.front+rear` | the front depth camera and a rear camera can run together |
| `imu.100hz` | measured device-motion rate ≥ 90 Hz |
| `audio.48k` | always |
| `probe.bracketed` | the bracketed lighting probe ran |
| `colour-chart`, `background-plate`, `multi-view:<n>` | produced by the session (from its events) |

## 5. `splits.json`

Held-out frames are chosen at capture time by a deterministic rule so every future recipe
is scored on the same frames ([`splits.schema.json`](../schemas/splits.schema.json)):

```json
{"version": 1, "method": "seeded-stride", "seed": 20261002, "stride": 10, "stills_stride": 8,
 "holdout": [
   {"stream": "d0/rgb.front", "phase": "orbit", "frames": [2, 12, 22, …]},
   {"stream": "d0/tracking.arkit", "phase": "expr", "frames": [2, 12, 22, …]},
   {"stream": "d0/stills", "frames": [2, 10, 18]}
 ]}
```

Rule: per stream and phase, with `o = seed mod stride` (video, depth and tracking streams)
or `o = seed mod stills_stride` (the stills stream, one group with no `phase`), frame index
`i` (0-based, in `frames.jsonl` / `stills.jsonl` order within the phase) is held out when
`i mod stride == o`. The seed is used as the plain integer, not hashed. Frames flagged
`dropped` are skipped but keep their index. Groups are listed in stream order, phases in
first-appearance order; a phase with rows but no held-out frame is listed with
`"frames": []`; a stream with no rows is omitted. The example above is the worked case:
`20261002 mod 10 = 2`, `20261002 mod 8 = 2`. Vectors:
[`conformance/splits/`](../conformance/splits/).

Held-out frames are never inputs to a derived asset (`select.exclude_split: "holdout"` is
mandatory in recipes); they exist only for `eval`. Live quality checks during capture MUST
NOT alter the split.

## 6. Tiers and stream configuration

| Stream | archival | standard | minimal |
|---|---|---|---|
| Front video, camera phases | ProRes RAW if `rgb.raw`, else ProRes 422 HQ Log 2 if `rgb.log2`, else ProRes 422 HQ HLG, else HEVC Main10 ≥ 100 Mb/s | HEVC Main10 Log 2 / HLG, ~100 Mb/s | HEVC Main10, ~40 Mb/s |
| Front video, face-tracking phases | HEVC Main ≥ 50 Mb/s (8-bit source) | same | same, 30 Mb/s |
| Depth | lossless EXR, native dtype, unfiltered, full rate | same | same, every 2nd frame |
| Stills | DNG+JXL if `stills.raw`, else HEIC 10-bit | HEIC 10-bit | none |
| Probe | bracketed DNG/HEIC + ARKit envmap | HEIC + envmap | envmap + 12 HEIC |
| Tracking, mesh, IMU, audio, calibration, chart, plate, events, splits | always, in full | always | always (mesh may be omitted) |

Approximate sizes for a 4-minute session (estimates): archival 22–30 GB, standard 5–6 GB,
minimal 2–2.5 GB.

**Never cut at any tier:** depth, calibration and LUTs, per-frame exposure and white
balance, IMU, face-tracking observations (blendshapes, poses), timestamps, colour chart,
background plate, at least the ARKit environment map probe, and `splits.json`.

## 7. Capture script (`script/script.json`)

The script is data, so every device in a session runs the same plan
([`script.schema.json`](../schemas/script.schema.json)). Phase ids and modes are fixed;
prompts and timings are versioned content.

```json
{"id": "example-guided", "version": "1.0.0", "kind": "full",
 "phases": [
   {"id": "setup",   "mode": "avf",   "steps": ["frame", "light-check", "lock-exposure"]},
   {"id": "chart",   "mode": "avf",   "steps": ["hold-chart 5s"]},
   {"id": "plate",   "mode": "avf",   "steps": ["leave-frame 5s"]},
   {"id": "probe",   "mode": "rear",  "steps": ["sit", "hold-device-rear-out", "spin 20s bracketed 3ev x 12"]},
   {"id": "orbit",   "mode": "avf",   "steps": ["neutral", "swivel 360 @30deg/s", "still every 15deg hold 0.7s"]},
   {"id": "neck",    "mode": "avf",   "steps": ["torso-still", "yaw ±70", "pitch ±30", "roll ±20"]},
   {"id": "face",    "mode": "avf",   "steps": ["approach 35cm", "turns", "raw-stills at 5 poses"]},
   {"id": "expr",    "mode": "arkit", "steps": ["52 blendshape prompts hold 1.5s neutral between", "tongue x6", "teeth bite", "gaze 9", "blinks", "subset at ±35 yaw"]},
   {"id": "speech",  "mode": "arkit", "steps": ["harvard-sentences 90s", "free-speech 60s", "room-tone 5s"]},
   {"id": "hair-up", "mode": "avf",   "steps": ["hair back/up", "short orbit 180"]},
   {"id": "raised",  "mode": "avf",   "optional": true, "steps": ["camera raised 30cm pitched down", "orbit 360"]}
 ],
 "global": {"center_stage": false, "stabilization": "off", "distortion_correction": false, "hdr": false, "portrait_effects": false}}
```

Gap-fill and top-up scripts (`kind` other than `full`) use a subset of the same phase ids.
Every spoken prompt, hold, chirp and screen flash is an `events.jsonl` line:
`{"t_ns": …, "phase": "expr", "event": "prompt", "name": "jawOpen", "source": "<device or guide>"}`.

## 8. Sealing and transfer

1. Streams are written into the directory package as they arrive; each file's SHA-256 is
   computed as it is written. A switch between capture modes closes the current media file.
2. At session end the capture application writes `events.jsonl`, `splits.json` and
   `session.json`, builds `manifest.json`, signs it (`signatures/manifest.sig`) and marks
   the package sealed. A sealed package is never modified; a retake creates new phase
   files before sealing.
3. A receiver verifies every entry hash and the signature before accepting the capture.

## 9. Validation

A capture is valid when: every manifest entry's hash and size match; `session.json` is
listed and `critical`; every `streams[]` id has files; every `phases[]` id is in the
script; `frames.jsonl` lines are monotonic in `pts_ns` per stream; `splits.json` follows
the §5 rule and its indices exist; blendshape vectors have 52 entries; `imu.bin` decodes
under §3.1 with monotonic `pts_ns`; and no derived data (no entry with a `derivation`) is
present; every capture with face-tracking data embeds its template (§3.2).

A minimal synthetic capture that passes the checks `tools/validate.py` implements is in
[`examples/prsncap/`](../examples/prsncap/).
