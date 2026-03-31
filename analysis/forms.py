from django import forms

from .report_types import REPORT_TYPE_CHOICES


class NewReportForm(forms.Form):
    site_no = forms.CharField(
        max_length=20,
        label='USGS Site Number',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. 09419800', 'autofocus': True, 'class': 'form-control'}),
    )
    report_type = forms.ChoiceField(
        choices=REPORT_TYPE_CHOICES,
        label='Report Type',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    period_start = forms.DateField(
        label='Period Start',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    period_end = forms.DateField(
        label='Period End',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('period_start')
        end = cleaned.get('period_end')
        if start and end and end < start:
            raise forms.ValidationError('Period end must be on or after period start.')
        return cleaned
