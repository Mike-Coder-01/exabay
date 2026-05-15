from django.shortcuts import render
from products.models import Product, Category
from orders.models import Order

# Create your views here.
def home(request):
    products = Product.objects.filter(is_available=True)\
        .select_related('seller__user', 'category')\
        .prefetch_related('images')
    
    categories = Category.objects.all()

    orders = Order.objects.all().count()

    return render(request, "main/index.html", {
        "products": products,
        'order_total': orders,
        'categories': categories,
    })
