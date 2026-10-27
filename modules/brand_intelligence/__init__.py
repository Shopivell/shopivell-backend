"""Brand Intelligence: brand DNA extraction and visual style analysis.

Note: the original source modules (brand_dna_extractor, visual_style_analyzer,
asset_categorizer) were lost; `campaigns/service.py` imports BrandDNAExtractor
from here inside a try/except and degrades gracefully when absent. The brand
DNA generator (Voice & Style + About + Buyer Profiles per store) lives in
brand_dna.py.
"""

from .brand_dna import generate_brand_dna, _fallback_dna  # noqa: F401
