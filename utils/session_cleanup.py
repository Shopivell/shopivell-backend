# utils/session_cleanup.py
from datetime import datetime, timedelta

from modules.stores.models import StoreSetupSession

class SessionCleanupService:
    @staticmethod
    def cleanup_old_sessions(db: Session, days_old: int = 30):
        """Clean up setup sessions older than X days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        
        old_sessions = db.query(StoreSetupSession).filter(
            StoreSetupSession.created_at < cutoff_date,
            StoreSetupSession.is_active == True
        ).all()
        
        for session in old_sessions:
            session.is_active = False
        
        db.commit()
        return len(old_sessions)