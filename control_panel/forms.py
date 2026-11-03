from django import forms
from django import forms
from control_panel.models import SellerPayoutResolution

class SellerRejectionForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "auth-field__input",
            "rows": 4,
            "placeholder": "Explain what the seller needs to fix before verification.",
        }),
        min_length=10,
    )


class ContactUserForm(forms.Form):
    subject = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Subject",
        }),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            "class": "auth-field__input",
            "rows": 4,
            "placeholder": "Write a clear follow-up message.",
        }),
        min_length=5,
    )



from django import forms

from control_panel.models import SellerPayoutInvestigation


class SellerPayoutInvestigationForm(forms.ModelForm):

    class Meta:
        model = SellerPayoutInvestigation

        fields = [
            "reason",
            "provider_reference",
            "findings",
            "outcome",
        ]

        widgets = {
            "reason": forms.Textarea(attrs={
                "rows": 3,
                "placeholder": "Why is this payout being investigated?",
            }),
            "provider_reference": forms.TextInput(attrs={
                "placeholder": "AzamPay transaction reference (if available)",
            }),
            "findings": forms.Textarea(attrs={
                "rows": 5,
                "placeholder": "Record evidence received from AzamPay",
            }),
        }

    def clean(self):
        cleaned_data = super().clean()

        outcome = cleaned_data.get("outcome")
        findings = cleaned_data.get("findings", "").strip()
        reference = cleaned_data.get(
            "provider_reference", ""
        ).strip()

        if outcome in [
            SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID,
            SellerPayoutInvestigation.OUTCOME_CONFIRMED_FAILED,
        ]:
            if not findings:
                self.add_error(
                    "findings",
                    "Evidence is required for a confirmed outcome.",
                )

            if not reference:
                self.add_error(
                    "provider_reference",
                    "A provider reference is required for a confirmed outcome.",
                )

        return cleaned_data



class SellerPayoutResolutionRequestForm(forms.Form):

    investigation_id = forms.IntegerField(
        widget=forms.HiddenInput()
    )

    proposed_outcome = forms.ChoiceField(
        choices=SellerPayoutResolution.OUTCOME_CHOICES
    )

    provider_reference = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "AzamPay reference or support case ID",
            }
        ),
    )

    evidence = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Describe the evidence received from AzamPay",
            }
        ),
    )


class SellerPayoutResolutionDecisionForm(forms.Form):

    decision = forms.ChoiceField(
        choices=[
            (
                SellerPayoutResolution.STATUS_APPROVED,
                "Approve resolution",
            ),
            (
                SellerPayoutResolution.STATUS_REJECTED,
                "Reject resolution",
            ),
        ],
        widget=forms.RadioSelect,
    )

    approval_notes = forms.CharField(
        min_length=10,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": (
                    "Explain your decision and the evidence reviewed."
                ),
            }
        ),
    )


class SellerPayoutFinalizationForm(forms.Form):
    verification_method = forms.CharField(
        max_length=100,
        help_text="Example: Verified AzamPay support ticket",
    )

    provider_reference = forms.CharField(max_length=150)

    verification_evidence = forms.CharField(
        min_length=20,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Record who confirmed the outcome, when, and how.",
    )

    provider_confirmed = forms.BooleanField(
        required=True,
        label=(
            "I independently verified the final transaction "
            "outcome with AzamPay."
        ),
    )
