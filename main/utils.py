from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def send_custom_email(user_email, username, subject, body):
    body_html = body.replace("\n", "<br>")

    html_content = render_to_string("account/email/send_email.html", {
        "username": username,
        "body": body_html,
    })

    email = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(html_content),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user_email],
        # ✅ no headers= here
    )

    email.attach_alternative(html_content, "text/html")
    email.send()