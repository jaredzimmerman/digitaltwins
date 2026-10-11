# Coordinate frames, transforms and units

Status: **Draft v1.1**. Part of the [`.prsn` specification](prsn.md). Every file field
that holds geometry, poses, depth, intrinsics or time follows this document. A sign error
here is easy to make and hard to see, so every rule has a test vector in
[`conformance/frames/`](../conformance/frames/) (§6).

## 1. Units

| Quantity | Unit | Encoding |
|---|---|---|
| Length, position, depth | metres | float |
| Disparity (TrueDepth native) | 1/metre | float, stored as delivered (`kind: "disparity"`) |
| Time stamps | nanoseconds, int64 | `*_ns` fields; never float seconds in files |
| Durations in human-facing JSON | seconds | `duration_s` |
| Angles in human-facing JSON (`pose.yaw` …) | degrees | float |
| Rotations in machine fields | unit quaternion `[x, y, z, w]` or a 4x4 matrix | see §3 |
| Pixels | continuous image coordinates | see §4 |
| Exposure | `exposure_ns`, `iso`, WB as `wb_gains [r, g, b]` and `temp_tint [K, tint]` | as the camera API delivers |
| Colour | named colour space string (`appleLog2`, `hlg-bt2020`, `srgb`, `p3-d65`, `camera-raw`) | per stream |

## 2. Named frames

Frames are referenced by name in files. All frames are right-handed and metric.

| Name | Definition | Where it appears |
|---|---|---|
| `cv-cam:<device>/<stream>` | Camera frame of one stream in **OpenCV convention**: +x right, +y down, +z forward (into the scene). | All stored and derived poses |
| `arkit-cam:<device>/<stream>` | ARKit/RealityKit camera frame: +x right, +y up, +z backward (out of the scene, toward the user). Recorded untouched for provenance. | `tracking.arkit/frames.jsonl` |
| `arkit-face` | `ARFaceAnchor` frame: origin at the centre of the head behind the nose; +x toward the **viewer's right** (the subject's left), +y up, +z out of the face toward the viewer. | `tracking.arkit/frames.jsonl` |
| `arkit-world` | ARKit world frame (gravity-aligned +y up, arbitrary heading). Only meaningful within one ARKit session. | Rear-camera / world-tracking passes |
| `cm-device` | Core Motion device frame: +x right of the screen, +y toward the top of the device, +z out of the screen. | `motion/imu.bin` |
| `session-world` | The `cv-cam:d0/rgb.front` frame at the session's first frame: the capture device on its stand is the world. If the IMU shows the device moved more than 2 mm / 0.2° during a phase, the phase is flagged `camera-moved` and its frames carry per-frame `T_sessionworld_from_cvcam` instead of identity. | Multi-device, derived poses |
| `head-canonical` (`org.prsn.frame.head-canonical`) | Per **era**. Defined by the era's GNM identity fit in its neutral pose: origin = midpoint between the two eyeball centres; +y up, +z out of the face toward the viewer, +x toward the viewer's right (the subject's left). Same handedness and orientation as `arkit-face` and as glTF (+Y up, front = +Z). Scale: metres. | Every splat, mesh, avatar, fit; all cross-session alignment |
| `gnm-template` | The axis convention of the GNM Head v3 model file as shipped. `T_headcanon_from_gnmtemplate` is a constant per model version, given in `conformance/frames/gnm_template.json`. | Head-model fits |
| `flame-canonical`, `ict-canonical`, `mhr-canonical` | The respective models' template frames. Each secondary fit stores `T_headcanon_from_<model>`. | Secondary fits |

`arkit-face` and `head-canonical` differ only by a rigid transform (and `head-canonical`
is fixed per era while `arkit-face` moves with the tracked head). Readers accept the draft
name `arkit-face-anchor` as an alias of `arkit-face`.

## 3. Transforms

- **Naming:** `T_a_from_b` maps points expressed in frame `b` to frame `a`:
  `p_a = T_a_from_b · p_b` (column vectors, homogeneous). Field names use the same
  pattern: `T_cvcam_from_head`, `T_sessionworld_from_cvcam`. Never name a transform by one
  frame only. Never store "pose" without saying which direction.
- **Stored poses are world-to-camera** (`T_cvcam_from_<world>`), as in COLMAP and most
  trainers. Anything camera-to-world is converted before storage, except the untouched
  ARKit native copies.
- **JSON matrices** are 16 floats **row by row** (`m00 m01 m02 m03 m10 … m33`). Column-major
  in-memory types (such as `simd_float4x4`) are transposed when serialised. Vector:
  `matrix_layout.json`.
- **Quaternions** are `[x, y, z, w]`, unit length, Hamilton convention, rotating points by
  `p' = q p q*`. Matrix → quaternion returns the representative with `w ≥ 0`. Vector:
  `quat_vs_matrix.json`.
- **OpenCV ⇄ ARKit camera:** `F = diag(1, -1, -1, 1)`.
  `T_cvcam_from_X = F · T_arkitcam_from_X` and `T_X_from_cvcam = T_X_from_arkitcam · F`.
  Vector: `arkit_cv.json`.
- **ARKit face pose to a stored pose.** ARKit gives `T_arkitworld_from_face` (anchor
  transform) and `T_arkitworld_from_arkitcam` (camera transform). Store:
  `T_arkitcam_from_face = inv(T_arkitworld_from_arkitcam) · T_arkitworld_from_face` (native)
  and `T_cvcam_from_face = F · T_arkitcam_from_face` (canonical). Both go in
  `tracking.arkit/frames.jsonl`. Vector: `arkit_face_to_cv.json`: a synthetic anchor whose
  nose tip is 0.1 m in front of the face origin (+z in `arkit-face`, toward the camera).
  After conversion the nose's `cv-cam` z must be **0.1 m smaller** than the face origin's
  `cv-cam` z (closer to the camera; both positive), and its `cv-cam` x must have the same
  sign as its `arkit-cam` x.
- **Head yaw/pitch/roll** (`pose` on `.prsn` entries, degrees) are defined in the
  **display-upright** head frame: the stream's EXIF `orientation` (§4) applied, so an
  upright head looking straight at the camera is (0, 0, 0) whatever the sensor's native
  orientation. Stored 4x4 poses stay sensor-native `cv-cam`; only the angles and the bins
  below are upright. For a stored `R_cvcam_from_head` on a stream with orientation `o`:
  `R_cvup_from_head = U_o · R_cvcam_from_head · H_o`, where `U_o` is the 3x3 lift
  `[[A, 0], [0, 1]]` of the orientation's 2x2 pixel-axis map `A` (stored → upright; table
  in `vision_pose.json`) and `H_o = diag(-1, 1, 1)` for the mirrored orientations
  (2, 4, 5, 7), else `I` (a mirrored image of a face is a face mirrored about its own
  sagittal plane, so the result stays a rotation). The inverse is
  `R_cvcam_from_head = U_oᵀ · R_cvup_from_head · H_o`.
  Then let `R_v = F3 · R_cvup_from_head` with `F3 = diag(1, -1, -1)` (so a head looking
  straight at the camera gives `R_v = I`). Decompose `R_v = Ry(yaw) · Rx(pitch) · Rz(roll)`,
  right-hand rule about each axis. Meaning: positive yaw = the nose moves toward the
  **viewer's right** (the subject turns to their left); positive pitch = **chin down**;
  positive roll = the viewer's-right side of the head rises (counter-clockwise as the
  viewer sees it), all as seen in the upright (displayed) image. Range: yaw and roll in
  [-180, 180), pitch in [-90, 90] (an upside-down head has |roll| > 90). The orientation
  is always explicit; an EXIF value outside 1–8 is an error, never silently 1. Vectors:
  `euler_signs.json` (signs, orientation 1), `upright_euler.json` (every orientation,
  stored matrix → upright angles and back).
- **Vision face pose → file Euler angles.** Angles from Apple Vision's `VNFaceObservation`
  (`yaw`, `pitch`, `roll`, radians, Vision's image-space conventions) are measured on the
  display-upright, un-mirrored image when the stream's EXIF orientation is passed to the
  request; they are then already display-upright, and the mapping to file angles is a unit
  conversion plus range normalisation, so the same head gives the same angles from ARKit
  and from Vision. Vector: `vision_pose.json` (authored from Apple's documented
  conventions; each case carries `verified_on_device: false` until confirmed on a device).
- **Angle bins** (coverage, budgets) take display-upright angles: 15° yaw bins, id =
  `min(floor((yaw + 180) / 15), 23)` (0…23); 15° pitch bins, id =
  `min(floor((pitch + 90) / 15), 11)` (0…11); the clamp puts the closed upper bound (yaw
  180 after rounding, pitch 90) in the last bin. The bin key is `yaw:<id>|pitch:<id>`.
  A `condition` label maps from yaw: `frontal` |yaw| < 15, `three-quarter`
  15 ≤ |yaw| < 60, `profile` 60 ≤ |yaw| < 120, `back` otherwise; for the stills bank only,
  `pitch ≥ 15` (chin down) is `down` and `pitch ≤ -15` is `up`, overriding yaw. Vector:
  `bins.json`, including both boundary cases.
- **Edge conventions** (enforced by the vectors):
  - Gimbal lock: when `cos(pitch) < 1e-9`, roll is reported as 0 and yaw carries the whole
    in-plane angle.
  - Yaw and roll are wrapped to [-180, 180) (180 becomes -180; never -0).
  - Depth holes: z non-finite or `≤ 0` is a hole, so disparity 0 is a hole (§4).
  - Bins clamp: angles below the range go to bin 0, above it to the last bin; NaN has no
    bin (and no key).
  - Vision angles are taken as right-hand rotations about the upright image axes (x right,
    y up, z toward the viewer), composed `Ry·Rx·Rz`; unverified on a device.

## 4. Images, intrinsics, distortion

- **Pixel coordinates** `(u, v)`: `u` right, `v` down, continuous; the centre of pixel
  `(i, j)` is at `(i + 0.5, j + 0.5)` (COLMAP convention). `K` maps `cv-cam` points to
  these coordinates: `u = fx · x/z + cx`, `v = fy · y/z + cy`. A camera API's delivered `K`
  is stored verbatim with its reference dimensions; it is assumed to use this convention,
  and the half-pixel ambiguity is noted in `calib/*.json` as `pixel_center: "0.5-assumed"`.
- **Scaling** `K` to a stream of different size: `fx' = fx · w'/w`, `cx' = cx · w'/w`, same
  for y. Streams are never cropped by the capture application; if the OS crops, the crop
  rectangle in reference pixels is recorded in the stream configuration.
- **Orientation:** frames are stored in **sensor-native orientation**, with an
  `orientation` field (EXIF values 1–8) in the stream configuration. Intrinsics and LUTs
  refer to the stored orientation. Rotation is a derivation; head Euler angles and bins are
  the one exception, defined display-upright (§3).
- **Distortion:** the camera's forward and inverse lens-distortion lookup tables and the
  distortion centre are stored as binary float32 arrays with their reference dimensions. A
  fitted OpenCV model (`k1 k2 p1 p2 k3`) is a derived cache item
  (`org.prsn.method.calib-fit`) and never replaces the LUT. Frames are stored
  **un-undistorted**.
- **Depth images** have the dimensions the OS delivered. `frames.jsonl` says `kind`
  (`depth` or `disparity`), `units` (`m` or `1/m`), `dtype` (`float16`/`float32`),
  `filtered` (must be `false` for archived streams), and `calib` (a path to the depth
  stream's calibration JSON, which carries the depth↔RGB extrinsic
  `T_cvcam_rgb_from_cvcam_depth`). Holes are NaN. Depth EXR: single channel `Z`, stored in
  the native dtype.
- **Depth ⇄ 3D:** `z = depth` (or `1/disparity`); `x = (u − cx) · z / fx`,
  `y = (v − cy) · z / fy` in `cv-cam` of the depth stream. Vector: `backproject.json`.

## 5. Clocks

- Every sample of every stream carries `pts_ns` on its **device host clock** (the
  device's monotonic host time in nanoseconds; on Apple platforms `mach_absolute_time`
  through `mach_timebase_info`, on which camera sample times, ARKit timestamps and Core
  Motion timestamps are all taken).
- The **session clock domain** is `d0.host` (the primary device). Each device `k` has
  `to_session: {offset_ns, drift_ppm, method, residual_ns}` in `session.json`:
  `t_session = offset_ns + t_dev · (1 + drift_ppm · 1e-6)`. `d0` has offset 0, drift 0.
- `method` names how the model was measured, for example an NTP-style exchange (min-RTT
  filtered, at least 20 samples at the start and end of the session) for offset and drift,
  with start/end audio chirps recorded by every microphone giving an independent residual:
  `"ntp-link+audio-chirp"`. `residual_ns` is the remaining error.
- Frame rates are nominal; never assume `pts_ns` spacing. Dropped frames are recorded
  (`dropped: true` lines with the expected `pts_ns`).

## 6. Test vectors

[`conformance/frames/`](../conformance/frames/) holds small JSON cases: input matrices,
quaternions, angles and pixels with the expected outputs for each rule above. They are
normative: an implementation of these rules passes every case within the stated tolerance.
`tools/gen_frames_vectors.py` regenerates all but `gnm_template.json` by forward
construction (it never runs a decomposition it is meant to test).
