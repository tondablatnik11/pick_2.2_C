import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from modules.utils import tr, safe_del

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f


def render_fu_compare(df_pick: pd.DataFrame,
                      billing_df: pd.DataFrame,
                      voll_set: set,
                      queue_count_col: str):
    """
    Porovnání FU (Vollpaletten detekovaných z pick reportu)
    vs SAP Vollpaletten (z VEKP/VEPO přes billing_df).

    OPRAVA:
    - Nepřistupuje k session_state['data_dict'] přímo – dostává data jako parametry.
    - billing_df pochází z centrálního výpočtu v app.py → konzistentní s ostatními taby.
    - Trend graf nyní pracuje se všemi měsíci z billing_df (ne jen s aktuálním filtrem).
    """
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>↔️ {tr('Porovnání FU vs SAP (Vollpaletten)', 'Comparison FU vs SAP (Vollpaletts)')}</h3>"
        f"<p>{tr('Korelace mezi interní detekcí Vollpalet (pick report) a SAP záznamy (VEKP/VEPO).', 'Correlation between internal Vollpallets detection and SAP records.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    if df_pick is None or df_pick.empty:
        st.info(tr("Chybí data Pick reportu.", "Pick report data missing."))
        return

    # -------------------------------------------------------------------
    # 1. FU DETEKCE Z PICK REPORTU
    # -------------------------------------------------------------------
    df_p = df_pick.copy()
    df_p['Clean_Del'] = df_p['Delivery'].apply(safe_del)

    # Vollpaletten řádky z pick reportu (přes voll_set)
    def _row_is_voll(row):
        from modules.utils import safe_hu
        d  = row['Clean_Del']
        hu = safe_hu(row.get('Handling Unit', ''))
        if not hu:
            hu = safe_hu(row.get('Source storage unit', ''))
        return (d, hu) in voll_set

    df_p['Is_Voll_Pick'] = df_p.apply(_row_is_voll, axis=1)

    # Agregace FU per zakázka
    pick_del_agg = df_p.groupby('Clean_Del').agg(
        total_to=(queue_count_col, 'nunique'),
        voll_to=('Is_Voll_Pick', 'sum'),
        month=('Month', 'first')
    ).reset_index()
    pick_del_agg['voll_pct_pick'] = np.where(
        pick_del_agg['total_to'] > 0,
        pick_del_agg['voll_to'] / pick_del_agg['total_to'] * 100,
        0
    )

    # -------------------------------------------------------------------
    # 2. SAP VOLLPALETTEN Z BILLING_DF
    # -------------------------------------------------------------------
    sap_del_agg = pd.DataFrame(columns=['Clean_Del', 'voll_hu_sap', 'total_hu_sap'])
    if billing_df is not None and not billing_df.empty:
        b = billing_df.copy()
        b['Clean_Del'] = b['Delivery'].apply(safe_del)
        b['is_voll_sap'] = b['Category_Full'].str.contains('Vollpalette', na=False)
        sap_del_agg = b.groupby('Clean_Del').agg(
            voll_hu_sap=('pocet_hu', lambda x: x[b.loc[x.index, 'is_voll_sap']].sum()),
            total_hu_sap=('pocet_hu', 'sum'),
            month_sap=('Month', 'first')
        ).reset_index()
        sap_del_agg['voll_pct_sap'] = np.where(
            sap_del_agg['total_hu_sap'] > 0,
            sap_del_agg['voll_hu_sap'] / sap_del_agg['total_hu_sap'] * 100,
            0
        )

    # -------------------------------------------------------------------
    # 3. MERGE
    # -------------------------------------------------------------------
    merged = pd.merge(
        pick_del_agg, sap_del_agg,
        on='Clean_Del', how='outer'
    )
    merged['month'] = merged['month'].fillna(merged.get('month_sap', ''))
    for col in ['total_to', 'voll_to', 'voll_pct_pick',
                'voll_hu_sap', 'total_hu_sap', 'voll_pct_sap']:
        merged[col] = merged[col].fillna(0)

    merged['diff_voll'] = merged['voll_to'] - merged['voll_hu_sap']

    # -------------------------------------------------------------------
    # 4. KPI METRIKY
    # -------------------------------------------------------------------
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.metric(tr("Vollpalet (Pick)", "Vollpallets (Pick)"),
                      f"{int(merged['voll_to'].sum()):,}")
    with c2:
        with st.container(border=True):
            st.metric(tr("Vollpalet (SAP)", "Vollpallets (SAP)"),
                      f"{int(merged['voll_hu_sap'].sum()):,}")
    with c3:
        with st.container(border=True):
            net_diff = int(merged['diff_voll'].sum())
            st.metric(tr("Rozdíl (Pick - SAP)", "Difference (Pick - SAP)"),
                      f"{net_diff:+,}",
                      help=tr(
                          "Kladné = Pick detekoval více vollpalet než SAP záznamy.",
                          "Positive = Pick detected more vollpallets than SAP records."
                      ))
    with c4:
        total_dels = merged['Clean_Del'].nunique()
        matching = merged[abs(merged['diff_voll']) <= 1]['Clean_Del'].nunique()
        match_pct = matching / total_dels * 100 if total_dels > 0 else 0.0
        with st.container(border=True):
            st.metric(tr("Shoda zakázek (±1)", "Order Match (±1)"),
                      f"{match_pct:.1f}%",
                      help=tr("% zakázek kde se pick a SAP liší max o 1 HU.",
                               "% orders where pick and SAP differ by at most 1 HU."))

    st.divider()

    # -------------------------------------------------------------------
    # 5. TREND PŘES MĚSÍCE (z billing_df → všechny měsíce)
    # -------------------------------------------------------------------
    st.markdown(f"**{tr('Trend Vollpalet (všechny měsíce)', 'Vollpallets Trend (All Months)')}**")

    if billing_df is not None and not billing_df.empty:
        b_all = billing_df.copy()
        b_all['is_voll'] = b_all['Category_Full'].str.contains('Vollpalette', na=False)
        trend = b_all.groupby('Month').agg(
            total_hu=('pocet_hu', 'sum'),
            voll_hu=('pocet_hu', lambda x: x[b_all.loc[x.index, 'is_voll']].sum()),
        ).reset_index()
        trend['voll_pct'] = np.where(
            trend['total_hu'] > 0, trend['voll_hu'] / trend['total_hu'] * 100, 0)

        # Pick trend
        if 'Month' in df_p.columns:
            pick_trend = df_p.groupby('Month').agg(
                pick_voll=('Is_Voll_Pick', 'sum'),
                pick_total=(queue_count_col, 'nunique')
            ).reset_index()
            pick_trend['pick_voll_pct'] = np.where(
                pick_trend['pick_total'] > 0,
                pick_trend['pick_voll'] / pick_trend['pick_total'] * 100, 0)
            trend = pd.merge(trend, pick_trend, on='Month', how='outer').fillna(0)

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Bar(
            x=trend['Month'], y=trend['voll_hu'],
            name=tr('SAP Vollpalet (HU)', 'SAP Vollpallets (HU)'),
            marker_color='#3b82f6'
        ))
        if 'pick_voll' in trend.columns:
            fig_trend.add_trace(go.Bar(
                x=trend['Month'], y=trend['pick_voll'],
                name=tr('Pick Vollpalet (TO)', 'Pick Vollpallets (TO)'),
                marker_color='#10b981'
            ))
        fig_trend.add_trace(go.Scatter(
            x=trend['Month'], y=trend['voll_pct'],
            name=tr('SAP % Vollpalet', 'SAP % Vollpallets'),
            yaxis='y2', mode='lines+markers+text',
            text=trend['voll_pct'].round(1).astype(str) + '%',
            textposition='top center',
            line=dict(color='#f59e0b', width=3)
        ))
        if 'pick_voll_pct' in trend.columns:
            fig_trend.add_trace(go.Scatter(
                x=trend['Month'], y=trend['pick_voll_pct'],
                name=tr('Pick % Vollpalet', 'Pick % Vollpallets'),
                yaxis='y2', mode='lines+markers',
                line=dict(color='#06b6d4', width=2, dash='dot')
            ))
        fig_trend.update_layout(
            barmode='group',
            yaxis2=dict(title='%', side='right', overlaying='y', showgrid=False),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0)
        )
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info(tr("Billing data pro trend nejsou k dispozici.", "No billing data for trend."))

    st.divider()

    # -------------------------------------------------------------------
    # 6. DETAIL TABULKA – ZAKÁZKY S NEJVĚTŠÍM ROZDÍLEM
    # -------------------------------------------------------------------
    st.markdown(f"**{tr('Top zakázky s odchylkou (|Pick - SAP| > 2)', 'Top orders with deviation (|Pick - SAP| > 2)')}**")
    outliers = merged[abs(merged['diff_voll']) > 2].sort_values(
        'diff_voll', key=abs, ascending=False).head(50)

    if not outliers.empty:
        disp = outliers[[
            'Clean_Del', 'month', 'total_to', 'voll_to', 'voll_pct_pick',
            'total_hu_sap', 'voll_hu_sap', 'voll_pct_sap', 'diff_voll'
        ]].copy()
        disp.columns = [
            tr('Zakázka', 'Delivery'), tr('Měsíc', 'Month'),
            tr('TO celkem', 'Total TO'), tr('Voll TO (Pick)', 'Voll TO (Pick)'),
            tr('% Voll (Pick)', '% Voll (Pick)'),
            tr('HU celkem (SAP)', 'HU Total (SAP)'), tr('Voll HU (SAP)', 'Voll HU (SAP)'),
            tr('% Voll (SAP)', '% Voll (SAP)'),
            tr('Rozdíl', 'Difference'),
        ]

        def _color_diff(val):
            try:
                if abs(val) > 5: return 'color: #ef4444; font-weight: bold'
                if abs(val) > 2: return 'color: #f59e0b; font-weight: bold'
            except Exception:
                pass
            return ''

        try:
            styled = disp.style.format({
                tr('% Voll (Pick)', '% Voll (Pick)'): "{:.1f}%",
                tr('% Voll (SAP)', '% Voll (SAP)'): "{:.1f}%",
            }).map(_color_diff, subset=[tr('Rozdíl', 'Difference')])
        except AttributeError:
            styled = disp.style.format({
                tr('% Voll (Pick)', '% Voll (Pick)'): "{:.1f}%",
                tr('% Voll (SAP)', '% Voll (SAP)'): "{:.1f}%",
            }).applymap(_color_diff, subset=[tr('Rozdíl', 'Difference')])

        st.dataframe(styled, use_container_width=True, hide_index=True)
    else:
        st.success(tr("Žádné výrazné odchylky mezi Pick a SAP detekcí!",
                      "No significant deviations between Pick and SAP detection!"))

    st.divider()

    # -------------------------------------------------------------------
    # 7. SCATTER KORELACE
    # -------------------------------------------------------------------
    st.markdown(f"**{tr('Korelace Pick vs SAP Vollpalet', 'Pick vs SAP Vollpallets Correlation')}**")
    scatter_df = merged[(merged['voll_to'] > 0) | (merged['voll_hu_sap'] > 0)].copy()

    if not scatter_df.empty:
        fig_sc = px.scatter(
            scatter_df,
            x='voll_to', y='voll_hu_sap',
            color='month',
            labels={
                'voll_to':     tr('Pick Vollpalet', 'Pick Vollpallets'),
                'voll_hu_sap': tr('SAP Vollpalet', 'SAP Vollpallets'),
                'month':       tr('Měsíc', 'Month')
            },
            hover_data=['Clean_Del', 'diff_voll'],
            opacity=0.7
        )
        # Diagonální referenční linie (ideál = shoda)
        max_val = max(scatter_df['voll_to'].max(), scatter_df['voll_hu_sap'].max()) + 1
        fig_sc.add_trace(go.Scatter(
            x=[0, max_val], y=[0, max_val],
            mode='lines', name=tr('Ideální shoda', 'Perfect Match'),
            line=dict(color='rgba(255,255,255,0.4)', dash='dash', width=1)
        ))
        fig_sc.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_sc, use_container_width=True)
    else:
        st.info(tr("Nedostatek dat pro scatter graf.", "Not enough data for scatter plot."))