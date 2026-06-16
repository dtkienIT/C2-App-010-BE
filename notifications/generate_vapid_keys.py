from __future__ import annotations

import base64


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def main() -> None:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:
        raise RuntimeError("cryptography is required. Install backend dependencies with: pip install -r requirements.txt") from exc

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_number = private_key.private_numbers().private_value.to_bytes(32, "big")
    public_numbers = private_key.public_key().public_numbers()
    public_key = b"\x04" + public_numbers.x.to_bytes(32, "big") + public_numbers.y.to_bytes(32, "big")

    print("Add these values to repository-root/.env:")
    print(f"WEB_PUSH_VAPID_PUBLIC_KEY={base64url(public_key)}")
    print(f"VITE_WEB_PUSH_PUBLIC_KEY={base64url(public_key)}")
    print(f"WEB_PUSH_VAPID_PRIVATE_KEY={base64url(private_number)}")
    print("WEB_PUSH_VAPID_SUBJECT=mailto:team@example.com")
    print("")
    print("Do not commit the private key. Keep WEB_PUSH_VAPID_PRIVATE_KEY out of VITE_* variables.")


if __name__ == "__main__":
    main()
