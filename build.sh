#!/usr/bin/env bash
# Build script for Render deployment

set -e

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright..."
pip install playwright

echo "Installing Playwright Chromium browser..."
# Use --with-deps to install system dependencies (works on Render)
playwright install chromium --with-deps

echo "Build complete!"
