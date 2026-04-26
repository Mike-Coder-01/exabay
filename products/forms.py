from django import forms
from .models import Product, Category


class ProductCreationForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'category', 'name', 'description', 'price', 'stock', 'is_featured'
        ]
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-input',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter a product name',
                'maxlength': '120',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input form-input--textarea',
                'placeholder': 'Write a short, compelling product description',
                'rows': '5',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0.00',
                'min': '0',
                'step': '0.01',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0',
                'min': '0',
                'step': '1',
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'toggle-switch__input',
                'role': 'switch',
            }),
        }


class ProductUpdateForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['category', 'name', 'description', 'price', 'stock', 'is_available', 'is_featured']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-input',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Enter a product name',
                'maxlength': '120',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-input form-input--textarea',
                'placeholder': 'Write a short, compelling product description',
                'rows': '5',
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0.00',
                'min': '0',
                'step': '0.01',
            }),
            'stock': forms.NumberInput(attrs={
                'class': 'form-input',
                'placeholder': '0',
                'min': '0',
                'step': '1',
            }),
            'is_available': forms.CheckboxInput(attrs={
                'class': 'toggle-switch__input',
                'role': 'switch',
            }),
            'is_featured': forms.CheckboxInput(attrs={
                'class': 'toggle-switch__input',
                'role': 'switch',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Add category queryset to show all available categories
        self.fields['category'].queryset = Category.objects.all()

    def clean(self):
        cleaned_data = super().clean()

        # Safety check (extra layer of protection)
        if self.instance and self.user:
            if self.instance.seller.user != self.user:
                raise forms.ValidationError("You are not allowed to edit this product.")

        # Check featured limit if trying to feature this product
        if cleaned_data.get('is_featured') and self.instance:
            from .models import Product
            featured_count = Product.objects.filter(
                seller=self.instance.seller,
                is_featured=True
            ).exclude(pk=self.instance.pk).count()
            
            if featured_count >= 3:
                self.add_error(
                    'is_featured',
                    'Maximum of 3 featured products allowed. Please unfeature another product first.'
                )

        return cleaned_data