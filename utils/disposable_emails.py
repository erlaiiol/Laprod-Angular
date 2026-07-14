"""
Blocage des adresses email jetables à l'inscription.

Liste embarquée des domaines jetables les plus courants (pas de dépendance
réseau). Elle n'est pas exhaustive — c'est un filtre anti-spam de comptes, pas
une garantie. Compléter au besoin ; garder les domaines en minuscules.
"""

_DISPOSABLE_DOMAINS: frozenset[str] = frozenset({
    'mailinator.com', 'yopmail.com', 'yopmail.fr', 'guerrillamail.com',
    'guerrillamail.info', 'guerrillamail.net', 'guerrillamail.org',
    'grr.la', 'sharklasers.com', 'trashmail.com', 'trashmail.net',
    'temp-mail.org', 'tempmail.com', 'tempmailo.com', 'tempr.email',
    'throwawaymail.com', 'throwaway.email', 'getnada.com', 'nada.email',
    'maildrop.cc', 'mailnesia.com', 'mohmal.com', 'fakeinbox.com',
    'dispostable.com', 'discard.email', 'mailcatch.com', 'spam4.me',
    'mytemp.email', '10minutemail.com', '10minutemail.net', '20minutemail.com',
    'emailondeck.com', 'moakt.com', 'tmail.io', 'tmpmail.org', 'tmpmail.net',
    'inboxkitten.com', 'mailpoof.com', 'burnermail.io', 'einrot.com',
    'fakemailgenerator.com', 'jetable.org', 'wegwerfmail.de', 'wegwerfemail.de',
    'spambog.com', 'mailexpire.com', 'anonbox.net', 'mailtemp.info',
    'cs.email', '1secmail.com', '1secmail.net', '1secmail.org', 'linshi-email.com',
})


def is_disposable_email(email: str | None) -> bool:
    """True si le domaine de l'email fait partie des fournisseurs jetables connus."""
    if not email or '@' not in email:
        return False
    domain = email.rsplit('@', 1)[1].strip().lower()
    return domain in _DISPOSABLE_DOMAINS
