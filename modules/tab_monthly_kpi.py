import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import io
from modules.utils import tr, safe_del

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f


def render_monthly_kpi(df_pick, df_vekp, df_vepo,
                       billing_df: pd.DataFrame,
                       df_hu_details: pd.DataFrame):
    """
    Měsíční KPI a cílové sledování.

    OPRAVA: Přijímá předpočítaná billing_df a df_hu_details z app.py.
    Nepočítá cached_billing_logic sama → žádná duplicita výpočtu,
    žádné riziko odlišného voll_set mezi taby.
    """
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>📅 {tr('Měsíční KPI & Cíle', 'Monthly KPI & Targets')}</h3>"
        f"<p>{tr('Nastavte cíle na měsíc a sledujte plnění.', 'Set monthly targets and track achievement.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    if billing_df is None or billing_df.empty:
        st.info(tr("Data fakturace nejsou k dispozici.", "Billing data not available."))
        return

    # --- 1. Výběr měsíce ---
    available_months = sorted(billing_df['Month'].dropna().unique().tolist())
    if not available_months:
        st.warning(tr("Žádná data k dispozici.", "No data available."))
        return

    col_sel, _ = st.columns([1, 3])
    with col_sel:
        sel_month = st.selectbox(
            tr("Vyberte měsíc:", "Select Month:"),
            options=available_months,
            index=len(available_months) - 1
        )

    monthly_billing = billing_df[billing_df['Month'] == sel_month].copy()

    # --- 2. CÍLOVÉ NASTAVENÍ ---
    with st.expander(f"🎯 {tr('Nastavení cílů pro měsíc', 'Monthly Targets Settings')}", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            target_hu = st.number_input(tr("Cíl HU celkem", "Target HUs"), min_value=0, value=3000, step=100)
        with c2:
            target_voll = st.number_input(tr("Cíl Vollpaletten (%)", "Target Vollpallets (%)"),
                                          min_value=0.0, max_value=100.0, value=30.0, step=1.0)
        with c3:
            target_sortenrein = st.number_input(tr("Cíl Sortenrein (%)", "Target Sortenrein (%)"),
                                                min_value=0.0, max_value=100.0, value=40.0, step=1.0)
        with c4:
            target_efficiency = st.number_input(
                tr("Cíl efektivity (pohyby/HU)", "Target Efficiency (moves/HU)"),
                min_value=0.0, value=5.0, step=0.5
            )

    st.divider()

    # --- 3. HLAVNÍ KPI ---
    total_hu     = int(monthly_billing['pocet_hu'].sum())
    total_to     = int(monthly_billing['pocet_to'].sum())
    total_orders = int(monthly_billing['Delivery'].nunique())
    total_moves  = int(monthly_billing['pohyby_celkem'].sum())
    net_balance  = int(monthly_billing['Bilance'].sum())
    moves_per_hu = (total_moves / total_hu) if total_hu > 0 else 0.0

    voll_mask    = monthly_billing['Category_Full'].str.contains('Vollpalette', na=False)
    sort_mask    = monthly_billing['Category_Full'].str.contains('Sortenrein', na=False)
    voll_hu      = int(monthly_billing[voll_mask]['pocet_hu'].sum())
    sort_hu      = int(monthly_billing[sort_mask]['pocet_hu'].sum())
    voll_pct     = voll_hu / total_hu * 100 if total_hu > 0 else 0.0
    sort_pct     = sort_hu / total_hu * 100 if total_hu > 0 else 0.0

    # --- KPI Cards ---
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    metrics = [
        (k1, tr("HU Celkem", "Total HUs"),
         f"{total_hu:,}", f"{total_hu/target_hu*100:.1f}% {tr('cíle','target')}" if target_hu > 0 else None,
         "normal" if total_hu >= target_hu else "inverse"),
        (k2, tr("Zakázky", "Orders"),        f"{total_orders:,}",            None, "normal"),
        (k3, tr("Pohyby/HU", "Moves/HU"),    f"{moves_per_hu:.2f}",
         f"{tr('Cíl', 'Target')}: {target_efficiency:.1f}", "inverse" if moves_per_hu < target_efficiency else "normal"),
        (k4, tr("Vollpaletten (%)", "Vollpallets (%)"), f"{voll_pct:.1f}%",
         f"{tr('Cíl', 'Target')}: {target_voll:.0f}%", "normal" if voll_pct >= target_voll else "inverse"),
        (k5, tr("Sortenrein (%)", "Sortenrein (%)"), f"{sort_pct:.1f}%",
         f"{tr('Cíl', 'Target')}: {target_sortenrein:.0f}%", "normal" if sort_pct >= target_sortenrein else "inverse"),
        (k6, tr("Čistá bilance", "Net Balance"), f"{net_balance:+,}", None,
         "normal" if net_balance <= 0 else "inverse"),
    ]
    for col, label, val, delta, delta_color in metrics:
        with col:
            with st.container(border=True):
                st.metric(label=label, value=val, delta=delta, delta_color=delta_color)

    st.divider()

    # --- 4. GRAFY ---
    col_l, col_r = st.columns(2)

    with col_l:
        st.markdown(f"**{tr('Rozložení HU podle kategorií', 'HU Distribution by Category')}**")
        cat_agg = monthly_billing.groupby('Category_Full')['pocet_hu'].sum().reset_index()
        cat_agg.columns = [tr('Kategorie', 'Category'), tr('Počet HU', 'HU Count')]
        fig_pie = px.pie(
            cat_agg, values=tr('Počet HU', 'HU Count'), names=tr('Kategorie', 'Category'),
            color_discrete_sequence=['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
            hole=0.4
        )
        fig_pie.update_layout(paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_r:
        st.markdown(f"**{tr('Srovnání TO vs HU po kategoriích', 'TO vs HU Comparison by Category')}**")
        to_hu_agg = monthly_billing.groupby('Category_Full').agg(
            TO=('pocet_to', 'sum'), HU=('pocet_hu', 'sum')
        ).reset_index()
        fig_bar = go.Figure()
        fig_bar.add_trace(go.Bar(x=to_hu_agg['Category_Full'], y=to_hu_agg['TO'],
                                 name=tr('Počet TO', 'Total TOs'), marker_color='#3b82f6'))
        fig_bar.add_trace(go.Bar(x=to_hu_agg['Category_Full'], y=to_hu_agg['HU'],
                                 name=tr('Počet HU', 'Total HUs'), marker_color='#8b5cf6'))
        fig_bar.update_layout(
            barmode='group', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()

    # --- 5. Meziměsíční trend ---
    st.markdown(f"**{tr('Trend HU a pohybů (všechny měsíce)', 'HU & Moves Trend (All Months)')}**")
    trend_all = billing_df.groupby('Month').agg(
        HU=('pocet_hu', 'sum'),
        TO=('pocet_to', 'sum'),
        Moves=('pohyby_celkem', 'sum'),
        Locs=('pocet_lokaci', 'sum')
    ).reset_index()
    trend_all['Moves_per_HU'] = np.where(trend_all['HU'] > 0, trend_all['Moves'] / trend_all['HU'], 0)

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Bar(x=trend_all['Month'], y=trend_all['HU'],
                               name=tr('HU Celkem', 'Total HUs'), marker_color='#3b82f6'))
    fig_trend.add_trace(go.Bar(x=trend_all['Month'], y=trend_all['TO'],
                               name=tr('TO Celkem', 'Total TOs'), marker_color='#10b981'))
    fig_trend.add_trace(go.Scatter(x=trend_all['Month'], y=trend_all['Moves_per_HU'],
                                   name=tr('Pohyby/HU', 'Moves/HU'), yaxis='y2',
                                   mode='lines+markers+text',
                                   text=trend_all['Moves_per_HU'].round(2),
                                   textposition='top center',
                                   line=dict(color='#f59e0b', width=3)))
    fig_trend.update_layout(
        barmode='group',
        yaxis2=dict(title=tr('Pohyby/HU', 'Moves/HU'), side='right', overlaying='y', showgrid=False),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=30, b=0),
        legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0)
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    st.divider()

    # --- 6. Detail tabulka ---
    st.markdown(f"**{tr('Detail zakázek za měsíc', 'Order Detail for Month')}**")
    disp_monthly = monthly_billing[[
        'Delivery', 'Category_Full', 'pocet_to', 'pocet_hu', 'pohyby_celkem',
        'pocet_lokaci', 'Bilance'
    ]].copy()
    disp_monthly.columns = [
        tr('Zakázka', 'Order'), tr('Kategorie', 'Category'),
        tr('TO', 'TO'), tr('HU', 'HU'),
        tr('Pohyby', 'Moves'), tr('Lokace', 'Locs'),
        tr('Bilance', 'Balance')
    ]

    def _color_balance(val):
        try:
            if val > 0: return 'color: #ef4444; font-weight: bold'
            if val < 0: return 'color: #10b981; font-weight: bold'
        except Exception:
            pass
        return ''

    try:
        styled = disp_monthly.style.map(_color_balance, subset=[tr('Bilance', 'Balance')])
    except AttributeError:
        styled = disp_monthly.style.applymap(_color_balance, subset=[tr('Bilance', 'Balance')])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # --- 7. Excel export ---
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        monthly_billing.to_excel(writer, index=False, sheet_name=f'KPI_{sel_month}')
        billing_df.to_excel(writer, index=False, sheet_name='All_Months')
    st.download_button(
        label=tr("⬇️ Stáhnout měsíční KPI report (.xlsx)",
                 "⬇️ Download Monthly KPI Report (.xlsx)"),
        data=buffer.getvalue(),
        file_name=f"Monthly_KPI_{sel_month}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )