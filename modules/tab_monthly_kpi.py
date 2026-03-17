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

# ---------------------------------------------------------------------------
# Pomocné funkce pro přiřazení směny z VEKP/Pick časů
# (stejná logika jako tab_daily_kpi, ale zde pracujeme s billing_df
#  který nemá raw časy – směny odvodíme z pick reportu pokud je k dispozici)
# ---------------------------------------------------------------------------
SHIFT_A_END = 13 * 60 + 45   # 825 min
SHIFT_B_END = 21 * 60 + 45   # 1305 min


def _add_one_hour(time_val) -> str:
    if pd.isna(time_val):
        return time_val
    try:
        t_str = str(time_val).strip()
        if ':' in t_str:
            parts = t_str.split(':')
            h, m = int(parts[0]), int(parts[1])
            s = int(parts[2]) if len(parts) > 2 else 0
        elif len(t_str) >= 6:
            h, m, s = int(t_str[0:2]), int(t_str[2:4]), int(t_str[4:6])
        else:
            return time_val
        h = (h + 1) % 24
        return f"{h:02d}:{m:02d}:{s:02d}"
    except (ValueError, TypeError):
        return time_val


def _time_to_shift(time_val) -> str:
    """Přiřadí směnu A/B z časového stringu po korekci +1h."""
    corrected = _add_one_hour(time_val)
    if pd.isna(corrected):
        return "?"
    try:
        t_str = str(corrected).strip()
        if ':' in t_str:
            parts = t_str.split(':')
            mins = int(parts[0]) * 60 + int(parts[1])
        elif len(t_str) >= 6:
            mins = int(t_str[0:2]) * 60 + int(t_str[2:4])
        else:
            return "?"
        if mins < SHIFT_A_END:
            return "A"
        elif mins < SHIFT_B_END:
            return "B"
        else:
            return tr("Mimo", "Off")
    except (ValueError, TypeError):
        return "?"


def _render_shift_comparison(df_pick: pd.DataFrame, raw_vekp: pd.DataFrame,
                              df_hu_details: pd.DataFrame, sel_month: str):
    """
    Sekce porovnání směn A vs B za vybraný měsíc.
    Pick data: z df_pick (Confirmation date + time).
    Pack data: z raw_vekp spojeno s df_hu_details.
    """
    st.markdown(f"#### 🔄 {tr('Porovnání směn A vs B za měsíc', 'Shift Comparison A vs B – Month')} {sel_month}")

    pick_a = pick_b = pack_a = pack_b = 0

    # --- Pick ---
    if df_pick is not None and not df_pick.empty:
        df_p     = df_pick.copy()
        date_col = next((c for c in df_p.columns if 'Confirmation date' in str(c) or c == 'Date'), None)
        time_col = next((c for c in df_p.columns if 'Confirmation time' in str(c) or c == 'Time'), None)
        if date_col and time_col:
            df_p['_month'] = pd.to_datetime(df_p[date_col], errors='coerce').dt.strftime('%Y-%m')
            df_p_m = df_p[df_p['_month'] == sel_month].copy()
            if not df_p_m.empty:
                df_p_m['_shift'] = df_p_m[time_col].apply(_time_to_shift)
                pick_a = (df_p_m['_shift'] == 'A').sum()
                pick_b = (df_p_m['_shift'] == 'B').sum()

    # --- Pack ---
    if (raw_vekp is not None and not raw_vekp.empty
            and df_hu_details is not None and not df_hu_details.empty):
        from modules.utils import safe_hu
        df_vk = raw_vekp.copy()
        hu_int_col = next(
            (c for c in df_vk.columns if 'Internal HU' in str(c) or 'HU-Nummer intern' in str(c)),
            df_vk.columns[0]
        )
        date_col_v = next(
            (c for c in df_vk.columns if 'CREATED ON' in str(c).upper() or 'ERFASST AM' in str(c).upper()),
            None
        )
        time_col_v = next(
            (c for c in df_vk.columns if 'TIME' in str(c).upper() or 'UHRZEIT' in str(c).upper()),
            None
        )
        if date_col_v and time_col_v:
            df_vk['_hu'] = df_vk[hu_int_col].apply(safe_hu)
            b_df = df_hu_details.copy()
            b_df['_hu'] = b_df['HU_Int'].apply(safe_hu)
            merged = pd.merge(
                b_df[['_hu']],
                df_vk[['_hu', date_col_v, time_col_v]],
                on='_hu', how='inner'
            ).drop_duplicates('_hu')
            merged['_month'] = pd.to_datetime(merged[date_col_v], errors='coerce').dt.strftime('%Y-%m')
            merged_m = merged[merged['_month'] == sel_month].copy()
            if not merged_m.empty:
                merged_m['_shift'] = merged_m[time_col_v].apply(_time_to_shift)
                pack_a = (merged_m['_shift'] == 'A').sum()
                pack_b = (merged_m['_shift'] == 'B').sum()

    if pick_a + pick_b + pack_a + pack_b == 0:
        st.info(tr(
            "Data o čase nejsou k dispozici pro porovnání směn (potřeba df_pick / raw_vekp).",
            "Time data not available for shift comparison (df_pick / raw_vekp required)."
        ))
        return

    # --- Graf ---
    df_cmp = pd.DataFrame([
        {'Shift': 'A', 'Process': tr('Pick (TO)', 'Pick (TO)'), 'Count': int(pick_a)},
        {'Shift': 'B', 'Process': tr('Pick (TO)', 'Pick (TO)'), 'Count': int(pick_b)},
        {'Shift': 'A', 'Process': tr('Pack (HU)', 'Pack (HU)'), 'Count': int(pack_a)},
        {'Shift': 'B', 'Process': tr('Pack (HU)', 'Pack (HU)'), 'Count': int(pack_b)},
    ])
    col_g, col_t = st.columns([3, 2])
    with col_g:
        fig = px.bar(
            df_cmp, x='Shift', y='Count', color='Process', barmode='group',
            color_discrete_map={
                tr('Pick (TO)', 'Pick (TO)'): '#3b82f6',
                tr('Pack (HU)', 'Pack (HU)'): '#8b5cf6'
            },
            labels={
                'Shift':   tr('Směna', 'Shift'),
                'Count':   tr('Počet', 'Count'),
                'Process': tr('Proces', 'Process')
            },
            text_auto=True,
            template='plotly_white'
        )
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(size=13, family="Inter, sans-serif"),
            margin=dict(l=0, r=0, t=30, b=0)
        )
        st.plotly_chart(fig, use_container_width=True)

    # --- Tabulka ---
    with col_t:
        total_pick = pick_a + pick_b
        total_pack = pack_a + pack_b
        tbl = pd.DataFrame([
            {
                tr('Směna', 'Shift'): 'A  ☀️',
                tr('Pick (TO)', 'Pick (TO)'): pick_a,
                tr('Pick %', 'Pick %'): f"{pick_a/total_pick*100:.1f}%" if total_pick else "–",
                tr('Pack (HU)', 'Pack (HU)'): pack_a,
                tr('Pack %', 'Pack %'): f"{pack_a/total_pack*100:.1f}%" if total_pack else "–",
            },
            {
                tr('Směna', 'Shift'): 'B  🌆',
                tr('Pick (TO)', 'Pick (TO)'): pick_b,
                tr('Pick %', 'Pick %'): f"{pick_b/total_pick*100:.1f}%" if total_pick else "–",
                tr('Pack (HU)', 'Pack (HU)'): pack_b,
                tr('Pack %', 'Pack %'): f"{pack_b/total_pack*100:.1f}%" if total_pack else "–",
            },
            {
                tr('Směna', 'Shift'): tr('Celkem', 'Total'),
                tr('Pick (TO)', 'Pick (TO)'): total_pick,
                tr('Pick %', 'Pick %'): "100%",
                tr('Pack (HU)', 'Pack (HU)'): total_pack,
                tr('Pack %', 'Pack %'): "100%",
            },
        ])
        st.dataframe(tbl, hide_index=True, use_container_width=True)

    # --- Průměr na směnu ---
    st.caption(
        f"💡 {tr('Průměr na 1 směnu –', 'Avg per shift –')} "
        f"Pick: A={pick_a} / B={pick_b}   "
        f"Pack: A={pack_a} / B={pack_b}"
    )


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

    voll_mask = monthly_billing['Category_Full'].str.contains('Vollpalette', na=False)
    sort_mask = monthly_billing['Category_Full'].str.contains('Sortenrein', na=False)
    voll_hu   = int(monthly_billing[voll_mask]['pocet_hu'].sum())
    sort_hu   = int(monthly_billing[sort_mask]['pocet_hu'].sum())
    voll_pct  = voll_hu / total_hu * 100 if total_hu > 0 else 0.0
    sort_pct  = sort_hu / total_hu * 100 if total_hu > 0 else 0.0

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

    # --- 5. Porovnání směn A vs B ---
    _render_shift_comparison(df_pick, df_vekp, df_hu_details, sel_month)

    st.divider()

    # --- 6. Meziměsíční trend ---
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

    # --- 7. Detail tabulka ---
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

    # --- 8. Excel export ---
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
