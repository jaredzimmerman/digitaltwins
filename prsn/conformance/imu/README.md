# `imu.bin` vectors

For the record layout in [spec/prsncap.md](../../spec/prsncap.md) §3.1.

- `imu-10.bin`: ten packed 80-byte records (`<i64 pts_ns, u8 kind, u8 flags, u16 reserved,
  u32 seq, f32[16] v>`, little-endian, no padding).
- `imu-10.json`: the decoded records. `records[i].hex` is the exact 80 bytes of record
  `i`, so a writer re-encodes the JSON and compares byte for byte; a reader decodes the
  `.bin` and compares field by field.

| Case | Records |
|---|---|
| every kind (`device_motion`, `gyro`, `accel`, `mag`, `altimeter`) | all |
| `(pts_ns, kind)` tie broken by `kind` | 0/1 and 5/6 |
| dropped sample: gyro `seq` jumps 0 → 2 (`dropped: {"gyro": [1]}`) | 1, 6 |
| `flags` bit 0 (`mag_calibrated`) set and clear | 0, 3 set; 5, 8 clear |
| `pts_ns` around 2^53 (odd values above it are not doubles; read them as 64-bit integers) | all |
| float32 edges: inexact decimals, 1e-30, the smallest subnormal, FLT_MAX, -FLT_MIN | 5 |
| unused payload slots are 0.0 | 1–4, 6–9 |

JSON numbers in `v` are the float32 values widened exactly to double; compare them as
doubles.
