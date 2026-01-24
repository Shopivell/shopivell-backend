# Brand Intelligence Module
# Extracts complete brand identity from websites for autonomous ad generation
"""
This module provides autonomous brand analysis capabilities:

- BrandDNAExtractor: Main orchestrator - extracts complete brand identity
- AssetCategorizer: Extracts and categorizes all images from website
- VisualStyleAnalyzer: Analyzes photography style, colors, composition

Usage:
    from modules.brand_intelligence import BrandDNAExtractor

    extractor = BrandDNAExtractor()
    brand_dna = await extractor.extract_brand_dna("https://example.com")

    # brand_dna contains:
    # - business_identity (company name, industry, services)
    # - visual_style (photography style, colors, composition)
    # - reference_images (categorized by type)
    # - style_prompt (ready-to-use prompt for image generation)
"""

from .brand_dna_extractor import BrandDNAExtractor, extract_brand_dna
from .asset_categorizer import AssetCategorizer
from .visual_style_analyzer import VisualStyleAnalyzer

__all__ = [
    "BrandDNAExtractor",
    "AssetCategorizer",
    "VisualStyleAnalyzer",
    "extract_brand_dna",
]
