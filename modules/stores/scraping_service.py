# modules/stores/scraping_service.py
"""
Website scraping service using Tavily for content extraction,
BeautifulSoup for image extraction, and OpenAI Vision for image analysis.
"""
import os
import json
import re
import base64
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, urlparse
from pathlib import Path
from tavily import TavilyClient
from openai import OpenAI
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat

# Screenshot capture imports
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("[Screenshot] Playwright not installed. Run: pip install playwright && playwright install chromium")

load_dotenv()

# Initialize clients
tavily_api_key = os.getenv("TAVILY_API_KEY")
openai_api_key = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


def _llm_client() -> OpenAI:
    """OpenAI direct (gpt-4o-mini for scraping/extraction), falling back to OpenRouter
    only when OPENAI_API_KEY isn't configured. Model names like "gpt-4o-mini" resolve
    on both."""
    if openai_api_key:
        return OpenAI(api_key=openai_api_key)
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")

# Screenshot storage directory
SCREENSHOT_DIR = Path("uploads/screenshots")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# MinIO configuration for screenshot uploads (reuses the same config as assets)
try:
    from modules.assets.service import minio_client, MINIO_BUCKET, MINIO_CONFIGURED, _get_minio_url
    SCREENSHOT_MINIO_AVAILABLE = MINIO_CONFIGURED and minio_client is not None
    if SCREENSHOT_MINIO_AVAILABLE:
        print("[Screenshot] MinIO configured for screenshot uploads")
    else:
        print("[Screenshot] MinIO not configured - screenshots will be stored locally only")
except ImportError:
    SCREENSHOT_MINIO_AVAILABLE = False
    minio_client = None
    MINIO_BUCKET = None
    _get_minio_url = None
    print("[Screenshot] MinIO not available - screenshots will be stored locally only")

# ScreenshotOne API configuration (fallback when Playwright fails)
SCREENSHOTONE_ACCESS_KEY = os.getenv("SCREENSHOTONE_ACCESS_KEY")
SCREENSHOTONE_CONFIGURED = bool(SCREENSHOTONE_ACCESS_KEY)
if SCREENSHOTONE_CONFIGURED:
    print("[Screenshot] ScreenshotOne API configured as fallback")


def capture_screenshot_via_api(url: str) -> Dict[str, Any]:
    """
    Capture a screenshot using ScreenshotOne API as a fallback.
    This is useful when Playwright fails due to bot detection.

    Args:
        url: The website URL to capture

    Returns:
        Dict with screenshot_bytes and success status
    """
    if not SCREENSHOTONE_CONFIGURED:
        return {
            "success": False,
            "error": "ScreenshotOne API not configured. Set SCREENSHOTONE_ACCESS_KEY env variable."
        }

    try:
        from urllib.parse import quote

        # ScreenshotOne API endpoint
        api_url = (
            f"https://api.screenshotone.com/take?"
            f"access_key={SCREENSHOTONE_ACCESS_KEY}"
            f"&url={quote(url, safe='')}"
            f"&viewport_width=1280"
            f"&viewport_height=800"
            # The whole homepage, not just the first screen: scroll first so lazy-loaded
            # sections (team photos, fleet, products) are rendered in the capture.
            f"&full_page=true"
            f"&full_page_scroll=true"
            f"&full_page_max_height=12000"
            f"&format=png"
            f"&block_ads=true"
            f"&block_trackers=true"
            f"&delay=3"
            f"&timeout=60"
        )

        print(f"[Screenshot] Trying ScreenshotOne API fallback for {url}")

        response = requests.get(api_url, timeout=90)

        if response.status_code == 200 and response.headers.get('content-type', '').startswith('image/'):
            print(f"[Screenshot] ScreenshotOne API success: {len(response.content)} bytes")
            return {
                "success": True,
                "screenshot_bytes": response.content
            }
        else:
            error_msg = f"API returned status {response.status_code}"
            if response.headers.get('content-type', '').startswith('application/json'):
                try:
                    error_data = response.json()
                    error_msg = error_data.get('error', error_msg)
                except:
                    pass
            print(f"[Screenshot] ScreenshotOne API error: {error_msg}")
            return {
                "success": False,
                "error": error_msg
            }

    except Exception as e:
        print(f"[Screenshot] ScreenshotOne API exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def upload_screenshot_to_storage(
    screenshot_bytes: bytes,
    filename: str,
    folder: str = "shopivell/screenshots"
) -> Dict[str, Any]:
    """
    Upload a screenshot to MinIO object storage.

    Args:
        screenshot_bytes: The screenshot image bytes
        filename: The filename for the screenshot
        folder: Storage folder path

    Returns:
        Dict with upload result including secure_url, or error info
    """
    if not SCREENSHOT_MINIO_AVAILABLE:
        return {
            "success": False,
            "error": "MinIO not configured"
        }

    try:
        import uuid as uuid_module
        import io

        object_name = f"{folder}/{uuid_module.uuid4().hex}_{filename}"

        minio_client.put_object(
            MINIO_BUCKET,
            object_name,
            io.BytesIO(screenshot_bytes),
            length=len(screenshot_bytes),
            content_type="image/png"
        )

        url = _get_minio_url(object_name)
        print(f"[Screenshot] Uploaded to MinIO: {url}")

        return {
            "success": True,
            "public_id": object_name,
            "url": url,
            "secure_url": url,
            "thumbnail_url": url,  # Same URL — no server-side thumbnail generation
            "format": "png",
            "bytes": len(screenshot_bytes)
        }

    except Exception as e:
        print(f"[Screenshot] MinIO upload error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def capture_homepage_screenshot(url: str, full_page: bool = False) -> Dict[str, Any]:
    """
    Capture a screenshot of the website homepage using Playwright.

    Args:
        url: The website URL to capture
        full_page: If True, captures the full scrollable page. If False, captures viewport only.

    Returns:
        Dict with screenshot_path, screenshot_base64, width, height, or error info
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "success": False,
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"
        }

    # Normalize URL
    if not url.startswith('http'):
        url = 'https://' + url

    try:
        async with async_playwright() as p:
            # Determine if running on Linux (Render) or Windows
            import platform
            is_linux = platform.system() == "Linux"

            print(f"[Screenshot] Platform: {platform.system()}, Using Playwright bundled Chromium")

            # On Render/Linux, always use Playwright's bundled Chromium
            # On Windows, try system Chrome first for faster startup
            browser = None

            if not is_linux:
                # Windows: Try to find system Chrome installation
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                ]

                for path in chrome_paths:
                    if os.path.exists(path):
                        print(f"[Screenshot] Using system Chrome: {path}")
                        browser = await p.chromium.launch(
                            headless=True,
                            executable_path=path
                        )
                        break

            # Fall back to Playwright's bundled Chromium (default for Render/Linux)
            if browser is None:
                print("[Screenshot] Launching Playwright bundled Chromium...")
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )

            # Create context with desktop viewport
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            page = await context.new_page()

            # Navigate to URL with timeout
            # Use 'domcontentloaded' instead of 'networkidle' as many sites never reach networkidle
            # due to ads, tracking scripts, live updates, etc.

            # Try HTTPS first, then fall back to HTTP if it fails
            urls_to_try = [url]
            if url.startswith('https://'):
                # Add HTTP fallback
                urls_to_try.append(url.replace('https://', 'http://'))

            navigation_success = False
            last_nav_error = None
            final_url = url

            for try_url in urls_to_try:
                print(f"[Screenshot] Navigating to {try_url}")
                try:
                    await page.goto(try_url, wait_until="domcontentloaded", timeout=30000)
                    navigation_success = True
                    final_url = try_url
                    break
                except Exception as nav_error:
                    last_nav_error = nav_error
                    error_str = str(nav_error).lower()
                    # Check if it's a connection error that might be fixed by HTTP fallback
                    if any(err in error_str for err in ['err_connection', 'err_ssl', 'err_cert', 'timeout', 'net::']):
                        print(f"[Screenshot] Connection failed for {try_url}: {nav_error}")
                        if try_url != urls_to_try[-1]:
                            print(f"[Screenshot] Trying HTTP fallback...")
                        continue
                    else:
                        # Other errors - still try to continue
                        print(f"[Screenshot] Navigation warning (continuing anyway): {nav_error}")
                        navigation_success = True
                        final_url = try_url
                        break

            if not navigation_success:
                await browser.close()
                raise Exception(f"Failed to navigate to {url}. Last error: {last_nav_error}")

            # Wait for page to stabilize and render content
            # Try waiting for common content indicators
            try:
                # Wait for body to be visible
                await page.wait_for_selector("body", state="visible", timeout=5000)
            except Exception:
                pass

            # Additional wait for JavaScript rendering
            await page.wait_for_timeout(3000)

            # Scroll to trigger lazy loading, then scroll back up
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(500)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)
            except Exception:
                pass

            # Generate unique filename
            domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
            import uuid as uuid_module
            filename = f"{domain}_{uuid_module.uuid4().hex[:8]}.png"
            screenshot_path = SCREENSHOT_DIR / filename

            # Capture screenshot
            screenshot_bytes = await page.screenshot(
                full_page=full_page,
                type="png"
            )

            # Save to file locally
            with open(screenshot_path, "wb") as f:
                f.write(screenshot_bytes)

            # Get viewport size
            viewport_size = page.viewport_size

            await browser.close()

            print(f"[Screenshot] Captured: {screenshot_path} ({len(screenshot_bytes)} bytes)")

            # Upload to MinIO
            storage_url = None
            storage_thumbnail = None
            if SCREENSHOT_MINIO_AVAILABLE:
                storage_result = upload_screenshot_to_storage(
                    screenshot_bytes=screenshot_bytes,
                    filename=filename
                )
                if storage_result.get("success"):
                    storage_url = storage_result.get("secure_url")
                    storage_thumbnail = storage_result.get("thumbnail_url")

            return {
                "success": True,
                "screenshot_path": str(screenshot_path),
                "screenshot_filename": filename,
                "screenshot_base64": base64.b64encode(screenshot_bytes).decode("utf-8"),
                "screenshot_url": storage_url,
                "thumbnail_url": storage_thumbnail,
                "width": viewport_size["width"] if viewport_size else 1920,
                "height": viewport_size["height"] if viewport_size else 1080,
                "full_page": full_page,
                "url": final_url
            }

    except Exception as e:
        print(f"[Screenshot] Playwright error: {e}")

        # Try ScreenshotOne API as fallback
        if SCREENSHOTONE_CONFIGURED:
            api_result = capture_screenshot_via_api(url)
            if api_result.get("success"):
                screenshot_bytes = api_result["screenshot_bytes"]

                # Generate filename and save locally
                domain = urlparse(url).netloc.replace("www.", "").replace(".", "_")
                import uuid as uuid_module
                filename = f"{domain}_{uuid_module.uuid4().hex[:8]}.png"
                screenshot_path = SCREENSHOT_DIR / filename

                with open(screenshot_path, "wb") as f:
                    f.write(screenshot_bytes)

                print(f"[Screenshot] Fallback captured: {screenshot_path} ({len(screenshot_bytes)} bytes)")

                # Upload to MinIO
                storage_url = None
                storage_thumbnail = None
                if SCREENSHOT_MINIO_AVAILABLE:
                    storage_result = upload_screenshot_to_storage(
                        screenshot_bytes=screenshot_bytes,
                        filename=filename
                    )
                    if storage_result.get("success"):
                        storage_url = storage_result.get("secure_url")
                        storage_thumbnail = storage_result.get("thumbnail_url")

                return {
                    "success": True,
                    "screenshot_path": str(screenshot_path),
                    "screenshot_filename": filename,
                    "screenshot_base64": base64.b64encode(screenshot_bytes).decode("utf-8"),
                    "screenshot_url": storage_url,
                    "thumbnail_url": storage_thumbnail,
                    "width": 1920,
                    "height": 1080,
                    "full_page": full_page,
                    "url": url,
                    "fallback_used": "screenshotone"
                }

        print(f"[Screenshot] All methods failed for {url}")
        return {
            "success": False,
            "error": str(e),
            "url": url
        }


def capture_homepage_screenshot_sync(url: str, full_page: bool = False) -> Dict[str, Any]:
    """
    Synchronous wrapper for capture_homepage_screenshot.
    Always uses a new thread to avoid event loop conflicts with FastAPI/nest_asyncio.
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(
            asyncio.run,
            capture_homepage_screenshot(url, full_page)
        )
        return future.result(timeout=90)


async def capture_website_screenshots(url: str, full_page: bool = False) -> Dict[str, Any]:
    """
    Capture screenshots of multiple pages on a website.

    Args:
        url: The base website URL
        full_page: If True, captures the full scrollable page. If False, captures viewport only.

    Returns:
        Dict with screenshots list containing data for each captured page
    """
    if not PLAYWRIGHT_AVAILABLE:
        return {
            "success": False,
            "error": "Playwright not installed. Run: pip install playwright && playwright install chromium"
        }

    # Normalize URL
    base_url = url.rstrip('/')
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url

    # Pages to capture (same as Tavily extraction)
    pages_to_capture = [
        {"path": "", "name": "homepage"},
        {"path": "/about", "name": "about"},
        {"path": "/about-us", "name": "about_us"},
        {"path": "/contact", "name": "contact"},
        {"path": "/contact-us", "name": "contact_us"},
        {"path": "/services", "name": "services"},
        {"path": "/products", "name": "products"},
    ]

    screenshots = []

    try:
        async with async_playwright() as p:
            # Try to find system Chrome installation
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ]

            executable_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    executable_path = path
                    print(f"[Screenshot] Using system Chrome: {path}")
                    break

            # Launch headless browser
            launch_options = {"headless": True}
            if executable_path:
                launch_options["executable_path"] = executable_path
                browser = await p.chromium.launch(**launch_options)
            else:
                browser = await p.chromium.launch(headless=True)

            # Create context with desktop viewport
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            page = await context.new_page()
            domain = urlparse(base_url).netloc.replace("www.", "").replace(".", "_")

            for page_info in pages_to_capture:
                page_url = base_url + page_info["path"]
                page_name = page_info["name"]

                try:
                    print(f"[Screenshot] Capturing {page_name}: {page_url}")

                    # Navigate with domcontentloaded (faster than networkidle)
                    response = await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

                    # Skip if page doesn't exist (404, etc.)
                    if response and response.status >= 400:
                        print(f"[Screenshot] Skipping {page_name}: HTTP {response.status}")
                        continue

                    # Wait for content to settle
                    await page.wait_for_timeout(2000)

                    # Generate unique filename
                    import uuid as uuid_module
                    filename = f"{domain}_{page_name}_{uuid_module.uuid4().hex[:8]}.png"
                    screenshot_path = SCREENSHOT_DIR / filename

                    # Capture screenshot
                    screenshot_bytes = await page.screenshot(
                        full_page=full_page,
                        type="png"
                    )

                    # Save to file
                    with open(screenshot_path, "wb") as f:
                        f.write(screenshot_bytes)

                    viewport_size = page.viewport_size

                    screenshots.append({
                        "success": True,
                        "page_name": page_name,
                        "page_url": page_url,
                        "screenshot_path": str(screenshot_path),
                        "screenshot_filename": filename,
                        "screenshot_base64": base64.b64encode(screenshot_bytes).decode("utf-8"),
                        "width": viewport_size["width"] if viewport_size else 1920,
                        "height": viewport_size["height"] if viewport_size else 1080,
                    })

                    print(f"[Screenshot] Captured {page_name}: {filename} ({len(screenshot_bytes)} bytes)")

                except Exception as e:
                    print(f"[Screenshot] Failed to capture {page_name}: {e}")
                    # Continue to next page even if one fails

            await browser.close()

            return {
                "success": len(screenshots) > 0,
                "screenshots": screenshots,
                "total_captured": len(screenshots),
                "base_url": base_url
            }

    except Exception as e:
        print(f"[Screenshot] Error capturing screenshots: {e}")
        return {
            "success": False,
            "error": str(e),
            "screenshots": screenshots,
            "base_url": base_url
        }


def capture_website_screenshots_sync(url: str, full_page: bool = False) -> Dict[str, Any]:
    """
    Synchronous wrapper for capture_website_screenshots.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    capture_website_screenshots(url, full_page)
                )
                return future.result(timeout=300)  # 5 min timeout for multiple pages
        else:
            return loop.run_until_complete(capture_website_screenshots(url, full_page))
    except RuntimeError:
        return asyncio.run(capture_website_screenshots(url, full_page))


# Gemini brand analysis imports
try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("[BrandAnalysis] google-genai package not installed. Run: pip install google-genai")

# Gemini API key
gemini_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")


async def analyze_brand_from_screenshot(
    screenshot_base64: str = None,
    screenshot_path: str = None,
    url: str = None
) -> Dict[str, Any]:
    """
    Analyze a website screenshot using Gemini to extract brand elements.

    Args:
        screenshot_base64: Base64-encoded screenshot image
        screenshot_path: Path to screenshot file (alternative to base64)
        url: Original website URL (for context)

    Returns:
        Dict with brand analysis including:
        - logo_description: Description of the logo
        - logo_location: Where the logo appears in the screenshot
        - primary_color: Main brand color (hex)
        - secondary_color: Secondary brand color (hex)
        - accent_color: Accent color (hex)
        - color_palette: List of all detected brand colors
        - typography_style: Description of fonts/typography
        - design_style: Overall design aesthetic
        - brand_personality: Inferred brand personality traits
        - key_visual_elements: Notable visual elements
    """
    if not GEMINI_AVAILABLE:
        return {
            "success": False,
            "error": "google-genai package not installed. Run: pip install google-genai"
        }

    if not gemini_api_key:
        return {
            "success": False,
            "error": "GOOGLE_API_KEY or GEMINI_API_KEY not configured"
        }

    # Get image bytes
    image_bytes = None
    if screenshot_base64:
        image_bytes = base64.b64decode(screenshot_base64)
    elif screenshot_path:
        try:
            with open(screenshot_path, "rb") as f:
                image_bytes = f.read()
        except Exception as e:
            return {"success": False, "error": f"Failed to read screenshot file: {e}"}

    if not image_bytes:
        return {"success": False, "error": "No screenshot provided (base64 or path required)"}

    try:
        # Initialize Gemini client
        client = genai.Client(api_key=gemini_api_key)

        # Create image part
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")

        # Build the analysis prompt
        prompt = f"""Analyze this website screenshot and extract brand elements.
{f"Website URL: {url}" if url else ""}

Please provide a detailed brand analysis in the following JSON format:
{{
    "logo_description": "Detailed description of the logo (shape, text, imagery)",
    "logo_location": "Where the logo appears (e.g., 'top-left header', 'center hero')",
    "logo_colors": ["#hex1", "#hex2"],
    "primary_color": "#hex - The main brand color used prominently",
    "secondary_color": "#hex - The secondary supporting color",
    "accent_color": "#hex - Color used for CTAs, highlights",
    "background_color": "#hex - Main background color",
    "text_color": "#hex - Primary text color",
    "color_palette": ["#hex1", "#hex2", "#hex3", "#hex4", "#hex5"],
    "typography_style": "Description of font styles (modern sans-serif, classic serif, etc.)",
    "heading_style": "How headings appear (bold, light, uppercase, etc.)",
    "design_style": "Overall aesthetic (minimalist, corporate, playful, luxury, etc.)",
    "brand_personality": ["trait1", "trait2", "trait3"],
    "industry_guess": "What industry/business type this appears to be",
    "key_visual_elements": ["element1", "element2", "element3"],
    "layout_style": "Description of the layout (hero-centric, grid-based, etc.)",
    "call_to_action_style": "How CTAs are styled (button colors, shapes)"
}}

IMPORTANT:
- Return ONLY valid JSON, no markdown or explanation
- All colors must be in hex format (#RRGGBB)
- Be specific about colors - extract actual colors from the screenshot
- If you cannot determine something, use null"""

        # Call Gemini API
        print(f"[BrandAnalysis] Analyzing screenshot with Gemini...")
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[image_part, prompt]
        )

        # Parse the response
        response_text = response.text.strip()

        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        response_text = response_text.strip()

        # Parse JSON
        try:
            brand_data = json.loads(response_text)
            print(f"[BrandAnalysis] Successfully extracted brand data")
            return {
                "success": True,
                "brand_analysis": brand_data,
                "url": url
            }
        except json.JSONDecodeError as e:
            print(f"[BrandAnalysis] Failed to parse JSON response: {e}")
            print(f"[BrandAnalysis] Raw response: {response_text[:500]}")
            return {
                "success": False,
                "error": f"Failed to parse Gemini response as JSON: {e}",
                "raw_response": response_text
            }

    except Exception as e:
        print(f"[BrandAnalysis] Error analyzing screenshot: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def analyze_brand_from_screenshot_sync(
    screenshot_base64: str = None,
    screenshot_path: str = None,
    url: str = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for analyze_brand_from_screenshot.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    analyze_brand_from_screenshot(screenshot_base64, screenshot_path, url)
                )
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(
                analyze_brand_from_screenshot(screenshot_base64, screenshot_path, url)
            )
    except RuntimeError:
        return asyncio.run(
            analyze_brand_from_screenshot(screenshot_base64, screenshot_path, url)
        )


def extract_store_info_from_website(url: str, capture_screenshot: bool = True, analyze_brand: bool = True) -> Dict[str, Any]:
    """
    Scrape a website using Tavily and extract store information using an AI agent.
    Also extracts and analyzes images (logos, product images) using OpenAI Vision.
    """

    # Validate API keys
    if not tavily_api_key or tavily_api_key == "your-tavily-api-key-here":
        raise ValueError("TAVILY_API_KEY not configured. Please add your Tavily API key to .env")

    if not (openai_api_key or OPENROUTER_API_KEY):
        raise ValueError("OPENAI_API_KEY not configured")

    try:
        # Initialize Tavily client
        tavily = TavilyClient(api_key=tavily_api_key)

        # Extract base URL and domain
        base_url = url.rstrip('/')
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        domain = base_url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

        # Capture screenshots of multiple pages
        screenshots_data = None
        brand_analysis_data = None
        if capture_screenshot:
            print(f"[Screenshot] Capturing website screenshots for {base_url}")
            screenshots_data = capture_website_screenshots_sync(base_url, full_page=False)
            if screenshots_data.get("success"):
                print(f"[Screenshot] Successfully captured {screenshots_data.get('total_captured')} pages")

                # Run brand analysis on the homepage screenshot using Gemini
                if analyze_brand and screenshots_data.get("screenshots"):
                    # Find homepage screenshot for brand analysis
                    homepage_screenshot = next(
                        (s for s in screenshots_data["screenshots"] if s.get("page_name") == "homepage"),
                        screenshots_data["screenshots"][0] if screenshots_data["screenshots"] else None
                    )
                    if homepage_screenshot:
                        print(f"[BrandAnalysis] Running Gemini brand analysis on homepage screenshot...")
                        brand_analysis_data = analyze_brand_from_screenshot_sync(
                            screenshot_base64=homepage_screenshot.get("screenshot_base64"),
                            url=base_url
                        )
                        if brand_analysis_data.get("success"):
                            print(f"[BrandAnalysis] Successfully extracted brand data")
                        else:
                            print(f"[BrandAnalysis] Failed: {brand_analysis_data.get('error')}")
            else:
                print(f"[Screenshot] Failed: {screenshots_data.get('error')}")

        # Build list of URLs to extract (main page + common pages + product/pricing pages)
        urls_to_extract = [base_url]
        common_pages = [
            '/contact', '/contact-us',
            '/about', '/about-us',
            '/services', '/products', '/pricing', '/plans',  # Product/pricing pages
            '/packages', '/solutions', '/offerings',  # Alternative product pages
        ]
        for page in common_pages:
            urls_to_extract.append(base_url + page)

        all_content = []

        # Store extracted images from Tavily
        tavily_images = []

        # Method 1: Direct page extraction with Tavily (with images)
        print(f"[Tavily] Extracting pages with images: {urls_to_extract}")
        try:
            extract_result = tavily.extract(urls=urls_to_extract, include_images=True)
            if extract_result and extract_result.get("results"):
                for result in extract_result["results"]:
                    content = result.get("raw_content", "")
                    result_url = result.get("url", "")
                    images = result.get("images", [])

                    if content:
                        page_type = "MAIN PAGE" if result_url == base_url else "ADDITIONAL PAGE"
                        all_content.append(f"=== {page_type}: {result_url} ===\n{content}")
                        print(f"[Tavily] Extracted {result_url}: {len(content)} characters, {len(images)} images")

                    # Collect images from Tavily
                    if images:
                        tavily_images.extend(images)
                        print(f"[Tavily] Found images: {images[:3]}...")  # Log first 3
        except Exception as e:
            print(f"[Tavily] Extraction failed: {e}")

        # Method 2: If direct extraction failed, try search (but filter by domain)
        if not all_content:
            print(f"[Tavily] Direct extraction failed, trying search for {domain}")
            try:
                search_result = tavily.search(
                    query=f"{domain} contact about services products",
                    search_depth="advanced",
                    include_raw_content=True,
                    max_results=5,
                    include_domains=[domain]
                )

                for result in search_result.get("results", []):
                    result_url = result.get("url", "")
                    if domain in result_url:
                        content = result.get("raw_content") or result.get("content", "")
                        if content:
                            all_content.append(f"=== PAGE: {result_url} ===\n{content}")
                            print(f"[Tavily] Search found {result_url}: {len(content)} characters")
            except Exception as e:
                print(f"[Tavily] Search failed: {e}")

        # Extract images - use Tavily images if available, otherwise scrape
        if tavily_images:
            print(f"[Images] Using {len(tavily_images)} images from Tavily Extract API")
            images_data = _process_tavily_images(tavily_images, base_url)
        else:
            print(f"[Images] No Tavily images, extracting from {base_url}")
            images_data = _extract_images_from_website(base_url)

        # Extract brand colors from CSS
        print(f"[Colors] Extracting brand colors from {base_url}")
        colors_data = _extract_brand_colors_from_css(base_url)

        # Analyze images with OpenAI Vision
        image_analysis = None
        if images_data.get("logo_url") or images_data.get("og_image") or images_data.get("images"):
            print(f"[Vision] Analyzing images with OpenAI Vision")
            image_analysis = _analyze_images_with_vision(images_data, domain)

        # Combine all content
        combined_content = "\n\n".join(all_content)
        print(f"[Tavily] Total combined content: {len(combined_content)} characters")

        if not combined_content:
            print("[Tavily] No content extracted, using fallback")
            fallback = _generate_fallback_data(url)
            # Add image data if available
            if images_data.get("logo_url"):
                fallback["logo_url"] = images_data["logo_url"]
            return fallback

        # Use OpenAI to extract structured store information
        store_data = _extract_with_ai_agent(combined_content, url, image_analysis)

        # Add logo URL if found
        if images_data.get("logo_url"):
            store_data["logo_url"] = images_data["logo_url"]

        # Add extracted images
        if images_data.get("images"):
            store_data["extracted_images"] = images_data["images"][:10]  # Limit to 10 images

        # Add brand colors - PRIORITIZE Vision-extracted colors from logo over CSS
        # Vision colors are more accurate as they come directly from the logo image
        if image_analysis and image_analysis.get("brand_colors"):
            # Use first color from Vision analysis (extracted from logo)
            vision_color = image_analysis["brand_colors"][0]
            store_data["brand_color"] = vision_color
            store_data["brand_color_source"] = "logo (vision)"
            print(f"[Colors] Using Vision-extracted brand color from logo: {vision_color}")
        elif colors_data.get("primary_color"):
            # Fallback to CSS-extracted color
            store_data["brand_color"] = colors_data["primary_color"]
            store_data["brand_color_source"] = colors_data.get("source", "unknown")
            print(f"[Colors] Using CSS-extracted brand color: {colors_data['primary_color']} (from {colors_data.get('source')})")
        if colors_data.get("all_colors"):
            store_data["all_brand_colors"] = colors_data["all_colors"]

        # Also fetch raw HTML for better contact extraction (Tavily may miss footer/contact sections)
        try:
            print(f"[Contact] Fetching raw HTML for contact extraction...")
            print(f"[Contact] Current email: {store_data.get('store_email')}, phone: {store_data.get('store_phone')}")
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

            # Fetch main page and contact page
            urls_to_fetch = [base_url, base_url + '/contact', base_url + '/contact-us']
            all_html = ""

            for fetch_url in urls_to_fetch:
                try:
                    raw_response = requests.get(fetch_url, headers=headers, timeout=10, allow_redirects=True)
                    if raw_response.status_code == 200:
                        all_html += raw_response.text + "\n"
                        print(f"[Contact] Fetched {fetch_url}: {len(raw_response.text)} chars")
                    else:
                        print(f"[Contact] Failed to fetch {fetch_url}: status {raw_response.status_code}")
                except Exception as fetch_error:
                    print(f"[Contact] Error fetching {fetch_url}: {fetch_error}")

            if all_html:
                # Extract contact info directly from raw HTML
                direct_contact = _extract_contact_info_directly(all_html, domain)
                print(f"[Contact] Direct extraction result: email={direct_contact.get('email')}, phone={direct_contact.get('phone')}")

                if direct_contact.get("email"):
                    store_data["store_email"] = direct_contact["email"]
                    print(f"[Contact] SET email from raw HTML: {direct_contact['email']}")
                if direct_contact.get("phone"):
                    store_data["store_phone"] = direct_contact["phone"]
                    print(f"[Contact] SET phone from raw HTML: {direct_contact['phone']}")
        except Exception as e:
            print(f"[Contact] Error fetching raw HTML: {e}")

        # Extract FAQs from the scraped content
        print(f"[FAQ] Extracting FAQs from scraped content...")
        faqs = _extract_faqs_with_ai(combined_content, url)
        store_data["faqs"] = faqs

        # Extract products/services with prices (dedicated extraction)
        print(f"[Products] Extracting products/services with prices...")
        products_data = _extract_products_services_with_prices(combined_content, url)
        store_data["products"] = products_data.get("products", [])
        store_data["services"] = products_data.get("services", [])
        store_data["pricing_tiers"] = products_data.get("pricing_tiers", [])
        store_data["detected_industry"] = products_data.get("industry", "general")
        store_data["target_market"] = products_data.get("target_market", "")

        # Add screenshot data for brand analysis by AI agent
        if screenshots_data and screenshots_data.get("success"):
            # Add all screenshots
            store_data["screenshots"] = [
                {
                    "page_name": s.get("page_name"),
                    "page_url": s.get("page_url"),
                    "path": s.get("screenshot_path"),
                    "filename": s.get("screenshot_filename"),
                    "base64": s.get("screenshot_base64"),
                    "width": s.get("width"),
                    "height": s.get("height"),
                }
                for s in screenshots_data.get("screenshots", [])
            ]
            # Also keep homepage_screenshot for backwards compatibility
            homepage = next(
                (s for s in screenshots_data.get("screenshots", []) if s.get("page_name") == "homepage"),
                screenshots_data.get("screenshots", [None])[0]
            )
            if homepage:
                store_data["homepage_screenshot"] = {
                    "path": homepage.get("screenshot_path"),
                    "filename": homepage.get("screenshot_filename"),
                    "base64": homepage.get("screenshot_base64"),
                    "width": homepage.get("width"),
                    "height": homepage.get("height"),
                    "url": homepage.get("page_url")
                }
            print(f"[Screenshot] Added {len(store_data['screenshots'])} screenshots to store_data")

        # Add Gemini brand analysis results
        if brand_analysis_data and brand_analysis_data.get("success"):
            brand = brand_analysis_data.get("brand_analysis", {})
            store_data["brand_analysis"] = brand

            # Use Gemini-extracted colors if available (override CSS-extracted colors)
            if brand.get("primary_color"):
                store_data["brand_color"] = brand["primary_color"]
                store_data["brand_color_source"] = "gemini_screenshot_analysis"
                print(f"[BrandAnalysis] Using Gemini-extracted primary color: {brand['primary_color']}")

            if brand.get("color_palette"):
                store_data["all_brand_colors"] = [
                    {"color": c, "source": "gemini_screenshot_analysis"}
                    for c in brand["color_palette"]
                ]

            # Use Gemini-detected business type if available
            if brand.get("industry_guess"):
                store_data["detected_industry"] = brand["industry_guess"]

            print(f"[BrandAnalysis] Brand analysis added to store_data")

        return store_data

    except Exception as e:
        print(f"[Scraping] Error: {str(e)}")
        return _generate_fallback_data(url)


def _process_tavily_images(tavily_images: List[str], base_url: str) -> Dict[str, Any]:
    """
    Process images returned by Tavily Extract API.
    Identify logos and organize image data.
    """
    images_data = {
        "logo_url": None,
        "favicon_url": None,
        "images": [],
        "og_image": None
    }

    for img_url in tavily_images:
        if not img_url:
            continue

        # Make URL absolute if needed
        if not img_url.startswith('http'):
            img_url = urljoin(base_url, img_url)

        # Skip data URIs, tiny images, tracking pixels
        if (img_url.startswith('data:') or
            'pixel' in img_url.lower() or
            'tracking' in img_url.lower() or
            'spacer' in img_url.lower() or
            '1x1' in img_url.lower()):
            continue

        # Check if this is likely a logo
        is_logo = 'logo' in img_url.lower()

        # Set logo_url if we find one
        if is_logo and not images_data["logo_url"]:
            images_data["logo_url"] = img_url
            print(f"[Images] Identified logo from Tavily: {img_url}")

        # Check for OG image patterns
        if ('og-image' in img_url.lower() or 'opengraph' in img_url.lower() or
            'social' in img_url.lower()) and not images_data["og_image"]:
            images_data["og_image"] = img_url

        # Add to general images list
        images_data["images"].append({
            "url": img_url,
            "alt": "",
            "is_logo": is_logo
        })

    # If no logo found, try first image that might be header/hero
    if not images_data["logo_url"] and images_data["images"]:
        for img in images_data["images"]:
            url_lower = img["url"].lower()
            if any(kw in url_lower for kw in ['header', 'hero', 'brand', 'banner']):
                images_data["og_image"] = img["url"]
                break

    print(f"[Images] Processed {len(images_data['images'])} Tavily images, logo: {images_data['logo_url']}")
    return images_data


def _extract_brand_colors_from_css(url: str) -> Dict[str, Any]:
    """
    Extract brand colors from website CSS.
    Looks for:
    - CSS variables (--primary-color, --brand-color, etc.)
    - Common color selectors (.brand, .primary, header, nav)
    - Inline styles on key elements
    - Meta theme-color tag
    """
    colors_data = {
        "primary_color": None,
        "secondary_color": None,
        "accent_color": None,
        "all_colors": [],
        "source": None
    }

    try:
        base_url = url.rstrip('/')
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(base_url, headers=headers, timeout=15)

        if response.status_code != 200:
            print(f"[Colors] Failed to fetch {base_url}: {response.status_code}")
            return colors_data

        html = response.text
        soup = BeautifulSoup(html, 'html.parser')

        # Method 1: Meta theme-color tag
        theme_meta = soup.find('meta', attrs={'name': 'theme-color'})
        if theme_meta and theme_meta.get('content'):
            color = theme_meta.get('content')
            colors_data["primary_color"] = color
            colors_data["source"] = "meta theme-color"
            colors_data["all_colors"].append({"color": color, "source": "meta theme-color"})
            print(f"[Colors] Found theme-color meta: {color}")

        # Method 2: Extract inline styles from key elements
        key_selectors = ['header', 'nav', '.navbar', '.header', '.brand', '.logo', 'a.brand']
        for selector in key_selectors:
            try:
                elements = soup.select(selector)
                for el in elements:
                    style = el.get('style', '')
                    if style:
                        # Extract colors from inline style
                        color_matches = re.findall(r'(?:background-color|color|border-color)\s*:\s*(#[0-9a-fA-F]{3,6}|rgb[a]?\([^)]+\))', style)
                        for color in color_matches:
                            colors_data["all_colors"].append({"color": color, "source": f"inline style on {selector}"})
                            if not colors_data["primary_color"]:
                                colors_data["primary_color"] = color
                                colors_data["source"] = f"inline style on {selector}"
                                print(f"[Colors] Found color from {selector}: {color}")
            except Exception:
                pass

        # Method 3: Extract from <style> tags
        style_tags = soup.find_all('style')
        css_content = ""
        for style_tag in style_tags:
            if style_tag.string:
                css_content += style_tag.string + "\n"

        # Method 4: Fetch external CSS files
        css_links = soup.find_all('link', rel='stylesheet')
        for link in css_links[:5]:  # Limit to first 5 CSS files
            href = link.get('href')
            if href:
                if not href.startswith('http'):
                    href = urljoin(base_url, href)
                try:
                    css_response = requests.get(href, headers=headers, timeout=10)
                    if css_response.status_code == 200:
                        css_content += css_response.text + "\n"
                        print(f"[Colors] Fetched CSS: {href[:50]}...")
                except Exception as e:
                    print(f"[Colors] Failed to fetch CSS {href}: {e}")

        if css_content:
            # Extract CSS variables - including WordPress preset patterns
            # WordPress uses patterns like: --wp--preset--color--gold: #FFC000
            css_var_patterns_with_names = [
                # WordPress preset colors (highest priority - these are intentionally set)
                r'--wp--preset--color--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})',
                # Custom color variables
                r'--color-([a-z-]+):\s*(#[0-9a-fA-F]{3,6})',
            ]

            css_var_patterns_simple = [
                # Standard naming patterns (no name capture)
                r'--primary[-_]?color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'--brand[-_]?color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'--main[-_]?color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'--accent[-_]?color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'--theme[-_]?color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'--primary[^:]*:\s*(#[0-9a-fA-F]{3,6})',
                r'--brand[^:]*:\s*(#[0-9a-fA-F]{3,6})',
            ]

            # Generic color names to skip
            generic_color_names = {'black', 'white', 'gray', 'grey', 'light-gray', 'medium-gray', 'dark-gray'}

            # WordPress default preset color names to skip (these appear on EVERY WordPress site)
            wordpress_preset_names = {
                'cyan-bluish-gray', 'pale-pink', 'vivid-red', 'luminous-vivid-orange',
                'luminous-vivid-amber', 'light-green-cyan', 'vivid-green-cyan',
                'pale-cyan-blue', 'vivid-cyan-blue', 'vivid-purple',
                '-black', '-white', '-cyan-bluish-gray', '-pale-pink', '-vivid-red',
                '-luminous-vivid-orange', '-luminous-vivid-amber', '-light-green-cyan',
                '-vivid-green-cyan', '-pale-cyan-blue', '-vivid-cyan-blue', '-vivid-purple'
            }

            # Priority color names (brand-like)
            priority_color_names = {'gold', 'primary', 'brand', 'main', 'accent', 'highlight', 'secondary'}

            # Process patterns that capture color names (WordPress, custom)
            for pattern in css_var_patterns_with_names:
                matches = re.findall(pattern, css_content, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple) and len(match) == 2:
                        name, color = match[0].lower(), match[1]
                        # Skip generic color names and WordPress default presets
                        if name in generic_color_names or name in wordpress_preset_names:
                            print(f"[Colors] Skipping WordPress/generic preset '{name}': {color}")
                            continue
                        color = color.upper()
                        # Prioritize brand-like color names
                        if name in priority_color_names:
                            print(f"[Colors] Found priority CSS variable '{name}': {color}")
                            colors_data["all_colors"].insert(0, {"color": color, "source": f"CSS variable ({name})"})
                            if not colors_data["primary_color"]:
                                colors_data["primary_color"] = color
                                colors_data["source"] = f"CSS variable ({name})"
                        else:
                            colors_data["all_colors"].append({"color": color, "source": f"CSS variable ({name})"})
                            print(f"[Colors] Found CSS variable '{name}': {color}")

            # Generic colors to skip when setting primary (check early)
            # Includes black, white, grays, Bootstrap, and WordPress preset colors
            early_skip_colors = {
                '#000', '#000000', '#fff', '#ffffff', '#333', '#333333',
                '#666', '#666666', '#999', '#999999', '#ccc', '#cccccc',
                '#f5f5f5', '#f7f7f7', '#fafafa', '#eee', '#eeeeee',
                '#e5e5e5', '#d4d4d4', '#f0f0f0',  # More grays
                # Bootstrap colors (primary, hover, active states)
                '#007bff', '#0069d9', '#0062cc', '#0056b3',  # Bootstrap blue
                '#6c757d', '#5a6268', '#545b62',  # Bootstrap gray
                '#28a745', '#218838', '#1e7e34',  # Bootstrap green
                '#dc3545', '#c82333', '#bd2130',  # Bootstrap red
                '#ffc107', '#e0a800', '#d39e00',  # Bootstrap yellow
                '#17a2b8', '#138496', '#117a8b',  # Bootstrap cyan
                '#343a40', '#23272b', '#1d2124',  # Bootstrap dark
                '#f8f9fa', '#e2e6ea', '#dae0e5', '#212529',  # Bootstrap light/dark
                # WordPress default preset colors (appear on every WP site)
                '#abb8c3',  # cyan-bluish-gray
                '#f78da7',  # pale-pink
                '#cf2e2e',  # vivid-red
                '#ff6900',  # luminous-vivid-orange
                '#fcb900',  # luminous-vivid-amber
                '#7bdcb5',  # light-green-cyan
                '#00d084',  # vivid-green-cyan
                '#8ed1fc',  # pale-cyan-blue
                '#0693e3',  # vivid-cyan-blue
                '#9b51e0',  # vivid-purple
            }

            # Process simple patterns (no name capture)
            for pattern in css_var_patterns_simple:
                matches = re.findall(pattern, css_content, re.IGNORECASE)
                for color in matches:
                    color = color.upper() if isinstance(color, str) else color
                    color_lower = color.lower()
                    # Skip generic/framework colors
                    if color_lower in early_skip_colors:
                        print(f"[Colors] Skipping generic color: {color}")
                        continue
                    colors_data["all_colors"].append({"color": color, "source": "CSS variable"})
                    if not colors_data["primary_color"]:
                        colors_data["primary_color"] = color
                        colors_data["source"] = "CSS variable"
                        print(f"[Colors] Found CSS variable color: {color}")

            # Extract colors from common class selectors
            common_patterns = [
                r'\.brand[^{]*\{[^}]*(?:background-color|color)\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'\.primary[^{]*\{[^}]*(?:background-color|color)\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'header[^{]*\{[^}]*background-color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'\.navbar[^{]*\{[^}]*background-color\s*:\s*(#[0-9a-fA-F]{3,6})',
                r'\.btn-primary[^{]*\{[^}]*background-color\s*:\s*(#[0-9a-fA-F]{3,6})',
            ]

            for pattern in common_patterns:
                matches = re.findall(pattern, css_content, re.IGNORECASE | re.DOTALL)
                for color in matches:
                    color_lower = color.lower()
                    # Skip generic/framework colors
                    if color_lower in early_skip_colors:
                        print(f"[Colors] Skipping generic selector color: {color}")
                        continue
                    colors_data["all_colors"].append({"color": color, "source": "CSS selector"})
                    if not colors_data["primary_color"]:
                        colors_data["primary_color"] = color
                        colors_data["source"] = "CSS selector"
                        print(f"[Colors] Found CSS selector color: {color}")

        # Filter out common framework/generic colors
        generic_colors = {
            '#000', '#000000', '#fff', '#ffffff', '#333', '#333333',
            '#666', '#666666', '#999', '#999999', '#ccc', '#cccccc',
            '#f5f5f5', '#f7f7f7', '#fafafa', '#eee', '#eeeeee',
            '#007bff', '#0069d9', '#0062cc',  # Bootstrap blue
            '#28a745', '#218838', '#1e7e34',  # Bootstrap green
            '#dc3545', '#c82333', '#bd2130',  # Bootstrap red
            '#ffc107', '#e0a800', '#d39e00',  # Bootstrap yellow
            '#17a2b8', '#138496', '#117a8b',  # Bootstrap cyan
            '#6c757d', '#5a6268', '#545b62',  # Bootstrap gray
        }

        # Remove duplicates and filter generic colors
        seen = set()
        unique_colors = []
        brand_color_candidates = []

        for c in colors_data["all_colors"]:
            color_lower = c["color"].lower()
            if color_lower not in seen and color_lower not in generic_colors:
                seen.add(color_lower)
                unique_colors.append(c)
                # Prefer colors from theme-color or CSS variables
                if c["source"] in ["meta theme-color", "CSS variable"]:
                    brand_color_candidates.insert(0, c)
                else:
                    brand_color_candidates.append(c)

        colors_data["all_colors"] = unique_colors[:10]

        # Set primary color from best candidate (prefer non-generic)
        if brand_color_candidates and not colors_data["primary_color"]:
            colors_data["primary_color"] = brand_color_candidates[0]["color"]
            colors_data["source"] = brand_color_candidates[0]["source"]
        elif unique_colors and not colors_data["primary_color"]:
            colors_data["primary_color"] = unique_colors[0]["color"]

        # Fallback: If no color found from CSS variables, analyze inline styles
        # Look for most frequently used non-generic color in HTML
        if not colors_data["primary_color"] and css_content:
            print("[Colors] No CSS variables found, analyzing inline styles for frequent colors...")
            all_hex_colors = re.findall(r'#[0-9a-fA-F]{6}', css_content)
            color_counts = {}
            for c in all_hex_colors:
                c_lower = c.lower()
                if c_lower not in generic_colors and c_lower not in early_skip_colors:
                    color_counts[c_lower] = color_counts.get(c_lower, 0) + 1

            if color_counts:
                sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
                # Only use if it appears at least 3 times (likely intentional brand color)
                if sorted_colors and sorted_colors[0][1] >= 3:
                    top_color = sorted_colors[0][0].upper()
                    print(f"[Colors] Found frequent inline color {top_color} ({sorted_colors[0][1]} times)")
                    colors_data["primary_color"] = top_color
                    colors_data["source"] = "inline style (frequent)"
                    colors_data["all_colors"].insert(0, {"color": top_color, "source": "inline style (frequent)"})

        print(f"[Colors] Extracted {len(colors_data['all_colors'])} unique brand colors, primary: {colors_data['primary_color']}")
        return colors_data

    except Exception as e:
        print(f"[Colors] Error extracting colors: {e}")
        return colors_data


def _extract_images_from_spa_bundle(url: str, soup: BeautifulSoup) -> List[str]:
    """
    Extract images from SPA JavaScript bundles (React, Vue, Angular, etc.).
    Detects if site is SPA and parses JS bundles for image URLs.
    """
    images = []
    base_url = url.rstrip('/')

    try:
        # Find all script tags with src
        scripts = soup.find_all('script', src=True)

        for script in scripts:
            src = script.get('src', '')
            if not src:
                continue

            # Look for main bundle files (common patterns)
            if any(pattern in src.lower() for pattern in [
                'main', 'index', 'app', 'bundle', 'chunk', 'vendor'
            ]) and src.endswith('.js'):

                # Make URL absolute
                if not src.startswith('http'):
                    script_url = urljoin(base_url, src)
                else:
                    script_url = src

                print(f"[SPA] Fetching JS bundle: {script_url}")

                try:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    js_response = requests.get(script_url, headers=headers, timeout=15)

                    if js_response.status_code == 200:
                        js_content = js_response.text

                        # Extract image URLs from JS bundle
                        # Pattern 1: Full URLs
                        url_pattern = r'https?://[^\s"\'\\<>]+\.(?:png|jpg|jpeg|webp|svg|gif)'
                        found_urls = re.findall(url_pattern, js_content, re.IGNORECASE)

                        # Pattern 2: Relative paths in quotes
                        relative_pattern = r'["\']([^"\']+\.(?:png|jpg|jpeg|webp|svg|gif))["\']'
                        relative_urls = re.findall(relative_pattern, js_content, re.IGNORECASE)

                        for img_url in found_urls:
                            # Clean up URL (remove trailing quotes, etc.)
                            img_url = img_url.rstrip('"\',);')
                            if img_url and len(img_url) < 500:  # Sanity check
                                images.append(img_url)

                        for rel_url in relative_urls:
                            if rel_url.startswith('/') or rel_url.startswith('./'):
                                full_url = urljoin(base_url, rel_url)
                                images.append(full_url)
                            elif rel_url.startswith('http'):
                                images.append(rel_url)

                        print(f"[SPA] Found {len(images)} images in JS bundle")

                except Exception as e:
                    print(f"[SPA] Error fetching JS bundle: {e}")

        # Remove duplicates while preserving order
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)

        return unique_images[:50]  # Limit to 50 images

    except Exception as e:
        print(f"[SPA] Error extracting from bundle: {e}")
        return []


def _is_spa_website(soup: BeautifulSoup) -> bool:
    """
    Detect if a website is a Single Page Application (React, Vue, Angular, etc.).
    """
    # Check for common SPA root elements
    root_div = soup.find('div', id='root')  # React
    app_div = soup.find('div', id='app')    # Vue
    ng_app = soup.find(attrs={'ng-app': True})  # Angular

    # Check if body has minimal content (typical of SPAs)
    body = soup.find('body')
    if body:
        # Count actual content elements (not scripts)
        content_elements = body.find_all(['p', 'h1', 'h2', 'h3', 'img', 'article', 'section'])
        img_tags = body.find_all('img')

        # SPA indicators:
        # 1. Has root/app div
        # 2. Very few content elements
        # 3. No img tags in HTML
        if (root_div or app_div or ng_app) and len(content_elements) < 3 and len(img_tags) == 0:
            return True

    return False


def _extract_images_from_website(url: str) -> Dict[str, Any]:
    """
    Extract images from a website, focusing on logos and brand images.
    Handles both traditional websites and SPAs.
    """
    images_data = {
        "logo_url": None,
        "favicon_url": None,
        "images": [],
        "og_image": None
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'lxml')
        base_url = url.rstrip('/')

        # Check if this is a SPA
        is_spa = _is_spa_website(soup)
        if is_spa:
            print(f"[Images] Detected SPA website, parsing JS bundles...")
            spa_images = _extract_images_from_spa_bundle(url, soup)

            if spa_images:
                # Process SPA images
                for img_url in spa_images:
                    # Skip tracking pixels and tiny images
                    if any(skip in img_url.lower() for skip in ['pixel', 'tracking', '1x1', 'spacer', '.gif']):
                        continue

                    is_logo = 'logo' in img_url.lower()

                    # Set logo if found
                    if is_logo and not images_data["logo_url"]:
                        images_data["logo_url"] = img_url
                        print(f"[SPA] Found logo: {img_url}")

                    # First image from same domain could be hero/brand image
                    domain = urlparse(url).netloc.replace('www.', '')
                    if not images_data["og_image"]:
                        # Prioritize images from asset CDNs or same domain
                        if 'assets' in img_url.lower() or domain in img_url:
                            images_data["og_image"] = img_url

                    images_data["images"].append({
                        "url": img_url,
                        "alt": "",
                        "is_logo": is_logo
                    })

                # If no logo found, use first asset image as potential brand image
                if not images_data["logo_url"] and not images_data["og_image"] and images_data["images"]:
                    images_data["og_image"] = images_data["images"][0]["url"]

                print(f"[SPA] Extracted {len(images_data['images'])} images, logo: {images_data['logo_url']}")
                return images_data

        # 1. Find Open Graph image (usually a good brand image)
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            og_url = og_image['content']
            if not og_url.startswith('http'):
                og_url = urljoin(base_url, og_url)
            images_data["og_image"] = og_url
            print(f"[Images] Found OG image: {og_url}")

        # 2. Find favicon (prefer largest available)
        favicon = soup.find('link', rel=lambda x: x and 'icon' in x.lower() if x else False)
        if favicon and favicon.get('href'):
            fav_url = favicon['href']
            if not fav_url.startswith('http'):
                fav_url = urljoin(base_url, fav_url)
            images_data["favicon_url"] = fav_url

        # 2b. Find apple-touch-icon or high-res icons (great logo fallback, typically 180x180+)
        hi_res_icon_url = None
        icon_links = soup.find_all('link', rel=lambda x: x and ('apple-touch-icon' in ' '.join(x).lower() if isinstance(x, list) else 'apple-touch-icon' in x.lower()) if x else False)
        if not icon_links:
            # Also check for large icon sizes
            icon_links = soup.find_all('link', rel=lambda x: x and ('icon' in ' '.join(x).lower() if isinstance(x, list) else 'icon' in x.lower()) if x else False)
        # Pick the largest icon
        best_size = 0
        for link in icon_links:
            href = link.get('href')
            if not href:
                continue
            sizes = link.get('sizes', '')
            if sizes and 'x' in sizes.lower():
                try:
                    w = int(sizes.lower().split('x')[0])
                    if w > best_size:
                        best_size = w
                        hi_res_icon_url = href
                except (ValueError, IndexError):
                    pass
            elif not hi_res_icon_url and 'apple-touch-icon' in str(link.get('rel', '')).lower():
                # apple-touch-icon without sizes is typically 180x180
                hi_res_icon_url = href
                best_size = 180
        if hi_res_icon_url and not hi_res_icon_url.startswith('http'):
            hi_res_icon_url = urljoin(base_url, hi_res_icon_url)
        if hi_res_icon_url:
            print(f"[Images] Found high-res icon ({best_size}px): {hi_res_icon_url}")

        # 3. Find logo - look for common patterns
        logo_selectors = [
            # By class/id containing 'logo'
            lambda: soup.find('img', class_=lambda x: x and 'logo' in x.lower() if x else False),
            lambda: soup.find('img', id=lambda x: x and 'logo' in x.lower() if x else False),
            # By src containing 'logo'
            lambda: soup.find('img', src=lambda x: x and 'logo' in x.lower() if x else False),
            # By alt containing 'logo'
            lambda: soup.find('img', alt=lambda x: x and 'logo' in x.lower() if x else False),
            # WordPress custom-logo class (common WordPress pattern)
            lambda: soup.find('img', class_=lambda x: x and 'custom-logo' in x.lower() if x else False),
            # WordPress site-logo class
            lambda: soup.find('img', class_=lambda x: x and 'site-logo' in x.lower() if x else False),
            # In header
            lambda: soup.find('header', class_=lambda x: True).find('img') if soup.find('header') else None,
            # First image in navbar
            lambda: soup.find('nav').find('img') if soup.find('nav') else None,
            # WordPress site branding area
            lambda: soup.select_one('.site-branding img'),
            lambda: soup.select_one('.custom-logo-link img'),
            # Link with logo/brand class containing img
            lambda: soup.select_one('a[class*="logo"] img'),
            lambda: soup.select_one('a[class*="brand"] img'),
            # SVG logo
            lambda: soup.find('svg', class_=lambda x: x and 'logo' in x.lower() if x else False),
        ]

        def _get_best_img_src(img_tag):
            """Get the real image URL from an img tag, handling lazy-loading.
            Checks data-src, data-lazy-src, data-original, srcset before src.
            Skips placeholder/loader images."""
            skip_words = ['loader', 'spinner', 'placeholder', 'blank', 'spacer', 'pixel', 'loading']
            for attr in ['data-src', 'data-lazy-src', 'data-original', 'srcset', 'src']:
                val = img_tag.get(attr, '')
                if not val:
                    continue
                if attr == 'srcset' and val:
                    # Take the first (usually largest) URL from srcset
                    val = val.split(',')[0].strip().split(' ')[0]
                if val and not val.startswith('data:'):
                    if any(s in val.lower() for s in skip_words):
                        continue
                    return val
            return ''

        for selector in logo_selectors:
            try:
                logo = selector()
                if logo:
                    if logo.name == 'svg':
                        # For SVG, we might need to handle differently
                        continue
                    logo_url = _get_best_img_src(logo)
                    if logo_url:
                        if not logo_url.startswith('http'):
                            logo_url = urljoin(base_url, logo_url)
                        # Skip tiny images or data URIs
                        if not logo_url.startswith('data:') and 'pixel' not in logo_url.lower():
                            images_data["logo_url"] = logo_url
                            print(f"[Images] Found logo: {logo_url}")
                            break
            except Exception:
                continue

        # 3b. If no <img> logo found, use apple-touch-icon / high-res icon as logo
        if not images_data["logo_url"] and hi_res_icon_url:
            images_data["logo_url"] = hi_res_icon_url
            print(f"[Images] Using high-res icon as logo fallback: {hi_res_icon_url}")

        # 3c. If still no logo, try well-known icon paths
        if not images_data["logo_url"]:
            parsed = urlparse(base_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            well_known_paths = [
                "/apple-touch-icon.png",
                "/apple-touch-icon-precomposed.png",
                "/favicon-192x192.png",
                "/android-chrome-192x192.png",
                "/android-chrome-512x512.png",
            ]
            for path in well_known_paths:
                try:
                    test_url = origin + path
                    resp = requests.head(test_url, headers=headers, timeout=5, allow_redirects=True)
                    if resp.status_code == 200 and 'image' in resp.headers.get('Content-Type', ''):
                        images_data["logo_url"] = test_url
                        print(f"[Images] Found logo at well-known path: {test_url}")
                        break
                except Exception:
                    continue

        # 4. Collect other significant images (for product/brand understanding)
        all_images = soup.find_all('img')
        for img in all_images[:20]:  # Limit to first 20 images
            src = img.get('src') or img.get('data-src')
            if src:
                if not src.startswith('http'):
                    src = urljoin(base_url, src)
                # Skip data URIs, tiny images, tracking pixels
                if (not src.startswith('data:') and
                    'pixel' not in src.lower() and
                    'tracking' not in src.lower() and
                    'spacer' not in src.lower() and
                    '.gif' not in src.lower()):
                    alt = img.get('alt', '')
                    images_data["images"].append({
                        "url": src,
                        "alt": alt,
                        "is_logo": 'logo' in (alt + src).lower()
                    })

        print(f"[Images] Extracted {len(images_data['images'])} images, logo: {images_data['logo_url']}")

    except Exception as e:
        print(f"[Images] Error extracting images: {e}")

    return images_data


def _analyze_images_with_vision(images_data: Dict[str, Any], domain: str) -> Dict[str, Any]:
    """
    Analyze multiple images using OpenAI Vision to extract comprehensive brand information.
    Identifies which images contain uniforms, vehicles, equipment for use as Gemini reference images.
    """
    client = _llm_client()

    analysis_result = {
        "brand_colors": [],
        "logo_description": None,
        "logo_url": images_data.get("logo_url"),
        "brand_style": None,
        "detected_text": None,
        "uniform_description": None,
        "vehicle_description": None,
        "equipment_description": None,
        "visual_profile": None,
        "reference_images": [],  # Images to pass to Gemini with their types
        "uniform_images": [],    # Specific images showing uniforms
        "vehicle_images": [],    # Specific images showing vehicles
        "equipment_images": []   # Specific images showing equipment
    }

    # Step 1: Analyze the logo for brand colors
    logo_url = images_data.get("logo_url")
    if logo_url:
        try:
            print(f"[Vision] Analyzing logo: {logo_url}")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"""Analyze this company LOGO from {domain}. Extract:

1. **Brand Colors**: List PRIMARY colors as hex codes (e.g., #FF5733). Focus on main logo colors.
2. **Logo Description**: Describe the logo (icon, text, symbols, style).
3. **Brand Style**: What feeling does it convey? (Professional, Modern, Bold, etc.)
4. **Text Detected**: Company name visible in logo.

Return ONLY valid JSON:
{{"brand_colors": ["#hex1"], "logo_description": "...", "brand_style": "...", "detected_text": "..."}}"""
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": logo_url, "detail": "low"}
                            }
                        ]
                    }
                ],
                max_tokens=300
            )
            result_text = response.choices[0].message.content.strip()
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
                result_text = re.sub(r'\n?```$', '', result_text)
            logo_analysis = json.loads(result_text)
            analysis_result["brand_colors"] = logo_analysis.get("brand_colors", [])
            analysis_result["logo_description"] = logo_analysis.get("logo_description")
            analysis_result["brand_style"] = logo_analysis.get("brand_style")
            analysis_result["detected_text"] = logo_analysis.get("detected_text")
            analysis_result["reference_images"].append({"url": logo_url, "type": "logo"})
            print(f"[Vision] Logo colors: {analysis_result['brand_colors']}")
        except Exception as e:
            print(f"[Vision] Error analyzing logo: {e}")

    # Step 2: Analyze other images to find uniforms, vehicles, equipment
    # Filter out tracking pixels and invalid images
    invalid_patterns = [
        'facebook.com/tr', 'google-analytics.com', 'doubleclick.net',
        'pixel', 'tracking', 'beacon', '1x1', 'spacer', '.gif',
        'analytics', 'stat', 'counter', 'noscript'
    ]

    def is_valid_image(url: str) -> bool:
        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in invalid_patterns)

    other_images = [
        img for img in images_data.get("images", [])
        if img.get("url") and img["url"] != logo_url and is_valid_image(img["url"])
    ]

    # Also check OG image (if valid)
    og_image = images_data.get("og_image")
    if og_image and og_image != logo_url and is_valid_image(og_image):
        other_images.insert(0, {"url": og_image, "alt": "og_image"})

    # Analyze up to 8 images to find uniforms/vehicles/equipment
    images_to_analyze = other_images[:8]
    print(f"[Vision] Filtered to {len(images_to_analyze)} valid images (excluded tracking pixels)")

    if images_to_analyze:
        try:
            print(f"[Vision] Analyzing {len(images_to_analyze)} images for uniforms/vehicles/equipment...")

            # Build content with multiple images - numbered for identification
            image_list_text = "\n".join([f"Image {i+1}: {img['url']}" for i, img in enumerate(images_to_analyze)])

            content_parts = [
                {
                    "type": "text",
                    "text": f"""Analyze these {len(images_to_analyze)} images from {domain} company website.

IMAGE LIST:
{image_list_text}

For EACH category below, identify:
1. A detailed description of what you see
2. Which IMAGE NUMBER(s) show this (e.g., "1, 3" or "none")

Categories:

1. **UNIFORMS**: If you see employees/staff in uniforms:
   - Describe: Colors, style (polo, button-down, jacket), logos/badges
   - Which images show uniforms?

2. **VEHICLES**: If you see company vehicles:
   - Describe: Type (truck, van, sedan), colors, branding
   - Which images show vehicles?

3. **EQUIPMENT**: If you see security/business equipment:
   - Describe: Type (cameras, monitors, alarms), style
   - Which images show equipment?

4. **STAFF/PEOPLE**: If you see staff or employees:
   - Which images show staff/people?

Return ONLY valid JSON:
{{
    "uniform_description": "detailed description or null",
    "uniform_image_numbers": [1, 3] or [],
    "vehicle_description": "detailed description or null",
    "vehicle_image_numbers": [2] or [],
    "equipment_description": "detailed description or null",
    "equipment_image_numbers": [4, 5] or [],
    "staff_image_numbers": [1, 3] or [],
    "visual_profile": "overall visual style"
}}"""
                }
            ]

            for img in images_to_analyze:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": img["url"], "detail": "low"}
                })

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": content_parts}],
                max_tokens=600
            )

            result_text = response.choices[0].message.content.strip()
            if result_text.startswith("```"):
                result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
                result_text = re.sub(r'\n?```$', '', result_text)

            visual_analysis = json.loads(result_text)

            # Extract descriptions
            analysis_result["uniform_description"] = visual_analysis.get("uniform_description")
            analysis_result["vehicle_description"] = visual_analysis.get("vehicle_description")
            analysis_result["equipment_description"] = visual_analysis.get("equipment_description")
            analysis_result["visual_profile"] = visual_analysis.get("visual_profile")

            # Map image numbers to URLs and categorize
            uniform_nums = visual_analysis.get("uniform_image_numbers", [])
            vehicle_nums = visual_analysis.get("vehicle_image_numbers", [])
            equipment_nums = visual_analysis.get("equipment_image_numbers", [])
            staff_nums = visual_analysis.get("staff_image_numbers", [])

            for i, img in enumerate(images_to_analyze):
                img_num = i + 1  # 1-indexed
                img_url = img["url"]

                if img_num in uniform_nums or img_num in staff_nums:
                    analysis_result["uniform_images"].append(img_url)
                    analysis_result["reference_images"].append({"url": img_url, "type": "uniform"})
                    print(f"[Vision] Found UNIFORM image: {img_url[:60]}...")
                elif img_num in vehicle_nums:
                    analysis_result["vehicle_images"].append(img_url)
                    analysis_result["reference_images"].append({"url": img_url, "type": "vehicle"})
                    print(f"[Vision] Found VEHICLE image: {img_url[:60]}...")
                elif img_num in equipment_nums:
                    analysis_result["equipment_images"].append(img_url)
                    analysis_result["reference_images"].append({"url": img_url, "type": "equipment"})
                    print(f"[Vision] Found EQUIPMENT image: {img_url[:60]}...")
                else:
                    analysis_result["reference_images"].append({"url": img_url, "type": "scene"})

            print(f"[Vision] Uniform: {analysis_result['uniform_description']}")
            print(f"[Vision] Vehicle: {analysis_result['vehicle_description']}")
            print(f"[Vision] Equipment: {analysis_result['equipment_description']}")
            print(f"[Vision] Uniform images found: {len(analysis_result['uniform_images'])}")
            print(f"[Vision] Vehicle images found: {len(analysis_result['vehicle_images'])}")

        except Exception as e:
            print(f"[Vision] Error analyzing scene images: {e}")
            import traceback
            traceback.print_exc()

    return analysis_result



def _extract_with_ai_agent(content: str, url: str, image_analysis: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Use OpenAI to extract structured store information from website content.
    Incorporates image analysis results if available.
    """
    client = _llm_client()

    # Truncate content if too long
    if len(content) > 20000:
        content = content[:20000] + "..."

    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    # Build image analysis context
    image_context = ""
    if image_analysis:
        image_context = f"""
IMAGE ANALYSIS FROM LOGO/BRAND IMAGES:
- Brand Colors Detected: {image_analysis.get('brand_colors', 'Not detected')}
- Logo Description: {image_analysis.get('logo_description', 'Not available')}
- Brand Style: {image_analysis.get('brand_style', 'Not detected')}
- Text in Image: {image_analysis.get('detected_text', 'None')}

Use this visual analysis to inform your color_theme choice and brand understanding.
"""

    prompt = f"""You are an expert business analyst extracting store/business information from website content.

TASK: Analyze this website content and extract ALL available business information.

Website URL: {url}
Domain: {domain}
{image_context}

EXTRACT THESE FIELDS (return null only if truly not found):

1. store_name: The business name (from logo, header, title, footer, or About section)

2. store_email: Customer contact email. Look for:
   - mailto: links
   - "Contact us", "Email us", "Get in touch" sections
   - Footer contact info
   - Patterns like info@, hello@, contact@, support@, help@

3. store_phone: Customer service phone. Look for:
   - "Call us", "Phone", "Tel" labels
   - tel: links
   - Numbers in contact section or footer
   - Only use null if NO phone number appears anywhere

4. store_voice: Write 2-3 sentences describing:
   - What the business does
   - Their mission or value proposition
   - What makes them unique

5. store_tone: Analyze the website's communication style and pick ONE:
   - "friendly" = Friendly & Casual tone
   - "professional" = Professional & Formal tone
   - "luxury" = Luxury & Premium feel
   - "modern" = Modern & Trendy vibe
   - "traditional" = Traditional & Classic approach
   - "playful" = Playful & Fun personality
   - "minimalist" = Minimalist & Clean aesthetic
   - "eco_friendly" = Eco-Friendly & Sustainable focus

6. services_products: List the main products/services offered (comma-separated)
   - Look at navigation menu, product categories, services listed
   - Be specific, not generic

7. color_theme: The PRIMARY brand color as hex code
   - IMPORTANT: If brand colors were detected from image analysis above, use those!
   - Otherwise, pick a color that fits the industry
   - Common examples: Blue=#2563EB, Green=#16A34A, Red=#DC2626

8. business_type: Describe the business in 2-4 words
   - Examples: "Coffee Shop", "Athletic Apparel", "SaaS Platform"

WEBSITE CONTENT:
{content}

CRITICAL RULES:
- ONLY extract information that ACTUALLY APPEARS in the content above
- If you cannot find an email/phone, use null - DO NOT INVENT ONE
- For color_theme: PRIORITIZE colors from image analysis if provided
- Return ONLY valid JSON, no markdown or explanation

JSON FORMAT:
{{"store_name": "...", "store_email": "...", "store_phone": "...", "store_voice": "...", "store_tone": "...", "services_products": "...", "color_theme": "#...", "business_type": "..."}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts business information from website content. Always return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0,
            max_tokens=500
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up the response
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[AI Agent] Response: {result_text[:200]}...")

        store_data = json.loads(result_text)

        # Ensure required fields have defaults
        if not store_data.get("store_name"):
            store_data["store_name"] = _extract_domain_name(url)

        # Use image analysis color if available and no color was extracted
        if not store_data.get("color_theme") or store_data.get("color_theme") == "#3B82F6":
            if image_analysis and image_analysis.get("brand_colors"):
                store_data["color_theme"] = image_analysis["brand_colors"][0]
            else:
                store_data["color_theme"] = "#3B82F6"

        if not store_data.get("business_type"):
            store_data["business_type"] = "other"

        # Default store_tone if not extracted
        valid_tones = ["friendly", "professional", "luxury", "modern", "traditional", "playful", "minimalist", "eco_friendly"]
        if not store_data.get("store_tone") or store_data.get("store_tone") not in valid_tones:
            store_data["store_tone"] = "professional"  # Default to professional

        # Generate store_link from store name
        if store_data.get("store_name"):
            store_link = re.sub(r'[^a-z0-9]+', '-', store_data["store_name"].lower())
            store_data["store_link"] = store_link.strip('-')[:30]

        # Add brand style from image analysis
        if image_analysis and image_analysis.get("brand_style"):
            store_data["brand_style"] = image_analysis["brand_style"]

        # Validate contact info
        store_data = _validate_contact_info(store_data, content)

        return store_data

    except json.JSONDecodeError as e:
        print(f"[AI Agent] JSON parse error: {e}")
        return _generate_fallback_data(url)
    except Exception as e:
        print(f"[AI Agent] Error: {e}")
        return _generate_fallback_data(url)


def _extract_contact_info_directly(content: str, domain: str) -> Dict[str, Any]:
    """
    Extract contact info directly from content using regex patterns.
    This is more reliable than AI extraction for structured data.
    """
    import html
    from urllib.parse import unquote
    result = {"email": None, "phone": None}

    # Decode HTML entities in content (e.g., &#64; -> @, &amp; -> &)
    decoded_content = html.unescape(content)
    # Also decode URL encoding (e.g., %20 -> space, %40 -> @)
    decoded_content = unquote(decoded_content)

    # Also handle common email obfuscations
    decoded_content = re.sub(r'\s*\[at\]\s*', '@', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\(at\)\s*', '@', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\[dot\]\s*', '.', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'\s*\(dot\)\s*', '.', decoded_content, flags=re.IGNORECASE)
    decoded_content = re.sub(r'<span[^>]*>\s*@\s*</span>', '@', decoded_content, flags=re.IGNORECASE)

    # Extract emails using regex
    # Look for emails that match the domain first
    domain_base = domain.split('.')[0] if '.' in domain else domain
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    # Also try mailto: links which are more reliable
    mailto_pattern = r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
    mailto_emails = re.findall(mailto_pattern, decoded_content, re.IGNORECASE)

    # Also look for href="mailto:..." patterns
    href_mailto_pattern = r'href=["\']mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})["\']'
    href_mailto_emails = re.findall(href_mailto_pattern, decoded_content, re.IGNORECASE)

    all_emails = re.findall(email_pattern, decoded_content)

    # Add mailto emails to the front (higher priority)
    all_emails = href_mailto_emails + mailto_emails + all_emails

    # Also specifically search for the domain email pattern
    domain_email_pattern = rf'[a-zA-Z0-9._%+-]+@{re.escape(domain)}'
    domain_specific_emails = re.findall(domain_email_pattern, decoded_content, re.IGNORECASE)
    if domain_specific_emails:
        all_emails = domain_specific_emails + all_emails

    print(f"[Contact] Raw content length: {len(content)}, decoded: {len(decoded_content)}")
    print(f"[Contact] Domain: {domain}, domain_base: {domain_base}")
    print(f"[Contact] Mailto emails found: {mailto_emails}")
    print(f"[Contact] Href mailto emails: {href_mailto_emails}")
    print(f"[Contact] Domain specific emails: {domain_specific_emails}")
    print(f"[Contact] All emails found: {list(set(all_emails))[:10]}")

    # Filter and prioritize emails
    domain_emails = []
    contact_emails = []
    other_emails = []

    # Emails to skip (common generic/fake ones)
    skip_emails = {
        'example@example.com', 'test@test.com', 'user@example.com',
        'contact@gmail.com', 'info@gmail.com', 'noreply@'
    }

    for email in all_emails:
        email_lower = email.lower()
        if any(skip in email_lower for skip in skip_emails):
            continue
        if domain_base.lower() in email_lower:
            domain_emails.append(email)
        elif any(prefix in email_lower for prefix in ['info@', 'contact@', 'hello@', 'support@', 'enquiries@', 'sales@', 'help@']):
            contact_emails.append(email)
        else:
            other_emails.append(email)

    # Prioritize: domain emails > contact emails > other emails
    if domain_emails:
        result["email"] = domain_emails[0]
    elif contact_emails:
        result["email"] = contact_emails[0]
    elif other_emails:
        result["email"] = other_emails[0]

    print(f"[Contact] Found emails: domain={domain_emails}, contact={contact_emails}, other={other_emails[:3]}")

    # Extract phone numbers using phonenumbers library (Google's libphonenumber)
    # This handles international formats automatically
    all_phones = []
    seen_digits = set()

    # Try common regions - prioritize based on domain hints
    regions_to_try = ['ZW', 'ZA', 'US', 'GB', 'AU', None]  # None = no region hint

    # Check if domain suggests a specific country
    if '.zw' in domain.lower():
        regions_to_try = ['ZW'] + [r for r in regions_to_try if r != 'ZW']
    elif '.za' in domain.lower():
        regions_to_try = ['ZA'] + [r for r in regions_to_try if r != 'ZA']
    elif '.co.uk' in domain.lower() or '.uk' in domain.lower():
        regions_to_try = ['GB'] + [r for r in regions_to_try if r != 'GB']

    print(f"[Contact] Using phonenumbers library with regions: {regions_to_try[:3]}")

    for region in regions_to_try:
        try:
            for match in PhoneNumberMatcher(decoded_content, region):
                phone_obj = match.number
                # Format as international
                formatted = phonenumbers.format_number(phone_obj, PhoneNumberFormat.INTERNATIONAL)

                # Get digits for deduplication
                digits = re.sub(r'[^\d]', '', formatted)
                last7 = digits[-7:]

                if last7 not in seen_digits:
                    seen_digits.add(last7)
                    all_phones.append(formatted)
                    print(f"[Contact] phonenumbers found: {formatted} (region: {region})")
        except Exception as e:
            print(f"[Contact] phonenumbers error for region {region}: {e}")

    # Fallback to regex if phonenumbers found nothing
    if not all_phones:
        print("[Contact] phonenumbers found nothing, falling back to regex")
        phone_patterns = [
            r'\+\d{1,3}[\s\-\.]\d{2,4}[\s\-\.]\d{5,7}',
            r'\+\d{1,3}[\s\-\.]?\d{2,4}[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}',
            r'\+\d{1,3}[\s\-\.]?\(\d+\)[\s\-\.]?\d{3,}[\s\-\.]?\d*',
            r'\(\d{2,4}\)[\s\-\.]?\d{3,4}[\s\-\.]?\d{3,4}',
            r'\b\d{3,4}[\s\-\.]\d{3,4}[\s\-\.]\d{3,4}\b',
            r'\b0\d{8,11}\b',
        ]

        for pattern in phone_patterns:
            matches = re.findall(pattern, content)
            for phone in matches:
                digits = re.sub(r'[^\d]', '', phone)
                if len(digits) >= 7 and len(digits) <= 15:
                    last7 = digits[-7:]
                    if last7 not in seen_digits and len(set(digits)) > 2:
                        seen_digits.add(last7)
                        all_phones.append(phone.strip())

    if all_phones:
        result["phone"] = all_phones[0]

    print(f"[Contact] Found phones: {all_phones[:5]}")

    return result


def _validate_contact_info(store_data: Dict[str, Any], original_content: str) -> Dict[str, Any]:
    """
    Validate and enhance contact info.
    First try direct extraction, then validate AI-extracted data.
    """
    # Extract domain for email matching
    domain = ""
    if store_data.get("store_link"):
        domain = store_data.get("store_link", "")

    # Try direct extraction first
    direct_contact = _extract_contact_info_directly(original_content, domain)

    # Use direct extraction results if available
    if direct_contact["email"] and not store_data.get("store_email"):
        store_data["store_email"] = direct_contact["email"]
        print(f"[Validation] Using directly extracted email: {direct_contact['email']}")

    if direct_contact["phone"] and not store_data.get("store_phone"):
        store_data["store_phone"] = direct_contact["phone"]
        print(f"[Validation] Using directly extracted phone: {direct_contact['phone']}")

    # Validate AI-extracted email
    email = store_data.get("store_email")
    if email:
        fake_email_patterns = [
            "contact@gmail.com", "info@gmail.com", "hello@gmail.com",
            "support@gmail.com", "help@gmail.com", "sales@gmail.com",
            "@example.com", "@test.com", "@email.com", "@mail.com",
            "example@", "test@", "user@", "admin@"
        ]
        if any(pattern in email.lower() for pattern in fake_email_patterns):
            print(f"[Validation] Rejected fake email: {email}")
            store_data["store_email"] = direct_contact["email"]  # Fallback to direct extraction
        elif email.lower() not in original_content.lower():
            print(f"[Validation] AI email not found in content: {email}")
            # Still use it if we have no alternative, as AI might have normalized it
            if direct_contact["email"]:
                store_data["store_email"] = direct_contact["email"]

    # Validate AI-extracted phone
    phone = store_data.get("store_phone")
    if phone:
        fake_phone_patterns = [
            "+1 234 567 8901", "+1-234-567-8901", "234-567-8901",
            "555-", "123-456-7890", "000-000-0000",
            "111-111-1111", "123456789", "0000000000"
        ]
        phone_cleaned = re.sub(r'[\s\-\(\)\.]', '', phone)

        if any(pattern.replace("-", "").replace(" ", "") in phone_cleaned for pattern in fake_phone_patterns):
            print(f"[Validation] Rejected fake phone: {phone}")
            store_data["store_phone"] = direct_contact["phone"]
        elif phone_cleaned in ["12345678901", "1234567890"] or len(set(phone_cleaned.replace("+", ""))) <= 2:
            print(f"[Validation] Rejected suspicious phone pattern: {phone}")
            store_data["store_phone"] = direct_contact["phone"]

    # Sanitize phone: if multiple phones (comma-separated), keep only the first one
    # Also ensure it doesn't exceed database limit (50 chars)
    final_phone = store_data.get("store_phone")
    if final_phone:
        # Split by comma and take only the first phone
        if ',' in final_phone:
            final_phone = final_phone.split(',')[0].strip()
            print(f"[Validation] Multiple phones detected, using first: {final_phone}")
        # Truncate if still too long (max 50 chars for DB)
        if len(final_phone) > 50:
            final_phone = final_phone[:50]
            print(f"[Validation] Phone truncated to 50 chars: {final_phone}")
        store_data["store_phone"] = final_phone

    # Sanitize email: clean up URL-encoded characters and whitespace
    final_email = store_data.get("store_email")
    if final_email:
        from urllib.parse import unquote
        # Decode URL encoding (e.g., %20 -> space)
        final_email = unquote(final_email)
        # Strip whitespace
        final_email = final_email.strip()
        # Remove any remaining invalid characters at start
        final_email = re.sub(r'^[^a-zA-Z0-9]+', '', final_email)
        store_data["store_email"] = final_email
        print(f"[Validation] Sanitized email: {final_email}")

    return store_data


def _extract_domain_name(url: str) -> str:
    """Extract a readable name from the domain."""
    domain = url.lower()
    domain = re.sub(r'^https?://', '', domain)
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.split('/')[0]
    domain = domain.split('.')[0]
    return domain.capitalize()


def _extract_faqs_with_ai(content: str, url: str) -> List[Dict[str, str]]:
    """
    Use OpenAI to extract FAQ information from website content.
    Returns a list of {question, answer, category} dicts.
    Enhanced to extract comprehensive business information.
    """
    client = _llm_client()

    # Truncate content if too long
    if len(content) > 15000:
        content = content[:15000] + "..."

    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    prompt = f"""You are an expert at extracting FAQ and business information from website content.

TASK: Analyze this website content and create helpful FAQs that customers would want to know.

Website URL: {url}
Domain: {domain}

EXTRACT INFORMATION FOR THESE FAQ CATEGORIES:

1. **COMPANY INFO** (PRIORITY - Always extract if available):
   - "Who founded [Company]?" / "When was [Company] founded?"
   - "What does [Company] do?" / "What services does [Company] offer?"
   - "What is [Company]'s mission?"
   - Look for: founder names, CEO, year established, company history, mission statements

2. **LOCATION & CONTACT**:
   - "Where is [Company] located?"
   - "What are [Company]'s business hours?"
   - "How can I contact [Company]?"
   - Look for: physical addresses, office locations, operating hours, contact numbers, email

3. **PRODUCTS & SERVICES**:
   - "What products/services does [Company] offer?"
   - "How does [Product/Service] work?"
   - "What makes [Company] different?"
   - Look for: product descriptions, service offerings, unique selling points

4. **POLICIES & PROCEDURES**:
   - Shipping and delivery information
   - Returns and refunds
   - Payment methods accepted
   - Warranty information

5. **TECHNICAL/SPECIFIC INFO**:
   - Product specifications
   - Service accuracy/reliability stats
   - Certifications or credentials
   - Any numerical claims or statistics

WEBSITE CONTENT:
{content}

IMPORTANT RULES:
- Extract ONLY information that ACTUALLY appears in the content above
- PRIORITIZE company identity info: name, founder/CEO, founding year, location, hours
- Create 8-15 FAQs covering as many categories as possible
- Make questions natural - how a customer would actually ask
- Answers should be complete but concise (1-3 sentences)
- Use the actual company/brand name in questions when known
- Categories: company, location, hours, contact, products, services, shipping, returns, pricing, payment, general

Return ONLY valid JSON array in this format:
[
  {{"question": "When was [Company] founded?", "answer": "[Company] was founded in [year] by [founder].", "category": "company"}},
  {{"question": "Where is [Company] located?", "answer": "[Company] is located at [address].", "category": "location"}},
  {{"question": "What are [Company]'s business hours?", "answer": "[Company] is open [hours].", "category": "hours"}}
]

If no information can be extracted, return an empty array: []
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that extracts FAQ information from website content. Always return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up the response
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[FAQ Agent] Extracted FAQs: {result_text[:200]}...")

        faqs = json.loads(result_text)

        # Validate FAQ structure
        valid_faqs = []
        for faq in faqs:
            if isinstance(faq, dict) and faq.get("question") and faq.get("answer"):
                valid_faqs.append({
                    "question": faq.get("question", ""),
                    "answer": faq.get("answer", ""),
                    "category": faq.get("category", "general")
                })

        print(f"[FAQ Agent] Extracted {len(valid_faqs)} valid FAQs")
        return valid_faqs

    except json.JSONDecodeError as e:
        print(f"[FAQ Agent] JSON parse error: {e}")
        return []
    except Exception as e:
        print(f"[FAQ Agent] Error extracting FAQs: {e}")
        return []


def _extract_products_services_with_prices(content: str, url: str) -> Dict[str, Any]:
    """
    Extract ACTUAL products/services with prices from website content.
    This is a dedicated function for accurate product/service extraction.

    Returns:
        Dict with:
        - products: List of product dicts with name, description, price, category
        - services: List of service dicts with name, description, price, category
        - pricing_tiers: List of pricing tier dicts (for SaaS/subscription businesses)
        - industry: Detected industry type
        - target_market: Who the business sells to
    """
    client = _llm_client()

    # Use more content for product extraction
    if len(content) > 30000:
        content = content[:30000] + "..."

    domain = url.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]

    prompt = f"""You are an expert at extracting product and service information from websites.

TASK: Extract ALL products, services, and pricing from this website content.

Website URL: {url}
Domain: {domain}

EXTRACT THE FOLLOWING:

1. **PRODUCTS** (physical or digital items for sale):
   - name: Exact product name
   - description: What it is (1-2 sentences)
   - price: Actual price if shown (e.g., "$25/year", "$3.50/month", "From $99")
   - category: Product category

2. **SERVICES** (services offered):
   - name: Exact service name
   - description: What the service includes
   - price: Price if shown
   - category: Service category

3. **PRICING TIERS** (for subscription/SaaS businesses):
   - tier_name: Name of the plan (e.g., "Bronze", "Premium", "Enterprise")
   - price: Price with billing period (e.g., "$10/month", "$99/year")
   - features: Key features included (list)

4. **BUSINESS INFO**:
   - industry: Specific industry (e.g., "web_hosting", "security_services", "restaurant", "retail_fashion")
   - target_market: Who they sell to

WEBSITE CONTENT:
{content}

IMPORTANT RULES:
- Extract ONLY products/services that ACTUALLY appear in the content
- Include ACTUAL prices if shown - don't make up prices
- Be SPECIFIC - don't use generic terms like "various services"
- For hosting companies: look for Domain Registration, Web Hosting, Email Hosting, SSL Certificates
- For security companies: look for Armed Response, CCTV, Access Control, Monitoring
- For restaurants: look for menu items with prices
- If no price is shown, use "Contact for quote" or "Price on request"

Return ONLY valid JSON in this format:
{{
  "products": [
    {{"name": "Product Name", "description": "What it is", "price": "$XX", "category": "category"}}
  ],
  "services": [
    {{"name": "Service Name", "description": "What it includes", "price": "$XX/month", "category": "category"}}
  ],
  "pricing_tiers": [
    {{"tier_name": "Basic", "price": "$10/month", "features": ["feature 1", "feature 2"]}}
  ],
  "industry": "specific_industry",
  "target_market": "who they sell to"
}}

If no products/services found, return empty arrays."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Use stronger model for accurate extraction
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at extracting product and pricing information from websites. Always return valid JSON only. Be specific and accurate."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.1,
            max_tokens=2000
        )

        result_text = response.choices[0].message.content.strip()

        # Clean up the response
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        print(f"[Products] Extracted products/services: {result_text[:200]}...")

        data = json.loads(result_text)

        # Validate and clean the response
        products = data.get("products", [])
        services = data.get("services", [])
        pricing_tiers = data.get("pricing_tiers", [])

        # Validate products
        valid_products = []
        for p in products:
            if isinstance(p, dict) and p.get("name"):
                valid_products.append({
                    "name": p.get("name", ""),
                    "description": p.get("description", ""),
                    "price": p.get("price", "Contact for quote"),
                    "category": p.get("category", "general")
                })

        # Validate services
        valid_services = []
        for s in services:
            if isinstance(s, dict) and s.get("name"):
                valid_services.append({
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "price": s.get("price", "Contact for quote"),
                    "category": s.get("category", "general")
                })

        # Validate pricing tiers
        valid_tiers = []
        for t in pricing_tiers:
            if isinstance(t, dict) and t.get("tier_name"):
                valid_tiers.append({
                    "tier_name": t.get("tier_name", ""),
                    "price": t.get("price", "Contact for quote"),
                    "features": t.get("features", [])
                })

        result = {
            "products": valid_products,
            "services": valid_services,
            "pricing_tiers": valid_tiers,
            "industry": data.get("industry", "general"),
            "target_market": data.get("target_market", ""),
            "total_items": len(valid_products) + len(valid_services)
        }

        print(f"[Products] Found {len(valid_products)} products, {len(valid_services)} services, {len(valid_tiers)} pricing tiers")
        return result

    except json.JSONDecodeError as e:
        print(f"[Products] JSON parse error: {e}")
        return {"products": [], "services": [], "pricing_tiers": [], "industry": "general", "target_market": "", "total_items": 0}
    except Exception as e:
        print(f"[Products] Error extracting products/services: {e}")
        return {"products": [], "services": [], "pricing_tiers": [], "industry": "general", "target_market": "", "total_items": 0}


def _generate_fallback_data(url: str) -> Dict[str, Any]:
    """Generate fallback data when scraping fails."""
    domain = _extract_domain_name(url)
    store_link = re.sub(r'[^a-z0-9]+', '-', domain.lower()).strip('-')[:30]

    return {
        "store_name": f"{domain} Store",
        "store_email": None,
        "store_phone": None,
        "store_voice": f"Welcome to {domain}. We provide quality products and services tailored to your needs.",
        "store_tone": "professional",
        "store_link": store_link,
        "services_products": "General Products, Services",
        "color_theme": "#3B82F6",
        "business_type": "other",
        "logo_url": None,
        "faqs": []
    }


# Test function
def test_scraping(url: str = "https://example.com"):
    """Test the scraping service."""
    print(f"\n{'='*50}")
    print(f"Testing scraping for: {url}")
    print('='*50)

    result = extract_store_info_from_website(url)

    print(f"\n{'='*50}")
    print("RESULT:")
    print(json.dumps(result, indent=2))
    print('='*50)

    return result
