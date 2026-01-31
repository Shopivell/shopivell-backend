"""
Test: 2 Ad Sets for ANY website using full pipeline agents
============================================================
Usage: python test_2adsets_securesights.py [website_url]
Default: https://zimsecuresights.co.zw

Pipeline:
1. Full-page screenshot of the website (entire homepage)
2. Pass full homepage to Gemini for deep brand + service analysis
3. AdCreativeAgent generates 2 distinct ad set prompts (dynamic from analysis)
4. For each ad set: Gemini scene gen (with full homepage as reference) + PIL compose

Everything is dynamic from the brand analysis - no hardcoded assets.
"""

import os
import sys
import json
import re
import base64
import asyncio
import requests
from urllib.parse import quote
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

# Pass website URL as command-line arg, or default to securesights
WEBSITE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://zimsecuresights.co.zw"
SITE_SLUG = WEBSITE_URL.replace("https://", "").replace("http://", "").replace("/", "_").replace(".", "_")
SCREENSHOTONE_KEY = os.getenv("SCREENSHOTONE_ACCESS_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OUT = os.path.join(os.path.dirname(__file__), "uploads", "test_output", f"{SITE_SLUG}_2ads")


def log(step, msg):
    print(f"\n{'='*70}\n  [{step}] {msg}\n{'='*70}")


def save(name, data, mode="wb"):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, mode) as f:
        f.write(data)
    print(f"  >> Saved: {p}")
    return p


# ------------------------------------------------------------------
# Step 0: Extract logo URL from website HTML
# ------------------------------------------------------------------
def extract_logo_url():
    log("STEP 0", f"Extracting logo URL from {WEBSITE_URL}")
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
        resp = requests.get(WEBSITE_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Search patterns for logo images (order by likelihood)
        candidates = []

        def get_real_src(img_tag):
            """Get the real image URL, preferring data-src over src, skipping data: URIs and junk."""
            skip_words = ['loader', 'spinner', 'placeholder', 'blank', 'spacer', 'pixel', 'loading']
            for attr in ['data-src', 'data-lazy-src', 'data-original', 'srcset', 'src']:
                val = img_tag.get(attr, '')
                if attr == 'srcset' and val:
                    # Take the first URL from srcset
                    val = val.split(',')[0].strip().split(' ')[0]
                if val and not val.startswith('data:'):
                    if any(s in val.lower() for s in skip_words):
                        continue
                    return val
            return ''

        # Priority 1: Logo img inside header/nav (check for "logo" in attrs to avoid menu images)
        for tag in ['header', 'nav']:
            el = soup.find(tag)
            if el:
                for img in el.find_all('img'):
                    cls = img.get('class', [])
                    cls_str = ' '.join(cls) if isinstance(cls, list) else str(cls)
                    check = ' '.join([cls_str, str(img.get('id', '')), str(img.get('alt', '')), str(img.get('src', '')), str(img.get('data-src', ''))]).lower()
                    if 'logo' in check:
                        src = get_real_src(img)
                        if src:
                            candidates.append(urljoin(WEBSITE_URL, src))

        # Priority 2: Links with "logo" in class/id containing img
        for a in soup.find_all('a', class_=lambda c: c and 'logo' in str(c).lower()):
            img = a.find('img')
            if img:
                src = get_real_src(img)
                if src:
                    candidates.append(urljoin(WEBSITE_URL, src))

        # Priority 3: img tags with "logo" in class or id (not just filename)
        for img in soup.find_all('img'):
            cls = img.get('class', [])
            cls_str = ' '.join(cls) if isinstance(cls, list) else str(cls)
            id_str = str(img.get('id', ''))
            if 'logo' in cls_str.lower() or 'logo' in id_str.lower():
                src = get_real_src(img)
                if src:
                    candidates.append(urljoin(WEBSITE_URL, src))

        # Priority 4: First img in header/nav (no "logo" check - often the logo anyway)
        for tag in ['header', 'nav']:
            el = soup.find(tag)
            if el:
                img = el.find('img')
                if img:
                    src = get_real_src(img)
                    if src:
                        candidates.append(urljoin(WEBSITE_URL, src))
                        break

        # Deduplicate while preserving priority order
        seen = set()
        unique = []
        for url in candidates:
            if url not in seen:
                seen.add(url)
                unique.append(url)

        # Take the first candidate (priority order: header/nav > logo-class > logo-id)
        # Only return raster logos that PIL can render (PNG/JPG/WEBP/ICO)
        pil_formats = ['.png', '.jpg', '.jpeg', '.webp', '.ico', '.gif']
        best_raster = None
        for url in unique:
            if any(url.lower().endswith(ext) for ext in pil_formats):
                best_raster = url
                break

        if not best_raster:
            # Fallback: try favicon or apple-touch-icon
            for path in ['/apple-touch-icon.png', '/favicon-32x32.png', '/favicon.ico']:
                try:
                    fav_url = urljoin(WEBSITE_URL, path)
                    r = requests.head(fav_url, headers=headers, timeout=5)
                    if r.status_code == 200:
                        best_raster = fav_url
                        print(f"  >> Using favicon fallback: {fav_url}")
                        break
                except Exception:
                    pass

        if best_raster:
            print(f"  >> Found logo (PIL-renderable): {best_raster}")
            save("logo_url.txt", best_raster, "w")
            return best_raster
        else:
            print("  >> No PIL-renderable logo found - Gemini will create from screenshot")
            return None

    except ImportError:
        print("  >> bs4 not installed, skipping logo extraction")
        return None
    except Exception as e:
        print(f"  >> Logo extraction error: {e}")
        return None


# ------------------------------------------------------------------
# Step 1: Full-page screenshot (entire homepage, not just viewport)
# ------------------------------------------------------------------
def take_full_page_screenshot():
    log("STEP 1", f"Full-page screenshot of {WEBSITE_URL}")

    api_url = (
        f"https://api.screenshotone.com/take?"
        f"access_key={SCREENSHOTONE_KEY}"
        f"&url={quote(WEBSITE_URL, safe='')}"
        f"&viewport_width=1280&viewport_height=800"
        f"&full_page=true"
        f"&format=png&block_ads=true&block_trackers=true"
        f"&delay=5&timeout=30"
    )

    print("  Fetching full-page screenshot...")
    resp = requests.get(api_url, timeout=90)

    if resp.status_code == 200 and 'image' in resp.headers.get('content-type', ''):
        data = resp.content
        b64 = base64.b64encode(data).decode()
        print(f"  >> Full page screenshot: {len(data):,} bytes")
        save("homepage_full.png", data)
        return {"ok": True, "bytes": data, "b64": b64}

    print(f"  ERROR: {resp.status_code}")
    return {"ok": False}


# ------------------------------------------------------------------
# Step 2: Deep brand + service analysis with Gemini (full homepage)
# ------------------------------------------------------------------
def analyze_homepage(screenshot_b64):
    log("STEP 2", "Gemini deep analysis of full homepage")

    prompt = """You are looking at the FULL homepage of a company website. Analyze everything visible and return detailed JSON:

{
    "company_name": "",
    "tagline": "",
    "logo_description": "EXACT description of the logo as it appears",
    "primary_color": "#hex (the dominant background color)",
    "accent_color": "#hex (the bright highlight/CTA color)",
    "industry": "",
    "what_they_do": "2-3 sentence description of their core business",
    "services": ["list ALL services/features visible on the page"],
    "key_benefits": ["list specific benefits mentioned"],
    "imagery_on_site": "describe ALL images/visuals on the page in detail",
    "uniforms_visible": "describe any staff uniforms visible: exact colors, style (polo/shirt/jacket), any logos or badges on them, reflective strips, etc. Say 'none visible' if no uniforms shown.",
    "vehicles_visible": "describe any branded vehicles visible: vehicle type (van/truck/car), body color, branding placement, any stripes or chevrons, logo position. Say 'none visible' if no vehicles shown.",
    "equipment_visible": "describe any equipment visible: cameras, alarms, barriers, tools, devices - their exact style and colors",
    "visual_style": "describe the overall design aesthetic",
    "target_audience": "",
    "cta_buttons": ["list all call-to-action buttons visible"]
}

Be thorough and PRECISE about visual details - especially logos, uniforms, vehicles, and equipment. These descriptions will be used to recreate these assets accurately in generated images."""

    # Try Gemini direct first, then OpenRouter fallback
    text = None

    # Attempt 1: Gemini direct
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)
        img_bytes = base64.b64decode(screenshot_b64)
        img_part = types.Part.from_bytes(data=img_bytes, mime_type="image/png")

        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[prompt, img_part],
            config=types.GenerateContentConfig(temperature=0.2)
        )
        text = resp.candidates[0].content.parts[0].text
        print("  >> Used Gemini direct")
    except Exception as e:
        print(f"  Gemini direct failed: {str(e)[:150]}")

    # Attempt 2: OpenRouter fallback (Gemini via proxy)
    if not text:
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            print("  Trying OpenRouter fallback for brand analysis...")
            # Resize screenshot for API (max 1024px wide)
            from PIL import Image
            from io import BytesIO
            img_bytes = base64.b64decode(screenshot_b64)
            img = Image.open(BytesIO(img_bytes))
            if img.width > 1024:
                ratio = 1024 / img.width
                img = img.resize((1024, int(img.height * ratio)), Image.Resampling.LANCZOS)
            # Crop to just top portion for analysis (saves tokens)
            if img.height > 3000:
                img = img.crop((0, 0, img.width, 3000))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            resized_b64 = base64.b64encode(buf.getvalue()).decode()

            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.5-flash",
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{resized_b64}"}},
                            {"type": "text", "text": prompt},
                        ]
                    }],
                },
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"]
            print("  >> Used OpenRouter (Gemini Flash)")
        else:
            raise RuntimeError("No Gemini API key or OpenRouter key available for analysis")

    print(f"  Analysis:\n  {text[:2000]}")

    brand = None
    try:
        js = text.find('{')
        je = text.rfind('}') + 1
        if js >= 0:
            brand = json.loads(text[js:je])
            print(f"\n  >> Company: {brand.get('company_name')}")
            print(f"  >> What they do: {brand.get('what_they_do', '')[:200]}")
            print(f"  >> Services: {brand.get('services', [])}")
            print(f"  >> Imagery: {brand.get('imagery_on_site', '')[:200]}")
            print(f"  >> Primary: {brand.get('primary_color')}, Accent: {brand.get('accent_color')}")
    except json.JSONDecodeError as e:
        print(f"  JSON error: {e}")

    save("brand_analysis.json", json.dumps(brand or {"raw": text}, indent=2), "w")
    return brand or {}


# ------------------------------------------------------------------
# Step 3: AdCreativeAgent - generate 2 different ad angles
# ------------------------------------------------------------------
async def generate_2_creatives(brand):
    log("STEP 3", "AdCreativeAgent (Claude) - 2 distinct ad angles")

    from modules.agents.ad_creative_agent import AdCreativeAgent
    agent = AdCreativeAgent()

    company = brand.get("company_name", "Company")
    what = brand.get("what_they_do", "business services")
    services = brand.get("services", ["Service 1", "Service 2", "Service 3"])
    benefits = brand.get("key_benefits", services)
    accent = brand.get("accent_color", "#FFB800")
    primary = brand.get("primary_color", "#1A233A")
    target = brand.get("target_audience", "General business audience")
    imagery = brand.get("imagery_on_site", "")

    # Build dynamic visual direction from brand analysis
    vis_dir_base = (
        f"Use the exact visual assets from the company website as reference. "
        f"Match the website's color scheme ({accent} accents on {primary} background). "
        f"Website imagery includes: {imagery}. "
        f"Replicate these same asset designs. Professional aesthetic matching the website's mood."
    )

    industry = brand.get("industry", "business")

    # Ad Set 1: Focus on the core product/service
    print("\n  --- Ad Set 1: Product/Service Focus ---")
    ad1 = await agent.generate_ad_creative(
        product_name=company,
        product_description=f"{company}: {what}",
        target_audience=target,
        key_benefits=services[:3],
        call_to_action="LEARN MORE",
        angle_name="Product Showcase",
        angle_value_proposition=f"Experience the best of {services[0] if services else industry} from {company}",
        angle_emotion="Confidence",
        visual_direction=vis_dir_base + f" Show {company}'s core products or services in a real-world setting that matches the {industry} industry.",
        brand_color=accent,
    )
    print(f"  Headline: {ad1.get('headline')}")
    print(f"  Model: {ad1.get('ai_model')}")
    print(f"  Prompt: {ad1.get('image_prompt', '')[:300]}...")

    # Ad Set 2: Focus on customer experience/benefits
    print("\n  --- Ad Set 2: Customer Benefits ---")
    ad2 = await agent.generate_ad_creative(
        product_name=company,
        product_description=f"{company}: {what}",
        target_audience=target,
        key_benefits=benefits[:3] if benefits else services[:3],
        call_to_action="GET STARTED",
        angle_name="Customer Experience",
        angle_value_proposition=f"See why {target} choose {company}",
        angle_emotion="Satisfaction",
        visual_direction=vis_dir_base + f" Show a satisfied customer enjoying {company}'s {industry.lower()} products or services in a real-world setting.",
        brand_color=accent,
    )
    print(f"  Headline: {ad2.get('headline')}")
    print(f"  Model: {ad2.get('ai_model')}")
    print(f"  Prompt: {ad2.get('image_prompt', '')[:300]}...")

    save("ad1_creative.json", json.dumps(ad1, indent=2), "w")
    save("ad2_creative.json", json.dumps(ad2, indent=2), "w")
    return ad1, ad2


# ------------------------------------------------------------------
# Step 4: Strip text overlay directives
# ------------------------------------------------------------------
def strip_text(prompt):
    c = re.sub(r"TEXT OVERLAY:\s*[^.]*\.?\s*", "", prompt)
    c = re.sub(r"On the left side of the image,?\s*display\s+\d*\s*bullet\s+points?[^.]*\.\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"Include\s+a\s+[\w\s#]+colored\s+button[^.]*\.\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"LOGO:\s*[^.]*\.\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"Ensure\s+all\s+text\s+(overlays?\s+)?[^.]*\.\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"Subject\s+positioned\s+center-right\.?\s*", "", c, flags=re.IGNORECASE)
    c = re.sub(r"\s{2,}", " ", c).strip()
    c += " Do NOT include any text, headlines, buttons, or overlays. Generate ONLY the photorealistic scene."
    return c


# ------------------------------------------------------------------
# Step 5a: Break screenshot into focused sections
# ------------------------------------------------------------------
def crop_screenshot_sections(homepage_bytes):
    """Crop the full-page screenshot into focused sections so Gemini can see details."""
    from PIL import Image
    from io import BytesIO

    img = Image.open(BytesIO(homepage_bytes))
    w, h = img.size
    print(f"  Screenshot size: {w}x{h}")

    sections = []

    # Section 1: Header/Logo area (top ~500px)
    header_h = min(500, h)
    header = img.crop((0, 0, w, header_h))
    buf = BytesIO()
    header.save(buf, format="PNG")
    sections.append({"label": "HEADER (logo, navigation, branding)", "bytes": buf.getvalue()})
    print(f"  >> Cropped header: {w}x{header_h}")

    # Section 2-4: Content sections (~1500px each)
    section_h = 1500
    y = header_h
    idx = 2
    while y < h and idx <= 4:
        end_y = min(y + section_h, h)
        section = img.crop((0, y, w, end_y))
        buf = BytesIO()
        section.save(buf, format="PNG")
        sections.append({"label": f"CONTENT SECTION {idx-1} (services, images, assets)", "bytes": buf.getvalue()})
        print(f"  >> Cropped section {idx-1}: {w}x{end_y - y} (y={y}-{end_y})")
        y = end_y
        idx += 1

    return sections


# ------------------------------------------------------------------
# Step 5: Generate scene with Gemini (passing cropped screenshot sections)
# ------------------------------------------------------------------
async def generate_scene(label, scene_prompt, homepage_b64, brand, has_logo=False):
    log(f"STEP 5 ({label})", "Scene generation with cropped screenshot sections")

    homepage_bytes = base64.b64decode(homepage_b64)

    # Break screenshot into focused sections
    sections = crop_screenshot_sections(homepage_bytes)

    company = brand.get("company_name", "Company")
    primary = brand.get("primary_color", "#1A233A")
    accent = brand.get("accent_color", "#FFB800")
    what = brand.get("what_they_do", "business services")

    enhanced = f"""I am attaching CROPPED SECTIONS of {company}'s website homepage so you can see the details clearly.

{company} does: {what}

YOUR TASK: Generate a professional advertising image for {company}.

Study each attached image carefully. Use any useful VISUAL assets you find - uniforms, vehicles, equipment, products, colors, branding VISUALS - and copy them EXACTLY as they appear into the generated image. Same colors, same style, same details.

CRITICAL: Only copy VISUAL elements (uniforms, vehicles, equipment, colors, physical objects). Do NOT copy any TEXT you see in the screenshots - no company names, no slogans, no product names, no headings, no labels, no watermarks. Text will be added separately.

"""
    if has_logo:
        enhanced += "DO NOT add any standalone logo graphic or company name text overlay to the image. However, if vehicles, uniforms, or equipment from the screenshot already have branding on them, keep that branding as it appears. The real logo will be added separately.\n"
    else:
        enhanced += "Include the company logo as it appears on the screenshot. Copy it exactly.\n"

    enhanced += f"""

Match the website's color scheme: background {primary}, accents {accent}.

SCENE TO GENERATE:
{scene_prompt}

RULES:
- ABSOLUTELY NO TEXT of any kind in the generated image. No headlines, no labels, no company names, no product names, no slogans, no buttons, no bullet text, no watermarks, no signs with text. The image must contain ZERO readable text.
- Do NOT reproduce any text you see in the screenshot reference images. Only copy visual/physical elements.
- People can be in the FOREGROUND as main subjects, but NEVER place small people or faces in the background - they will appear distorted
- ONLY generate the photorealistic scene with NO text whatsoever
"""

    print(f"  >> Passing {len(sections)} cropped sections")

    # Attempt 1: Gemini direct
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=GEMINI_API_KEY)

        content_parts = [enhanced]
        for section in sections:
            part = types.Part.from_bytes(data=section["bytes"], mime_type="image/png")
            content_parts.append(part)

        models = ["gemini-3-pro-image-preview", "gemini-2.0-flash-exp-image-generation"]

        for model in models:
            try:
                print(f"  Trying {model} (Gemini direct)...")
                resp = client.models.generate_content(
                    model=model,
                    contents=content_parts,
                    config=types.GenerateContentConfig(
                        response_modalities=['IMAGE', 'TEXT'],
                        temperature=0.8,
                    )
                )

                img_data = None
                resp_text = None
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        resp_text = part.text
                    elif hasattr(part, 'inline_data') and part.inline_data:
                        img_data = part.inline_data.data

                if img_data:
                    b64 = base64.b64encode(img_data).decode() if isinstance(img_data, bytes) else img_data
                    raw = base64.b64decode(b64) if isinstance(img_data, str) else img_data
                    print(f"  >> Model: {model}, Size: {len(raw):,} bytes")
                    if resp_text:
                        print(f"  >> Notes: {resp_text[:200]}")
                    save(f"{label}_scene.png", raw)
                    return {"ok": True, "b64": b64, "bytes": raw, "model": model}
                else:
                    print(f"  No image from {model}")
            except Exception as e:
                print(f"  {model} failed: {str(e)[:200]}")
    except Exception as e:
        print(f"  Gemini direct unavailable: {str(e)[:150]}")

    # Attempt 2: OpenRouter fallback (Nano Banana Pro)
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if openrouter_key:
        print("  Trying OpenRouter (Nano Banana Pro) fallback...")
        from PIL import Image as PILImg
        from io import BytesIO

        # Resize sections to 1024px wide JPEG for smaller payloads
        content_parts = []
        for section in sections:
            img = PILImg.open(BytesIO(section["bytes"])).convert("RGB")
            if img.width > 1024:
                ratio = 1024 / img.width
                img = img.resize((1024, int(img.height * ratio)), PILImg.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            s_b64 = base64.b64encode(buf.getvalue()).decode()
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{s_b64}"}
            })
        content_parts.append({"type": "text", "text": enhanced[:4000]})

        for model_id in ["google/gemini-3-pro-image-preview", "google/gemini-2.5-flash-image-preview"]:
            try:
                print(f"  Trying {model_id} via OpenRouter...")
                resp = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://shopivell.com",
                        "X-Title": "Shopivell Test",
                    },
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": content_parts}],
                        "modalities": ["image", "text"],
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                result = resp.json()

                msg = result.get("choices", [{}])[0].get("message", {})
                images = msg.get("images", [])
                if images:
                    img_url = images[0].get("image_url", {}).get("url", "")
                    if img_url.startswith("data:"):
                        b64_data = img_url.split(",", 1)[1]
                        raw = base64.b64decode(b64_data)
                        print(f"  >> Model: {model_id} via OpenRouter, Size: {len(raw):,} bytes")
                        save(f"{label}_scene.png", raw)
                        return {"ok": True, "b64": b64_data, "bytes": raw, "model": model_id}
                else:
                    # Check for inline base64 in content
                    content = msg.get("content", "")
                    if "base64" in content[:100]:
                        print(f"  >> Got inline base64 content from {model_id}")
                    else:
                        print(f"  No image from {model_id} via OpenRouter")
            except Exception as e:
                print(f"  {model_id} via OpenRouter failed: {str(e)[:200]}")

    return {"ok": False}


# ------------------------------------------------------------------
# Step 6: Compose final ad with PIL
# ------------------------------------------------------------------
def crop_logo_from_screenshot(homepage_bytes):
    """Crop the top-left corner of the screenshot where the logo typically sits."""
    from PIL import Image
    from io import BytesIO

    img = Image.open(BytesIO(homepage_bytes))
    w, h = img.size
    # Crop top-left area: logo is usually in the first ~100px height, left ~350px
    logo_crop = img.crop((0, 0, min(350, w), min(100, h)))
    buf = BytesIO()
    logo_crop.save(buf, format="PNG")
    return buf.getvalue()


def compose(label, scene_b64, headline, bullets, cta, brand_name, brand_color, logo_url=None, logo_bytes=None):
    log(f"STEP 6 ({label})", f"Compose final ad: {headline}")

    from modules.agents.ad_image_composer import AdImageComposer
    composer = AdImageComposer()
    scene_bytes = base64.b64decode(scene_b64)

    print(f"  Headline: {headline}")
    print(f"  Bullets:  {bullets}")
    print(f"  CTA:      {cta}")
    print(f"  Color:    {brand_color}")
    print(f"  Logo:     {logo_url or ('cropped from screenshot' if logo_bytes else 'none')}")

    # If no URL but we have cropped logo bytes, save to temp file and use that path
    if not logo_url and logo_bytes:
        logo_path = os.path.join(OUT, "logo_cropped.png")
        with open(logo_path, "wb") as f:
            f.write(logo_bytes)
        logo_url = logo_path

    result = composer.compose_modern_ad_image(
        base_image=scene_bytes,
        headline=headline,
        bullet_points=bullets,
        cta_text=cta,
        brand_name=brand_name,
        brand_color=brand_color,
        logo_url=logo_url,
    )

    if result.get("success"):
        final_bytes = base64.b64decode(result["image_base64"])
        save(f"{label}_final.png", final_bytes)
        print(f"  >> Final: {len(final_bytes):,} bytes")
        return {"ok": True, "b64": result["image_base64"]}
    else:
        print(f"  ERROR: {result.get('error')}")
        return {"ok": False}


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
async def main():
    print(f"\n{'='*70}")
    print(f"  2 AD SETS - {WEBSITE_URL}")
    print(f"  {datetime.now().isoformat()}")
    print(f"{'='*70}")

    os.makedirs(OUT, exist_ok=True)

    # Step 0: Extract real logo URL from website HTML
    logo_url = extract_logo_url()

    # Step 1: Full page screenshot
    ss = take_full_page_screenshot()
    if not ss.get("ok"):
        print("FATAL: Screenshot failed")
        return

    # If no logo URL, crop the top-left of the screenshot (where logo sits)
    logo_crop_bytes = None
    if not logo_url:
        log("STEP 0b", "Cropping logo from screenshot top-left corner")
        logo_crop_bytes = crop_logo_from_screenshot(ss["bytes"])
        save("logo_cropped.png", logo_crop_bytes)

    # Step 2: Deep homepage analysis
    brand = analyze_homepage(ss["b64"])

    # Step 3: 2 creative prompts from AdCreativeAgent
    ad1, ad2 = await generate_2_creatives(brand)

    # Step 4 + 5 + 6 for each ad set
    accent = brand.get("accent_color", "#FFB800")
    company = brand.get("company_name", "Company")
    services = brand.get("services", ["ANPR", "Vehicle identification", "Parking management"])
    benefits = brand.get("key_benefits", services)

    for idx, (ad, default_cta, bullet_source) in enumerate([
        (ad1, "LEARN MORE", services),
        (ad2, "GET STARTED", benefits if benefits else services),
    ], 1):
        label = f"ad{idx}"
        prompt = ad.get("image_prompt", "")
        if not prompt:
            print(f"\n  SKIP ad{idx}: no prompt")
            continue

        # Step 4: Strip text
        log(f"STEP 4 (ad{idx})", "Strip text directives")
        scene_prompt = strip_text(prompt)
        print(f"  Stripped: {len(prompt)} -> {len(scene_prompt)} chars")
        save(f"{label}_scene_prompt.txt", scene_prompt, "w")

        # Step 5: Generate scene with full homepage reference
        scene = await generate_scene(label, scene_prompt, ss["b64"], brand, has_logo=bool(logo_url))
        if not scene.get("ok"):
            print(f"  FAIL: scene gen for ad{idx}")
            continue

        # Step 6: Compose with real logo
        headline = ad.get("headline", f"Discover {company}")
        bullets = [b if len(b) < 55 else b[:52] + "..." for b in bullet_source[:3]]
        cta_text = default_cta

        compose(label, scene["b64"], headline, bullets, cta_text, company, accent, logo_url=logo_url, logo_bytes=logo_crop_bytes)

    # Summary
    log("DONE", "2 Ad Sets Complete")
    print(f"  Output: {OUT}")
    print(f"  Files:")
    for f in sorted(os.listdir(OUT)):
        size = os.path.getsize(os.path.join(OUT, f))
        print(f"    {f:35s} {size:>12,} bytes")


if __name__ == "__main__":
    asyncio.run(main())
