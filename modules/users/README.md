# Users Module

## Overview
User authentication and profile management.

## Features
- User registration
- Authentication (JWT)
- Profile management
- Role-based access
- Password reset

## Endpoints
- `POST /auth/register` - Register user
- `POST /auth/login` - Login
- `POST /auth/refresh` - Refresh token
- `POST /auth/logout` - Logout
- `GET /auth/me` - Current user
- `PUT /users/{id}` - Update profile
- `POST /auth/forgot-password` - Password reset

## Authentication
- JWT access tokens (60 min expiry)
- Refresh tokens (7 day expiry)
- Token blacklisting for logout

## Models
- User
- UserProfile
- UserRole
