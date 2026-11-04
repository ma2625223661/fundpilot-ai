"""Persistent, bounded evidence-result reuse and paid-request replay protection.

Only fingerprints and validated result values belong here. Request evidence,
credentials and HTTP payloads are never written to this database.
"""
import hashlib
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


CACHE_TTL_SECONDS = 24 * 60 * 60
RETRY_COOLDOWN_SECONDS = 30 * 60
MAX_CACHE_ENTRIES = 10000
MAX_RESULT_BYTES = 65536
_CHINA = timezone(timedelta(hours=8))
_KINDS = re.compile(r'[A-Za-z0-9:_-]{1,64}\Z')
_FINGERPRINT = re.compile(r'[0-9a-f]{64}\Z')
_COLLECTION_FIELDS = frozenset(('fetched_at', 'observed_at', 'checked_at', 'calculated_at', 'revision'))


def _semantic_value(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in _COLLECTION_FIELDS:
                continue
            if key == 'as_of' and isinstance(item, str) and 'T' in item:
                # Preserve the evidence day while ignoring within-day collection
                # clocks. Financial publication dates and quote trade dates use
                # other field names and remain entirely unchanged.
                try:
                    datetime.fromisoformat(item.replace('Z', '+00:00'))
                    item = item[:10]
                except ValueError:
                    pass
            result[key] = _semantic_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_semantic_value(item) for item in value]
    return value


def semantic_fingerprint(model, system, payload):
    """Hash effective evidence, model and prompt; never serialize it to disk.

    List ordering stays significant: a changed priority/selection order must
    not accidentally reuse a result for a different requested sample.
    """
    material = {'model': model, 'system': system, 'evidence': _semantic_value(payload)}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True,
                         allow_nan=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


class AIEvidenceCache:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or time.time

    def _now(self):
        value = self.clock()
        if isinstance(value, datetime):
            value = value.replace(tzinfo=_CHINA) if value.tzinfo is None else value
            value = value.timestamp()
        value = float(value)
        if not math.isfinite(value):
            raise ValueError('Invalid cache clock')
        return value

    @staticmethod
    def _valid(kind, fingerprint):
        return (isinstance(kind, str) and _KINDS.fullmatch(kind) is not None
                and isinstance(fingerprint, str) and _FINGERPRINT.fullmatch(fingerprint) is not None)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute('PRAGMA busy_timeout=10000')
            db.execute('''CREATE TABLE IF NOT EXISTS evidence_results (
                kind TEXT NOT NULL, fingerprint TEXT NOT NULL,
                created REAL NOT NULL, result TEXT NOT NULL,
                PRIMARY KEY(kind,fingerprint))''')
            db.execute('''CREATE TABLE IF NOT EXISTS evidence_attempts (
                kind TEXT NOT NULL, fingerprint TEXT NOT NULL, attempted REAL NOT NULL,
                PRIMARY KEY(kind,fingerprint))''')
            return db
        except Exception:
            db.close()
            raise

    def get(self, kind, fingerprint):
        """Return a detached validated result and original time, or a cache miss."""
        if not self._valid(kind, fingerprint):
            return None
        db = None
        try:
            now = self._now()
            db = self._connect()
            row = db.execute('SELECT created,result FROM evidence_results WHERE kind=? AND fingerprint=?',
                             (kind, fingerprint)).fetchone()
            if row is None or not 0 <= now - row[0] < CACHE_TTL_SECONDS:
                return None
            if len(row[1].encode('utf-8')) > MAX_RESULT_BYTES:
                return None
            value = json.loads(row[1])
            if not isinstance(value, dict):
                return None
            return {'value': value,
                    'created_at': datetime.fromtimestamp(row[0], _CHINA).isoformat(timespec='seconds')}
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError):
            return None
        finally:
            if db is not None:
                db.close()

    def put(self, kind, fingerprint, value):
        """Save an already validated result; a failed cache write is nonfatal."""
        if not self._valid(kind, fingerprint) or not isinstance(value, dict):
            return False
        db = None
        try:
            result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            if len(result.encode('utf-8')) > MAX_RESULT_BYTES:
                return False
            now = self._now()
            db = self._connect()
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR REPLACE INTO evidence_results VALUES (?,?,?,?)',
                       (kind, fingerprint, now, result))
            self._cleanup(db, now)
            db.commit()
            return True
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError):
            if db is not None:
                db.rollback()
            return False
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _cleanup(db, now):
        db.execute('DELETE FROM evidence_results WHERE created<=? OR created>?',
                   (now - CACHE_TTL_SECONDS, now))
        db.execute('''DELETE FROM evidence_results WHERE rowid NOT IN
            (SELECT rowid FROM evidence_results ORDER BY created DESC,rowid DESC LIMIT ?)''',
                   (MAX_CACHE_ENTRIES,))
        db.execute('DELETE FROM evidence_attempts WHERE attempted<=? OR attempted>?',
                   (now - CACHE_TTL_SECONDS, now))
        db.execute('''DELETE FROM evidence_attempts WHERE rowid NOT IN
            (SELECT rowid FROM evidence_attempts ORDER BY attempted DESC,rowid DESC LIMIT ?)''',
                   (MAX_CACHE_ENTRIES,))

    def recent_attempt(self, kind, fingerprint, seconds=RETRY_COOLDOWN_SECONDS):
        """Fail closed when attempt state cannot be read, preventing paid replay."""
        if not self._valid(kind, fingerprint):
            return True
        db = None
        try:
            seconds = float(seconds)
            if not math.isfinite(seconds) or not 0 < seconds <= CACHE_TTL_SECONDS:
                return True
            now = self._now()
            db = self._connect()
            row = db.execute('SELECT attempted FROM evidence_attempts WHERE kind=? AND fingerprint=?',
                             (kind, fingerprint)).fetchone()
            return bool(row is not None and (now < row[0] or now - row[0] < seconds))
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError):
            return True
        finally:
            if db is not None:
                db.close()

    def mark_attempt(self, kind, fingerprint, seconds=RETRY_COOLDOWN_SECONDS):
        """Atomically reserve an imminent send; False means it must not be sent.

        This is deliberately stronger than a separate recent_attempt/check:
        concurrent workers or separate processes cannot reserve the same
        fingerprint twice during the cooldown. A crash after reservation may
        skip a call, but cannot replay an uncertain paid request immediately.
        """
        if not self._valid(kind, fingerprint):
            return False
        db = None
        try:
            seconds = float(seconds)
            if not math.isfinite(seconds) or not 0 < seconds <= CACHE_TTL_SECONDS:
                return False
            now = self._now()
            db = self._connect()
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT attempted FROM evidence_attempts WHERE kind=? AND fingerprint=?',
                             (kind, fingerprint)).fetchone()
            if row is not None and (now < row[0] or now - row[0] < seconds):
                db.rollback()
                return False
            db.execute('INSERT OR REPLACE INTO evidence_attempts VALUES (?,?,?)',
                       (kind, fingerprint, now))
            self._cleanup(db, now)
            db.commit()
            return True
        except (OSError, sqlite3.Error, TypeError, ValueError, OverflowError):
            if db is not None:
                db.rollback()
            return False
        finally:
            if db is not None:
                db.close()
