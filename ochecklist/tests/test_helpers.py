"""
Tests unitaires pour les helpers de ochecklist/views.py.

Couvre :
  - decompress_if_needed : pas d'en-tête, gzip valide, gzip invalide,
    casse, encodage inconnu, valeurs multiples
  - verify_content_digest : pas d'en-tête, SHA-256 base64/hex, SHA-512, MD5,
    algorithme non supporté, format invalide, délimiteurs RFC 3230,
    alias
"""

import base64
import gzip
import hashlib
from unittest.mock import patch

import pytest

from ochecklist import views as ochecklist_views
from ochecklist.views import decompress_if_needed, verify_content_digest


# ─── Tests decompress_if_needed ────────────────────────────────────────────────

class TestDecompressIfNeeded:
    """Vérifie le comportement du décompresseur gzip."""

    def test_header_none(self):
        body = b'raw bytes'
        assert decompress_if_needed(body, None) == body

    def test_header_vide(self):
        body = b'raw bytes'
        assert decompress_if_needed(body, '') == body

    def test_pas_de_gzip(self):
        """Un Content-Encoding qui n'est pas gzip laisse le corps intact."""
        body = b'raw bytes'
        assert decompress_if_needed(body, 'identity') == body

    def test_gzip_valide(self):
        original = b'Hello Ochecklist!'
        compressed = gzip.compress(original)
        assert decompress_if_needed(compressed, 'gzip') == original

    def test_gzip_majuscule(self):
        """La comparaison est insensible à la casse."""
        original = b'Hello Ochecklist!'
        compressed = gzip.compress(original)
        assert decompress_if_needed(compressed, 'GZIP') == original

    def test_gzip_mixte_casse(self):
        original = b'Hello Ochecklist!'
        compressed = gzip.compress(original)
        assert decompress_if_needed(compressed, 'Gzip') == original

    def test_gzip_invalide_retourne_original(self):
        """Si la décompression échoue, le corps d'origine est retourné."""
        body = b'not actually gzipped'
        assert decompress_if_needed(body, 'gzip') == body

    def test_gzip_corrompu(self):
        """Un blob gzip corrompu → retour au corps d'origine."""
        compressed = gzip.compress(b'payload')
        corrupted = b'\x00\x00\x00\x00\x00' + compressed[5:]
        assert decompress_if_needed(corrupted, 'gzip') == corrupted

    def test_encodage_inconnu(self):
        body = b'raw bytes'
        assert decompress_if_needed(body, 'deflate') == body

    def test_encodage_inconnu_bizarre(self):
        body = b'raw bytes'
        assert decompress_if_needed(body, 'br') == body

    def test_multi_valeurs_avec_gzip(self):
        """'gzip, identity' doit être traité comme gzip."""
        original = b'payload multi'
        compressed = gzip.compress(original)
        assert decompress_if_needed(compressed, 'gzip, identity') == original

    def test_multi_valeurs_sans_gzip(self):
        """'identity, br' ne doit pas décompresser."""
        body = b'raw bytes'
        assert decompress_if_needed(body, 'identity, br') == body

    def test_corps_vide_avec_gzip(self):
        """Un corps vide avec header gzip → body vide (gzip vide)."""
        empty_gzip = gzip.compress(b'')
        result = decompress_if_needed(empty_gzip, 'gzip')
        assert result == b''


# ─── Tests verify_content_digest ───────────────────────────────────────────────

class TestVerifyContentDigest:
    """Vérifie la validation de l'en-tête Content-Digest."""

    BODY = b'Hello Ochecklist body for hashing'

    def _digest(self, algo, encoding='base64'):
        h = algo(self.BODY).digest()
        if encoding == 'base64':
            return base64.b64encode(h).decode('ascii')
        return h.hex()

    # ── Pas d'en-tête ──────────────────────────────────────────────────────────

    def test_header_none(self):
        assert verify_content_digest(self.BODY, None) is True

    def test_header_vide(self):
        assert verify_content_digest(self.BODY, '') is True

    # ── Format invalide ────────────────────────────────────────────────────────

    def test_header_sans_egal(self):
        assert verify_content_digest(self.BODY, 'invalidnoequals') is False

    def test_header_avec_seulement_egal(self):
        assert verify_content_digest(self.BODY, '=') is False

    def test_algorithme_non_supporte(self):
        assert verify_content_digest(
            self.BODY, 'sha-1=abcdef'
        ) is False

    def test_algorithme_aleatoire(self):
        assert verify_content_digest(
            self.BODY, 'crc32=abcdef'
        ) is False

    # ── SHA-256 base64 ─────────────────────────────────────────────────────────

    def test_sha256_base64_match(self):
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(self.BODY, f'sha-256={digest}') is True

    def test_sha256_alias_sans_tiret(self):
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(self.BODY, f'sha256={digest}') is True

    def test_sha256_base64_mismatch(self):
        wrong = base64.b64encode(b'wrong hash wrong hash wrong hash').decode()
        assert verify_content_digest(self.BODY, f'sha-256={wrong}') is False

    def test_sha256_base64_mauvaise_longueur(self):
        assert verify_content_digest(
            self.BODY, 'sha-256=YWJjZA=='
        ) is False

    # ── SHA-256 hex ────────────────────────────────────────────────────────────

    def test_sha256_hex_mismatch(self):
        assert verify_content_digest(
            self.BODY, 'sha-256=' + '0' * 64
        ) is False

    def test_sha256_valeur_invalide(self):
        """Ni base64 ni hex valide → False."""
        assert verify_content_digest(
            self.BODY, 'sha-256=!!!notbase64andnothex!!!'
        ) is False

    def test_sha256_chaine_quelconque(self):
        assert verify_content_digest(
            self.BODY, 'sha-256=zzzz'
        ) is False

    def test_sha256_chiffres_uniquement(self):
        """Une chaîne de chiffres est un base64 valide mais ne matche pas."""
        assert verify_content_digest(self.BODY, 'sha-256=12345678') is False

    # ── SHA-512 ────────────────────────────────────────────────────────────────

    def test_sha512_base64_match(self):
        digest = self._digest(hashlib.sha512, 'base64')
        assert verify_content_digest(self.BODY, f'sha-512={digest}') is True

    def test_sha512_alias_sans_tiret(self):
        digest = self._digest(hashlib.sha512, 'base64')
        assert verify_content_digest(self.BODY, f'sha512={digest}') is True

    def test_sha512_mismatch(self):
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(self.BODY, f'sha-512={digest}') is False

    # ── MD5 ────────────────────────────────────────────────────────────────────

    def test_md5_base64_match(self):
        digest = self._digest(hashlib.md5, 'base64')
        assert verify_content_digest(self.BODY, f'md5={digest}') is True

    def test_md5_mismatch(self):
        assert verify_content_digest(
            self.BODY, 'md5=AAAAAAAAAAAAAAAAAAAAAA=='
        ) is False

    # ── Délimiteurs RFC 3230 (':valeur:') ──────────────────────────────────────

    def test_sha256_avec_coln_rfc3230(self):
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(
            self.BODY, f'sha-256=:{digest}:'
        ) is True

    def test_sha256_avec_colon_uniquement(self):
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(
            self.BODY, f'sha-256=:{digest}'
        ) is True

    def test_sha256_avec_espaces(self):
        """Les espaces autour de la valeur sont strippés."""
        digest = self._digest(hashlib.sha256, 'base64')
        assert verify_content_digest(
            self.BODY, f'sha-256=  {digest}  '
        ) is True

    # ── Robustesse ─────────────────────────────────────────────────────────────

    def test_corps_vide_avec_digest_vide(self):
        """Digest du corps vide doit être valide."""
        digest = base64.b64encode(hashlib.sha256(b'').digest()).decode()
        assert verify_content_digest(b'', f'sha-256={digest}') is True

    def test_b64decode_leve_exception_et_fromhex_aussi(self):
        """b64decode lève, fromhex lève → False retourné sans crash."""
        with patch.object(ochecklist_views.base64, 'b64decode',
                          side_effect=ValueError('forced')):
            assert verify_content_digest(
                self.BODY, 'sha-256=invalid!!!'
            ) is False

    def test_exception_avant_decodage(self):
        """Exception inattendue dans la phase algo/hash → outer except."""
        with patch.object(ochecklist_views.hashlib, 'sha256',
                          side_effect=RuntimeError('forced')):
            assert verify_content_digest(
                self.BODY, 'sha-256=YWJjZA=='
            ) is False
