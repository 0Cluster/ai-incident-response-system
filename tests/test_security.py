import pytest
from fastapi import HTTPException

from app.webhooks.security import verify_webhook


def test_missing_secret_is_401():
    with pytest.raises(HTTPException) as exc:
        verify_webhook(None)
    assert exc.value.status_code == 401


def test_wrong_secret_is_401():
    with pytest.raises(HTTPException) as exc:
        verify_webhook("wrong")
    assert exc.value.status_code == 401
