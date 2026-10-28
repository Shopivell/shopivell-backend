"""Store-scoped permissions shared by staff-facing APIs."""
import uuid

from fastapi import HTTPException

from modules.stores.models import Store
from modules.users.models import StoreMember


def require_store_capability(db, current_user, store_id, capability):
    try:
        store_id = uuid.UUID(str(store_id))
        user_id = uuid.UUID(str(current_user.id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=403, detail='Invalid store access')
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail='Store not found')
    if store.owner_id == user_id:
        return store
    member = db.query(StoreMember).filter(StoreMember.store_id == store_id,
        StoreMember.user_id == user_id, StoreMember.is_active.is_(True)).first()
    if not member or capability not in (member.permissions or []):
        raise HTTPException(status_code=403, detail='Permission denied for this store')
    return store
