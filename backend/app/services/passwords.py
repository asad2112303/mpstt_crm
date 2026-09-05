"""One-time password generation for admin-created logins."""
import secrets

# Unambiguous alphabet: no O/0, l/1/I — these get read aloud and mistyped.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
SYMBOLS = "!@#$%*?"


def generate_password(length: int = 16) -> str:
    """A password that satisfies Supabase's default strength rules."""
    body = "".join(secrets.choice(ALPHABET) for _ in range(length - 2))
    return body + secrets.choice(SYMBOLS) + secrets.choice("23456789")
