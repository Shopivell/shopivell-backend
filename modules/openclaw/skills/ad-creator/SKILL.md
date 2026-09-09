# Ad Creator

AI-powered skill for creating Meta ad campaigns including market research, copywriting, and image generation via OpenAI GPT-Image-2.5.

## Description
Generate complete ad campaigns by researching the market, writing compelling copy, and creating visuals using GPT-Image-2.5. Uses AI to produce multiple variations for A/B testing.

## Image Generation
Uses **OpenAI GPT-Image-2.5** for high-quality ad creative generation:
- HD quality images
- Multiple styles: lifestyle, product_shot, minimalist, ugc, testimonial
- Automatic prompt optimization
- Brand color integration

## Actions

### Market Research

#### research_market
Analyze market and competitors for a product/niche.
- Parameters:
  - product_name (string): Product name
  - product_description (string): Product description
  - niche (string): Market niche/category
  - target_country (string): Target market country code
- Returns: market_size, competitor_analysis, trending_topics, audience_insights, recommended_angles

#### analyze_product
Extract marketing-relevant info from a product.
- Parameters:
  - product_url (string): Product page URL (optional)
  - product_data: {name, description, price, images[], features[], benefits[]}
- Returns: unique_selling_points, target_audience, pain_points_addressed, emotional_triggers, objections

### Creative Strategy

#### generate_angles
Generate creative angles for the campaign.
- Parameters:
  - product_data: Product info from analyze_product
  - market_data: Market info from research_market
  - campaign_goal (string): conversions, awareness, engagement
  - brand_voice (string): professional, casual, playful, luxury
- Returns: angles[] with name, hook, narrative, target_emotion, cta_style

#### generate_ad_copy
Generate ad copy variations.
- Parameters:
  - angle: Selected angle from generate_angles
  - product_data: Product info
  - format (string): single_image, carousel, video_script, story
  - variations (number): Number of variations (1-5)
  - max_length (number): Max characters for primary text
- Returns: variations[] with headline, primary_text, description, cta, hashtags

#### generate_whatsapp_copy
Generate Click-to-WhatsApp ad copy with welcome message.
- Parameters:
  - product_data: Product info
  - angle: Selected angle
  - store_name (string): Store name for personalization
- Returns: headline, primary_text, welcome_message, chatbot_intro, qualification_questions

### Creative Generation (GPT-Image-2.5)

#### generate_image
Generate ad creative image using OpenAI GPT-Image-2.5.
- Parameters:
  - product_name (string): Product name
  - product_description (string): Product description
  - style (string): lifestyle, product_shot, testimonial, minimalist, ugc
  - dimensions (string): square, portrait, story, landscape
  - overlay_text (string): Text to overlay (optional)
  - brand_colors (string[]): Hex color codes
  - mood (string): Emotional mood (optional)
- Returns:
  - image_url: Generated image URL (valid for 1 hour)
  - prompt_used: The prompt used for generation
  - dimensions, style, model

#### generate_image_variations
Generate multiple image variations for A/B testing.
- Parameters:
  - product_name (string): Product name
  - product_description (string): Product description
  - angle: Creative angle
  - count (number): Number of variations (1-5)
  - dimensions (string): Image dimensions
  - brand_colors (string[]): Brand colors
- Returns: variations[] with image_url, style, variation number

#### generate_carousel
Generate carousel ad with images for each slide.
- Parameters:
  - product_data: Product info
  - angle: Selected angle
  - slides (number): Number of slides (2-10)
  - style (string): storytelling, features, testimonials, comparison
  - brand_colors (string[]): Brand colors
- Returns: slides[] with image_url, headline, description

#### generate_video_script
Generate video ad script.
- Parameters:
  - product_data: Product info
  - angle: Selected angle
  - duration (number): Video length in seconds (15, 30, 60)
  - style (string): talking_head, product_demo, testimonial, story
- Returns: script with hook, problem, solution, proof, cta + b_roll_suggestions, music_mood

### Campaign Assembly

#### create_ad_set
Assemble a complete ad set ready for launch.
- Parameters:
  - product_data: Product info
  - angle: Selected angle
  - copies: Generated copy variations
  - creatives: Generated images
  - targeting: Audience targeting
- Returns: ad_set with name, ads[], targeting, recommended_budget, expected_metrics

#### suggest_ab_tests
Suggest A/B test variations.
- Parameters:
  - ad_set: Current ad set
  - test_type (string): headline, image, audience, cta, copy
- Returns: variations[] with name, change, hypothesis, config

### Full Automation

#### generate_full_campaign
Generate a complete campaign from product info (one-click).
- Parameters:
  - product_name (string): Product name
  - product_description (string): Product description
  - product_price (number): Price (optional)
  - product_images (string[]): Existing product images (optional)
  - store_name (string): Store name
  - target_country (string): Target country code
  - campaign_goal (string): conversions, awareness, engagement
  - brand_voice (string): professional, casual, playful, luxury
  - brand_colors (string[]): Brand colors
  - budget (number): Daily budget in USD
- Returns:
  - product_analysis: Full product analysis
  - market_research: Market research results
  - angles: Generated creative angles
  - ad_set: Ready-to-launch ad set with images
  - ready_for_launch: true

## Example Usage

### One-Click Campaign Generation
```javascript
const campaign = await adCreator.generate_full_campaign({
  product_name: "Organic Face Serum",
  product_description: "Natural vitamin C serum for glowing skin",
  product_price: 29.99,
  store_name: "BeautyZW",
  target_country: "ZW",
  campaign_goal: "conversions",
  brand_voice: "professional",
  brand_colors: ["#FF6B6B", "#4ECDC4"],
  budget: 50
});

// Result includes everything ready to launch:
// - Market research
// - 5 creative angles
// - 3 copy variations
// - 3 AI-generated images (GPT-Image-2.5)
// - Complete ad set configuration

// Launch via Zernio
await zernioAds.create_campaign({
  profile_id: "store_123_profile",
  ...campaign.ad_set
});
```

### Generate Single Image
```javascript
const image = await adCreator.generate_image({
  product_name: "Wireless Earbuds Pro",
  product_description: "Premium wireless earbuds with noise cancellation",
  style: "lifestyle",
  dimensions: "square",
  overlay_text: "50% Off Today",
  brand_colors: ["#000000", "#FFD700"],
  mood: "excitement"
});

console.log(image);
// {
//   image_url: "https://oaidalleapiprodscus.blob.core.windows.net/...",
//   prompt_used: "A lifestyle photo featuring premium wireless earbuds...",
//   dimensions: "square",
//   style: "lifestyle",
//   model: "gpt-image-2.5"
// }
```

### Generate Carousel
```javascript
const carousel = await adCreator.generate_carousel({
  product_data: { name: "Fitness App", description: "Track workouts and nutrition" },
  angle: { name: "Transformation", hook: "Before vs After" },
  slides: 4,
  style: "storytelling",
  brand_colors: ["#00FF00", "#FFFFFF"]
});

// Returns 4 slides, each with AI-generated image
```

## Environment Variables
- OPENAI_API_KEY (required for GPT-Image-2.5)
- ANTHROPIC_API_KEY (for Claude copywriting)
- SHOPIVELL_API_URL (for product data)

## Image Sizes
| Dimensions | OpenAI Size | Use Case |
|------------|-------------|----------|
| square | 1024x1024 | Feed posts |
| portrait | 1024x1792 | Stories, Reels |
| landscape | 1792x1024 | Link ads |

## Integration with Zernio Ads
The output of `generate_full_campaign()` or `create_ad_set()` maps directly to `zernioAds.create_campaign()` input.
