"""
Apex Agents Bots: Sales Rep Quality Coach

Analyzes rep email quality and provides real-time coaching.

Features:
- Email quality scoring (subject, body, CTA analysis)
- Benchmarking (compare to high-performers)
- Micro-feedback (specific improvement suggestions)
- Progress tracking (improvement over time)
- Vertical-specific coaching (SaaS tips differ from Fintech)
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
from datetime import datetime
import json


@dataclass
class SentEmail:
    """An email sent by a rep"""
    email_id: str
    rep_id: str
    rep_name: str
    recipient_email: str
    vertical: str  # 'saas', 'fintech', 'ecommerce'
    subject: str
    body: str
    sent_at: datetime
    opened: bool = False
    opened_at: Optional[datetime] = None
    clicked: bool = False
    clicked_at: Optional[datetime] = None
    replied: bool = False
    replied_at: Optional[datetime] = None


@dataclass
class Benchmark:
    """Industry/vertical-specific benchmarks"""
    vertical: str
    metric: str  # 'open_rate', 'click_rate', 'response_rate'
    value: float  # 0.0-1.0


class SubjectLineCoach:
    """Analyzes and coaches on subject line quality"""

    # High-performing subject line characteristics
    GOOD_PATTERNS = {
        'personalization': ['[FirstName]', 'Hi [First]'],  # Uses name
        'curiosity': ['?', '...', 'thought', 'idea', 'quick'],
        'specificity': ['[Company]', '[Metric]', '3x', 'specific number'],
        'short': lambda s: len(s) < 50,  # Under 50 chars
    }

    BAD_PATTERNS = {
        'salesy': ['offer', 'limited time', 'act now', 'exclusive', '$'],
        'generic': ['hello', 'interested', 'introduce', 'connect'],
        'spam_indicators': ['!!', 'FREE', 'URGENT', 'ASAP'],
        'too_long': lambda s: len(s) > 65,
    }

    def score_subject_line(self, subject: str, vertical: str = 'saas') -> Dict:
        """Score a subject line 0-100"""
        score = 50  # Start at 50
        feedback = []

        # Check good patterns
        has_personalization = any(p in subject for p in ['[FirstName]', 'Hi [First]'])
        if has_personalization:
            score += 15
            feedback.append("✓ Personalized with prospect name")

        has_curiosity = any(p in subject for p in ['?', 'thought', 'idea'])
        if has_curiosity:
            score += 15
            feedback.append("✓ Creates curiosity")

        if len(subject) < 50:
            score += 10
            feedback.append("✓ Short and scannable")

        # Check bad patterns
        if any(p in subject for p in ['!!', 'FREE', 'URGENT']):
            score -= 20
            feedback.append("✗ Looks spammy")

        if any(p in subject for p in ['hello', 'interested', 'introduce']):
            score -= 10
            feedback.append("✗ Too generic")

        # Vertical-specific tips
        if vertical == 'saas':
            if any(word in subject for word in ['salesforce', 'integration', 'scaling']):
                score += 5
                feedback.append("✓ SaaS-relevant keyword")

        # Clamp to 0-100
        score = max(0, min(100, score))

        return {
            'score': score,
            'feedback': feedback,
            'grade': self._score_to_grade(score),
            'tips': self._get_improvement_tips(subject, vertical)
        }

    def _score_to_grade(self, score: float) -> str:
        if score >= 80:
            return 'A - Excellent'
        elif score >= 70:
            return 'B - Good'
        elif score >= 60:
            return 'C - Okay'
        elif score >= 50:
            return 'D - Needs work'
        else:
            return 'F - Poor'

    def _get_improvement_tips(self, subject: str, vertical: str) -> List[str]:
        tips = []

        if len(subject) > 65:
            tips.append(f"Shorten to <65 chars (currently {len(subject)})")

        if not any(p in subject for p in ['?', 'thought']):
            tips.append("Add curiosity hook (?, 'thought on', 'idea')")

        if any(p in subject for p in ['Hello', 'Hi']):
            tips.append("Lead with value, not greeting")

        if vertical == 'saas' and not any(word in subject for word in ['scaling', 'sales', 'growth']):
            tips.append(f"Try {vertical}-specific keywords: 'scaling', 'sales team', 'growth'")

        return tips[:3]  # Top 3 tips


class EmailBodyCoach:
    """Analyzes email body structure and quality"""

    # Ideal email structure
    IDEAL_LENGTH = {
        'hook': (10, 30),  # 10-30 words
        'proof': (20, 60),  # 20-60 words
        'cta': (10, 20),   # 10-20 words
    }

    def score_body(self, body: str) -> Dict:
        """Score email body 0-100"""
        score = 50
        feedback = []

        lines = body.strip().split('\n')
        line_count = len([l for l in lines if l.strip()])

        # Check length (rule of thumb: 50-150 words is ideal)
        word_count = len(body.split())
        if 50 <= word_count <= 150:
            score += 15
            feedback.append(f"✓ Good length ({word_count} words)")
        elif word_count < 30:
            score -= 10
            feedback.append(f"✗ Too short ({word_count} words)")
        elif word_count > 250:
            score -= 15
            feedback.append(f"✗ Too long ({word_count} words)")

        # Check structure (should have: hook, value, CTA)
        has_question = '?' in body
        has_cta_word = any(word in body.lower() for word in ['call', 'demo', 'chat', 'talk', 'schedule'])

        if has_question:
            score += 10
            feedback.append("✓ Ends with question (conversational)")

        if has_cta_word:
            score += 10
            feedback.append("✓ Clear call-to-action")

        # Check for value proposition
        value_words = ['reduce', 'improve', 'save', 'increase', '3x', '2x', '70%']
        has_value = any(word in body.lower() for word in value_words)
        if has_value:
            score += 10
            feedback.append("✓ Shows customer value")
        else:
            score -= 5
            feedback.append("✗ Missing value prop")

        # Check for overly salesy language
        salesy_words = ['interested', 'leveraging', 'synergy', 'paradigm', 'disrupt']
        salesy_count = sum(1 for word in salesy_words if word in body.lower())
        if salesy_count > 0:
            score -= salesy_count * 5
            feedback.append(f"✗ Too corporate ({salesy_count} corporate phrases)")

        # Check for personalization
        if '[FirstName]' in body or '[Company]' in body:
            score += 10
            feedback.append("✓ Personalized with placeholders")

        score = max(0, min(100, score))

        return {
            'score': score,
            'word_count': word_count,
            'feedback': feedback,
            'grade': SubjectLineCoach()._score_to_grade(score),
            'improvements': self._get_body_tips(body, word_count)
        }

    def _get_body_tips(self, body: str, word_count: int) -> List[str]:
        tips = []

        if word_count > 200:
            tips.append(f"Cut to <150 words (currently {word_count})")

        if '?' not in body:
            tips.append("End with a question (more conversational)")

        if not any(word in body.lower() for word in ['reduce', 'improve', 'save', '3x']):
            tips.append("Add concrete value metric ('save $X', '3x faster')")

        return tips[:2]


class RepCoach:
    """Main coaching engine combining subject + body analysis"""

    def __init__(self):
        self.subject_coach = SubjectLineCoach()
        self.body_coach = EmailBodyCoach()

        # Benchmark data
        self.benchmarks = {
            'saas': {
                'open_rate': 0.14,
                'click_rate': 0.03,
                'response_rate': 0.05,
            },
            'fintech': {
                'open_rate': 0.12,
                'click_rate': 0.025,
                'response_rate': 0.04,
            },
            'ecommerce': {
                'open_rate': 0.13,
                'click_rate': 0.03,
                'response_rate': 0.035,
            }
        }

    def coach_email(self, email: SentEmail) -> Dict:
        """
        Provide comprehensive coaching on a sent email.

        Returns:
        {
            'email_id': str,
            'rep_id': str,
            'overall_score': 0-100,
            'subject_score': {...},
            'body_score': {...},
            'performance_vs_benchmark': {...},
            'key_feedback': List[str],
            'action_items': List[str],
        }
        """

        # Score subject and body
        subject_score = self.subject_coach.score_subject_line(email.subject, email.vertical)
        body_score = self.body_coach.score_body(email.body)

        # Calculate overall score (weighted average)
        overall = (subject_score['score'] * 0.4) + (body_score['score'] * 0.6)

        # Performance vs benchmark
        vertical_benchmarks = self.benchmarks.get(email.vertical, self.benchmarks['saas'])
        opened = 1 if email.opened else 0
        actual_open_rate = opened  # For single email, it's 0 or 1
        benchmark_open_rate = vertical_benchmarks['open_rate']
        open_rate_performance = (actual_open_rate / benchmark_open_rate * 100) if benchmark_open_rate > 0 else 0

        # Compile feedback
        key_feedback = []
        key_feedback.extend([f['subject']['feedback'][0] for f in [{'subject': subject_score}] if subject_score['feedback']])
        key_feedback.extend([f['body']['feedback'][0] for f in [{'body': body_score}] if body_score['feedback']])

        # Action items (what to do next)
        action_items = []
        if subject_score['score'] < 70:
            action_items.append(f"Improve subject line: {', '.join(subject_score['tips'][:1])}")
        if body_score['score'] < 70:
            action_items.append(f"Improve email body: {', '.join(body_score['improvements'][:1])}")
        if not email.opened and email.opened_at is None:
            action_items.append("No open yet - may need follow-up in 48h")

        return {
            'email_id': email.email_id,
            'rep_id': email.rep_id,
            'rep_name': email.rep_name,
            'overall_score': round(overall, 1),
            'overall_grade': SubjectLineCoach()._score_to_grade(overall),
            'subject_line': {
                'score': subject_score['score'],
                'grade': subject_score['grade'],
                'feedback': subject_score['feedback'],
                'tips': subject_score['tips'],
            },
            'email_body': {
                'score': body_score['score'],
                'grade': body_score['grade'],
                'word_count': body_score['word_count'],
                'feedback': body_score['feedback'],
                'improvements': body_score['improvements'],
            },
            'performance_vs_benchmark': {
                'open_rate_actual': actual_open_rate,
                'open_rate_benchmark': benchmark_open_rate,
                'performance_vs_benchmark_pct': round(open_rate_performance, 0),
            },
            'key_feedback': key_feedback[:3],
            'action_items': action_items,
            'recommendation': self._get_recommendation(overall),
        }

    def _get_recommendation(self, score: float) -> str:
        if score >= 80:
            return "Great email! Keep this template. High likelihood of opens."
        elif score >= 70:
            return "Good email. Minor improvements could boost opens 20%+."
        elif score >= 60:
            return "Okay email. Several improvements suggested (see above)."
        else:
            return "Needs work. Follow the tips above to improve open rates."


if __name__ == '__main__':
    coach = RepCoach()

    # Example 1: High-quality email
    email1 = SentEmail(
        email_id='em_001',
        rep_id='rep_001',
        rep_name='Sarah',
        recipient_email='john@techcorp.com',
        vertical='saas',
        subject='John, quick thought on scaling your sales team',
        body="""Hi John,

I noticed you visited our pricing page recently.

Most SaaS teams we work with reduce cost-per-lead by 70% in the first 30 days.

Worth a quick call?

Sarah""",
        sent_at=datetime.utcnow(),
        opened=True
    )

    result = coach.coach_email(email1)
    print("=== COACHING RESULT: HIGH-QUALITY EMAIL ===")
    print(f"Overall Score: {result['overall_score']}/100 ({result['overall_grade']})")
    print(f"\nSubject Line: {result['subject_line']['grade']}")
    print(f"  Feedback: {', '.join(result['subject_line']['feedback'][:2])}")
    print(f"\nEmail Body: {result['email_body']['grade']}")
    print(f"  Word count: {result['email_body']['word_count']}")
    print(f"  Feedback: {', '.join(result['email_body']['feedback'][:2])}")
    print(f"\nRecommendation: {result['recommendation']}")
    print()

    # Example 2: Low-quality email
    email2 = SentEmail(
        email_id='em_002',
        rep_id='rep_002',
        rep_name='Mike',
        recipient_email='jane@startup.com',
        vertical='saas',
        subject='Hello from Apex!!!',
        body="""Hi Jane,

I want to introduce you to Apex. We offer a cutting-edge SaaS platform leveraging AI to synergize your sales process.

Interested?

Mike""",
        sent_at=datetime.utcnow(),
        opened=False
    )

    result = coach.coach_email(email2)
    print("=== COACHING RESULT: LOW-QUALITY EMAIL ===")
    print(f"Overall Score: {result['overall_score']}/100 ({result['overall_grade']})")
    print(f"\nAction Items:")
    for item in result['action_items']:
        print(f"  - {item}")
    print(f"\nRecommendation: {result['recommendation']}")
