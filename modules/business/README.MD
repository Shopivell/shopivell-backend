# Business Module

## Overview
Business profile and settings management for store owners.

## Features
- Business registration
- Profile management
- Business verification
- Tax information
- Legal documents

## Endpoints
- `POST /business` - Register business
- `GET /business/{id}` - Get business details
- `PUT /business/{id}` - Update business
- `POST /business/{id}/verify` - Submit verification
- `GET /business/{id}/documents` - List documents

## Models
- Business
- BusinessDocument
- BusinessVerification
