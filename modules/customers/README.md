# Customers Module

## Overview
Customer relationship management for store owners.

## Features
- Customer profiles
- Purchase history
- Customer segmentation
- Communication preferences
- Loyalty tracking

## Endpoints
- `GET /customers` - List customers
- `GET /customers/{id}` - Get customer details
- `PUT /customers/{id}` - Update customer
- `GET /customers/{id}/orders` - Customer orders
- `POST /customers/{id}/notes` - Add customer note
- `GET /customers/segments` - List segments

## Models
- Customer
- CustomerNote
- CustomerSegment
