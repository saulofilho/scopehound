import ipaddress

import pytest
from conftest import make_scope

from scopehound.guardrails import DEFAULT_INTERNAL, EgressDenied, IpPolicy

ip = ipaddress.ip_address


@pytest.mark.parametrize(
    "addr",
    [
        "169.254.169.254",
        "::ffff:169.254.169.254",
        "64:ff9b::a9fe:a9fe",  # NAT64 de 169.254.169.254
        "2002:a9fe:a9fe::1",  # 6to4 de 169.254.169.254
        "fd00:ec2::254",
        "0.0.0.0",
        "224.0.0.1",
        "::",
    ],
)
def test_always_denied_even_with_cidr(addr):
    scope = make_scope(allowed_cidrs=["169.254.0.0/16"])
    with pytest.raises(EgressDenied):
        IpPolicy().check(ip(addr), scope)


def test_local_mode_allows_loopback():
    IpPolicy().check(ip("127.0.0.1"), make_scope())


def test_server_mode_blocks_internal_unless_scoped():
    policy = IpPolicy.build(internal_deny=DEFAULT_INTERNAL)
    for addr in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "::1", "::ffff:10.0.0.5"):
        with pytest.raises(EgressDenied):
            policy.check(ip(addr), make_scope())
    policy.check(ip("10.0.0.5"), make_scope(allowed_cidrs=["10.0.0.0/24"]))
    policy.check(ip("93.184.215.14"), make_scope())


def test_hard_deny_not_overridable():
    policy = IpPolicy.build(hard_deny=["10.96.0.0/12"])
    with pytest.raises(EgressDenied):
        policy.check(ip("10.96.0.1"), make_scope(allowed_cidrs=["10.96.0.0/12"]))
