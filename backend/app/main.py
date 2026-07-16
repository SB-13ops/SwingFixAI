"""
SwingFix AI - FastAPI Backend
Real video analysis using MediaPipe Pose + Claude API
"""

import os
import uuid
import json
import socket
import time
import base64
import asyncio
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp
import anthropic
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="SwingFix AI API", version="1.0.0")

# Allow your frontend origin - update this in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# In-memory job store (use Redis in production)
jobs: dict = {}

# Serve the frontend from the same server
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"
SESSIONS_DIR = UPLOAD_DIR / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True, parents=True)
REPORTS_DIR = UPLOAD_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True, parents=True)
JOBS_FILE = UPLOAD_DIR / "jobs.json"


@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "Frontend not found", "looked_in": str(FRONTEND_DIR)}


@app.get("/mobile/{session_id}")
async def serve_mobile(session_id: str):
    page = FRONTEND_DIR / "mobile.html"
    if page.exists():
        return FileResponse(str(page))
    raise HTTPException(status_code=404, detail="Mobile page missing")


# ---- Job persistence (survives restarts) ----
def save_jobs():
    try:
        serializable = {k: v for k, v in jobs.items()}
        JOBS_FILE.write_text(json.dumps(serializable, default=str))
    except Exception:
        pass

def load_jobs():
    if JOBS_FILE.exists():
        try:
            return json.loads(JOBS_FILE.read_text())
        except Exception:
            return {}
    return {}

jobs.update(load_jobs())


# ---- LAN IP detection (so phones on the same WiFi can reach us) ----
def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ---- Sessions (Scan-to-Swing) ----
SLOT_NAMES = ("faceon", "dtl", "front")

@app.post("/api/session")
async def create_session(request: Request):
    session_id = uuid.uuid4().hex[:10]
    (SESSIONS_DIR / session_id).mkdir(exist_ok=True)
    # When deployed publicly (Render, Railway, etc.) the QR must point at the
    # public URL, not the machine's private LAN IP.
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    if host and not host.startswith(("localhost", "127.0.0.1", "0.0.0.0")):
        base = f"{scheme}://{host}"
    else:
        lan_ip = get_lan_ip()
        port = os.environ.get("PORT", "8000")
        base = f"http://{lan_ip}:{port}"
    return {"session_id": session_id, "lan_url": base}


@app.post("/api/session/{session_id}/upload")
async def session_upload(session_id: str, slot: str = Form(...), file: UploadFile = File(...)):
    if slot not in SLOT_NAMES:
        raise HTTPException(status_code=400, detail="Invalid slot")
    sdir = SESSIONS_DIR / session_id
    if not sdir.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    suffix = Path(file.filename).suffix or ".mp4"
    dest = sdir / f"{slot}{suffix}"
    # Remove any earlier upload for this slot
    for old in sdir.glob(f"{slot}.*"):
        old.unlink(missing_ok=True)
    dest.write_bytes(await file.read())
    return {"ok": True, "slot": slot}


def session_video_path(session_id: str, slot: str):
    sdir = SESSIONS_DIR / session_id
    if not sdir.exists():
        return None
    matches = list(sdir.glob(f"{slot}.*"))
    return matches[0] if matches else None


@app.get("/api/session/{session_id}/videos")
async def session_videos(session_id: str):
    return {slot: session_video_path(session_id, slot) is not None for slot in SLOT_NAMES}


@app.get("/api/session/{session_id}/video/{slot}")
async def session_video(session_id: str, slot: str):
    path = session_video_path(session_id, slot)
    if not path:
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(str(path), media_type="video/mp4")


@app.post("/api/session/{session_id}/analyze")
async def session_analyze(session_id: str, background_tasks: BackgroundTasks):
    paths = {}
    for slot in SLOT_NAMES:
        p = session_video_path(session_id, slot)
        if p:
            paths[slot] = str(p)
    if not paths:
        raise HTTPException(status_code=400, detail="No videos in session")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "progress": 0, "step": "Queued", "result": None, "error": None}
    save_jobs()
    background_tasks.add_task(run_analysis_job, job_id, paths, keep_files=True)
    return {"job_id": job_id, "status": "pending", "step": "Queued"}




# ── POSE EXTRACTION ────────────────────────────────────────────────────────────

# ── POSE BACKEND COMPATIBILITY ─────────────────────────────────────────────────
# MediaPipe <= 0.10.14 ships the legacy mp.solutions API (Python <= 3.12).
# MediaPipe >= 0.10.30 (Python 3.13+) removed it in favor of the Tasks API.
# This layer supports both so any Python 3.9 - 3.13+ install works.

from enum import IntEnum

class LANDMARK(IntEnum):
    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28

_LEGACY_API = hasattr(mp, "solutions")

POSE_MODEL_PATH = Path(__file__).parent / "pose_landmarker_lite.task"
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)

def _ensure_pose_model():
    """Download the Tasks API model on first run (about 5 MB)."""
    if POSE_MODEL_PATH.exists():
        return
    import urllib.request
    print("Downloading pose model (one time, ~5 MB)...")
    try:
        urllib.request.urlretrieve(POSE_MODEL_URL, str(POSE_MODEL_PATH))
    except Exception as e:
        raise RuntimeError(
            f"Could not download the pose model. Download it manually from "
            f"{POSE_MODEL_URL} and save it as {POSE_MODEL_PATH}"
        ) from e


class _TaskLandmark:
    """Adapter for Tasks API landmarks. Some MediaPipe versions leave
    visibility unpopulated (0.0), which would wrongly fail our > 0.3
    filters - fall back to presence, then to 1.0."""
    __slots__ = ("x", "y", "z", "visibility")

    def __init__(self, l):
        self.x = l.x
        self.y = l.y
        self.z = getattr(l, "z", 0.0)
        v = getattr(l, "visibility", None)
        if not v:
            v = getattr(l, "presence", None) or 1.0
        self.visibility = v


class PoseDetector:
    """Uniform wrapper: .process(rgb) returns a list of 33 landmarks
    (each with .x .y .z .visibility) or None, on either MediaPipe API."""

    def __init__(self):
        if _LEGACY_API:
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        else:
            _ensure_pose_model()
            from mediapipe.tasks import python as mp_tasks
            from mediapipe.tasks.python import vision
            opts = vision.PoseLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=str(POSE_MODEL_PATH)),
                running_mode=vision.RunningMode.IMAGE,
            )
            self._landmarker = vision.PoseLandmarker.create_from_options(opts)

    def process(self, rgb):
        if _LEGACY_API:
            res = self._pose.process(rgb)
            if not res.pose_landmarks:
                return None
            return res.pose_landmarks.landmark
        else:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            res = self._landmarker.detect(mp_image)
            if not res.pose_landmarks:
                return None
            return [_TaskLandmark(l) for l in res.pose_landmarks[0]]

    def close(self):
        if _LEGACY_API:
            self._pose.close()
        else:
            self._landmarker.close()


def detect_phase_boundaries(snapshots: list) -> list:
    """
    Velocity-based swing phase detection using wrist speed.
    Returns 6 boundaries as fractions of video duration:
    [setup_start, takeaway_start, top_start, downswing_start, impact_start, follow_start]
    Falls back to fixed percentages if the signal is too noisy.
    """
    if len(snapshots) < 10:
        return [0.0, 0.12, 0.28, 0.48, 0.68, 0.85]

    # Wrist position per snapshot (already normalized 0-1 via head_x style fields)
    xs = np.array([s["wrist_x_norm"] for s in snapshots])
    ys = np.array([s["wrist_y_norm"] for s in snapshots])
    ts = np.array([s["time_pct"] for s in snapshots])

    # Speed between consecutive samples
    dx = np.diff(xs)
    dy = np.diff(ys)
    dt = np.diff(ts)
    dt[dt == 0] = 1e-6
    speed = np.sqrt(dx**2 + dy**2) / dt

    # Smooth with a small moving average
    k = max(3, len(speed) // 20)
    kernel = np.ones(k) / k
    speed_smooth = np.convolve(speed, kernel, mode="same")

    # Impact = global max speed (clubhead/hands fastest at impact)
    impact_i = int(np.argmax(speed_smooth))
    impact_t = float(ts[impact_i])

    # Takeaway start = first time speed exceeds 15% of max, before impact
    thresh = 0.15 * speed_smooth[impact_i]
    moving = np.where(speed_smooth[:impact_i] > thresh)[0]
    takeaway_i = int(moving[0]) if len(moving) else max(1, impact_i // 4)
    takeaway_t = float(ts[takeaway_i])

    # Top = speed minimum between takeaway and impact (transition pause)
    if impact_i - takeaway_i > 4:
        mid_lo = takeaway_i + (impact_i - takeaway_i) // 3
        top_i = mid_lo + int(np.argmin(speed_smooth[mid_lo:impact_i]))
    else:
        top_i = (takeaway_i + impact_i) // 2
    top_t = float(ts[top_i])

    # Downswing starts right after top; follow-through shortly after impact
    downswing_t = top_t + (impact_t - top_t) * 0.15
    follow_t = min(0.98, impact_t + (1.0 - impact_t) * 0.25)

    bounds = [0.0, takeaway_t, top_t, downswing_t, impact_t, follow_t]
    # Sanity: must be strictly increasing and within (0,1)
    for i in range(1, 6):
        if bounds[i] <= bounds[i-1] or bounds[i] >= 1.0:
            return [0.0, 0.12, 0.28, 0.48, 0.68, 0.85]
    return [round(b, 4) for b in bounds]


def extract_pose_data(video_path: str, sample_rate: int = 8) -> dict:
    """
    Two-pass analysis:
    Pass 1 - run MediaPipe on sampled frames, collect all snapshots with wrist tracking.
    Pass 2 - detect phase boundaries from wrist velocity, then bucket snapshots into phases.
    """
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    duration = total_frames / fps
    aspect = (cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 16) / (cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 9)

    pose_detector = PoseDetector()

    snapshots = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % sample_rate == 0:
            # Downscale before pose detection - big memory/CPU savings on
            # small cloud instances, negligible accuracy cost (landmarks
            # are normalized 0-1 so downstream math is unaffected).
            h0, w0 = frame.shape[:2]
            if w0 > 960:
                scale = 960 / w0
                frame_small = cv2.resize(frame, (960, int(h0 * scale)))
            else:
                frame_small = frame
            rgb = cv2.cvtColor(frame_small, cv2.COLOR_BGR2RGB)
            lm = pose_detector.process(rgb)
            if lm:
                snapshot = extract_key_angles(lm, frame_small.shape)
                snapshot["frame"] = frame_idx
                snapshot["time_pct"] = frame_idx / max(total_frames - 1, 1)
                # Wrist tracking for phase detection (lead wrist)
                snapshot["wrist_x_norm"] = float(lm[LANDMARK.LEFT_WRIST].x)
                snapshot["wrist_y_norm"] = float(lm[LANDMARK.LEFT_WRIST].y)
                # Full skeleton keypoints (normalized 0-1) for frontend overlay
                def _pt(idx):
                    p = lm[idx]
                    return [round(float(p.x), 4), round(float(p.y), 4)] if p.visibility > 0.3 else None
                snapshot["skeleton"] = {
                    "nose": _pt(LANDMARK.NOSE),
                    "ls": _pt(LANDMARK.LEFT_SHOULDER),  "rs": _pt(LANDMARK.RIGHT_SHOULDER),
                    "le": _pt(LANDMARK.LEFT_ELBOW),     "re": _pt(LANDMARK.RIGHT_ELBOW),
                    "lw": _pt(LANDMARK.LEFT_WRIST),     "rw": _pt(LANDMARK.RIGHT_WRIST),
                    "lh": _pt(LANDMARK.LEFT_HIP),       "rh": _pt(LANDMARK.RIGHT_HIP),
                    "lk": _pt(LANDMARK.LEFT_KNEE),      "rk": _pt(LANDMARK.RIGHT_KNEE),
                    "la": _pt(LANDMARK.LEFT_ANKLE),     "ra": _pt(LANDMARK.RIGHT_ANKLE),
                }
                snapshots.append(snapshot)
        frame_idx += 1

    cap.release()
    pose_detector.close()

    # Detect real phase boundaries from wrist velocity
    bounds = detect_phase_boundaries(snapshots)
    phase_names = ["setup", "takeaway", "top", "downswing", "impact", "follow"]

    phase_data = {name: [] for name in phase_names}
    for s in snapshots:
        t = s["time_pct"]
        idx = 0
        for i in range(len(bounds)):
            if t >= bounds[i]:
                idx = i
        phase_data[phase_names[idx]].append(s)

    skeleton_track = [
        {"t": s["time_pct"], "pts": s["skeleton"]}
        for s in snapshots if "skeleton" in s
    ]
    return {
        "phases": phase_data,
        "phase_bounds": bounds,
        "duration": duration,
        "total_frames": total_frames,
        "fps": fps,
        "aspect": aspect,
        "skeleton_track": skeleton_track,
    }


def extract_key_angles(lm, shape) -> dict:
    """Compute biomechanically meaningful angles from pose landmarks."""
    h, w = shape[:2]

    def pt(idx):
        l = lm[idx]
        return np.array([l.x * w, l.y * h, l.z * w])

    def angle_3pt(a, b, c):
        """Angle at joint b between segments ba and bc."""
        ba = a - b
        bc = c - b
        cos_a = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
        return float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))

    def spine_angle(shoulder_mid, hip_mid, vertical=None):
        """Angle of spine from vertical."""
        if vertical is None:
            vertical = np.array([0, -1, 0])
        spine = shoulder_mid - hip_mid
        cos_a = np.dot(spine, vertical) / (np.linalg.norm(spine) + 1e-6)
        return float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))

    l_shoulder = pt(LANDMARK.LEFT_SHOULDER)
    r_shoulder = pt(LANDMARK.RIGHT_SHOULDER)
    l_hip      = pt(LANDMARK.LEFT_HIP)
    r_hip      = pt(LANDMARK.RIGHT_HIP)
    l_knee     = pt(LANDMARK.LEFT_KNEE)
    r_knee     = pt(LANDMARK.RIGHT_KNEE)
    l_ankle    = pt(LANDMARK.LEFT_ANKLE)
    r_ankle    = pt(LANDMARK.RIGHT_ANKLE)
    l_elbow    = pt(LANDMARK.LEFT_ELBOW)
    r_elbow    = pt(LANDMARK.RIGHT_ELBOW)
    l_wrist    = pt(LANDMARK.LEFT_WRIST)
    r_wrist    = pt(LANDMARK.RIGHT_WRIST)
    nose       = pt(LANDMARK.NOSE)

    shoulder_mid = (l_shoulder + r_shoulder) / 2
    hip_mid      = (l_hip + r_hip) / 2

    return {
        # Core posture
        "spine_angle":          spine_angle(shoulder_mid, hip_mid),
        "hip_shoulder_x_diff":  float(shoulder_mid[0] - hip_mid[0]),  # lateral sway

        # Rotation (shoulder line vs hip line angle)
        "shoulder_rotation":    float(np.degrees(np.arctan2(
            l_shoulder[1] - r_shoulder[1], l_shoulder[0] - r_shoulder[0]))),
        "hip_rotation":         float(np.degrees(np.arctan2(
            l_hip[1] - r_hip[1], l_hip[0] - r_hip[0]))),

        # Lead arm / trail arm angles
        "lead_arm_angle":       angle_3pt(l_shoulder, l_elbow, l_wrist),
        "trail_arm_angle":      angle_3pt(r_shoulder, r_elbow, r_wrist),

        # Knee flex
        "lead_knee_flex":       angle_3pt(l_hip, l_knee, l_ankle),
        "trail_knee_flex":      angle_3pt(r_hip, r_knee, r_ankle),

        # Head position relative to setup (normalized)
        "head_x_norm":          float(nose[0] / w),
        "head_y_norm":          float(nose[1] / h),

        # Hip extension (early extension detection)
        "hip_y_norm":           float(hip_mid[1] / h),

        # Landmark visibility scores
        "visibility": {
            "left_shoulder":  float(lm[LANDMARK.LEFT_SHOULDER].visibility),
            "right_shoulder": float(lm[LANDMARK.RIGHT_SHOULDER].visibility),
            "left_hip":       float(lm[LANDMARK.LEFT_HIP].visibility),
            "right_hip":      float(lm[LANDMARK.RIGHT_HIP].visibility),
        }
    }


def compute_swing_metrics(pose_data: dict, view: str) -> dict:
    """
    Aggregate pose snapshots into swing-level metrics and fault signals.
    Returns a structured summary Claude will use to generate coaching.
    """
    phases = pose_data["phases"]

    def avg(phase, key, default=None):
        frames = phases.get(phase, [])
        vals = [f[key] for f in frames if key in f]
        return float(np.mean(vals)) if vals else default

    def std(phase, key):
        frames = phases.get(phase, [])
        vals = [f[key] for f in frames if key in f]
        return float(np.std(vals)) if len(vals) > 1 else 0.0

    # ── Posture score ──────────────────────────────────────────────────────────
    setup_spine   = avg("setup",  "spine_angle", 90)
    impact_spine  = avg("impact", "spine_angle", 90)
    spine_loss    = abs(impact_spine - setup_spine) if setup_spine and impact_spine else 0
    posture_score = max(40, min(100, 100 - spine_loss * 2))

    # ── Tempo score ────────────────────────────────────────────────────────────
    # Ratio of backswing frames to downswing frames (ideal ~3:1)
    bs_frames = len(phases.get("takeaway", [])) + len(phases.get("top", []))
    ds_frames = len(phases.get("downswing", [])) + len(phases.get("impact", []))
    if ds_frames > 0:
        ratio = bs_frames / ds_frames
        tempo_score = max(40, min(100, 100 - abs(ratio - 3.0) * 15))
    else:
        tempo_score = 60

    # ── Rotation score ─────────────────────────────────────────────────────────
    top_shoulder_rot   = avg("top",    "shoulder_rotation")
    impact_hip_rot     = avg("impact", "hip_rotation")
    setup_hip_rot      = avg("setup",  "hip_rotation")
    hip_clearance      = abs(impact_hip_rot - setup_hip_rot) if (impact_hip_rot and setup_hip_rot) else 0
    rotation_score     = max(40, min(100, 50 + hip_clearance * 1.5))

    # ── Balance score ──────────────────────────────────────────────────────────
    sway_setup    = avg("setup",     "hip_shoulder_x_diff", 0)
    sway_top      = avg("top",       "hip_shoulder_x_diff", 0)
    sway_impact   = avg("impact",    "hip_shoulder_x_diff", 0)
    sway_amount   = max(abs(sway_top - sway_setup), abs(sway_impact - sway_setup)) if sway_setup else 0
    balance_score = max(40, min(100, 100 - sway_amount * 3))

    # ── Club path (inferred from wrist trajectory) ─────────────────────────────
    lead_arm_top    = avg("top",    "lead_arm_angle", 160)
    lead_arm_impact = avg("impact", "lead_arm_angle", 160)
    arm_extension   = abs(lead_arm_impact - lead_arm_top) if (lead_arm_top and lead_arm_impact) else 0
    clubpath_score  = max(40, min(100, 60 + arm_extension * 0.4))

    overall = int((posture_score + tempo_score + rotation_score + balance_score + clubpath_score) / 5)

    # ── Fault signals ─────────────────────────────────────────────────────────
    setup_head_y   = avg("setup",  "head_y_norm")
    impact_head_y  = avg("impact", "head_y_norm")
    setup_head_x   = avg("setup",  "head_x_norm")
    impact_head_x  = avg("impact", "head_x_norm")

    setup_hip_y    = avg("setup",  "hip_y_norm")
    impact_hip_y   = avg("impact", "hip_y_norm")

    faults = {
        "early_extension":    bool(impact_hip_y and setup_hip_y and (impact_hip_y - setup_hip_y) < -0.04),
        "head_drift":         bool(impact_head_x and setup_head_x and abs(impact_head_x - setup_head_x) > 0.06),
        "head_rise":          bool(impact_head_y and setup_head_y and (impact_head_y - setup_head_y) < -0.05),
        "hip_stall":          bool(hip_clearance < 15),
        "loss_of_lag":        bool(arm_extension > 30),
        "sway":               bool(sway_amount > 20),
        "spine_loss":         bool(spine_loss > 12),
    }

    return {
        "view": view,
        "scores": {
            "posture":  int(posture_score),
            "tempo":    int(tempo_score),
            "rotation": int(rotation_score),
            "balance":  int(balance_score),
            "clubPath": int(clubpath_score),
            "overall":  overall,
        },
        "fault_signals": faults,
        "raw_metrics": {
            "setup_spine_angle":   round(setup_spine or 0, 1),
            "impact_spine_angle":  round(impact_spine or 0, 1),
            "spine_angle_loss":    round(spine_loss, 1),
            "hip_clearance_deg":   round(hip_clearance, 1),
            "sway_pixels":         round(sway_amount, 1),
            "arm_extension_diff":  round(arm_extension, 1),
            "backswing_downswing_ratio": round(bs_frames / max(ds_frames, 1), 2),
        }
    }




# -- ANNOTATED FRAME RENDERING (for the report) --------------------------------

SKELETON_LINKS = [
    ("ls","rs"), ("ls","le"), ("le","lw"), ("rs","re"), ("re","rw"),
    ("ls","lh"), ("rs","rh"), ("lh","rh"),
    ("lh","lk"), ("lk","la"), ("rh","rk"), ("rk","ra"),
]

def _skeleton_at(track, t):
    """Interpolate skeleton keypoints at normalized time t."""
    if not track:
        return None
    if t <= track[0]["t"]:
        return track[0]["pts"]
    if t >= track[-1]["t"]:
        return track[-1]["pts"]
    for i in range(len(track) - 1):
        a, b = track[i], track[i+1]
        if a["t"] <= t <= b["t"]:
            f = (t - a["t"]) / max(b["t"] - a["t"], 1e-6)
            out = {}
            for k in a["pts"]:
                p, q = a["pts"].get(k), b["pts"].get(k)
                if p and q:
                    out[k] = [p[0] + (q[0]-p[0])*f, p[1] + (q[1]-p[1])*f]
                else:
                    out[k] = p or q
            return out
    return track[-1]["pts"]


def _draw_skeleton_cv(img, pts, color, thickness, dashed=False):
    if not pts:
        return
    h, w = img.shape[:2]
    def px(p):
        return (int(p[0]*w), int(p[1]*h))
    for a_k, b_k in SKELETON_LINKS:
        a, b = pts.get(a_k), pts.get(b_k)
        if not a or not b:
            continue
        p1, p2 = px(a), px(b)
        if dashed:
            dist = np.hypot(p2[0]-p1[0], p2[1]-p1[1])
            n = max(int(dist / 22), 1)
            for i in range(0, n, 2):
                t1, t2 = i/n, min((i+1)/n, 1.0)
                q1 = (int(p1[0]+(p2[0]-p1[0])*t1), int(p1[1]+(p2[1]-p1[1])*t1))
                q2 = (int(p1[0]+(p2[0]-p1[0])*t2), int(p1[1]+(p2[1]-p1[1])*t2))
                cv2.line(img, q1, q2, color, thickness)
        else:
            cv2.line(img, p1, p2, color, thickness)
    for k in ("ls","rs","le","re","lw","rw","lh","rh","lk","rk"):
        p = pts.get(k)
        if p:
            cv2.circle(img, px(p), thickness + 2 if not dashed else thickness, color, -1)
    if pts.get("nose"):
        cv2.circle(img, px(pts["nose"]), max(int(w*0.018), 10), color, thickness if not dashed else 2)


def render_report_frame(video_path: str, skeleton_track: list, phase_bounds: list, out_path: str) -> bool:
    """Render the impact frame with impact skeleton + setup ghost. Returns success."""
    try:
        cap = cv2.VideoCapture(video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        impact_t = phase_bounds[4] if phase_bounds and len(phase_bounds) >= 5 else 0.68
        setup_t  = min((phase_bounds[1] * 0.5) if phase_bounds else 0.08, 0.08)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * impact_t))
        ret, frame = cap.read()
        cap.release()
        if not ret:
            return False
        frame = cv2.addWeighted(frame, 0.78, np.zeros_like(frame), 0.22, 0)
        h, w = frame.shape[:2]
        thick = max(3, int(w * 0.004))
        _draw_skeleton_cv(frame, _skeleton_at(skeleton_track, setup_t), (255, 255, 255), max(2, thick - 2), dashed=True)
        _draw_skeleton_cv(frame, _skeleton_at(skeleton_track, impact_t), (30, 189, 124), thick)
        # Head movement arrow
        s = _skeleton_at(skeleton_track, setup_t)
        i = _skeleton_at(skeleton_track, impact_t)
        if s and i and s.get("nose") and i.get("nose"):
            p1 = (int(s["nose"][0]*w), int(s["nose"][1]*h))
            p2 = (int(i["nose"][0]*w), int(i["nose"][1]*h))
            cv2.arrowedLine(frame, p1, p2, (74, 75, 226), max(2, thick - 1), tipLength=0.25)
        # Scale to max 960px wide for the report
        if w > 960:
            scale = 960 / w
            frame = cv2.resize(frame, (960, int(h * scale)))
        cv2.imwrite(out_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return True
    except Exception:
        return False




FAULT_LIBRARY = {
    "spine_loss": {
        "title": "Losing posture through impact",
        "why": "You lose {spine_angle_loss} degrees of spine angle between setup and impact - standing up out of the shot causes thin and fat contact.",
        "severity": "high",
        "fix": {"cue": "Feel your chest stay down and rotating through the ball.",
                "why": "Maintaining spine angle keeps the club bottoming out in the same place every swing.",
                "checkpoint": "Video face-on: your head height at impact should match your setup height."},
        "drill": {"name": "Chair drill", "duration": "5 min", "trains": "Holds spine angle through impact",
                  "steps": ["Set up with your rear lightly touching a chair or wall", "Make slow half swings keeping contact through impact", "Build speed over 10 swings without losing contact"],
                  "reps": "3 sets of 10", "feel": "Like you are sitting into the wall while your chest rotates down and through"},
    },
    "sway": {
        "title": "Lateral sway instead of rotation",
        "why": "Your hips slide sideways during the swing instead of rotating in place, hurting balance and consistency.",
        "severity": "high",
        "fix": {"cue": "Feel your trail hip turn behind you in the backswing, not away from the target.",
                "why": "Rotation stores power over a stable base; a slide has to be perfectly re-timed every swing.",
                "checkpoint": "Backswing video: your trail hip should stay inside your trail foot."},
        "drill": {"name": "Wall hip drill", "duration": "5 min", "trains": "Hip rotation without lateral slide",
                  "steps": ["Stand with your trail hip a few inches from a wall", "Make backswings - your hip may touch the wall but never push into it", "Progress to full swings keeping that spacing"],
                  "reps": "15 slow swings", "feel": "Coiling into your trail side like a spring, not leaning"},
    },
    "head_drift": {
        "title": "Head drifts toward the target",
        "why": "Your head moves toward the target during the downswing, moving your strike point ahead of the ball.",
        "severity": "medium",
        "fix": {"cue": "Keep your head behind the ball until the ball is gone.",
                "why": "A stable head keeps the swing bottom consistent so contact stops varying.",
                "checkpoint": "Have someone hold a club shaft at your lead ear at address - do not touch it during the swing."},
        "drill": {"name": "Head-on-wall swings", "duration": "5 min", "trains": "A stable center of rotation",
                  "steps": ["Rest your forehead lightly on a wall in golf posture, no club", "Make slow crossing-arm swings keeping the forehead in place", "Feel the body rotate under a still head"],
                  "reps": "2 sets of 10", "feel": "Your body turns like a door on a fixed hinge"},
    },
    "head_rise": {
        "title": "Head rises through impact",
        "why": "Your head lifts before impact, pulling the club up with it - the classic cause of thin shots.",
        "severity": "medium",
        "fix": {"cue": "Stay in your posture until the ball is gone - chase the ball with your chest.",
                "why": "Keeping height through impact lets the club reach the bottom of its arc at the ball.",
                "checkpoint": "Finish drills: hold your finish and check your head only rose after impact."},
        "drill": {"name": "Eyes-on-the-coin drill", "duration": "5 min", "trains": "Keeping height through the strike",
                  "steps": ["Place a coin where the ball would be", "Make practice swings brushing the grass while keeping eyes on the coin until after 'impact'", "Add a ball once the brush point is consistent"],
                  "reps": "20 swings", "feel": "Your eyes stay down a beat longer than feels natural"},
    },
    "hip_stall": {
        "title": "Hip rotation stalls on the downswing",
        "why": "Your hips stop turning before impact ({hip_clearance_deg} degrees of clearance measured), forcing the arms to take over.",
        "severity": "high",
        "fix": {"cue": "Feel your lead hip pocket pull behind you as you start down.",
                "why": "Continuous hip rotation clears space for the arms and shallows the club path.",
                "checkpoint": "At impact your belt buckle should already face ahead of the ball."},
        "drill": {"name": "Step-through drill", "duration": "5 min", "trains": "Full rotation and weight transfer",
                  "steps": ["Narrow your stance slightly", "Swing and let the trail foot step through toward the target after impact", "Walk toward the target as you finish"],
                  "reps": "15 swings, no ball at first", "feel": "All your weight releases onto the lead side"},
    },
    "loss_of_lag": {
        "title": "Early release of wrist angle",
        "why": "The angle between your lead arm and the club releases too early, costing clubhead speed at the ball.",
        "severity": "medium",
        "fix": {"cue": "Drag the butt of the club toward the ball starting down.",
                "why": "Holding lag delivers speed at impact instead of wasting it before the ball.",
                "checkpoint": "Downswing video at hip height: the shaft should still point behind you, not at the ball."},
        "drill": {"name": "Pump drill", "duration": "8 min", "trains": "Lag retention and sequencing",
                  "steps": ["Swing to the top and pause", "Pump down slowly to hip height keeping the wrist angle, return to the top", "On the third pump swing through and hit the ball"],
                  "reps": "10 balls, 3 pumps each", "feel": "The clubhead feels late - body leads, club trails"},
    },
    "early_extension": {
        "title": "Early extension at impact",
        "why": "Your hips thrust toward the ball through impact, raising your body and causing thin shots and blocks.",
        "severity": "high",
        "fix": {"cue": "Keep your belt buckle pointed at the ball until your hands pass your trail thigh.",
                "why": "Stops the goat-hump move that raises the swing bottom mid-strike.",
                "checkpoint": "Video down-the-line: your rear should stay on the line it started on through impact."},
        "drill": {"name": "Alignment stick hip drill", "duration": "5 min", "trains": "Maintaining hip depth",
                  "steps": ["Place an alignment stick in the ground just behind your rear at address", "Make slow half swings keeping light contact through impact", "Build to full speed without losing contact"],
                  "reps": "3 sets of 10", "feel": "Sitting into the stick while the chest rotates through"},
    },
}


def build_fallback_coaching(metrics_list: list) -> dict:
    """Rule-based coaching from measured fault signals - used when the
    Claude API is unavailable so pose results are never wasted."""
    primary = metrics_list[0]
    scores = combine_scores(metrics_list)
    raw = primary["raw_metrics"]

    # Faults present in the most views, strongest first
    counts = {}
    for m in metrics_list:
        for k, v in m["fault_signals"].items():
            if v:
                counts[k] = counts.get(k, 0) + 1
    ranked = sorted(counts, key=lambda k: -counts[k])
    top = [k for k in ranked if k in FAULT_LIBRARY][:3]
    if not top:
        top = ["spine_loss"]

    faults, fixes, drills = [], [], []
    for k in top:
        lib = FAULT_LIBRARY[k]
        why = lib["why"]
        for rk, rv in raw.items():
            why = why.replace("{" + rk + "}", str(rv))
        faults.append({"title": lib["title"], "why": why, "severity": lib["severity"]})
        fixes.append(lib["fix"])
        drills.append(lib["drill"])

    strengths = [n for n, key in [("rotation", "rotation"), ("tempo", "tempo"), ("posture", "posture"), ("balance", "balance")]
                 if scores.get(key, 0) >= 75]
    strength_txt = (" Your " + strengths[0] + " is a real strength.") if strengths else ""

    summary = (f"Measured from your videos: {faults[0]['title'].lower()} is the priority fix, "
               f"with {len(top)} fault patterns detected across your camera angles.{strength_txt} "
               f"Work the drills below in order and re-test with new videos in a week.")

    plan = ("Week 1: first drill only, every session, slow reps until the checkpoint passes consistently. "
            "Week 2: keep drill 1 as a warmup, add drill 2 with short irons. "
            "Week 3: add drill 3 and progress to full swings, filming face-on to confirm the checkpoints. "
            "Re-run a SwingFix analysis to measure the improvement.")

    phase_status = {"Setup": "good", "Takeaway": "good", "Top of backswing": "good",
                    "Downswing": "warn", "Impact": "fault", "Follow-through": "good"}
    phases = [{"name": n, "status": s} for n, s in phase_status.items()]

    return {"summary": summary, "scores": scores, "faults": faults, "fixes": fixes,
            "drills": drills, "practice_plan": plan, "phases": phases}




def combine_scores(metrics_list: list) -> dict:
    """Combine scores across camera views, using the view best suited to
    measure each dimension in 2D:
      - posture / spine angle: best seen down-the-line
      - balance / sway / head: best seen face-on
      - club path: a down-the-line concept
      - rotation: down-the-line or face-on (front-facing inflates it)
      - tempo: view-independent, take the median
    Falls back gracefully when a preferred view is missing."""
    by_view = {m["view"]: m["scores"] for m in metrics_list}

    def pick(metric, preferred):
        for view in preferred:
            if view in by_view:
                return by_view[view][metric]
        return metrics_list[0]["scores"][metric]

    def median(metric):
        vals = sorted(m["scores"][metric] for m in metrics_list)
        return vals[len(vals) // 2]

    scores = {
        "posture":  pick("posture",  ["Down-the-line", "Face-on"]),
        "balance":  pick("balance",  ["Face-on", "Down-the-line"]),
        "clubPath": pick("clubPath", ["Down-the-line", "Face-on"]),
        "rotation": pick("rotation", ["Down-the-line", "Face-on"]),
        "tempo":    median("tempo"),
    }
    scores["overall"] = int(sum(scores.values()) / 5)
    return scores




def detect_view(pose_data: dict) -> tuple:
    """Classify camera angle from setup-phase skeleton geometry.
    Returns (slot, confidence): 'faceon' | 'dtl' | 'front'.
    - Wide shoulders relative to torso  -> golfer faces the camera -> faceon
    - Narrow (profile) -> side view; the left/right shoulder ordering tells
      which side faces the camera -> dtl (behind) vs front (target side).
      Side assignment assumes a right-handed golfer.
    """
    track = pose_data.get("skeleton_track") or []
    bounds = pose_data.get("phase_bounds") or [0, 0.12]
    aspect = pose_data.get("aspect", 9 / 16)
    setup = [f for f in track if f["t"] < max(bounds[1], 0.08)] or track[:5]

    ratios, mirrors = [], []
    for f in setup:
        p = f["pts"]
        ls, rs, lh, rh = p.get("ls"), p.get("rs"), p.get("lh"), p.get("rh")
        if not (ls and rs and lh and rh):
            continue
        shoulder_w = abs(ls[0] - rs[0]) * aspect
        sh_c = ((ls[0] + rs[0]) / 2 * aspect, (ls[1] + rs[1]) / 2)
        hip_c = ((lh[0] + rh[0]) / 2 * aspect, (lh[1] + rh[1]) / 2)
        torso = ((sh_c[0] - hip_c[0]) ** 2 + (sh_c[1] - hip_c[1]) ** 2) ** 0.5
        if torso < 1e-4:
            continue
        ratios.append(shoulder_w / torso)
        mirrors.append(1 if ls[0] > rs[0] else 0)

    if not ratios:
        return None, 0.0
    ratios.sort()
    r = ratios[len(ratios) // 2]
    mirror_frac = sum(mirrors) / len(mirrors)

    if r >= 0.45:
        conf = min(1.0, 0.5 + (r - 0.45))
        return "faceon", round(conf, 2)
    # Side view: which profile faces the camera decides dtl vs front
    side_conf = min(1.0, 0.5 + (0.45 - r)) * (abs(mirror_frac - 0.5) + 0.5)
    if mirror_frac >= 0.5:
        return "dtl", round(min(side_conf, 1.0), 2)
    return "front", round(min(side_conf, 1.0), 2)


def resolve_view_assignments(detected: dict) -> tuple:
    """detected: uploaded_slot -> (view, confidence, pose_data, path).
    Returns (assignments uploaded_slot -> final_slot, corrections dict)."""
    taken, assignments = {}, {}
    # Highest-confidence detections claim their slot first
    order = sorted(detected.items(), key=lambda kv: -(kv[1][1] or 0))
    for up_slot, (view, conf, _pd, _path) in order:
        want = view if (view and conf >= 0.5) else up_slot
        if want in taken.values():
            want = up_slot if up_slot not in taken.values() else None
        if want is None:
            for cand in ("faceon", "dtl", "front"):
                if cand not in taken.values():
                    want = cand
                    break
        taken[up_slot] = want
        assignments[up_slot] = want
    corrections = {u: f for u, f in assignments.items() if u != f}
    return assignments, corrections


# ── CLAUDE COACHING REPORT ─────────────────────────────────────────────────────

def build_coaching_prompt(metrics_list: list[dict]) -> str:
    views_summary = "\n".join([
        f"View: {m['view']}\n"
        f"  Scores: {m['scores']}\n"
        f"  Faults detected: {[k for k,v in m['fault_signals'].items() if v]}\n"
        f"  Raw metrics: {m['raw_metrics']}"
        for m in metrics_list
    ])

    return f"""You are SwingFix AI, an expert PGA golf coach receiving REAL biomechanical data from MediaPipe Pose analysis of a golfer's swing video.

The following measurements were extracted from the actual video frames:

{views_summary}

Based on these real measurements, generate a coaching report. The fault signals and metrics are ground truth - use them to drive your analysis. If early_extension is True, that IS a fault. If hip_clearance_deg < 20, hip rotation IS limited.

Respond ONLY with a valid JSON object matching this schema exactly:
{{
  "summary": "2-sentence assessment referencing the actual measured values",
  "scores": {{"posture":0,"tempo":0,"rotation":0,"balance":0,"clubPath":0,"overall":0}},
  "faults": [
    {{"title":"fault name","why":"explanation referencing the specific measurement","severity":"high|medium|low"}},
    {{"title":"...","why":"...","severity":"..."}},
    {{"title":"...","why":"...","severity":"..."}}
  ],
  "fixes": [
    {{"cue":"the one swing thought, in feel language","why":"what it corrects, tied to the measurement","checkpoint":"how the golfer can self-check it worked (mirror position, video check, or contact feel)"}},
    {{"cue":"...","why":"...","checkpoint":"..."}},
    {{"cue":"...","why":"...","checkpoint":"..."}}
  ],
  "drills": [
    {{"name":"drill name","duration":"X min","trains":"what it trains","steps":["step 1","step 2","step 3"],"reps":"sets and reps, e.g. 3 sets of 10 slow swings","feel":"what a correct rep feels like"}},
    {{"name":"...","duration":"...","trains":"...","steps":["..."],"reps":"...","feel":"..."}},
    {{"name":"...","duration":"...","trains":"...","steps":["..."],"reps":"...","feel":"..."}}
  ],
  "practice_plan": "3-4 sentence weekly practice progression: what to do first, when to add the next drill, and when to take it to full swings on the range",
  "phases": [
    {{"name":"Setup","status":"good|warn|fault|pending"}},
    {{"name":"Takeaway","status":"..."}},
    {{"name":"Top of backswing","status":"..."}},
    {{"name":"Downswing","status":"..."}},
    {{"name":"Impact","status":"..."}},
    {{"name":"Follow-through","status":"..."}}
  ]
}}

Use the measured fault signals and scores directly - do not fabricate. Return ONLY the JSON."""


async def call_claude(prompt: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── API ROUTES ─────────────────────────────────────────────────────────────────

class AnalysisJob(BaseModel):
    job_id: str
    status: str   # pending | processing | complete | error
    result: Optional[dict] = None
    error: Optional[str] = None
    progress: int = 0
    step: str = ""


@app.post("/api/analyze", response_model=AnalysisJob)
async def start_analysis(
    background_tasks: BackgroundTasks,
    faceon: Optional[UploadFile] = File(None),
    dtl:    Optional[UploadFile] = File(None),
    front:  Optional[UploadFile] = File(None),
    session_id: Optional[str] = Form(None),
):
    uploads = {"faceon": faceon, "dtl": dtl, "front": front}
    provided = {k: v for k, v in uploads.items() if v is not None}

    if not provided:
        raise HTTPException(status_code=400, detail="At least one video file required")

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "pending", "progress": 0, "step": "Queued", "result": None, "error": None}

    # Save uploaded files to disk
    saved_paths = {}
    for slot, upload in provided.items():
        suffix = Path(upload.filename).suffix or ".mp4"
        path = UPLOAD_DIR / f"{job_id}_{slot}{suffix}"
        content = await upload.read()
        path.write_bytes(content)
        saved_paths[slot] = str(path)

    background_tasks.add_task(run_analysis_job, job_id, saved_paths)

    return AnalysisJob(job_id=job_id, status="pending", step="Queued")


async def run_analysis_job(job_id: str, video_paths: dict, keep_files: bool = False):
    try:
        jobs[job_id]["status"] = "processing"
        save_jobs()
        metrics_list = []
        phase_bounds = None
        skeletons = {}
        report_frames = []
        slot_labels  = {"faceon": "Face-on", "dtl": "Down-the-line", "front": "Front-facing"}

        total = len(video_paths)

        # Pass 1: pose-extract every video and detect its actual camera view
        detected = {}
        for i, (slot, path) in enumerate(video_paths.items()):
            jobs[job_id]["step"]     = f"Analyzing video {i+1}/{total}..."
            jobs[job_id]["progress"] = int((i / total) * 60)
            save_jobs()
            loop = asyncio.get_event_loop()
            pose_data = await loop.run_in_executor(None, extract_pose_data, path, 8)
            view, conf = detect_view(pose_data)
            detected[slot] = (view, conf, pose_data, path)

        # Auto-correct slot assignments from the detected views
        assignments, corrections = resolve_view_assignments(detected)
        if corrections:
            jobs[job_id]["step"] = "Auto-corrected video labels: " + ", ".join(
                f"{slot_labels[u]} -> {slot_labels[f]}" for u, f in corrections.items())
            save_jobs()

        # Pass 2: score and render everything under the corrected labels
        for up_slot, (view, conf, pose_data, path) in detected.items():
            slot = assignments[up_slot]
            metrics = compute_swing_metrics(pose_data, slot_labels[slot])
            metrics_list.append(metrics)

            # Phase boundaries from the face-on video when available
            if slot == "faceon" or phase_bounds is None:
                phase_bounds = pose_data.get("phase_bounds")
            skeletons[slot] = pose_data.get("skeleton_track", [])

            frame_path = REPORTS_DIR / f"{job_id}_{slot}.jpg"
            if render_report_frame(path, skeletons[slot], pose_data.get("phase_bounds"), str(frame_path)):
                report_frames.append(slot)

            if not keep_files:
                Path(path).unlink(missing_ok=True)

        jobs[job_id]["step"]     = "Generating coaching report..."
        jobs[job_id]["progress"] = 80
        save_jobs()

        coaching = None
        if ANTHROPIC_API_KEY:
            try:
                prompt = build_coaching_prompt(metrics_list)
                coaching = await call_claude(prompt)
            except Exception as claude_err:
                jobs[job_id]["step"] = f"AI coaching unavailable ({type(claude_err).__name__}) - using measured analysis"
                save_jobs()
        if coaching is None:
            coaching = build_fallback_coaching(metrics_list)
            coaching["_source"] = "measured"
        else:
            coaching["_source"] = "ai"

        if metrics_list:
            coaching["scores"] = combine_scores(metrics_list)

        jobs[job_id]["status"]   = "complete"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["step"]     = "Done"
        jobs[job_id]["result"]   = {
            "coaching": coaching,
            "phase_bounds": phase_bounds,
            "skeletons": skeletons,
            "report_frames": report_frames,
            "view_corrections": corrections,
            "metrics":  [{"view": m["view"], "fault_signals": m["fault_signals"], "raw": m["raw_metrics"]} for m in metrics_list],
        }
        save_jobs()

    except Exception as e:
        import traceback
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = f"{type(e).__name__}: {e} | " + traceback.format_exc()[-500:]
        jobs[job_id]["step"]   = "Error"
        save_jobs()


@app.get("/api/job/{job_id}", response_model=AnalysisJob)
async def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    j = jobs[job_id]
    return AnalysisJob(
        job_id=job_id,
        status=j["status"],
        result=j.get("result"),
        error=j.get("error"),
        progress=j.get("progress", 0),
        step=j.get("step", ""),
    )




@app.get("/api/job/{job_id}/frame/{slot}")
async def job_frame(job_id: str, slot: str):
    path = REPORTS_DIR / f"{job_id}_{slot}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/api/job/{job_id}/report")
async def job_report(job_id: str):
    if job_id not in jobs or jobs[job_id].get("status") != "complete":
        raise HTTPException(status_code=404, detail="Report not ready")
    result = jobs[job_id]["result"]
    c = result["coaching"]
    slot_labels = {"faceon": "Face-on", "dtl": "Down-the-line", "front": "Front-facing"}

    import base64
    frame_html = ""
    for slot in result.get("report_frames", []):
        p = REPORTS_DIR / f"{job_id}_{slot}.jpg"
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            frame_html += (
                f'<div style="margin-bottom:20px;"><div style="font-size:12px;color:#5a6e42;'
                f'text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;">'
                f'{slot_labels.get(slot, slot)} - impact vs setup</div>'
                f'<img src="data:image/jpeg;base64,{b64}" style="width:100%;border-radius:10px;"/></div>'
            )

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    scores = c["scores"]
    score_rows = "".join(
        f'<tr><td style="padding:6px 0;color:#555;">{name}</td>'
        f'<td style="text-align:right;font-weight:600;">{scores.get(key, "-")}</td></tr>'
        for name, key in [("Posture","posture"),("Tempo","tempo"),("Rotation","rotation"),
                          ("Balance","balance"),("Club path","clubPath")]
    )
    fault_html = "".join(
        f'<div style="border-left:4px solid {"#E24B4A" if f.get("severity")=="high" else "#E8B84B"};'
        f'padding:8px 12px;margin-bottom:10px;background:#f8f8f6;">'
        f'<strong>{esc(f["title"])}</strong><br>'
        f'<span style="color:#555;font-size:13px;">{esc(f["why"])}</span></div>'
        for f in c["faults"]
    )
    def fix_item(x):
        if isinstance(x, dict):
            return (f'<li style="margin-bottom:12px;"><strong>{esc(x.get("cue",""))}</strong><br>'
                    f'<span style="color:#555;font-size:13px;">{esc(x.get("why",""))}</span><br>'
                    f'<span style="color:#5a9614;font-size:13px;">Check: {esc(x.get("checkpoint",""))}</span></li>')
        return f'<li style="margin-bottom:6px;">{esc(x)}</li>'
    fix_html = "".join(fix_item(x) for x in c["fixes"])

    def drill_item(d):
        steps = "".join(f'<li style="font-size:13px;color:#444;">{esc(s)}</li>' for s in d.get("steps", []))
        extra = ""
        if steps:
            extra += f'<ol style="margin:6px 0 4px 18px;padding:0;">{steps}</ol>'
        if d.get("reps"):
            extra += f'<div style="font-size:13px;color:#555;">Reps: {esc(d["reps"])}</div>'
        if d.get("feel"):
            extra += f'<div style="font-size:13px;color:#5a9614;">Feel: {esc(d["feel"])}</div>'
        return (f'<li style="margin-bottom:14px;"><strong>{esc(d["name"])}</strong> '
                f'({esc(d.get("duration",""))}) - {esc(d.get("trains",""))}{extra}</li>')
    drill_html = "".join(drill_item(d) for d in c["drills"])
    plan_html = f'<h2>Weekly practice plan</h2><p style="line-height:1.6;">{esc(c["practice_plan"])}</p>' if c.get("practice_plan") else ""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SwingFix AI Report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; max-width: 760px;
         margin: 0 auto; padding: 32px 24px; color: #1a1a1a; }}
  h1 {{ font-size: 26px; margin-bottom: 4px; }}
  h1 .g {{ color: #5a9614; }}
  h2 {{ font-size: 17px; margin: 26px 0 10px; border-bottom: 2px solid #e5e5e0; padding-bottom: 6px; }}
  .big {{ font-size: 52px; font-weight: 800; color: #5a9614; }}
  @media print {{ body {{ padding: 0; }} }}
</style></head><body>
<h1>Swing<span class="g">Fix</span> AI - Swing Analysis Report</h1>
<p style="color:#888;font-size:13px;">Generated from MediaPipe pose analysis of your uploaded swing videos</p>

<h2>Overall score</h2>
<div class="big">{scores.get("overall","-")}<span style="font-size:20px;color:#888;font-weight:400;"> /100</span></div>
<table style="width:280px;font-size:14px;margin-top:8px;">{score_rows}</table>

<h2>Assessment</h2>
<p style="line-height:1.6;">{esc(c["summary"])}</p>

<h2>Your swing - measured</h2>
{frame_html if frame_html else '<p style="color:#888;">No annotated frames available.</p>'}

<h2>Faults detected</h2>
{fault_html}

<h2>How to fix it</h2>
<ul>{fix_html}</ul>

<h2>Recommended drills</h2>
<ol>{drill_html}</ol>

{plan_html}

<p style="margin-top:36px;color:#aaa;font-size:11px;">SwingFix AI - scores computed from detected joint positions.
Print this page or save as PDF from your browser.</p>
</body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


@app.get("/health")
async def health():
    return {"status": "ok", "mediapipe": True, "anthropic": bool(ANTHROPIC_API_KEY)}
