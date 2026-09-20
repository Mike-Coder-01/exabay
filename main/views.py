from django.shortcuts import render, redirect
from products.models import Product, Category
from orders.models import Order
from users.models import SellerProfile
from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from .forms import ReportSellerForm
from django.views.generic import TemplateView
from django.http import HttpResponse

# Create your views here.
def robots_txt(request):
    return HttpResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Sitemap: https://exxabay.co.tz/sitemap.xml",
        content_type="text/plain",
    )


def home(request):
    products = Product.objects.filter(is_available=True)\
        .select_related('seller__user', 'category')\
        .prefetch_related('images').order_by('-created_at')
    
    categories = Category.objects.all()

    orders = Order.objects.filter(status="paid").count()
    
    return render(request, "main/index.html", {
        "products": products,
        'order_total': orders,
        'categories': categories,
    })


def exxabay_go_payment_link_generate(request):
    return render(request, 'exxabayGo/exxabay_go_payment.html')


POLICY_PAGES = {
    "buyer_protection": {
        "i18n_prefix": "buyerProtection",
        "title": "Buyer Protection",
        "eyebrow": "Shop with confidence",
        "summary": "Exxabay helps buyers shop safely by combining verified seller signals, secure payment flow, and clear order follow-up.",
        "badge": "Buyer safety",
        "sections": [
            {
                "title": "Verified seller visibility",
                "body": "Product pages and seller cards show verification status so buyers can quickly understand whether a seller has completed Exxabay trust checks.",
            },
            {
                "title": "Secure payment flow",
                "body": "Buyers should complete payment only through Exxabay-supported checkout channels. Sellers must not request private PINs, passwords, or off-platform payment confirmation.",
            },
            {
                "title": "Order follow-up",
                "body": "Paid orders can be monitored by Exxabay admins to help sellers and buyers coordinate fulfillment and delivery confirmation.",
            },
            {
                "title": "Report and review process",
                "body": "If a product is misleading, not delivered, or connected to suspicious seller behavior, buyers can submit a seller report for review.",
            },
        ],
        "actions": [
            {"label": "Report a seller", "url": "main:report_seller"},
            {"label": "View products", "url": "main:home"},
        ],
    },


    "refund_policy": {

        "i18n_prefix": "refundPolicy",

        "title": "Refund & Return Policy",

        "eyebrow": "Shop with confidence",

        "summary": "Exxabay protects buyers by keeping the payment process secure and providing a clear process for reporting problems, returning eligible products, and requesting refunds.",

        "badge": "Buyer protection",

        "sections": [

            {
                "title": "Payment protection",
                "body": "When you place an order through Exxabay, your payment is held through our secure payment and escrow process while the order is being fulfilled. Seller payout is processed according to the order and confirmation process.",
            },

            {
                "title": "Check your order",
                "body": "After receiving your order, carefully check that the product is the correct item, matches the listing, and is not damaged or missing important accessories. If there is a problem, report it through Exxabay before confirming your order.",
            },

            {
                "title": "When can I request a refund?",
                "body": "You may be eligible for a refund or other remedy if you receive the wrong product, a product that is materially different from the listing, a damaged or defective product, an incomplete order, or if the seller fails to fulfil your order. Refunds are also subject to any rights provided by applicable Tanzanian law.",
            },

            {
                "title": "Report a problem",
                "body": "If there is a problem with your order, open the relevant order in your Exxabay account and select the option to report a problem. You may be asked to provide photos, videos, delivery information, or other evidence to help us review the case.",
            },

            {
                "title": "Dispute review",
                "body": "When a buyer reports a problem, Exxabay may temporarily hold the transaction while the issue is reviewed. We may contact the buyer and seller and review the product listing, order information, delivery details, and evidence provided by both parties before determining the appropriate resolution.",
            },

            {
                "title": "Possible resolutions",
                "body": "Depending on the circumstances, Exxabay may determine that the appropriate resolution is a replacement, repair, partial refund, full refund, return of the product, or release of the payment to the seller.",
            },

            {
                "title": "Product returns",
                "body": "If a return is approved, buyers must follow Exxabay's return instructions. Products should generally be returned in substantially the same condition in which they were received, together with the supplied accessories and packaging where reasonably available.",
            },

            {
                "title": "Return delivery costs",
                "body": "Where the seller sent the wrong product, materially misrepresented the product, or the product is defective or damaged due to circumstances attributable to the seller, the seller may be responsible for applicable return costs. Where a return is made because of a buyer's change of mind, the buyer may be responsible for return costs where permitted by applicable law.",
            },

            {
                "title": "Change of mind",
                "body": "Changing your mind does not automatically guarantee a refund or free return. Any cancellation or return rights will be handled according to applicable Tanzanian law, the product category, and the applicable seller return terms.",
            },

            {
                "title": "Refund processing",
                "body": "Once a refund is approved, Exxabay will initiate the refund through the applicable payment channel. The refund may be full or partial depending on the outcome of the case. The time required for the refunded amount to reach the buyer may depend on the payment provider or financial institution.",
            },

            {
                "title": "After confirming your order",
                "body": "Once you confirm that your order has been received satisfactorily, the normal order dispute process may no longer apply to ordinary delivery-related complaints. However, genuine defects or other issues may still be handled under an applicable warranty, seller return policy, consumer protection right, or other applicable remedy.",
            },

            {
                "title": "Fraudulent or abusive claims",
                "body": "Exxabay may investigate and take appropriate action where there is reasonable evidence of fraudulent or abusive refund activity, including false non-delivery claims, returning a different product, deliberately damaging a product, or submitting misleading evidence.",
            },

            {
                "title": "Seller responsibility",
                "body": "Sellers are responsible for ensuring that their product descriptions, images, specifications, prices, and availability are accurate and that products supplied to buyers match their listings. Sellers must also comply with applicable return, warranty, and consumer protection requirements.",
            },

            {
                "title": "Exxabay's role",
                "body": "Exxabay operates the marketplace and provides the systems used to facilitate transactions between buyers and verified sellers. When a dispute occurs, Exxabay may review the available information and administer the applicable buyer-protection and escrow process.",
            },

            {
                "title": "Applicable law",
                "body": "This policy is subject to applicable laws and regulations of Tanzania. Nothing in this policy is intended to remove or limit a consumer right or remedy that cannot legally be excluded.",
            },

        ],

        "actions": [

            {
                "label": "View products",
                "url": "main:home"
            },

        ],

    },

    "seller_verification_policy": {
        "i18n_prefix": "sellerVerificationPolicy",
        "title": "Seller Verification Policy",
        "eyebrow": "Marketplace trust",
        "summary": "Exxabay verifies seller identity and business information before giving sellers full trusted marketplace access.",
        "badge": "Verification",
        "sections": [
            {
                "title": "Required business information",
                "body": "Sellers may be asked to provide a business name, TIN number, business license document, license expiry date, and other supporting tax or registration details.",
            },
            {
                "title": "Admin review",
                "body": "Exxabay admins review submitted seller information and may verify, reject, or request corrections before trust status is shown to buyers.",
            },
            {
                "title": "Document privacy",
                "body": "Verification documents are used for marketplace trust review and are not displayed as sensitive previews on public product pages.",
            },
            {
                "title": "Ongoing trust checks",
                "body": "Verified status can be removed if a seller provides false information, violates marketplace rules, or fails to maintain valid verification records.",
            },
        ],
        "actions": [
            {"label": "Complete seller profile", "url": "users:complete_profile"},
            {"label": "Seller guidelines", "url": "main:seller_guidelines"},
        ],
    },
    "privacy_policy": {
        "i18n_prefix": "privacyPolicy",
        "title": "Privacy Policy",
        "eyebrow": "Data and trust",
        "summary": "Exxabay collects only the information needed to operate accounts, orders, seller verification, payments, payouts, and marketplace support.",
        "badge": "Privacy",
        "sections": [
            {
                "title": "Information we collect",
                "body": "We may collect account details, contact information, order records, payment references, seller business documents, and support messages.",
            },
            {
                "title": "How information is used",
                "body": "Information is used to manage accounts, process orders, verify sellers, support payments and payouts, prevent fraud, and communicate marketplace updates.",
            },
            {
                "title": "Sharing and security",
                "body": "Exxabay may share required transaction details with payment providers and operational partners. Sensitive seller documents should be protected and accessed only by authorized review users.",
            },
            {
                "title": "Your choices",
                "body": "Users can update account details, notification preferences, and seller settings from their account pages where available.",
            },
        ],
        "actions": [
            {"label": "Account settings", "url": "users:seller_settings"},
            {"label": "Contact support", "url": "main:report_seller"},
        ],
    },
    "terms_of_service": {
        "i18n_prefix": "termsOfService",
        "title": "Terms of Service",
        "eyebrow": "Marketplace rules",
        "summary": "These terms explain the responsibilities of buyers, sellers, and Exxabay when using the marketplace.",
        "badge": "Terms",
        "sections": [
            {
                "title": "Account responsibility",
                "body": "Users are responsible for keeping account credentials secure and providing accurate registration, contact, and seller information.",
            },
            {
                "title": "Marketplace role",
                "body": "Exxabay provides a marketplace platform for product discovery, checkout, seller verification, order follow-up, and payout support.",
            },
            {
                "title": "Seller obligations",
                "body": "Sellers must list accurate products, maintain stock information, fulfill paid orders, communicate professionally, and comply with verification requirements.",
            },
            {
                "title": "Buyer obligations",
                "body": "Buyers must provide accurate order and contact information, complete payments through supported channels, and avoid abusive or fraudulent activity.",
            },
            {
                "title": "Policy enforcement",
                "body": "Exxabay may restrict accounts, remove listings, reject verification, pause payouts, or cancel orders when marketplace safety requires action.",
            },
        ],
        "actions": [
            {"label": "Buyer protection", "url": "main:buyer_protection"},
            {"label": "Seller guidelines", "url": "main:seller_guidelines"},
        ],
    },
    "seller_guidelines": {
        "i18n_prefix": "sellerGuidelines",
        "title": "Seller Guidelines",
        "eyebrow": "Sell responsibly",
        "summary": "These guidelines help sellers build buyer trust, reduce disputes, and maintain healthy marketplace performance.",
        "badge": "Seller standards",
        "sections": [
            {
                "title": "Accurate listings",
                "body": "Product names, images, descriptions, specifications, prices, and stock counts should be truthful and kept up to date.",
            },
            {
                "title": "Reliable fulfillment",
                "body": "Sellers should prepare paid orders promptly, communicate clearly with buyers, and update order handling when fulfillment changes.",
            },
            {
                "title": "Professional communication",
                "body": "Sellers must communicate respectfully and should not request sensitive payment credentials or push buyers outside protected checkout channels.",
            },
            {
                "title": "Trust and verification",
                "body": "Business documents and payout details should remain accurate. Expired or incorrect records may delay verification or payouts.",
            },
            {
                "title": "Payout readiness",
                "body": "Payouts are based on eligible seller earnings after marketplace commission and depend on valid payout details and completed fulfillment.",
            },
        ],
        "actions": [
            {"label": "Seller settings", "url": "users:seller_settings"},
            {"label": "Verification policy", "url": "main:seller_verification_policy"},
        ],
    },
}


def with_translation_keys(page):
    page = {
        **page,
        "title_key": f"{page['i18n_prefix']}Title",
        "eyebrow_key": f"{page['i18n_prefix']}Eyebrow",
        "summary_key": f"{page['i18n_prefix']}Summary",
        "badge_key": f"{page['i18n_prefix']}Badge",
    }
    page["sections"] = [
        {
            **section,
            "title_key": f"{page['i18n_prefix']}Section{index}Title",
            "body_key": f"{page['i18n_prefix']}Section{index}Body",
        }
        for index, section in enumerate(page["sections"], start=1)
    ]
    page["actions"] = [
        {
            **action,
            "label_key": f"{page['i18n_prefix']}Action{index}",
        }
        for index, action in enumerate(page["actions"], start=1)
    ]
    return page


def render_policy_page(request, page_key):
    return render(request, "main/policy_page.html", {
        "page": with_translation_keys(POLICY_PAGES[page_key]),
    })


def buyer_protection(request):
    return render_policy_page(request, "buyer_protection")


def seller_verification_policy(request):
    return render_policy_page(request, "seller_verification_policy")

def refund_policy (request):
    return render_policy_page(request, "refund_policy")


def privacy_policy(request):
    return render_policy_page(request, "privacy_policy")


def terms_of_service(request):
    return render_policy_page(request, "terms_of_service")


def seller_guidelines(request):
    return render_policy_page(request, "seller_guidelines")


def exxabay_go_land_page(request):
    return render(request, 'exxabayGo/exxabay_go_landing_page.html')


def report_seller(request):
    initial = {}
    if request.user.is_authenticated and request.user.email:
        initial["reporter_email"] = request.user.email

    form = ReportSellerForm(request.POST or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        subject = f"Seller report: {data['seller_name']}"
        message = (
            f"Seller: {data['seller_name']}\n"
            f"Order ID: {data.get('order_id') or 'N/A'}\n"
            f"Reporter email: {data['reporter_email']}\n"
            f"Reason: {data['reason']}\n"
            f"Evidence URL: {data.get('evidence_url') or 'N/A'}\n\n"
            f"Details:\n{data['details']}"
        )
        send_mail(
            subject,
            message,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [getattr(settings, "EXABAY_SUPPORT_EMAIL", getattr(settings, "DEFAULT_FROM_EMAIL", ""))],
            fail_silently=True,
        )
        messages.success(request, "Your report has been submitted. Exxabay support will review it.")
        return redirect("main:report_seller")

    return render(request, "main/report_seller.html", {"form": form})