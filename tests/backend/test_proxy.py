from email.message import Message
import unittest

from research_proxy import client_ip, parse_trusted_proxies


class ClientIPTests(unittest.TestCase):
    def headers(self, *values):
        headers = Message()
        for value in values:
            headers['X-Forwarded-For'] = value
        return headers

    def test_untrusted_direct_peer_cannot_choose_identity(self):
        for peer in ('198.51.100.4', '127.0.0.1'):
            self.assertEqual(client_ip(peer, self.headers('203.0.113.8')), peer)
        trusted = parse_trusted_proxies('127.0.0.1')
        self.assertEqual(client_ip('198.51.100.4', self.headers('203.0.113.8'), trusted), '198.51.100.4')

    def test_trusted_proxy_uses_only_last_ip(self):
        trusted = parse_trusted_proxies('127.0.0.1/32')
        for header in ('203.0.113.99, 198.51.100.8', 'fake, fake-again, 198.51.100.8', '198.51.100.8'):
            self.assertEqual(client_ip('127.0.0.1', self.headers(header), trusted), '198.51.100.8')

    def test_invalid_duplicate_and_oversized_headers_fall_back_to_peer(self):
        trusted = parse_trusted_proxies('127.0.0.1')
        for headers in (self.headers(), self.headers(''), self.headers('203.0.113.4,'),
                        self.headers('203.0.113.4, invalid'), self.headers('198.51.100.8:42'),
                        self.headers('198.51.100.8', '203.0.113.4'), self.headers(' ' * 2048 + '1')):
            self.assertEqual(client_ip('127.0.0.1', headers, trusted), '127.0.0.1')

    def test_ipv6_and_ipv4_mapped_addresses_have_canonical_buckets(self):
        trusted = parse_trusted_proxies('::1, 127.0.0.1')
        self.assertEqual(client_ip('::1', self.headers('2001:db8:0:0::a'), trusted), '2001:db8::a')
        self.assertEqual(client_ip('::ffff:127.0.0.1', self.headers('::ffff:198.51.100.8'), trusted), '198.51.100.8')
        self.assertEqual(client_ip('::1', self.headers('fe80::1%eth0'), trusted), '::1')

    def test_configuration_accepts_explicit_networks_and_rejects_invalid_trust(self):
        self.assertEqual(len(parse_trusted_proxies('127.0.0.1/32, ::1/128 10.20.30.0/24')), 3)
        self.assertEqual(parse_trusted_proxies(''), ())
        for value in ('0.0.0.0/0', '::/0', 'localhost', '127.0.0.1:8080', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_trusted_proxies(value)


if __name__ == '__main__':
    unittest.main()
