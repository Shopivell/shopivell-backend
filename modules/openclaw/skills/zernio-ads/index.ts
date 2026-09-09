import { SkillContext } from "@openclaw/sdk";
import crypto from "crypto";

const ZERNIO_BASE_URL = "https://zernio.com/api/v1";

async function zernioRequest(
  ctx: SkillContext,
  method: string,
  endpoint: string,
  body?: any
) {
  const apiKey = ctx.env.ZERNIO_API_KEY;
  if (!apiKey) throw new Error("ZERNIO_API_KEY not configured");

  const response = await fetch(`${ZERNIO_BASE_URL}${endpoint}`, {
    method,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Zernio API error: ${response.status} - ${error}`);
  }

  return response.json();
}

function hashForCAPI(value: string): string {
  return crypto.createHash("sha256").update(value.toLowerCase().trim()).digest("hex");
}

export const zernioAds = {
  name: "zernio-ads",
  description: "Manage Meta Ads via Zernio API with CTWA and offline conversions",

  actions: {
    // ============ Profile Management ============

    async create_store_profile(
      ctx: SkillContext,
      { store_id, store_name }: { store_id: string; store_name: string }
    ) {
      return zernioRequest(ctx, "POST", "/profiles", {
        external_id: store_id,
        name: store_name,
      });
    },

    async get_store_profile(
      ctx: SkillContext,
      { store_id }: { store_id: string }
    ) {
      return zernioRequest(ctx, "GET", `/profiles/external/${store_id}`);
    },

    async get_oauth_url(
      ctx: SkillContext,
      {
        profile_id,
        redirect_url,
        scopes,
      }: { profile_id: string; redirect_url: string; scopes?: string[] }
    ) {
      const defaultScopes = [
        "ads_management",
        "ads_read",
        "business_management",
        "pages_read_engagement",
        "whatsapp_business_management",
        "whatsapp_business_messaging",
      ];
      return zernioRequest(ctx, "POST", `/profiles/${profile_id}/oauth`, {
        redirect_url,
        scopes: scopes || defaultScopes,
      });
    },

    async list_connected_accounts(
      ctx: SkillContext,
      { profile_id }: { profile_id: string }
    ) {
      return zernioRequest(ctx, "GET", `/profiles/${profile_id}/accounts`);
    },

    // ============ Campaign Management ============

    async create_campaign(
      ctx: SkillContext,
      params: {
        profile_id: string;
        ad_account_id: string;
        name: string;
        goal: string;
        budget_amount: number;
        budget_type: string;
        start_date?: string;
        end_date?: string;
        targeting: {
          countries: string[];
          age_min?: number;
          age_max?: number;
          interests?: { id: string; name: string }[];
          custom_audience_ids?: string[];
        };
        creative: {
          headline: string;
          body: string;
          image_url: string;
          call_to_action: string;
          link_url: string;
        };
        placements?: string[];
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${params.profile_id}/campaigns`,
        params
      );
    },

    async create_ctwa_campaign(
      ctx: SkillContext,
      params: {
        profile_id: string;
        ad_account_id: string;
        whatsapp_number: string;
        name: string;
        budget_amount: number;
        budget_type: string;
        targeting: {
          countries: string[];
          age_min?: number;
          age_max?: number;
          interests?: { id: string; name: string }[];
        };
        creative: {
          headline: string;
          body: string;
          image_url: string;
          welcome_message: string;
        };
        placements?: string[];
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${params.profile_id}/campaigns/ctwa`,
        {
          ...params,
          goal: "messages",
          call_to_action: "WHATSAPP_MESSAGE",
        }
      );
    },

    async list_campaigns(
      ctx: SkillContext,
      {
        profile_id,
        status,
        campaign_type,
      }: { profile_id: string; status?: string; campaign_type?: string }
    ) {
      const query = new URLSearchParams();
      if (status) query.set("status", status);
      if (campaign_type) query.set("type", campaign_type);
      return zernioRequest(
        ctx,
        "GET",
        `/profiles/${profile_id}/campaigns?${query}`
      );
    },

    async update_campaign(
      ctx: SkillContext,
      {
        ad_id,
        updates,
      }: { ad_id: string; updates: { budget?: number; status?: string } }
    ) {
      return zernioRequest(ctx, "PATCH", `/ads/${ad_id}`, updates);
    },

    async pause_ad(
      ctx: SkillContext,
      { ad_id, reason }: { ad_id: string; reason?: string }
    ) {
      return zernioRequest(ctx, "PATCH", `/ads/${ad_id}`, {
        status: "PAUSED",
        pause_reason: reason,
      });
    },

    async scale_budget(
      ctx: SkillContext,
      {
        ad_id,
        percentage,
        max_budget,
      }: { ad_id: string; percentage: number; max_budget?: number }
    ) {
      return zernioRequest(ctx, "POST", `/ads/${ad_id}/scale`, {
        percentage,
        max_budget,
      });
    },

    // ============ Analytics ============

    async get_insights(
      ctx: SkillContext,
      {
        ad_id,
        date_preset,
        breakdowns,
      }: { ad_id: string; date_preset: string; breakdowns?: string[] }
    ) {
      const query = new URLSearchParams({ date_preset });
      if (breakdowns) query.set("breakdowns", breakdowns.join(","));
      return zernioRequest(ctx, "GET", `/ads/${ad_id}/insights?${query}`);
    },

    async get_all_store_insights(
      ctx: SkillContext,
      { profile_id, date_preset }: { profile_id: string; date_preset: string }
    ) {
      return zernioRequest(
        ctx,
        "GET",
        `/profiles/${profile_id}/insights?date_preset=${date_preset}`
      );
    },

    async get_ctwa_insights(
      ctx: SkillContext,
      { campaign_id, date_preset }: { campaign_id: string; date_preset: string }
    ) {
      return zernioRequest(
        ctx,
        "GET",
        `/campaigns/${campaign_id}/ctwa-insights?date_preset=${date_preset}`
      );
    },

    // ============ WhatsApp + Offline Conversions ============

    async connect_whatsapp_account(
      ctx: SkillContext,
      {
        profile_id,
        waba_id,
        phone_number_id,
      }: { profile_id: string; waba_id: string; phone_number_id: string }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/whatsapp`,
        { waba_id, phone_number_id }
      );
    },

    async send_offline_conversion(
      ctx: SkillContext,
      {
        profile_id,
        pixel_id,
        event_name,
        event_time,
        user_data,
        custom_data,
      }: {
        profile_id: string;
        pixel_id: string;
        event_name: string;
        event_time: number;
        user_data: {
          phone?: string;
          email?: string;
          external_id?: string;
          client_ip_address?: string;
          client_user_agent?: string;
          fbc?: string;
          fbp?: string;
        };
        custom_data?: {
          lead_score?: number;
          lead_quality?: string;
          value?: number;
          currency?: string;
          content_name?: string;
          content_ids?: string[];
        };
      }
    ) {
      // Hash PII data for CAPI
      const hashedUserData: any = {};
      if (user_data.phone) hashedUserData.ph = [hashForCAPI(user_data.phone.replace(/\D/g, ""))];
      if (user_data.email) hashedUserData.em = [hashForCAPI(user_data.email)];
      if (user_data.external_id) hashedUserData.external_id = [hashForCAPI(user_data.external_id)];
      if (user_data.client_ip_address) hashedUserData.client_ip_address = user_data.client_ip_address;
      if (user_data.client_user_agent) hashedUserData.client_user_agent = user_data.client_user_agent;
      if (user_data.fbc) hashedUserData.fbc = user_data.fbc;
      if (user_data.fbp) hashedUserData.fbp = user_data.fbp;

      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/conversions`,
        {
          pixel_id,
          data: [
            {
              event_name,
              event_time,
              action_source: "chat",
              user_data: hashedUserData,
              custom_data,
            },
          ],
        }
      );
    },

    async send_lead_event(
      ctx: SkillContext,
      {
        profile_id,
        pixel_id,
        phone,
        lead_score,
        lead_quality,
        conversation_id,
        ad_id,
      }: {
        profile_id: string;
        pixel_id: string;
        phone: string;
        lead_score: number;
        lead_quality: string;
        conversation_id?: string;
        ad_id?: string;
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/conversions`,
        {
          pixel_id,
          data: [
            {
              event_name: "Lead",
              event_time: Math.floor(Date.now() / 1000),
              action_source: "chat",
              user_data: {
                ph: [hashForCAPI(phone.replace(/\D/g, ""))],
              },
              custom_data: {
                lead_score,
                lead_quality,
                content_name: conversation_id,
                content_ids: ad_id ? [ad_id] : undefined,
              },
            },
          ],
        }
      );
    },

    async send_purchase_event(
      ctx: SkillContext,
      {
        profile_id,
        pixel_id,
        phone,
        value,
        currency,
        order_id,
        product_ids,
      }: {
        profile_id: string;
        pixel_id: string;
        phone: string;
        value: number;
        currency: string;
        order_id: string;
        product_ids?: string[];
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/conversions`,
        {
          pixel_id,
          data: [
            {
              event_name: "Purchase",
              event_time: Math.floor(Date.now() / 1000),
              action_source: "chat",
              user_data: {
                ph: [hashForCAPI(phone.replace(/\D/g, ""))],
              },
              custom_data: {
                value,
                currency,
                order_id,
                content_ids: product_ids,
              },
            },
          ],
        }
      );
    },

    async get_conversion_stats(
      ctx: SkillContext,
      {
        profile_id,
        pixel_id,
        date_range,
      }: { profile_id: string; pixel_id: string; date_range: string }
    ) {
      return zernioRequest(
        ctx,
        "GET",
        `/profiles/${profile_id}/conversions/stats?pixel_id=${pixel_id}&date_range=${date_range}`
      );
    },

    // ============ Audience Management ============

    async create_custom_audience(
      ctx: SkillContext,
      {
        profile_id,
        ad_account_id,
        name,
        description,
      }: {
        profile_id: string;
        ad_account_id: string;
        name: string;
        description?: string;
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/audiences`,
        { ad_account_id, name, description, subtype: "CUSTOM" }
      );
    },

    async create_lookalike_audience(
      ctx: SkillContext,
      {
        profile_id,
        ad_account_id,
        source_audience_id,
        country,
        ratio,
      }: {
        profile_id: string;
        ad_account_id: string;
        source_audience_id: string;
        country: string;
        ratio: number;
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/audiences/lookalike`,
        { ad_account_id, source_audience_id, country, ratio }
      );
    },

    async create_whatsapp_audience(
      ctx: SkillContext,
      {
        profile_id,
        ad_account_id,
        name,
        min_lead_score,
        lead_quality,
      }: {
        profile_id: string;
        ad_account_id: string;
        name: string;
        min_lead_score?: number;
        lead_quality?: string[];
      }
    ) {
      return zernioRequest(
        ctx,
        "POST",
        `/profiles/${profile_id}/audiences/whatsapp-leads`,
        { ad_account_id, name, min_lead_score, lead_quality }
      );
    },

    async add_users_to_audience(
      ctx: SkillContext,
      {
        audience_id,
        users,
      }: { audience_id: string; users: { email?: string; phone?: string }[] }
    ) {
      const hashedUsers = users.map((u) => ({
        email: u.email ? hashForCAPI(u.email) : undefined,
        phone: u.phone ? hashForCAPI(u.phone.replace(/\D/g, "")) : undefined,
      }));
      return zernioRequest(ctx, "POST", `/audiences/${audience_id}/users`, {
        users: hashedUsers,
      });
    },

    // ============ Targeting ============

    async search_interests(
      ctx: SkillContext,
      { query }: { query: string }
    ) {
      return zernioRequest(
        ctx,
        "GET",
        `/targeting/interests?q=${encodeURIComponent(query)}`
      );
    },
  },
};

export default zernioAds;
