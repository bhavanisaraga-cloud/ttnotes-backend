import os
import re
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

def translate_to_telugu(text: str) -> str:
    """Instant translation to Telugu via lightweight Google endpoint."""
    if not text.strip():
        return ""
    try:
        # Split into manageable chunks if long
        chunks = [text[i:i+400] for i in range(0, len(text), 400)]
        results = []
        for c in chunks:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=te&dt=t&q={urllib.parse.quote(c)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                translated = "".join([part[0] for part in data[0] if part[0]])
                results.append(translated)
        return " ".join(results)
    except Exception as e:
        return text

def generate_telugu_notes(title: str, platform: str, raw_text: str, gemini_api_key: Optional[str] = None) -> str:
    """
    Transforms video content / transcript from YouTube, Instagram, Facebook, etc.
    into structured, elegant Telugu study notes.
    """
    if gemini_api_key:
        try:
            # Use Gemini 1.5 Flash if API key provided
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_api_key}"
            system_prompt = (
                "You are TT Notes, an elite Telugu educational notes specialist. "
                "Transform the provided video transcript into structured, highly readable Markdown notes in natural, professional Telugu (సరళ వ్యావహారిక తెలుగు). "
                "Include: 1. 📌 ఎగ్జిక్యూటివ్ సారాంశం (Executive Summary), 2. 🔑 ప్రధాన ముఖ్యాంశాలు (Key Takeaways), "
                "3. ⏱️ సమయాల విశ్లేషణ (Timestamped Breakdown), 4. 💡 కార్యాచరణ ప్రణాళిక (Actionable Steps), 5. 📖 ముఖ్య పదాలు (Key Terminology). "
                "Keep English technical terms in brackets next to Telugu."
            )
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": f"Video Platform: {platform}\nTitle: {title}\nTranscript/Content:\n{raw_text[:8000]}"}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 3000}
            }
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print("Gemini API call failed, falling back to local NLP structurer:", e)

    # Local fallback structurer & Telugu translator
    telugu_title = translate_to_telugu(title)
    
    # Extract sentences
    sentences = [s.strip() for s in re.split(r'[.!?\n]', raw_text) if len(s.strip()) > 15]
    if not sentences:
        sentences = [raw_text[:200]]

    # Translate key sections
    summary_src = ". ".join(sentences[:3])
    points_src = sentences[3:9] if len(sentences) >= 9 else sentences[:5]
    actions_src = sentences[-3:] if len(sentences) >= 6 else sentences[:2]

    summary_te = translate_to_telugu(summary_src)
    points_te = [translate_to_telugu(p) for p in points_src]
    actions_te = [translate_to_telugu(a) for a in actions_src]

    notes_md = f"""# 📌 {telugu_title}
**ప్లాట్‌ఫారమ్:** {platform} | **బ్రాండ్:** TT Notes (Video to Telugu PDF)

---

### 1. 📝 ఎగ్జిక్యూటివ్ సారాంశం (Executive Summary)
> {summary_te}

---

### 2. 🔑 ప్రధాన ముఖ్యాంశాలు (Key Takeaways)
"""
    for idx, pt in enumerate(points_te, 1):
        notes_md += f"- **అంశం {idx}:** {pt}\n"

    notes_md += """
---

### 3. 💡 చేయవలసిన పనులు / కార్యాచరణ ప్రణాళిక (Actionable Steps)
"""
    for idx, act in enumerate(actions_te, 1):
        notes_md += f"{idx}. **దశ {idx}:** {act}\n"

    notes_md += f"""
---

### 4. 📖 సాంకేతిక పదాల సూచిక (Vocabulary & Context)
| ఆంగ్ల పదం (English) | తెలుగు అర్థం (Telugu Meaning) | వేదిక (Platform) |
| :--- | :--- | :--- |
| Video Content | వీడియో సమాచారం | {platform} |
| Core Concept | ముఖ్య భావన | TT Notes Engine |
| Action Plan | కార్యాచరణ ప్రణాళిక | Telugu Study System |

---
*TT Notes AI ద్వారా రూపొందించబడింది. 100% జీరో-స్టోరేజ్ & ఎఫెమరల్ ప్రాసెసింగ్.*
"""
    return notes_md

def generate_telugu_pdf_html(title: str, platform: str, url: str, markdown_content: str, is_pro: bool = False) -> str:
    """
    Renders pure, ligature-perfect Telugu HTML with embedded Google Noto Sans Telugu font.
    Can be printed or saved as PDF without broken consonants/vattulu.
    """
    # Simple markdown to HTML conversion
    html_body = markdown_content
    html_body = re.sub(r'^# (.*)$', r'<h1>\1</h1>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^### (.*)$', r'<h3>\1</h3>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^\> (.*)$', r'<blockquote>\1</blockquote>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^- \*\*(.*?)\*\*: (.*)$', r'<li><b>\1:</b> \2</li>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'^\d+\. \*\*(.*?)\*\*: (.*)$', r'<li><b>\1:</b> \2</li>', html_body, flags=re.MULTILINE)
    html_body = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html_body)
    html_body = html_body.replace('\n\n', '<br>')

    watermark = "" if is_pro else """
    <div style="margin-top: 40px; border-top: 1px dashed #CBD5E1; padding-top: 14px; text-align: center; color: #94A3B8; font-size: 10pt;">
        Generated by <b>TT Notes: Video to Telugu PDF</b> (Free Tier) • Pro వెర్షన్‌లో వాటర్‌మార్క్ ఉండదు.
    </div>
    """

    return f"""<!DOCTYPE html>
<html lang="te">
<head>
  <meta charset="UTF-8">
  <title>{title} - TT Telugu Notes</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+Telugu:wght@400;600;700&display=swap');
    
    @page {{
      size: A4;
      margin: 20mm 15mm;
    }}
    
    body {{
      font-family: 'Noto Sans Telugu', sans-serif;
      color: #1E293B;
      line-height: 1.8;
      font-size: 12pt;
      margin: 0;
      padding: 24px;
      background-color: #FFFFFF;
      text-rendering: optimizeLegibility;
      -webkit-font-smoothing: antialiased;
    }}

    .header-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 3px solid #4F46E5;
      padding-bottom: 12px;
      margin-bottom: 20px;
    }}

    .brand-title {{
      font-size: 18pt;
      font-weight: 700;
      color: #1E293B;
    }}

    .brand-tag {{
      background: #EEF2FF;
      color: #4F46E5;
      padding: 4px 10px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 9pt;
    }}

    .meta-box {{
      background-color: #F8FAFC;
      border-left: 4px solid #F59E0B;
      padding: 10px 14px;
      margin-bottom: 20px;
      font-size: 10pt;
      color: #334155;
    }}

    h1 {{ font-size: 16pt; color: #1E293B; margin-top: 10px; }}
    h3 {{ font-size: 13pt; color: #4338CA; margin-top: 18px; border-bottom: 1px solid #E2E8F0; padding-bottom: 4px; }}
    blockquote {{
      background-color: #EEF2FF;
      border-left: 4px solid #4F46E5;
      padding: 10px 14px;
      margin: 12px 0;
      color: #1E1B4B;
    }}
    li {{ margin-bottom: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 10pt; }}
    th, td {{ border: 1px solid #CBD5E1; padding: 6px 10px; text-align: left; }}
    th {{ background: #F1F5F9; }}
    @media print {{
      body {{ padding: 0; }}
      .no-print {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="no-print" style="margin-bottom: 16px; text-align: right;">
    <button onclick="window.print()" style="background: #4F46E5; color: white; border: none; padding: 10px 18px; border-radius: 6px; font-weight: 600; cursor: pointer;">
      📄 PDF డౌన్‌లోడ్ చేసుకోండి (Print / Save as PDF)
    </button>
  </div>

  <div class="header-bar">
    <div class="brand-title">TT Notes • తెలుగు స్టడీ నోట్స్</div>
    <div class="brand-tag">వేదిక: {platform}</div>
  </div>

  <div class="meta-box">
    <div><b>వీడియో లింక్:</b> <a href="{url}" target="_blank">{url}</a></div>
  </div>

  <div>
    {html_body}
  </div>

  {watermark}
</body>
</html>
"""
