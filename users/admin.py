from django.contrib import admin
from users.models import User, SellerProfile, Subscriber

# Register your models here.
admin.site.register(User)
admin.site.register(SellerProfile)
admin.site.register(Subscriber)