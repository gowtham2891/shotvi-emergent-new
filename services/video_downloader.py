"""
ClipForge AI — Video Downloader Service
Downloads YouTube videos (yt-dlp) or handles MP4 uploads.
Extracts audio as 16kHz WAV for Whisper transcription.
"""

import os
import subprocess
import shutil
import yt_dlp
from pathlib import Path


# Base directories
UPLOAD_DIR = Path("storage/uploads")
OUTPUT_DIR = Path("storage/outputs")


def ensure_dirs():
    """Make sure storage directories exist."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def download_youtube(url: str) -> dict:
    """
    Download a YouTube video at 720p max quality.
    
    Args:
        url: YouTube video URL
        
    Returns:
        dict with 'video_path', 'audio_path', 'title', 'duration'
    """
    ensure_dirs()
    
    # yt-dlp options: 720p max, merge to mp4
    # Check if a cookies.txt file exists (export manually via browser extension if needed)
    cookies_file = Path("cookies.txt")

    ydl_opts = {
        'format': 'bestvideo[height<=720][vcodec^=avc]+bestaudio/best[height<=720]',
        'merge_output_format': 'mp4',
        'outtmpl': str(UPLOAD_DIR / '%(id)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'js_runtimes': {'node': {}},
        'remote_components': {'ejs': 'github'},
    }

    # Only add cookies if the file exists — avoids the Chrome lock error
    if cookies_file.exists():
        ydl_opts['cookiefile'] = str(cookies_file)
    
    # Download video
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info['id']
        title = info.get('title', 'Untitled')
        duration = info.get('duration', 0)
        video_path = UPLOAD_DIR / f"{video_id}.mp4"
    
    # Extract audio as 16kHz WAV for Whisper
    audio_path = UPLOAD_DIR / f"{video_id}_audio.wav"
    extract_audio(str(video_path), str(audio_path))
    
    return {
        'video_path': str(video_path),
        'audio_path': str(audio_path),
        'title': title,
        'duration': duration,
        'video_id': video_id,
    }


def handle_upload(uploaded_file_path: str, filename: str = "uploaded_video") -> dict:
    """
    Handle a directly uploaded MP4 file.
    Copies it to storage/uploads and extracts audio.
    
    Args:
        uploaded_file_path: path to the uploaded MP4 file
        filename: name to save as (without extension)
        
    Returns:
        dict with 'video_path', 'audio_path', 'title', 'duration'
    """
    ensure_dirs()
    
    # Copy to uploads directory
    video_path = UPLOAD_DIR / f"{filename}.mp4"
    if str(uploaded_file_path) != str(video_path):
        shutil.copy2(uploaded_file_path, video_path)
    
    # Get video duration using ffprobe
    duration = get_video_duration(str(video_path))
    
    # Extract audio
    audio_path = UPLOAD_DIR / f"{filename}_audio.wav"
    extract_audio(str(video_path), str(audio_path))
    
    return {
        'video_path': str(video_path),
        'audio_path': str(audio_path),
        'title': filename,
        'duration': duration,
        'video_id': filename,
    }


def extract_audio(video_path: str, audio_path: str):
    """
    Extract audio from video as 16kHz mono WAV (Whisper format).
    Uses FFmpeg.
    """
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-vn',                    # no video
        '-acodec', 'pcm_s16le',  # 16-bit PCM
        '-ar', '16000',           # 16kHz sample rate
        '-ac', '1',               # mono
        '-y',                     # overwrite if exists
        audio_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed:\n{result.stderr}")
    
    print(f"Audio extracted: {audio_path}")


def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        video_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        import json
        data = json.loads(result.stdout)
        return float(data.get('format', {}).get('duration', 0))
    
    return 0.0


# --- Quick test ---
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python video_downloader.py <youtube_url>")
        print("Example: python video_downloader.py https://www.youtube.com/watch?v=XXXXX")
        sys.exit(1)
    
    url = sys.argv[1]
    print(f"\nDownloading: {url}")
    print("-" * 50)
    
    result = download_youtube(url)
    
    print(f"\nDone!")
    print(f"Title:      {result['title']}")
    print(f"Duration:   {result['duration']}s")
    print(f"Video:      {result['video_path']}")
    print(f"Audio:      {result['audio_path']}")