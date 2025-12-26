# Campaigns Module

## Overview
Marketing campaign management for Meta ads and promotional activities.

## Features
- Campaign creation and management
- Budget allocation
- Audience targeting
- Performance tracking
- A/B testing

## Endpoints
- `POST /campaigns` - Create campaign
- `GET /campaigns` - List campaigns
- `GET /campaigns/{id}` - Get campaign details
- `PUT /campaigns/{id}` - Update campaign
- `DELETE /campaigns/{id}` - Delete campaign
- `POST /campaigns/{id}/launch` - Launch campaign
- `POST /campaigns/{id}/pause` - Pause campaign

## Campaign Types
- Awareness
- Engagement
- Conversion
- Retargeting

## Models
- Campaign
- CreativeAngle
- AdCopy
- CampaignMetrics
