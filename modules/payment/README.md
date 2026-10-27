# Payment Module

## Overview
Payment processing and subscription management.

## Features
- Multiple payment gateways
- Subscription plans
- Transaction history
- Invoice generation
- Refund processing

## Payment Methods
- EcoCash (PayNow)
- InnBucks (PayNow)
- Bank Transfer
- Stripe (Cards)
- PayPal

## Endpoints
- `POST /payments/initiate` - Initiate payment
- `GET /payments/status/{ref}` - Check status
- `POST /payments/webhook` - Payment webhook
- `GET /payments/transactions` - Transaction history
- `GET /subscriptions` - Get subscription
- `POST /subscriptions/upgrade` - Upgrade plan

## Subscription Plans
- FREE: 10 products, 50 orders
- PREMIUM: 100 products, 500 orders - $9.99/mo
- BUSINESS: 1000 products, 5000 orders - $29.99/mo

## Models
- PaymentTransaction
- StoreSubscription
- PackagePricing
