import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import requests
from pydantic import SecretStr

from shared.enums import ErrorType

_BASE = "https://api.schwabapi.com/trader/v1/accounts"
_HASH = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_NUMBER = re.compile(r"[0-9]{1,32}\Z")
_READ_URL = re.compile(
    re.escape(_BASE)
    + r"/(?:accountNumbers|[A-Za-z0-9_-]{1,256}(?:/(?:transactions|orders))?)\Z"
)


class SchwabReadError(ValueError):
    def __init__(
        self, code: ErrorType, message: str, *, retryable: bool = False
    ) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


def _flag(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name, "false").strip().lower()
    if value not in ("true", "false"):
        raise SchwabReadError(
            ErrorType.VALIDATION_ERROR, f"{name} 必须为 true 或 false。"
        )
    return value == "true"


@dataclass(frozen=True)
class ReadOnlyPolicy:
    enabled: bool = False
    submission_enabled: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "ReadOnlyPolicy":
        return cls(
            _flag(env, "SCHWAB_API_ENABLED"), _flag(env, "ORDER_SUBMISSION_ENABLED")
        )

    def require_enabled(self) -> None:
        if self.enabled is not True or self.submission_enabled is not False:
            raise SchwabReadError(
                ErrorType.RISK_RULE_BLOCKED,
                "Schwab 同步需要显式启用 API；订单提交必须保持关闭。",
            )


@dataclass(frozen=True)
class TokenMetadata:
    access_token: SecretStr = field(repr=False)
    account_number: SecretStr = field(repr=False)
    expires_at: datetime

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "TokenMetadata":
        token = env.get("SCHWAB_ACCESS_TOKEN", "")
        account = env.get("SCHWAB_ACCOUNT_NUMBER", "")
        try:
            expiry = datetime.fromisoformat(
                env.get("SCHWAB_ACCESS_TOKEN_EXPIRES_AT", "")
            )
        except ValueError:
            expiry = None
        if (
            not token
            or not token.isascii()
            or not token.isprintable()
            or any(char.isspace() for char in token)
            or not _NUMBER.fullmatch(account)
            or expiry is None
            or expiry.utcoffset() is None
        ):
            raise SchwabReadError(
                ErrorType.AUTH_ERROR,
                "请在本地设置访问令牌、带时区的到期时间及目标 Schwab 账号。",
            )
        return cls(SecretStr(token), SecretStr(account), expiry.astimezone(UTC))


def _now() -> datetime:
    return datetime.now(UTC)


def utc_time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise SchwabReadError(
            ErrorType.VALIDATION_ERROR, "Schwab 读取时间必须包含时区。"
        )
    return value.astimezone(UTC)


def _window(start: datetime, end: datetime) -> tuple[str, str]:
    start, end = utc_time(start), utc_time(end)
    if not timedelta(seconds=1) <= end - start <= timedelta(days=365):
        raise SchwabReadError(
            ErrorType.VALIDATION_ERROR, "Schwab 读取区间应为 1 秒至 365 天。"
        )
    return tuple(
        item.isoformat(timespec="seconds").replace("+00:00", "Z")
        for item in (start, end)
    )


def require_list(result: object) -> list[dict]:
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise SchwabReadError(
            ErrorType.VALIDATION_ERROR, "Schwab 读取响应应为对象列表。"
        )
    return result


class SchwabReadClient:
    """仅提供固定 Schwab Trader GET 路由，未实现任何交易操作。"""

    def __init__(
        self,
        policy: ReadOnlyPolicy,
        auth: TokenMetadata,
        *,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        policy.require_enabled()
        self._auth = auth
        self._clock = clock
        self._owned = session is None
        self._http = requests.Session() if session is None else session
        if self._owned:
            self._http.trust_env = False
        self._account_hash: str | None = None

    def close(self) -> None:
        if self._owned:
            self._http.close()

    def read_account(self) -> dict:
        self._account_hash = None
        number = self._auth.account_number.get_secret_value()
        rows = require_list(self._get(f"{_BASE}/accountNumbers"))
        hashes = [
            row.get("hashValue") for row in rows if row.get("accountNumber") == number
        ]
        if (
            len(hashes) != 1
            or not isinstance(hashes[0], str)
            or not _HASH.fullmatch(hashes[0])
        ):
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "未能唯一匹配目标 Schwab 账户。"
            )
        account_hash = hashes[0]
        payload = self._get(f"{_BASE}/{account_hash}", params={"fields": "positions"})
        account = (
            payload.get("securitiesAccount") if isinstance(payload, dict) else None
        )
        if not isinstance(account, dict) or account.get("accountNumber") != number:
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "Schwab 返回的账户与本地绑定不一致。"
            )
        self._account_hash = account_hash
        return account

    def read_trades(self, start: datetime, end: datetime) -> list[dict]:
        first, last = _window(start, end)
        return require_list(
            self._get(
                self._account_path("transactions"),
                params={"startDate": first, "endDate": last, "types": "TRADE"},
            )
        )

    def read_orders(self, start: datetime, end: datetime) -> list[dict]:
        first, last = _window(start, end)
        rows = require_list(
            self._get(
                self._account_path("orders"),
                params={
                    "fromEnteredTime": first,
                    "toEnteredTime": last,
                    "maxResults": 5000,
                },
            )
        )
        if len(rows) >= 5000:
            raise SchwabReadError(
                ErrorType.BROKER_API_ERROR, "订单历史可能被截断，请缩短读取区间。"
            )
        return rows

    def validate_account(self, payload: dict) -> None:
        number = payload.get("accountNumber")
        if (
            number is not None
            and number != self._auth.account_number.get_secret_value()
        ):
            raise SchwabReadError(
                ErrorType.VALIDATION_ERROR, "历史记录中的账户与本地绑定不一致。"
            )

    def _account_path(self, endpoint: str) -> str:
        if self._account_hash is None:
            raise SchwabReadError(ErrorType.AUTH_ERROR, "必须先核验 Schwab 账户绑定。")
        return f"{_BASE}/{self._account_hash}/{endpoint}"

    def _get(self, url: str, *, params: dict | None = None):
        if not _READ_URL.fullmatch(url):
            raise SchwabReadError(
                ErrorType.RISK_RULE_BLOCKED, "该地址不属于允许的 Schwab 只读路由。"
            )
        if utc_time(self._clock()) >= self._auth.expires_at:
            raise SchwabReadError(
                ErrorType.AUTH_ERROR, "访问令牌已过期，请在本地更新授权。"
            )
        try:
            response = self._http.get(
                url,
                headers={
                    "Authorization": "Bearer "
                    + self._auth.access_token.get_secret_value(),
                    "Accept": "application/json",
                },
                params=params,
                timeout=15,
                verify=True,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabReadError(
                ErrorType.BROKER_API_ERROR, "无法读取 Schwab API。", retryable=True
            ) from None
        status = response.status_code
        if status in (401, 403):
            raise SchwabReadError(
                ErrorType.AUTH_ERROR, "Schwab 拒绝授权或当前应用无读取权限。"
            )
        if status != 200:
            raise SchwabReadError(
                ErrorType.BROKER_API_ERROR,
                f"Schwab 读取失败（HTTP {status}）。",
                retryable=status == 429 or 500 <= status <= 599,
            )
        try:
            return response.json(parse_float=Decimal)
        except ValueError:
            raise SchwabReadError(
                ErrorType.BROKER_API_ERROR, "Schwab 响应不是有效的 JSON。"
            ) from None
