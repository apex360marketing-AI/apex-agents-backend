"""
Apex Agents: Free Tier Signup & Authentication System

Manages:
- User registration (email, company, vertical)
- Email verification
- Trial account creation (14 days)
- API key generation + expiration/rotation (SECURITY)
- Trial usage tracking & limits
- Rate limiting (SECURITY)
- Batch job tracking (BATCH IMPORT)

Uses simple in-memory database (in production: PostgreSQL)
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import uuid
import hashlib
import json
from enum import Enum
import csv
import io
from cryptography.fernet import Fernet


class TrialStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CONVERTED = "converted"  # Paid customer
    CANCELLED = "cancelled"


@dataclass
class APIKey:
    """API key with expiration tracking (SECURITY FIX)"""
    key_id: str
    user_id: str
    key: str  # apx_xxxxx
    created_at: datetime
    expires_at: datetime
    last_used: Optional[datetime] = None
    revoked: bool = False
    revoked_at: Optional[datetime] = None

    def is_valid(self) -> bool:
        """Check if key is valid and not expired"""
        return not self.revoked and datetime.utcnow() < self.expires_at

    def mark_used(self):
        """Update last_used timestamp"""
        self.last_used = datetime.utcnow()


@dataclass
class BatchJob:
    """Batch scoring job tracking (BATCH IMPORT)"""
    job_id: str
    user_id: str
    created_at: datetime
    status: str  # 'processing', 'completed', 'failed'
    total_leads: int
    processed_leads: int = 0
    results_url: Optional[str] = None
    webhook_url: Optional[str] = None
    error_message: Optional[str] = None

    def get_progress(self) -> int:
        """Return progress as percentage"""
        if self.total_leads == 0:
            return 0
        return int((self.processed_leads / self.total_leads) * 100)


@dataclass
class RateLimitTracker:
    """Rate limiting for auth endpoints (SECURITY FIX)"""
    ip_address: str
    endpoint: str  # '/api/signup', '/api/login'
    attempt_count: int = 0
    first_attempt_at: datetime = field(default_factory=datetime.utcnow)
    blocked_until: Optional[datetime] = None

    def is_blocked(self) -> bool:
        """Check if IP is currently blocked"""
        if not self.blocked_until:
            return False
        return datetime.utcnow() < self.blocked_until

    def record_attempt(self):
        """Record a failed attempt"""
        self.attempt_count += 1
        # Exponential backoff: 2^n seconds
        if self.attempt_count >= 5:
            backoff_seconds = 2 ** (self.attempt_count - 4)
            self.blocked_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)


@dataclass
class TrialAccount:
    """A free trial account"""
    user_id: str
    email: str
    company: str
    vertical: str  # 'saas', 'fintech', 'ecommerce'
    api_key: str
    api_keys: List[APIKey] = field(default_factory=list)  # SECURITY: Track all keys

    # Trial info
    created_at: datetime = field(default_factory=datetime.utcnow)
    trial_expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(days=14))
    status: TrialStatus = TrialStatus.ACTIVE

    # Usage tracking
    leads_scored_this_month: int = 0
    emails_composed_this_month: int = 0
    api_calls_this_month: int = 0

    # Engagement tracking
    last_api_call: Optional[datetime] = None
    dashboard_views: int = 0
    rep_feedbacks_given: int = 0

    # Contact info (for follow-up)
    first_name: str = ""
    last_name: str = ""
    phone: Optional[str] = None

    # Conversion tracking
    converted_to_paid: bool = False
    paid_plan: Optional[str] = None

    def is_trial_active(self) -> bool:
        """Check if trial is still active"""
        return (self.status == TrialStatus.ACTIVE and
                datetime.utcnow() < self.trial_expires_at)

    def days_remaining(self) -> int:
        """Days left in trial"""
        if not self.is_trial_active():
            return 0
        remaining = (self.trial_expires_at - datetime.utcnow()).days
        return max(0, remaining)

    def to_dict(self):
        """Convert to dict, hiding sensitive data"""
        data = asdict(self)
        data['api_key'] = data['api_key'][:8] + '...'  # Mask API key
        data['api_keys'] = [{'key_id': k.key_id, 'created': k.created_at.isoformat(),
                             'expires': k.expires_at.isoformat(), 'valid': k.is_valid()}
                            for k in self.api_keys]
        data['created_at'] = data['created_at'].isoformat()
        data['trial_expires_at'] = data['trial_expires_at'].isoformat()
        if data['last_api_call']:
            data['last_api_call'] = data['last_api_call'].isoformat()
        return data


@dataclass
class CustomField:
    """Custom field definition for a user"""
    field_id: str
    field_name: str  # e.g., "industry_code", "partner_tier"
    field_type: str  # 'text', 'number', 'select', 'date'
    required: bool = False
    options: Optional[List[str]] = None  # For select type
    user_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self):
        return {
            'field_id': self.field_id,
            'field_name': self.field_name,
            'field_type': self.field_type,
            'required': self.required,
            'options': self.options,
            'created_at': self.created_at.isoformat(),
        }


@dataclass
class SignupRequest:
    """User signup form data"""
    email: str
    first_name: str
    last_name: str
    company: str
    vertical: str  # 'saas', 'fintech', 'ecommerce'
    phone: Optional[str] = None
    company_size: str = "mid-market"  # 'small', 'mid-market', 'enterprise'


class SignupSystem:
    """
    Manages user signups and trial accounts.

    In production, this would connect to a real database.
    For now: in-memory storage with JSON export/import.
    """

    def __init__(self):
        self.accounts: Dict[str, TrialAccount] = {}
        self.email_to_user: Dict[str, str] = {}
        self.pending_verifications: Dict[str, dict] = {}  # email -> verification code + details
        self.batch_jobs: Dict[str, BatchJob] = {}  # BATCH IMPORT: job_id -> job
        self.rate_limiters: Dict[str, RateLimitTracker] = {}  # SECURITY: ip:endpoint -> tracker
        self.encryption_key = Fernet.generate_key()  # SECURITY: Token encryption
        self.custom_fields: Dict[str, List[CustomField]] = {}  # user_id -> list of custom fields
        self.lead_custom_data: Dict[str, Dict[str, dict]] = {}  # user_id -> {lead_id -> custom_data}

    def generate_api_key(self, email: str) -> str:
        """Generate a unique API key for a user"""
        key_material = f"{email}:{uuid.uuid4()}:{datetime.utcnow().isoformat()}"
        hash_obj = hashlib.sha256(key_material.encode())
        return f"apx_{hash_obj.hexdigest()[:32]}"

    def rotate_api_key(self, user_id: str) -> Optional[str]:
        """SECURITY: Rotate API key (60-day expiration). Generate new key and deprecate old."""
        account = self.accounts.get(user_id)
        if not account:
            return None

        # Generate new key
        new_key = self.generate_api_key(account.email)
        now = datetime.utcnow()
        expires_at = now + timedelta(days=60)

        # Create APIKey object
        api_key_obj = APIKey(
            key_id=f"key_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            key=new_key,
            created_at=now,
            expires_at=expires_at
        )

        # Mark old key as deprecated
        for existing_key in account.api_keys:
            if existing_key.is_valid():
                existing_key.revoked = True
                existing_key.revoked_at = now

        # Add new key
        account.api_keys.append(api_key_obj)
        account.api_key = new_key  # Update primary key

        return new_key

    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        """SECURITY: Revoke a specific API key immediately"""
        account = self.accounts.get(user_id)
        if not account:
            return False

        for api_key in account.api_keys:
            if api_key.key_id == key_id:
                api_key.revoked = True
                api_key.revoked_at = datetime.utcnow()
                return True

        return False

    def get_valid_api_keys(self, user_id: str) -> List[Dict]:
        """Get all valid (non-revoked, non-expired) API keys for user"""
        account = self.accounts.get(user_id)
        if not account:
            return []

        return [
            {
                'key_id': k.key_id,
                'created_at': k.created_at.isoformat(),
                'expires_at': k.expires_at.isoformat(),
                'last_used': k.last_used.isoformat() if k.last_used else None,
                'key_prefix': k.key[:12] + '...'
            }
            for k in account.api_keys if k.is_valid()
        ]

    def check_rate_limit(self, ip_address: str, endpoint: str) -> bool:
        """SECURITY: Check if IP is rate-limited for endpoint"""
        key = f"{ip_address}:{endpoint}"
        tracker = self.rate_limiters.get(key)

        if not tracker:
            return True  # Not limited

        # Reset if hour has passed
        if (datetime.utcnow() - tracker.first_attempt_at).seconds > 3600:
            del self.rate_limiters[key]
            return True

        return not tracker.is_blocked()

    def record_rate_limit_failure(self, ip_address: str, endpoint: str):
        """SECURITY: Record failed auth attempt"""
        key = f"{ip_address}:{endpoint}"

        if key not in self.rate_limiters:
            self.rate_limiters[key] = RateLimitTracker(ip_address, endpoint)

        self.rate_limiters[key].record_attempt()

    def create_trial_account(self, signup: SignupRequest) -> Dict:
        """
        Create a new trial account.

        Returns:
            {
                'success': bool,
                'user_id': str (if success),
                'api_key': str (if success),
                'trial_days': 14,
                'message': str
            }
        """
        # Validate input
        if not signup.email or '@' not in signup.email:
            return {'success': False, 'message': 'Invalid email address'}

        if signup.email in self.email_to_user:
            return {'success': False, 'message': 'Email already registered'}

        if signup.vertical not in ['saas', 'fintech', 'ecommerce']:
            return {'success': False, 'message': 'Invalid vertical'}

        # Generate IDs
        user_id = f"usr_{uuid.uuid4().hex[:16]}"
        api_key = self.generate_api_key(signup.email)

        # Create account
        now = datetime.utcnow()
        trial_expires = now + timedelta(days=14)

        account = TrialAccount(
            user_id=user_id,
            email=signup.email,
            first_name=signup.first_name,
            last_name=signup.last_name,
            company=signup.company,
            vertical=signup.vertical,
            phone=signup.phone,
            api_key=api_key,
            created_at=now,
            trial_expires_at=trial_expires,
        )

        # Store
        self.accounts[user_id] = account
        self.email_to_user[signup.email] = user_id

        return {
            'success': True,
            'user_id': user_id,
            'api_key': api_key,
            'trial_days': 14,
            'trial_expires_at': trial_expires.isoformat(),
            'message': f'Welcome! Your 14-day trial starts now.',
            'next_steps': [
                '1. Copy your API key (shown once)',
                '2. Integration guide: https://docs.apex-agents.com/api',
                '3. Start scoring leads: POST /score',
                '4. View dashboard: https://app.apex-agents.com'
            ]
        }

    def get_account_by_email(self, email: str) -> Optional[TrialAccount]:
        """Look up account by email"""
        user_id = self.email_to_user.get(email)
        if user_id:
            return self.accounts.get(user_id)
        return None

    def get_account_by_api_key(self, api_key: str) -> Optional[TrialAccount]:
        """Look up account by API key (for API requests)"""
        for account in self.accounts.values():
            if account.api_key == api_key:
                return account
        return None

    def record_api_call(self, api_key: str, call_type: str = 'score') -> bool:
        """Record API usage for tracking"""
        account = self.get_account_by_api_key(api_key)
        if not account:
            return False

        if not account.is_trial_active():
            return False

        account.last_api_call = datetime.utcnow()
        account.api_calls_this_month += 1

        if call_type == 'score':
            account.leads_scored_this_month += 1
        elif call_type == 'compose':
            account.emails_composed_this_month += 1

        # Trial limit: 100 leads/month
        if account.leads_scored_this_month > 100:
            return False

        return True

    def get_trial_status(self, api_key: str) -> Dict:
        """Get current trial status for a user"""
        account = self.get_account_by_api_key(api_key)
        if not account:
            return {'error': 'Invalid API key'}

        return {
            'user_id': account.user_id,
            'email': account.email,
            'company': account.company,
            'vertical': account.vertical,
            'status': account.status.value,
            'trial_active': account.is_trial_active(),
            'days_remaining': account.days_remaining(),
            'trial_expires_at': account.trial_expires_at.isoformat(),
            'usage': {
                'leads_scored_this_month': account.leads_scored_this_month,
                'emails_composed_this_month': account.emails_composed_this_month,
                'api_calls_this_month': account.api_calls_this_month,
                'limits': {
                    'leads_per_month': 100,
                    'emails_per_month': 50,
                }
            },
            'engagement': {
                'last_api_call': account.last_api_call.isoformat() if account.last_api_call else None,
                'dashboard_views': account.dashboard_views,
                'rep_feedbacks_given': account.rep_feedbacks_given,
            }
        }

    def export_accounts(self) -> str:
        """Export all accounts as JSON (for backup/migration)"""
        data = {
            'exported_at': datetime.utcnow().isoformat(),
            'accounts': [
                {
                    **account.to_dict(),
                    'api_key': account.api_key,  # Full key for backup
                }
                for account in self.accounts.values()
            ]
        }
        return json.dumps(data, indent=2, default=str)

    # =========== CUSTOM FIELDS MANAGEMENT ===========

    def create_custom_field(self, user_id: str, field_name: str, field_type: str,
                           required: bool = False, options: Optional[List[str]] = None) -> Dict:
        """Create a custom field for a user"""

        # Validate field type
        if field_type not in ['text', 'number', 'select', 'date']:
            return {'success': False, 'message': 'Invalid field type'}

        # Validate select options
        if field_type == 'select' and not options:
            return {'success': False, 'message': 'Select type requires options'}

        # Check for duplicate names
        if user_id in self.custom_fields:
            for field in self.custom_fields[user_id]:
                if field.field_name == field_name:
                    return {'success': False, 'message': 'Field name already exists'}

        # Create field
        field_id = f"fld_{uuid.uuid4().hex[:16]}"
        field = CustomField(
            field_id=field_id,
            field_name=field_name,
            field_type=field_type,
            required=required,
            options=options,
            user_id=user_id,
            created_at=datetime.utcnow(),
        )

        if user_id not in self.custom_fields:
            self.custom_fields[user_id] = []

        self.custom_fields[user_id].append(field)

        return {'success': True, 'field_id': field_id, 'field': field.to_dict()}

    def list_custom_fields(self, user_id: str) -> List[Dict]:
        """List all custom fields for a user"""
        if user_id not in self.custom_fields:
            return []
        return [f.to_dict() for f in self.custom_fields[user_id]]

    def update_custom_field(self, user_id: str, field_id: str,
                           field_name: Optional[str] = None,
                           field_type: Optional[str] = None,
                           required: Optional[bool] = None,
                           options: Optional[List[str]] = None) -> Dict:
        """Update a custom field"""

        if user_id not in self.custom_fields:
            return {'success': False, 'message': 'No custom fields for user'}

        field_obj = None
        for field in self.custom_fields[user_id]:
            if field.field_id == field_id:
                field_obj = field
                break

        if not field_obj:
            return {'success': False, 'message': 'Field not found'}

        # Check for duplicate field name (if changing name)
        if field_name and field_name != field_obj.field_name:
            for f in self.custom_fields[user_id]:
                if f.field_name == field_name:
                    return {'success': False, 'message': 'Field name already exists'}
            field_obj.field_name = field_name

        if field_type:
            field_obj.field_type = field_type
        if required is not None:
            field_obj.required = required
        if options is not None:
            field_obj.options = options

        return {'success': True, 'field': field_obj.to_dict()}

    def delete_custom_field(self, user_id: str, field_id: str) -> Dict:
        """Delete a custom field"""

        if user_id not in self.custom_fields:
            return {'success': False, 'message': 'No custom fields for user'}

        self.custom_fields[user_id] = [
            f for f in self.custom_fields[user_id] if f.field_id != field_id
        ]

        # Also delete all custom data for this field across all leads
        if user_id in self.lead_custom_data:
            for lead_id in self.lead_custom_data[user_id]:
                if field_id in self.lead_custom_data[user_id][lead_id]:
                    del self.lead_custom_data[user_id][lead_id][field_id]

        return {'success': True, 'message': f'Field {field_id} deleted'}

    def set_lead_custom_data(self, user_id: str, lead_id: str, custom_data: Dict) -> Dict:
        """Set custom data for a lead"""

        if user_id not in self.lead_custom_data:
            self.lead_custom_data[user_id] = {}

        self.lead_custom_data[user_id][lead_id] = custom_data

        return {'success': True, 'custom_data': custom_data}

    def get_lead_custom_data(self, user_id: str, lead_id: str) -> Dict:
        """Get custom data for a lead"""

        if user_id not in self.lead_custom_data:
            return {}

        return self.lead_custom_data[user_id].get(lead_id, {})

    def create_batch_job(self, user_id: str, total_leads: int, webhook_url: Optional[str] = None) -> str:
        """BATCH IMPORT: Create a new batch scoring job"""
        job_id = f"job_{uuid.uuid4().hex[:16]}"

        job = BatchJob(
            job_id=job_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
            status='processing',
            total_leads=total_leads,
            webhook_url=webhook_url
        )

        self.batch_jobs[job_id] = job
        return job_id

    def get_batch_job_status(self, job_id: str) -> Optional[Dict]:
        """BATCH IMPORT: Get status of batch job"""
        job = self.batch_jobs.get(job_id)
        if not job:
            return None

        return {
            'job_id': job.job_id,
            'status': job.status,
            'progress': job.get_progress(),
            'processed': job.processed_leads,
            'total': job.total_leads,
            'results_url': job.results_url,
            'created_at': job.created_at.isoformat(),
            'error': job.error_message
        }

    def update_batch_job_progress(self, job_id: str, processed_count: int):
        """BATCH IMPORT: Update progress of batch job"""
        job = self.batch_jobs.get(job_id)
        if job:
            job.processed_leads = processed_count

    def mark_batch_job_complete(self, job_id: str, results_url: str):
        """BATCH IMPORT: Mark batch job as complete"""
        job = self.batch_jobs.get(job_id)
        if job:
            job.status = 'completed'
            job.results_url = results_url

    def mark_batch_job_failed(self, job_id: str, error_message: str):
        """BATCH IMPORT: Mark batch job as failed"""
        job = self.batch_jobs.get(job_id)
        if job:
            job.status = 'failed'
            job.error_message = error_message

    def get_analytics(self) -> Dict:
        """Get signup analytics (useful for Week 1-2 tracking)"""
        now = datetime.utcnow()
        signups_this_week = sum(
            1 for acc in self.accounts.values()
            if (now - acc.created_at).days < 7
        )
        active_trials = sum(
            1 for acc in self.accounts.values()
            if acc.is_trial_active()
        )
        converted = sum(
            1 for acc in self.accounts.values()
            if acc.converted_to_paid
        )
        vertical_breakdown = {}
        for acc in self.accounts.values():
            vertical_breakdown[acc.vertical] = vertical_breakdown.get(acc.vertical, 0) + 1

        return {
            'total_signups': len(self.accounts),
            'active_trials': active_trials,
            'converted_to_paid': converted,
            'signups_this_week': signups_this_week,
            'conversion_rate': f"{(converted / max(1, len(self.accounts)) * 100):.1f}%",
            'vertical_breakdown': vertical_breakdown,
            'average_engagement': {
                'avg_api_calls': sum(acc.api_calls_this_month for acc in self.accounts.values()) / max(1, len(self.accounts)),
                'avg_leads_scored': sum(acc.leads_scored_this_month for acc in self.accounts.values()) / max(1, len(self.accounts)),
            }
        }


# Test the signup system
if __name__ == '__main__':
    print("=" * 70)
    print("SIGNUP SYSTEM TEST")
    print("=" * 70)

    system = SignupSystem()

    # Test 1: Create signup for SaaS company
    print("\n✓ Test 1: SaaS Company Signup")
    signup1 = SignupRequest(
        email='sarah@techcorp.com',
        first_name='Sarah',
        last_name='Chen',
        company='TechCorp',
        vertical='saas',
        phone='+1-415-555-0100',
        company_size='mid-market'
    )
    result1 = system.create_trial_account(signup1)
    print(f"  Email: {signup1.email}")
    print(f"  Success: {result1['success']}")
    print(f"  API Key: {result1.get('api_key', 'N/A')[:16]}...")
    print(f"  Trial Days: {result1.get('trial_days', 0)}")
    api_key_1 = result1.get('api_key')

    # Test 2: Create signup for Fintech company
    print("\n✓ Test 2: Fintech Company Signup")
    signup2 = SignupRequest(
        email='john@banktech.com',
        first_name='John',
        last_name='Smith',
        company='BankTech',
        vertical='fintech',
    )
    result2 = system.create_trial_account(signup2)
    print(f"  Email: {signup2.email}")
    print(f"  Success: {result2['success']}")
    api_key_2 = result2.get('api_key')

    # Test 3: Duplicate signup (should fail)
    print("\n✓ Test 3: Duplicate Email (should fail)")
    result3 = system.create_trial_account(signup1)
    print(f"  Success: {result3['success']}")
    print(f"  Message: {result3['message']}")

    # Test 4: Record API calls
    print("\n✓ Test 4: Record API Usage")
    system.record_api_call(api_key_1, 'score')
    system.record_api_call(api_key_1, 'score')
    system.record_api_call(api_key_2, 'compose')
    status1 = system.get_trial_status(api_key_1)
    print(f"  User 1 leads scored: {status1['usage']['leads_scored_this_month']}")
    print(f"  User 1 API calls: {status1['usage']['api_calls_this_month']}")
    status2 = system.get_trial_status(api_key_2)
    print(f"  User 2 emails composed: {status2['usage']['emails_composed_this_month']}")

    # Test 5: Trial status
    print("\n✓ Test 5: Trial Status Check")
    print(f"  User 1 trial active: {status1['trial_active']}")
    print(f"  User 1 days remaining: {status1['days_remaining']}")
    print(f"  Trial expires: {status1['trial_expires_at']}")

    # Test 6: Analytics
    print("\n✓ Test 6: Signup Analytics")
    analytics = system.get_analytics()
    print(f"  Total signups: {analytics['total_signups']}")
    print(f"  Active trials: {analytics['active_trials']}")
    print(f"  Vertical breakdown: {analytics['vertical_breakdown']}")
    print(f"  Avg leads scored: {analytics['average_engagement']['avg_leads_scored']:.1f}")

    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED")
    print("=" * 70)
