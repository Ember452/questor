"""Mirror test for ``execution/network.py`` (plan 01, R7).

Scope note: this module is the SSRF guard in front of every outbound web tool, and
before this file no test named any of ``validate_http_url``, ``ensure_http_url_allowed``,
``NetworkGuardError``, ``ResolutionMode``, ``parse_synthetic_dns_cidrs`` or
``get_web_resolution_mode``. Every case here is policy: what is refused, in which mode,
and what the operator is told to change. No test performs real DNS or real HTTP.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from questorharness.execution import network
from questorharness.execution.network import (
    NetworkGuardError,
    ResolutionMode,
    ensure_http_url_allowed,
    get_web_resolution_mode,
    parse_synthetic_dns_cidrs,
    validate_http_url,
)

# Addresses used below: 8.8.8.8 is public, the rest are not.
PUBLIC = "8.8.8.8"
LOOPBACK = "127.0.0.1"
PRIVATE = "10.13.37.5"
LINK_LOCAL = "169.254.169.254"  # the cloud metadata endpoint


def fake_dns(*addresses: str):
    """Replace getaddrinfo so a hostname resolves to fixed literals."""

    def _resolve(host, port, family, type_):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, port)) for address in addresses]

    return _resolve


# --- syntax policy --------------------------------------------------------


@pytest.mark.parametrize("url", ["https://example.com/a", "http://example.com", f"http://{PUBLIC}/"])
def test_http_and_https_are_accepted(url: str) -> None:
    assert validate_http_url(url) is None


@pytest.mark.parametrize(
    "url",
    ["ftp://example.com/file", "file:///etc/passwd", "https://", "//example.com", "example.com/no-scheme"],
)
def test_anything_that_is_not_an_absolute_http_url_is_refused(url: str) -> None:
    with pytest.raises(NetworkGuardError):
        validate_http_url(url)


def test_credentials_embedded_in_the_url_are_refused() -> None:
    # ``https://user:pass@host`` would silently carry a secret into logs and redirects.
    with pytest.raises(NetworkGuardError, match="embedded credentials"):
        validate_http_url("https://admin:pw@example.com/")


# --- mode resolution ------------------------------------------------------


def test_auto_mode_follows_the_presence_of_a_proxy() -> None:
    assert get_web_resolution_mode(None) is ResolutionMode.DIRECT
    assert get_web_resolution_mode("http://proxy.internal:3128") is ResolutionMode.PROXY
    assert get_web_resolution_mode(None, configured_mode="auto") is ResolutionMode.DIRECT


def test_mode_names_are_normalised_across_dashes_and_case() -> None:
    assert get_web_resolution_mode(None, configured_mode="Synthetic-DNS") is ResolutionMode.SYNTHETIC_DNS
    assert get_web_resolution_mode(None, configured_mode=" DIRECT ") is ResolutionMode.DIRECT


def test_asking_for_proxy_mode_without_a_proxy_is_a_configuration_error() -> None:
    with pytest.raises(NetworkGuardError, match="requires web.proxy"):
        get_web_resolution_mode(None, configured_mode="proxy")


def test_an_unknown_mode_lists_the_choices_it_accepts() -> None:
    with pytest.raises(NetworkGuardError, match="must be one of") as caught:
        get_web_resolution_mode(None, configured_mode="split-tunnel")

    message = str(caught.value)
    for mode in ResolutionMode:
        assert mode.value in message


# --- synthetic DNS cidrs --------------------------------------------------


def test_no_cidrs_is_no_networks() -> None:
    assert parse_synthetic_dns_cidrs() == ()
    assert parse_synthetic_dns_cidrs("") == ()
    assert parse_synthetic_dns_cidrs(" , ") == ()


def test_cidr_list_is_parsed_leniently() -> None:
    networks = parse_synthetic_dns_cidrs("10.0.0.0/8, 192.168.1.100")

    assert networks == (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("192.168.1.100/32"))


def test_a_bad_entry_names_the_entry_not_the_whole_list() -> None:
    with pytest.raises(NetworkGuardError, match="invalid web.synthetic_dns_cidrs entry: 10.0.0.0/33"):
        parse_synthetic_dns_cidrs("10.0.0.0/8, 10.0.0.0/33")


# --- direct mode: the strict case ----------------------------------------


async def test_direct_mode_accepts_a_public_literal_address() -> None:
    await ensure_http_url_allowed(f"http://{PUBLIC}/x", mode=ResolutionMode.DIRECT)


@pytest.mark.parametrize("address", [LOOPBACK, PRIVATE, LINK_LOCAL, "::1"])
async def test_direct_mode_refuses_every_non_public_literal(address: str) -> None:
    host = f"[{address}]" if ":" in address else address

    with pytest.raises(NetworkGuardError, match="non-public") as caught:
        await ensure_http_url_allowed(f"http://{host}/", mode=ResolutionMode.DIRECT)

    # A literal address is refused without the synthetic-dns hint: the hint exists for
    # hostnames whose DNS was resolved for you, and there is nothing to declare when the
    # operator typed the private address themselves. Asserted so the asymmetry is visible
    # rather than assumed -- if that asymmetry is ever judged wrong, fix the guard, not
    # this test.
    assert "resolution_mode=synthetic_dns" not in str(caught.value)


async def test_direct_mode_names_only_the_first_three_blocked_addresses(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns("10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"))

    with pytest.raises(NetworkGuardError) as caught:
        await ensure_http_url_allowed("https://svc.example/", mode=ResolutionMode.DIRECT)

    message = str(caught.value)
    assert "10.0.0.1, 10.0.0.2, 10.0.0.3, ..." in message
    assert "10.0.0.4" not in message
    # This is the path where the escape hatch is actionable, so the hint is included.
    assert "web.resolution_mode=synthetic_dns" in message


async def test_direct_mode_checks_resolved_addresses_not_just_the_hostname(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(PUBLIC, PRIVATE))

    with pytest.raises(NetworkGuardError, match=PRIVATE.replace(".", r"\.")):
        await ensure_http_url_allowed("https://svc.example.com/", mode=ResolutionMode.DIRECT)


async def test_direct_mode_allows_a_host_whose_addresses_are_all_public(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(PUBLIC, "8.8.4.4"))

    await ensure_http_url_allowed("https://svc.example.com/", mode=ResolutionMode.DIRECT)


async def test_a_local_hostname_never_reaches_the_resolver(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("getaddrinfo must not be called for a local name")

    monkeypatch.setattr(network.socket, "getaddrinfo", _boom)

    for url in (
        "http://localhost:8080/",
        "http://LOCALHOST./",  # normalised before the check
        "http://db.internal/",
        "http://api.cluster.local/",
        "http://intranet/",  # single label
        "http://metadata.google.internal/",
    ):
        with pytest.raises(NetworkGuardError):
            await ensure_http_url_allowed(url, mode=ResolutionMode.DIRECT)


async def test_unresolvable_hosts_are_reported_rather_than_allowed(monkeypatch) -> None:
    def _fail(host, port, family, type_):
        raise OSError(" Name or service not known")

    monkeypatch.setattr(network.socket, "getaddrinfo", _fail)
    with pytest.raises(NetworkGuardError, match="could not resolve target host"):
        await ensure_http_url_allowed("https://nope.example/", mode=ResolutionMode.DIRECT)

    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns())
    with pytest.raises(NetworkGuardError, match="did not resolve"):
        await ensure_http_url_allowed("https://empty.example/", mode=ResolutionMode.DIRECT)


# --- proxy mode -----------------------------------------------------------


async def test_proxy_mode_checks_the_name_but_leaves_resolution_to_the_proxy(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("proxy mode must not resolve the target locally")

    monkeypatch.setattr(network.socket, "getaddrinfo", _boom)

    await ensure_http_url_allowed("https://intranet-service.example.com/", mode=ResolutionMode.PROXY)


@pytest.mark.parametrize("address", [LOOPBACK, PRIVATE])
async def test_proxy_mode_still_refuses_a_literal_private_target(address: str) -> None:
    # A proxy resolves the name, but a literal address is already concrete.
    with pytest.raises(NetworkGuardError, match="non-public"):
        await ensure_http_url_allowed(f"http://{address}/", mode=ResolutionMode.PROXY)


async def test_proxy_mode_refuses_local_names_without_resolving(monkeypatch) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("proxy mode must not resolve the target locally")

    monkeypatch.setattr(network.socket, "getaddrinfo", _boom)

    with pytest.raises(NetworkGuardError, match="local hostnames"):
        await ensure_http_url_allowed("http://cache.local/", mode=ResolutionMode.PROXY)


# --- synthetic dns mode ---------------------------------------------------


async def test_synthetic_mode_requires_a_declared_cidr_block(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(PRIVATE))

    with pytest.raises(NetworkGuardError, match="requires web.synthetic_dns_cidrs"):
        await ensure_http_url_allowed("https://svc.example/", mode=ResolutionMode.SYNTHETIC_DNS)


async def test_synthetic_mode_allows_the_declared_range_and_nothing_else(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(PRIVATE))
    allowed = parse_synthetic_dns_cidrs("10.0.0.0/8")

    await ensure_http_url_allowed("https://svc.example/", mode=ResolutionMode.SYNTHETIC_DNS, synthetic_cidrs=allowed)

    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(LINK_LOCAL))
    with pytest.raises(NetworkGuardError, match=LINK_LOCAL.replace(".", r"\.")) as caught:
        await ensure_http_url_allowed("https://svc.example/", mode=ResolutionMode.SYNTHETIC_DNS, synthetic_cidrs=allowed)

    # The synthetic-dns hint is already the mode in use, so it is not repeated back.
    assert "resolution_mode=synthetic_dns" not in str(caught.value)


async def test_a_v6_address_is_not_matched_against_a_v4_cidr(monkeypatch) -> None:
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns("fd00::1"))

    with pytest.raises(NetworkGuardError, match="fd00::1"):
        await ensure_http_url_allowed(
            "https://svc.example/",
            mode=ResolutionMode.SYNTHETIC_DNS,
            synthetic_cidrs=parse_synthetic_dns_cidrs("10.0.0.0/8"),
        )


# --- the redirect loop ----------------------------------------------------


async def allow_any(*args, **kwargs) -> None:
    """Stand-in for the guard when the test is about the loop, not about policy."""
    return


class _Client:
    """Minimal stand-in for httpx.AsyncClient: scripted hops, no sockets."""

    def __init__(self, hops: list[tuple[str, str | None]]) -> None:
        self.hops = hops
        self.requested: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, *, params=None, headers=None):
        self.requested.append(url)
        location = self.hops[len(self.requested) - 1][1]
        return _Response(url, location)


class _Response:
    def __init__(self, url: str, location: str | None) -> None:
        self.url = url
        self.has_redirect_location = location is not None
        self.headers = {"location": location} if location is not None else {}


@pytest.fixture()
def default_web_config(monkeypatch):
    """Pin the persisted settings so a developer's proxy config cannot flip the mode."""
    monkeypatch.setattr(
        network,
        "_load_configured_web_settings",
        lambda: network._ConfiguredWebSettings(proxy=None, resolution_mode="auto", synthetic_dns_cidrs=[]),
    )


async def test_every_redirect_hop_is_validated_again(monkeypatch, default_web_config) -> None:
    """A public first hop must not be allowed to bounce into the private range."""
    from questorharness.execution.network import fetch_public_http_response

    hops = [("https://public.example/", "http://" + PRIVATE + "/x")]
    client = _Client(hops)
    monkeypatch.setattr(network.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(network.socket, "getaddrinfo", fake_dns(PUBLIC))
    seen: list[str] = []
    original = network.ensure_http_url_allowed

    async def spy(url, **kwargs):
        seen.append(url)
        await original(url, **kwargs)

    monkeypatch.setattr(network, "ensure_http_url_allowed", spy)

    with pytest.raises(NetworkGuardError, match="non-public"):
        await fetch_public_http_response("https://public.example/", proxy=None)

    assert seen == ["https://public.example/", f"http://{PRIVATE}/x"]


async def test_query_params_are_dropped_after_a_redirect(monkeypatch, default_web_config) -> None:
    from questorharness.execution.network import fetch_public_http_response

    client = _Client([("https://public.example/", f"https://other.example/{PUBLIC}"), ("https://other.example/8.8.4.4", None)])
    monkeypatch.setattr(network.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(network, "ensure_http_url_allowed", allow_any)

    recorded: list[dict] = []
    original_get = client.get

    async def get(url, *, params=None, headers=None):
        recorded.append({"url": url, "params": params})
        return await original_get(url, params=params, headers=headers)

    client.get = get  # type: ignore[method-assign]

    await fetch_public_http_response("https://public.example/", params={"secret": "token"}, proxy=None)

    assert recorded[0]["params"] == {"secret": "token"}
    assert recorded[1]["params"] is None


async def test_the_redirect_chain_is_limited(monkeypatch, default_web_config) -> None:
    from questorharness.execution.network import fetch_public_http_response

    hops = [(f"https://hop{i}.example/", f"https://hop{i + 1}.example/") for i in range(10)]
    client = _Client(hops)
    monkeypatch.setattr(network.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(network, "ensure_http_url_allowed", allow_any)

    with pytest.raises(NetworkGuardError, match="too many redirects"):
        await fetch_public_http_response("https://start.example/", max_redirects=2, proxy=None)

    assert len(client.requested) == 3
