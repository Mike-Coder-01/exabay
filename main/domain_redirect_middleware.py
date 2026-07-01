from django.http import HttpResponsePermanentRedirect

class RedirectCoTzMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()

        if host in ("exxabay.com", "www.exxabay.com"):
            return HttpResponsePermanentRedirect(
                f"https://exxabay.co.tz{request.get_full_path()}"
            )

        return self.get_response(request)