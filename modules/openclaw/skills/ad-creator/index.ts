import { SkillContext } from "@openclaw/sdk";

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

// ============ ACTUAL PROMPTS FROM SHOPIVELL AGENTS ============

const PROMPTS = {
  // From creative_angles_agent.py
  CREATIVE_ANGLES: `Based on the market research and campaign brief, generate {num_angles} creative angles:

CAMPAIGN BRIEF:
Name: {campaign_name}
Objective: {objective}
Product: {product_description}
Target: {target_audience}
Target Location: {location}
Keywords: {keywords}

MARKET RESEARCH:
{market_research}

KEYWORD INTELLIGENCE:
{keyword_intelligence}

Generate {num_angles} distinct creative angles for advertising this product.
Make each angle unique and tailored to different segments of the target audience.

{performance_insights}

If keyword intelligence data is available, use it to:
- Align angles with high-volume search terms people actually use
- Create angles that match different search intents (transactional keywords for conversion angles, informational for awareness angles)
- Reference specific keyword language in value propositions so ads match what people search for
- If a Target Location is given, make at least one angle explicitly local: reference the city/country and use the local phrases above so the ad speaks to that market

IMPORTANT: Return your response as valid JSON with this exact structure:
{
  "angles": [
    {
      "angle_name": "Creative name for this angle",
      "value_proposition": "What unique value does this angle present?",
      "emotion_target": "What emotion does this angle aim to evoke?",
      "visual_direction": "What should the visual look like?",
      "reasoning": "Why this angle fits the research?"
    }
  ]
}

Return ONLY valid JSON, no other text.`,

  // From ad_copy_agent.py - research_based_prompt
  AD_COPY_RESEARCH: `You are an expert direct-response copywriter specializing in Facebook/Instagram ads.
Generate high-converting ad copy using the market research data provided.

COMPANY INFORMATION:
Company Name: {company_name}
WHAT THEY SELL (USE THESE SPECIFIC TERMS - NOT GENERIC INDUSTRY TERMS): {primary_products}
Tagline: {tagline}
Years in Business: {years_in_business}
Geographic Coverage: {geographic_coverage}
Target Location (mention in copy when present): {location}

LOCAL SEARCH TERMS customers in this market actually type (weave the most relevant ones verbatim into headlines and primary text where natural):
{local_keywords}

PRODUCTS/SERVICES DETAILS:
{services_products}

VALUE PROPOSITIONS:
{value_propositions}

KEY STATISTICS (USE THESE EXACT NUMBERS AS SOCIAL PROOF):
{statistics}

TARGET AUDIENCE FOR THIS AD:
Audience Segment: {audience_segment}
What they're looking for: {shopping_need}
Their frustration: {pain_point}
Audience Type: {audience_type}

PLATFORM: {platform}

BRAND VOICE: {brand_voice}

{creative_insights}

---

CRITICAL INSTRUCTIONS:
- Use the SPECIFIC product terms provided above (e.g., "fashion", "clothing", "workwear")
- NEVER use generic terms like "retail", "products", "services", or "solutions"
- Reference the ACTUAL statistics and years in business as proof points
- Make hooks specific to what {company_name} sells and who {audience_segment} are
- Address the actual frustration ({pain_point}) the audience faces

Generate ad copy optimized for {platform} with the following:

1. HOOKS (3 attention-grabbing opening lines - first 125 characters are crucial)
   - Pattern interrupt: Something unexpected about {primary_products}
   - Question: A question {audience_segment} ask themselves about {primary_products}
   - Social proof: Use the actual statistics ({statistics}) or years in business

2. HEADLINES (3 variations, max 40 characters each) - MUST mention specific products
   - Benefit-focused (specific benefit of {primary_products})
   - Curiosity-driven (about {company_name}'s {primary_products})
   - Social proof based (use actual numbers)
   - LOCAL: if a Target Location is given, at least one headline MUST include it,
     phrased like the local search terms above (e.g. "Electric Fence Installation in Harare")

3. PRIMARY TEXT (3 variations)
   For {platform}:
   - Short version (50-80 words) - mention {primary_products} specifically
   - Medium version (100-150 words) - address {pain_point}
   - Long version (200-250 words) - include statistics as proof

   Each should include:
   - Hook in first line (specific to {primary_products})
   - Problem agitation (about {pain_point})
   - Solution presentation (how {company_name}'s {primary_products} helps)
   - Social proof using actual statistics
   - Clear call to action
   - NO EMOJIS

4. DESCRIPTIONS (2 variations, max 30 words each) - mention specific products

5. CALL TO ACTION: Choose the most appropriate from:
   [Learn More, Shop Now, Sign Up, Get Quote, Contact Us, Book Now, See More]

Return as valid JSON:
{
  "hooks": {
    "pattern_interrupt": "Hook about {primary_products}",
    "question": "Question {audience_segment} ask about {primary_products}",
    "social_proof": "Hook using {statistics}"
  },
  "headlines": [
    {"type": "benefit", "text": "Headline about {primary_products}"},
    {"type": "curiosity", "text": "Headline 2"},
    {"type": "social_proof", "text": "Headline with statistics"}
  ],
  "primary_text": {
    "short": "Short version mentioning {primary_products}...",
    "medium": "Medium version addressing {pain_point}...",
    "long": "Long version with statistics..."
  },
  "descriptions": ["Description with {primary_products}", "Description 2"],
  "call_to_action": "Shop Now",
  "audience_segment": "{audience_segment}",
  "platform": "{platform}"
}

IMPORTANT:
- Use ACTUAL company data and product terms provided above
- Include real statistics as social proof
- Match the brand voice
- NO emojis in any text
- Return ONLY valid JSON`,

  // From visual_director_agent.py - image_prompt_template
  IMAGE_PROMPT: `You are an expert visual director specializing in Meta advertising creatives.

Generate detailed image generation prompts based on this creative hook/angle.

CAMPAIGN DETAILS:
Name: {campaign_name}
Product: {product_description}
Target Audience: {target_audience}

CREATIVE HOOK:
Hook Type: {hook_type}
Hook Text: {hook_text}
Emotion: {emotion}
Visual Direction Hint: {visual_hint}

AD COPY (for context):
Headline: {headline}
Primary Text: {primary_text}

Generate visual prompts for 3 different image concepts. For each:

{
    "image_concepts": [
        {
            "concept_name": "Descriptive name",
            "visual_style": "One of: lifestyle, product_hero, before_after, ugc_style, minimal, bold_graphic",
            "ai_image_prompt": "Detailed prompt for AI image generation (DALL-E/Midjourney style). Include: subject, action, setting, lighting, mood, camera angle, style modifiers",
            "composition": {
                "focal_point": "Where the eye should be drawn",
                "text_safe_zones": "Where to place text overlays",
                "color_palette": ["primary color", "secondary color", "accent color"]
            },
            "mood_board_keywords": ["list", "of", "mood", "keywords"],
            "format_variants": {
                "square": "Adjustments for 1:1",
                "portrait": "Adjustments for 4:5",
                "stories": "Adjustments for 9:16"
            },
            "overlay_text": {
                "headline_placement": "top/middle/bottom",
                "cta_placement": "bottom-right/bottom-center",
                "text_color": "color that contrasts with background"
            }
        }
    ]
}

Make prompts specific, detailed, and optimized for AI image generation.
Return ONLY valid JSON, no markdown.`,

  // From visual_director_agent.py - video_concept_template
  VIDEO_CONCEPT: `You are an expert video creative director for Meta advertising.

Create a detailed video concept based on this creative hook/angle.

CAMPAIGN DETAILS:
Name: {campaign_name}
Product: {product_description}
Target Audience: {target_audience}

CREATIVE HOOK:
Hook Type: {hook_type}
Hook Text: {hook_text}
Emotion: {emotion}

AD COPY:
Headline: {headline}
Primary Text: {primary_text}

Create a {video_length}-second video concept with shot-by-shot breakdown:

{
    "video_concept": {
        "concept_name": "Name of this concept",
        "format": "UGC/Animated/Live Action/Mixed",
        "total_duration": {video_length},
        "aspect_ratio": "9:16 for Reels/Stories or 1:1 for Feed",
        "hook_timing": "First 3 seconds must grab attention",
        "shots": [
            {
                "shot_number": 1,
                "duration": "0-3s",
                "type": "Hook",
                "visual": "Description of what's shown",
                "audio": "Music/voiceover/sound effect",
                "text_overlay": "Any on-screen text"
            }
        ],
        "music_direction": "Style and mood of music",
        "voiceover_script": "If applicable, the spoken words",
        "call_to_action": {
            "timing": "When CTA appears",
            "text": "CTA text",
            "visual": "How it's displayed"
        }
    }
}

Return ONLY valid JSON.`,

  // From gemini_image_generator.py - enhanced prompt
  IMAGE_GENERATION: `Generate a professional advertisement image based on this description:

{prompt}

IMPORTANT INSTRUCTIONS FOR REFERENCE IMAGES:
CRITICAL RULE: ABSOLUTELY NO TEXT of any kind in the generated image. No headlines, no labels, no company names, no product names, no slogans, no buttons, no signs with text, no watermarks, no review cards, no testimonials, no screen text, no vehicle text. The image must contain ZERO readable characters. If the prompt describes text on signs, screens, or vehicles - leave those surfaces blank or use abstract colored shapes instead. Only copy PHYSICAL/VISUAL elements from references (uniforms, vehicles, colors, equipment), never any text.
CRITICAL RULE: NEVER place small people or faces in the background. Only 1-3 main foreground subjects with large clear faces. Keep backgrounds clean with buildings, vehicles, or equipment only.`,

  // WhatsApp/CTWA specific copy
  WHATSAPP_COPY: `You are a conversational marketing expert specializing in WhatsApp commerce.

Generate Click-to-WhatsApp ad copy that drives conversations.

PRODUCT:
Name: {product_name}
Description: {product_description}
Price: {price}

STORE: {store_name}
TARGET LOCATION: {location}

CREATIVE ANGLE:
{angle}

Generate WhatsApp-optimized ad copy:

1. HEADLINE (25 chars max) - encourage chat, create curiosity
2. PRIMARY TEXT (125 chars) - why they should message you
3. WELCOME MESSAGE - auto-sent when they click (friendly, inviting, 160 chars max)
4. CHATBOT INTRO - first response from chatbot (personalized, helpful)
5. QUALIFICATION QUESTIONS - 3 questions to score the lead:
   - Question to understand their need
   - Question to understand their budget/timeline
   - Question to understand their readiness to buy

Return as JSON:
{
  "headline": "...",
  "primary_text": "...",
  "welcome_message": "...",
  "chatbot_intro": "...",
  "qualification_questions": ["Q1", "Q2", "Q3"]
}

IMPORTANT:
- Make it conversational, not salesy
- Welcome message should feel personal
- Questions should naturally score lead quality
- Return ONLY valid JSON`,

  // Market Research prompt
  MARKET_RESEARCH: `You are a market research analyst specializing in digital advertising.

Analyze the market for this product/business:

BUSINESS INFORMATION:
Name: {company_name}
Product/Service: {product_description}
Industry/Niche: {niche}
Target Country: {target_country}
Website: {website_url}

Provide comprehensive market research including:

1. MARKET SIZE & OPPORTUNITY
   - Estimated addressable market
   - Growth trends
   - Seasonal patterns

2. COMPETITOR ANALYSIS (Top 3-5)
   - Who are the main competitors?
   - Their positioning and USPs
   - Their pricing strategy
   - Their advertising approach

3. TARGET AUDIENCE INSIGHTS
   - Demographics (age, gender, income)
   - Psychographics (interests, values, lifestyle)
   - Pain points and frustrations
   - Buying behavior and triggers

4. KEYWORD INTELLIGENCE
   - High-intent search terms
   - Question-based keywords (what people ask)
   - Local search variations
   - Trending topics in this niche

5. RECOMMENDED MARKETING ANGLES (5)
   - Each angle should target a different segment or pain point
   - Include emotional triggers
   - Suggest visual direction

Return as JSON:
{
  "market_size": {...},
  "competitor_analysis": [...],
  "audience_insights": {...},
  "keywords": {...},
  "recommended_angles": [...]
}

Return ONLY valid JSON.`
};

// ============ Helper Functions ============

function fillTemplate(template: string, data: Record<string, any>): string {
  let result = template;
  for (const [key, value] of Object.entries(data)) {
    const placeholder = new RegExp(`\\{${key}\\}`, 'g');
    result = result.replace(placeholder, String(value || ''));
  }
  return result;
}

async function aiGenerate(ctx: SkillContext, prompt: string, system?: string): Promise<string> {
  return ctx.ai.generate({
    messages: [
      { role: "system", content: system || "You are an expert digital marketer." },
      { role: "user", content: prompt }
    ],
    model: "claude-sonnet-4-5",
    temperature: 0.7
  });
}

async function aiGenerateJSON<T>(ctx: SkillContext, prompt: string, system?: string): Promise<T> {
  const response = await aiGenerate(ctx, prompt, system);
  // Clean JSON from markdown
  let cleaned = response.trim();
  if (cleaned.startsWith("```json")) cleaned = cleaned.slice(7);
  if (cleaned.startsWith("```")) cleaned = cleaned.slice(3);
  if (cleaned.endsWith("```")) cleaned = cleaned.slice(0, -3);
  return JSON.parse(cleaned.trim());
}

// OpenAI Image Generation using GPT-Image-2.5
async function generateImageWithOpenAI(
  prompt: string,
  size: string = "1024x1024",
  quality: string = "hd",
  style: string = "vivid"
): Promise<{ url: string; revised_prompt: string }> {
  // Apply the critical rules from Gemini generator
  const enhancedPrompt = fillTemplate(PROMPTS.IMAGE_GENERATION, { prompt });

  const response = await fetch("https://api.openai.com/v1/images/generations", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-image-2.5",
      prompt: enhancedPrompt,
      n: 1,
      size,
      quality,
      style,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI Image API error: ${response.status} - ${error}`);
  }

  const data = await response.json();
  return {
    url: data.data[0].url,
    revised_prompt: data.data[0].revised_prompt || prompt,
  };
}

function mapDimensionsToSize(dimensions: string): string {
  const sizeMap: Record<string, string> = {
    "square": "1024x1024",
    "1080x1080": "1024x1024",
    "portrait": "1024x1792",
    "1080x1350": "1024x1792",
    "story": "1024x1792",
    "1080x1920": "1024x1792",
    "landscape": "1792x1024",
    "1200x628": "1792x1024",
  };
  return sizeMap[dimensions] || "1024x1024";
}

// ============ Skill Definition ============

export const adCreator = {
  name: "ad-creator",
  description: "AI-powered ad campaign creation using actual Shopivell agent prompts",

  actions: {
    // ============ Market Research ============

    async research_market(
      ctx: SkillContext,
      {
        company_name,
        product_description,
        niche,
        target_country,
        website_url,
      }: {
        company_name: string;
        product_description: string;
        niche: string;
        target_country: string;
        website_url?: string;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.MARKET_RESEARCH, {
        company_name,
        product_description,
        niche,
        target_country,
        website_url: website_url || "Not provided"
      });

      return aiGenerateJSON(ctx, prompt, "You are a market research analyst specializing in digital advertising.");
    },

    // ============ Creative Angles ============

    async generate_angles(
      ctx: SkillContext,
      {
        campaign_name,
        objective,
        product_description,
        target_audience,
        location,
        keywords,
        market_research,
        keyword_intelligence,
        performance_insights,
        num_angles,
      }: {
        campaign_name: string;
        objective: string;
        product_description: string;
        target_audience: string;
        location?: string;
        keywords?: string;
        market_research?: string;
        keyword_intelligence?: string;
        performance_insights?: string;
        num_angles?: number;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.CREATIVE_ANGLES, {
        campaign_name,
        objective,
        product_description,
        target_audience: typeof target_audience === 'object' ? JSON.stringify(target_audience) : target_audience,
        location: location || "Not specified",
        keywords: keywords || "Not provided",
        market_research: market_research || "Not provided",
        keyword_intelligence: keyword_intelligence || "Not provided",
        performance_insights: performance_insights || "",
        num_angles: num_angles || 5
      });

      return aiGenerateJSON(ctx, prompt, "You are a creative director at a top advertising agency.");
    },

    // ============ Ad Copy ============

    async generate_ad_copy(
      ctx: SkillContext,
      {
        company_name,
        primary_products,
        tagline,
        years_in_business,
        geographic_coverage,
        location,
        local_keywords,
        services_products,
        value_propositions,
        statistics,
        audience_segment,
        shopping_need,
        pain_point,
        audience_type,
        platform,
        brand_voice,
        creative_insights,
      }: {
        company_name: string;
        primary_products: string;
        tagline?: string;
        years_in_business?: string;
        geographic_coverage?: string;
        location?: string;
        local_keywords?: string;
        services_products?: string;
        value_propositions?: string;
        statistics?: string;
        audience_segment: string;
        shopping_need?: string;
        pain_point?: string;
        audience_type?: string;
        platform?: string;
        brand_voice?: string;
        creative_insights?: string;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.AD_COPY_RESEARCH, {
        company_name,
        primary_products,
        tagline: tagline || "Not provided",
        years_in_business: years_in_business || "Not specified",
        geographic_coverage: geographic_coverage || "Local",
        location: location || "Not specified",
        local_keywords: local_keywords || "Not provided",
        services_products: services_products || primary_products,
        value_propositions: value_propositions || "Quality products at great prices",
        statistics: statistics || "Not provided",
        audience_segment,
        shopping_need: shopping_need || "Quality products",
        pain_point: pain_point || "Finding reliable products",
        audience_type: audience_type || "B2C",
        platform: platform || "Facebook",
        brand_voice: brand_voice || "Professional",
        creative_insights: creative_insights || ""
      });

      return aiGenerateJSON(ctx, prompt, "You are an expert direct-response copywriter specializing in Facebook/Instagram ads.");
    },

    // ============ WhatsApp/CTWA Copy ============

    async generate_whatsapp_copy(
      ctx: SkillContext,
      {
        product_name,
        product_description,
        price,
        store_name,
        location,
        angle,
      }: {
        product_name: string;
        product_description: string;
        price?: string;
        store_name: string;
        location?: string;
        angle?: string;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.WHATSAPP_COPY, {
        product_name,
        product_description,
        price: price || "Contact for price",
        store_name,
        location: location || "Not specified",
        angle: angle || "Conversational, helpful"
      });

      return aiGenerateJSON(ctx, prompt, "You are a conversational marketing expert specializing in WhatsApp commerce.");
    },

    // ============ Image Prompts ============

    async generate_image_prompts(
      ctx: SkillContext,
      {
        campaign_name,
        product_description,
        target_audience,
        hook_type,
        hook_text,
        emotion,
        visual_hint,
        headline,
        primary_text,
      }: {
        campaign_name: string;
        product_description: string;
        target_audience: string;
        hook_type: string;
        hook_text: string;
        emotion?: string;
        visual_hint?: string;
        headline?: string;
        primary_text?: string;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.IMAGE_PROMPT, {
        campaign_name,
        product_description,
        target_audience: typeof target_audience === 'object' ? JSON.stringify(target_audience) : target_audience,
        hook_type,
        hook_text,
        emotion: emotion || "Engaging",
        visual_hint: visual_hint || "No specific direction",
        headline: headline || "No headline yet",
        primary_text: primary_text || "No primary text yet"
      });

      return aiGenerateJSON(ctx, prompt, "You are an expert visual director specializing in Meta advertising creatives.");
    },

    // ============ Actual Image Generation (GPT-Image-2.5) ============

    async generate_image(
      ctx: SkillContext,
      {
        prompt,
        dimensions,
        style,
      }: {
        prompt: string;
        dimensions?: string;
        style?: string;
      }
    ) {
      const size = mapDimensionsToSize(dimensions || "square");
      const result = await generateImageWithOpenAI(
        prompt,
        size,
        "hd",
        style === "ugc" ? "natural" : "vivid"
      );

      return {
        image_url: result.url,
        prompt_used: result.revised_prompt,
        dimensions: dimensions || "square",
        model: "gpt-image-2.5",
      };
    },

    async generate_image_from_concept(
      ctx: SkillContext,
      {
        campaign_name,
        product_description,
        target_audience,
        angle,
        headline,
        dimensions,
      }: {
        campaign_name: string;
        product_description: string;
        target_audience: string;
        angle: any;
        headline?: string;
        dimensions?: string;
      }
    ) {
      // First generate image prompts using the visual director template
      const imageConcepts = await adCreator.actions.generate_image_prompts(ctx, {
        campaign_name,
        product_description,
        target_audience,
        hook_type: angle.angle_name || angle.name,
        hook_text: angle.value_proposition || angle.hook,
        emotion: angle.emotion_target,
        visual_hint: angle.visual_direction,
        headline,
      });

      // Generate actual image from the first concept
      const firstConcept = imageConcepts.image_concepts?.[0];
      if (!firstConcept) {
        throw new Error("Failed to generate image concepts");
      }

      const image = await adCreator.actions.generate_image(ctx, {
        prompt: firstConcept.ai_image_prompt,
        dimensions,
        style: firstConcept.visual_style,
      });

      return {
        ...image,
        concept: firstConcept,
      };
    },

    // ============ Video Concept ============

    async generate_video_concept(
      ctx: SkillContext,
      {
        campaign_name,
        product_description,
        target_audience,
        hook_type,
        hook_text,
        emotion,
        headline,
        primary_text,
        video_length,
      }: {
        campaign_name: string;
        product_description: string;
        target_audience: string;
        hook_type: string;
        hook_text: string;
        emotion?: string;
        headline?: string;
        primary_text?: string;
        video_length?: number;
      }
    ) {
      const prompt = fillTemplate(PROMPTS.VIDEO_CONCEPT, {
        campaign_name,
        product_description,
        target_audience: typeof target_audience === 'object' ? JSON.stringify(target_audience) : target_audience,
        hook_type,
        hook_text,
        emotion: emotion || "Engaging",
        headline: headline || "No headline yet",
        primary_text: primary_text || "No primary text yet",
        video_length: video_length || 15
      });

      return aiGenerateJSON(ctx, prompt, "You are an expert video creative director for Meta advertising.");
    },

    // ============ Full Campaign Generation ============

    async generate_full_campaign(
      ctx: SkillContext,
      {
        company_name,
        product_name,
        product_description,
        product_price,
        store_name,
        target_country,
        location,
        campaign_goal,
        brand_voice,
        brand_colors,
        budget,
        niche,
        website_url,
      }: {
        company_name?: string;
        product_name: string;
        product_description: string;
        product_price?: number;
        store_name: string;
        target_country: string;
        location?: string;
        campaign_goal: string;
        brand_voice: string;
        brand_colors?: string[];
        budget: number;
        niche?: string;
        website_url?: string;
      }
    ) {
      const name = company_name || store_name;

      // 1. Market Research
      const market = await adCreator.actions.research_market(ctx, {
        company_name: name,
        product_description,
        niche: niche || "retail",
        target_country,
        website_url,
      });

      // 2. Generate Angles
      const angles = await adCreator.actions.generate_angles(ctx, {
        campaign_name: `${product_name} Campaign`,
        objective: campaign_goal,
        product_description,
        target_audience: JSON.stringify(market.audience_insights || {}),
        location,
        keywords: JSON.stringify(market.keywords || {}),
        market_research: JSON.stringify(market),
        num_angles: 5,
      });

      // 3. Generate Ad Copy for top angle
      const topAngle = angles.angles?.[0] || angles[0];
      const adCopy = await adCreator.actions.generate_ad_copy(ctx, {
        company_name: name,
        primary_products: product_name,
        location,
        audience_segment: market.audience_insights?.demographics || "General audience",
        pain_point: market.audience_insights?.pain_points?.[0] || "Finding quality products",
        platform: "Facebook",
        brand_voice,
        statistics: JSON.stringify(market.market_size || {}),
      });

      // 4. Generate Image
      const image = await adCreator.actions.generate_image_from_concept(ctx, {
        campaign_name: `${product_name} Campaign`,
        product_description,
        target_audience: JSON.stringify(market.audience_insights || {}),
        angle: topAngle,
        headline: adCopy.headlines?.[0]?.text,
        dimensions: "square",
      });

      // 5. Assemble ad set
      const adSet = {
        name: `${product_name} - ${topAngle.angle_name || "Main"}`,
        ads: [
          {
            name: `${topAngle.angle_name || "Main"} - V1`,
            creative: {
              headline: adCopy.headlines?.[0]?.text,
              body: adCopy.primary_text?.short,
              description: adCopy.descriptions?.[0],
              call_to_action: adCopy.call_to_action,
              image_url: image.image_url,
            },
          },
        ],
        targeting: {
          countries: [target_country],
          age_min: market.audience_insights?.demographics?.age_min || 18,
          age_max: market.audience_insights?.demographics?.age_max || 65,
        },
        budget_amount: budget,
        budget_type: "daily",
      };

      return {
        market_research: market,
        angles: angles.angles || angles,
        ad_copy: adCopy,
        image,
        ad_set: adSet,
        ready_for_launch: true,
      };
    },
  },
};

export default adCreator;
