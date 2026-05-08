from django.conf import settings
from django.db import models
from .approval_types import APPROVAL_TYPE_CHOICES, APPROVAL_TYPES_BY_ID


class ApprovalRequest(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('complete', 'Complete'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='approval_requests',
    )
    site = models.ForeignKey(
        'usgs_sites.Site',
        on_delete=models.CASCADE,
        related_name='approval_requests',
    )
    approval_type = models.CharField(max_length=50, choices=APPROVAL_TYPE_CHOICES)
    period_start = models.DateField()
    period_end = models.DateField()
    response_data = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return (
            f"{self.site.site_no} — {self.get_approval_type_display()} "
            f"({self.period_start} to {self.period_end})"
        )

    def completion_pct(self):
        at = APPROVAL_TYPES_BY_ID.get(self.approval_type)
        if not at:
            return 0
        items = at['items']
        response_data = self.response_data

        # Mirror the conditional visibility logic from the frontend
        visible = {}
        for item in items:
            if item['type'] == 'section':
                continue
            key = item['key']
            cond_on = item.get('conditional_on')
            if not cond_on:
                visible[key] = True
            else:
                cond_val = item.get('conditional_value', 'yes')
                parent_visible = visible.get(cond_on, False)
                parent_answer = response_data.get(cond_on, {}).get('answer', '')
                visible[key] = parent_visible and (parent_answer == cond_val)

        questions = [
            item for item in items
            if item['type'] in ('yn', 'date', 'text') and visible.get(item['key'], False)
        ]
        if not questions:
            return 0
        answered = 0
        for q in questions:
            r = response_data.get(q['key'], {})
            if q['type'] == 'yn' and r.get('answer'):
                answered += 1
            elif q['type'] == 'date' and r.get('date'):
                answered += 1
            elif q['type'] == 'text' and r.get('text', '').strip():
                answered += 1
        return round(answered / len(questions) * 100)
