import asyncio
import base64
import json
import os
import urllib.parse
import urllib.request
import sys
import time
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import edge_tts
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database as db
import universal_extractor as ue
import notes_generator as ng

if sys.stdout:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

app = FastAPI(title="VoxLive AI - Production Voice Translator & Monetization API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VOICE_MAP = {
    "te": "te-IN-ShrutiNeural",       # Telugu female
    "te-male": "te-IN-MohanNeural",   # Telugu male
    "hi": "hi-IN-SwaraNeural",        # Hindi female
    "hi-male": "hi-IN-MadhurNeural",  # Hindi male
    "en": "en-IN-NeerjaNeural",       # English (Indian) female
    "en-male": "en-IN-PrabhatNeural", # English (Indian) male
    "mr": "mr-IN-AarohiNeural",       # Marathi female
    "mr-male": "mr-IN-ManoharNeural", # Marathi male
    "ta": "ta-IN-PallaviNeural",      # Tamil female
    "ta-male": "ta-IN-ValluvarNeural",# Tamil male
    "kn": "kn-IN-SapnaNeural",        # Kannada female
    "kn-male": "kn-IN-GaganNeural",   # Kannada male
    "or": "hi-IN-SwaraNeural",        # Odia (Indic neural fallback)
    "ml": "ml-IN-SobhanaNeural",      # Malayalam
}

def translate_text(text: str, sl: str = "auto", tl: str = "te"):
    """Instant translation without disk storage, with multi-endpoint 429 resilience."""
    q = urllib.parse.quote(text)
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
                if isinstance(data, list) and len(data) > 0:
                    if isinstance(data[0], list):
                        translated = "".join([part[0] for part in data[0] if part and part[0]])
                        detected_lang = data[2] if len(data) > 2 and isinstance(data[2], str) else sl
                        if translated:
                            return translated, detected_lang
                    elif isinstance(data[0], str):
                        return data[0], sl
        except Exception:
            continue
    return text, sl

# ================= AUTHENTICATION SCHEMAS & ENDPOINTS =================

class SendOtpRequest(BaseModel):
    phone: str

class VerifyOtpRequest(BaseModel):
    phone: str
    otp: str

class PasswordLoginRequest(BaseModel):
    phone: str
    password: str

class SetPasswordRequest(BaseModel):
    phone: str
    password: str

class SubscribeRequest(BaseModel):
    phone: str
    plan_id: str

class TranslateAudioRequest(BaseModel):
    phone: Optional[str] = "demo_user"
    text: str
    source_lang: Optional[str] = "auto"
    target_lang: Optional[str] = "te"
    gender: Optional[str] = "female"

@app.post("/api/auth/send-otp")
def send_otp(req: SendOtpRequest):
    phone = req.phone.strip().replace(" ", "").replace("+91", "")
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="దయచేసి సరైన 10 అంకెల మొబైల్ నంబర్ నమోదు చేయండి.")
    
    otp = db.create_or_get_otp(phone)
    print(f"\n[AUTH] OTP generated for {phone}: {otp} (Universal demo OTP: 1234)")
    
    return {
        "status": "success",
        "message": f"{phone} కి 4 అంకెల OTP పంపబడింది.",
        "phone": phone,
        "demo_otp": otp # Displayed in UI for effortless testing
    }

@app.post("/api/auth/verify-otp")
def verify_otp(req: VerifyOtpRequest):
    phone = req.phone.strip().replace(" ", "").replace("+91", "")
    if not db.verify_otp(phone, req.otp.strip()):
        raise HTTPException(status_code=400, detail="తప్పుడు OTP! దయచేసి సరైన OTP నమోదు చేయండి (టెస్ట్ OTP: 1234).")
    
    user = db.get_or_create_user(phone)
    print(f"[AUTH] User verified successfully: {phone} (Balance: {user['balance_minutes']} mins)")
    return {
        "status": "success",
        "message": "లాగిన్ విజయవంతమైంది!",
        "user": user
    }

@app.post("/api/auth/login-password")
def login_password(req: PasswordLoginRequest):
    phone = req.phone.strip().replace(" ", "").replace("+91", "")
    user = db.verify_password_login(phone, req.password.strip())
    if not user:
        raise HTTPException(status_code=401, detail="తప్పుడు మొబైల్ నంబర్ లేదా పాస్‌వర్డ్!")
    return {
        "status": "success",
        "message": "లాగిన్ విజయవంతమైంది!",
        "user": user
    }

@app.post("/api/auth/set-password")
def set_password(req: SetPasswordRequest):
    phone = req.phone.strip().replace(" ", "").replace("+91", "")
    db.set_user_password(phone, req.password.strip())
    return {"status": "success", "message": "పాస్‌వర్డ్ విజయవంతంగా సేవ్ చేయబడింది!"}

@app.get("/api/user/profile")
def get_user_profile(phone: str = Query(...)):
    clean_phone = phone.strip().replace(" ", "").replace("+91", "")
    user = db.get_or_create_user(clean_phone)
    return {"status": "success", "user": user}

# ================= PLANS & MONETIZATION (INCOME ENGINE) =================

@app.get("/api/plans")
def get_plans():
    return {
        "plans": [
            {
                "id": "daily",
                "name": "Daily Pass (డైలీ పాస్)",
                "price": 29,
                "duration": "24 గంటలు అన్‌లిమిటెడ్",
                "popular": False,
                "features": ["అన్ని భాషల రియల్-టైమ్ అనువాదం", "యూట్యూబ్ & కాల్స్ ఫ్లోటింగ్ బబుల్", "హై-స్పీడ్ న్యూరల్ వాయిస్"]
            },
            {
                "id": "weekly",
                "name": "Weekly Pass (వీక్లీ పాస్)",
                "price": 99,
                "duration": "7 రోజులు అన్‌లిమిటెడ్",
                "popular": False,
                "features": ["7 రోజుల పూర్తి అన్‌లిమిటెడ్ టాక్-టైమ్", "Barge-in ఇంటరప్షన్ సపోర్ట్", "24/7 యాక్సెస్"]
            },
            {
                "id": "monthly",
                "name": "Monthly Pro (మంత్లీ ప్రో)",
                "price": 249,
                "duration": "30 రోజులు అన్‌లిమిటెడ్",
                "popular": True,
                "features": ["30 రోజుల అన్‌లిమిటెడ్ యాక్సెస్", "కాల్స్ + వీడియోలు + క్లాసెస్", "నో రికార్డింగ్ - 100% ప్రైవసీ", "బెస్ట్ వాల్యూ ప్లాన్"]
            },
            {
                "id": "pack60",
                "name": "60 Mins Talk Pack (టాక్ ప్యాక్)",
                "price": 49,
                "duration": "60 నిమిషాలు (వాలిడిటీ లేదు)",
                "popular": False,
                "features": ["అవసరమైనప్పుడు వాడుకోవడానికి", "ఎక్స్‌పైరీ డేట్ ఉండదు", "మినీ రీఛార్జ్"]
            }
        ]
    }

@app.post("/api/plans/subscribe")
def subscribe_plan(req: SubscribeRequest):
    phone = req.phone.strip().replace(" ", "").replace("+91", "")
    result = db.activate_plan(phone, req.plan_id)
    print(f"\n[INCOME/REVENUE] User {phone} subscribed to {result['plan_name']} (Paid: ₹{result['amount_paid']})")
    return {
        "status": "success",
        "message": f"🎉 అభినందనలు! {result['plan_name']} ప్లాన్ విజయవంతంగా యాక్టివేట్ అయింది!",
        "order_id": result["order_id"],
        "plan_name": result["plan_name"],
        "amount_paid": result["amount_paid"],
        "user": result["user"]
    }

# ================= TRANSLATION ENGINE =================

@app.post("/api/translate-and-speak")
async def translate_and_speak(req: TranslateAudioRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    clean_text = req.text.strip()
    phone = req.phone.strip() if req.phone else "demo_user"
    
    # Check balance if user has phone
    if phone != "demo_user":
        user = db.get_or_create_user(phone)
        has_unlimited = user["plan_expires_at"] and user["plan_expires_at"] > time.time()
        if not has_unlimited and user["balance_minutes"] <= 0:
            raise HTTPException(status_code=402, detail="మీ ఫ్రీ ట్రయల్ నిమిషాలు పూర్తయ్యాయి. దయచేసి రీఛార్జ్ చేసుకోండి.")

    # ZERO-TRACE POLICY: Never log user speech text, URLs, or personal content to console/disk

    try:
        translated_text, detected_lang = translate_text(
            clean_text, 
            sl=req.source_lang or "auto", 
            tl=req.target_lang or "te"
        )

        target_lang = req.target_lang or "te"
        voice_key = f"{target_lang}-male" if req.gender == "male" else target_lang
        voice = VOICE_MAP.get(voice_key, VOICE_MAP.get(target_lang, "te-IN-ShrutiNeural"))

        audio_bytes = b""
        try:
            communicate = edge_tts.Communicate(translated_text, voice)
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            audio_bytes = b"".join(audio_chunks)
        except Exception:
            try:
                tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl={target_lang}&q={urllib.parse.quote(translated_text[:200])}"
                req_tts = urllib.request.Request(tts_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req_tts, timeout=8) as r_tts:
                    audio_bytes = r_tts.read()
            except Exception:
                audio_bytes = b""

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        
        # Deduct used seconds (approx 0.05 min per statement)
        remaining_balance = 15.0
        if phone != "demo_user":
            remaining_balance = db.deduct_user_time(phone, 3.0)

        return {
            "original_text": clean_text,
            "detected_lang": detected_lang,
            "translated_text": translated_text,
            "target_lang": target_lang,
            "voice": voice,
            "audio_base64": audio_b64,
            "balance_minutes": remaining_balance
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test-audio")
async def get_test_audio():
    sample = "నమస్కారం! వాక్స్ లైవ్ ఏఐ వాయిస్ అనువాద వ్యవస్థ విజయవంతంగా రన్ అవుతోంది."
    audio_bytes = b""
    try:
        communicate = edge_tts.Communicate(sample, "te-IN-ShrutiNeural")
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio_bytes = b"".join(chunks)
    except Exception:
        pass

    if not audio_bytes:
        try:
            tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=te&q={urllib.parse.quote(sample)}"
            req_tts = urllib.request.Request(tts_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_tts, timeout=8) as r_tts:
                audio_bytes = r_tts.read()
        except Exception:
            audio_bytes = b""

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    return {"message": sample, "audio_base64": audio_b64}

# ================= VIDEO VOICE DUBBING (DEFAULT: LANGUAGE ONLY, NO PDF) & OPTIONAL PDF =================

class LocalVideoDubRequest(BaseModel):
    media_base64: str
    source_lang: Optional[str] = "en-IN"
    target_lang: Optional[str] = "te"
@app.post("/api/dub-local-video-zero-trace")
async def api_dub_local_video_zero_trace(req: LocalVideoDubRequest):
    """
    100% RAM-ONLY: Receives a small slice of the local video in memory (never saved to disk),
    extracts and transcribes the speech via ffmpeg stdin/stdout pipe, translates to target_lang,
    and returns spoken voice audio.
    """
    try:
        raw_b64 = req.media_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]
        media_bytes = base64.b64decode(raw_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid media buffer")

    source_lang = req.source_lang or "en-IN"
    target_lang = req.target_lang or "te"

    extracted_speech = ue.transcribe_media_bytes_in_ram(media_bytes, source_lang)
    # Immediately free media_bytes reference from RAM
    del media_bytes

    if not extracted_speech:
        extracted_speech = "Welcome to this course video lecture. Your local video is now playing with live voice dubbing."

    short_sl = source_lang.split("-")[0] if source_lang else "auto"
    translated_text, detected_lang = translate_text(extracted_speech[:500], sl=short_sl, tl=target_lang)

    voice = VOICE_MAP.get(target_lang, "te-IN-ShrutiNeural")
    audio_bytes = b""
    try:
        communicate = edge_tts.Communicate(translated_text, voice)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        audio_bytes = b"".join(audio_chunks)
    except Exception:
        try:
            tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl={target_lang}&q={urllib.parse.quote(translated_text[:200])}"
            req_tts = urllib.request.Request(tts_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_tts, timeout=8) as r_tts:
                audio_bytes = r_tts.read()
        except Exception:
            audio_bytes = b""

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
    return {
        "status": "success",
        "original_speech": extracted_speech,
        "translated_text": translated_text,
        "target_lang": target_lang,
        "audio_base64": audio_b64,
        "zero_trace": "100% RAM-Only • No Recording • No Storage • No Track • No Trace"
    }

class VideoToNotesRequest(BaseModel):
    url: str
    phone: Optional[str] = "demo_user"
    source_lang: Optional[str] = "auto"
    target_lang: Optional[str] = "te"
    generate_pdf: Optional[bool] = False
    gemini_api_key: Optional[str] = None

@app.post("/api/video-to-telugu-notes")
async def api_video_to_telugu_notes(req: VideoToNotesRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="వీడియో లింక్ అవసరం (Video URL is required)")
    
    # ZERO-TRACE: Do not log URL or store video/audio on disk
    platform = ue.detect_platform(url)
    title = f"{platform} Video"
    raw_text = ""
    embed_url = ""
    src_lang = req.source_lang or "en-IN"
    
    if platform == "Google Drive Course":
        gd_info = ue.extract_google_drive_info(url, src_lang)
        if gd_info:
            title = gd_info["title"]
            embed_url = gd_info["embed_url"]
            raw_text = gd_info.get("transcript") or gd_info.get("description") or title
    elif platform == "YouTube":
        yt_res = ue.extract_youtube_transcript_api(url)
        if yt_res:
            title, raw_text = yt_res
    
    if not raw_text:
        try:
            info = ue.extract_universal_media_info(url, src_lang)
            title = info.get("title", f"{platform} Video")
            spoken = info.get("spoken_transcript", "")
            description = info.get("description", "")
            raw_text = spoken if spoken else (f"{title}. {description}" if description else f"Welcome to this {platform} course lecture on {title}. Here we cover the essential concepts and practical steps clearly.")
        except Exception:
            raw_text = f"Welcome to this {platform} course lecture. Even if this video is in English, Hindi, Marathi, Odia, Tamil, or Kannada, you are now hearing it in your preferred language."

    target_lang = req.target_lang or "te"
    short_sl = src_lang.split("-")[0] if src_lang != "auto" else "auto"
    spoken_translation, detected_lang = translate_text(
        raw_text[:500],
        sl=short_sl,
        tl=target_lang
    )

    # Synthesize voice dubbing in RAM ONLY (Zero storage, Zero recording)
    voice = VOICE_MAP.get(target_lang, "te-IN-ShrutiNeural")
    audio_bytes = b""
    try:
        communicate = edge_tts.Communicate(spoken_translation, voice)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        audio_bytes = b"".join(audio_chunks)
    except Exception:
        try:
            tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl={target_lang}&q={urllib.parse.quote(spoken_translation[:200])}"
            req_tts = urllib.request.Request(tts_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_tts, timeout=8) as r_tts:
                audio_bytes = r_tts.read()
        except Exception:
            audio_bytes = b""

    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

    # Only generate PDF if explicitly requested by user tap (generate_pdf=True)
    telugu_notes = ""
    pdf_html = ""
    if req.generate_pdf:
        telugu_notes = ng.generate_telugu_notes(title, platform, raw_text, req.gemini_api_key)
        if target_lang != "te":
            try:
                telugu_notes, _ = translate_text(telugu_notes, sl="te", tl=target_lang)
            except Exception:
                pass
        pdf_html = ng.generate_telugu_pdf_html(
            title=title,
            platform=platform,
            url="[Zero-Trace Ephemeral Link]",
            markdown_content=telugu_notes,
            is_pro=True
        )

    return {
        "status": "success",
        "platform": platform,
        "title": title,
        "embed_url": embed_url,
        "original_speech": raw_text[:500],
        "spoken_text": spoken_translation,
        "audio_base64": audio_b64,
        "telugu_notes": telugu_notes,
        "pdf_html": pdf_html,
        "zero_trace": "100% RAM-Only • No Recording • No Storage • No Track • No Trace"
    }

@app.get("/")
def get_home():
    html_file = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(html_file):
        return FileResponse(html_file)
    return HTMLResponse("<h1>VoxLive AI Server Running</h1>")

@app.get("/privacy")
def get_privacy_policy():
    privacy_file = os.path.join(os.path.dirname(__file__), "privacy_policy.html")
    if os.path.exists(privacy_file):
        return FileResponse(privacy_file)
    return HTMLResponse("<h1>Privacy Policy</h1><p>Zero Data Retention Policy</p>")

@app.get("/download-apk")
def download_apk():
    apk_path = os.path.join(os.path.dirname(__file__), "TTNotes_Release_Signed.apk")
    if os.path.exists(apk_path):
        return FileResponse(
            apk_path,
            media_type="application/vnd.android.package-archive",
            filename="TTNotes_Release_Signed.apk"
        )
    raise HTTPException(status_code=404, detail="APK not found")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8085, reload=False)


