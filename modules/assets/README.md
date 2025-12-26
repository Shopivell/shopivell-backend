# Assets Module

## Overview
Digital asset management for images, videos, and other media files.

## Features
- Image upload and optimization
- Video storage
- Cloudinary integration
- Asset categorization
- Bulk upload support

## Endpoints
- `POST /assets/upload` - Upload new asset
- `GET /assets` - List all assets
- `GET /assets/{id}` - Get asset details
- `DELETE /assets/{id}` - Delete asset
- `POST /assets/bulk` - Bulk upload

## Supported Formats
- Images: JPG, PNG, GIF, WebP
- Videos: MP4, MOV, AVI
- Documents: PDF

## Storage
- Cloudinary for cloud storage
- Local filesystem fallback
