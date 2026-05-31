from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    name: str
    server: str
    username: str | None = None
    password: str | None = None

    def to_playwright(self) -> dict[str, str]:
        payload = {"server": self.server}
        if self.username:
            payload["username"] = self.username
        if self.password:
            payload["password"] = self.password
        return payload

    def safe_label(self) -> str:
        return self.name


def build_proxy_configs(
    proxy_list_path: str | None = None,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
) -> list[ProxyConfig]:
    configs: list[ProxyConfig] = []
    if proxy_list_path:
        configs.extend(load_proxy_list(Path(proxy_list_path)))
    if proxy_server:
        configs.append(parse_proxy_line(proxy_server, proxy_username, proxy_password, index=len(configs) + 1))
    return configs


def load_proxy_list(path: Path) -> list[ProxyConfig]:
    if not path.exists():
        raise FileNotFoundError(f"Proxy list file not found: {path}")

    configs: list[ProxyConfig] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        configs.append(parse_proxy_line(line, index=len(configs) + 1))
    return configs


def parse_proxy_line(
    raw_proxy: str,
    username: str | None = None,
    password: str | None = None,
    index: int = 1,
) -> ProxyConfig:
    proxy = raw_proxy.strip()
    if not proxy:
        raise ValueError("Proxy value cannot be empty.")
    if "://" not in proxy:
        proxy = f"http://{proxy}"

    parsed = urlsplit(proxy)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"Invalid proxy format: {raw_proxy}")

    proxy_username = username if username is not None else unquote(parsed.username or "") or None
    proxy_password = password if password is not None else unquote(parsed.password or "") or None
    server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
    label_host = parsed.hostname.replace(".", "_").replace("-", "_")
    return ProxyConfig(
        name=f"proxy_{index}_{label_host}_{parsed.port}",
        server=server,
        username=proxy_username,
        password=proxy_password,
    )


def proxy_for_batch(proxy_configs: list[ProxyConfig], batch_index: int) -> ProxyConfig | None:
    if not proxy_configs:
        return None
    return proxy_configs[(batch_index - 1) % len(proxy_configs)]
