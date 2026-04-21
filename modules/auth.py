# === auth.py ===
# 역할 선택 UI (프론트엔드만 -- 인증/로그인은 추후 개발)
# 첫 화면에서 admin / client 택1 하여 대시보드 진입

import streamlit as st


def init_session():
    """세션 상태 초기화"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None


def is_admin() -> bool:
    """admin 여부"""
    return st.session_state.get('user_role') == 'admin'


def logout():
    """로그아웃 (역할 선택 화면으로 복귀)"""
    st.session_state.authenticated = False
    st.session_state.user_role = None


def show_role_selector() -> bool:
    """
    역할 선택 화면 표시.
    admin / client 중 선택하면 authenticated=True 설정 후 rerun.
    이미 선택 완료된 경우 True 반환.
    """
    init_session()

    if st.session_state.authenticated:
        return True

    # --- 역할 선택 화면 ---
    st.markdown("")
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("""
        <div style="text-align:center; padding: 60px 40px;
                    background: linear-gradient(135deg, #667eea22, #764ba222);
                    border-radius: 20px; margin-top: 40px;">
            <h1 style="font-size: 2.5rem; margin-bottom: 10px;">DB OCIO 운용 대시보드</h1>
            <p style="font-size: 1.1rem; color: #666; margin-bottom: 10px;">
                DB형 퇴직연금 OCIO 운용 현황을 한눈에 확인하세요
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("")
        st.markdown("")

        btn1, btn2 = st.columns(2)

        with btn1:
            st.markdown("""
            <div style="text-align:center; padding: 20px; border: 2px solid #667eea;
                        border-radius: 12px; background: #667eea08; margin-bottom: 10px;">
                <h3 style="color: #667eea; margin-bottom: 5px;">Admin</h3>
                <p style="color: #888; font-size: 0.9rem;">전체 펀드 조회 및 관리</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Admin 으로 접속", width="stretch", type="primary"):
                st.session_state.authenticated = True
                st.session_state.user_role = 'admin'
                st.rerun()

        with btn2:
            st.markdown("""
            <div style="text-align:center; padding: 20px; border: 2px solid #764ba2;
                        border-radius: 12px; background: #764ba208; margin-bottom: 10px;">
                <h3 style="color: #764ba2; margin-bottom: 5px;">Client</h3>
                <p style="color: #888; font-size: 0.9rem;">할당 펀드 조회</p>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Client 로 접속", width="stretch"):
                st.session_state.authenticated = True
                st.session_state.user_role = 'client'
                st.rerun()

    return False
