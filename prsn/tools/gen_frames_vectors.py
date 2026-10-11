#!/usr/bin/env python3
"""Generates the frames conformance vectors in conformance/frames/ (spec/frames-and-units.md §6).

Stdlib only, so it runs anywhere. Expected values are produced by *forward*
construction (compose rotations from known angles, apply formulas) or are written
out by hand (bins, Vision orientation cases), never by running a decomposition we
are trying to test. Re-run after any deliberate change:

    python3 tools/gen_frames_vectors.py
"""

import json
import math
import os

HERE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "conformance", "frames")
CONTRACT = "spec/frames-and-units.md"


# ----------------------------------------------------------------- tiny linear algebra
def matmul(a, b):
    n, m, p = len(a), len(b), len(b[0])
    return [[sum(a[i][k] * b[k][j] for k in range(m)) for j in range(p)] for i in range(n)]


def matvec(a, v):
    return [sum(a[i][k] * v[k] for k in range(len(v))) for i in range(len(a))]


def transpose(a):
    return [list(r) for r in zip(*a)]


def rx(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def ry(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rz(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def euler_to_rv(yaw, pitch, roll):
    """R_v = Ry(yaw) . Rx(pitch) . Rz(roll) (contract §3)."""
    return matmul(matmul(ry(yaw), rx(pitch)), rz(roll))


F3 = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
F4 = [[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]]


# A: maps a direction in the stored image's cv axes (x right, y down) to the upright
# (displayed) image's cv axes. EXIF 6 = rotate 90 CW to display.
ORIENTATIONS = {
    1: [[1, 0], [0, 1]],
    2: [[-1, 0], [0, 1]],
    3: [[-1, 0], [0, -1]],
    4: [[1, 0], [0, -1]],
    5: [[0, 1], [1, 0]],
    6: [[0, -1], [1, 0]],
    7: [[0, -1], [-1, 0]],
    8: [[0, 1], [-1, 0]],
}


def lift(a):
    """U: the 3x3 lift of A acting on cv-cam vectors (optical axis unchanged)."""
    return [[a[0][0], a[0][1], 0], [a[1][0], a[1][1], 0], [0, 0, 1]]


def head_mirror(a):
    """H = diag(-1,1,1) for a mirrored orientation (det A < 0), else I."""
    det = a[0][0] * a[1][1] - a[0][1] * a[1][0]
    return [[-1 if det < 0 else 1, 0, 0], [0, 1, 0], [0, 0, 1]]


def stored_from_upright(o, r_cvup):
    """R_cvcam_from_head (stored) = U^T . R_cvup_from_head . H (forward construction)."""
    a = ORIENTATIONS[o]
    return matmul(matmul(transpose(lift(a)), r_cvup), head_mirror(a))


def rigid(r, t):
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0, 0, 0, 1]]


def rigid_inv(m):
    r = [row[:3] for row in m[:3]]
    t = [row[3] for row in m[:3]]
    rt = transpose(r)
    ti = [-x for x in matvec(rt, t)]
    return rigid(rt, ti)


def apply(m, p):
    return matvec(m, list(p) + [1])[:3]


def clean(x, nd=15):
    if isinstance(x, list):
        return [clean(v, nd) for v in x]
    if isinstance(x, float):
        y = round(x, nd)
        return 0.0 if y == 0 else y
    return x


def rowmajor(m):
    return clean([v for row in m for v in row])


def write(name, doc):
    path = os.path.join(HERE, name)
    with open(path, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print("wrote", path)


# ----------------------------------------------------------------- matrix_layout.json
def matrix_layout():
    seq = [[float(4 * r + c + 1) for c in range(4)] for r in range(4)]
    rot_t = rigid(rz(90), [1.0, 2.0, 3.0])
    rot_t = [[round(v, 15) + 0.0 for v in row] for row in rot_t]
    return {
        "rule": "JSON matrices are 16 floats row by row (m00 m01 m02 m03 m10 ... m33); "
        "simd 4x4 is column-major in memory, serialisers transpose.",
        "contract": CONTRACT + " §3",
        "tolerance": 1e-12,
        "cases": [
            {
                "name": "sequential-entries",
                "row_major": rowmajor(seq),
                "column_major_memory": clean([seq[r][c] for c in range(4) for r in range(4)]),
                "elements": [
                    {"row": 0, "col": 3, "value": 4.0},
                    {"row": 3, "col": 0, "value": 13.0},
                    {"row": 1, "col": 2, "value": 7.0},
                ],
                "point_h": [1.0, 2.0, 3.0, 1.0],
                "expected_h": clean(matvec(seq, [1.0, 2.0, 3.0, 1.0])),
            },
            {
                "name": "rz90-plus-translation",
                "note": "T_a_from_b: rotate +90 deg about z then translate (1,2,3); p_a = T . p_b",
                "row_major": rowmajor(rot_t),
                "column_major_memory": clean([rot_t[r][c] for c in range(4) for r in range(4)]),
                "elements": [
                    {"row": 0, "col": 3, "value": 1.0},
                    {"row": 1, "col": 3, "value": 2.0},
                    {"row": 2, "col": 3, "value": 3.0},
                    {"row": 0, "col": 1, "value": -1.0},
                    {"row": 1, "col": 0, "value": 1.0},
                ],
                "point_h": [1.0, 0.0, 0.0, 1.0],
                "expected_h": [1.0, 3.0, 3.0, 1.0],
                "inverse_row_major": rowmajor(rigid_inv(rot_t)),
            },
        ],
    }


# ----------------------------------------------------------------- quat_vs_matrix.json
def quat_vs_matrix():
    h = math.sqrt(0.5)
    s3 = math.sqrt(3) / 2
    cases = [
        ("identity", [0, 0, 0, 1], [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 2, 3], [1, 2, 3]),
        ("x+90", [h, 0, 0, h], [[1, 0, 0], [0, 0, -1], [0, 1, 0]], [0, 1, 0], [0, 0, 1]),
        ("y+90", [0, h, 0, h], [[0, 0, 1], [0, 1, 0], [-1, 0, 0]], [0, 0, 1], [1, 0, 0]),
        ("z+90", [0, 0, h, h], [[0, -1, 0], [1, 0, 0], [0, 0, 1]], [1, 0, 0], [0, 1, 0]),
        ("z+60", [0, 0, 0.5, s3], [[0.5, -s3, 0], [s3, 0.5, 0], [0, 0, 1]], [1, 0, 0], [0.5, s3, 0]),
        ("x+180", [1, 0, 0, 0], [[1, 0, 0], [0, -1, 0], [0, 0, -1]], [0, 1, 1], [0, -1, -1]),
        ("axis111+120 (x->y->z->x)", [0.5, 0.5, 0.5, 0.5], [[0, 0, 1], [1, 0, 0], [0, 1, 0]], [1, 0, 0], [0, 1, 0]),
        ("negated z+90 is the same rotation", [0, 0, -h, -h], [[0, -1, 0], [1, 0, 0], [0, 0, 1]], [1, 0, 0], [0, 1, 0]),
    ]
    # One generic case built from Euler angles; its quaternion is the Hamilton product
    # qy * qx * qz (half-angle form), computed independently of the matrix.
    def qaxis(ax, deg):
        s, c = math.sin(math.radians(deg) / 2), math.cos(math.radians(deg) / 2)
        v = [0.0, 0.0, 0.0]
        v[ax] = s
        return v + [c]

    def qmul(a, b):
        ax, ay, az, aw = a
        bx, by, bz, bw = b
        return [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ]

    q = qmul(qmul(qaxis(1, 40), qaxis(0, -25)), qaxis(2, 70))
    r = matmul(matmul(ry(40), rx(-25)), rz(70))
    p = [0.3, -0.2, 0.9]
    cases.append(("generic Ry40.Rx-25.Rz70", q, r, p, matvec(r, p)))

    out = []
    for name, q, r, p, e in cases:
        canon = list(q)
        if canon[3] < 0:
            canon = [-v for v in canon]
        out.append({
            "name": name,
            "quat_xyzw": clean([float(v) for v in q]),
            "matrix_row_major": clean([float(v) for row in r for v in row]),
            "quat_from_matrix_xyzw": clean([float(v) for v in canon]),
            "point": clean([float(v) for v in p]),
            "rotated": clean([float(v) for v in e]),
        })
    return {
        "rule": "Quaternions are [x, y, z, w], unit, Hamilton, rotating points by p' = q p q*. "
        "Matrix -> quaternion returns the representative with w >= 0 (for w == 0, compare up to sign).",
        "contract": CONTRACT + " §3",
        "tolerance": 1e-12,
        "cases": out,
    }


# ----------------------------------------------------------------- arkit_cv.json (F)
def arkit_cv():
    t_ak_from_x = rigid(matmul(ry(25), rx(-10)), [0.05, -0.02, -0.45])
    t_x_from_ak = rigid_inv(t_ak_from_x)
    p_ak = [0.1, 0.2, -0.5]
    return {
        "rule": "F = diag(1,-1,-1,1). T_cvcam_from_X = F . T_arkitcam_from_X; T_X_from_cvcam = T_X_from_arkitcam . F.",
        "contract": CONTRACT + " §3",
        "tolerance": 1e-12,
        "F_row_major": rowmajor(F4),
        "cases": [
            {
                "name": "left-multiply (to cv-cam)",
                "T_arkitcam_from_X": rowmajor(t_ak_from_x),
                "T_cvcam_from_X": rowmajor(matmul(F4, t_ak_from_x)),
            },
            {
                "name": "right-multiply (from cv-cam)",
                "T_X_from_arkitcam": rowmajor(t_x_from_ak),
                "T_X_from_cvcam": rowmajor(matmul(t_x_from_ak, F4)),
            },
        ],
        "points": [
            {
                "name": "a point in front of the camera",
                "p_arkitcam": p_ak,
                "p_cvcam": clean(matvec(F3, p_ak)),
                "note": "in front: arkit-cam z < 0, cv-cam z > 0",
            }
        ],
    }


# ----------------------------------------------------------------- arkit_face_to_cv.json
def arkit_face_to_cv():
    cam_world = rigid(matmul(ry(10), rx(5)), [0.05, 1.2, 0.3])  # T_arkitworld_from_arkitcam
    cases = []
    specs = [
        ("frontal, nose 0.1 m toward camera", 1, (0, 0, 0), [0.02, -0.03, -0.4]),
        ("yaw 20 pitch -5 roll 3", 1, (20, -5, 3), [-0.04, 0.01, -0.35]),
        ("front stream stored in orientation 6, upright yaw 15 pitch 5 roll -4", 6, (15, 5, -4),
         [0.03, 0.02, -0.38]),
    ]
    for name, o, (y, p, r), t in specs:
        # arkit-cam axes coincide with the "viewer" axes (x right, y up, z toward user) of
        # the stored image, so for orientation 1 the face rotation in arkit-cam is Ry Rx Rz
        # of the contract angles. Otherwise build the upright cv rotation, take it to the
        # stored frame, and back to arkit-cam: R_arkitcam = F3 . U^T . F3 . R_v . H.
        r_ak = matmul(F3, stored_from_upright(o, matmul(F3, euler_to_rv(y, p, r))))
        face_in_cam = rigid(r_ak, t)  # T_arkitcam_from_face (truth)
        face_world = matmul(cam_world, face_in_cam)  # T_arkitworld_from_face (what ARKit gives)
        t_cv = matmul(F4, face_in_cam)
        origin_ak = apply(face_in_cam, [0, 0, 0])
        nose_ak = apply(face_in_cam, [0, 0, 0.1])
        cases.append({
            "name": name,
            "T_arkitworld_from_arkitcam": rowmajor(cam_world),
            "T_arkitworld_from_face": rowmajor(face_world),
            "expected_T_arkitcam_from_face": rowmajor(face_in_cam),
            "expected_T_cvcam_from_face": rowmajor(t_cv),
            "orientation": o,
            "expected_euler_deg": {"yaw": float(y), "pitch": float(p), "roll": float(r)},
            "nose_face": [0.0, 0.0, 0.1],
            "expected_origin_cvcam": clean(apply(t_cv, [0, 0, 0])),
            "expected_nose_cvcam": clean(apply(t_cv, [0, 0, 0.1])),
            "expected_origin_arkitcam": clean(origin_ak),
            "expected_nose_arkitcam": clean(nose_ak),
        })
    return {
        "rule": "T_arkitcam_from_face = inv(T_arkitworld_from_arkitcam) . T_arkitworld_from_face; "
        "T_cvcam_from_face = F . T_arkitcam_from_face. Frontal case: nose cv z is exactly 0.1 smaller "
        "than origin cv z (both positive) and nose cv x has the sign of nose arkit x. "
        "expected_euler_deg are display-upright contract angles for the case's stream `orientation`.",
        "contract": CONTRACT + " §3",
        "tolerance": 1e-9,
        "cases": cases,
    }


# ----------------------------------------------------------------- euler_signs.json
def euler_signs():
    specs = [
        ("yaw +30: nose toward viewer's right", 30, 0, 0),
        ("pitch +20: chin down", 0, 20, 0),
        ("roll +15: viewer's-right side of head rises", 0, 0, 15),
        ("combined yaw 40 pitch -10 roll 5", 40, -10, 5),
        ("looking straight at the camera", 0, 0, 0),
        ("profile yaw -90", -90, 0, 0),
        ("near-back yaw 170 pitch 12", 170, 12, -8),
        ("roll +120: head past sideways (roll range [-180, 180))", 0, 0, 120),
    ]
    cases = []
    for name, y, p, r in specs:
        rv = euler_to_rv(y, p, r)
        rcv = matmul(F3, rv)  # R_cvcam_from_head
        cases.append({
            "name": name,
            "R_cvcam_from_head_row_major": clean([v for row in rcv for v in row]),
            "expected_deg": {"yaw": float(y), "pitch": float(p), "roll": float(r)},
            "nose_dir_cvcam": clean(matvec(rcv, [0, 0, 1])),
            "head_right_dir_cvcam": clean(matvec(rcv, [1, 0, 0])),
        })
    # Boundaries (expected written by hand)
    cases.append({
        "name": "yaw 180 normalises to -180 (range [-180, 180))",
        "R_cvcam_from_head_row_major": rowmajor(matmul(F3, [[-1, 0, 0], [0, 1, 0], [0, 0, -1]])),
        "expected_deg": {"yaw": -180.0, "pitch": 0.0, "roll": 0.0},
    })
    cases.append({
        "name": "upside-down head: roll 180 normalises to -180",
        "R_cvcam_from_head_row_major": rowmajor(matmul(F3, [[-1, 0, 0], [0, -1, 0], [0, 0, 1]])),
        "expected_deg": {"yaw": 0.0, "pitch": 0.0, "roll": -180.0},
    })
    cases.append({
        "name": "gimbal: pitch +90 (chin straight down), roll reported 0",
        "R_cvcam_from_head_row_major": rowmajor(matmul(F3, euler_to_rv(25, 90, 0))),
        "expected_deg": {"yaw": 25.0, "pitch": 90.0, "roll": 0.0},
    })
    cases.append({
        "name": "gimbal: pitch -90, roll reported 0",
        "R_cvcam_from_head_row_major": rowmajor(matmul(F3, euler_to_rv(-35, -90, 0))),
        "expected_deg": {"yaw": -35.0, "pitch": -90.0, "roll": 0.0},
    })
    return {
        "rule": "R_v = F3 . R_cvcam_from_head, F3 = diag(1,-1,-1); R_v = Ry(yaw) . Rx(pitch) . Rz(roll). "
        "+yaw: nose to the viewer's right (cv x > 0); +pitch: chin down (nose cv y > 0); "
        "+roll: viewer's-right side rises (head-right dir cv y < 0). yaw and roll in [-180,180), "
        "pitch in [-90,90]. At |pitch| = 90 (gimbal lock, cos pitch < 1e-9) roll is reported as 0 "
        "and yaw carries the whole in-plane angle. Matrices here are of an upright stream "
        "(orientation 1), where stored cv-cam and display-upright cv-cam coincide; other "
        "orientations: upright_euler.json.",
        "contract": CONTRACT + " §3",
        "tolerance_deg": 1e-7,
        "cases": cases,
    }


# ----------------------------------------------------------------- vision_pose.json
def vision_pose():
    d = math.radians
    # (orientation, vision yaw/pitch/roll degrees, expected contract degrees, why).
    # Vision measured the display-upright image, so the contract angles are Vision's own,
    # whatever the stored orientation (Euler angles are display-upright).
    specs = [
        (1, (0, 0, 0), (0, 0, 0), "upright stored frame: identity"),
        (1, (30, 0, 0), (30, 0, 0), "Vision +yaw (right-hand about image +y, z toward viewer) = nose to viewer's right"),
        (1, (0, 20, 0), (0, 20, 0), "Vision +pitch (right-hand about image +x) = chin down"),
        (1, (0, 0, 15), (0, 0, 15), "Vision +roll (counter-clockwise in the y-up image) = viewer's-right side rises"),
        (1, (-40, 10, -5), (-40, 10, -5), "combined"),
        (6, (0, 0, 0), (0, 0, 0), "front stream (sensor-native portrait, EXIF 6): an upright head is 0, not roll 90"),
        (6, (30, 0, 0), (30, 0, 0), "display yaw stays yaw (in the stored frame it would be a chin-up)"),
        (6, (0, 20, 0), (0, 20, 0), "display chin-down stays pitch"),
        (6, (0, 0, 10), (0, 0, 10), "rolls are display rolls"),
        (8, (0, 0, 0), (0, 0, 0), "stored frame must turn 90 CCW to be upright"),
        (3, (30, 0, 0), (30, 0, 0), "upside-down stored frame"),
        (2, (30, 10, 5), (30, 10, 5), "mirrored stream: Vision saw the un-mirrored upright image"),
        (4, (0, 0, 0), (0, 0, 0), "vertical mirror"),
        (5, (-20, 5, 0), (-20, 5, 0), "transpose"),
        (7, (0, 0, -25), (0, 0, -25), "transverse"),
        (1, (0, 0, 180), (0, 0, -180), "roll 180 normalises to -180 (range [-180, 180))"),
        (6, (0, 0, -100), (0, 0, -100), "roll beyond 90 is kept (head past sideways)"),
    ]
    cases = []
    for o, (vy, vp, vr), (ey, ep, er), why in specs:
        cases.append({
            "orientation": o,
            "vision_rad": {"yaw": d(vy), "pitch": d(vp), "roll": d(vr)},
            "expected_deg": {"yaw": float(ey), "pitch": float(ep), "roll": float(er)},
            "why": why,
            "verified_on_device": False,
        })
    return {
        "rule": "The Vision-to-contract mapping takes VNFaceObservation angles "
        "(radians) to contract Euler degrees in the display-upright head frame. "
        "`orientation` is the EXIF orientation handed to VNImageRequestHandler, i.e. the stored "
        "stream's orientation, so Vision measured the upright (un-mirrored) image; the mapping is "
        "therefore a unit conversion plus range normalisation for every orientation.",
        "contract": CONTRACT + " §3",
        "assumed_vision_convention": "Vision angles are right-hand rotations about the axes of its "
        "upright image frame (x right, y up, z out of the image toward the viewer), composed as "
        "Ry(yaw) . Rx(pitch) . Rz(roll), with the face looking at the camera = 0. Authored from "
        "Apple's documented image-space convention (lower-left origin, y up); NOT yet verified on "
        "a device (`verified_on_device: false`). A confirmed sign flip is a change to these vectors.",
        "algorithm": "contract = euler(Ry.Rx.Rz(vision)) (degrees; yaw, roll wrapped to [-180,180)). "
        "The stored pose of the same head is orientation-dependent: see upright_euler.json.",
        "orientations": {str(k): v for k, v in ORIENTATIONS.items()},
        "orientations_note": "A maps a direction in the stored image's pixel axes (u right, v down) "
        "to the upright (displayed) image's pixel axes. EXIF 6 = rotate 90 CW to display.",
        "tolerance_deg": 1e-7,
        "cases": cases,
    }


# ----------------------------------------------------------------- upright_euler.json
def upright_euler():
    hand = [
        # (orientation, stored-frame Euler of R_cvcam_from_head, expected display-upright, why)
        (1, (40, -10, 5), (40, -10, 5), "upright stream: stored and display frames coincide"),
        (6, (0, 0, 90), (0, 0, 0), "EXIF 6 (turn 90 CW to display): a head rolled 90 CCW in the stored frame is upright"),
        (6, (0, -30, 90), (30, 0, 0), "display-right is stored-up: a stored chin-up is a display yaw"),
        (6, (20, 0, 90), (0, 20, 0), "display-down is stored-right: a stored +yaw is a display chin-down"),
        (6, (0, 0, 100), (0, 0, 10), "rolls subtract the 90 of the sensor"),
        (8, (0, 0, -90), (0, 0, 0), "EXIF 8 (turn 90 CCW to display)"),
        (3, (0, 0, -180), (0, 0, 0), "EXIF 3: upside-down stored frame"),
        (3, (-30, 0, -180), (30, 0, 0), "display-right is stored-left"),
        (2, (-30, 10, -5), (30, 10, 5), "mirrored: yaw and roll flip, pitch keeps its sign"),
        (4, (0, 0, -180), (0, 0, 0), "vertical mirror: the (mirrored) face appears upside down when stored"),
        (5, (0, 0, 90), (0, 0, 0), "transpose: head top points stored-left"),
        (7, (0, 0, -90), (0, 0, 0), "transverse: head top points stored-right"),
    ]
    cases = []
    for o, (sy, sp, sr), (ey, ep, er), why in hand:
        cases.append({
            "orientation": o,
            "R_cvcam_from_head_row_major": rowmajor(matmul(F3, euler_to_rv(sy, sp, sr))),
            "stored_frame_euler_deg": {"yaw": float(sy), "pitch": float(sp), "roll": float(sr)},
            "expected_deg": {"yaw": float(ey), "pitch": float(ep), "roll": float(er)},
            "why": why,
        })
    # Forward construction for every orientation: upright angles -> stored matrix.
    for o in range(1, 9):
        for (y, p, r) in ((25, -12, 8), (-70, 30, -140)):
            stored = stored_from_upright(o, matmul(F3, euler_to_rv(y, p, r)))
            cases.append({
                "orientation": o,
                "R_cvcam_from_head_row_major": rowmajor(stored),
                "expected_deg": {"yaw": float(y), "pitch": float(p), "roll": float(r)},
                "why": "forward construction: R = U^T . F3 . Ry.Rx.Rz(expected) . H",
            })
    return {
        "rule": "Head Euler angles are display-upright: for a stream with EXIF `orientation`, "
        "R_cvup_from_head = U . R_cvcam_from_head . H and R_v = F3 . R_cvup_from_head = "
        "Ry(yaw) . Rx(pitch) . Rz(roll). U is the 3x3 lift of A (orientations table in "
        "vision_pose.json); H = diag(-1,1,1) for mirrored orientations (2, 4, 5, 7), else I. "
        "Stored 4x4 poses stay sensor-native cv-cam; only the angles (and bins) are upright. "
                "The inverse (angles -> stored R) must rebuild R_cvcam_from_head_row_major.",
        "contract": CONTRACT + " §3",
        "tolerance_deg": 1e-7,
        "cases": cases,
    }


# ----------------------------------------------------------------- backproject.json
def backproject():
    K = {"fx": 1400.0, "fy": 1410.0, "cx": 960.5, "cy": 720.25, "width": 1920, "height": 1440}

    def bp(u, v, z):
        return [(u - K["cx"]) * z / K["fx"], (v - K["cy"]) * z / K["fy"], z]

    cases = [
        {"name": "principal point", "u": 960.5, "v": 720.25, "depth": 0.5, "expected": [0.0, 0.0, 0.5]},
        {"name": "pixel (0,0) centre is (0.5,0.5)", "pixel": [0, 0], "u": 0.5, "v": 0.5, "depth": 0.4,
         "expected": clean(bp(0.5, 0.5, 0.4))},
        {"name": "right and below", "u": 1500.0, "v": 1000.0, "depth": 0.35, "expected": clean(bp(1500.0, 1000.0, 0.35))},
        {"name": "disparity 2.5 /m -> z 0.4", "u": 400.0, "v": 300.0, "disparity": 2.5, "expected": clean(bp(400.0, 300.0, 0.4))},
        {"name": "hole (NaN depth, JSON null)", "u": 10.0, "v": 10.0, "depth": None, "expected": None},
        {"name": "zero depth is a hole", "u": 10.0, "v": 10.0, "depth": 0.0, "expected": None},
        {"name": "negative depth is a hole", "u": 10.0, "v": 10.0, "depth": -0.2, "expected": None},
        {"name": "zero disparity is a hole", "u": 10.0, "v": 10.0, "disparity": 0.0, "expected": None},
    ]
    proj = [
        {"point": [0.1, -0.05, 0.5], "expected_uv": [1400.0 * 0.2 + 960.5, 1410.0 * -0.1 + 720.25]},
        {"point": [0.0, 0.0, -0.5], "expected_uv": None, "note": "behind the camera"},
    ]
    scale = {
        "from": K,
        "to_width": 640, "to_height": 480,
        "expected": {"fx": 1400.0 / 3, "fy": 1410.0 / 3, "cx": 960.5 / 3, "cy": 720.25 / 3, "width": 640, "height": 480},
    }
    return {
        "rule": "u = fx x/z + cx, v = fy y/z + cy; pixel (i,j) centre at (i+0.5, j+0.5). "
        "Back-projection z = depth (or 1/disparity), x = (u-cx) z/fx, y = (v-cy) z/fy. "
        "Non-finite or non-positive z is a hole (null). Scaling: fx' = fx w'/w, cx' = cx w'/w, same for y.",
        "contract": CONTRACT + " §4",
        "tolerance": 1e-12,
        "K": K,
        "cases": cases,
        "project": proj,
        "scale": clean(scale),
    }


# ----------------------------------------------------------------- bins.json
def bins():
    yaw = [(-180.0, 0), (-179.99, 0), (-165.0, 1), (-0.001, 11), (0.0, 12), (14.999, 12), (15.0, 13),
           (179.0, 23), (179.999999, 23), (180.0, 23), (-200.0, 0), (200.0, 23)]
    pitch = [(-90.0, 0), (-75.0, 1), (-0.5, 5), (0.0, 6), (44.9, 8), (89.99, 11), (90.0, 11), (-95.0, 0), (95.0, 11)]
    cond = [
        (0.0, 0.0, False, "frontal"), (14.9, 0.0, False, "frontal"), (-14.9, 0.0, False, "frontal"),
        (15.0, 0.0, False, "three-quarter"), (-15.0, 0.0, False, "three-quarter"), (59.9, 0.0, False, "three-quarter"),
        (60.0, 0.0, False, "profile"), (-119.9, 0.0, False, "profile"), (120.0, 0.0, False, "back"),
        (-180.0, 0.0, False, "back"),
        (0.0, 30.0, False, "frontal"),
        (0.0, 15.0, True, "down"), (40.0, 20.0, True, "down"), (0.0, -15.0, True, "up"),
        (70.0, -14.9, True, "profile"), (5.0, 14.9, True, "frontal"),
    ]
    return {
        "rule": "Inputs are display-upright contract angles (upright_euler.json). "
        "yaw bin = min(floor((yaw+180)/15), 23); pitch bin = min(floor((pitch+90)/15), 11). "
        "Inputs below the range clamp to bin 0 (both languages; outside the contract's range). "
        "condition from |yaw|: frontal < 15 <= three-quarter < 60 <= profile < 120 <= back. "
        "Stills bank only: pitch >= 15 -> 'down' (chin down), pitch <= -15 -> 'up', overriding yaw. "
        "Bin key (enrichment-model.md): 'yaw:<id>|pitch:<id>'.",
        "contract": CONTRACT + " §3",
        "yaw_bins": [{"yaw": y, "bin": b} for y, b in yaw],
        "pitch_bins": [{"pitch": p, "bin": b} for p, b in pitch],
        "conditions": [{"yaw": y, "pitch": p, "stills_bank": s, "condition": c} for y, p, s, c in cond],
        "keys": [{"yaw": 0.0, "pitch": 0.0, "key": "yaw:12|pitch:6"}, {"yaw": -180.0, "pitch": 90.0, "key": "yaw:0|pitch:11"}],
    }


if __name__ == "__main__":
    write("matrix_layout.json", matrix_layout())
    write("quat_vs_matrix.json", quat_vs_matrix())
    write("arkit_cv.json", arkit_cv())
    write("arkit_face_to_cv.json", arkit_face_to_cv())
    write("euler_signs.json", euler_signs())
    write("vision_pose.json", vision_pose())
    write("upright_euler.json", upright_euler())
    write("backproject.json", backproject())
    write("bins.json", bins())
