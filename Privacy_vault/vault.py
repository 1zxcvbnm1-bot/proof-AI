"""
╔══════════════════════════════════════════════════════╗
║  ENCRYPTION VAULT — AES-256-GCM · Key rotation       ║
║  Per-tenant keys · HashiCorp Vault compatible        ║
╚══════════════════════════════════════════════════════╝

Provides:
  - AES-256-GCM encryption/decryption for any data
  - Per-tenant encryption key isolation
  - Automatic key rotation every 90 days
  - HashiCorp Vault integration (production upgrade path)
  - Key versioning — old versions can still decrypt
"""

from __future__ import annotations
import base64, hashlib, hmac, json, os, time, uuid
from dataclasses import dataclass, field
from typing import Optional


# ── Minimal AES-256-GCM without heavy deps ───────────────────────────────────
# Production: from cryptography.hazmat.primitives.ciphers.aead import AESGCM
# Dev fallback: XOR-based symmetric cipher (NEVER use in production)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


@dataclass
class EncryptedPayload:
    ciphertext:   str       # base64-encoded
    nonce:        str       # base64-encoded (96-bit for GCM)
    key_id:       str       # which key version was used
    tenant_id:    str
    algorithm:    str = "AES-256-GCM"
    created_at:   float = field(default_factory=time.time)


@dataclass
class VaultKey:
    key_id:     str
    tenant_id:  str
    key_bytes:  bytes       # 32 bytes = 256 bits
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    active:     bool = True

    KEY_ROTATION_DAYS = 90

    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False
        return time.time() > self.expires_at


class EncryptionVault:
    """
    AES-256-GCM encryption vault with per-tenant key isolation.

    Production upgrade:
        Connect to HashiCorp Vault:
            import hvac
            client = hvac.Client(url='https://vault:8200', token=VAULT_TOKEN)
            client.secrets.transit.encrypt_data('key-name', base64_plaintext)

        Or AWS KMS:
            import boto3
            kms = boto3.client('kms')
            kms.encrypt(KeyId=KEY_ARN, Plaintext=plaintext)

    Dev mode: in-memory key store with proper AES-256-GCM when cryptography
    package is available, XOR fallback otherwise.
    """

    KEY_ROTATION_SECONDS = 90 * 86400   # 90 days

    def __init__(self, master_secret: Optional[str] = None):
        self._master = (master_secret or os.environ.get("VAULT_MASTER_SECRET", "dev-secret-change-in-prod")).encode()
        self._keys:   dict[str, list[VaultKey]] = {}   # tenant_id → [VaultKey, ...]
        self._active: dict[str, VaultKey] = {}          # tenant_id → current active key

    def _derive_key(self, tenant_id: str, salt: bytes) -> bytes:
        """Derive a 256-bit key from master secret + tenant_id + salt."""
        if CRYPTO_AVAILABLE:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100_000,
            )
            return kdf.derive(self._master + tenant_id.encode())
        # Fallback: HMAC-SHA256 (not as secure as PBKDF2 but usable for dev)
        return hmac.new(self._master, salt + tenant_id.encode(), hashlib.sha256).digest()

    def get_or_create_key(self, tenant_id: str) -> VaultKey:
        """Get or create the active encryption key for a tenant."""
        active = self._active.get(tenant_id)
        if active and not active.is_expired():
            return active
        return self._rotate_key(tenant_id)

    def _rotate_key(self, tenant_id: str) -> VaultKey:
        """Create a new key version, retire the old one."""
        salt = os.urandom(16)
        key_bytes = self._derive_key(tenant_id, salt)
        key = VaultKey(
            key_id=str(uuid.uuid4())[:12],
            tenant_id=tenant_id,
            key_bytes=key_bytes,
            expires_at=time.time() + self.KEY_ROTATION_SECONDS,
        )
        if tenant_id not in self._keys:
            self._keys[tenant_id] = []
        # Deactivate old key (keep for decryption of old data)
        if tenant_id in self._active:
            self._active[tenant_id].active = False
        self._keys[tenant_id].append(key)
        self._active[tenant_id] = key
        return key

    def encrypt(self, plaintext: str, tenant_id: str = "default") -> EncryptedPayload:
        """Encrypt plaintext using AES-256-GCM."""
        key = self.get_or_create_key(tenant_id)
        data = plaintext.encode("utf-8")

        if CRYPTO_AVAILABLE:
            nonce = os.urandom(12)   # 96-bit nonce for GCM
            aesgcm = AESGCM(key.key_bytes)
            ciphertext = aesgcm.encrypt(nonce, data, None)
        else:
            # XOR fallback — dev only, not production-safe
            nonce = os.urandom(12)
            keystream = (key.key_bytes * ((len(data) // 32) + 2))[:len(data)]
            ciphertext = bytes(a ^ b for a, b in zip(data, keystream))

        return EncryptedPayload(
            ciphertext=base64.b64encode(ciphertext).decode(),
            nonce=base64.b64encode(nonce).decode(),
            key_id=key.key_id,
            tenant_id=tenant_id,
            algorithm="AES-256-GCM" if CRYPTO_AVAILABLE else "XOR-DEV-ONLY",
        )

    def decrypt(self, payload: EncryptedPayload) -> str:
        """Decrypt using the key version that was used to encrypt."""
        key = self._find_key(payload.tenant_id, payload.key_id)
        if not key:
            raise ValueError(f"Key {payload.key_id} not found for tenant {payload.tenant_id}")

        ciphertext = base64.b64decode(payload.ciphertext)
        nonce       = base64.b64decode(payload.nonce)

        if CRYPTO_AVAILABLE and payload.algorithm == "AES-256-GCM":
            aesgcm = AESGCM(key.key_bytes)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        else:
            keystream = (key.key_bytes * ((len(ciphertext) // 32) + 2))[:len(ciphertext)]
            plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))

        return plaintext.decode("utf-8")

    def encrypt_dict(self, data: dict, tenant_id: str = "default") -> str:
        """Encrypt a dict → returns base64 JSON of EncryptedPayload."""
        payload = self.encrypt(json.dumps(data), tenant_id)
        return base64.b64encode(json.dumps({
            "ciphertext": payload.ciphertext,
            "nonce":      payload.nonce,
            "key_id":     payload.key_id,
            "tenant_id":  payload.tenant_id,
            "algorithm":  payload.algorithm,
        }).encode()).decode()

    def decrypt_dict(self, encrypted_str: str) -> dict:
        """Decrypt a base64 JSON string back to dict."""
        raw = json.loads(base64.b64decode(encrypted_str).decode())
        payload = EncryptedPayload(**raw)
        return json.loads(self.decrypt(payload))

    def _find_key(self, tenant_id: str, key_id: str) -> Optional[VaultKey]:
        for k in self._keys.get(tenant_id, []):
            if k.key_id == key_id:
                return k
        return None

    def key_status(self, tenant_id: str) -> dict:
        active = self._active.get(tenant_id)
        all_keys = self._keys.get(tenant_id, [])
        return {
            "tenant_id":    tenant_id,
            "active_key_id": active.key_id if active else None,
            "total_versions": len(all_keys),
            "algorithm":    "AES-256-GCM" if CRYPTO_AVAILABLE else "XOR-DEV",
            "crypto_available": CRYPTO_AVAILABLE,
            "expires_in_days": round((active.expires_at - time.time()) / 86400, 1) if active and active.expires_at else None,
        }
