# Zernio Ads Manager

A comprehensive skill for managing Meta Ads (Facebook/Instagram) via Zernio API, including Click-to-WhatsApp (CTWA) ads with lead scoring and offline conversions.

## Description
Manage Meta ad campaigns for multiple stores (multi-tenant). Each store has its own Zernio Profile with connected Facebook/Instagram ad accounts. Supports Click-to-WhatsApp ads with AI-powered lead scoring and offline conversion tracking.

## Authentication
- **ZERNIO_API_KEY**: Bearer token for Zernio API (set in environment)
- Base URL: https://zernio.com/api/v1

## Multi-Tenant Model
- **One Profile per Store**: Each Shopivell store gets a unique Zernio profile
- **Profile contains**: Connected FB/IG accounts, ad accounts, campaigns, WhatsApp Business accounts
- **Pricing**: First 2 accounts free, then $6/account (3-10), $3/account (11-100), $1/account (101+)

## Actions

### Profile Management (Multi-Tenant)

#### create_store_profile
Create a new Zernio profile for a store when they sign up.
- Parameters:
  - store_id (string): Shopivell store ID
  - store_name (string): Store name for the profile
- Returns: profile_id, created_at

#### get_store_profile
Get the Zernio profile for a store.
- Parameters:
  - store_id (string): Shopivell store ID
- Returns: profile_id, name, connected_accounts[], whatsapp_accounts[]

#### get_oauth_url
Generate OAuth URL for a store to connect their Meta ad account.
- Parameters:
  - profile_id (string): Zernio profile ID
  - redirect_url (string): Where to redirect after OAuth
  - scopes (string[]): Required scopes (ads_management, whatsapp_business_management, etc.)
- Returns: auth_url

#### list_connected_accounts
List all connected Meta ad accounts for a store.
- Parameters:
  - profile_id (string): Zernio profile ID
- Returns: accounts[] with id, name, ad_account_id, status

### Campaign Management

#### create_campaign
Create a complete Meta ad campaign with ad sets and ads.
- Parameters:
  - profile_id (string): Zernio profile ID
  - ad_account_id (string): Meta ad account (act_xxx)
  - name (string): Campaign name
  - goal (string): traffic, conversions, lead_generation, engagement, messages
  - budget_amount (number): Budget in dollars
  - budget_type (string): daily or lifetime
  - start_date (string): ISO date
  - end_date (string): ISO date (optional)
  - targeting:
    - countries (string[]): Country codes
    - age_min (number): Minimum age
    - age_max (number): Maximum age
    - interests (object[]): Interest IDs and names
    - custom_audience_ids (string[]): Custom audience IDs
  - creative:
    - headline (string): Ad headline
    - body (string): Ad copy
    - image_url (string): Image URL
    - call_to_action (string): SHOP_NOW, LEARN_MORE, SIGN_UP, WHATSAPP_MESSAGE, etc.
    - link_url (string): Destination URL
  - placements (string[]): facebook_feeds, instagram_feeds, instagram_reels, etc.
- Returns: campaign_id, adset_id, ad_id, status

#### create_ctwa_campaign
Create a Click-to-WhatsApp campaign that drives conversations to WhatsApp.
- Parameters:
  - profile_id (string): Zernio profile ID
  - ad_account_id (string): Meta ad account (act_xxx)
  - whatsapp_number (string): WhatsApp Business number
  - name (string): Campaign name
  - budget_amount (number): Budget in dollars
  - budget_type (string): daily or lifetime
  - targeting:
    - countries (string[]): Country codes
    - age_min (number): Minimum age
    - age_max (number): Maximum age
    - interests (object[]): Interest IDs and names
  - creative:
    - headline (string): Ad headline
    - body (string): Ad copy encouraging WhatsApp conversation
    - image_url (string): Image URL
    - welcome_message (string): Auto-message when user clicks
  - placements (string[]): facebook_feeds, instagram_feeds, etc.
- Returns: campaign_id, adset_id, ad_id, whatsapp_flow_id

#### list_campaigns
List all campaigns for a store.
- Parameters:
  - profile_id (string): Zernio profile ID
  - status (string): active, paused, all
  - campaign_type (string): all, standard, ctwa (optional)
- Returns: campaigns[] with id, name, status, budget, metrics, type

#### update_campaign
Update campaign budget, status, or settings.
- Parameters:
  - ad_id (string): Ad/campaign/adset ID
  - updates:
    - budget (number): New budget
    - status (string): ACTIVE, PAUSED
- Returns: success, new_values

#### pause_ad
Pause an underperforming ad.
- Parameters:
  - ad_id (string): Ad ID
  - reason (string): Reason for pausing
- Returns: success

#### scale_budget
Increase budget for a winning ad.
- Parameters:
  - ad_id (string): Ad ID
  - percentage (number): Percentage increase (e.g., 20 for +20%)
  - max_budget (number): Maximum budget cap
- Returns: success, old_budget, new_budget

### Analytics

#### get_insights
Get performance metrics for an ad/campaign.
- Parameters:
  - ad_id (string): Ad/campaign/adset ID
  - date_preset (string): today, yesterday, last_7d, last_30d, this_month
  - breakdowns (string[]): age, gender, country, device (optional)
- Returns:
  - spend
  - impressions
  - clicks
  - ctr (%)
  - cpc
  - cpm
  - conversions
  - roas (%)
  - cpa
  - messaging_conversations (for CTWA)
  - cost_per_conversation (for CTWA)

#### get_all_store_insights
Get performance metrics for all campaigns of a store.
- Parameters:
  - profile_id (string): Zernio profile ID
  - date_preset (string): today, yesterday, last_7d, last_30d
- Returns: campaigns[] with metrics

#### get_ctwa_insights
Get Click-to-WhatsApp specific metrics.
- Parameters:
  - campaign_id (string): CTWA campaign ID
  - date_preset (string): today, yesterday, last_7d, last_30d
- Returns:
  - messaging_conversations_started
  - cost_per_conversation
  - leads_qualified (from offline conversions)
  - lead_conversion_rate
  - cost_per_qualified_lead

### WhatsApp + Lead Scoring + Offline Conversions

#### connect_whatsapp_account
Connect a WhatsApp Business account to the profile.
- Parameters:
  - profile_id (string): Zernio profile ID
  - waba_id (string): WhatsApp Business Account ID
  - phone_number_id (string): Phone number ID
- Returns: success, connected_number

#### send_offline_conversion
Send an offline conversion event to Meta (like Pixel but for WhatsApp messages).
Used to tell Meta when a WhatsApp lead converts so it can optimize for quality leads.
- Parameters:
  - profile_id (string): Zernio profile ID
  - pixel_id (string): Meta Pixel ID for the ad account
  - event_name (string): Lead, Purchase, CompleteRegistration, AddToCart, etc.
  - event_time (number): Unix timestamp of conversion
  - user_data:
    - phone (string): User phone number (hashed)
    - email (string): User email (hashed, optional)
    - external_id (string): Your internal user ID (hashed)
    - client_ip_address (string): User IP (optional)
    - client_user_agent (string): User agent (optional)
    - fbc (string): Facebook click ID (optional)
    - fbp (string): Facebook browser ID (optional)
  - custom_data:
    - lead_score (number): AI-assigned lead score (0-100)
    - lead_quality (string): hot, warm, cold
    - value (number): Monetary value of conversion
    - currency (string): Currency code (USD, ZWL, etc.)
    - content_name (string): Product/service name
    - content_ids (string[]): Product IDs
- Returns: events_received, fbtrace_id

#### send_lead_event
Shorthand for sending a Lead event with scoring data.
- Parameters:
  - profile_id (string): Zernio profile ID
  - pixel_id (string): Meta Pixel ID
  - phone (string): Lead phone number
  - lead_score (number): AI-assigned score (0-100)
  - lead_quality (string): hot, warm, cold
  - conversation_id (string): WhatsApp conversation ID
  - ad_id (string): Source ad ID (optional)
- Returns: events_received, fbtrace_id

#### send_purchase_event
Send a purchase conversion from a WhatsApp lead.
- Parameters:
  - profile_id (string): Zernio profile ID
  - pixel_id (string): Meta Pixel ID
  - phone (string): Customer phone number
  - value (number): Purchase value
  - currency (string): Currency code
  - order_id (string): Order reference
  - product_ids (string[]): Purchased product IDs
- Returns: events_received, fbtrace_id

#### get_conversion_stats
Get stats on offline conversions sent.
- Parameters:
  - profile_id (string): Zernio profile ID
  - pixel_id (string): Meta Pixel ID
  - date_range (string): last_7d, last_30d
- Returns:
  - events_sent
  - events_matched
  - match_rate
  - by_event_type: {Lead, Purchase, etc.}

### Audience Management

#### create_custom_audience
Create a customer list audience.
- Parameters:
  - profile_id (string): Zernio profile ID
  - ad_account_id (string): Meta ad account
  - name (string): Audience name
  - description (string): Description
- Returns: audience_id

#### create_lookalike_audience
Create a lookalike audience from an existing audience.
- Parameters:
  - profile_id (string): Zernio profile ID
  - ad_account_id (string): Meta ad account
  - source_audience_id (string): Seed audience
  - country (string): Target country code
  - ratio (number): 0.01-0.20 (1%-20% similarity)
- Returns: audience_id

#### create_whatsapp_audience
Create an audience from WhatsApp leads by quality.
- Parameters:
  - profile_id (string): Zernio profile ID
  - ad_account_id (string): Meta ad account
  - name (string): Audience name
  - min_lead_score (number): Minimum lead score (0-100)
  - lead_quality (string[]): hot, warm, cold (optional filter)
- Returns: audience_id

#### add_users_to_audience
Add users to a custom audience.
- Parameters:
  - audience_id (string): Audience ID
  - users (object[]): Array of {email, phone}
- Returns: success, received_count

### Targeting

#### search_interests
Search Meta interest targeting options.
- Parameters:
  - query (string): Search term
- Returns: interests[] with id, name, audience_size

## Built-in Rules (for Optimizer Plugin)

### scale_winner
- Conditions: ROAS >= target x 1.25 for 3 consecutive days
- Action: Increase budget +20%
- Cooldown: 6 hours
- Max triggers: 1/day

### kill_loser
- Conditions: CPA > target x 2 AND 0 conversions AND impressions >= 2000
- Action: Cut budget 50%
- Cooldown: 12 hours
- Max triggers: 1/day

### pause_no_spend
- Conditions: $0 spend for 24 hours
- Action: Pause
- Cooldown: 24 hours

### creative_fatigue
- Conditions: Frequency > 3 AND CTR decline > 30% for 3 days
- Action: Pause and notify

### ctwa_low_quality
- Conditions: cost_per_qualified_lead > target x 2 for 3 days
- Action: Reduce budget 30% and notify
- Note: Uses offline conversion data for qualified lead count

### ctwa_high_performer
- Conditions: cost_per_qualified_lead < target x 0.7 for 3 days
- Action: Increase budget 25%
- Note: Scale ads that bring quality WhatsApp leads

## Example Usage

### Standard Campaign
```javascript
const campaign = await zernioAds.create_campaign({
  profile_id: "store_123_profile",
  ad_account_id: "act_1234567890",
  name: "Summer Sale Campaign",
  goal: "conversions",
  budget_amount: 50,
  budget_type: "daily",
  targeting: {
    countries: ["ZW", "ZA"],
    age_min: 25,
    age_max: 55,
    interests: [{ id: "6003139266461", name: "Online shopping" }]
  },
  creative: {
    headline: "Summer Sale - 50% Off!",
    body: "Limited time offer. Shop now and save big.",
    image_url: "https://cdn.shopivell.com/store123/summer-sale.jpg",
    call_to_action: "SHOP_NOW",
    link_url: "https://store.shopivell.com/summer-sale"
  },
  placements: ["facebook_feeds", "instagram_feeds", "instagram_reels"]
});
```

### Click-to-WhatsApp Campaign
```javascript
const ctwaCampaign = await zernioAds.create_ctwa_campaign({
  profile_id: "store_123_profile",
  ad_account_id: "act_1234567890",
  whatsapp_number: "+263771234567",
  name: "Chat With Us - Summer Sale",
  budget_amount: 30,
  budget_type: "daily",
  targeting: {
    countries: ["ZW"],
    age_min: 18,
    age_max: 45,
    interests: [{ id: "6003139266461", name: "Online shopping" }]
  },
  creative: {
    headline: "Questions? Chat with us!",
    body: "Get personalized help with your order. Tap to WhatsApp now.",
    image_url: "https://cdn.shopivell.com/store123/whatsapp-cta.jpg",
    welcome_message: "Hi! Thanks for reaching out about our Summer Sale. How can I help you today?"
  },
  placements: ["facebook_feeds", "instagram_feeds"]
});
```

### Send Lead Event (After AI Scores the Lead)
```javascript
// When chatbot qualifies a lead, send to Meta for optimization
await zernioAds.send_lead_event({
  profile_id: "store_123_profile",
  pixel_id: "123456789012345",
  phone: "+263771234567",
  lead_score: 85,
  lead_quality: "hot",
  conversation_id: "wamid.abc123",
  ad_id: "23456789012345"
});
```

### Send Purchase Event
```javascript
// When WhatsApp lead makes a purchase
await zernioAds.send_purchase_event({
  profile_id: "store_123_profile",
  pixel_id: "123456789012345",
  phone: "+263771234567",
  value: 150.00,
  currency: "USD",
  order_id: "ORD-12345",
  product_ids: ["PROD-001", "PROD-002"]
});
```

### Get CTWA Performance with Lead Quality
```javascript
const ctwaInsights = await zernioAds.get_ctwa_insights({
  campaign_id: ctwaCampaign.campaign_id,
  date_preset: "last_7d"
});

console.log(ctwaInsights);
// {
//   messaging_conversations_started: 150,
//   cost_per_conversation: 0.35,
//   leads_qualified: 45,  // From offline conversions
//   lead_conversion_rate: 0.30,  // 30% of conversations become qualified leads
//   cost_per_qualified_lead: 1.17  // $52.50 spent / 45 qualified leads
// }
```

## Environment Variables
- ZERNIO_API_KEY (required)
- SHOPIVELL_API_URL (for store data)

## WhatsApp Lead Scoring Flow

1. **Ad Click**: User clicks CTWA ad, lands in WhatsApp
2. **Chatbot Conversation**: AI chatbot qualifies the lead
3. **Lead Scoring**: AI assigns score (0-100) based on:
   - Purchase intent signals
   - Budget indicators
   - Timeline urgency
   - Engagement quality
4. **Send to Meta**: Call `send_lead_event()` with score
5. **Meta Optimization**: Meta learns which audiences produce quality leads
6. **Better Targeting**: Future ad delivery prioritizes high-quality lead profiles

This creates a feedback loop where Meta optimizes for QUALITY leads, not just any conversation.
