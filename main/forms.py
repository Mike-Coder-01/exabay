from django import forms


class ReportSellerForm(forms.Form):
    REASON_CHOICES = (
        ("fake_product", "Fake or misleading product"),
        ("fraud", "Fraud or suspicious payment request"),
        ("non_delivery", "Product not delivered"),
        ("poor_communication", "Poor or unsafe communication"),
        ("document_trust", "Seller trust concern"),
        ("other", "Other"),
    )

    seller_name = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Seller or store name",
        }),
    )
    order_id = forms.CharField(
        required=False,
        max_length=50,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Order ID, if available",
        }),
    )
    reporter_email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Your email address",
        }),
    )
    reason = forms.ChoiceField(
        choices=REASON_CHOICES,
        widget=forms.Select(attrs={"class": "auth-field__input"}),
    )
    details = forms.CharField(
        min_length=20,
        widget=forms.Textarea(attrs={
            "class": "auth-field__input",
            "rows": 6,
            "placeholder": "Describe what happened. Do not include passwords, PINs, or sensitive payment credentials.",
        }),
    )
    evidence_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Optional evidence link",
        }),
    )