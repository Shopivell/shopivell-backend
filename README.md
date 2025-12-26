# Shopivell Backend

A production-ready, multi-tenant e-commerce platform backend built with FastAPI, featuring AI-powered marketing automation, comprehensive payment processing, and real-time analytics.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Documentation](#api-documentation)
- [Database Schema](#database-schema)
- [Caching Strategy](#caching-strategy)
- [Performance Optimization](#performance-optimization)
- [Security](#security)
- [Deployment](#deployment)
- [Contributing](#contributing)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Web App    │  │  Mobile App  │  │   Webhooks   │  │  Third Party │    │
│  │   (React)    │  │   (Future)   │  │   (PayNow)   │  │     APIs     │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
└─────────┼─────────────────┼─────────────────┼─────────────────┼────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API GATEWAY                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         NGINX / Load Balancer                         │  │
│  │                    (SSL Termination, Rate Limiting)                   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           APPLICATION LAYER                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                      FastAPI Application (Uvicorn)                    │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐     │  │
│  │  │   CORS     │  │  Auth JWT  │  │   Cache    │  │  Logging   │     │  │
│  │  │ Middleware │  │ Middleware │  │ Middleware │  │ Middleware │     │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                      │                                       │
│  ┌───────────────────────────────────┼───────────────────────────────────┐  │
│  │                          API ROUTERS (v1)                              │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │
│  │  │  Auth   │ │  Users  │ │ Stores  │ │Products │ │ Orders  │        │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │
│  │  │Customers│ │Analytics│ │Marketing│ │ Payment │ │ Assets  │        │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │
│  │  │WhatsApp │ │ Social  │ │ Content │ │ Agents  │ │Campaigns│        │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SERVICE LAYER                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Payment    │  │  AI/Agent   │  │Notification │  │  Analytics  │        │
│  │  Service    │  │  Service    │  │  Service    │  │  Service    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA LAYER                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐          │
│  │    PostgreSQL    │  │      Redis       │  │    Cloudinary    │          │
│  │   (Primary DB)   │  │     (Cache)      │  │  (Media Storage) │          │
│  │                  │  │                  │  │                  │          │
│  │  - Users         │  │  - Session Cache │  │  - Images        │          │
│  │  - Stores        │  │  - API Response  │  │  - Videos        │          │
│  │  - Products      │  │  - Rate Limiting │  │  - Assets        │          │
│  │  - Orders        │  │  - Pub/Sub       │  │                  │          │
│  │  - Payments      │  │                  │  │                  │          │
│  │  - pgvector      │  │                  │  │                  │          │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL INTEGRATIONS                                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐  │
│  │ OpenAI  │ │  Meta   │ │ PayNow  │ │ Stripe  │ │ PayPal  │ │WhatsApp │  │
│  │   API   │ │Ads API  │ │   API   │ │   API   │ │   API   │ │Bus. API │  │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘  │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                          │
│  │ Google  │ │Facebook │ │ Tavily  │ │  Gemini │                          │
│  │  OAuth  │ │  OAuth  │ │ Search  │ │   API   │                          │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Module Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MODULES OVERVIEW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  COMMERCE CORE                    USER & STORE MANAGEMENT                    │
│  ┌─────────────────────┐         ┌─────────────────────┐                    │
│  │ customers/          │         │ users/              │                    │
│  │ ├── models.py       │         │ ├── models.py       │                    │
│  │ ├── router.py       │         │ ├── auth_router.py  │                    │
│  │ └── schemas.py      │         │ └── schemas.py      │                    │
│  ├─────────────────────┤         ├─────────────────────┤                    │
│  │ orders/             │         │ stores/             │                    │
│  │ products/           │         │ agency/             │                    │
│  │ payment/            │         │ business/           │                    │
│  │ offers/             │         └─────────────────────┘                    │
│  │ requests/           │                                                     │
│  └─────────────────────┘                                                     │
│                                                                              │
│  MARKETING & AI                   CONTENT & SOCIAL                           │
│  ┌─────────────────────┐         ┌─────────────────────┐                    │
│  │ agents/             │         │ content/            │                    │
│  │ ├── market_research │         │ social/             │                    │
│  │ ├── creative_angles │         │ whatsapp/           │                    │
│  │ ├── ad_copy         │         │ assets/             │                    │
│  │ └── optimization    │         └─────────────────────┘                    │
│  ├─────────────────────┤                                                     │
│  │ marketing/          │         ANALYTICS & AUTOMATION                      │
│  │ campaigns/          │         ┌─────────────────────┐                    │
│  │ ad_generator/       │         │ analytics/          │                    │
│  └─────────────────────┘         │ automation/         │                    │
│                                  │ workflow/           │                    │
│                                  └─────────────────────┘                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Core Framework
| Technology | Version | Purpose |
|------------|---------|---------|
| FastAPI | 0.116.1 | Async web framework |
| Uvicorn | 0.35.0 | ASGI server |
| Python | 3.12+ | Runtime |

### Database & ORM
| Technology | Version | Purpose |
|------------|---------|---------|
| PostgreSQL | 15+ | Primary database |
| SQLAlchemy | 2.0.29 | ORM with type hints |
| psycopg2 | - | PostgreSQL driver |
| pgvector | - | Vector embeddings for AI |
| Redis | 5.0+ | Caching & session store |

### AI & Machine Learning
| Technology | Purpose |
|------------|---------|
| OpenAI GPT-4 | AI agents, embeddings |
| LangGraph | Agentic workflow orchestration |
| Google Gemini | Alternative AI for ad generation |
| Tavily | Web research agent |

### Payment Processing
| Provider | Region |
|----------|--------|
| PayNow (EcoCash/InnBucks) | Zimbabwe |
| Stripe | International |
| PayPal | International |

### External Services
| Service | Purpose |
|---------|---------|
| Cloudinary | Image/video CDN |
| AWS S3 | File storage |
| WhatsApp Business API | Messaging |
| Meta Ads API | Ad campaigns |

---

## Project Structure

```
Shopivell-backend/
├── main.py                    # Application entry point
├── database.py                # Database connection & session
├── dependencies.py            # FastAPI dependencies
├── config.py                  # Configuration management
├── requirements.txt           # Python dependencies
│
├── modules/                   # Feature modules
│   ├── users/                 # User authentication & management
│   │   ├── __init__.py
│   │   ├── models.py          # User, VerificationCode models
│   │   ├── auth_router.py     # Auth endpoints
│   │   ├── user_router.py     # User CRUD endpoints
│   │   └── schemas.py         # Pydantic schemas
│   │
│   ├── stores/                # Multi-tenant store management
│   ├── products/              # Product catalog & inventory
│   ├── orders/                # Order processing
│   ├── customers/             # Customer CRM
│   ├── payment/               # Payment processing
│   ├── analytics/             # Data analytics
│   ├── marketing/             # Marketing campaigns
│   ├── agents/                # AI marketing agents
│   ├── campaigns/             # Campaign management
│   ├── ad_generator/          # AI ad generation
│   ├── assets/                # Digital asset management
│   ├── content/               # Content management
│   ├── social/                # Social media integration
│   ├── whatsapp/              # WhatsApp Business API
│   ├── offers/                # Supplier offers
│   ├── requests/              # Customer requests
│   ├── agency/                # Agency management
│   ├── business/              # Business operations
│   ├── automation/            # Workflow automation
│   ├── workflow/              # Workflow management
│   └── markets/               # Market/location management
│
├── utils/                     # Utility services
│   ├── payment_service.py     # Payment processing logic
│   ├── Verification_Codes_Services.py
│   └── cache.py               # Redis caching utilities
│
├── scripts/                   # Database scripts
│   ├── add_draft_columns.py
│   └── seed_packages.py
│
└── uploads/                   # Local file uploads
    └── assets/
```

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 15+
- Redis 5.0+
- Node.js 18+ (for frontend)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/your-org/shopivell.git
cd shopivell/Shopivell-backend
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Initialize database**
```bash
# Create PostgreSQL database
createdb shopivell

# Run migrations
python -c "from database import init_db; init_db()"

# Seed initial data
python scripts/seed_packages.py
```

6. **Start Redis**
```bash
redis-server
```

7. **Run the application**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/shopivell

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# AI Services
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
TAVILY_API_KEY=...

# Payment Providers
PAYNOW_INTEGRATION_ID=...
PAYNOW_INTEGRATION_KEY=...
STRIPE_SECRET_KEY=sk_...
STRIPE_PUBLISHABLE_KEY=pk_...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...

# OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
FACEBOOK_APP_ID=...
FACEBOOK_APP_SECRET=...

# Storage
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_BUCKET_NAME=...

# WhatsApp
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
```

---

## API Documentation

### Base URL
```
Development: http://localhost:8000/v1
Production: https://api.shopivell.com/v1
```

### Authentication
All protected endpoints require a Bearer token:
```
Authorization: Bearer <access_token>
```

### Main Endpoints

| Module | Prefix | Description |
|--------|--------|-------------|
| Auth | `/api/auth` | Login, signup, verification |
| Users | `/api/users` | User management |
| Stores | `/api/stores` | Store CRUD |
| Products | `/api/products` | Product catalog |
| Orders | `/api/orders` | Order management |
| Customers | `/api/customers` | Customer CRM |
| Payments | `/api/payments` | Payment processing |
| Analytics | `/api/analytics` | Data & reporting |
| Marketing | `/api/marketing` | Campaign management |
| Assets | `/api/assets` | Media management |
| WhatsApp | `/api/whatsapp` | Messaging |

### Interactive Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Database Schema

### Core Entities

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│      User       │────<│      Store      │────<│    Product      │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ id (UUID)       │     │ id (UUID)       │     │ id (UUID)       │
│ email           │     │ owner_id (FK)   │     │ store_id (FK)   │
│ password_hash   │     │ store_name      │     │ name            │
│ role            │     │ business_type   │     │ price           │
│ created_at      │     │ color_theme     │     │ inventory       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                      │                       │
         │                      │                       │
         ▼                      ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Customer     │     │   Subscription  │     │     Order       │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ id (UUID)       │     │ id (UUID)       │     │ id (UUID)       │
│ store_id (FK)   │     │ store_id (FK)   │     │ store_id (FK)   │
│ name            │     │ package_name    │     │ customer_id (FK)│
│ email           │     │ is_active       │     │ status          │
│ phone           │     │ billing_period  │     │ total_amount    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### Vector Embeddings (pgvector)

```sql
-- AI-powered semantic search
CREATE TABLE market_research (
    id UUID PRIMARY KEY,
    embedding VECTOR(1536),  -- OpenAI embedding dimensions
    content TEXT,
    created_at TIMESTAMP
);

CREATE INDEX ON market_research
USING ivfflat (embedding vector_cosine_ops);
```

---

## Caching Strategy

### Redis Cache Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REDIS CACHE LAYERS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Layer 1: SESSION CACHE (TTL: 24 hours)                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Key Pattern: session:{user_id}                                      │   │
│  │  Data: User session data, auth tokens                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Layer 2: API RESPONSE CACHE (TTL: 5-60 minutes)                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Key Pattern: api:{endpoint}:{params_hash}                           │   │
│  │  Data: JSON responses from expensive queries                         │   │
│  │  Examples:                                                            │   │
│  │    - api:products:store_abc123:page_1 (TTL: 5 min)                   │   │
│  │    - api:analytics:store_abc123:weekly (TTL: 15 min)                 │   │
│  │    - api:packages:all (TTL: 60 min)                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Layer 3: ENTITY CACHE (TTL: 30 minutes)                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Key Pattern: {entity}:{id}                                          │   │
│  │  Data: Frequently accessed database records                          │   │
│  │  Examples:                                                            │   │
│  │    - store:abc123                                                     │   │
│  │    - user:xyz789                                                      │   │
│  │    - product:def456                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Layer 4: RATE LIMITING (TTL: 1 minute sliding window)                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Key Pattern: ratelimit:{ip}:{endpoint}                              │   │
│  │  Data: Request count                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Layer 5: REAL-TIME DATA (TTL: varies)                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  - Pub/Sub for real-time notifications                               │   │
│  │  - Leaderboards and counters                                         │   │
│  │  - Queue for background jobs                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Cache Invalidation Strategy

```python
# Automatic invalidation on write operations
@cache.invalidate_on_write("store:{store_id}")
async def update_store(store_id: UUID, data: StoreUpdate):
    # Update database
    # Cache is automatically invalidated
    pass

# Manual invalidation patterns
cache.delete("store:abc123")
cache.delete_pattern("api:products:store_abc123:*")
```

---

## Performance Optimization

### Current Optimizations

1. **Async Everything**
   - All endpoints are async
   - Non-blocking database operations
   - Background task support

2. **Database Indexing**
   - UUID primary keys indexed
   - Foreign key indexes
   - Composite indexes on frequently queried columns

3. **Connection Pooling**
   - SQLAlchemy connection pool
   - Pool size: 10-20 connections

### Recommended Improvements

#### 1. Add Redis Caching
```bash
pip install redis aioredis
```

```python
# utils/cache.py
from redis import asyncio as aioredis

class RedisCache:
    def __init__(self, url: str):
        self.redis = aioredis.from_url(url)

    async def get(self, key: str):
        return await self.redis.get(key)

    async def set(self, key: str, value: str, ttl: int = 300):
        await self.redis.setex(key, ttl, value)

    async def delete(self, key: str):
        await self.redis.delete(key)
```

#### 2. Query Optimization
```python
# Use eager loading to prevent N+1 queries
from sqlalchemy.orm import joinedload

products = db.query(Product).options(
    joinedload(Product.store),
    joinedload(Product.collections)
).all()
```

#### 3. Response Compression
```python
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

#### 4. Rate Limiting
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/products")
@limiter.limit("100/minute")
async def get_products():
    pass
```

#### 5. Database Read Replicas
```python
# For read-heavy operations
WRITE_DATABASE_URL = "postgresql://..."
READ_DATABASE_URL = "postgresql://read-replica..."
```

### Performance Benchmarks Target

| Metric | Current | Target |
|--------|---------|--------|
| API Response Time (p50) | ~200ms | <100ms |
| API Response Time (p99) | ~800ms | <300ms |
| Database Query Time | ~50ms | <20ms |
| Cache Hit Rate | 0% | >80% |
| Concurrent Users | ~100 | >1000 |

---

## Security

### Authentication Flow

```
┌────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
│ Client │────>│  API GW    │────>│   Auth     │────>│  Database  │
└────────┘     └────────────┘     │  Service   │     └────────────┘
                                  └────────────┘
     │                                  │
     │  1. Login Request                │
     │─────────────────────────────────>│
     │                                  │
     │  2. Verify Credentials           │
     │                                  │
     │  3. Generate JWT Token           │
     │<─────────────────────────────────│
     │                                  │
     │  4. Subsequent Requests          │
     │  (Bearer Token)                  │
     │─────────────────────────────────>│
```

### Security Best Practices

1. **Password Security**
   - bcrypt hashing with salt
   - Minimum 8 characters
   - Complexity requirements

2. **JWT Configuration**
   - Short-lived access tokens (30 min)
   - Refresh token rotation
   - Secure HTTP-only cookies

3. **API Security**
   - CORS configuration
   - Rate limiting
   - Input validation (Pydantic)
   - SQL injection prevention (SQLAlchemy ORM)

4. **Data Protection**
   - Encryption at rest
   - TLS in transit
   - PII handling compliance

---

## Deployment

### Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/shopivell
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=shopivell
      - POSTGRES_PASSWORD=password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### Production Checklist

- [ ] Enable HTTPS (SSL/TLS)
- [ ] Configure production database
- [ ] Set up Redis cluster
- [ ] Configure proper CORS origins
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Configure logging (ELK stack)
- [ ] Set up CI/CD pipeline
- [ ] Configure auto-scaling
- [ ] Set up backup strategy

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Code Style

- Follow PEP 8
- Use type hints
- Write docstrings for public functions
- Add tests for new features

---

## License

This project is proprietary. All rights reserved.

---

## Support

For support, email support@shopivell.com or join our Slack channel.
