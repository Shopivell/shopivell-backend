# Automation Module

## Overview
Marketing automation and workflow scheduling for stores.

## Features
- Automated social media posting
- Scheduled campaigns
- Trigger-based actions
- Email automation
- Order notifications

## Endpoints
- `POST /automation/rules` - Create automation rule
- `GET /automation/rules` - List rules
- `PUT /automation/rules/{id}` - Update rule
- `DELETE /automation/rules/{id}` - Delete rule
- `POST /automation/trigger` - Manual trigger

## Trigger Types
- Time-based (cron)
- Event-based (order placed, product added)
- Condition-based (inventory low)
