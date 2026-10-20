"""
Apex Agents Bots: Real-Time Behavioral Confidence Engine

Scores leads 0-100 based on real-time behavioral signals:
- Website visits (tracking pixel)
- Email engagement (opens, clicks, forwards)
- LinkedIn activity (profile views, job changes)
- Form submissions
- CRM activity (deal stage, notes)

Target accuracy: 70%+ (detect active opportunities vs stale/uninterested leads)
"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import math


@dataclass
class BehavioralSignal:
    """A single behavioral event for a lead"""
    signal_type: str  # 'website_visit', 'email_open', 'email_click', 'linkedin_view', 'form_submit', 'deal_update'
    timestamp: datetime
    metadata: Dict  # Additional data (page_url, email_subject, etc.)
    weight: float = 1.0  # How important is this signal? (0.5 = half weight, 2.0 = double)


@dataclass
class LeadSignalHistory:
    """All signals for a lead over time"""
    lead_id: str
    email: str
    company: str
    vertical: str  # 'saas', 'fintech', 'ecommerce', 'agency', 'other'
    signals: List[BehavioralSignal]
    last_updated: datetime

    def get_signals_last_n_days(self, days: int) -> List[BehavioralSignal]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        return [s for s in self.signals if s.timestamp >= cutoff]


class ConfidenceEngineV1:
    """
    Real-time behavioral confidence scoring engine.

    Scoring logic:
    - Recent website visits (last 7 days): +15 points per visit
    - Email opens (last 7 days): +10 points per open
    - Email clicks (last 7 days): +20 points per click
    - Email forward (last 7 days): +30 points (high intent signal)
    - Form submission (last 30 days): +25 points
    - LinkedIn profile view (last 7 days): +10 points
    - LinkedIn job change (last 30 days): +20 points
    - CRM deal created (last 30 days): +40 points
    - CRM deal update (last 7 days): +10 points per update

    Decay factors (older signals are weighted less):
    - Last 24h: 100% weight
    - 2-7 days ago: 70% weight
    - 8-30 days ago: 40% weight
    - 31+ days ago: 10% weight

    Floor/ceiling: 0-100 (confidence score)
    """

    # Base signal weights
    SIGNAL_WEIGHTS = {
        'website_visit': 15,
        'email_open': 10,
        'email_click': 20,
        'email_forward': 30,
        'form_submit': 25,
        'linkedin_view': 10,
        'linkedin_job_change': 20,
        'deal_created': 40,
        'deal_update': 10,
        'deal_stage_advance': 15,
    }

    # Time-based decay multipliers
    def _get_decay_multiplier(self, signal_age_days: float) -> float:
        """Recent signals are more important than old ones"""
        if signal_age_days <= 1:
            return 1.0
        elif signal_age_days <= 7:
            return 0.7
        elif signal_age_days <= 30:
            return 0.4
        else:
            return 0.1

    def _calculate_recency_bonus(self, signals: List[BehavioralSignal]) -> float:
        """Bonus if lead has signals in last 24 hours (actively engaging NOW)"""
        now = datetime.utcnow()
        recent_signals = [s for s in signals if (now - s.timestamp).total_seconds() < 86400]

        if len(recent_signals) > 0:
            return 15  # +15 bonus for active in last 24h
        return 0

    def _calculate_signal_score(self, signals: List[BehavioralSignal]) -> float:
        """Calculate raw signal score before normalization"""
        now = datetime.utcnow()
        total_score = 0.0

        for signal in signals:
            age_days = (now - signal.timestamp).days
            base_weight = self.SIGNAL_WEIGHTS.get(signal.signal_type, 10)
            decay = self._get_decay_multiplier(age_days)
            signal_weight = signal.weight  # Custom weight override (e.g., 2.0 for high-priority signals)

            signal_score = base_weight * decay * signal_weight
            total_score += signal_score

        return total_score

    def _calculate_signal_diversity_bonus(self, signals: List[BehavioralSignal]) -> float:
        """Bonus if lead shows signals across multiple channels (more credible interest)"""
        signal_types = set(s.signal_type for s in signals)

        if len(signal_types) >= 3:
            return 10  # Multi-channel engagement = higher confidence
        elif len(signal_types) >= 2:
            return 5
        else:
            return 0

    def _calculate_engagement_frequency(self, signals: List[BehavioralSignal]) -> float:
        """Bonus if lead engages frequently (multiple touches in short time)"""
        signals_last_7_days = [s for s in signals if (datetime.utcnow() - s.timestamp).days <= 7]

        if len(signals_last_7_days) >= 5:
            return 10  # Multiple touches in last week
        elif len(signals_last_7_days) >= 3:
            return 5
        else:
            return 0

    def _apply_decay_for_staleness(self, signals: List[BehavioralSignal]) -> float:
        """Penalty if lead has gone cold (no signals for 14+ days)"""
        if not signals:
            return -50  # No signals = very low confidence

        last_signal_time = max(s.timestamp for s in signals)
        days_since_last = (datetime.utcnow() - last_signal_time).days

        if days_since_last >= 30:
            return -30  # No activity for 30+ days = stale
        elif days_since_last >= 14:
            return -15  # No activity for 2+ weeks = cooling
        else:
            return 0  # Recent activity = no penalty

    def score(self, lead: LeadSignalHistory) -> Dict:
        """
        Calculate confidence score for a lead.

        Returns:
        {
            'lead_id': str,
            'email': str,
            'confidence_score': 0-100,
            'confidence_level': 'low' | 'medium' | 'high' | 'very_high',
            'top_signals': List[str],  # What drove the score up?
            'risk_factors': List[str],  # What should we worry about?
            'recommendation': str,  # What should rep do?
            'calculation_details': Dict,  # Transparent breakdown
        }
        """

        if not lead.signals:
            return {
                'lead_id': lead.lead_id,
                'email': lead.email,
                'confidence_score': 0,
                'confidence_level': 'very_low',
                'top_signals': [],
                'risk_factors': ['No behavioral signals recorded'],
                'recommendation': 'Enrich lead data or remove from nurture',
                'calculation_details': {
                    'signal_score': 0,
                    'recency_bonus': 0,
                    'diversity_bonus': 0,
                    'frequency_bonus': 0,
                    'staleness_penalty': 0,
                    'final_score': 0,
                }
            }

        # Calculate component scores
        signal_score = self._calculate_signal_score(lead.signals)
        recency_bonus = self._calculate_recency_bonus(lead.signals)
        diversity_bonus = self._calculate_signal_diversity_bonus(lead.signals)
        frequency_bonus = self._calculate_engagement_frequency(lead.signals)
        staleness_penalty = self._apply_decay_for_staleness(lead.signals)

        # Raw confidence score (before normalization)
        raw_score = signal_score + recency_bonus + diversity_bonus + frequency_bonus + staleness_penalty

        # Normalize to 0-100 range (using soft cap at 85, hard cap at 100)
        if raw_score > 100:
            confidence_score = 85 + (min(raw_score - 100, 30) * 0.5)  # Diminishing returns above 100
        else:
            confidence_score = raw_score

        confidence_score = max(0, min(100, confidence_score))  # Clamp to 0-100

        # Determine confidence level
        if confidence_score >= 75:
            confidence_level = 'very_high'
        elif confidence_score >= 60:
            confidence_level = 'high'
        elif confidence_score >= 40:
            confidence_level = 'medium'
        else:
            confidence_level = 'low'

        # Identify top signals
        now = datetime.utcnow()
        signal_contributions = []
        for signal in lead.signals:
            age_days = (now - signal.timestamp).days
            base_weight = self.SIGNAL_WEIGHTS.get(signal.signal_type, 10)
            decay = self._get_decay_multiplier(age_days)
            contribution = base_weight * decay * signal.weight
            signal_contributions.append((signal.signal_type, contribution, signal))

        signal_contributions.sort(key=lambda x: x[1], reverse=True)
        top_signals = [f"{s[0]} (+{s[1]:.0f})" for s in signal_contributions[:3]]

        # Identify risk factors
        risk_factors = []
        if staleness_penalty < -10:
            risk_factors.append(f"No activity for {(datetime.utcnow() - max(s.timestamp for s in lead.signals)).days} days")
        if len(set(s.signal_type for s in lead.signals)) == 1:
            risk_factors.append("Only one channel of engagement (not multi-channel)")
        if len(lead.get_signals_last_n_days(7)) == 0:
            risk_factors.append("No engagement in last 7 days")

        # Recommendation
        if confidence_score >= 75:
            recommendation = "Hot lead - prioritize follow-up within 24h"
        elif confidence_score >= 60:
            recommendation = "Warm lead - regular nurture sequence, likely to convert"
        elif confidence_score >= 40:
            recommendation = "Cool lead - longer nurture cycle needed"
        else:
            recommendation = "Cold/stale - consider removing or re-engaging with fresh outreach"

        return {
            'lead_id': lead.lead_id,
            'email': lead.email,
            'company': lead.company,
            'vertical': lead.vertical,
            'confidence_score': round(confidence_score, 1),
            'confidence_level': confidence_level,
            'top_signals': top_signals,
            'risk_factors': risk_factors if risk_factors else ['None identified'],
            'recommendation': recommendation,
            'calculation_details': {
                'signal_score': round(signal_score, 1),
                'recency_bonus': round(recency_bonus, 1),
                'diversity_bonus': round(diversity_bonus, 1),
                'frequency_bonus': round(frequency_bonus, 1),
                'staleness_penalty': round(staleness_penalty, 1),
                'raw_score': round(raw_score, 1),
                'final_score': round(confidence_score, 1),
                'total_signals': len(lead.signals),
                'signals_last_7_days': len(lead.get_signals_last_n_days(7)),
            }
        }


# Example usage / testing
if __name__ == '__main__':
    engine = ConfidenceEngineV1()

    # Example 1: Hot lead (very active)
    now = datetime.utcnow()
    hot_lead = LeadSignalHistory(
        lead_id='lead_001',
        email='sarah@techcorp.com',
        company='TechCorp',
        vertical='saas',
        signals=[
            BehavioralSignal('website_visit', now - timedelta(hours=2), {'page': '/pricing'}, weight=2.0),
            BehavioralSignal('website_visit', now - timedelta(hours=24), {'page': '/integrations'}, weight=2.0),
            BehavioralSignal('website_visit', now - timedelta(days=2), {'page': '/security'}, weight=1.0),
            BehavioralSignal('email_open', now - timedelta(hours=6), {'subject': 'New Salesforce Integration'}, weight=1.0),
            BehavioralSignal('email_click', now - timedelta(hours=5), {'url': 'pricing-page'}, weight=1.5),
            BehavioralSignal('form_submit', now - timedelta(days=1), {'form': 'demo-request'}, weight=2.0),
            BehavioralSignal('linkedin_view', now - timedelta(hours=48), {}, weight=1.0),
        ],
        last_updated=now,
    )

    result = engine.score(hot_lead)
    print("=== HOT LEAD ===")
    print(json.dumps(result, indent=2, default=str))
    print()

    # Example 2: Cold lead (no recent activity)
    cold_lead = LeadSignalHistory(
        lead_id='lead_002',
        email='john@startup.com',
        company='StartupXYZ',
        vertical='fintech',
        signals=[
            BehavioralSignal('email_open', now - timedelta(days=45), {'subject': 'Cold email'}, weight=1.0),
        ],
        last_updated=now - timedelta(days=45),
    )

    result = engine.score(cold_lead)
    print("=== COLD LEAD ===")
    print(json.dumps(result, indent=2, default=str))
    print()

    # Example 3: Medium lead (some signals, but not recent)
    medium_lead = LeadSignalHistory(
        lead_id='lead_003',
        email='alice@agency.com',
        company='CreativeAgency',
        vertical='agency',
        signals=[
            BehavioralSignal('website_visit', now - timedelta(days=8), {'page': '/pricing'}, weight=1.0),
            BehavioralSignal('email_open', now - timedelta(days=12), {'subject': 'Product Update'}, weight=1.0),
            BehavioralSignal('form_submit', now - timedelta(days=15), {'form': 'webinar-signup'}, weight=1.0),
        ],
        last_updated=now - timedelta(days=8),
    )

    result = engine.score(medium_lead)
    print("=== MEDIUM LEAD ===")
    print(json.dumps(result, indent=2, default=str))
