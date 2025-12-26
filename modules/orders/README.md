# Orders Module

## Overview
Order processing and management system.

## Features
- Order creation
- Payment processing
- Order fulfillment
- Shipping management
- Refund handling

## Endpoints
- `POST /orders` - Create order
- `GET /orders` - List orders
- `GET /orders/{id}` - Get order details
- `PUT /orders/{id}/status` - Update status
- `POST /orders/{id}/refund` - Process refund
- `GET /orders/{id}/tracking` - Get tracking

## Order Statuses
- Pending
- Confirmed
- Processing
- Shipped
- Delivered
- Cancelled
- Refunded

## Models
- Order
- OrderItem
- OrderStatus
- Shipment
