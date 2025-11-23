from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
import logging

from modules.automation import models, schemas
from database import get_db  # Adjust import based on your project structure

# Setup logging
logger = logging.getLogger(__name__)

automation_router = APIRouter(prefix="/api/automation", tags=["automation"])

# Business CRUD Operations
def get_business(db: Session, business_id: int):
    return db.query(models.Business).filter(models.Business.id == business_id).first()

def get_business_social_config(db: Session, business_id: int) -> Dict[str, Any]:
    business = get_business(db, business_id)
    if not business:
        return None
    
    social_configs = db.query(models.SocialMediaConfig).filter(
        models.SocialMediaConfig.business_id == business_id
    ).all()
    
    social_media = {}
    for config in social_configs:
        social_media[config.platform] = config
    
    return {
        "business": business,
        "social_media": social_media
    }

def create_social_post(db: Session, post: schemas.SocialPostCreate):
    db_post = models.SocialPost(**post.dict())
    db.add(db_post)
    db.commit()
    db.refresh(db_post)
    return db_post

def get_social_posts(db: Session, business_id: int, skip: int = 0, limit: int = 100):
    return db.query(models.SocialPost).filter(
        models.SocialPost.business_id == business_id
    ).offset(skip).limit(limit).all()

def create_workflow_log(db: Session, log: schemas.WorkflowLogCreate):
    db_log = models.WorkflowLog(**log.dict())
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

def update_workflow_log_completion(db: Session, log_id: int, status: str, message: str = None):
    db_log = db.query(models.WorkflowLog).filter(models.WorkflowLog.id == log_id).first()
    if db_log:
        db_log.status = status
        db_log.message = message
        db_log.completed_at = func.now()
        db.commit()
        db.refresh(db_log)
    return db_log

def create_error_log(db: Session, error: schemas.ErrorLogCreate):
    db_error = models.ErrorLog(**error.dict())
    db.add(db_error)
    db.commit()
    db.refresh(db_error)
    return db_error

def send_message_externally(recipient: str, message_body: str, platform: str) -> Dict[str, Any]:
    """
    Simulates sending a message using an external service API.
    In a real app, this would involve HTTP requests to a provider (Twilio, etc.).
    """
    try:

        return {
            "success": True,
            "message": f"Message successfully scheduled for {platform}."
        }
    except Exception as e:
        logger.error(f"Error sending message to {recipient}: {str(e)}")
        return {
            "success": False,
            "message": "Failed to connect to external messaging service.",
            "task_id": None
        }

# # API Endpoints
# @automation_router.get(
#     "/business/{business_id}/social-config",
#     response_model=schemas.BusinessSocialConfigResponse
# )
# def get_business_social_config_endpoint(business_id: int, db: Session = Depends(get_db)):
#     """
#     Get business social media configuration for n8n workflow
#     """
#     try:
#         config_data = get_business_social_config(db, business_id)
#         if not config_data:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Business with ID {business_id} not found"
#             )
        
#         return config_data
#     except Exception as e:
#         logger.error(f"Error fetching business config: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Internal server error"
#         )

# @automation_router.post(
#     "/business/{business_id}/social-posts",
#     response_model=schemas.SocialPost
# )
# def create_social_post_endpoint(
#     business_id: int,
#     post: schemas.SocialPostCreate,
#     db: Session = Depends(get_db)
# ):
#     """
#     Save generated social media post to database
#     """
#     try:
#         # Ensure business exists
#         business = get_business(db, business_id)
#         if not business:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Business with ID {business_id} not found"
#             )
        
#         # Set business_id from path parameter
#         post_data = post.dict()
#         post_data["business_id"] = business_id
#         post_data["status"] = "published"  # Assuming approved and published
        
#         db_post = create_social_post(db, schemas.SocialPostCreate(**post_data))
#         logger.info(f"Social post saved for business {business_id}")
        
#         return db_post
#     except Exception as e:
#         logger.error(f"Error saving social post: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error saving social post"
#         )

# @automation_router.get(
#     "/business/{business_id}/social-posts",
#     response_model=List[schemas.SocialPost]
# )
# def get_social_posts_endpoint(
#     business_id: int,
#     skip: int = 0,
#     limit: int = 100,
#     db: Session = Depends(get_db)
# ):
#     """
#     Get social posts for a business
#     """
#     try:
#         posts = get_social_posts(db, business_id, skip, limit)
#         return posts
#     except Exception as e:
#         logger.error(f"Error fetching social posts: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error fetching social posts"
#         )

# @automation_router.post(
#     "/business/{business_id}/workflow-logs",
#     response_model=schemas.WorkflowLog
# )
# def create_workflow_log_endpoint(
#     business_id: int,
#     log: schemas.WorkflowLogCreate,
#     db: Session = Depends(get_db)
# ):
#     """
#     Log workflow execution results
#     """
#     try:
#         # Ensure business exists
#         business = get_business(db, business_id)
#         if not business:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Business with ID {business_id} not found"
#             )
        
#         # Set business_id from path parameter
#         log_data = log.dict()
#         log_data["business_id"] = business_id
        
#         db_log = create_workflow_log(db, schemas.WorkflowLogCreate(**log_data))
#         logger.info(f"Workflow log created for business {business_id}")
        
#         return db_log
#     except Exception as e:
#         logger.error(f"Error creating workflow log: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error creating workflow log"
#         )

# @automation_router.put(
#     "/workflow-logs/{log_id}/completion",
#     response_model=schemas.WorkflowLog
# )
# def update_workflow_log_completion_endpoint(
#     log_id: int,
#     status: str,
#     message: Optional[str] = None,
#     db: Session = Depends(get_db)
# ):
#     """
#     Update workflow log completion status
#     """
#     try:
#         db_log = update_workflow_log_completion(db, log_id, status, message)
#         if not db_log:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Workflow log with ID {log_id} not found"
#             )
        
#         return db_log
#     except Exception as e:
#         logger.error(f"Error updating workflow log: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error updating workflow log"
#         )

# @automation_router.post(
#     "/business/{business_id}/error-logs",
#     response_model=schemas.ErrorLog
# )
# def create_error_log_endpoint(
#     business_id: int,
#     error: schemas.ErrorLogCreate,
#     db: Session = Depends(get_db)
# ):
#     """
#     Log errors from workflow execution
#     """
#     try:
#         # Set business_id from path parameter
#         error_data = error.dict()
#         error_data["business_id"] = business_id
        
#         db_error = create_error_log(db, schemas.ErrorLogCreate(**error_data))
#         logger.error(f"Error logged for business {business_id}: {error.error_message}")
        
#         return db_error
#     except Exception as e:
#         logger.error(f"Error creating error log: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error creating error log"
#         )

# @automation_router.post("/webhook/social-automation")
# async def social_automation_webhook(webhook_data: schemas.WebhookResponse, db: Session = Depends(get_db)):
#     """
#     Webhook endpoint to trigger social media automation
#     This would be called by external systems to start the workflow
#     """
#     try:
#         logger.info(f"Social automation webhook triggered for business: {webhook_data.businessId}")
        
#         # Validate business exists
#         business = get_business(db, webhook_data.businessId)
#         if not business:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Business with ID {webhook_data.businessId} not found"
#             )
        
#         # Log the webhook trigger
#         workflow_log = create_workflow_log(db, schemas.WorkflowLogCreate(
#             business_id=webhook_data.businessId,
#             workflow_id=webhook_data.trigger,
#             execution_id=f"webhook_{webhook_data.businessId}",
#             status="triggered",
#             message="Social automation triggered via webhook"
#         ))
        
#         # In a real implementation, you might:
#         # 1. Queue a background task for processing
#         # 2. Trigger the n8n workflow via webhook
#         # 3. Process the automation immediately
        
#         return {
#             "success": True,
#             "message": "Social automation triggered successfully",
#             "business_id": webhook_data.businessId,
#             "workflow_log_id": workflow_log.id
#         }
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Webhook error: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Webhook processing failed"
#         )

# # Utility endpoints for testing and management
# @automation_router.post("/business", response_model=schemas.Business)
# def create_business_endpoint(business: schemas.BusinessCreate, db: Session = Depends(get_db)):
#     """
#     Create a new business (for testing)
#     """
#     try:
#         db_business = models.Business(**business.dict())
#         db.add(db_business)
#         db.commit()
#         db.refresh(db_business)
#         return db_business
#     except Exception as e:
#         logger.error(f"Error creating business: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error creating business"
#         )

# @automation_router.post("/business/{business_id}/social-config", response_model=schemas.SocialMediaConfig)
# def create_social_config_endpoint(
#     business_id: int,
#     config: schemas.SocialMediaConfigCreate,
#     db: Session = Depends(get_db)
# ):
#     """
#     Create social media config for a business (for testing)
#     """
#     try:
#         # Ensure business exists
#         business = get_business(db, business_id)
#         if not business:
#             raise HTTPException(
#                 status_code=status.HTTP_404_NOT_FOUND,
#                 detail=f"Business with ID {business_id} not found"
#             )
        
#         # Set business_id from path parameter
#         config_data = config.dict()
#         config_data["business_id"] = business_id
        
#         db_config = models.SocialMediaConfig(**config_data)
#         db.add(db_config)
#         db.commit()
#         db.refresh(db_config)
#         return db_config
#     except Exception as e:
#         logger.error(f"Error creating social config: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error creating social config"
#         )

# @automation_router.get("/business/{business_id}/workflow-logs", response_model=List[schemas.WorkflowLog])
# def get_workflow_logs_endpoint(
#     business_id: int,
#     skip: int = 0,
#     limit: int = 100,
#     db: Session = Depends(get_db)
# ):
#     """
#     Get workflow logs for a business
#     """
#     try:
#         logs = db.query(models.WorkflowLog).filter(
#             models.WorkflowLog.business_id == business_id
#         ).offset(skip).limit(limit).all()
#         return logs
#     except Exception as e:
#         logger.error(f"Error fetching workflow logs: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error fetching workflow logs"
#         )

# @automation_router.get("/business/{business_id}/error-logs", response_model=List[schemas.ErrorLog])
# def get_error_logs_endpoint(
#     business_id: int,
#     skip: int = 0,
#     limit: int = 100,
#     db: Session = Depends(get_db)
# ):
#     """
#     Get error logs for a business
#     """
#     try:
#         errors = db.query(models.ErrorLog).filter(
#             models.ErrorLog.business_id == business_id
#         ).offset(skip).limit(limit).all()
#         return errors
#     except Exception as e:
#         logger.error(f"Error fetching error logs: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Error fetching error logs"
#         )

# # Health check endpoint
# @automation_router.get("/health")
# async def health_check():
#     """
#     Health check endpoint for automation service
#     """
#     return {
#         "status": "healthy",
#         "service": "social_media_automation",
#         "timestamp": func.now()
#     }

@automation_router.post(
    "/business/send-message",
    response_model=schemas.MessageSendResponse,
    status_code=status.HTTP_202_ACCEPTED # 202 Accepted indicates processing has begun
)
def send_message_endpoint(
    business_id: int,
    message_data: schemas.MessageSend,
    db: Session = Depends(get_db)
):
    """
    Send a message to a recipient using a specified platform.
    This simulates triggering an external message service.
    """
    try:
    
        send_result = send_message_externally(
            recipient=message_data.recipient,
            message_body=message_data.message_body,
            platform=message_data.platform
        )

    except HTTPException:
        # Reraise FastAPI's HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Fatal error in send_message_endpoint: {str(e)}")
        # Log an error in your database if necessary
        # create_error_log(...)
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during message sending process."
        )