from django.shortcuts import render
from products.models import Product

# Create your views here.
def home(request):
    products = Product.objects.filter(is_available=True)\
        .select_related('seller__user', 'category')\
        .prefetch_related('images')

    return render(request, "main/index.html", {
        "products": products
    })

# products = Product.objects.filter(is_available=True)\
#     .select_related('seller__user', 'category')\
#     .prefetch_related('images')
