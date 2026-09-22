"""Testes de hash de PIN/senha, validação de documento e sessão de admin (RNF01)."""

import pytest

from app.security import (
    AdminSessionStore,
    InvalidDocument,
    InvalidPassword,
    InvalidPin,
    hash_password,
    hash_pin,
    normalize_document,
    validate_document,
    verify_password,
    verify_pin,
)


def test_pin_hash_roundtrip():
    pin_hash = hash_pin("1234")
    assert pin_hash != "1234"
    assert verify_pin("1234", pin_hash) is True
    assert verify_pin("4321", pin_hash) is False


@pytest.mark.parametrize("bad_pin", ["123", "12345", "abcd", "12a4", ""])
def test_pin_must_be_four_digits(bad_pin):
    with pytest.raises(InvalidPin):
        hash_pin(bad_pin)


def test_verify_pin_never_raises_on_garbage_hash():
    assert verify_pin("1234", "not-a-real-bcrypt-hash") is False


def test_password_hash_roundtrip():
    password_hash = hash_password("supersecreta123")
    assert verify_password("supersecreta123", password_hash) is True
    assert verify_password("outrasenha", password_hash) is False


def test_password_must_have_minimum_length():
    with pytest.raises(InvalidPassword):
        hash_password("curta")


def test_normalize_document_strips_non_digits():
    assert normalize_document("123.456.789-09") == "12345678909"
    assert normalize_document("(11) 98765-4321") == "11987654321"


def test_validate_document_accepts_10_to_11_digits():
    assert validate_document("123.456.789-09") == "12345678909"
    assert validate_document("(11) 3456-7890") == "1134567890"


@pytest.mark.parametrize("bad", ["123", "123456789", "123456789012"])
def test_validate_document_rejects_wrong_length(bad):
    with pytest.raises(InvalidDocument):
        validate_document(bad)


def test_admin_session_store_create_and_resolve():
    store = AdminSessionStore()
    token = store.create(admin_id=7)
    assert store.resolve(token) == 7


def test_admin_session_store_rejects_unknown_token():
    store = AdminSessionStore()
    assert store.resolve("token-que-nao-existe") is None
    assert store.resolve(None) is None


def test_admin_session_store_expires():
    store = AdminSessionStore(ttl_seconds=-1)  # já nasce expirado
    token = store.create(admin_id=1)
    assert store.resolve(token) is None


def test_admin_session_store_revoke():
    store = AdminSessionStore()
    token = store.create(admin_id=1)
    store.revoke(token)
    assert store.resolve(token) is None
