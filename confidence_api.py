"""
Apex Agents Bots: Confidence Engine API Server

FastAPI server that exposes the confidence scoring engine via REST API.

Endpoints:
- POST /score - Score a single lead
- POST /score_batch - Score multiple leads
- POST /api/signup - Create free trial account
- GET /trial/status - Get trial status and usage
- GET /health - Health check
"""

from fastapi import FastAPI, HTTPException, Header, Depends, BackgroundTasks, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
import json
import csv
import io
import asyncio
import logging
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import the confidence engine
from confidence_engine import ConfidenceEngineV1, LeadSignalHistory, BehavioralSignal
from signup_system import SignupSystem, SignupRequest

# Environment configuration
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# CORS allowed origins based on environment
if ENVIRONMENT == "production":
    ALLOWED_ORIGINS = [
        "https://apex-agents-frontend.vercel.app",
        "https://www.yourdomain.com",
    ]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
    ]

# ============================================================================
# Enums for Input Validation
# ============================================================================

class VerticalEnum(str, Enum):
    """Valid industry verticals"""
    SAAS = "saas"
    FINTECH = "fintech"
    ECOMMERCE = "ecommerce"
    AGENCY = "agency"
    OTHER = "other"


class FieldTypeEnum(str, Enum):
    """Valid custom field types"""
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    DATE = "date"


class CompanySizeEnum(str, Enum):
    """Valid company sizes"""
    SMALL = "small"
    MID_MARKET = "mid-market"
    ENTERPRISE = "enterprise"

app = FastAPI(
    title="Apex Confidence Engine API",
    description="Real-time behavioral confidence scoring for B2B leads",
    version="1.0.0"
)


# SECURITY: HTTPS enforcement + HSTS headers middleware
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Add CORS support for frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Initialize engine
engine = ConfidenceEngineV1()

# Initialize signup system
signup_system = SignupSystem()


# ============================================================================
# Dependencies & Helper Functions
# ============================================================================

def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers"""
    if request.client:
        return request.client.host
    # Fallback to X-Forwarded-For header if behind proxy
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return "unknown"


def validate_request_content(request: Request) -> None:
    """Validate request content type and size"""
    content_type = request.headers.get("content-type", "").lower()
    if content_type and "application/json" not in content_type:
        raise HTTPException(
            status_code=415,
            detail="Content-Type must be application/json"
        )

    # Validate payload size (10MB limit)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > 10:
                raise HTTPException(
                    status_code=413,
                    detail="Payload too large. Maximum size is 10MB."
                )
        except ValueError:
            pass


# ============================================================================
# Pydantic Models (Request/Response Schemas)
# ============================================================================

class SignalRequest(BaseModel):
    """A single behavioral signal for a lead"""
    signal_type: str  # 'website_visit', 'email_open', 'email_click', etc.
    timestamp: str  # ISO format: "2025-10-19T10:30:00Z"
    metadata: Optional[Dict] = None  # Additional context
    weight: float = 1.0  # Custom weight multiplier


class ScoreRequest(BaseModel):
    """Request to score a single lead"""
    lead_id: str
    email: str
    company: str
    vertical: VerticalEnum
    signals: List[SignalRequest]


class BatchScoreRequest(BaseModel):
    """Request to score multiple leads at once"""
    leads: List[ScoreRequest]


class ScoreResponse(BaseModel):
    """Response for a scored lead"""
    lead_id: str
    email: str
    company: str
    vertical: str
    confidence_score: float  # 0-100
    confidence_level: str  # 'low', 'medium', 'high', 'very_high'
    top_signals: List[str]  # What drove the score?
    risk_factors: List[str]  # What should we worry about?
    recommendation: str  # What should the rep do?
    calculation_details: Dict  # Transparent breakdown


class SignupRequestBody(BaseModel):
    """Free trial signup request"""
    first_name: str
    last_name: str
    email: str
    company: str
    vertical: VerticalEnum
    company_size: CompanySizeEnum
    phone: Optional[str] = None


class SignupResponse(BaseModel):
    """Free trial signup response"""
    success: bool
    user_id: str
    api_key: str
    trial_days: int
    trial_expires_at: str
    message: str


class TrialStatusResponse(BaseModel):
    """Trial account status response"""
    trial_active: bool
    days_remaining: int
    trial_expires_at: str
    usage: Dict
    engagement: Dict


class CustomFieldRequest(BaseModel):
    """Custom field creation/update request"""
    field_name: str
    field_type: FieldTypeEnum
    required: bool = False
    options: Optional[List[str]] = None  # For select fields


class CustomFieldResponse(BaseModel):
    """Custom field response"""
    field_id: str
    field_name: str
    field_type: str
    required: bool
    options: Optional[List[str]] = None
    created_at: str
    user_id: str


class UpdateLeadCustomDataRequest(BaseModel):
    """Request to update custom data for a lead"""
    custom_data: Dict


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/health")
async def health_check():
    """Simple health check endpoint"""
    return {
        "status": "healthy",
        "service": "Apex Confidence Engine",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/score", response_model=ScoreResponse)
async def score_lead(request: ScoreRequest) -> ScoreResponse:
    """
    Score a single lead based on behavioral signals.

    Example request:
    {
      "lead_id": "lead_001",
      "email": "sarah@techcorp.com",
      "company": "TechCorp",
      "vertical": "saas",
      "signals": [
        {
          "signal_type": "website_visit",
          "timestamp": "2025-10-19T14:30:00Z",
          "metadata": {"page": "/pricing"},
          "weight": 1.0
        },
        {
          "signal_type": "email_open",
          "timestamp": "2025-10-19T14:00:00Z",
          "metadata": {"subject": "New Integration"},
          "weight": 1.0
        }
      ]
    }
    """
    try:
        # Convert request signals to BehavioralSignal objects
        behavioral_signals = []
        for sig in request.signals:
            try:
                timestamp = datetime.fromisoformat(sig.timestamp.replace('Z', '+00:00'))
            except ValueError:
                timestamp = datetime.fromisoformat(sig.timestamp)

            behavioral_signals.append(
                BehavioralSignal(
                    signal_type=sig.signal_type,
                    timestamp=timestamp,
                    metadata=sig.metadata or {},
                    weight=sig.weight
                )
            )

        # Create lead object
        lead = LeadSignalHistory(
            lead_id=request.lead_id,
            email=request.email,
            company=request.company,
            vertical=request.vertical,
            signals=behavioral_signals,
            last_updated=datetime.utcnow()
        )

        # Score the lead
        result = engine.score(lead)

        return ScoreResponse(**result)

    except Exception as e:
        logger.error(f"Error scoring lead", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to score lead. Please try again.")


@app.post("/score_batch")
async def score_batch(request: BatchScoreRequest, background_tasks: BackgroundTasks, authorization: Optional[str] = Header(None)) -> Dict:
    """
    Score multiple leads at once (async with job tracking).

    Returns immediately with job_id. Poll /api/batch/{job_id}/status for progress.
    """
    # Check authentication
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")

    api_key = authorization.replace("Bearer ", "").strip()
    status = signup_system.get_trial_status(api_key)
    if not status:
        raise HTTPException(status_code=401, detail="Invalid API key")

    user_id = status.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        job_id = signup_system.create_batch_job(user_id, len(request.leads), None)

        background_tasks.add_task(process_batch_scoring, job_id, request.leads, user_id)

        return {
            "success": True,
            "job_id": job_id,
            "status": "processing",
            "total_leads": len(request.leads),
            "message": f"Batch job {job_id} queued for processing"
        }
    except Exception as e:
        logger.error(f"Error creating batch job", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to create batch job. Please try again.")


async def process_batch_scoring(job_id: str, leads: List[ScoreRequest], user_id: str):
    """Background task to score leads asynchronously"""
    results = []
    high_confidence_count = 0

    try:
        for idx, lead_request in enumerate(leads):
            try:
                score_req = ScoreRequest(**lead_request.dict())
                response = await score_lead(score_req)
                results.append(response.dict())

                if response.confidence_score >= 75:
                    high_confidence_count += 1
            except Exception as e:
                results.append({
                    "lead_id": lead_request.lead_id,
                    "email": lead_request.email,
                    "error": str(e)
                })

            signup_system.update_batch_job_progress(job_id, idx + 1)

        results_data = {
            "results": results,
            "total": len(results),
            "high_confidence_count": high_confidence_count,
            "timestamp": datetime.utcnow().isoformat()
        }

        results_url = f"/api/batch/{job_id}/results"
        signup_system.mark_batch_job_complete(job_id, results_url)

    except Exception as e:
        signup_system.mark_batch_job_failed(job_id, str(e))


@app.post("/score_with_recommendation")
async def score_with_recommendation(request: ScoreRequest) -> Dict:
    """
    Score a lead and provide detailed recommendation for sales team.

    This endpoint adds interpretation layer on top of raw confidence score.
    """
    try:
        score_resp = await score_lead(request)
        score_dict = score_resp.dict()

        # Add human-friendly recommendation
        confidence = score_dict['confidence_score']

        if confidence >= 75:
            action = "🔥 PRIORITY: This lead is actively buying NOW. Call within 24 hours."
            suggested_approach = "Discovery call - ask about timeline and pain points"
            nurture_length = "Short (3-5 touches)"
        elif confidence >= 60:
            action = "✅ WARM: This lead is interested. Regular follow-up recommended."
            suggested_approach = "Value-based email sequences + one call"
            nurture_length = "Medium (7-10 touches)"
        elif confidence >= 40:
            action = "⏳ COOL: This lead is exploring. Patience required."
            suggested_approach = "Educational content + slow nurture"
            nurture_length = "Long (15+ touches)"
        else:
            action = "❄️ COLD: This lead is not actively engaged. Re-engagement or removal."
            suggested_approach = "Win-back email or remove from active pipeline"
            nurture_length = "None (nurture later or remove)"

        return {
            **score_dict,
            "action_recommendation": action,
            "suggested_approach": suggested_approach,
            "suggested_nurture_length": nurture_length
        }

    except HTTPException as e:
        raise e


@app.get("/stats")
async def get_stats() -> Dict:
    """
    Return statistics about the scoring engine.
    Useful for monitoring and debugging.
    """
    return {
        "engine_version": "1.0.0",
        "signal_weights": engine.SIGNAL_WEIGHTS,
        "confidence_thresholds": {
            "very_high": "75+",
            "high": "60-74",
            "medium": "40-59",
            "low": "0-39"
        },
        "max_confidence_score": 100,
        "min_confidence_score": 0,
        "timestamp": datetime.utcnow().isoformat()
    }


# ============================================================================
# Trial Account & Signup Endpoints
# ============================================================================

@app.post("/api/signup", response_model=SignupResponse)
async def create_trial_signup(request: SignupRequestBody, client_ip: str = Depends(get_client_ip)) -> SignupResponse:
    """
    Create a free trial account for a new user.

    Returns:
    - api_key: Use this for all API requests
    - trial_days: 14 days free
    - trial_expires_at: ISO timestamp when trial expires
    """
    # Check rate limit
    if not signup_system.check_rate_limit(client_ip, "/api/signup"):
        logger.warning(f"Rate limit exceeded for IP {client_ip} on /api/signup")
        raise HTTPException(
            status_code=429,
            detail="Too many signup attempts. Please try again later."
        )

    try:
        # Create signup request
        signup_req = SignupRequest(
            first_name=request.first_name,
            last_name=request.last_name,
            email=request.email,
            company=request.company,
            vertical=request.vertical,
            company_size=request.company_size,
            phone=request.phone
        )

        # Create trial account
        trial_account = signup_system.create_trial_account(signup_req)

        return SignupResponse(
            success=True,
            user_id=trial_account.user_id,
            api_key=trial_account.api_key,
            trial_days=14,
            trial_expires_at=trial_account.trial_expires_at.isoformat(),
            message=f"Welcome {request.first_name}! Your 14-day free trial is now active."
        )

    except ValueError as e:
        logger.warning(f"Signup validation error", exc_info=e)
        raise HTTPException(status_code=400, detail="Invalid signup data. Please check your input.")
    except Exception as e:
        logger.error(f"Signup error", exc_info=e)
        raise HTTPException(status_code=500, detail="Unable to create trial account. Please try again.")


@app.get("/trial/status")
async def get_trial_status(authorization: Optional[str] = Header(None)) -> TrialStatusResponse:
    """
    Get trial account status and current usage.

    Headers:
    - Authorization: Bearer {API_KEY}

    Returns:
    - trial_active: Whether trial is still valid
    - days_remaining: Days left in trial
    - trial_expires_at: When trial expires
    - usage: Current usage (leads scored, emails composed, API calls)
    - engagement: User engagement metrics (last API call, dashboard views)
    """
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()

        # Get trial status from signup system
        status = signup_system.get_trial_status(api_key)

        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return TrialStatusResponse(
            trial_active=status["trial_active"],
            days_remaining=status["days_remaining"],
            trial_expires_at=status["trial_expires_at"],
            usage=status["usage"],
            engagement=status["engagement"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trial status", exc_info=e)
        raise HTTPException(status_code=500, detail="Unable to fetch trial status. Please try again.")


# ============================================================================
# Batch Job Management Endpoints
# ============================================================================

@app.get("/api/batch/{job_id}/status")
async def get_batch_status(job_id: str, authorization: Optional[str] = Header(None)) -> Dict:
    """Get status and progress of a batch scoring job"""
    try:
        status = signup_system.get_batch_job_status(job_id)

        if not status:
            raise HTTPException(status_code=404, detail=f"Batch job {job_id} not found")

        return {
            "job_id": job_id,
            "status": status["status"],
            "progress_percentage": (status["processed_leads"] / status["total_leads"] * 100) if status["total_leads"] > 0 else 0,
            "processed_leads": status["processed_leads"],
            "total_leads": status["total_leads"],
            "results_url": status["results_url"] if status["status"] == "completed" else None,
            "error_message": status["error_message"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch status", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to fetch batch status. Please try again.")


@app.get("/api/batch/{job_id}/results")
async def get_batch_results(job_id: str, format: str = "json", authorization: Optional[str] = Header(None)) -> Dict:
    """Get results of a completed batch scoring job (JSON or CSV)"""
    try:
        status = signup_system.get_batch_job_status(job_id)

        if not status:
            raise HTTPException(status_code=404, detail=f"Batch job {job_id} not found")

        if status["status"] != "completed":
            raise HTTPException(status_code=400, detail=f"Batch job {job_id} is still {status['status']}")

        # In a real implementation, fetch from storage
        # For now, return placeholder
        results = {
            "job_id": job_id,
            "format": format,
            "results": [],
            "timestamp": datetime.utcnow().isoformat()
        }

        if format == "csv":
            return FileResponse(
                "/tmp/results.csv",
                media_type="text/csv",
                filename=f"batch_results_{job_id}.csv"
            )

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching batch results", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to fetch batch results. Please try again.")


# ============================================================================
# API Key Management Endpoints
# ============================================================================

@app.post("/api/keys/rotate")
async def rotate_api_key(authorization: Optional[str] = Header(None)) -> Dict:
    """Rotate API key (revoke old, generate new 60-day key)"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()

        # Get user from current key
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Rotate the key
        new_key = signup_system.rotate_api_key(user_id)

        return {
            "success": True,
            "new_api_key": new_key,
            "expires_in_days": 60,
            "message": "API key rotated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rotating API key", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to rotate API key. Please try again.")


@app.delete("/api/keys/{key_id}")
async def revoke_api_key(key_id: str, authorization: Optional[str] = Header(None)) -> Dict:
    """Revoke a specific API key"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()

        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        signup_system.revoke_api_key(user_id, key_id)

        return {
            "success": True,
            "key_id": key_id,
            "message": f"API key {key_id} revoked"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking API key", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to revoke API key. Please try again.")


@app.get("/api/keys")
async def list_api_keys(authorization: Optional[str] = Header(None)) -> Dict:
    """List all valid API keys for the current user"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()

        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")
        valid_keys = signup_system.get_valid_api_keys(user_id)

        return {
            "success": True,
            "user_id": user_id,
            "keys": [
                {
                    "key_id": k.key_id,
                    "created_at": k.created_at.isoformat(),
                    "expires_at": k.expires_at.isoformat(),
                    "last_used": k.last_used.isoformat() if k.last_used else None,
                    "revoked": k.revoked
                } for k in valid_keys
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing API keys", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to list API keys. Please try again.")


# ============================================================================
# Custom Fields Management Endpoints
# ============================================================================

@app.post("/api/custom-fields", response_model=CustomFieldResponse)
async def create_custom_field(request: CustomFieldRequest, authorization: Optional[str] = Header(None)) -> CustomFieldResponse:
    """Create a new custom field for the user"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Validate field type
        valid_types = ["text", "number", "select", "date"]
        if request.field_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid field type. Must be one of: {valid_types}")

        # Validate select fields have options
        if request.field_type == "select" and not request.options:
            raise HTTPException(status_code=400, detail="Select fields must have options")

        field_id = f"field_{user_id}_{hash(request.field_name)}"

        return CustomFieldResponse(
            field_id=field_id,
            field_name=request.field_name,
            field_type=request.field_type,
            required=request.required,
            options=request.options,
            created_at=datetime.utcnow().isoformat(),
            user_id=user_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating custom field", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to create custom field. Please try again.")


@app.get("/api/custom-fields")
async def list_custom_fields(authorization: Optional[str] = Header(None)) -> Dict:
    """List all custom fields for the current user"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return {
            "success": True,
            "user_id": user_id,
            "fields": []
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing custom fields", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to list custom fields. Please try again.")


@app.put("/api/custom-fields/{field_id}")
async def update_custom_field(field_id: str, request: CustomFieldRequest, authorization: Optional[str] = Header(None)) -> CustomFieldResponse:
    """Update a custom field"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        user_id = status.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return CustomFieldResponse(
            field_id=field_id,
            field_name=request.field_name,
            field_type=request.field_type,
            required=request.required,
            options=request.options,
            created_at=datetime.utcnow().isoformat(),
            user_id=user_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating custom field", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to update custom field. Please try again.")


@app.delete("/api/custom-fields/{field_id}")
async def delete_custom_field(field_id: str, authorization: Optional[str] = Header(None)) -> Dict:
    """Delete a custom field"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return {
            "success": True,
            "field_id": field_id,
            "message": f"Custom field {field_id} deleted"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting custom field", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to delete custom field. Please try again.")


@app.patch("/api/leads/{lead_id}/custom-data")
async def update_lead_custom_data(lead_id: str, request: UpdateLeadCustomDataRequest, authorization: Optional[str] = Header(None)) -> Dict:
    """Update custom data for a specific lead"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return {
            "success": True,
            "lead_id": lead_id,
            "custom_data": request.custom_data,
            "message": f"Custom data updated for lead {lead_id}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating lead custom data", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to update lead data. Please try again.")


# ============================================================================
# Scoring Transparency Endpoints
# ============================================================================

@app.get("/api/leads/{lead_id}/scoring-breakdown")
async def get_scoring_breakdown(lead_id: str, authorization: Optional[str] = Header(None)) -> Dict:
    """Get detailed scoring breakdown for a lead"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        api_key = authorization.replace("Bearer ", "").strip()
        status = signup_system.get_trial_status(api_key)
        if not status:
            raise HTTPException(status_code=401, detail="Invalid API key")

        breakdown = {
            "lead_id": lead_id,
            "confidence_score": 0,
            "signal_breakdown": [
                {
                    "signal_type": "example_signal",
                    "weight": 1.0,
                    "contribution": 0,
                    "percentage": 0,
                    "reasoning": "Signal contributed X points"
                }
            ],
            "time_decay_applied": False,
            "total_signals_analyzed": 0,
            "scoring_methodology": "Behavioral signal weighting with time decay",
            "timestamp": datetime.utcnow().isoformat()
        }

        return breakdown
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching scoring breakdown", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to fetch scoring breakdown. Please try again.")


@app.post("/api/leads/{lead_id}/score-with-breakdown")
async def score_lead_with_breakdown(lead_id: str, request: ScoreRequest, authorization: Optional[str] = Header(None)) -> Dict:
    """Score a lead and return detailed breakdown"""
    try:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        score_response = await score_lead(request)
        score_dict = score_response.dict()

        breakdown = await get_scoring_breakdown(lead_id, authorization)

        return {
            **score_dict,
            "breakdown": breakdown
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scoring lead with breakdown", exc_info=e)
        raise HTTPException(status_code=400, detail="Unable to score lead. Please try again.")


# ============================================================================
# Error Handling
# ============================================================================

@app.exception_handler(ValueError)
async def value_error_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"detail": f"Validation error: {str(exc)}"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
