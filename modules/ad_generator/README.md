# Ad Generator Module

## Overview
AI-powered advertisement generation module for creating Meta (Facebook/Instagram) ads.

## Features
- Generate ad creatives using AI models
- Image generation with DALL-E/Midjourney prompts
- Video concept generation
- A/B testing variations

## Endpoints
- `POST /ad-generator/generate` - Generate new ad creative
- `GET /ad-generator/{id}` - Get generated ad details
- `POST /ad-generator/batch` - Batch generate multiple ads

## Dependencies
- OpenAI API for text generation
- Cloudinary for image storage
- Campaign module for campaign data
