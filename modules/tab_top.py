import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

# Globální nastavení grafů (pokud by ještě nebylo definováno v utils.py)
CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)', 
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#f8fafc', size=12, family="Inter, sans-serif"),
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified"
)

def render_top(df_pick):
    # Chytrý lokální překladač pro tuto záložku
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>🏆 {_t('Materiály (TOP)', 'Top Materials')}</h3><p>{_t('Přehled nejčastěji vychystávaných materiálů podle fyzické náročnosti a počtu zakázek (TO).', 'Overview of the most frequently picked materials based on physical effort and TO count.')}</p></div>", unsafe_allow_html=True)
    
    if df_pick is None or df_pick.empty:
        st.info(_t("Žádná data nejsou k dispozici.", "No data available."))
        return

    # Bezpečná detekce sloupce pro zakázky (TO)
    to_col = 'Transfer Order Number' if 'Transfer Order Number' in df_pick.columns else 'Delivery'
    
    # 1. Agregace všech dat za materiály
    mat_agg = df_pick.groupby('Material').agg(
        Moves=('Pohyby_Rukou', 'sum'),
        Exact=('Pohyby_Exact', 'sum'),
        Miss=('Pohyby_Loose_Miss', 'sum'),
        Qty=('Qty', 'sum'),
        TO_Count=(to_col, 'nunique'),
        Lines=('Material', 'count')
    ).reset_index()
    
    # 2. Výpočet GLOBÁLNÍCH statistik přesnosti (Exact vs Estimate)
    total_mats = len(mat_agg)
    exact_mats = len(mat_agg[mat_agg['Miss'] == 0])
    est_mats = len(mat_agg[mat_agg['Miss'] > 0])
    
    pct_exact = (exact_mats / total_mats) * 100 if total_mats > 0 else 0
    pct_est = (est_mats / total_mats) * 100 if total_mats > 0 else 0
    
    # Zobrazení statistik nahoře (Globální)
    st.markdown(f"#### 📊 {_t('Kvalita dat a pokrytí materiálů (Globální pohled)', 'Data Quality and Material Coverage (Global View)')}")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric(_t("Celkem unikátních materiálů", "Total Unique Materials"), f"{total_mats:,}")
    with c2:
        with st.container(border=True):
            st.metric(_t("Přesná data 100% z manuálních master dat", "Exact Data 100% from Manual Master Data"), f"{exact_mats:,} ks", f"{pct_exact:.1f} %")
    with c3:
        with st.container(border=True):
            st.metric(_t("Vyžadující odhad (Chybí obal)", "Requiring Estimate (Missing box)"), f"{est_mats:,} ks", f"- {pct_est:.1f} %")
            
    st.divider()
    
    # Rozdělení do 3 záložek
    tab1, tab2, tab3 = st.tabs([
        f"💪 {_t('TOP 500: Podle pohybů', 'TOP 500: By Moves')}",
        f"📦 {_t('TOP 500: Podle zakázek (TO)', 'TOP 500: By TOs')}",
        f"⚠️ {_t('TOP 500: Odhady (Chybí data)', 'TOP 500: Estimates (Missing data)')}"
    ])
    
    # Pomocná funkce pro formátování tabulky
    def format_table(df):
        disp = df[['Material', 'Moves', 'TO_Count', 'Qty', 'Exact', 'Miss', 'Lines']].copy()
        disp.columns = [
            _t("Materiál", "Material"),
            _t("Celkem Pohybů", "Total Moves"),
            _t("Počet TO", "TO Count"),
            _t("Vychystáno kusů", "Picked Qty"),
            _t("Přesné pohyby", "Exact Moves"),
            _t("Odhady (Miss)", "Estimates (Miss)"),
            _t("Řádků v reportu", "Lines in Report")
        ]
        return disp
    
    # Pomocná funkce pro kreslení čistých Plotly grafů
    def make_bar_chart(df, x_col, y_col, title, color='#3b82f6'):
        fig = go.Figure()
        
        # PŘEVOD NA STRING = Zabrání Plotly analyzovat materiály jako matematická čísla
        x_vals = df[x_col].astype(str)
        
        fig.add_trace(go.Bar(
            x=x_vals,
            y=df[y_col],
            marker_color=color,
            text=df[y_col].apply(lambda x: f"{x:,.0f}"),
            textposition='auto',
            name=title
        ))
        
        fig.update_layout(**CHART_LAYOUT)
        fig.update_layout(
            title=title, 
            xaxis_title=_t("Materiál", "Material"), 
            yaxis_title="",
            xaxis=dict(type='category') # VYNUCENÍ KATEGORICKÉ OSY X
        )
        return fig

    # --- ZÁLOŽKA 1: Podle pohybů ---
    with tab1:
        st.markdown(f"**{_t('Nejnáročnější materiály z hlediska fyzické práce (bez ohledu na přesnost).', 'Most demanding materials in terms of physical effort (regardless of accuracy).')}**")
        top_moves = mat_agg.sort_values('Moves', ascending=False).head(500)
        
        # Lokální statistika kvality dat pro tento TOP výběr
        t1_len = len(top_moves)
        t1_exact = len(top_moves[top_moves['Miss'] == 0])
        t1_est = len(top_moves[top_moves['Miss'] > 0])
        p1_exact = (t1_exact / t1_len * 100) if t1_len > 0 else 0
        p1_est = (t1_est / t1_len * 100) if t1_len > 0 else 0
        
        cs1, cs2 = st.columns(2)
        cs1.success(f"✅ **{_t('Přesná data u tohoto TOP', 'Exact data in this TOP')} {t1_len}:** {t1_exact} {_t('materiálů', 'materials')} ({p1_exact:.1f} %)")
        cs2.warning(f"⚠️ **{_t('Odhady u tohoto TOP', 'Estimates in this TOP')} {t1_len}:** {t1_est} {_t('materiálů', 'materials')} ({p1_est:.1f} %)")
        
        col_t1, col_g1 = st.columns([1.1, 1])
        with col_t1:
            st.dataframe(format_table(top_moves), use_container_width=True, hide_index=True)
        with col_g1:
            st.plotly_chart(make_bar_chart(top_moves.head(15), 'Material', 'Moves', _t("TOP 15 dle fyzických pohybů", "TOP 15 by Physical Moves"), '#3b82f6'), use_container_width=True)

    # --- ZÁLOŽKA 2: Podle TO ---
    with tab2:
        st.markdown(f"**{_t('Nejfrekventovanější materiály (nejvíce zastávek skladníka u regálu).', 'Most frequent materials (most picker stops at the shelf).')}**")
        top_tos = mat_agg.sort_values('TO_Count', ascending=False).head(500)
        
        # Lokální statistika kvality dat pro tento TOP výběr
        t2_len = len(top_tos)
        t2_exact = len(top_tos[top_tos['Miss'] == 0])
        t2_est = len(top_tos[top_tos['Miss'] > 0])
        p2_exact = (t2_exact / t2_len * 100) if t2_len > 0 else 0
        p2_est = (t2_est / t2_len * 100) if t2_len > 0 else 0
        
        cs3, cs4 = st.columns(2)
        cs3.success(f"✅ **{_t('Přesná data u tohoto TOP', 'Exact data in this TOP')} {t2_len}:** {t2_exact} {_t('materiálů', 'materials')} ({p2_exact:.1f} %)")
        cs4.warning(f"⚠️ **{_t('Odhady u tohoto TOP', 'Estimates in this TOP')} {t2_len}:** {t2_est} {_t('materiálů', 'materials')} ({p2_est:.1f} %)")
        
        col_t2, col_g2 = st.columns([1.1, 1])
        with col_t2:
            st.dataframe(format_table(top_tos), use_container_width=True, hide_index=True)
        with col_g2:
            st.plotly_chart(make_bar_chart(top_tos.head(15), 'Material', 'TO_Count', _t("TOP 15 dle počtu zakázek (TO)", "TOP 15 by Order Count (TO)"), '#10b981'), use_container_width=True)

    # --- ZÁLOŽKA 3: Odhady (Miss) ---
    with tab3:
        st.markdown(f"**{_t('Materiály, kterým chybí master data (balení) a systém jejich fyzickou náročnost odhaduje.', 'Materials missing master data (packaging) whose physical effort is estimated.')}**")
        est_df = mat_agg[mat_agg['Miss'] > 0].copy()
        
        if est_df.empty:
            st.success(_t("Skvělá zpráva! Všechny vaše materiály mají perfektní master data.", "Great news! All your materials have perfect master data."))
        else:
            sort_opt = st.radio(
                _t("Seřadit žebříček podle:", "Sort ranking by:"),
                options=[_t("Počtu zakázek (TO_Count)", "Order Count (TO_Count)"), _t("Odhadnutých pohybů (Miss)", "Estimated Moves (Miss)")],
                horizontal=True
            )
            
            if sort_opt == _t("Odhadnutých pohybů (Miss)", "Estimated Moves (Miss)"):
                top_est = est_df.sort_values('Miss', ascending=False).head(500)
                y_col_chart = 'Miss'
                chart_title = _t("TOP 15 chybějících dat (dle dopadu na pohyby)", "TOP 15 Missing Data (by impact on moves)")
                chart_color = '#ef4444'
            else:
                top_est = est_df.sort_values('TO_Count', ascending=False).head(500)
                y_col_chart = 'TO_Count'
                chart_title = _t("TOP 15 chybějících dat (dle frekvence TO)", "TOP 15 Missing Data (by TO frequency)")
                chart_color = '#f59e0b'

            col_t3, col_g3 = st.columns([1.1, 1])
            with col_t3:
                st.dataframe(format_table(top_est), use_container_width=True, hide_index=True)
            with col_g3:
                st.plotly_chart(make_bar_chart(top_est.head(15), 'Material', y_col_chart, chart_title, chart_color), use_container_width=True)
