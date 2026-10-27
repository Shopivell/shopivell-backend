# all_models.py
"""
Central import file for all SQLAlchemy models.
Import this file before using any database operations to ensure
all relationships are properly resolved.

Order matters: base models first, then models that depend on them.
"""

# Base database
from database import Base

# Users - base model for many relationships
from modules.users.models import *

# Business/Agency - depends on User
try:
    from modules.agency.models import *
except ImportError:
    pass

# Social connections - depends on User
try:
    from modules.social.models import *
except ImportError:
    pass

# Business accounts
try:
    from modules.business.models import *
except ImportError:
    pass

# Stores - depends on User, Agency
from modules.stores.models import *

# Assets - depends on Store
from modules.assets.models import *

# Campaigns - depends on Store, Asset
from modules.campaigns.models import *

# Marketing (Meta ad accounts) and Agents (AI campaign generation) modules were
# removed in the OpenClaw migration — ad management now lives in OpenClaw.

# Customers
try:
    from modules.customers.models import *
except ImportError:
    pass

# Orders
try:
    from modules.orders.models import *
except ImportError:
    pass

# Products
try:
    from modules.products.models import *
except ImportError:
    pass

# Payments
try:
    from modules.payment.models import *
except ImportError:
    pass

# WhatsApp
try:
    from modules.whatsapp.models import *
except ImportError:
    pass

# Referral
try:
    from modules.referral.models import *
except ImportError:
    pass

# AI Usage Tracking
try:
    from modules.openrouter.models import *
except ImportError:
    pass

# Notifications
try:
    from modules.notifications.models import *
except ImportError:
    pass

# Procurement
try:
    from modules.procurement.models import *
except ImportError:
    pass

# Delivery
try:
    from modules.delivery.models import *
except ImportError:
    pass

# Reviews
try:
    from modules.reviews.models import *
except ImportError:
    pass

# Coupons
try:
    from modules.coupons.models import *
except ImportError:
    pass

# Returns
try:
    from modules.returns.models import *
except ImportError:
    pass

# Analytics
try:
    from modules.analytics.models import *
except ImportError:
    pass

print("[Models] All models loaded successfully")
