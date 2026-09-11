from app.core.security import hash_password, verify_password


def test_password_hash_roundtrip():
    password = "demo1234"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
