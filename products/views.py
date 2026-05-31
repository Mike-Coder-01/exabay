from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from products.forms import ProductCreationForm, ProductUpdateForm
from users.models import SellerProfile
from .models import Product, ProductImage, Category
from django.contrib import messages
from django.db import models as db_models
from django.db.models import Case, When, Value, IntegerField, Q, F
from .filters import ProductFilter
from django.urls import reverse
from control_panel.models import AdminNotification




DEFAULT_DASHBOARD_PRODUCTS = [
    {
        "id": None,
        "name": "Artisan Desk Lamp",
        "price": Decimal("129.00"),
        "stock": 48,
        "is_available": True,
        "is_featured": True,
        "image_url": "https://via.placeholder.com/300x300/f0f4ff/2f6df6?text=Lamp",
    },
    {
        "id": None,
        "name": "Canvas Market Tote",
        "price": Decimal("44.50"),
        "stock": 93,
        "is_available": True,
        "is_featured": True,
        "image_url": "https://via.placeholder.com/300x300/f0f4ff/2f6df6?text=Lamp",
    },
    {
        "id": None,
        "name": "Stoneware Tea Set",
        "price": Decimal("86.00"),
        "stock": 17,
        "is_available": True,
        "is_featured": False,
        "image_url": "https://via.placeholder.com/300x300/f0f4ff/2f6df6?text=Lamp",
    },
    {
        "id": None,
        "name": "Minimal Wall Clock",
        "price": Decimal("64.00"),
        "stock": 0,
        "is_available": False,
        "is_featured": False,
        "image_url": "https://via.placeholder.com/300x300/f0f4ff/2f6df6?text=Lamp",
    },
    {
        "id": None,
        "name": "Nordic Storage Bin",
        "price": Decimal("32.00"),
        "stock": 61,
        "is_available": True,
        "is_featured": False,
        "image_url": "https://via.placeholder.com/300x300/f0f4ff/2f6df6?text=Lamp",
    },
]



def _get_product_image_url(product):
    image_field = getattr(product, "image", None)
    if not image_field:
        return ""

    try:
        return image_field.url
    except ValueError:
        return ""


def _get_product_stock(product):
    for field_name in ("stock", "stock_quantity", "quantity", "inventory"):
        value = getattr(product, field_name, None)
        if value is not None:
            return value
    return 0


def _serialize_product(product):
    # Get the first image URL if available
    image_url = ""
    if hasattr(product, 'images') and product.images.exists():
        image_url = product.images.first().image.url
    elif hasattr(product, 'image') and product.image:
        try:
            image_url = product.image.url
        except ValueError:
            pass
    
    return {
        "id": product.pk,
        "name": getattr(product, "name", "Unnamed product"),
        "price": getattr(product, "price", Decimal("0.00")),
        "stock": _get_product_stock(product),
        "is_available": getattr(product, "is_available", False),
        "is_featured": getattr(product, "is_featured", False),
        "image_url": image_url,
    }


def _build_featured_slots(featured_products, limit=3):
    slots = list(featured_products[:limit])

    while len(slots) < limit:
        slots.append(None)

    return slots


def product_view(request):
    return render(request, "products/products.html")


# ----------------------------
# CREATE PRODUCT
# ----------------------------
@login_required
def create_product(request):
    seller = get_object_or_404(SellerProfile, user=request.user)
    products = Product.objects.filter(seller=seller, is_featured=True).count()

    if not seller.is_verified:
        return HttpResponseForbidden("Seller not verified")

    if request.method == "POST":
        form = ProductCreationForm(request.POST)
        is_product_featured = form.cleaned_data['is_featured']
        if is_product_featured  and products >= 3:
            messages.info(request, "You already have 3 products as featured, unfeature one to feature this.")
        if form.is_valid():
            product = form.save(commit=False)
            product.seller = seller
            product.save()
            return redirect("seller_product_list")
    else:
        form = ProductCreationForm()

    # Get all categories for the template
    categories = Category.objects.all()

    return render(
        request,
        "products/create_product.html",
        {
            "form": form,
            "categories": categories,  
        },
    )

@login_required
def create_product_api(request):
    seller = get_object_or_404(SellerProfile, user=request.user)

    if not seller.is_verified:
        return JsonResponse({"error": "Seller not verified"}, status=403)

    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)

    try:
        created = []
        index = 0

        while True:
            prefix = f"products[{index}]"

            name = request.POST.get(f"{prefix}[name]")
            if not name:
                break

            # Handle category - now using ID
            category_id = request.POST.get(f"{prefix}[category]")
            category = None
            if category_id:
                try:
                    category = Category.objects.get(id=category_id)
                except Category.DoesNotExist:
                    return JsonResponse({"error": f"Category with id {category_id} not found"}, status=400)

            # Get boolean value properly
            is_featured = request.POST.get(f"{prefix}[is_featured]")
            if isinstance(is_featured, str):
                is_featured = is_featured.lower() in ['true', '1', 'on']
            else:
                is_featured = bool(is_featured)

            product = Product.objects.create(
                seller=seller,
                category=category,
                name=name,
                description=request.POST.get(f"{prefix}[description]", ""),
                price=request.POST.get(f"{prefix}[price]", 0),
                stock=request.POST.get(f"{prefix}[stock]", 0),
                is_featured=is_featured,
            )

            # Get images from FILES
            images = request.FILES.getlist(f"{prefix}[images][]")
            
            for img in images:
                ProductImage.objects.create(
                    product=product,
                    image=img
                )

            created.append(product.id)
            index += 1

        if not created:
            return JsonResponse({"error": "No valid products to create"}, status=400)

        return JsonResponse({
            "message": "Products created successfully",
            "products": created
        })

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({"error": str(e)}, status=500)

# ----------------------------
# UPDATE PRODUCT
# ----------------------------
@login_required
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    seller = get_object_or_404(SellerProfile, user=request.user)

    if product.seller != seller:
        raise PermissionDenied("You are not allowed to edit this product.")

    if request.method == "POST":
        form = ProductUpdateForm(request.POST, instance=product)

        if form.is_valid():
            form.save()
            messages.success(request, f'Product "{product.name}" updated successfully!')
        else:
            messages.error(request, 'Please correct the errors below. Or turn off  is featured because it exceed limit')
    else:
        form = ProductUpdateForm(instance=product)

    return render(
        request,
        "products/product_update.html",
        {
            "form": form,
            "product": product,
        },
    )


# ----------------------------
# DELETE (ARCHIVE) PRODUCT
# ----------------------------
@login_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    seller = get_object_or_404(SellerProfile, user=request.user)

    if product.seller != seller:
        raise PermissionDenied

    if request.method == "POST":
        product_name = product.name
        product.is_available = False
        product.save()
        messages.warning(request, f'Product "{product_name}" has been archived.')
        return redirect("products:sellerDashboard")

    return render(
        request,
        "products/product_confirm_delete.html",
        {
            "product": product,
        },
    )


# ----------------------------
# SELLER PRODUCT LIST
# ----------------------------
@login_required
def seller_product_list(request):
    seller = get_object_or_404(SellerProfile, user=request.user)
    products = Product.objects.filter(seller=seller)

    return render(
        request,
        "seller/product_list.html",
        {
            "products": products,
        },
    )


# ----------------------------
# SELLER DASHBOARD
# ----------------------------
@login_required
def seller_dashboard(request):
    seller = get_object_or_404(SellerProfile, user=request.user)

    product_qs = Product.objects.filter(seller=seller).order_by("-id")

    product_field_names = {field.name for field in Product._meta.get_fields()}
    has_featured_field = "is_featured" in product_field_names

    total_products = product_qs.count()
    active_products = product_qs.filter(is_available=True).count()
    inactive_products = product_qs.filter(is_available=False).count()

    featured_limit = 3

    if has_featured_field:
        featured_count = product_qs.filter(is_featured=True).count()
        featured_products = [
            _serialize_product(product)
            for product in product_qs.filter(is_featured=True)[:featured_limit]
        ]
        featured_usage = min(featured_count, featured_limit)
    else:
        featured_products = []
        featured_usage = 0

    paginator = Paginator(product_qs, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    products = [
        _serialize_product(product)
        for product in page_obj.object_list
    ]

    context = {
        "seller": seller,
        "seller_name": request.user.get_full_name() or request.user.username,
        "products": products,
        "page_obj": page_obj,
        "use_demo_data": False,

        "total_products": total_products,
        "active_products": active_products,
        "inactive_products": inactive_products,

        "featured_products": featured_products,
        "featured_slots": _build_featured_slots(featured_products, featured_limit),
        "featured_limit": featured_limit,
        "featured_usage": featured_usage,
        "has_featured_field": has_featured_field,
    }

    return render(request, "products/dashboard.html", context)


def notification_view (request):
    user = request.user
    unread_notifications = AdminNotification.objects.filter(user=user, is_read=False)
    return render (request, 'products/dashboard.html', {'unread_notification':unread_notifications})

# ----------------------------
# TOGGLE FEATURED API
# ----------------------------
@login_required
def toggle_featured_api(request, pk):
    """Toggle the is_featured status of a product via AJAX"""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)
    
    product = get_object_or_404(Product, pk=pk)
    seller = get_object_or_404(SellerProfile, user=request.user)
    
    # Check ownership
    if product.seller != seller:
        return JsonResponse({"error": "Permission denied"}, status=403)
    
    # Check featured limit when trying to feature a product
    if not product.is_featured:
        featured_count = Product.objects.filter(seller=seller, is_featured=True).count()
        featured_limit = 3
        
        if featured_count >= featured_limit:
            return JsonResponse({
                "error": "Featured limit reached. Maximum 3 products can be featured.",
                "featured_count": featured_count,
                "featured_limit": featured_limit
            }, status=400)
    
    # Toggle the featured status
    product.is_featured = not product.is_featured
    product.save()
    
    return JsonResponse({
        "message": "Featured status updated",
        "product_id": product.pk,
        "is_featured": product.is_featured
    })



# ----------------------------
# UPDATE PRODUCT API (for inline editing)
# ----------------------------
@login_required
def update_product_api(request, pk):
    """Update product fields via AJAX"""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)
    
    product = get_object_or_404(Product, pk=pk)
    seller = get_object_or_404(SellerProfile, user=request.user)
    
    # Check ownership
    if product.seller != seller:
        return JsonResponse({"error": "Permission denied"}, status=403)
    
    # Update fields if provided
    if "name" in request.POST:
        product.name = request.POST["name"]
    
    if "description" in request.POST:
        product.description = request.POST["description"]
    
    if "price" in request.POST:
        try:
            product.price = Decimal(request.POST["price"])
        except (ValueError, InvalidOperation):
            return JsonResponse({"error": "Invalid price format"}, status=400)
    
    if "stock" in request.POST:
        try:
            product.stock = int(request.POST["stock"])
        except ValueError:
            return JsonResponse({"error": "Invalid stock value"}, status=400)
    
    if "category" in request.POST:
        try:
            product.category = Category.objects.get(id=request.POST["category"])
        except Category.DoesNotExist:
            return JsonResponse({"error": "Category not found"}, status=400)
    
    if "is_available" in request.POST:
        product.is_available = request.POST["is_available"].lower() in ["true", "1", "on"]
    
    product.save()
    
    return JsonResponse({
        "message": "Product updated successfully",
        "product": _serialize_product(product)
    })


# ----------------------------
# TOGGLE FEATURED API
# ----------------------------
@login_required
def toggle_featured_api(request, pk):
    """Toggle the is_featured status of a product via AJAX"""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=400)
    
    product = get_object_or_404(Product, pk=pk)
    seller = get_object_or_404(SellerProfile, user=request.user)
    
    # Check ownership
    if product.seller != seller:
        return JsonResponse({"error": "Permission denied"}, status=403)
    
    # Check featured limit when trying to feature a product
    if not product.is_featured:
        featured_count = Product.objects.filter(
            seller=seller, 
            is_featured=True
        ).count()
        featured_limit = 3
        
        if featured_count >= featured_limit:
            return JsonResponse({
                "error": "Featured limit reached. Maximum 3 products can be featured.",
                "featured_count": featured_count,
                "featured_limit": featured_limit
            }, status=400)
    
    # Toggle the featured status
    product.is_featured = not product.is_featured
    product.save()
    
    return JsonResponse({
        "message": "Featured status updated successfully",
        "product_id": product.pk,
        "is_featured": product.is_featured
    })


@login_required
def search_products_api(request):
    """Search products via AJAX"""
    seller = get_object_or_404(SellerProfile, user=request.user)
    query = request.GET.get('query', '').strip()
    
    products_qs = Product.objects.filter(seller=seller)
    
    if query:
        # Order by relevance: exact match first, then starts with, then contains
        products_qs = products_qs.filter(
            db_models.Q(name__icontains=query) |
            db_models.Q(description__icontains=query) |
            db_models.Q(category__name__icontains=query)
        ).annotate(
            relevance=Case(
                When(name__iexact=query, then=Value(3)),
                When(name__istartswith=query, then=Value(2)),
                When(name__icontains=query, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).order_by('-relevance', '-id')  # Most relevant first, then newest
    else:
        products_qs = products_qs.order_by('-id')
    
    page_number = request.GET.get('page', 1)
    paginator = Paginator(products_qs, 10)
    page_obj = paginator.get_page(page_number)
    
    products_data = [_serialize_product(p) for p in page_obj.object_list]
    
    return JsonResponse({
        'products': products_data,
        'total_count': paginator.count,
        'current_page': page_obj.number,
        'total_pages': paginator.num_pages,
    })


def product_search_view(request):
    if request.method != 'GET':
        return redirect(reverse('main:home'))

    query = request.GET.get('search_filter')
    queryset = Product.objects.none()  # safe default

    if query:
        queryset = Product.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        ).annotate(
            search_rank=Case(
                When(name__iexact=query, then=Value(1)),
                When(name__istartswith=query, then=Value(2)),
                When(name__icontains=query, then=Value(3)),
                When(description__icontains=query, then=Value(4)),
                default=Value(0),
                output_field=IntegerField()
            )
        ).order_by('search_rank', '-id')

    context = {
        'products': queryset,
        'scroll_to_products': bool(query),
    }

    return render(request, 'main/index.html', context)


def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects
        .select_related("seller__user", "category")
        .prefetch_related("images", "specs"),
        pk=pk,
        is_available=True
    )

    return render(request, "main/product_detail.html", {
        "product": product
    })
