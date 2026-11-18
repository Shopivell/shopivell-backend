"""Read-only OpenAI marketing skill probe for a public brand URL.

Example:
  python scripts/marketing_skills_probe.py https://www.reliabletech.co.zw/ \
      --output reliabletech-audit.json

Use --snapshot PATH when the URL is not reachable from the running environment.
No Shopivell store, campaign or ad account is modified.
"""

import argparse
from bs4 import BeautifulSoup
import json
import os
from pathlib import Path
import sys

import httpx
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.openclaw.marketing_skill_library import brand_url_audit_messages


def page_text(url: str, snapshot: Path | None) -> str:
    if snapshot:
        return snapshot.read_text(encoding="utf-8")
    if not url.startswith("https://"):
        raise ValueError("Use a public HTTPS URL")
    with httpx.Client(timeout=20, follow_redirects=True, trust_env=False) as client:
        response = client.get(url, headers={"User-Agent": "Shopivell-Marketing-Probe/1.0"})
        response.raise_for_status()
        if not response.url.scheme == "https" or "html" not in response.headers.get("content-type", ""):
            raise ValueError("The URL did not return an HTTPS HTML page")
        if len(response.content) > 1_000_000:
            raise ValueError("Page is too large for this probe")
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "svg", "noscript"]):
        node.decompose()
    return soup.get_text(" ", strip=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("OPENAI_API_KEY is required for a live model test")
    text = page_text(args.url, args.snapshot)
    if len(text) < 100:
        parser.error("The page has too little readable text for an audit")
    model = os.getenv("MARKETING_TEST_MODEL", "gpt-4o-mini")
    response = OpenAI().chat.completions.create(
        model=model,
        messages=brand_url_audit_messages(args.url, text),
        response_format={"type": "json_object"},
    )
    result = {
        "url": args.url,
        "model": model,
        "source_characters": len(text),
        "audit": json.loads(response.choices[0].message.content or "{}"),
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Saved {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
