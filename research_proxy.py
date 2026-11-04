"""Client identity for an explicitly trusted, single HTTP reverse proxy."""
import ipaddress
import re


def _address(value):
    if not isinstance(value, str) or '%' in value:
        raise ValueError('无效 IP 地址')
    address = ipaddress.ip_address(value.strip())
    return address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped else address


def parse_trusted_proxies(value):
    """No implicit trust, including loopback; deployment declares the proxy IPs."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('FUNDPILOT_TRUSTED_PROXIES 格式无效')
    networks = []
    for token in re.split(r'[,\s]+', value.strip()):
        if not token:
            continue
        try:
            network = ipaddress.ip_network(token, strict=False)
        except ValueError:
            raise ValueError('FUNDPILOT_TRUSTED_PROXIES 只能包含 IP 地址或 CIDR 网段') from None
        if network.prefixlen == 0:
            raise ValueError('可信代理不能设置为全部互联网地址')
        networks.append(network)
    return tuple(networks)


def client_ip(peer, headers, trusted_proxies=()):
    """Only the last XFF item written by the trusted direct proxy is used.

    Caller-supplied values on the left never define an identity. Multiple header
    lines, oversized values and an invalid final item fall back to the TCP peer.
    This deliberately describes one proxy hop, not arbitrary CDN chain parsing.
    """
    address = _address(peer)
    if not any(address.version == network.version and address in network for network in trusted_proxies):
        return str(address)
    values = headers.get_all('X-Forwarded-For', [])
    if len(values) != 1 or len(values[0]) > 2048:
        return str(address)
    try:
        return str(_address(values[0].rsplit(',', 1)[-1]))
    except ValueError:
        return str(address)
