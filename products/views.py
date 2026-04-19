from django.shortcuts import render, redirect
from django.core.exceptions import PermissionDenied
from products.forms import ProductCreationForm
from django.http import HttpResponse
from . models import Product
from django.contrib.auth.decorators import login_required

# Create your views here.
def product_view(request):
    return render (request, 'products/products.html')


@login_required
def create_product(request):
    if request.method == "POST":
        form = ProductCreationForm(request.POST)

        if form.is_valid():
           form.save()
        return redirect("success_page")

    else:
        form = ProductCreationForm()

    return render(request, "create_product.html", {"form": form})