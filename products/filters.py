import django_filters
from .models import Product
from django.db.models import Q

class ProductFilter(django_filters.FilterSet):
    search_filter = django_filters.CharFilter(method='product_filter')

    class Meta:
        model = Product
        fields = ['name','description']

    def product_filter(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value) | Q(description__icontains=value)
        )