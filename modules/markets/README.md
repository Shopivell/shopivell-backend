# Markets & Catalogs Module

## Overview

The **Markets & Catalogs Module** provides a comprehensive system for managing international markets, product catalogs, pricing strategies, and market-specific customizations. It enables businesses to deliver fully localized shopping experiences across regions, currencies, languages, and domains.

This module is designed to support global commerce use cases such as multi-currency pricing, regional product availability, localized content, and market-level overrides.

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                Markets & Catalogs Module                     │
├──────────────┬────────────────┬─────────────────┬───────────┤
│   Markets    │   Catalogs     │   Products      │  Pricing  │
│  Management  │  Management    │  Assignment     │  Strategy │
├──────────────┴────────────────┴─────────────────┴───────────┤
│                     Database Layer                           │
│               (PostgreSQL + SQLAlchemy ORM)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Models

### 1. Market

Represents a geographical or logical market (country, region, or group of regions).

**Fields**

* `id` (UUID, PK)
* `name` — Market name (e.g., *United States*, *European Union*)
* `status` — `active | inactive`
* `flag` — Country flag emoji or ISO code (optional)
* `customizations` — Count of active market customizations
* `currency` — Default currency for the market
* `catalogs` — Default catalog assignment description
* `domain` — Market-specific domain or subdomain
* `online_store` — Storefront platform or theme
* `created_at`, `updated_at`

**Relationships**

* One-to-many → `MarketInclude`
* One-to-many → `MarketCustomization`
* Many-to-many → `Catalog` (via `CatalogMarket`)

---

### 2. MarketInclude

Defines inclusion rules that determine which users or regions belong to a market.

**Fields**

* `id` (UUID, PK)
* `market_id` (FK → Market)
* `type` — Inclusion type (`country`, `region`, `language`, `currency`)
* `value` — ISO or logical value (e.g., `GB`, `en-GB`)
* `condition` — Optional qualifier (e.g., `default`)

---

### 3. MarketCustomization

Stores overrides and localized customizations for a market.

**Fields**

* `id` (UUID, PK)
* `market_id` (FK → Market)
* `type` — Customization type (`price`, `content`, `shipping`, `tax`)
* `original_value` — Default value
* `customized_value` — Market-specific value

---

### 4. Catalog

Represents a product catalog with pricing and adjustment strategies.

**Fields**

* `id` (UUID, PK)
* `title` — Catalog name
* `status` — `Draft | Active | Archived`
* `assigned_to` — Responsible person or team (optional)
* `price_overrides` — Count of product-level overrides
* `overall_adjustment` — Computed pricing strategy summary
* `products_count` — Number of products
* `auto_include_products` — Auto-add new products
* `price_adjustment` — Percentage adjustment value
* `adjustment_type` — `Increase | Decrease`
* `include_compare_price` — Show compare-at pricing
* `currency` — Catalog currency
* `created_at`, `updated_at`

**Relationships**

* One-to-many → `CatalogProduct`
* Many-to-many → `Market` (via `CatalogMarket`)

---

### 5. CatalogProduct

Represents a product entry inside a catalog.

**Fields**

* `id` (UUID, PK)
* `catalog_id` (FK → Catalog)
* `product_id` — Reference to master product
* `product_name`
* `price_in_usd`
* `compare_at_price`
* `status` — `included | excluded`
* `product_image` (optional)

---

### 6. CatalogMarket

Junction table linking catalogs and markets.

**Fields**

* `id` (UUID, PK)
* `catalog_id` (FK → Catalog)
* `market_id` (FK → Market)

---

## API Endpoints

### Base Router

`markets_router` (mounted in main FastAPI application)

---

## Market Management

### 1. GET /markets

Retrieve all markets with pagination and filtering.

**Query Parameters**

* `skip` (int, default=0)
* `limit` (int, default=10, max=100)
* `status` — Filter by status
* `search` — Search by market name

**Response**: `MarketListResponse`

---

### 2. GET /markets/{market_id}

Retrieve a single market by ID.

**Response**: `MarketResponse`

---

### 3. POST /markets

Create a new market with inclusion rules and customizations.

**Request Body: MarketCreate**

```json
{
  "name": "United Kingdom",
  "status": "active",
  "flag": "🇬🇧",
  "currency": "British Pound (£)",
  "domain": "https://uk.example.com",
  "online_store": "Horizon",
  "includes": [
    { "type": "country", "value": "GB", "condition": null },
    { "type": "language", "value": "en-GB", "condition": "default" }
  ],
  "customizations": [
    {
      "type": "shipping",
      "original_value": "Free shipping over $50",
      "customized_value": "Free shipping over £40"
    }
  ]
}
```

**Response**: `MarketResponse` (201 Created)

---

### 4. PUT /markets/{market_id}

Update market details (partial updates supported).

**Request Body**: `MarketUpdate`

**Response**: `MarketResponse`

---

### 5. DELETE /markets/{market_id}

Delete a market.

**Response**: `204 No Content`

---

## Catalog Management

### 1. GET /catalogs

Retrieve catalogs with pagination and filtering.

**Query Parameters**

* `skip`, `limit`
* `status` — Filter by catalog status
* `search` — Search by title

**Response**: `CatalogListResponse`

---

### 2. GET /catalogs/{catalog_id}

Retrieve a catalog with products and assigned markets.

**Response**: `CatalogResponse`

---

### 3. POST /catalogs

Create a catalog with products and market assignments.

**Request Body: CatalogCreate**

```json
{
  "title": "Spring Collection 2024",
  "status": "Draft",
  "assigned_to": "Marketing Team",
  "auto_include_products": true,
  "price_adjustment": 10.5,
  "adjustment_type": "Increase",
  "include_compare_price": true,
  "currency": "USD",
  "products": [
    {
      "product_id": "550e8400-e29b-41d4-a716-446655440000",
      "product_name": "Premium T-Shirt",
      "price_in_usd": 29.99,
      "compare_at_price": 39.99,
      "status": "included",
      "product_image": "https://example.com/tshirt.jpg"
    }
  ],
  "markets": [
    { "market_id": "550e8400-e29b-41d4-a716-446655440001" },
    { "market_id": "550e8400-e29b-41d4-a716-446655440002" }
  ]
}
```

**Response**: `CatalogResponse` (201 Created)

---

### 4. PUT /catalogs/{catalog_id}

Update catalog details.

**Request Body**: `CatalogUpdate`

**Response**: `CatalogResponse`

---

### 5. DELETE /catalogs/{catalog_id}

Delete a catalog.

**Response**: `204 No Content`

---

## Product Management

### 1. GET /products

Retrieve products with pagination.

**Query Parameters**

* `skip`, `limit`
* `search` — Search by product name

**Response**: `ProductListResponse`

---

### 2. POST /products

Create a new product.

**Request Body: ProductCreate**

```json
{
  "name": "Premium T-Shirt",
  "price_in_usd": 29.99,
  "compare_at_price": 39.99,
  "status": "active",
  "image": "https://example.com/tshirt.jpg"
}
```

**Response**: `ProductResponse` (201 Created)

---

## Pydantic Schemas

### Market Schemas

**MarketIncludeBase**

```python
type: str            # country, region, language, currency
value: str           # ISO code or logical value
condition: Optional[str]
```

**MarketCustomizationBase**

```python
type: str            # price, content, shipping, tax
original_value: str
customized_value: str
```

**MarketBase**

```python
name: str
status: str = "active"
flag: Optional[str]
currency: str = "US Dollar (USD $)"
catalogs: str = "All products"
domain: str
online_store: str = "Horizon"
```

**MarketResponse**

```python
id: UUID
customizations: int
created_at: datetime
updated_at: datetime
market_includes: List[MarketIncludeResponse]
market_customizations: List[MarketCustomizationResponse]
```

---

### Catalog Schemas

**CatalogProductBase**

```python
product_id: UUID
product_name: str
price_in_usd: float
compare_at_price: float = 0
status: str = "included"
product_image: Optional[str]
```

**CatalogBase**

```python
title: str
status: str = "Draft"
assigned_to: Optional[str]
auto_include_products: bool = True
price_adjustment: float = 0
adjustment_type: str = "Decrease"
include_compare_price: bool = True
currency: str = "USD"
```

**CatalogResponse**

```python
id: UUID
price_overrides: int
overall_adjustment: str
products_count: int
created_at: datetime
updated_at: datetime
catalog_products: List[CatalogProductResponse]
catalog_markets: List[CatalogMarketResponse]
```

---

### Product Schemas

**ProductBase**

```python
name: str
price_in_usd: float
compare_at_price: float = 0
status: str = "active"
image: Optional[str]
```

**ProductResponse**

```python
id: UUID
created_at: datetime
updated_at: datetime
```
