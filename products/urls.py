from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('', views.product_view, name='products'),
    path('create_product/', views.create_product, name='add_product'),
    path('create_product_api/', views.create_product_api, name='add_product_api'),
    path("product/<int:pk>/edit/", views.product_update, name="product_update"),
    path("product/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path('seller/dashboard/', views.seller_dashboard, name='sellerDashboard'),

    path("product/<int:pk>/toggle_featured/", views.toggle_featured_api, name="toggle_featured_api"),
    # path("product/<int:pk>/delete_api/", views.delete_product_api, name="delete_product_api"),
    path("product/<int:pk>/update_api/", views.update_product_api, name="update_product_api"),
    path('search_products_api/', views.search_products_api, name='search_products_api'),

    path('product_filter/', views.product_search_view, name='filter_product'),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
]