# -*- coding: utf-8 -*-
"""DB 접속 + SCIP blob 파싱 — 단일 소스"""

import json
import os
from pathlib import Path

import pymysql

# 시크릿은 repo 루트 .env (배포 하드닝 2026-07-09, .env.example 참조)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
except ImportError:
    pass

DB_CONFIG = dict(
    host=os.environ.get('OCIO_DB_HOST', '192.168.195.55'),
    user=os.environ.get('OCIO_DB_USER', 'solution'),
    password=os.environ.get('OCIO_DB_PASSWORD', ''),
    charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
)


def get_conn(db='SCIP'):
    """MariaDB 접속 (SCIP / dt / solution / cream)"""
    if not DB_CONFIG['password']:
        raise RuntimeError('OCIO_DB_PASSWORD 미설정 — repo 루트 .env 확인 (.env.example 참조)')
    return pymysql.connect(db=db, **DB_CONFIG)


def parse_blob(blob, blob_key=None):
    """SCIP back_datapoint.data blob 파싱.

    3가지 형태:
      {"USD": 608.66, "KRW": 868066.70}  → dict 또는 blob_key 값
      2451.187912                          → float
      "13.06"                              → float
    """
    if isinstance(blob, (bytes, bytearray)):
        s = blob.decode('utf-8')
    else:
        s = str(blob)
    s = s.strip()
    if s.startswith('{'):
        obj = json.loads(s)
        if isinstance(obj, dict):
            if blob_key:
                return float(obj.get(blob_key, obj.get(list(obj.keys())[0])))
            return {k: float(v) for k, v in obj.items()}
    try:
        return float(s.replace(',', '').replace('"', ''))
    except Exception:
        return None
