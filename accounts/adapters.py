from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def generate_username(self, request, sociallogin):
        """Use the email prefix as the username instead of the provider's display name."""
        email = sociallogin.account.extra_data.get('mail') or \
                sociallogin.account.extra_data.get('userPrincipalName') or \
                (sociallogin.email_addresses[0].email if sociallogin.email_addresses else None)
        if email:
            return self.clean_username(email.split('@')[0])
        return super().generate_username(request, sociallogin)
