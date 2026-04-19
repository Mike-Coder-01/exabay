from django.shortcuts import render
from .forms import UserRegisterUser
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt

# Create your views here.
@csrf_exempt
def register_user(request):
    if request.method == 'POST':
        user_register_form = UserRegisterUser(request.POST)
        if user_register_form.is_valid():
            user_register_form.save()
        else:
            user_register_form = UserRegisterUser()

        context = {
            'register_form': user_register_form,
        }

    return HttpResponse('The account has been created')

    # return render (request, 'users/register.html', context)