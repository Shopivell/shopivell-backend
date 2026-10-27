# Agency Module

## Overview
Multi-tenant agency management for handling multiple stores and clients.

## Features
- Agency registration and management
- Client/store assignment
- Agency-level analytics
- Team member management

## Endpoints
- `POST /agencies` - Create new agency
- `GET /agencies/{id}` - Get agency details
- `PUT /agencies/{id}` - Update agency
- `GET /agencies/{id}/stores` - List agency stores
- `POST /agencies/{id}/invite` - Invite team member

## Models
- Agency
- AgencyMember
- AgencyInvitation
