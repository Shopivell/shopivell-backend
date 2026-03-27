from .models import UrlCampaign, CampaignStatus, CampaignGoal, UrlAdSet, UrlAdContent, AdContentMetrics
from .router import campaign_router

# Aliases for backward compatibility
Campaign = UrlCampaign
AdSet = UrlAdSet
AdContent = UrlAdContent

__all__ = ['UrlCampaign', 'Campaign', 'CampaignStatus', 'CampaignGoal', 'UrlAdSet', 'AdSet', 'UrlAdContent', 'AdContent', 'AdContentMetrics', 'campaign_router']
