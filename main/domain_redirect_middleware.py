from django.http import HttpResponsePermanentRedirect

class RedirectCoTzMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()

        if host in ("exxabay.co.tz", "www.exxabay.co.tz"):
            return HttpResponsePermanentRedirect(
                f"https://exxabay.com{request.get_full_path()}"
            )

        return self.get_response(request)