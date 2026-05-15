def seller_profile_complete(user):
    if not user.is_seller:
        return True

    profile = getattr(user, "sellerprofile", None)
    return bool(profile and profile.is_profile_complete())


def profile_requires_onboarding(user):
    if not user.is_authenticated:
        return False

    if user.is_seller:
        return not seller_profile_complete(user)

    return not bool(user.phone_number)
