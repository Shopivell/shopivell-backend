"""
WhatsApp Flow Manager — lifecycle management via Meta Graph API.

Create, upload JSON, publish, and deprecate WhatsApp Flows.
Each store gets its own published Flow for ordering.
"""

import io
import json
import logging
import os
from typing import Optional, Dict, Any
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from .flow_json_template import generate_flow_json

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v23.0"


class WhatsAppFlowManager:
    """Manages WhatsApp Flows via Meta Graph API."""

    def __init__(self, waba_id: str, access_token: str):
        self.waba_id = waba_id
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
        }

    def create_flow(
        self, name: str, endpoint_uri: str, categories: list = None
    ) -> Dict[str, Any]:
        """Create a new Flow on Meta. Returns {"id": "flow_id"}."""
        url = f"{GRAPH_API_BASE}/{self.waba_id}/flows"
        payload = {
            "name": name,
            "categories": categories or ["OTHER"],
        }
        if endpoint_uri:
            payload["endpoint_uri"] = endpoint_uri

        resp = requests.post(
            url, json=payload, headers={**self.headers, "Content-Type": "application/json"}, timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Created Flow: {result}")
        return result

    def upload_flow_json(self, flow_id: str, flow_json: dict) -> Dict[str, Any]:
        """Upload flow.json as a multipart asset."""
        url = f"{GRAPH_API_BASE}/{flow_id}/assets"

        json_bytes = json.dumps(flow_json, indent=2).encode("utf-8")
        files = {
            "file": ("flow.json", io.BytesIO(json_bytes), "application/json"),
        }
        data = {
            "name": "flow.json",
            "asset_type": "FLOW_JSON",
        }

        resp = requests.post(
            url, files=files, data=data, headers=self.headers, timeout=30
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Uploaded Flow JSON: {result}")
        return result

    def publish_flow(self, flow_id: str) -> Dict[str, Any]:
        """Publish a draft Flow."""
        url = f"{GRAPH_API_BASE}/{flow_id}/publish"
        resp = requests.post(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Published Flow: {result}")
        return result

    def deprecate_flow(self, flow_id: str) -> Dict[str, Any]:
        """Deprecate a published Flow."""
        url = f"{GRAPH_API_BASE}/{flow_id}/deprecate"
        resp = requests.post(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_flow(self, flow_id: str) -> Dict[str, Any]:
        """Get Flow details."""
        url = f"{GRAPH_API_BASE}/{flow_id}"
        params = {"fields": "id,name,status,categories,validation_errors,json_version"}
        resp = requests.get(url, params=params, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def create_and_publish_store_flow(
        self,
        store_id: UUID,
        store_name: str,
        db: Session,
    ) -> str:
        """
        Full lifecycle: create → upload JSON → publish.

        Returns the flow_id string.
        Saves a WhatsAppFlow record to the database.
        """
        from .models import WhatsAppFlow

        endpoint_url = os.getenv(
            "WHATSAPP_FLOWS_ENDPOINT_URL",
            "https://shopivell-backend.onrender.com/v1/api/whatsapp/flow-endpoint",
        )

        # 1. Create
        name = f"{store_name} Order Flow"
        create_result = self.create_flow(name, endpoint_url)
        flow_id = create_result["id"]

        # 2. Upload JSON
        flow_json = generate_flow_json()
        self.upload_flow_json(flow_id, flow_json)

        # 3. Publish
        self.publish_flow(flow_id)

        # 4. Save to DB
        flow_record = WhatsAppFlow(
            store_id=store_id,
            waba_id=self.waba_id,
            flow_id=flow_id,
            flow_name=name,
            status="published",
            endpoint_uri=endpoint_url,
        )
        db.add(flow_record)
        db.commit()
        db.refresh(flow_record)

        logger.info(f"Store {store_id} flow created and published: {flow_id}")
        return flow_id
