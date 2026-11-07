# SPDX-License-Identifier: GPL-3.0-or-later
# The pairing proofs of protocol v2 (docs/PROTOCOL.md section 3), plain Python (hashlib / hmac only), shared by the
# addon's server and the tests' client. The plugin (plugin/main.js) computes exactly the same values.
#
# Pairing (first time): the Nighty Vault plugin shows a 6-digit code; the person types it in Blender's N panel. Both
# sides turn the code into a key with PBKDF2-HMAC-SHA256 (salted with both random nonces, so a key is good for one
# connection only), then prove they know it with HMACs, Blender first:
#     key          = PBKDF2(code, "nighty-blender.v2|" + nonce_client + "|" + nonce_server, ITERATIONS, 32 bytes)
#     server proof = HMAC(key, "nb2/server-pair|" + nonce_client + "|" + nonce_server)
#     client proof = HMAC(key, "nb2/client-pair|" + nonce_server + "|" + nonce_client)
# Then Blender makes a random 16-byte token (32 hex) and sends it sealed with the key:
#     box          = token XOR HMAC(key, "nb2/token-box|" + nonce_client + "|" + nonce_server)[:16]
# Reconnects (the token both sides kept): the same two proofs with the token's 16 bytes as the key and the labels
# "nb2/server-auth" / "nb2/client-auth", Blender first. A fake listener that never saw the code or the token can't
# make Blender's proof, so the plugin finds it out before it sends anything that matters.

import hashlib
import hmac
import os

ITERATIONS = 100_000
CODE_DIGITS = 6
MAX_WRONG = 5
NONCE_BYTES = 16
TOKEN_BYTES = 16


def new_nonce():
    return os.urandom(NONCE_BYTES).hex()


def new_token():
    return os.urandom(TOKEN_BYTES).hex()


def is_hex(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def normalize_code(text):
    """The digits the person typed ('123 456', '123-456' -> '123456'); None unless exactly 6 digits."""
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits if len(digits) == CODE_DIGITS else None


def derive_key(code, nonce_client, nonce_server, iterations=ITERATIONS):
    salt = ("nighty-blender.v2|%s|%s" % (nonce_client, nonce_server)).encode("ascii")
    return hashlib.pbkdf2_hmac("sha256", code.encode("ascii"), salt, iterations, 32)


def proof(key, label, first, second):
    return hmac.new(key, ("%s|%s|%s" % (label, first, second)).encode("ascii"), hashlib.sha256).hexdigest()


def same(a, b):
    return isinstance(a, str) and isinstance(b, str) and hmac.compare_digest(a, b)


def server_pair_proof(key, nc, ns):
    return proof(key, "nb2/server-pair", nc, ns)


def client_pair_proof(key, nc, ns):
    return proof(key, "nb2/client-pair", ns, nc)


def token_key(token_hex):
    return bytes.fromhex(token_hex)


def server_auth_proof(token_hex, nc, ns):
    return proof(token_key(token_hex), "nb2/server-auth", nc, ns)


def client_auth_proof(token_hex, nc, ns):
    return proof(token_key(token_hex), "nb2/client-auth", ns, nc)


def _pad(key, nc, ns):
    return bytes.fromhex(proof(key, "nb2/token-box", nc, ns))[:TOKEN_BYTES]


def seal_token(key, token_hex, nc, ns):
    return bytes(a ^ b for a, b in zip(bytes.fromhex(token_hex), _pad(key, nc, ns))).hex()


def open_token(key, box_hex, nc, ns):
    return bytes(a ^ b for a, b in zip(bytes.fromhex(box_hex), _pad(key, nc, ns))).hex()
