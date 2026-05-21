from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

def send_custom_email(user_email, username, subject, body):

    html_content = render_to_string("account/email/send_email.html", {
        "username": username,
        "body": body,
    })

    plain_text = strip_tags(html_content)

    email = EmailMultiAlternatives(
        subject=subject,
        body=plain_text,
        from_email="michaelmsita95@gmail.com",
        to=[user_email]
    )

    email.attach_alternative(html_content, "text/html")
    email.send()