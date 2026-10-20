"""
Apex Agents Bots: Vertical-Specific AI Models

Provides buying signal detection and coaching recommendations tailored to:
- SaaS (scaling/growth/efficiency focus)
- Fintech (compliance/risk/security focus)
- E-commerce (volume/CAC/ROAS focus)

Each vertical has different signal weights, coaching strategies, and lead prioritization.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class Vertical(str, Enum):
    SAAS = "saas"
    FINTECH = "fintech"
    ECOMMERCE = "ecommerce"


@dataclass
class VerticalSignalWeight:
    """Signal weight multiplier for a specific vertical"""
    signal_type: str
    base_weight: float  # 0.5 = half weight, 2.0 = double weight
    relevance: str  # Why this matters for this vertical


class VerticalModels:
    """
    Vertical-specific signal weights and recommendations.

    Philosophy: Different verticals have different buying behaviors:
    - SaaS buyers care about integrations, pricing, scaling
    - Fintech buyers care about compliance, security, API docs
    - E-commerce buyers care about ROI, case studies, pricing
    """

    # SaaS-specific signal weights
    SAAS_SIGNAL_WEIGHTS = {
        'website_visit': {
            '/pricing': 2.0,  # Pricing page = serious buyer in SaaS
            '/integrations': 2.0,  # Want to see if it connects to their stack
            '/security': 1.5,  # Growing concern for compliance
            '/customers': 1.5,  # Want to see social proof
            '/api_docs': 1.8,  # Technical evaluation
            'default': 1.0,
        },
        'email_open': {'default': 1.2},
        'email_click': {'default': 1.3},
        'form_submit': {
            'demo_request': 2.5,  # Demo request = high intent in SaaS
            'trial_signup': 2.2,
            'whitepaper': 1.5,
            'default': 1.5,
        },
        'deal_created': {'default': 2.0},  # Deal stage = serious
    }

    # Fintech-specific signal weights
    FINTECH_SIGNAL_WEIGHTS = {
        'website_visit': {
            '/compliance': 2.5,  # HIGHEST for Fintech - compliance is critical
            '/security': 2.5,
            '/audits': 2.3,
            '/api_docs': 2.2,
            '/pricing': 1.8,
            'default': 1.0,
        },
        'email_open': {'default': 1.2},
        'email_click': {'default': 1.3},
        'form_submit': {
            'security_audit': 2.5,  # Security audit request = serious
            'api_access': 2.5,
            'compliance_check': 2.4,
            'trial_signup': 2.0,
            'default': 1.5,
        },
        'deal_created': {'default': 2.0},
    }

    # E-commerce-specific signal weights
    ECOMMERCE_SIGNAL_WEIGHTS = {
        'website_visit': {
            '/roi_calculator': 2.5,  # ROI calculator = serious intent (E-comm ROI obsessed)
            '/case_studies': 2.0,
            '/pricing': 2.0,
            '/integrations': 1.8,
            '/customers': 1.5,
            'default': 1.0,
        },
        'email_open': {'default': 1.2},
        'email_click': {'default': 1.3},
        'form_submit': {
            'roi_calculator': 2.5,
            'case_study': 2.0,
            'trial_signup': 1.8,
            'default': 1.5,
        },
        'deal_created': {'default': 2.0},
    }

    @staticmethod
    def get_signal_weight(vertical: str, signal_type: str, metadata: Optional[Dict] = None) -> float:
        """
        Get the weight multiplier for a signal based on vertical.

        Examples:
        - SaaS pricing page = 2.0x
        - Fintech compliance = 2.5x
        - E-commerce ROI calc = 2.5x
        """
        weights_map = {
            'saas': VerticalModels.SAAS_SIGNAL_WEIGHTS,
            'fintech': VerticalModels.FINTECH_SIGNAL_WEIGHTS,
            'ecommerce': VerticalModels.ECOMMERCE_SIGNAL_WEIGHTS,
        }

        if vertical not in weights_map:
            return 1.0  # Default weight

        vertical_weights = weights_map[vertical]

        if signal_type not in vertical_weights:
            return 1.0

        signal_weights = vertical_weights[signal_type]

        # If it's a dict with page/form metadata
        if isinstance(signal_weights, dict) and metadata:
            key = metadata.get('page') or metadata.get('form_type')
            if key and key in signal_weights:
                return signal_weights[key]
            return signal_weights.get('default', 1.0)

        # If it's a dict with 'default' key
        if isinstance(signal_weights, dict):
            return signal_weights.get('default', 1.0)

        return signal_weights

    @staticmethod
    def get_coaching_recommendations(vertical: str, email_score: float) -> str:
        """Get vertical-specific coaching based on email quality score."""

        coaching_by_vertical = {
            'saas': {
                'high': 'SaaS buyers love: (1) Free trial CTA, (2) integration mentions, (3) "time to value" language',
                'medium': 'Try: Demo request angle, mention their specific tools/integrations, add social proof from similar companies',
                'low': 'Remove: Generic "I wanted to reach out", corporate jargon. Add: personalization + specific pain point + proof',
            },
            'fintech': {
                'high': 'Fintech buyers respect: (1) Compliance certifications, (2) security features, (3) audit reports',
                'medium': 'Try: Ask about compliance requirements, mention SOC2/ISO, reference API security, add regulatory benefits',
                'low': 'Remove: Pushy language. Add: Compliance angle, security language, reference industry standards (PCI, GDPR, etc)',
            },
            'ecommerce': {
                'high': 'E-commerce buyers want: (1) ROI metrics, (2) case studies with revenue impact, (3) integration with tools they use',
                'medium': 'Try: Include ROI calculator link, mention revenue impact, reference competitors they know, add conversion metrics',
                'low': 'Remove: Feature list dumps. Add: revenue/ROI angle, case studies with numbers, competitive comparison',
            },
        }

        vertical_key = vertical.lower()
        if vertical_key not in coaching_by_vertical:
            return "Focus on personalization and specific pain points."

        recommendations = coaching_by_vertical[vertical_key]

        if email_score >= 75:
            return recommendations['high']
        elif email_score >= 50:
            return recommendations['medium']
        else:
            return recommendations['low']

    @staticmethod
    def get_personalization_tips(vertical: str, company_size: str) -> List[str]:
        """Get personalization tips for vertical + company size combo."""

        tips = {
            'saas': {
                'small': [
                    'Mention their specific use case (not generic "sales team")',
                    'Reference cost savings angle (SMBs care about budget)',
                    'Keep CTA simple: "Quick 15-min call?"',
                ],
                'mid-market': [
                    'Mention their industry (SaaS/Healthcare/Finance)',
                    'Reference ROI and efficiency gains',
                    'Add social proof from similar-sized companies',
                ],
                'enterprise': [
                    'Mention security/compliance certifications',
                    'Reference scalability and team size',
                    'Add case study with revenue impact numbers',
                ],
            },
            'fintech': {
                'small': [
                    'Emphasize regulatory compliance benefits',
                    'Keep technical language but simple',
                    'Mention specific compliance frameworks they face (SOC2, ISO 27001)',
                ],
                'mid-market': [
                    'Reference specific regulatory challenges in their vertical',
                    'Mention audit readiness and compliance automation',
                    'Add case study from similar fintech company',
                ],
                'enterprise': [
                    'Lead with security certifications and audit trails',
                    'Reference enterprise SLA and dedicated support',
                    'Add case study with compliance impact metrics',
                ],
            },
            'ecommerce': {
                'small': [
                    'Focus on quick ROI and conversion lift',
                    'Mention their specific e-commerce platform (Shopify, WooCommerce)',
                    'Use conversion rate language, not feature language',
                ],
                'mid-market': [
                    'Reference average AOV and conversion benchmarks',
                    'Mention multi-channel attribution benefits',
                    'Add case study with revenue impact from similar retailer',
                ],
                'enterprise': [
                    'Emphasize scale: "handles 10M+ events/day"',
                    'Reference enterprise integrations (Salesforce, Marketo)',
                    'Add case study with 7-figure revenue impact',
                ],
            },
        }

        vertical_key = vertical.lower()
        company_key = company_size.lower()

        if vertical_key in tips and company_key in tips[vertical_key]:
            return tips[vertical_key][company_key]

        return ['Personalize to their specific role', 'Reference their company/vertical', 'Use specific examples, not generic benefits']


# Test the module
if __name__ == '__main__':
    # Test SaaS weights
    assert VerticalModels.get_signal_weight('saas', 'website_visit', {'page': '/pricing'}) == 2.0
    assert VerticalModels.get_signal_weight('fintech', 'website_visit', {'page': '/compliance'}) == 2.5
    assert VerticalModels.get_signal_weight('ecommerce', 'form_submit', {'form_type': 'roi_calculator'}) == 2.5

    # Test coaching
    saas_coaching = VerticalModels.get_coaching_recommendations('saas', 80)
    assert 'SaaS' in saas_coaching

    # Test tips
    tips = VerticalModels.get_personalization_tips('saas', 'small')
    assert len(tips) == 3

    print("✅ All vertical models tests passed!")
