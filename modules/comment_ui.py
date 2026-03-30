# -*- coding: utf-8 -*-
"""
운용보고 코멘트 생성 UI — report_cli.py 로직의 Streamlit 구현
render_comment_tab() 호출로 사용
"""
import sys
import json
from pathlib import Path

if sys.stdout and sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

_PYTHON_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PYTHON_ROOT))

import streamlit as st
import anthropic

_ENGINE_LOADED = False
try:
    from market_research.comment_engine import (
        load_benchmark_returns, load_all_pa_attributions, load_fund_return,
        load_fund_holdings_summary, load_digest, _build_llm_prompt,
        load_pa_by_item,
        FUND_CONFIGS, ANTHROPIC_API_KEY,
    )
    _ENGINE_LOADED = True
except Exception as e:
    _ENGINE_LOAD_ERR = str(e)

def _search_news_vectordb(month_str, asset_class, contrib, top_k=5):
    """뉴스 벡터DB 검색 — 당월 우선, 부족하면 익월 fallback"""
    from market_research.news_vectordb import search_for_factors, _get_collection
    results = search_for_factors(month_str, asset_class, contrib, top_k=top_k)

    # 결과 부족하면 익월도 검색
    if len(results) < 3:
        y, m = int(month_str[:4]), int(month_str[5:7])
        next_m = m + 1 if m < 12 else 1
        next_y = y if m < 12 else y + 1
        next_month = f'{next_y}-{next_m:02d}'
        next_col = _get_collection(next_month)
        if next_col.count() > 0:
            extra = search_for_factors(next_month, asset_class, contrib, top_k=top_k)
            seen = set(r['title'][:40] for r in results)
            for r in extra:
                if r['title'][:40] not in seen:
                    results.append(r)
                    seen.add(r['title'][:40])
                if len(results) >= top_k:
                    break

    return results


# ═══════════════════════════════════════════════════════
# 토픽 → 자산군 매핑
# ═══════════════════════════════════════════════════════

TOPIC_ASSET_MAP = {
    'AI_반도체': ['해외주식', '국내주식'],
    '금리': ['국내채권', '해외채권'],
    '달러': ['해외주식', '원자재'],
    '한국_원화': ['국내주식'],
    '유가_에너지': ['원자재'],
    '금': ['원자재'],
    '관세': ['해외주식', '국내주식'],
    '물가': ['국내채권', '해외채권'],
    '미국채': ['해외채권'],
    '엔화_캐리': ['해외주식'],
    '중국_위안화': ['해외주식'],
    '유럽_ECB': ['해외채권', '해외주식'],
    '유로달러': ['해외채권'],
    '부동산': ['원자재'],
    '안전자산': ['해외채권', '원자재'],
}


# ═══════════════════════════════════════════════════════
# 팩터 추출
# ═══════════════════════════════════════════════════════

def _extract_blog_factors(digest, asset_class, global_seen):
    """블로그 digest에서 팩터 추출 (글로벌 중복 제거 + Haiku 적절성 필터)"""
    if not digest:
        return []
    raw = []
    for topic, mapped in TOPIC_ASSET_MAP.items():
        if asset_class not in mapped:
            continue
        info = digest.get('topics', {}).get(topic)
        if not info:
            continue
        for item in info.get('key_events', []) + info.get('key_claims', []):
            if 20 < len(item) < 120:
                if any(x in item for x in ['🚨', '🔴', '🛑', '🦋', '|게시판', '여러분', '드립니다']):
                    continue
                if len(item) < 25 and item[:10].replace('/', '').replace(' ', '').replace(':', '').isdigit():
                    continue
                if item.endswith('?'):
                    continue
                raw.append((item, topic))

    # 키워드 중복 제거
    deduped = []
    for item, topic in raw:
        kw = set(w for w in item.split() if len(w) >= 3)
        if kw:
            overlap = len(kw & global_seen) / max(len(kw), 1)
            if overlap > 0.4:
                continue
        global_seen.update(kw)
        deduped.append(item)
        if len(deduped) >= 8:
            break

    if not deduped:
        return []

    # Haiku 적절성 필터: "이 문장이 {자산군} 수익률 원인으로 운용보고서에 쓸 수 있는가?"
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        fl = '\n'.join(f'{i+1}. {f}' for i, f in enumerate(deduped))
        prompt = f"""다음 문장들이 "{asset_class}" 자산군의 월간 수익률 등락 원인으로 운용보고서에 사용 가능한지 판단하세요.

후보:
{fl}

각 문장에 대해:
- 1 = 이 자산군 수익률의 직접/간접 원인으로 사용 가능한 시장 이벤트
- 0 = 다른 자산군 얘기, 블로그 감상/비유/역사적 사례, 또는 운용보고서에 부적절

JSON 배열만 응답. [{len(deduped)}개]"""

        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=100,
            messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text.strip()
        s, e = text.find('['), text.rfind(']') + 1
        if s >= 0 and e > s:
            flags = json.loads(text[s:e])
            if len(flags) == len(deduped):
                return [f for f, flag in zip(deduped, flags) if flag == 1][:4]
    except Exception:
        pass

    return deduped[:4]


def _extract_indicator_factors(bm_returns, asset_class):
    """지표 기반 팩터"""
    factors = []
    dxy = bm_returns.get('DXY', {}).get('return')
    gold = bm_returns.get('Gold', {}).get('return')
    wti = bm_returns.get('WTI', {}).get('return')
    usdkrw = bm_returns.get('USDKRW', {}).get('return')
    growth = bm_returns.get('미국성장주', {}).get('return')
    value = bm_returns.get('미국가치주', {}).get('return')
    sp500 = bm_returns.get('S&P500', {}).get('return')
    kospi = bm_returns.get('KOSPI', {}).get('return')
    us_bond = bm_returns.get('미국종합채권', {}).get('return')
    kr_bond = bm_returns.get('매경채권국채3년', {}).get('return')
    em = bm_returns.get('신흥국주식', {}).get('return')
    dm_exus = bm_returns.get('미국외선진국', {}).get('return')

    if asset_class == '해외주식':
        if dxy and abs(dxy) > 0.3:
            factors.append(f'달러 {"강세" if dxy > 0 else "약세"} DXY {dxy:+.1f}%')
        if growth and value and abs(growth - value) > 1:
            factors.append(f'성장주({growth:+.1f}%) vs 가치주({value:+.1f}%) 스타일 차별화')
        if em and sp500 and em > sp500 + 2:
            factors.append(f'신흥국 상대 강세 EM {em:+.1f}% vs S&P {sp500:+.1f}%')
        if dm_exus and sp500 and dm_exus > sp500 + 2:
            factors.append(f'선진국(ex-US) 상대 강세 {dm_exus:+.1f}%')
    elif asset_class == '국내주식':
        if kospi and abs(kospi) > 2:
            factors.append(f'KOSPI {"강세" if kospi > 0 else "약세"} {kospi:+.1f}%')
        if usdkrw and abs(usdkrw) > 1:
            factors.append(f'원화 {"약세" if usdkrw > 0 else "강세"} USD/KRW {usdkrw:+.1f}%')
    elif asset_class == '국내채권':
        if kr_bond and abs(kr_bond) > 0.1:
            factors.append(f'국내 채권지수 {kr_bond:+.2f}%')
    elif asset_class == '해외채권':
        if us_bond and abs(us_bond) > 0.3:
            factors.append(f'미국 종합채권 {us_bond:+.2f}%')
    elif asset_class == '원자재':
        if gold and abs(gold) > 0.5:
            factors.append(f'금 {gold:+.1f}%')
        if wti and abs(wti) > 1:
            factors.append(f'WTI {wti:+.1f}%')
        if dxy and gold and dxy > 0.3 and gold < -0.3:
            factors.append(f'달러 강세({dxy:+.1f}%) → 원자재 약세')
    return factors


def _llm_summarize_factors(asset_class, contrib, raw_factors, bm_returns):
    """Haiku로 raw 팩터 중복 합치고 최대 3개 요약문 반환. 소스에 없으면 빈 배열."""
    if not raw_factors:
        return []
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        bm_parts = []
        for n in ['S&P500', '미국성장주', '미국가치주', 'KOSPI', 'DXY', 'USDKRW',
                   '매경채권국채3년', '미국종합채권', 'Gold', 'WTI']:
            r = bm_returns.get(n, {}).get('return')
            if r is not None:
                bm_parts.append(f'{n}:{r:+.1f}%')

        fl = '\n'.join(f'- {f}' for f in raw_factors)
        prompt = f"""당신은 운용보고서 팩터 분석가입니다.

자산군: {asset_class}
월간 기여도: {contrib:+.2f}%
벤치마크: {', '.join(bm_parts)}

아래는 블로그, 뉴스, 지표에서 수집한 raw 소스입니다:
{fl}

규칙:
1. 비슷한 내용을 합쳐 중복 제거 후, "{asset_class}"의 수익률 등락 원인을 최대 3개 요약.
2. 각 팩터는 한국어 1문장 (30~60자), 간결하게.
3. 반드시 위 소스에 근거한 내용만 작성. 소스에 없는 내용을 만들어내지 마세요.
4. "{asset_class}"과 직접 관련 없는 소스(다른 자산군 얘기, 블로그 감상/비유)는 무시.
5. 소스가 전부 "{asset_class}"과 무관하면 빈 배열 []을 반환.
6. 추천도: 직접 원인=8~10, 배경=5~7.

JSON만 응답: [{{"text": "...", "score": N}}, ...]
최대 3개. 적절한 소스 없으면 []."""

        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=500,
            messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text.strip()
        s, e = text.find('['), text.rfind(']') + 1
        if s >= 0 and e > s:
            items = json.loads(text[s:e])
            if isinstance(items, list):
                return items[:3]
        return []
    except Exception as e:
        import traceback
        _log = Path(__file__).resolve().parent.parent.parent / 'market_research' / 'output' / 'debug_haiku.log'
        with open(_log, 'w', encoding='utf-8') as f:
            f.write(f'에러: {e}\n')
            f.write(traceback.format_exc())
        return []  # fallback도 빈 배열 — hallucination 방지


# ═══════════════════════════════════════════════════════
# 메인 렌더
# ═══════════════════════════════════════════════════════

@st.fragment
def render_comment_tab():
    """운용보고 탭 전체 UI (fragment로 탭 이동 방지)"""

    if not _ENGINE_LOADED:
        st.error(f"comment_engine 로드 실패: {_ENGINE_LOAD_ERR}")
        return

    st.markdown("#### 운용보고 코멘트 생성")

    # ── 선택기 ──
    sel_cols = st.columns([1, 1, 2, 1])
    with sel_cols[0]:
        c_year = st.selectbox("연도", [2026, 2025, 2024], key='cmt_year')
    with sel_cols[1]:
        c_month = st.selectbox("월", list(range(1, 13)), index=1, key='cmt_month')
    with sel_cols[2]:
        fund_opts = list(FUND_CONFIGS.keys())
        c_fund = st.selectbox("펀드", fund_opts, key='cmt_fund')
    with sel_cols[3]:
        cfg = FUND_CONFIGS[c_fund]
        st.markdown(f"**포맷 {cfg['format']}**")
        if cfg.get('target_return'):
            st.caption(f"목표 연 {cfg['target_return']:.0f}%")

    st.markdown("---")

    # ── Step 1: 팩터 분석 ──
    _LOG_FILE = Path(__file__).resolve().parent.parent.parent / 'market_research' / 'output' / 'debug_comment.log'

    with st.form(key='cmt_analyze_form'):
        analyze_submitted = st.form_submit_button("팩터 분석 실행", type='primary')

    if analyze_submitted:
        with st.spinner('데이터 로딩 + Haiku 랭킹 중...'), open(_LOG_FILE, 'w', encoding='utf-8') as _dbg:
            bm = load_benchmark_returns(c_year, c_month)
            pa_all = load_all_pa_attributions([c_fund], c_year, c_month)
            pa = pa_all.get(c_fund, {})
            fund_ret = load_fund_return(c_fund, c_year, c_month)
            holdings = load_fund_holdings_summary(c_fund, c_year, c_month)
            digest = load_digest(c_year, c_month)
            next_m = 1 if c_month == 12 else c_month + 1
            next_y = c_year + 1 if c_month == 12 else c_year
            next_digest = load_digest(next_y, next_m)

            # 팩터 후보 생성
            global_seen = set()
            factor_data = {}
            for ac in ['국내주식', '해외주식', '국내채권', '해외채권', '원자재']:
                contrib = pa.get(ac, 0)
                weight = holdings.get(ac, 0)
                if abs(contrib) < 0.05 and weight < 1:
                    continue

                blog_f = _extract_blog_factors(digest, ac, global_seen)
                ind_f = _extract_indicator_factors(bm, ac)

                # 뉴스 RAG (벡터DB 검색)
                news_f = []
                try:
                    month_str = f'{c_year}-{c_month:02d}'
                    _dbg.write(f'[{ac}] 뉴스 검색 시작: month={month_str}, contrib={contrib:+.2f}\n')
                    news_results = _search_news_vectordb(month_str, ac, contrib, top_k=5)
                    _dbg.write(f'[{ac}] 뉴스 검색 결과: {len(news_results)}건\n')
                    for nr in news_results:
                        _dbg.write(f'  → {nr["title"][:60]}\n')
                    news_seen = set()
                    for nr in news_results:
                        title = nr['title']
                        if any(title[:30] in f for f in blog_f + ind_f):
                            continue
                        prefix = title[:40]
                        if prefix in news_seen:
                            continue
                        news_seen.add(prefix)
                        src_tag = nr.get('source', '')
                        news_f.append(f'{title} ({src_tag})')
                        if len(news_f) >= 4:
                            break
                except Exception as _news_err:
                    import traceback
                    _dbg.write(f'[{ac}] 뉴스 에러: {_news_err}\n')
                    _dbg.write(traceback.format_exc() + '\n')
                    st.toast(f"뉴스 검색 오류: {_news_err}", icon="⚠️")

                all_f = blog_f + news_f + ind_f
                _dbg.write(f'[{ac}] 합계: 블로그={len(blog_f)}, 뉴스={len(news_f)}, 지표={len(ind_f)}\n')
                _dbg.flush()
                if not all_f:
                    continue

                # Haiku로 중복 합치고 3개 요약
                summarized = _llm_summarize_factors(ac, contrib, all_f, bm)
                _dbg.write(f'[{ac}] 요약 결과: {len(summarized)}개\n')
                for item in summarized:
                    _dbg.write(f'  → ({item.get("score",0)}점) {item.get("text","")}\n')

                items = []
                for item in summarized:
                    score = item.get('score', 5)
                    starred = '★★' if score >= 8 else '★' if score >= 6 else ''
                    items.append({
                        'text': item.get('text', ''),
                        'score': score,
                        'starred': starred,
                        'source': '종합',
                        'recommended': score >= 6,
                    })
                factor_data[ac] = {'contrib': contrib, 'weight': weight, 'items': items, 'has_source': len(items) > 0}

            # session_state에 저장
            st.session_state['cmt_bm'] = bm
            st.session_state['cmt_pa'] = pa
            st.session_state['cmt_pa_items'] = load_pa_by_item(c_fund, c_year, c_month)
            st.session_state['cmt_fund_ret'] = fund_ret
            st.session_state['cmt_holdings'] = holdings
            st.session_state['cmt_digest'] = digest
            st.session_state['cmt_next_digest'] = next_digest
            st.session_state['cmt_factors'] = factor_data

    # ── 벤치마크 요약 ──
    if 'cmt_bm' in st.session_state:
        bm = st.session_state['cmt_bm']
        pa = st.session_state['cmt_pa']
        fund_ret = st.session_state['cmt_fund_ret']

        with st.expander("벤치마크 월간 수익률", expanded=False):
            bm_items = []
            for n in ['글로벌주식', 'KOSPI', 'KOSPI_PRICE', 'S&P500', '미국성장주', '미국가치주',
                      '미국외선진국', '신흥국주식', '글로벌채권UH', '매경채권국채3년',
                      'KRX10년채권', '미국종합채권', 'Gold', 'WTI', 'DXY', 'USDKRW']:
                r = bm.get(n, {}).get('return')
                if r is not None:
                    bm_items.append({'지표': n, '수익률': f'{r:+.2f}%'})
            if bm_items:
                import pandas as pd
                st.dataframe(pd.DataFrame(bm_items), hide_index=True, use_container_width=True)

        # 펀드 성과 + PA
        ret_cols = st.columns(3)
        with ret_cols[0]:
            if fund_ret:
                st.metric("펀드 월수익률", f"{fund_ret['return']:+.2f}%")
                if fund_ret.get('sub_returns'):
                    for label, ret in fund_ret['sub_returns'].items():
                        st.caption(f"{label}: {ret:+.2f}%")
        with ret_cols[1]:
            st.markdown("**PA 기여도**")
            for cls in ['국내주식', '해외주식', '국내채권', '해외채권', '원자재']:
                if cls in pa and abs(pa[cls]) >= 0.01:
                    color = '🔴' if pa[cls] > 0 else '🔵'
                    st.caption(f"{color} {cls}: {pa[cls]:+.2f}%")

            # 종목별 drill-down
            if 'cmt_pa_items' in st.session_state:
                with st.expander("종목별 기여도", expanded=False):
                    _pa_items = st.session_state['cmt_pa_items']
                    import pandas as _pd2
                    _pa_df = _pd2.DataFrame(_pa_items)
                    if not _pa_df.empty:
                        _pa_df = _pa_df.sort_values('contrib_pct', key=abs, ascending=False)
                        _pa_df['기여도'] = _pa_df['contrib_pct'].apply(lambda v: f'{v:+.4f}%')
                        _pa_display = _pa_df[['asset_class', 'item_name', '기여도']].rename(
                            columns={'asset_class': '자산군', 'item_name': '종목명'})
                        st.dataframe(_pa_display, hide_index=True, use_container_width=True)
        with ret_cols[2]:
            st.markdown("**보유 비중**")
            holdings = st.session_state['cmt_holdings']
            for cls, wt in sorted(holdings.items(), key=lambda x: -x[1]):
                if wt > 0.5:
                    st.caption(f"{cls}: {wt:.1f}%")

    # ── 팩터 선택 체크박스 ──
    if 'cmt_factors' in st.session_state:
        factor_data = st.session_state['cmt_factors']
        st.markdown("---")
        st.markdown("#### 팩터 선택")
        st.caption("★★ = LLM 추천 (기본 선택). 체크박스로 코멘트에 반영할 원인을 선택하세요.")

        for ac, data in factor_data.items():
            st.markdown(f"**{ac}**: 기여 `{data['contrib']:+.2f}%` (비중 {data['weight']:.1f}%)")
            if not data.get('has_source') or not data['items']:
                st.caption("⚠️ 소스 부족 — 팩터를 직접 입력하세요")
                st.text_input(f"{ac} 원인 (직접 입력)", key=f"cmt_manual_{ac}", placeholder="예: 한은 금통위 비둘기파 발언으로 금리 하락")
            else:
                for i, item in enumerate(data['items']):
                    star = '★★' if item['score'] >= 8 else '★' if item['score'] >= 6 else ''
                    label = f"{star} {item['text']}  ({item['score']}점)"
                    default = False  # 디폴트 체크 해제 — 사용자가 직접 선택
                    key = f"cmt_fac_{ac}_{i}"
                    st.checkbox(label, value=default, key=key)
            st.markdown("")

        # ── Step 2: 코멘트 생성 ──
        st.markdown("---")
        gen_cols = st.columns([2, 1])
        with gen_cols[0]:
            gen_btn = st.button("코멘트 생성 (Opus)", key='cmt_generate', type='primary')
        with gen_cols[1]:
            st.caption("예상 비용: ~$0.22")

        if gen_btn:
            # 선택된 팩터 수집 (체크박스 + 직접 입력)
            selections = {}
            for ac, data in factor_data.items():
                selected = []
                # 체크박스 선택
                for i, item in enumerate(data['items']):
                    key = f"cmt_fac_{ac}_{i}"
                    if st.session_state.get(key, False):
                        selected.append(item['text'])
                # 직접 입력
                manual_key = f"cmt_manual_{ac}"
                manual = st.session_state.get(manual_key, '').strip()
                if manual:
                    selected.append(manual)
                if selected:
                    selections[ac] = selected

            if not selections:
                st.warning("팩터를 1개 이상 선택하세요.")
            else:
                with st.spinner('Opus 생성 중...'):
                    bm = st.session_state['cmt_bm']
                    pa = st.session_state['cmt_pa']
                    fund_ret = st.session_state['cmt_fund_ret']
                    holdings = st.session_state['cmt_holdings']
                    digest = st.session_state['cmt_digest']
                    next_digest = st.session_state['cmt_next_digest']

                    # 프롬프트 빌드
                    prompt = _build_llm_prompt(
                        c_fund, c_year, c_month, bm, fund_ret, pa, holdings,
                        digest, next_digest)

                    # 선택된 팩터 섹션 주입
                    sel_text = ''
                    for ac, texts in selections.items():
                        sel_text += f'\n[{ac}] 선택된 원인:\n'
                        for t in texts:
                            sel_text += f'  - {t}\n'

                    inject = f"""## {c_month}월 시장 — 자산군별 선택된 원인 (이것만 사용)
{sel_text}
위 선택된 원인만 코멘트에 반영하세요. 선택되지 않은 원인은 언급하지 마세요."""

                    next_m = 1 if c_month == 12 else c_month + 1
                    marker = f'## {c_month}월 시장 이벤트/분석 (블로그 기반)'
                    next_marker = f'## {next_m}월 전망 소스'
                    if marker in prompt:
                        idx1 = prompt.index(marker)
                        idx2 = prompt.index(next_marker) if next_marker in prompt else len(prompt)
                        prompt = prompt[:idx1] + inject + '\n\n' + prompt[idx2:]

                    # 프롬프트 저장 (디버그용)
                    st.session_state['cmt_prompt'] = prompt
                    st.session_state['cmt_selections'] = selections

                    try:
                        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                        response = client.messages.create(
                            model='claude-opus-4-6', max_tokens=2000,
                            messages=[{"role": "user", "content": prompt}])

                        result = response.content[0].text
                        u = response.usage
                        cost = u.input_tokens * 15 / 1e6 + u.output_tokens * 75 / 1e6
                        st.session_state['cmt_result'] = result
                        st.session_state['cmt_cost'] = cost
                        st.session_state['cmt_tokens'] = f'{u.input_tokens} in + {u.output_tokens} out'
                    except Exception as ex:
                        st.error(f"API 오류: {ex}")

    # ── Step 3: 미리보기 & 편집 ──
    if 'cmt_result' in st.session_state:
        st.markdown("---")
        st.markdown("#### 미리보기")
        cost = st.session_state.get('cmt_cost', 0)
        tokens = st.session_state.get('cmt_tokens', '')
        st.caption(f"💰 {tokens} = ${cost:.4f}")

        edited = st.text_area(
            "코멘트 (편집 가능)",
            value=st.session_state['cmt_result'],
            height=500,
            key='cmt_editor')

        dl_cols = st.columns([1, 3])
        with dl_cols[0]:
            st.download_button(
                "다운로드 (.txt)",
                data=edited.encode('utf-8'),
                file_name=f"report_{c_year}{c_month:02d}_{c_fund}.txt",
                mime="text/plain",
                key='cmt_download')

        # ── 디버그: 선택된 팩터 + 프롬프트 확인 ──
        if 'cmt_selections' in st.session_state:
            with st.expander("선택된 팩터 확인"):
                for ac, texts in st.session_state['cmt_selections'].items():
                    st.markdown(f"**{ac}**")
                    for t in texts:
                        st.markdown(f"- {t}")

        if 'cmt_prompt' in st.session_state:
            with st.expander("LLM 프롬프트 전문 (디버그)"):
                st.code(st.session_state['cmt_prompt'], language=None)
