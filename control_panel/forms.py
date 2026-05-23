from django import forms


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