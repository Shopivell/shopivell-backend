"""Contract checks for imported marketing prompts. No model or ad-account calls."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.ad_angles.service import generate_ad_angles
from modules.campaigns.service import CampaignService
from modules.openclaw import agent_service
from modules.openclaw.marketing_skill_library import _SECTIONS, marketing_skill_guidance


def response():
    return {"angles": [{"angle_name": "Printer enquiries", "value_proposition": "Explore the listed printer",
        "proof": "Canon PIXMA MG2541S", "hook": "Explore Canon printing", "copy_variations": [
            {"approach": name, "primary_text": f"{name}: enquire about the Canon PIXMA MG2541S.",
             "headline": "Explore Canon printing", "description": "Ask for product details",
             "call_to_action": "Contact Us", "optimization": "messages"}
            for name in ("product details", "home paperwork", "shop consultation")]}]}


class ImportedMarketingTests(unittest.TestCase):
    def test_angles_use_imported_prompt_and_preserve_model_variations(self):
        raw = response()
        with patch('modules.openclaw.gateway.ask_json_sync', return_value=raw) as model:
            result = generate_ad_angles({"company_name": "Reliable Modern Technologies"}, [], [], [],
                                        count=1, clean_text="Canon PIXMA MG2541S is listed.")
        self.assertEqual([v['approach'] for v in result[0]['copy_variations']],
                         ['product details', 'home paperwork', 'shop consultation'])
        prompt = model.call_args.args[2]
        self.assertIn('[corey/', prompt)
        self.assertIn('[ryze/', prompt)
        self.assertNotIn('[meta_ads_kit/', prompt)
        self.assertNotIn('invent the vivid', prompt)
        self.assertIn('Canon PIXMA MG2541S', model.call_args.args[3])

    def test_partial_copy_never_uses_legacy_template(self):
        raw = response()
        raw['angles'][0]['copy_variations'] = raw['angles'][0]['copy_variations'][:1]
        with patch('modules.openclaw.gateway.ask_json_sync', return_value=raw):
            with self.assertRaisesRegex(ValueError, 'fewer than three'):
                generate_ad_angles({'company_name': 'Brand'}, [], [], [], count=1, clean_text='Real facts')

    def test_campaign_source_is_the_supplied_brand(self):
        service = CampaignService.__new__(CampaignService)
        service.openrouter = None
        service.openai = object()
        service._generate_with_openai = Mock(return_value={'ad_sets': []})
        result = service._generate_ad_content({'content': 'Reliable Tech sells printers'},
                                              'https://www.reliabletech.co.zw/',
                                              {'store_name': 'Unrelated Store'})
        prompt = service._generate_with_openai.call_args.args[0]
        self.assertNotIn('Unrelated Store', prompt)
        self.assertNotIn('Corporate Security Directors', prompt)
        self.assertIn('Reliable Tech sells printers', prompt)
        self.assertEqual(result, {'ad_sets': []})

    def test_missing_model_does_not_generate_mock_campaign(self):
        service = CampaignService.__new__(CampaignService)
        service.openrouter = service.openai = None
        with self.assertRaises(RuntimeError):
            service._generate_ad_content_from_store({'store_name': 'Brand'})

    def test_image_contract_preserves_reference_validation(self):
        result = agent_service._validate_image_direction(
            {'prompt': 'A detailed typographic composition featuring the supplied brand and product title.',
             'reference_numbers': [1, 99]}, [{'url': 'https://example.com/product.png'}])
        self.assertEqual(result['reference_indices'], [1])
        self.assertIn('[corey/image]', agent_service.IMAGE_AGENT_PROMPT)

    def test_registry_and_legacy_discovery(self):
        for task in _SECTIONS:
            self.assertTrue(marketing_skill_guidance(task).strip())
        root = Path(__file__).resolve().parents[1] / 'modules/openclaw/skills'
        for name in ('ad-creator', 'market-research', 'zernio-ads'):
            self.assertFalse((root / name / 'SKILL.md').exists())
            self.assertTrue((root / name / 'SKILL.md.disabled').exists())


if __name__ == '__main__':
    unittest.main()
