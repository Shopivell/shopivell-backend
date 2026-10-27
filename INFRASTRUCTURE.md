# Shopivell Backend Infrastructure Audit

## 1. Redis Caching

### What's Built
- Full Redis client with connection pooling (`utils/cache.py`)
- Decorators: `@cached` (sync) and `@cached_async` (async) — defined but **never used**
- `CacheInvalidator` helper for entity-based invalidation (product, store, user, order, campaign)
- `CacheMiddleware` for auto-caching GET responses — defined but **not registered in main.py**
- TTL presets: SHORT (60s), MEDIUM (5min), LONG (1hr), DAY (24hr)

### Where Redis IS Used
| Module | What's cached | TTL |
|--------|--------------|-----|
| `market_research_agent` | Scrape results, competitors, trends, keywords | 1 hour |
| `competitive_intelligence_agent` | Categories, competitors, keywords | 24 hours |
| `calendar_engine` | Public holidays | 7 days |

### Where Redis is NOT Used (but should be)
| Module | Why it needs caching |
|--------|---------------------|
| Products router | Most read-heavy endpoint, product lists queried constantly |
| Stores router | Store data rarely changes, high read frequency |
| Orders router | Order lists queried often from dashboard |
| Analytics router | Expensive aggregation queries |
| Customers router | Customer lists queried frequently |
| Content router | Templates and content rarely change |

### Action Items
1. Register `CacheMiddleware` in `main.py` (currently commented out at line 117)
2. Add `@cached` decorators to read-heavy router endpoints
3. Call `CacheInvalidator` on write operations (create/update/delete)

---

## 2. MinIO Object Storage

### What's Built
- MinIO client singleton in `modules/assets/service.py`
- Auto bucket creation with public read policy
- File-serving proxy at `GET /api/assets/file/{path}`
- URL generation via `_get_minio_url()` → `{API_PUBLIC_URL}/api/assets/file/{object_name}`
- Fallback chain: MinIO → Cloudinary → local filesystem

### Where MinIO IS Used
| Module | Upload pattern | Fallback |
|--------|---------------|----------|
| `assets/service.py` | `stores/{store_id}/assets/{uuid}_{filename}` | Cloudinary → local |
| `assets/router.py` | Upload endpoints + file serving proxy | Cloudinary → local |
| `agents/media_generator_agent.py` | `{folder}/generated_{uuid}.png` | Cloudinary |
| `stores/scraping_service.py` | `shopivell/screenshots/{uuid}_{filename}` | Local only |

### Where Cloudinary is STILL Hardcoded (needs migration to MinIO)
| Module | File | Issue |
|--------|------|-------|
| `content/template/router.py` | Lines 331-350 | `cloudinary.uploader.upload()` called directly, NO MinIO fallback |
| `admin/router.py` | Line 553 | Reads `cloudinary_secure_url` field — assumes Cloudinary URLs |

### Action Items
1. Update `content/template/router.py` to use MinIO (same pattern as media_generator_agent)
2. Ensure `admin/router.py` handles both MinIO and Cloudinary URLs
3. Set env vars in Dokploy: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `API_PUBLIC_URL`

---

## 3. Pagination

### Pagination Styles in Use (inconsistent)
- `skip/limit` — products, orders, customers, analytics, marketing, stores, whatsapp
- `page/page_size` — admin, feedback, notifications, returns, reviews
- `page/size` — assets, campaigns

### Endpoints WITH Pagination (good)
| Module | Endpoint | Style |
|--------|----------|-------|
| products | `get_products`, `get_inventory_items` | skip/limit |
| orders | `get_orders` | skip/limit |
| customers | `get_customers`, `get_segments` | skip/limit |
| admin | `list_users`, `list_stores`, `list_campaigns`, `list_assets` | page/page_size |
| analytics | `get_platforms`, `get_reports` | skip/limit |
| marketing | `get_campaigns`, `get_ad_sets`, `get_ads` | skip/limit |
| agents | `get_campaigns` | skip/limit |
| assets | `get_store_assets` | page/size |
| business | `get_facebook_pages_list`, `get_instagram_accounts` | skip/limit |
| delivery | `list_deliveries` | skip/limit |
| feedback | `list_feedback` | page/page_size |
| notifications | `get_notifications` | page/page_size |
| reviews | `get_product_reviews`, `get_store_reviews` | page/page_size |
| returns | `get_store_returns` | page/page_size |
| whatsapp | `get_messages`, `get_conversations`, `get_leads` | mixed |
| stores | `get_stores_by_owner` | skip/limit |
| procurement | `list_store_orders` | skip/limit |

### Endpoints MISSING Pagination (needs fix)

#### HIGH Priority (can return large datasets)
| Module | Endpoint | Issue |
|--------|----------|-------|
| products | `get_collections` | Returns ALL collections, no limit |
| products | `get_collection_products` | Returns ALL products in collection |
| accounting | `list_accounts` | Returns ALL accounts |
| delivery | `list_zones` | Returns ALL zones |
| delivery | `list_drivers` | Returns ALL drivers |
| delivery | `list_vehicles` | Returns ALL vehicles |

#### MEDIUM Priority
| Module | Endpoint | Issue |
|--------|----------|-------|
| agents | `get_ad_copies` | All ad copies for campaign |
| agents | `get_creative_angles` | All angles for campaign |
| agents | `get_market_research` | All research for campaign |
| agency | `list_agencies` | All agencies |
| admin | `list_admins` | All admin users |
| micro_strategy | `list_strategies` | All strategies |
| micro_strategy | `list_pixel_trackers` | All trackers |
| procurement | `list_suppliers` | All active suppliers |
| referral | `list_referrals` | All referrals |
| social | `get_facebook_connections` | All connections |
| whatsapp | `get_whatsapp_accounts` | All accounts |
| website_builder | `list_websites` | All websites |
| pos | `get_active_sessions` | All active POS sessions |

### Action Items
1. Standardize on `skip/limit` pattern across ALL modules
2. Add pagination to all 17+ missing endpoints
3. Set max limit cap (e.g., `limit: int = Query(50, ge=1, le=500)`)
4. Always return `total_count` in list responses for frontend pagination

---

## Environment Variables Required (Dokploy)

```env
# MinIO
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=<key>
MINIO_SECRET_KEY=<secret>
MINIO_BUCKET=shopivell-assets
MINIO_USE_SSL=false
API_PUBLIC_URL=https://api.shopivell.com/v1

# Redis
REDIS_URL=redis://redis:6379/0

# APIs
SERPER_API_KEY=<key>
TAVILY_API_KEY=<key>
DATAFORSEO_LOGIN=<email>
DATAFORSEO_PASSWORD=<password>
OPENROUTER_API_KEY=<key>
FACEBOOK_APP_ID=<id>
FACEBOOK_APP_SECRET=<secret>
```
