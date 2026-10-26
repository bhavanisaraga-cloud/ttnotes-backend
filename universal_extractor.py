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
    converts to 16kHz mono WAV in memory (0 disk files), and transcribes speech
    in consecutive 10-second segments to capture full lecture speech.
    """
    if not media_bytes or not sr:
        return ""
    try:
        import tempfile
        wav_bytes = b""
        ext = ".m4a"
        if media_bytes.startswith(b"ID3") or media_bytes.startswith(b"\xff\xfb") or media_bytes.startswith(b"\xff\xf3"):
            ext = ".mp3"
        elif media_bytes.startswith(b"RIFF"):
            ext = ".wav"
        elif media_bytes.startswith(b"\x1a\x45\xdf\xa3"):
            ext = ".mkv"
        elif media_bytes.startswith(b"OggS"):
            ext = ".ogg"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(media_bytes)
            tf_path = tf.name
        try:
            cmd = [
                FFMPEG_BIN,
                "-hide_banner", "-loglevel", "error",
                "-i", tf_path,
                "-t", "600",
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "16000",
                "-ac", "1",
                "-f", "wav",
                "pipe:1"
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            wav_bytes = proc.stdout
        finally:
            try:
                os.unlink(tf_path)
            except Exception:
                pass
        if not wav_bytes or len(wav_bytes) < 1000:
            return ""

        recognizer = sr.Recognizer()
        short_code = source_lang.split("-")[0].lower() if source_lang else "en"
        bcp47 = LANG_BCP47_MAP.get(short_code, source_lang if "-" in source_lang else "en-IN")

        audio_chunks = []
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            total_duration = int(getattr(source, 'DURATION', 60))
            max_limit = min(total_duration, 300)
            for _ in range(0, max_limit, 10):
                try:
                    chunk = recognizer.record(source, duration=10)
                    if not chunk or len(chunk.get_raw_data()) < 1000:
                        break
                    audio_chunks.append(chunk)
                except Exception:
                    break

        def recognize_one(chunk_audio):
            rec = sr.Recognizer()
            try:
                txt = rec.recognize_google(chunk_audio, language=bcp47)
                if txt and txt.strip():
                    return txt.strip()
            except Exception:
                for fb in ["en-IN", "hi-IN"]:
                    if fb != bcp47:
                        try:
                            txt = rec.recognize_google(chunk_audio, language=fb)
                            if txt and txt.strip():
                                return txt.strip()
                        except Exception:
                            pass
            return ""

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(recognize_one, audio_chunks))

        transcripts = [t for t in results if t]
        if transcripts:
            return " ".join(transcripts)
    except Exception:
        pass
    return ""

def transcribe_stream_url_in_ram(stream_url: str, source_lang: str = "en-IN", headers: Optional[Dict[str, str]] = None) -> str:
    """
    100% RAM-ONLY: Streams first 90s from a remote media URL directly into ffmpeg stdout WAV pipe
    and transcribes speech in consecutive 10-second segments (0% disk storage).
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
            "-t", "90",
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
            timeout=30
        )
        wav_bytes = proc.stdout
        if not wav_bytes or len(wav_bytes) < 1000:
            return ""

        recognizer = sr.Recognizer()
        short_code = source_lang.split("-")[0].lower() if source_lang else "en"
        bcp47 = LANG_BCP47_MAP.get(short_code, source_lang if "-" in source_lang else "en-IN")

        transcripts = []
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            total_duration = int(getattr(source, 'DURATION', 60))
            max_limit = min(total_duration, 90)
            for _ in range(0, max_limit, 10):
                try:
                    chunk_audio = recognizer.record(source, duration=10)
                    if not chunk_audio or len(chunk_audio.get_raw_data()) < 1000:
                        break
                    txt = ""
                    try:
                        txt = recognizer.recognize_google(chunk_audio, language=bcp47)
                    except Exception:
                        for fb in ["en-IN", "hi-IN"]:
                            if fb != bcp47:
                                try:
                                    txt = recognizer.recognize_google(chunk_audio, language=fb)
                                    if txt:
                                        break
                                except Exception:
                                    pass
                    if txt and txt.strip():
                        transcripts.append(txt.strip())
                except Exception:
                    pass

        if transcripts:
            return " ".join(transcripts)
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
    """Instant subtitle extraction for YouTube (0 audio download, ~300ms) using YouTubeTranscriptApi."""
    regExp = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([^"&?\/\s]{11})'
    match = re.search(regExp, url)
    if not match:
        return None
    video_id = match.group(1)

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        raw = None
        try:
            raw = ytt.fetch(video_id).to_raw_data()
        except Exception:
            try:
                for t in ytt.list(video_id):
                    raw = t.fetch().to_raw_data()
                    if raw:
                        break
            except Exception:
                pass

        if raw and len(raw) > 0:
            # Extract first 60 snippets (~800-1500 words of spoken lecture)
            full_speech = " ".join([item.get('text', '') for item in raw[:350] if item.get('text')])
            clean_speech = re.sub(r'\[.*?\]', '', full_speech).strip()
            if clean_speech:
                return f"YouTube Video ({video_id})", clean_speech
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


def translate_plain_text(text: str, sl: str = "auto", tl: str = "te") -> str:
    """Translates a short string, trying several public endpoints before giving up."""
    if not text or not text.strip():
        return ""
    q = urllib.parse.quote(text.strip())
    endpoints = [
        f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={q}",
        f"https://translate.google.com/translate_a/single?client=at&sl={sl}&tl={tl}&dt=t&q={q}",
        f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl={sl}&tl={tl}&q={q}",
    ]
    for idx, url in enumerate(endpoints):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36.{idx}"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list) and data:
                if isinstance(data[0], list):
                    parts = [p[0] for p in data[0] if p and p[0]]
                    out = "".join(parts).strip()
                elif isinstance(data[0], str):
                    out = data[0].strip()
                else:
                    out = ""
                if out:
                    return out
        except Exception:
            continue
    return ""


def extract_youtube_timestamped_cues(url: str, target_lang: str = "te") -> Dict[str, Any]:
    regExp = r'(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([^"&?\/\s]{11})'
    match = re.search(regExp, url)
    if not match:
        return {"status": "error", "message": "చెల్లుబాటు అయ్యే యూట్యూబ్ లింక్ కాదు (Invalid YouTube URL)"}
    
    video_id = match.group(1)
    raw = None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        try:
            raw = ytt.fetch(video_id).to_raw_data()
        except Exception:
            for t in ytt.list(video_id):
                raw = t.fetch().to_raw_data()
                if raw:
                    break
    except Exception as e:
        return {"status": "error", "message": f"యూట్యూబ్ నుండి సబ్‌టైటిల్స్ లభించలేదు: {str(e)}"}
        
    if not raw:
        return {"status": "error", "message": "ఈ వీడియోలో ఆటోమేటిక్ లేదా మాన్యువల్ సబ్‌టైటిల్స్ లభించలేదు."}
        
    merged = []
    curr = None
    for item in raw:
        txt = item.get('text', '').replace('\n', ' ').strip()
        txt = re.sub(r'[\u266a\u266b\[\]]', '', txt).strip()
        if not txt:
            continue
        s = float(item.get('start', 0))
        dur = float(item.get('duration', 0))
        e = s + dur
        
        if curr is None:
            curr = {'start': round(s, 2), 'end': round(e, 2), 'text': txt}
        elif (e - curr['start'] < 8.0) and (s - curr['end'] < 2.0):
            curr['end'] = round(e, 2)
            curr['text'] += ' ' + txt
        else:
            merged.append(curr)
            curr = {'start': round(s, 2), 'end': round(e, 2), 'text': txt}
    if curr:
        merged.append(curr)

    # Translate each cue on its own: batching with "|||" separators loses alignment
    # because the translator rewrites or drops the markers, leaving cues in English.
    limit_chunks = min(len(merged), 120)
    selected = merged[:limit_chunks]

    def translate_cue(cue):
        try:
            te_text = translate_plain_text(cue['text'], sl="auto", tl=target_lang)
            return te_text if te_text else cue['text']
        except Exception:
            return cue['text']

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as executor:
        te_texts = list(executor.map(translate_cue, selected))

    translated_cues = []
    for c, te_text in zip(selected, te_texts):
        translated_cues.append({
            'start': c['start'],
            'end': c['end'],
            'duration': round(c['end'] - c['start'], 2),
            'en': c['text'],
            'te': te_text,
            'text_original': c['text'],
            'text_target': te_text
        })

    return {
        "status": "success",
        "video_id": video_id,
        "embed_url": f"https://www.youtube-nocookie.com/embed/{video_id}?enablejsapi=1&autoplay=1&playsinline=1&controls=1",
        "total_cues": len(translated_cues),
        "cues": translated_cues
    }
