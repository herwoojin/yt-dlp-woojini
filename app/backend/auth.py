"""Firebase ID token verification.

Verifies the Authorization: Bearer <id_token> header against the Firebase
project configured via FIREBASE_SERVICE_ACCOUNT_PATH. If ALLOW_INSECURE_AUTH
is set, requests pass through with a synthetic uid - useful for local dev
before Firebase credentials are provisioned.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, status

from . import config

_firebase_ready = False
_firebase_error: str | None = None


def _ensure_firebase() -> None:
    global _firebase_ready, _firebase_error
    if _firebase_ready or _firebase_error:
        return
    # ID 토큰 검증에는 서비스 계정 비공개키가 필요 없다(구글 공개 인증서로 검증).
    # 서비스 계정 파일이 있으면 그걸 쓰고, 없으면 projectId만으로 초기화한다.
    if not config.FIREBASE_SERVICE_ACCOUNT_PATH and not config.FIREBASE_PROJECT_ID:
        _firebase_error = "FIREBASE_PROJECT_ID(또는 FIREBASE_SERVICE_ACCOUNT_PATH) 미설정"
        return
    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            if config.FIREBASE_SERVICE_ACCOUNT_PATH:
                cred = credentials.Certificate(config.FIREBASE_SERVICE_ACCOUNT_PATH)
                firebase_admin.initialize_app(cred, {"projectId": config.FIREBASE_PROJECT_ID})
            else:
                firebase_admin.initialize_app(options={"projectId": config.FIREBASE_PROJECT_ID})
        _firebase_ready = True
    except Exception as exc:
        _firebase_error = f"firebase init failed: {exc}"


def verify_id_token(token: str) -> dict[str, Any]:
    """서비스 계정 없이 Firebase ID 토큰을 검증한다(구글 공개 인증서 사용).
    google-auth의 verify_firebase_token으로 서명·발급자·audience(projectId)를 확인."""
    if not config.FIREBASE_PROJECT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="FIREBASE_PROJECT_ID 미설정",
        )
    try:
        from google.oauth2 import id_token as g_id_token
        from google.auth.transport import requests as g_requests

        claims = g_id_token.verify_firebase_token(
            token, g_requests.Request(), audience=config.FIREBASE_PROJECT_ID
        )
        if not claims:
            raise ValueError("토큰 검증 실패(빈 클레임)")
        uid = claims.get("user_id") or claims.get("sub")
        if not uid:
            raise ValueError("토큰에 uid 없음")
        return {"uid": uid, "email": claims.get("email"), "claims": claims}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid id token: {exc}"
        ) from exc


async def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if config.ALLOW_INSECURE_AUTH:
        return {"uid": "local-dev", "email": "local@dev"}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_id_token(token)


UserDep = Depends(current_user)
