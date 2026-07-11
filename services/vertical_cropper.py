"""
ClipForge AI — Vertical Cropper
Takes horizontal clips and converts to 9:16 vertical using a
single FFmpeg pass with face-aware centre crop.
"""

import cv2
import os
import sys
import subprocess
import shutil
import numpy as np


# ── Output dimensions (9:16 vertical) ─────────────────────────────────────────
OUTPUT_WIDTH  = 1080
OUTPUT_HEIGHT = 1920
ASPECT_RATIO  = OUTPUT_WIDTH / OUTPUT_HEIGHT  # 0.5625

# ── Face detection config ──────────────────────────────────────────────────────
SAMPLE_FRAMES = 8   # frames sampled per clip

# MediaPipe Tasks API model path
FACE_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "blaze_face_short_range.tflite"
)


# ──────────────────────────────────────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_video_dimensions(video_path: str) -> tuple:
    """Return (width, height) of the first video stream via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        video_path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def _get_video_duration(video_path: str) -> float:
    """Return clip duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def sample_frames(video_path: str, num_frames: int = SAMPLE_FRAMES) -> list:
    """Extract evenly spaced frames (skip first/last 10%) via OpenCV."""
    cap = cv2.VideoCapture(video_path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames == 0:
        cap.release()
        return []

    start   = int(total_frames * 0.1)
    end     = int(total_frames * 0.9)
    indices = np.linspace(start, end, num_frames, dtype=int)

    frames = []
    for idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if ret:
            frames.append(frame)
    cap.release()
    return frames


# ──────────────────────────────────────────────────────────────────────────────
# Face detection
# ──────────────────────────────────────────────────────────────────────────────

def detect_faces(frames: list) -> list:
    """
    Run MediaPipe face detection on a list of BGR frames.
    Returns a flat list of face x-centre pixel positions.
    """
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    base_options = mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH)
    options = vision.FaceDetectorOptions(
        base_options=base_options, min_detection_confidence=0.5
    )
    detector = vision.FaceDetector.create_from_options(options)

    positions = []
    for frame in frames:
        rgb      = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result   = detector.detect(mp_image)
        for det in result.detections:
            bbox = det.bounding_box
            positions.append(bbox.origin_x + bbox.width // 2)

    detector.close()
    return positions


# ──────────────────────────────────────────────────────────────────────────────
# Crop-position calculation
# ──────────────────────────────────────────────────────────────────────────────

def calculate_crop_x(video_width: int, video_height: int, face_positions: list) -> tuple:
    """
    Return (crop_x, crop_width) for a face-centred or centre crop.

    crop_width: the slice of the original frame that, scaled to OUTPUT_WIDTH,
                fills the interior panel of the 9:16 canvas.
    """
    crop_width = int(video_height * ASPECT_RATIO)
    crop_width = min(crop_width, video_width)

    if face_positions:
        avg_face_x = int(np.mean(face_positions))
        crop_x     = avg_face_x - crop_width // 2
        crop_x     = max(0, min(crop_x, video_width - crop_width))
        print(f"  🎯 Face — avg x: {avg_face_x}px, crop_x: {crop_x}px")
    else:
        crop_x = (video_width - crop_width) // 2
        print(f"  📐 No face — centre crop, crop_x: {crop_x}px")

    return crop_x, crop_width


# ──────────────────────────────────────────────────────────────────────────────
# Main crop function
# ──────────────────────────────────────────────────────────────────────────────

def crop_to_vertical(input_path: str, output_path: str, use_blur_bg: bool = False) -> bool:
    """Crop a horizontal clip to 9:16 vertical in a single FFmpeg pass."""
    vid_w, vid_h = get_video_dimensions(input_path)
    print(f"  Source: {vid_w}x{vid_h}")

    if vid_h >= vid_w:
        print("  ⏭ Already vertical — copying as-is")
        shutil.copy2(input_path, output_path)
        return True

    frames = sample_frames(input_path)
    print(f"  Sampled {len(frames)} frames")

    face_positions = detect_faces(frames)
    print(f"  Face detections: {len(face_positions)}")

    crop_x, crop_width = calculate_crop_x(vid_w, vid_h, face_positions)

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", (
            f"crop={crop_width}:{vid_h}:{crop_x}:0,"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
        ),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ]

    print(f"  Crop: {crop_width}x{vid_h} at x={crop_x} → {OUTPUT_WIDTH}x{OUTPUT_HEIGHT}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        if result.returncode != 0:
            print(f"  ✗ FFmpeg error: {result.stderr[-300:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print("  ✗ FFmpeg timed out")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Batch entry point
# ──────────────────────────────────────────────────────────────────────────────

def crop_all_clips(input_dir: str, output_dir: str = None, video_id: str = None) -> list:
    """
    Crop all raw clips in input_dir to vertical.
    video_id: if given, only process files starting with this prefix.
    """
    if output_dir is None:
        output_dir = input_dir

    clips = [
        f for f in os.listdir(input_dir)
        if f.endswith(".mp4")
        and "_vertical"  not in f
        and "_captioned" not in f
        and (video_id is None or f.startswith(video_id))
    ]

    if not clips:
        print("✗ No clips found to crop")
        return []

    print(f"✓ Found {len(clips)} clips to crop\n")

    results = []
    for i, clip in enumerate(clips, 1):
        input_path  = os.path.join(input_dir, clip).replace("\\", "/")
        output_name = clip.replace(".mp4", "_vertical.mp4")
        output_path = os.path.join(output_dir, output_name).replace("\\", "/")

        print(f"🎬 [{i}/{len(clips)}] {clip}")
        success = crop_to_vertical(input_path, output_path)

        if success:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"  ✓ Saved: {output_path} ({size_mb:.1f} MB)\n")
            results.append(output_path)
        else:
            print(f"  ✗ Failed: {clip}\n")

    print("=" * 60)
    print(f"✓ Cropped {len(results)}/{len(clips)} clips")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python services/vertical_cropper.py <clips_directory> [video_id]")
        print("Example: python services/vertical_cropper.py storage/outputs")
        print("Example (scoped): python services/vertical_cropper.py storage/outputs -OetXsp7xdI")
        sys.exit(1)

    input_dir = sys.argv[1]
    video_id  = sys.argv[2] if len(sys.argv) > 2 else None

    if not os.path.isdir(input_dir):
        print(f"✗ Directory not found: {input_dir}")
        sys.exit(1)

    results = crop_all_clips(input_dir, video_id=video_id)
    print(f"\n{'🎉 Done!' if results else '✗ Nothing produced.'}")
    if results:
        print(f"{len(results)} vertical clips ready.")
