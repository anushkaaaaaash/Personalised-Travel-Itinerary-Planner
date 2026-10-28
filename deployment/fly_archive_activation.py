"""Offline activation gate for separately verified account archive migrations.

This checks an operator attestation and exact reviewed SQL identity, not hosted
database state. Hosted owner/RLS/grant checks must precede that attestation.
"""
import hashlib
import os
from pathlib import Path
import re

SQL = Path(__file__).resolve().parents[1] / 'docs/adaptive_saved_archive_REVIEW_ONLY.sql'


def verify(action, confirmed, verified_sha, *, sql_path=SQL):
    if action not in {'stage', 'upgrade', 'activate'}:
        raise ValueError('Unknown deployment action')
    if action != 'activate':
        return
    if confirmed != 'true':
        raise ValueError('Separate archive migration verification is required')
    if type(verified_sha) is not str or not re.fullmatch(r'[0-9a-f]{64}', verified_sha):
        raise ValueError('Exact reviewed archive SQL identity is required')
    if sql_path.is_symlink() or not sql_path.is_file():
        raise ValueError('Reviewed archive SQL is unavailable')
    if hashlib.sha256(sql_path.read_bytes()).hexdigest() != verified_sha:
        raise ValueError('Verified archive SQL does not match this release')


def main():
    try:
        verify(os.getenv('DEPLOYMENT_ACTION', ''), os.getenv('SAVED_ARCHIVE_SCHEMA_VERIFIED', ''),
               os.getenv('VERIFIED_SAVED_ARCHIVE_SQL_SHA256', ''))
    except Exception:
        print('Account archive activation verification is missing or does not match this release; stopped.')
        return 1
    print('Offline account archive activation gate passed; hosted verification remains an operator prerequisite.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
