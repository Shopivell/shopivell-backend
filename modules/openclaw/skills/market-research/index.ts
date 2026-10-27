import { SkillContext } from "@openclaw/sdk";

/**
 * market-research skill (the agentic/reasoning layer).
 *
 * Deterministic data gathering lives in the Shopivell backend
 * (MarketResearchService, exposed at /v1/api/research/*). This skill CALLS
 * those APIs, then uses the model to reason over the raw data: structured
 * business understanding, SWOT, audience insights, and creative angles.
 *
 * Env:
 *   SHOPIVELL_API_URL      e.g. https://api.shopivell.com/v1
 *   RESEARCH_SERVICE_TOKEN shared token sent as X-Research-Token
 */

const API = process.env.SHOPIVELL_API_URL || "https://api.shopivell.com/v1";
const TOKEN = process.env.RESEARCH_SERVICE_TOKEN || "";

async function research(path: string, body: Record<string, unknown>): Promise<any> {
  const r = await fetch(`${API}/api/research/${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Research-Token": TOKEN,
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`research/${path} -> ${r.status}`);
  return r.json();
}

async function aiJSON<T = any>(ctx: SkillContext, prompt: string, system?: string): Promise<T> {
  const raw = await ctx.ai.generate({ prompt, system });
  let s = String(raw).trim();
  s = s.replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  try {
    return JSON.parse(s);
  } catch {
    const m = s.match(/\{[\s\S]*\}/);
    if (m) return JSON.parse(m[0]);
    return {} as T;
  }
}

export const marketResearch = {
  name: "market-research",
  description:
    "End-to-end market research: pulls real competitors, keyword demand and " +
    "trends from the Shopivell backend, then reasons over them (structured " +
    "business profile, SWOT, audience insights, creative angles).",

  actions: {
    /**
     * Full analysis for a business/website.
     * Params: url, content (scraped text, optional), business_type, location,
     *         country_code, company_name, products[]
     */
    async analyze(
      ctx: SkillContext,
      {
        url,
        content,
        business_type,
        location,
        country_code,
        company_name,
        products,
      }: {
        url?: string;
        content?: string;
        business_type?: string;
        location?: string;
        country_code?: string;
        company_name?: string;
        products?: string[];
      }
    ) {
      // 1. Structured understanding of the business (backend LLM extraction).
      let structured: any = {};
      if (content) {
        try {
          structured = (await research("extract", { content, url: url || "" })).data || {};
        } catch (e) {
          /* extraction optional */
        }
      }

      const bizType = structured.industry || business_type || "business";
      const extractedProducts = (structured.services_products || [])
        .map((s: any) => s?.name)
        .filter(Boolean)
        .slice(0, 6);
      const finalProducts = extractedProducts.length ? extractedProducts : products || [];
      const seeds = (structured.keyword_seeds && structured.keyword_seeds.length
        ? structured.keyword_seeds
        : finalProducts) as string[];
      const country = country_code || "US";
      const loc = structured.geographic_coverage || location || "";
      const year = String(new Date().getFullYear());

      // 2. Deterministic data from the backend (parallel).
      const [comp, kw, tr] = await Promise.all([
        research("competitors", {
          business_type: bizType, location: loc, products: finalProducts,
          domain: url, country_code: country, company_name,
        }).catch(() => ({ competitors: [] })),
        research("keywords", { seeds, country_code: country }).catch(() => ({ keywords: [] })),
        research("trends", { industry: bizType, year }).catch(() => ({ trends: [] })),
      ]);

      const competitors = comp.competitors || [];
      const keywords = kw.keywords || [];
      const trends = tr.trends || [];

      // 3. Reason over the raw data (the agentic part).
      const reasoning = await aiJSON(
        ctx,
        `Business: ${company_name || ""} (${bizType})\n` +
          `Location: ${loc}\nProducts/services: ${finalProducts.join(", ")}\n\n` +
          `Competitors (name — snippet):\n` +
          competitors.slice(0, 10).map((c: any) => `- ${c.name}: ${(c.description || "").slice(0, 120)}`).join("\n") +
          `\n\nTop keywords: ${keywords.slice(0, 20).map((k: any) => k.keyword).join(", ")}\n\n` +
          `Trends:\n` + trends.slice(0, 5).map((t: any) => `- ${t.title}`).join("\n") +
          `\n\nReturn ONLY JSON: {"swot":{"strengths":[],"weaknesses":[],"opportunities":[],"threats":[]},` +
          `"audience_insights":{"demographics":"","psychographics":"","pain_points":[],"buying_triggers":[]},` +
          `"angles":[{"angle_name":"","value_proposition":"","emotion_target":"","visual_direction":""}]}`,
        "You are a senior marketing strategist. Use ONLY the data provided. Return valid JSON only."
      ).catch(() => ({}));

      return {
        business_type: bizType,
        company_name: structured.company_name || company_name || "",
        products: finalProducts,
        geographic_coverage: loc,
        competitors,
        keywords,
        trends,
        swot: (reasoning as any).swot || {},
        audience_insights: (reasoning as any).audience_insights || {},
        angles: (reasoning as any).angles || [],
      };
    },
  },
};

export default marketResearch;
