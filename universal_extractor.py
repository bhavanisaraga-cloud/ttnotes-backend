import re
import os
import io
import json
import subprocess
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, Tuple

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_BIN = "ffmpeg"

LANG_BCP47_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "or": "or-IN",
    "ta": "ta-IN",
    "kn": "kn-IN",
    "te": "te-IN",
    "auto": "hi-IN"
}

def detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "drive.google.com" in url_lower or "docs.google.com" in url_lower:
        return "Google Drive Course"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "YouTube"
    elif "instagram.com" in url_lower:
        return "Instagram"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "Facebook"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "Twitter/X"
    elif "tiktok.com" in url_lower:
        return "TikTok"
    elif "linkedin.com" in url_lower:
        return "LinkedIn"
    else:
        return "Web Video"

def extract_drive_file_id(url: str) -> Optional[str]:
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]{10,})',
        r'/d/([a-zA-Z0-9_-]{10,})',
        r'[?&]id=([a-zA-Z0-9_-]{10,})',
        r'/folders/([a-zA-Z0-9_-]{10,})'
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None

def transcribe_media_bytes_in_ram(media_bytes: bytes, source_lang: str = "en-IN") -> str:
    """
    100% RAM-ONLY: Pipes raw video/audio bytes into ffmpeg via stdin/stdout,
    converts to 16kHz mono WAV in memory (0 disk files), and transcribes speech.
    """
    if not media_bytes or not sr:
        return ""
    try:
        cmd = [
            FFMPEG_BIN,
            "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-t", "45",
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            "pipe:1"
        ]
        proc = subprocess.run(
            cmd,
            input=media_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25
        )
        wav_bytes = proc.stdout
        if not wav_bytes or len(wav_bytes) < 1000:
            return ""

        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = recognizer.record(source, duration=40)

        short_code = source_lang.split("-")[0].lower() if source_lang else "en"
        bcp47 = LANG_BCP47_MAP.get(short_code, source_lang if "-" in source_lang else "en-IN")

        try:
            text = recognizer.recognize_google(audio_data, language=bcp47)
            if text and text.strip():
                return text.strip()
        except Exception:
            # Fallback to English/Hindi auto-try if primary language didn't match
            for fallback_lang in ["en-IN", "hi-IN"]:
                if fallback_lang != bcp47:
                    try:
                        text = recognizer.recognize_google(audio_data, language=fallback_lang)
                        if text and text.strip():
                            return text.strip()
                    except Exception:
                        pass
    except Exception:
        pass
    return ""

def transcribe_stream_url_in_ram(stream_url: str, source_lang: str = "en-IN", headers: Optional[Dict[str, str]] = None) -> str:
    """
    100% RAM-ONLY: Streams first 45s from a remote media URL directly into ffmpeg stdout WAV pipe
    and transcribes the speech in RAM without creating any file on disk.
    """
    if not stream_url or not sr:
        return ""
    try:
        cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error"]
        if headers:
            hdr_str = "".join([f"{k}: {v}\r\n" for k, v in headers.items()])
            cmd.extend(["-headers", hdr_str])
        cmd.extend([
            "-i", stream_url,
            "-t", "45",
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            "pipe:1"
        ])
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=25
        )
        wav_bytes = proc.stdout
        if not wav_bytes or len(wav_bytes) < 1000:
            return ""

        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio_data = recognizer.record(source, duration=40)

        short_code = source_lang.split("-")[0].lower() if source_lang else "en"
        bcp47 = LANG_BCP47_MAP.get(short_code, source_lang if "-" in source_lang else "en-IN")

        try:
            text = recognizer.recognize_google(audio_data, language=bcp47)
            if text and text.strip():
                return text.strip()
        except Exception:
            for fallback_lang in ["en-IN", "hi-IN"]:
                if fallback_lang != bcp47:
                    try:
                        text = recognizer.recognize_google(audio_data, language=fallback_lang)
                        if text and text.strip():
                            return text.strip()
                    except Exception:
                        pass
    except Exception:
        pass
    return ""

def extract_google_drive_info(url: str, source_lang: str = "en-IN") -> Optional[Dict[str, str]]:
    """
    Extracts Google Drive File ID, title, embed preview URL, AND streams the video's
    audio in RAM to transcribe actual spoken course lecture words (0% disk storage).
    """
    file_id = extract_drive_file_id(url)
    embed_url = f"https://drive.google.com/file/d/{file_id}/preview" if file_id else url
    title = f"Google Drive Course Video ({file_id[:8]})" if file_id else "Google Drive Course Video"
    desc = ""
    spoken_transcript = ""

    # 1. Try yt-dlp in-memory stream extraction for Google Drive first
    if yt_dlp:
        try:
            ydl_opts = {
                'skip_download': True,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    title = info.get("title") or title
                    stream_url = info.get("url")
                    http_headers = info.get("http_headers") or {}
                    if not stream_url and info.get("formats"):
                        for f in info["formats"]:
                            if f.get("acodec") != "none" and f.get("url"):
                                stream_url = f["url"]
                                http_headers = f.get("http_headers") or http_headers
                                break
                    if stream_url:
                        spoken_transcript = transcribe_stream_url_in_ram(stream_url, source_lang, http_headers)
        except Exception:
            pass

    # 2. If yt-dlp didn't get the stream (e.g. direct shared Drive file), stream first 2MB from uc?export=download in RAM
    if not spoken_transcript and file_id:
        try:
            dl_url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
            req = urllib.request.Request(dl_url, headers={
                "User-Agent": "Mozilla/5.0",
                "Range": "bytes=0-3145728"
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if "video" in ctype or "audio" in ctype or "octet-stream" in ctype:
                    media_chunk = resp.read(3145728)
                    spoken_transcript = transcribe_media_bytes_in_ram(media_chunk, source_lang)
        except Exception:
            pass

    # 3. Also check page title/meta if needed
    if not spoken_transcript:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                t_match = re.search(r'<title>([^<]+)</title>', html)
                if t_match:
                    clean_t = t_match.group(1).replace(" - Google Drive", "").strip()
                    if clean_t and "Sign in" not in clean_t:
                        title = clean_t
                d_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
                if d_match:
                    desc = d_match.group(1)
        except Exception:
            pass

    return {
        "file_id": file_id or "",
        "title": title,
        "embed_url": embed_url,
        "transcript": spoken_transcript,
        "description": spoken_transcript or desc or f"Welcome to this Google Drive course video ({title}). The lecture audio is ready for live dubbing."
    }

def extract_youtube_transcript_api(url: str) -> Optional[Tuple[str, str]]:
    """Instant subtitle extraction for YouTube (0 audio download, ~200ms)."""
    regExp = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([^"&?\/\s]{11})'
    match = re.search(regExp, url)
    if not match:
        return None
    video_id = match.group(1)

    try:
        list_url = f"https://www.youtube.com/api/timedtext?type=list&v={video_id}"
        req = urllib.request.Request(list_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            if "<track" in data:
                lang_match = re.search(r'lang_code="([^"]+)"', data)
                lang = lang_match.group(1) if lang_match else "en"
                sub_url = f"https://www.youtube.com/api/timedtext?v={video_id}&lang={lang}"
                req_sub = urllib.request.Request(sub_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_sub, timeout=5) as resp_sub:
                    sub_xml = resp_sub.read().decode("utf-8")
                    lines = re.findall(r'<text[^>]*>([^<]+)<\/text>', sub_xml)
                    clean_text = " ".join([urllib.parse.unquote(l).replace("&#39;", "'").replace("&amp;", "&") for l in lines])
                    if clean_text:
                        return f"YouTube Video ({video_id})", clean_text
    except Exception:
        pass
    return None

def extract_universal_media_info(url: str, source_lang: str = "en-IN") -> Dict[str, Any]:
    """
    Extracts media metadata and transcribes audio stream in RAM for ANY platform.
    Zero-Disk policy: Media files are NEVER downloaded to local storage.
    """
    if not yt_dlp:
        raise RuntimeError("yt-dlp is not installed.")

    ydl_opts = {
        'skip_download': True,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    platform = detect_platform(url)
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get('title') or f"{platform} Video"
        duration = info.get('duration') or 0
        uploader = info.get('uploader') or info.get('channel') or "Unknown Creator"
        description = info.get('description') or ""

        audio_stream_url = None
        http_headers = info.get('http_headers') or {}
        formats = info.get('formats', [])
        for f in formats:
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none' and f.get('url'):
                audio_stream_url = f.get('url')
                http_headers = f.get('http_headers') or http_headers
                break

        if not audio_stream_url:
            audio_stream_url = info.get('url')

        spoken_text = ""
        if audio_stream_url:
            spoken_text = transcribe_stream_url_in_ram(audio_stream_url, source_lang, http_headers)

        return {
            "platform": platform,
            "title": title,
            "duration": duration,
            "uploader": uploader,
            "description": spoken_text or description[:500],
            "spoken_transcript": spoken_text,
            "audio_stream_url": audio_stream_url,
            "subtitles": info.get('subtitles') or info.get('automatic_captions') or {}
        }
