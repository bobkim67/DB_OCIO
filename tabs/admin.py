# -*- coding: utf-8 -*-
"""Tab 6: Admin — 전체 펀드 운용 현황 + 시장 코멘트 관리 (admin 전용).

render(ctx) 호출로 사용. ctx dict 필수 키:
  - FUND_META: 펀드 메타정보 dict
  - FUND_LIST: 대상 펀드코드 리스트
  - DB_CONNECTED: bool
  - cache: {'load_fund_summary': callable}
"""

import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

_PUBLISHED_DIR = Path(__file__).resolve().parent.parent / 'market_research' / 'data' / 'debate_published'
_PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
_NEWS_DIR = Path(__file__).resolve().parent.parent / 'market_research' / 'data' / 'news'

_TIER1 = {'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
          'CNBC', 'MarketWatch', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1'}
_TIER2_PARTIAL = {'SeekingAlpha', 'Benzinga', '매일경제', '한경', '서울경제',
                  '머니투데이', '이데일리', '조선비즈', '헤럴드경제'}

_METRICS_GUIDE = {
    '중요도(salience)': '기사 중요도 점수 (0~1). 매체등급 30% + 강도 25% + 교차보도 25% + BM이상치 20%로 산출',
    '전이경로 신뢰도': 'GraphRAG 인과추론 엣지의 신뢰도. 0.9 이상은 다수 기사에서 반복 확인된 인과 경로',
    '교차보도 N건': '동일 이벤트를 서로 다른 매체가 보도한 횟수. 많을수록 사실 신뢰도 높음',
    'BM 이상치': '해당 날짜에 벤치마크 수익률이 z-score 1.5 이상 급변한 경우 해당',
    '매체등급': 'TIER1(Reuters/Bloomberg/연합 등)=1.0, TIER2(SeekingAlpha/매경 등)=0.7, TIER3(기타)=0.3',
}


# ══════════════════════════════════════════
# 후처리: customer_comment 검증 + 정제
# ══════════════════════════════════════════

# 금지: "주어+실행동사" 패턴 (시장 설명 용어 자체는 허용)
_BANNED_PATTERNS = [
    r'당사[는은이가]?\s',
    r'본\s*펀드[는은이가]?\s',
    r'비중을\s*(확대|축소|유지)',
    r'비중(확대|축소)\s*(기조|방침|전략)',
    r'(헤지|hedge)\s*(수단을|를)\s*병행',
    r'듀레이션을\s*(축소|확대|조정|관리)',
    r'유동성\s*버퍼를?\s*(확보|구축)',
    r'운용\s*(전략|방침)[으로는]?\s',
    r'편입\s*(비중|비율)[을를]?\s*(조정|변경)',
    r'BM\s*대비\s*.*(추구|목표|초과)',
    r'대응\s*방침',
    r'기조를\s*유지',
    r'(할|나갈)\s*방침',
]

# 권고형/처방형 문장 패턴 (시장 설명은 허용, 실행 권고는 경고)
_ADVISORY_PATTERNS = [
    r'(줄일|늘릴|축소할|확대할|조정할)\s*필요가\s*있',
    r'(적절하다|적절합니다)',
    r'(바람직하다|바람직합니다)',
    r'(유효하다|유효합니다)',
    r'(유지하는\s*것이\s*좋|유지하는\s*것이\s*적절)',
    r'(권고한다|권고합니다|권장한다|권장합니다)',
    r'(대비할\s*필요|대응할\s*필요)',
    r'(강화하고|강화하며).*방침',
]

# ── 시제/불확실성 validator ──

_UNCERTAINTY_LEXICON = [
    '유력', '전망', '무게', '가능성', '관측', '예상', '시사',
    '검토', '논의', '가능', '우려', '추정', '잠정', '임시',
    '예정', '전해', '알려', '보도',
]

_CERTAINTY_PATTERNS = [
    r'동결한\s', r'동결했', r'동결됐', r'인상한\s', r'인하한\s',
    r'결정했', r'결정됐', r'확정됐', r'발표했', r'합의했',
    r'단행했', r'인상됐', r'인하됐', r'채택했', r'승인했',
]


def _validate_tense(comment: str, annotations: list) -> list[str]:
    """evidence가 불확실형인데 코멘트가 확정형이면 경고."""
    warnings = []
    if not annotations:
        return warnings

    # 문장 분리
    sentences = re.split(r'(?<=[.다])\s+', comment)

    for sent in sentences:
        # 이 문장이 확정형 패턴을 포함하는지
        certainty_match = None
        for pat in _CERTAINTY_PATTERNS:
            m = re.search(pat, sent)
            if m:
                certainty_match = m.group()
                break
        if not certainty_match:
            continue

        # 이 문장에 연결된 ref 번호 추출
        refs_in_sent = re.findall(r'\[ref:(\d+)\]', sent)
        # ref 없어도, 문장 키워드로 관련 evidence 찾기
        sent_lower = sent.lower()

        for ann in annotations:
            ref_idx = str(ann.get('ref', ''))
            title = ann.get('title', '')

            # ref가 직접 매칭되거나, 키워드 겹침이 있으면 검사
            is_linked = ref_idx in refs_in_sent
            if not is_linked:
                # 키워드 겹침으로 간접 연결 추정
                title_words = set(title.replace(',', ' ').replace('…', ' ').split())
                sent_words = set(sent.replace(',', ' ').replace('…', ' ').split())
                overlap = title_words & sent_words
                if len(overlap) < 2:
                    continue

            # evidence 제목에 불확실 표현이 있는지
            for unc in _UNCERTAINTY_LEXICON:
                if unc in title:
                    warnings.append(
                        f'시제 불일치: 코멘트 "{certainty_match}" ← '
                        f'evidence ref:{ref_idx} "{title[:50]}" (불확실: "{unc}")')
                    break

    return warnings


def _validate_ref_matching(comment: str, annotations: list) -> list[str]:
    """ref:N이 붙은 문장의 키워드와 해당 ref 기사 제목 키워드를 교차검증."""
    warnings = []
    if not annotations:
        return warnings

    ann_map = {str(a['ref']): a for a in annotations}

    # 문장 분리
    sentences = re.split(r'(?<=[.다])\s+', comment)

    # 주요 키워드 사전 (토픽별)
    _TOPIC_KEYWORDS = {
        '한국은행': ['한국은행', '한은', '금통위', '기준금리', '이창용', '동결', '인상', '인하'],
        '연준': ['연준', 'Fed', 'FOMC', '파월', '금리경로', '연방준비'],
        '유가': ['유가', 'WTI', '브렌트', '원유', 'oil', '배럴', 'OPEC'],
        '환율': ['환율', 'USDKRW', '원달러', '원·달러', '달러/원', 'DXY', '달러인덱스'],
        '휴전': ['휴전', '이란', 'Iran', '중동', '호르무즈', 'ceasefire'],
        '금': ['금값', '금가격', 'gold', 'Gold', '귀금속'],
        'IMF': ['IMF', '국제통화기금'],
        'KOSPI': ['KOSPI', '코스피', 'KOSDAQ', '코스닥'],
    }

    for sent in sentences:
        refs = re.findall(r'\[ref:(\d+)\]', sent)
        if not refs:
            continue

        # 문장의 토픽 키워드 탐지
        sent_topics = set()
        for topic, keywords in _TOPIC_KEYWORDS.items():
            for kw in keywords:
                if kw in sent:
                    sent_topics.add(topic)
                    break

        if not sent_topics:
            continue

        for ref_num in refs:
            ann = ann_map.get(ref_num)
            if not ann:
                continue
            title = ann.get('title', '')

            # ref 기사의 토픽 키워드 탐지
            ref_topics = set()
            for topic, keywords in _TOPIC_KEYWORDS.items():
                for kw in keywords:
                    if kw in title:
                        ref_topics.add(topic)
                        break

            # 겹침 검사
            if sent_topics and ref_topics and not (sent_topics & ref_topics):
                warnings.append(
                    f'ref 오매핑: 문장 토픽={sent_topics} ← '
                    f'ref:{ref_num} 토픽={ref_topics} '
                    f'"{title[:50]}"')

    return warnings

_INTERNAL_PATTERNS = [
    r'\[ref:\d+\]',           # evidence trace 태그
    r'살리언스\s*[\d.]+',      # 살리언스 0.925
    r'salience\s*[\d.]+',
    r'신뢰도\s*[\d.]+',        # 전이경로 신뢰도 0.956
    r'confidence\s*[\d.]+',
    r'교차보도\s*\d+건',        # 교차보도 23건
    r'evidence_ids?',
    r'F_[A-Z_]{3,}',          # F_USDKRW 등 내부 코드
]


def _sanitize_customer_comment(text: str, indicators: dict = None,
                               annotations: list = None) -> tuple[str, list[dict]]:
    """customer_comment 후처리. (정제된 텍스트, 구조화된 경고 목록) 반환.

    자동 제거: 내부 토큰, inline ref
    경고: structured metadata (type, ref_no, message)
    """
    warnings = []  # list[dict]
    annotations = annotations or []
    max_ref = len(annotations)

    def _warn(warn_type: str, message: str, ref_no: int = None, severity: str = 'warning'):
        w = {'type': warn_type, 'message': message, 'severity': severity}
        if ref_no is not None:
            w['ref_no'] = ref_no
        warnings.append(w)

    # ── A. ref 관련 검증 (자동제거 전에 실행) ──

    # 1. 시제/불확실성 검증
    tense_warnings = _validate_tense(text, annotations)
    for tw in tense_warnings:
        ref_match = re.search(r'ref:(\d+)', tw)
        ref_no = int(ref_match.group(1)) if ref_match else None
        _warn('tense_mismatch', tw, ref_no=ref_no)

    # 2. ref ↔ 문장 키워드 교차검증
    ref_warnings = _validate_ref_matching(text, annotations)
    for rw in ref_warnings:
        ref_match = re.search(r'ref:(\d+)', rw)
        ref_no = int(ref_match.group(1)) if ref_match else None
        _warn('ref_mismatch', rw, ref_no=ref_no)

    # 3. ref 범위/유효성 검증 — 존재하지 않는 ref 번호 탐지
    used_refs = [int(r) for r in re.findall(r'\[ref:(\d+)\]', text)]
    for r in used_refs:
        if r < 1 or r > max_ref:
            _warn('ref_invalid', f'존재하지 않는 ref:{r} (유효 범위: 1~{max_ref})', ref_no=r)

    # ── B. 자동 제거 ──

    # 4. 내부 토큰 제거 (ref 포함)
    for pat in _INTERNAL_PATTERNS:
        if re.search(pat, text):
            _warn('auto_remove', f'내부 지표 제거: {pat}', severity='info')
        text = re.sub(pat, '', text)

    # ── C. 텍스트 기반 경고 ──

    # 5. raw number 경고
    raw_nums = re.findall(r'[+\-]\d{3,}\.\d+', text)
    for rn in raw_nums:
        _warn('raw_number', f'단위 불명 숫자: {rn} — 서술형 치환 또는 제거 권장')

    # 6. 펀드 액션 패턴
    for pat in _BANNED_PATTERNS:
        match = re.search(pat, text)
        if match:
            _warn('fund_action', f'펀드 액션: "{match.group()}"')

    # 7. 권고형/처방형 문장
    for pat in _ADVISORY_PATTERNS:
        match = re.search(pat, text)
        if match:
            _warn('advisory', f'권고형 표현: "{match.group()}"')

    # 8. 역수익률곡선 검증
    if indicators:
        ust_2y = indicators.get('UST_2Y')
        ust_10y = indicators.get('UST_10Y')
        if ust_2y and ust_10y and float(ust_2y) < float(ust_10y):
            if '역수익률' in text or '역전' in text:
                _warn('fact_error',
                      f'2Y({ust_2y}) < 10Y({ust_10y})이면 정상 스프레드, 역전 아님')

    # ── 정리 ──
    text = re.sub(r'\s{2,}', ' ', text).strip()
    text = re.sub(r'\s+([.,])', r'\1', text)

    return text, warnings


def _source_tier(source: str) -> str:
    if source in _TIER1:
        return 'TIER1'
    for t2 in _TIER2_PARTIAL:
        if t2 in source:
            return 'TIER2'
    return 'TIER3'


def _salience_explanation(article: dict) -> str:
    """중요도 점수를 사람이 읽을 수 있는 설명으로 변환."""
    parts = []
    source = article.get('source', '')
    tier = _source_tier(source)
    parts.append(f'{tier} 매체({source})')

    intensity = 0
    for t in article.get('_classified_topics', []):
        intensity = max(intensity, t.get('intensity', 0))
    if intensity >= 7:
        parts.append(f'높은 강도({intensity}/10)')

    corr = article.get('_event_source_count', 0)
    if corr >= 2:
        parts.append(f'교차보도 {corr}건')

    if article.get('_bm_overlap'):
        parts.append('BM 이상치 날짜 해당')

    return ', '.join(parts) if parts else '일반 기사'


def _build_evidence_annotations(evidence_ids: list, year: int, months: list) -> list:
    """evidence_ids → 기사 메타 + URL + 중요도 설명 매핑."""
    # 해당 월 뉴스에서 article_id → article 인덱스
    id_map = {}
    for m in months:
        news_file = _NEWS_DIR / f'{year}-{m:02d}.json'
        if not news_file.exists():
            continue
        data = json.loads(news_file.read_text(encoding='utf-8'))
        for a in data.get('articles', []):
            aid = a.get('_article_id', '')
            if aid:
                id_map[aid] = a

    annotations = []
    for i, eid in enumerate(evidence_ids, 1):
        art = id_map.get(eid, {})
        sal = art.get('_event_salience', 0)
        annotations.append({
            'ref': i,
            'article_id': eid,
            'title': art.get('title', '(매핑 실패)')[:100],
            'url': art.get('url', ''),
            'source': art.get('source', ''),
            'date': art.get('date', ''),
            'topic': art.get('primary_topic', ''),
            'salience': round(sal, 3),
            'salience_explanation': _salience_explanation(art) if art else '',
        })
    return annotations


def render(ctx):
    """Admin 탭 렌더링."""
    FUND_META = ctx['FUND_META']
    FUND_LIST = ctx['FUND_LIST']
    DB_CONNECTED = ctx['DB_CONNECTED']
    cached_load_fund_summary = ctx['cache']['load_fund_summary']

    st.markdown("#### 전체 펀드 운용 현황")

    # DB 펀드 요약 로드 (fallback: FUND_META 기반 mockup)
    _tab6_db = False
    if DB_CONNECTED:
        try:
            _summary_df = cached_load_fund_summary(FUND_LIST)
            if not _summary_df.empty:
                _tab6_db = True
        except Exception as _e:
            st.toast(f"Admin DB 오류, 목업 사용: {_e}", icon="⚠️")

    if _tab6_db:
        st.caption(f"📡 DB 실데이터 | 기준일: {_summary_df['기준일자'].max().strftime('%Y-%m-%d')}")
        all_funds = pd.DataFrame()
        all_funds['펀드코드'] = _summary_df['FUND_CD']
        all_funds['펀드명'] = _summary_df['FUND_CD'].map(
            lambda x: FUND_META.get(x, {}).get('short', x)
        )
        all_funds['AUM(억)'] = _summary_df['AUM_억'].round(1)
        all_funds['기준가'] = _summary_df['MOD_STPR'].round(2)
        if 'DD1_ERN_RT' in _summary_df.columns:
            _ern = pd.to_numeric(_summary_df['DD1_ERN_RT'].apply(lambda x: float(x) if x is not None else None), errors='coerce')
            all_funds['전일수익률(%)'] = (_ern * 100).round(4)
        else:
            all_funds['전일수익률(%)'] = 0.0
        all_funds['그룹'] = _summary_df['FUND_CD'].map(
            lambda x: FUND_META.get(x, {}).get('group', '기타')
        )
        all_funds['MP'] = _summary_df['FUND_CD'].map(
            lambda x: 'O' if FUND_META.get(x, {}).get('has_mp', False) else 'X'
        )
        all_funds['듀레이션'] = _summary_df['FUND_DUR'].round(2) if 'FUND_DUR' in _summary_df.columns else '-'
    else:
        all_funds = pd.DataFrame([
            {'펀드코드': k, '펀드명': v['short'], 'AUM(억)': v['aum'],
             '그룹': v['group'],
             'YTD': f"{np.random.uniform(-1, 5):.2f}%",
             'BM대비': f"{np.random.uniform(-0.5, 1.5):+.2f}%p",
             'MP': 'O' if v['has_mp'] else 'X',
             'MP Gap': np.random.choice(['적정', 'Over', 'Under'], p=[0.6, 0.2, 0.2]) if v['has_mp'] else '-'}
            for k, v in FUND_META.items()
        ])

    all_funds = all_funds.sort_values('AUM(억)', ascending=False)
    st.dataframe(all_funds, hide_index=True, width="stretch", height=500)

    st.markdown("---")
    col_a1, col_a2 = st.columns(2)
    with col_a1:
        st.markdown("#### AUM 분포")
        fig_aum = px.treemap(all_funds, path=['그룹', '펀드명'], values='AUM(억)',
                              color='AUM(억)', color_continuous_scale='Blues')
        fig_aum.update_layout(height=400, margin=dict(t=30, b=10))
        st.plotly_chart(fig_aum, width="stretch")

    with col_a2:
        st.markdown("#### 그룹별 AUM")
        group_aum = all_funds.groupby('그룹')['AUM(억)'].sum().sort_values(ascending=True)
        fig_group = go.Figure(go.Bar(
            x=group_aum.values, y=group_aum.index,
            orientation='h', marker_color='#636EFA',
            text=[f"{v:,.0f}억" for v in group_aum.values], textposition='outside'
        ))
        fig_group.update_layout(height=400, margin=dict(t=30, l=100), xaxis_title='AUM (억원)')
        st.plotly_chart(fig_group, width="stretch")

    # ══════════════════════════════════════════
    # 시장 코멘트 관리
    # ══════════════════════════════════════════
    st.markdown("---")
    st.markdown("#### 시장 코멘트 관리")

    col_mode, col_year, col_period = st.columns([1, 1, 1])
    with col_mode:
        mode = st.radio("기간 유형", ["월별", "분기"], horizontal=True, key="admin_debate_mode")
    with col_year:
        year = st.number_input("년도", min_value=2025, max_value=2030,
                               value=datetime.now().year, key="admin_debate_year")
    with col_period:
        if mode == "월별":
            month = st.number_input("월", min_value=1, max_value=12,
                                    value=datetime.now().month, key="admin_debate_month")
            period_key = f"{year}-{month:02d}"
        else:
            quarter = st.number_input("분기", min_value=1, max_value=4,
                                      value=(datetime.now().month - 1) // 3 + 1,
                                      key="admin_debate_quarter")
            period_key = f"{year}-Q{quarter}"

    # 기존 발행본 로드
    pub_file = _PUBLISHED_DIR / f"{period_key}.json"
    existing = None
    if pub_file.exists():
        existing = json.loads(pub_file.read_text(encoding='utf-8'))

    col_gen, col_status = st.columns([1, 2])
    with col_gen:
        generate = st.button("코멘트 생성 (debate)", key="admin_gen_debate",
                             type="primary", use_container_width=True)
    with col_status:
        if existing:
            debated = existing.get('debated_at', '?')
            edited = existing.get('edited_at', '')
            status_text = f"생성: {debated}"
            if edited:
                status_text += f" | 최종수정: {edited}"
            st.success(status_text)
        else:
            st.info("발행본 없음 — '코멘트 생성' 버튼으로 debate를 실행하세요")

    # ── debate 생성 ──
    if generate:
        with st.spinner("4인 debate 실행 중... (1~2분 소요)"):
            try:
                if mode == "월별":
                    from market_research.report.debate_engine import run_market_debate
                    result = run_market_debate(year, month)
                else:
                    from market_research.report.debate_engine import run_quarterly_debate
                    result = run_quarterly_debate(year, quarter)

                synthesis = result.get('synthesis', {})
                raw_comment = synthesis.get('customer_comment', '')
                evidence_ids = result.get('_evidence_ids', [])

                # evidence annotations 빌드
                annotations = _build_evidence_annotations(
                    evidence_ids, year, months=result.get('months') or [month])

                # customer_comment 후처리 (내부지표 제거 + 금지표현 + 시제 + ref 검증)
                clean_comment, sanitize_warnings = _sanitize_customer_comment(
                    raw_comment, annotations=annotations)

                pub_data = {
                    'period': period_key,
                    'debated_at': result.get('debated_at', ''),
                    'customer_comment': clean_comment,
                    'admin_comment': raw_comment,
                    'admin_summary': synthesis.get('admin_summary', ''),
                    'consensus_points': synthesis.get('consensus_points', []),
                    'disagreements': synthesis.get('disagreements', []),
                    'tail_risks': synthesis.get('tail_risks', []),
                    'evidence_annotations': annotations,
                    'internal_metrics_guide': _METRICS_GUIDE,
                    '_sanitize_warnings': sanitize_warnings,
                }
                pub_file.write_text(
                    json.dumps(pub_data, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                existing = pub_data
                st.success(f"debate 완료 + 저장 (생성: {pub_data.get('debated_at', '')})")
                st.rerun()
            except Exception as exc:
                st.error(f"debate 실패: {exc}")

    # ── 수정/저장 UI ──
    if existing:
        st.markdown("---")
        st.markdown("##### Admin Summary")
        st.caption(existing.get('admin_summary', ''))

        with st.expander("합의 / 쟁점 / 테일리스크", expanded=False):
            st.markdown("**합의**")
            for p in existing.get('consensus_points', []):
                st.markdown(f"- {p}")
            st.markdown("**쟁점**")
            for d in existing.get('disagreements', []):
                if isinstance(d, dict):
                    st.markdown(f"**[{d.get('topic', '')}]**")
                    for role in ('bull', 'bear', 'quant', 'monygeek'):
                        if d.get(role):
                            st.caption(f"  {role}: {d[role]}")
            st.markdown("**테일 리스크**")
            for t in existing.get('tail_risks', []):
                st.markdown(f"- {t}")

        # ── 내부 지표 가이드 ──
        guide = existing.get('internal_metrics_guide', _METRICS_GUIDE)
        if guide:
            with st.expander("내부 지표 가이드", expanded=False):
                for k, v in guide.items():
                    st.markdown(f"**{k}**: {v}")

        # ── Customer Comment 수정 ──
        st.markdown("##### Customer Comment (수정 가능)")
        # admin_comment(ref 포함)이 있으면 첨자 변환, 없으면 customer_comment
        admin_raw = existing.get('admin_comment', '')
        if admin_raw:
            comment_text = re.sub(r'\[ref:(\d+)\]', r' \1)', admin_raw)
        else:
            comment_text = existing.get('customer_comment', '')

        # 줄바꿈이 없는 줄글이면 문단 자동 분리
        if comment_text and '\n' not in comment_text:
            sentences = re.split(r'(?<=[.다])\s+', comment_text)
            chunk_size = max(3, len(sentences) // 4)
            paragraphs = []
            for i in range(0, len(sentences), chunk_size):
                paragraphs.append(' '.join(sentences[i:i + chunk_size]))
            comment_text = '\n\n'.join(paragraphs)

        # 키에 debated_at 포함 → 재생성 시 자동 갱신
        ta_key = f"admin_comment_edit_{existing.get('debated_at', '')}"
        edited = st.text_area(
            "코멘트 수정",
            value=comment_text,
            height=400,
            key=ta_key,
            label_visibility="collapsed",
        )

        if st.button("저장", key="admin_save_comment", type="primary"):
            existing['customer_comment'] = edited
            existing['edited_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            pub_file.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            st.success(f"저장 완료: {pub_file.name}")

        # 출처 목록 (저장 버튼 아래) — 경고 ref에 ⚠️ 표시
        annotations = existing.get('evidence_annotations', [])
        sw_list = existing.get('_sanitize_warnings', [])

        # structured warnings에서 문제 있는 ref_no 추출
        warn_refs = {}  # ref_no → [warning messages]
        for w in sw_list:
            if isinstance(w, dict) and w.get('ref_no') is not None:
                rn = w['ref_no']
                warn_refs.setdefault(rn, []).append(w.get('message', w.get('type', '')))

        if annotations:
            st.markdown('---')
            st.markdown('**출처**')
            for ann in annotations:
                ref = ann.get('ref', '')
                title = ann.get('title', '')
                source = ann.get('source', '')
                date = ann.get('date', '')
                url = ann.get('url', '')
                sal = ann.get('salience', 0)
                expl = ann.get('salience_explanation', '')

                # 경고 여부
                ref_warns = warn_refs.get(ref, [])
                warn_icon = ' ⚠️' if ref_warns else ''

                if url:
                    st.caption(
                        f'[ref:{ref}]{warn_icon} [{title}]({url}) — {source}, {date} '
                        f'| 중요도 {sal:.2f} ({expl})')
                else:
                    st.caption(
                        f'[ref:{ref}]{warn_icon} {title} — {source}, {date} '
                        f'| 중요도 {sal:.2f} ({expl})')

                # 경고 상세
                for wm in ref_warns:
                    st.caption(f'&emsp;&emsp;⚠️ {wm}')
