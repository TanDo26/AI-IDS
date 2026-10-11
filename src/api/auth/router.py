"""
/auth endpoints: signup, login, refresh, logout, me, password.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.auth import security, service
from src.api.auth.deps import get_current_user, require_csrf
from src.api.auth.schemas import LoginRequest, PasswordChangeRequest, SignupRequest, TokenResponse, UserOut
from src.api.db.models import User
from src.api.db.session import get_db
from src.api.ratelimit import LOGIN_PER_ACCOUNT, LOGIN_PER_IP, SIGNUP_PER_IP, rate_limit
from src.api.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("User-Agent"), request.client.host if request.client else None


def _set_session(response: Response, issued: service.IssuedTokens) -> TokenResponse:
    settings = get_settings()
    access_s = settings.access_token_minutes * 60
    refresh_s = settings.refresh_token_days * 86400
    common = {"secure": settings.cookie_secure, "samesite": "lax"}
    response.set_cookie(security.ACCESS_COOKIE, issued.access_token, max_age=access_s,
                        httponly=True, path="/api", **common)
    response.set_cookie(security.REFRESH_COOKIE, issued.refresh_token, max_age=refresh_s,
                        httponly=True, path="/api/v1/auth", **common)
    response.set_cookie(security.CSRF_COOKIE, issued.csrf_token, max_age=refresh_s,
                        httponly=False, path="/", **common)
    return TokenResponse(access_token=issued.access_token, expires_in=access_s,
                         user=UserOut.model_validate(issued.user))


def _clear_session(response: Response) -> None:
    response.delete_cookie(security.ACCESS_COOKIE, path="/api")
    response.delete_cookie(security.REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(security.CSRF_COOKIE, path="/")


def _raise(e: service.AuthError):
    raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ua, ip = _client(request)
    rate_limit(SIGNUP_PER_IP, "signup", ip)
    try:
        user = service.signup(db, body.email, body.username, body.password)
    except service.AuthError as e:
        _raise(e)
    return _set_session(response, service.issue_tokens(db, user, user_agent=ua, ip=ip))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ua, ip = _client(request)
    rate_limit(LOGIN_PER_IP, "login-ip", ip)
    rate_limit(LOGIN_PER_ACCOUNT, "login-account", body.email)
    try:
        user = service.authenticate(db, body.email, body.password)
    except service.AuthError as e:
        _raise(e)
    return _set_session(response, service.issue_tokens(db, user, user_agent=ua, ip=ip))


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(require_csrf)])
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    ua, ip = _client(request)
    try:
        issued = service.rotate_refresh_token(db, request.cookies.get(security.REFRESH_COOKIE), ua, ip)
    except service.AuthError as e:
        # Returned, not raised: an exception would drop the cookie deletions,
        # and the browser should forget a session the server no longer honours
        failed = JSONResponse(status_code=e.status, content={"detail": e.message})
        _clear_session(failed)
        return failed
    return _set_session(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    service.logout(db, request.cookies.get(security.REFRESH_COOKIE))
    _clear_session(response)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password", response_model=TokenResponse)
def change_password(body: PasswordChangeRequest, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ua, ip = _client(request)
    try:
        issued = service.change_password(db, user, body.current_password, body.new_password, ua, ip)
    except service.AuthError as e:
        _raise(e)
    return _set_session(response, issued)
