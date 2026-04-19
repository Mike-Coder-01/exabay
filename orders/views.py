from django.shortcuts import render

# Create your views here.
def orderView (request):
    return render (request, 'orders/orders.html')