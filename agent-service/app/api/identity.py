"""Agent HTTP入口共享的最小身份解析。"""

from pydantic import SecretStr, ValidationError

from app.schemas.business import BusinessIdentity


def resolve_business_identity(
    *,
    user_id: str | None,
    user_role: str | None,
    authorization: str | None,
) -> BusinessIdentity | None:
    """把身份Header转换为Java Tool可安全透传的身份。"""

    if user_id is None or user_role is None:
        return None
    token: SecretStr | None = None
    if authorization is not None:
        scheme, separator, value = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not value.strip():
            return None
        token = SecretStr(value.strip())
    try:
        return BusinessIdentity(user_id=user_id, role=user_role, token=token)
    except ValidationError:
        return None
