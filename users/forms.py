from . models import User
from django import forms
from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password

from .models import SellerProfile, SellerSettings, User

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from .models import SellerProfile, User


class ExabayLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Enter your username or email",
            "autocomplete": "username",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        })
    )

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            lookup = username
            if "@" in username:
                user = User.objects.filter(email__iexact=username).first()
                if user:
                    lookup = user.username

            self.user_cache = authenticate(
                self.request,
                username=lookup,
                password=password,
            )
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Please enter a correct username/email and password.",
                    code="invalid_login",
                )
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class RegistrationForm(forms.ModelForm):
    ROLE_BUYER = "buyer"
    ROLE_SELLER = "seller"
    ROLE_CHOICES = (
        (ROLE_BUYER, "Buyer"),
        (ROLE_SELLER, "Seller"),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "auth-role__radio"}),
        initial=ROLE_BUYER,
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Create a password",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Confirm your password",
            "autocomplete": "new-password",
        }),
    )

    phone_number = forms.CharField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "phone_number")
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Choose a username",
                "autocomplete": "username",
            }),

            "email": forms.EmailInput(attrs={
                "class": "auth-field__input",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }),
            "phone_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Optional phone number",
                "autocomplete": "tel",
            }),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            validate_password(password1)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].lower()
        user.is_seller = self.cleaned_data["role"] == self.ROLE_SELLER
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()
            if user.is_seller:
                SellerProfile.objects.get_or_create(user=user)

        return user


# class CompleteProfileForm(forms.Form):
#     REGIONAL_CHOICES = [
#         ('', '-- Select Region --'),
#         ('ARU', 'Arusha'),
#         ('DSM', 'Dar es salaam'),
#         ('DOM', 'Dodoma'),
#         ('GEITA', 'Geita'),
#         ('IRINGA', 'Iringa'),
#         ('KGR', 'Kagera'),
#         ('KATAVI', 'Katavi'),
#         ('KGM', 'Kigoma'),
#         ('KLM', 'Kilimanjaro'),
#         ('LINDI', 'Lindi'),
#         ('MNYR', 'Manyara'),
#         ('MARA', 'MARA'),
#         ('MBY', 'Mbeya'),
#         ('MORO', 'Morogoro'),
#         ('MTWARA', 'Mtwara'),
#         ('MWNZ', 'Mwanza'),
#         ('NJOMBE', 'Njombe'),
#         ('PWANI', 'Pwani'),
#         ('RUKWA', 'Rukwa'),
#         ('RVM', 'Ruvuma'),
#         ('SHNYNG', 'Shinyanga'),
#         ('SIMIYU', 'Simiyu'),
#         ('SINGIDA', 'Singida'),
#         ('SONGWE', 'Songwe'),
#         ('TABORA', 'Tabora'),
#         ('TANGA', 'Tanga'),
#     ]
#     ROLE_BUYER = "buyer"
#     ROLE_SELLER = "seller"
#     ROLE_CHOICES = (
#         (ROLE_BUYER, "Continue as Buyer"),
#         (ROLE_SELLER, "Continue as Seller"),
#     )

#     role = forms.ChoiceField(
#         choices=ROLE_CHOICES,
#         widget=forms.RadioSelect(attrs={"class": "auth-role__radio"}),
#         initial=ROLE_BUYER,
#     )
#     phone_number = forms.CharField(
#         required=False,
#         widget=forms.TextInput(attrs={
#             "class": "auth-field__input",
#             "placeholder": "Phone number",
#             "autocomplete": "tel",
#         }),
#     )
#     business_name = forms.CharField(
#         required=False,
#         widget=forms.TextInput(attrs={
#             "class": "auth-field__input",
#             "placeholder": "Registered business name",
#         }),
#     )
#     tin_number = forms.CharField(
#         required=False,
#         widget=forms.TextInput(attrs={
#             "class": "auth-field__input",
#             "placeholder": "TIN number",
#         }),
#     )
#     license_document = forms.FileField(
#         required=False,
#         widget=forms.ClearableFileInput(attrs={"class": "auth-field__input auth-field__input--file"}),
#     )
#     license_expiry_date = forms.DateField(
#         required=False,
#         widget=forms.DateInput(attrs={
#             "class": "auth-field__input",
#             "type": "date",
#         }),
#     )
#     region_choices = forms.ChoiceField(
#         required=True,
#         choices=REGIONAL_CHOICES,
#         widget=forms.Select(attrs={
#             "class": "auth-field__input",
#         }),
#     )
#     vat_number = forms.CharField(
#         required=False,
#         widget=forms.TextInput(attrs={
#             "class": "auth-field__input",
#             "placeholder": "VAT number, if available",
#         }),
#     )
#     vrn_number = forms.CharField(
#         required=False,
#         widget=forms.TextInput(attrs={
#             "class": "auth-field__input",
#             "placeholder": "VRN number, if available",
#         }),
#     )
#     tax_clearance_document = forms.FileField(
#         required=False,
#         widget=forms.ClearableFileInput(attrs={"class": "auth-field__input auth-field__input--file"}),
#     )

#     def __init__(self, *args, user=None, **kwargs):
#         self.user = user
#         super().__init__(*args, **kwargs)

#         if user and not self.is_bound:
#             seller_profile = getattr(user, "sellerprofile", None)
#             self.initial.update({
#                 "role": self.ROLE_SELLER if user.is_seller else self.ROLE_BUYER,
#                 "phone_number": user.phone_number,
#             })
#             if seller_profile:
#                 self.initial.update({
#                     "business_name": seller_profile.business_name,
#                     "tin_number": seller_profile.tin_number,
#                     "license_expiry_date": seller_profile.license_expiry_date,
#                     "vat_number": seller_profile.vat_number,
#                     "vrn_number": seller_profile.vrn_number,
#                 })

#     def clean(self):
#         cleaned_data = super().clean()

#         if cleaned_data.get("role") == self.ROLE_BUYER and not cleaned_data.get("phone_number"):
#             self.add_error("phone_number", "Phone number is required to complete your buyer profile.")

#         if cleaned_data.get("role") == self.ROLE_SELLER:
#             required_seller_fields = (
#                 "business_name",
#                 "tin_number",
#                 "license_expiry_date",
#             )
#             for field in required_seller_fields:
#                 if not cleaned_data.get(field):
#                     self.add_error(field, "This field is required for seller onboarding.")

#             existing_profile = getattr(self.user, "sellerprofile", None)
#             has_existing_license = bool(existing_profile and existing_profile.license_document)
#             if not cleaned_data.get("license_document") and not has_existing_license:
#                 self.add_error("license_document", "Business license document is required for seller onboarding.")

#         return cleaned_data

#     def save(self):
#         role = self.cleaned_data["role"]
#         user = self.user
#         user.phone_number = self.cleaned_data.get("phone_number")
#         user.is_seller = role == self.ROLE_SELLER
#         user.save(update_fields=["phone_number", "is_seller"])

#         if user.is_seller:
#             profile, _ = SellerProfile.objects.get_or_create(user=user)
#             profile.business_name = self.cleaned_data.get("business_name")
#             profile.tin_number = self.cleaned_data.get("tin_number")
#             profile.license_expiry_date = self.cleaned_data.get("license_expiry_date")
#             profile.vat_number = self.cleaned_data.get("vat_number")
#             profile.vrn_number = self.cleaned_data.get("vrn_number")

#             if self.cleaned_data.get("license_document"):
#                 profile.license_document = self.cleaned_data["license_document"]
#             if self.cleaned_data.get("tax_clearance_document"):
#                 profile.tax_clearance_document = self.cleaned_data["tax_clearance_document"]

#             profile.save()

#         return user


class ExabayLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Enter your username or email",
            "autocomplete": "username",
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        })
    )

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username and password:
            lookup = username
            if "@" in username:
                user = User.objects.filter(email__iexact=username).first()
                if user:
                    lookup = user.username

            self.user_cache = authenticate(
                self.request,
                username=lookup,
                password=password,
            )
            if self.user_cache is None:
                raise forms.ValidationError(
                    "Please enter a correct username/email and password.",
                    code="invalid_login",
                )
            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class RegistrationForm(forms.ModelForm):
    ROLE_BUYER = "buyer"
    ROLE_SELLER = "seller"
    ROLE_CHOICES = (
        (ROLE_BUYER, "Buyer"),
        (ROLE_SELLER, "Seller"),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "auth-role__radio"}),
        initial=ROLE_BUYER,
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Create a password",
            "autocomplete": "new-password",
        }),
    )
    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Confirm your password",
            "autocomplete": "new-password",
        }),
    )

    class Meta:
        model = User
        fields = ("username", "email", "phone_number")
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Choose a username",
                "autocomplete": "username",
            }),
            "email": forms.EmailInput(attrs={
                "class": "auth-field__input",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }),
            "phone_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Optional phone number",
                "autocomplete": "tel",
            }),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Passwords do not match.")

        if password1:
            validate_password(password1)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].lower()
        user.is_seller = self.cleaned_data["role"] == self.ROLE_SELLER
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()
            if user.is_seller:
                SellerProfile.objects.get_or_create(user=user)

        return user


class CompleteProfileForm(forms.Form):
    REGIONAL_CHOICES = [
        ('', '-- Select Region --'),
        ('ARU', 'Arusha'),
        ('DSM', 'Dar es salaam'),
        ('DOM', 'Dodoma'),
        ('GEITA', 'Geita'),
        ('IRINGA', 'Iringa'),
        ('KGR', 'Kagera'),
        ('KATAVI', 'Katavi'),
        ('KGM', 'Kigoma'),
        ('KLM', 'Kilimanjaro'),
        ('LINDI', 'Lindi'),
        ('MNYR', 'Manyara'),
        ('MARA', 'MARA'),
        ('MBY', 'Mbeya'),
        ('MORO', 'Morogoro'),
        ('MTWARA', 'Mtwara'),
        ('MWNZ', 'Mwanza'),
        ('NJOMBE', 'Njombe'),
        ('PWANI', 'Pwani'),
        ('RUKWA', 'Rukwa'),
        ('RVM', 'Ruvuma'),
        ('SHNYNG', 'Shinyanga'),
        ('SIMIYU', 'Simiyu'),
        ('SINGIDA', 'Singida'),
        ('SONGWE', 'Songwe'),
        ('TABORA', 'Tabora'),
        ('TANGA', 'Tanga'),
    ]

    ROLE_BUYER = "buyer"
    ROLE_SELLER = "seller"
    ROLE_CHOICES = (
        (ROLE_BUYER, "Continue as Buyer"),
        (ROLE_SELLER, "Continue as Seller"),
    )

    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "auth-role__radio"}),
        initial=ROLE_BUYER,
    )
    phone_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Phone number",
            "autocomplete": "tel",
        }),
    )
    business_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "Registered business name",
        }),
    )
    tin_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "TIN number",
        }),
    )
    license_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "auth-field__input auth-field__input--file"}),
    )
    license_expiry_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            "class": "auth-field__input",
            "type": "date",
        }),
    )
    region_choices = forms.ChoiceField(
        required=True,
        choices=REGIONAL_CHOICES,
        widget=forms.Select(attrs={
            "class": "auth-field__input",
        }),
    )
    vat_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "VAT number, if available",
        }),
    )
    vrn_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "class": "auth-field__input",
            "placeholder": "VRN number, if available",
        }),
    )
    tax_clearance_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "auth-field__input auth-field__input--file"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

        if user and not self.is_bound:
            seller_profile = getattr(user, "sellerprofile", None)
            self.initial.update({
                "role": self.ROLE_SELLER if user.is_seller else self.ROLE_BUYER,
                "phone_number": user.phone_number,
            })
            if seller_profile:
                self.initial.update({
                    "business_name": seller_profile.business_name,
                    "tin_number": seller_profile.tin_number,
                    "license_expiry_date": seller_profile.license_expiry_date,
                    "vat_number": seller_profile.vat_number,
                    "vrn_number": seller_profile.vrn_number,
                })

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data.get("role") == self.ROLE_BUYER and not cleaned_data.get("phone_number"):
            self.add_error("phone_number", "Phone number is required to complete your buyer profile.")

        if cleaned_data.get("role") == self.ROLE_SELLER:
            required_seller_fields = (
                "business_name",
                "tin_number",
                "license_expiry_date",
            )
            for field in required_seller_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, "This field is required for seller onboarding.")

            existing_profile = getattr(self.user, "sellerprofile", None)
            has_existing_license = bool(existing_profile and existing_profile.license_document)
            if not cleaned_data.get("license_document") and not has_existing_license:
                self.add_error("license_document", "Business license document is required for seller onboarding.")

        return cleaned_data

    def save(self):
        role = self.cleaned_data["role"]
        user = self.user
        user.phone_number = self.cleaned_data.get("phone_number")
        user.is_seller = role == self.ROLE_SELLER
        user.save(update_fields=["phone_number", "is_seller"])

        if user.is_seller:
            profile, _ = SellerProfile.objects.get_or_create(user=user)
            profile.business_name = self.cleaned_data.get("business_name")
            profile.tin_number = self.cleaned_data.get("tin_number")
            profile.license_expiry_date = self.cleaned_data.get("license_expiry_date")
            profile.vat_number = self.cleaned_data.get("vat_number")
            profile.vrn_number = self.cleaned_data.get("vrn_number")

            if self.cleaned_data.get("license_document"):
                profile.license_document = self.cleaned_data["license_document"]
            if self.cleaned_data.get("tax_clearance_document"):
                profile.tax_clearance_document = self.cleaned_data["tax_clearance_document"]

            profile.save()

        return user


class AccountProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email", "phone_number")
        widgets = {
            "first_name": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "First name",
                "autocomplete": "given-name",
            }),
            "last_name": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Last name",
                "autocomplete": "family-name",
            }),
            "username": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Username",
                "autocomplete": "username",
            }),
            "email": forms.EmailInput(attrs={
                "class": "auth-field__input",
                "placeholder": "you@example.com",
                "autocomplete": "email",
            }),
            "phone_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Phone number",
                "autocomplete": "tel",
            }),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        exists = (
            User.objects
            .filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if exists:
            raise forms.ValidationError("Another account already uses this email.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"].lower()
        if commit:
            user.save()
        return user


class SellerVerificationSettingsForm(forms.ModelForm):
    class Meta:
        model = SellerProfile
        fields = (
            "business_name",
            "tin_number",
            "license_document",
            "license_expiry_date",
            "vat_number",
            "vrn_number",
            "tax_clearance_document",
        )
        widgets = {
            "business_name": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Registered business name",
            }),
            "tin_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "TIN number",
            }),
            "license_document": forms.ClearableFileInput(attrs={
                "class": "auth-field__input auth-field__input--file",
            }),
            "license_expiry_date": forms.DateInput(attrs={
                "class": "auth-field__input",
                "type": "date",
            }),
            "vat_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "VAT number, if available",
            }),
            "vrn_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "VRN number, if available",
            }),
            "tax_clearance_document": forms.ClearableFileInput(attrs={
                "class": "auth-field__input auth-field__input--file",
            }),
        }


class SellerStorePreferencesForm(forms.ModelForm):
    class Meta:
        model = SellerSettings
        fields = (
            "store_display_name",
            "store_description",
            "business_location",
            "support_email",
            "support_phone",
            "default_currency",
            "low_stock_threshold",
        )
        widgets = {
            "store_display_name": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Store display name",
            }),
            "store_description": forms.Textarea(attrs={
                "class": "auth-field__input",
                "rows": 4,
                "placeholder": "Short description buyers can trust",
            }),
            "business_location": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "City or business location",
            }),
            "support_email": forms.EmailInput(attrs={
                "class": "auth-field__input",
                "placeholder": "support@example.com",
            }),
            "support_phone": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Support phone number",
            }),
            "default_currency": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Tsh",
            }),
            "low_stock_threshold": forms.NumberInput(attrs={
                "class": "auth-field__input",
                "min": 1,
            }),
        }


class SellerNotificationSettingsForm(forms.ModelForm):
    class Meta:
        model = SellerSettings
        fields = (
            "notify_new_orders",
            "notify_verification_updates",
            "notify_low_stock",
            "notify_admin_messages",
        )
        widgets = {
            "notify_new_orders": forms.CheckboxInput(attrs={"class": "auth-role__radio"}),
            "notify_verification_updates": forms.CheckboxInput(attrs={"class": "auth-role__radio"}),
            "notify_low_stock": forms.CheckboxInput(attrs={"class": "auth-role__radio"}),
            "notify_admin_messages": forms.CheckboxInput(attrs={"class": "auth-role__radio"}),
        }


class SellerMobileMoneySettingsForm(forms.ModelForm):
    class Meta:
        model = SellerSettings
        fields = (
            "mobile_money_provider",
            "payout_phone_number",
            "payout_account_name",
        )
        widgets = {
            "mobile_money_provider": forms.Select(attrs={"class": "auth-field__input"}),
            "payout_phone_number": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Mobile money payout number",
                "autocomplete": "tel",
            }),
            "payout_account_name": forms.TextInput(attrs={
                "class": "auth-field__input",
                "placeholder": "Registered account holder name",
            }),
        }


class ExabayPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs.update({
            "class": "auth-field__input",
            "placeholder": "Current password",
            "autocomplete": "current-password",
        })
        self.fields["new_password1"].widget.attrs.update({
            "class": "auth-field__input",
            "placeholder": "New password",
            "autocomplete": "new-password",
        })
        self.fields["new_password2"].widget.attrs.update({
            "class": "auth-field__input",
            "placeholder": "Confirm new password",
            "autocomplete": "new-password",
        })
