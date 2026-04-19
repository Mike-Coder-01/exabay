from . models import User
from django import forms

# User Creation Form
class UserRegisterUser (forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'phone_number', 'is_seller']