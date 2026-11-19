"""Contract tests for the shared visual brand system. No network/model calls."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.ad_angles.image_brief import build_image_prompt
from modules.campaigns.service import CampaignService
from modules.openclaw.agent_service import IMAGE_AGENT_PROMPT, IMAGE_SET_AGENT_PROMPT
from modules.openclaw.brand_context import build_brand_voice_contract, build_visual_brand_contract


class BrandConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "store_name": "Example Brand",
            "brand_description": "Precise industrial systems with a calm, expert presence.",
            "color_theme": "#123",
            "secondary_colors": ["#ABCDEF", "#112233", "#abcdef"],
            "font_heading": "Montserrat",
            "font_body": "Inter",
            "logo_url": "https://example.com/logo.png",
            "real_asset_urls": ["https://example.com/product.jpg"],
            "brand_dna": {"voice_and_style": {
                "aesthetic_style": "Clean technical photography with strong negative space.",
                "tone_of_voice": "calm and authoritative",
            }},
        }

    def test_contract_normalizes_palette_and_keeps_saved_typography(self):
        contract = build_visual_brand_contract(self.context)
        self.assertEqual(contract["palette"]["all"], ["#112233", "#ABCDEF"])
        self.assertEqual(contract["typography"], {"heading": "Montserrat", "body": "Inter"})
        self.assertEqual(contract["logo"]["placement"], "top-left")
        self.assertEqual(len(contract["signature"]), 16)

    def test_signature_is_stable_and_changes_with_brand_system(self):
        first = build_visual_brand_contract(self.context)["signature"]
        reordered = dict(reversed(list(self.context.items())))
        self.assertEqual(first, build_visual_brand_contract(reordered)["signature"])
        changed = {**self.context, "color_theme": "#654321"}
        self.assertNotEqual(first, build_visual_brand_contract(changed)["signature"])

    def test_missing_fonts_get_one_consistent_fallback_rule(self):
        contract = build_visual_brand_contract({"store_name": "No Fonts"})
        self.assertFalse(contract["typography"]["heading"])
        self.assertTrue(any("neutral sans-serif" in rule for rule in contract["consistency_rules"]))

    def test_voice_contract_locks_tone_positioning_and_customer_language(self):
        context = {**self.context, "brand_dna": {
            "voice_and_style": {"tone_of_voice": "calm, plain-spoken and technically confident"},
            "about": {"positioning": "A dependable local technical partner"},
            "buyer_profiles": [{"their_language": ["I need it to keep working", "No guesswork"]}],
        }}
        contract = build_brand_voice_contract(context)
        self.assertEqual(contract["tone_of_voice"], "calm, plain-spoken and technically confident")
        self.assertEqual(contract["positioning"], "A dependable local technical partner")
        self.assertEqual(contract["customer_language"], ["I need it to keep working", "No guesswork"])
        self.assertEqual(len(contract["signature"]), 16)

    def test_image_brief_repeats_palette_fonts_and_logo_placement(self):
        result = build_image_prompt(
            {"name": "Example Brand", "logo": True, "colors": ["#112233", "#ABCDEF"],
             "aesthetic": "Clean technical photography", "font_heading": "Montserrat",
             "font_body": "Inter"},
            {"headline": "Keep systems working", "button_label": "Learn More"},
            [],
        )
        prompt = result["prompt"]
        self.assertIn("#112233, #ABCDEF", prompt)
        self.assertIn("Montserrat", prompt)
        self.assertIn("Inter", prompt)
        self.assertIn("top-left", prompt)

    def test_image_agents_lock_one_contract_across_the_set(self):
        self.assertIn("immutable visual system", IMAGE_AGENT_PROMPT)
        self.assertIn("immutable across the entire image set", IMAGE_SET_AGENT_PROMPT)
        self.assertIn("contract signature", IMAGE_SET_AGENT_PROMPT)

    def test_campaign_uses_saved_kit_only_for_the_same_domain(self):
        service = CampaignService.__new__(CampaignService)
        scraped = {
            "domain": "example.com",
            "brand_color": "#999999",
            "brand_colors": ["#999999", "#EEEEEE"],
            "logo_url": "https://example.com/scraped-logo.png",
        }
        saved = {
            **self.context,
            "link_url": "https://www.example.com/",
        }
        with patch("modules.openclaw.brand_context.load_brand_context", return_value=saved):
            matching = service._build_campaign_visual_contract(
                scraped, store_id="store-1", source_url="https://example.com/products"
            )
            different = service._build_campaign_visual_contract(
                scraped, store_id="store-1", source_url="https://another-brand.co.zw/"
            )
        self.assertEqual(matching["palette"]["primary"], "#112233")
        self.assertEqual(matching["typography"]["heading"], "Montserrat")
        self.assertEqual(different["palette"]["primary"], "#999999")
        self.assertFalse(different["typography"]["heading"])

    def test_campaign_voice_snapshot_respects_domain_boundary(self):
        service = CampaignService.__new__(CampaignService)
        scraped = {"domain": "example.com", "brand_dna": {"voice_and_style": {
            "tone_of_voice": "website voice",
        }}}
        saved = {**self.context, "link_url": "example.com", "brand_dna": {
            "voice_and_style": {"tone_of_voice": "saved brand voice"},
        }}
        with patch("modules.openclaw.brand_context.load_brand_context", return_value=saved):
            matching = service._build_campaign_voice_contract(
                scraped, store_id="store-1", source_url="https://www.example.com/"
            )
            different = service._build_campaign_voice_contract(
                scraped, store_id="store-1", source_url="https://different.co.zw/"
            )
        self.assertEqual(matching["tone_of_voice"], "saved brand voice")
        self.assertEqual(different["tone_of_voice"], "website voice")


if __name__ == "__main__":
    unittest.main()
