# modules/marketing/meta_targeting_service.py
"""
Meta Targeting Service — Interest validation, reach estimation, and audience tools.

Validates LLM-generated interest tags against Meta's actual interest taxonomy
and provides reach estimates for targeting specs.

Usage:
    from modules.marketing.meta_targeting_service import MetaTargetingService

    service = MetaTargetingService(access_token="...")
    validated = await service.validate_interests(["home repair", "plumbing"])
    reach = await service.get_reach_estimate(ad_account_id, targeting_spec)
"""

import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

FB_GRAPH_API_BASE = "https://graph.facebook.com/v24.0"


class MetaTargetingService:
    """Service for Meta targeting validation and reach estimation."""

    def __init__(self, access_token: str):
        self.access_token = access_token

    def validate_interests(self, interest_tags: List[str]) -> Dict[str, Any]:
        """
        Validate interest tags against Meta's Interest Search API.

        For each LLM-generated interest tag, searches Meta's taxonomy to find
        matching valid interests with their IDs.

        Args:
            interest_tags: List of interest strings from LLM (e.g., ["home repair", "DIY"])

        Returns:
            Dict with validated interests, invalid ones, and suggestions
        """
        validated = []
        invalid = []
        suggestions = {}

        for tag in interest_tags:
            try:
                response = requests.get(
                    f"{FB_GRAPH_API_BASE}/search",
                    params={
                        "type": "adinterest",
                        "q": tag,
                        "access_token": self.access_token
                    }
                )
                response.raise_for_status()
                data = response.json().get("data", [])

                if data:
                    # Check for exact match first
                    exact_match = None
                    for item in data:
                        if item.get("name", "").lower() == tag.lower():
                            exact_match = item
                            break

                    if exact_match:
                        validated.append({
                            "name": exact_match["name"],
                            "id": exact_match["id"],
                            "audience_size_lower_bound": exact_match.get("audience_size_lower_bound", 0),
                            "audience_size_upper_bound": exact_match.get("audience_size_upper_bound", 0),
                            "path": exact_match.get("path", []),
                            "original_tag": tag
                        })
                    else:
                        # No exact match — use closest match and note the difference
                        closest = data[0]
                        validated.append({
                            "name": closest["name"],
                            "id": closest["id"],
                            "audience_size_lower_bound": closest.get("audience_size_lower_bound", 0),
                            "audience_size_upper_bound": closest.get("audience_size_upper_bound", 0),
                            "path": closest.get("path", []),
                            "original_tag": tag,
                            "was_corrected": True
                        })
                        # Store other suggestions
                        if len(data) > 1:
                            suggestions[tag] = [
                                {"name": item["name"], "id": item["id"]}
                                for item in data[1:5]
                            ]
                else:
                    invalid.append(tag)
                    logger.warning(f"[MetaTargeting] No match found for interest: '{tag}'")

            except Exception as e:
                logger.error(f"[MetaTargeting] Error validating interest '{tag}': {str(e)}")
                invalid.append(tag)

        logger.info(
            f"[MetaTargeting] Validated {len(validated)}/{len(interest_tags)} interests, "
            f"{len(invalid)} invalid"
        )

        return {
            "validated": validated,
            "invalid": invalid,
            "suggestions": suggestions,
            "total_checked": len(interest_tags),
            "valid_count": len(validated),
            "invalid_count": len(invalid)
        }

    def get_reach_estimate(
        self,
        ad_account_id: str,
        targeting_spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get reach estimate for a targeting spec from Meta API.

        Args:
            ad_account_id: Meta ad account ID (e.g., "act_123456")
            targeting_spec: Meta targeting spec dict with geo_locations, interests, etc.

        Returns:
            Dict with estimated daily reach, audience size, etc.
        """
        try:
            import json
            response = requests.get(
                f"{FB_GRAPH_API_BASE}/{ad_account_id}/reachestimate",
                params={
                    "access_token": self.access_token,
                    "targeting_spec": json.dumps(targeting_spec)
                }
            )
            response.raise_for_status()
            data = response.json().get("data", {})

            return {
                "success": True,
                "users_lower_bound": data.get("users_lower_bound", 0),
                "users_upper_bound": data.get("users_upper_bound", 0),
                "estimate_dau": data.get("estimate_dau", 0),
                "estimate_mau": data.get("estimate_mau", 0),
                "estimate_ready": data.get("estimate_ready", False),
                "raw_data": data
            }

        except Exception as e:
            error_detail = str(e)
            try:
                error_data = e.response.json()
                error_detail = error_data.get("error", {}).get("message", str(e))
            except Exception:
                pass
            logger.error(f"[MetaTargeting] Reach estimate error: {error_detail}")
            return {
                "success": False,
                "error": error_detail,
                "users_lower_bound": 0,
                "users_upper_bound": 0
            }

    def build_targeting_spec(
        self,
        validated_interests: List[Dict],
        countries: List[str],
        age_min: int = 18,
        age_max: int = 65,
        genders: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Build a Meta-compatible targeting_spec from validated interests.

        Args:
            validated_interests: List of validated interest dicts (from validate_interests)
            countries: List of country codes (e.g., ["ZW", "ZA"])
            age_min: Minimum age (default 18)
            age_max: Maximum age (default 65)
            genders: List of gender codes [1=male, 2=female] or None for all

        Returns:
            Meta-compatible targeting_spec dict
        """
        targeting = {
            "geo_locations": {
                "countries": countries
            },
            "age_min": age_min,
            "age_max": age_max,
        }

        if genders:
            targeting["genders"] = genders

        if validated_interests:
            targeting["flexible_spec"] = [{
                "interests": [
                    {"id": interest["id"], "name": interest["name"]}
                    for interest in validated_interests
                ]
            }]

        return targeting

    def validate_and_estimate(
        self,
        ad_account_id: str,
        interest_tags: List[str],
        countries: List[str],
        age_min: int = 18,
        age_max: int = 65,
        genders: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Combined: validate interests + build targeting spec + get reach estimate.

        This is the main method to call from the creative strategist agent.
        """
        # Step 1: Validate interests
        validation = self.validate_interests(interest_tags)

        # Step 2: Build targeting spec from validated interests
        targeting_spec = self.build_targeting_spec(
            validated_interests=validation["validated"],
            countries=countries,
            age_min=age_min,
            age_max=age_max,
            genders=genders
        )

        # Step 3: Get reach estimate
        reach = self.get_reach_estimate(ad_account_id, targeting_spec)

        return {
            "validation": validation,
            "targeting_spec": targeting_spec,
            "reach_estimate": reach
        }

    # ==================== Custom Audiences ====================

    def create_custom_audience(
        self,
        ad_account_id: str,
        name: str,
        description: str,
        phone_numbers: List[str],
        subtype: str = "CUSTOM"
    ) -> Dict[str, Any]:
        """
        Create a Custom Audience from phone numbers (hashed with SHA256).

        Steps:
        1. Create the custom audience container
        2. Hash phone numbers with SHA256
        3. Upload hashed data to the audience

        Args:
            ad_account_id: Meta ad account ID (e.g., "act_123456")
            name: Audience name
            description: Audience description
            phone_numbers: List of phone numbers to hash and upload
            subtype: Audience subtype (default "CUSTOM")

        Returns:
            Dict with audience_id and upload results
        """
        import hashlib

        try:
            # Step 1: Create audience container
            response = requests.post(
                f"{FB_GRAPH_API_BASE}/{ad_account_id}/customaudiences",
                params={
                    "access_token": self.access_token,
                    "name": name,
                    "description": description,
                    "subtype": subtype,
                    "customer_file_source": "USER_PROVIDED_ONLY"
                }
            )
            response.raise_for_status()
            audience_data = response.json()
            audience_id = audience_data.get("id")

            if not audience_id:
                return {"success": False, "error": "Failed to create audience container"}

            # Step 2: Hash phone numbers with SHA256
            import json
            hashed_phones = []
            for phone in phone_numbers:
                # Normalize: remove spaces, dashes, plus sign
                normalized = phone.strip().replace(" ", "").replace("-", "").replace("+", "")
                hashed = hashlib.sha256(normalized.encode()).hexdigest()
                hashed_phones.append(hashed)

            # Step 3: Upload hashed data
            # Meta expects batches of up to 10,000
            batch_size = 10000
            total_uploaded = 0

            for i in range(0, len(hashed_phones), batch_size):
                batch = hashed_phones[i:i + batch_size]

                payload = {
                    "schema": "PHONE_SHA256",
                    "data": batch
                }

                upload_response = requests.post(
                    f"{FB_GRAPH_API_BASE}/{audience_id}/users",
                    params={"access_token": self.access_token},
                    json={"payload": payload}
                )
                upload_response.raise_for_status()
                upload_result = upload_response.json()
                total_uploaded += upload_result.get("num_received", len(batch))

            logger.info(
                f"[MetaTargeting] Custom audience created: {audience_id}, "
                f"{total_uploaded} phone numbers uploaded"
            )

            return {
                "success": True,
                "audience_id": audience_id,
                "name": name,
                "total_uploaded": total_uploaded,
                "total_provided": len(phone_numbers)
            }

        except Exception as e:
            error_detail = str(e)
            try:
                error_data = e.response.json()
                error_detail = error_data.get("error", {}).get("message", str(e))
            except Exception:
                pass
            logger.error(f"[MetaTargeting] Custom audience error: {error_detail}")
            return {"success": False, "error": error_detail}

    # ==================== Lookalike Audiences ====================

    def create_lookalike_audience(
        self,
        ad_account_id: str,
        source_audience_id: str,
        name: str,
        country: str,
        ratio: float = 0.01,
        description: str = ""
    ) -> Dict[str, Any]:
        """
        Create a Lookalike Audience from a source Custom Audience.

        Args:
            ad_account_id: Meta ad account ID (e.g., "act_123456")
            source_audience_id: ID of the source custom audience
            name: Name for the lookalike audience
            country: Target country code (e.g., "ZW")
            ratio: Lookalike ratio 0.01-0.20 (1%-20% of country population)
            description: Optional description

        Returns:
            Dict with lookalike audience ID and details
        """
        try:
            import json
            spec = {
                "country": country,
                "ratio": ratio,
                "starting_ratio": 0.0
            }

            response = requests.post(
                f"{FB_GRAPH_API_BASE}/{ad_account_id}/customaudiences",
                params={
                    "access_token": self.access_token,
                    "name": name,
                    "description": description or f"Lookalike of {source_audience_id}",
                    "subtype": "LOOKALIKE",
                    "origin_audience_id": source_audience_id,
                    "lookalike_spec": json.dumps(spec)
                }
            )
            response.raise_for_status()
            result = response.json()
            audience_id = result.get("id")

            logger.info(
                f"[MetaTargeting] Lookalike audience created: {audience_id} "
                f"(source: {source_audience_id}, ratio: {ratio}, country: {country})"
            )

            return {
                "success": True,
                "audience_id": audience_id,
                "name": name,
                "source_audience_id": source_audience_id,
                "country": country,
                "ratio": ratio
            }

        except Exception as e:
            error_detail = str(e)
            try:
                error_data = e.response.json()
                error_detail = error_data.get("error", {}).get("message", str(e))
            except Exception:
                pass
            logger.error(f"[MetaTargeting] Lookalike audience error: {error_detail}")
            return {"success": False, "error": error_detail}
