from django.contrib import admin
from products.models import Product, ProductImage, ProductSpecification, Category

# Register your models here.
admin.site.register(Product)
admin.site.register(ProductImage)
admin.site.register(ProductSpecification)
admin.site.register(Category)