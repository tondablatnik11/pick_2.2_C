import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import datetime
import io
from modules.utils import safe_hu, tr

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

# ---------------------------------------------------------------------------
# Konstanty směn
# Směna A: 5:45–13:45  (+ časy před 5:45 = přesčas ranní, také A)
# Směna B: 13:45–21:45
# ---------------------------------------------------------------------------
SHIFT_A_END = 13 * 60 + 45   # 825 min
SHIFT_B_END = 21 * 60 + 45   # 1305 min


def _add_one_hour(time_val) -> str:
    """Přičte 1 hodinu k časovému stringu (HH:MM:SS nebo HHMMSS). Vrací HH:MM:SS."""
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


def _parse_minutes(time_val) -> int:
    """Vrátí celkový počet minut od půlnoci, nebo -1 při chybě."""
    if pd.isna(time_val):
        return -1
    try:
        t_str = str(time_val).strip()
        if ':' in t_str:
            parts = t_str.split(':')
            return int(parts[0]) * 60 + int(parts[1])
        elif len(t_str) >= 6:
            return int(t_str[0:2]) * 60 + int(t_str[2:4])
    except (ValueError, TypeError):
        pass
    return -1


def _get_shift(time_val: str) -> str:
    """
    Určí směnu A / B po přičtení +1 hodiny.
    Směna A: 0:00–13:44 (včetně časů před 5:45 = přesčas)
    Směna B: 13:45–21:44
    Mimo:    21:45–23:59
    """
    corrected = _add_one_hour(time_val)
    mins = _parse_minutes(corrected)
    if mins < 0:
        return tr("Neznámá", "Unknown")
    if mins < SHIFT_A_END:
        return "A"
    elif mins < SHIFT_B_END:
        return "B"
    else:
        return tr("Mimo směnu", "Off-shift")


def _get_hour(time_val) -> int:
    """Vrátí hodinu po přičtení +1h pro hodinový graf."""
    corrected = _add_one_hour(time_val)
    if pd.isna(corrected):
        return -1
    try:
        t_str = str(corrected).strip()
        if ':' in t_str:
            return int(t_str.split(':')[0])
        elif len(t_str) >= 6:
            return int(t_str[0:2])
    except (ValueError, TypeError):
        pass
    return -1


def _shift_comparison_section(pick_df: pd.DataFrame, pack_df: pd.DataFrame,
                               hc_a_pick: float, hc_a_pack: float,
                               hc_b_pick: float, hc_b_pack: float):
    """Vykreslí sekci porovnání směn A vs B – graf + tabulka."""
    st.markdown(f"#### 🔄 {tr('Porovnání směn A vs B', 'Shift Comparison A vs B')}")

    a_pick = len(pick_df[pick_df['Shift'] == 'A']) if not pick_df.empty else 0
    b_pick = len(pick_df[pick_df['Shift'] == 'B']) if not pick_df.empty else 0
    a_pack = len(pack_df[pack_df['Shift'] == 'A']) if not pack_df.empty else 0
    b_pack = len(pack_df[pack_df['Shift'] == 'B']) if not pack_df.empty else 0

    if a_pick + b_pick + a_pack + b_pack == 0:
        st.info(tr("Žádná data pro porovnání směn.", "No data for shift comparison."))
        return

    # --- Graf ---
    df_cmp = pd.DataFrame([
        {'Shift': 'A', 'Process': tr('Pick (TO)', 'Pick (TO)'), 'Count': a_pick},
        {'Shift': 'B', 'Process': tr('Pick (TO)', 'Pick (TO)'), 'Count': b_pick},
        {'Shift': 'A', 'Process': tr('Pack (HU)', 'Pack (HU)'), 'Count': a_pack},
        {'Shift': 'B', 'Process': tr('Pack (HU)', 'Pack (HU)'), 'Count': b_pack},
    ])
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
    def _prod(val, hc):
        return f"{val / hc:.1f}" if hc > 0 else "–"

    tbl = pd.DataFrame([
        {
            tr('Směna', 'Shift'): 'A  ☀️  (5:45–13:45)',
            tr('Pick (TO)', 'Pick (TO)'): a_pick,
            tr('Pick / hlava', 'Pick / head'): _prod(a_pick, hc_a_pick),
            tr('Pack (HU)', 'Pack (HU)'): a_pack,
            tr('Pack / hlava', 'Pack / head'): _prod(a_pack, hc_a_pack),
        },
        {
            tr('Směna', 'Shift'): 'B  🌆  (13:45–21:45)',
            tr('Pick (TO)', 'Pick (TO)'): b_pick,
            tr('Pick / hlava', 'Pick / head'): _prod(b_pick, hc_b_pick),
            tr('Pack (HU)', 'Pack (HU)'): b_pack,
            tr('Pack / hlava', 'Pack / head'): _prod(b_pack, hc_b_pack),
        },
    ])
    st.dataframe(tbl, hide_index=True, use_container_width=True)


@fast_render
def render_daily_kpi(df_pick, raw_vekp,
                     billing_df: pd.DataFrame,
                     df_hu_details: pd.DataFrame):
    """
    Vykreslí záložku Denní KPI.

    OPRAVA: Přijímá předpočítaná billing_df a df_hu_details z app.py.
    Nepočítá cached_billing_logic sama → žádná duplicita výpočtu,
    žádné riziko odlišného voll_set.
    """
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>📊 {tr('Denní KPI & Shopfloor Board', 'Daily KPI & Shopfloor Board')}</h3>"
        f"<p>{tr('Ranní přehled výkonu skladu. Zadejte účast, zkontrolujte produktivitu.', 'Morning warehouse performance overview.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    # --- 1. Výběr data ---
    col_date, _ = st.columns([1, 3])
    with col_date:
        default_date = datetime.date.today() - datetime.timedelta(days=1)
        selected_date = st.date_input(
            f"📅 {tr('Vyberte analyzovaný den:', 'Select analyzed date:')}",
            value=default_date
        )

    sel_date_str        = selected_date.strftime('%Y-%m-%d')
    sel_date_str_nodash = selected_date.strftime('%Y%m%d')

    # --- 2. Headcount vstup ---
    with st.expander(tr("👥 Účast (Headcount)", "👥 Headcount"), expanded=False):
        hc_c1, hc_c2 = st.columns(2)
        with hc_c1:
            st.info(f"**☀️ {tr('Směna A', 'Shift A')} (5:45 – 13:45)**")
            hc_a_pick = st.number_input(tr("Pickování – Směna A", "Picking – Shift A"), min_value=0.0, step=0.5, key="hc_r_pick")
            hc_a_pack = st.number_input(tr("Balení – Směna A",    "Packing – Shift A"), min_value=0.0, step=0.5, key="hc_r_pack")
        with hc_c2:
            st.warning(f"**🌆 {tr('Směna B', 'Shift B')} (13:45 – 21:45)**")
            hc_b_pick = st.number_input(tr("Pickování – Směna B", "Picking – Shift B"), min_value=0.0, step=0.5, key="hc_o_pick")
            hc_b_pack = st.number_input(tr("Balení – Směna B",    "Packing – Shift B"), min_value=0.0, step=0.5, key="hc_o_pack")

    st.divider()

    # --- 3. PICK DATA pro vybraný den ---
    pick_daily = pd.DataFrame()
    time_col   = 'Confirmation time'

    if df_pick is not None and not df_pick.empty:
        df_p     = df_pick.copy()
        date_col = 'Confirmation date' if 'Confirmation date' in df_p.columns else 'Date'
        time_col = 'Confirmation time' if 'Confirmation time' in df_p.columns else 'Time'

        if date_col in df_p.columns and time_col in df_p.columns:
            df_p['TempDate'] = pd.to_datetime(df_p[date_col], errors='coerce').dt.strftime('%Y-%m-%d')
            pick_daily = df_p[df_p['TempDate'] == sel_date_str].copy()
            if not pick_daily.empty:
                pick_daily['Shift']    = pick_daily[time_col].apply(_get_shift)
                pick_daily['Hour']     = pick_daily[time_col].apply(_get_hour)
                pick_daily['Category'] = pick_daily.get('Queue', tr('Neznámá fronta', 'Unknown Queue'))

    # --- 4. PACK DATA pro vybraný den (z předpočítaného df_hu_details) ---
    pack_daily = pd.DataFrame()
    time_col_v = None

    if (raw_vekp is not None and not raw_vekp.empty
            and df_hu_details is not None and not df_hu_details.empty):

        df_vk      = raw_vekp.copy()
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
            df_vk['Clean_HU_Int'] = df_vk[hu_int_col].apply(safe_hu)

            b_df = df_hu_details.copy()
            b_df['Clean_HU_Int'] = b_df['HU_Int'].apply(safe_hu)

            pack_merged = pd.merge(
                b_df[['Clean_HU_Int', 'Category_Full']],
                df_vk[['Clean_HU_Int', date_col_v, time_col_v]],
                on='Clean_HU_Int',
                how='inner'
            ).drop_duplicates('Clean_HU_Int')

            pack_merged['TempDate'] = pd.to_datetime(
                pack_merged[date_col_v], errors='coerce').dt.strftime('%Y-%m-%d')
            pack_daily = pack_merged[pack_merged['TempDate'] == sel_date_str].copy()

            if not pack_daily.empty:
                pack_daily['Shift']    = pack_daily[time_col_v].apply(_get_shift)
                pack_daily['Hour']     = pack_daily[time_col_v].apply(_get_hour)
                pack_daily['Category'] = pack_daily['Category_Full']

    # --- 5. VÝSLEDKY ---
    st.markdown(
        f"### 📈 {tr('Výsledky za den:', 'Results for:')} {selected_date.strftime('%d.%m.%Y')}"
    )

    kpi_c1, kpi_c2, kpi_c3 = st.columns(3)

    with kpi_c1:
        st.markdown(
            f"<div style='background-color:var(--secondary-background-color);padding:15px;"
            f"border-radius:8px;border-left:5px solid #94a3b8;'>"
            f"<h4>📥 {tr('Příjem', 'Inbound')} (Zítra)</h4>"
            f"<p>{tr('Čekáme na napojení reportu...', 'Waiting for report connection...')}</p>"
            f"</div>",
            unsafe_allow_html=True
        )

    with kpi_c2:
        total_pick = pick_daily.shape[0]
        st.markdown(
            f"<div style='background-color:var(--secondary-background-color);padding:15px;"
            f"border-radius:8px;border-left:5px solid #3b82f6;'>"
            f"<h4>🛒 Pick ({tr('Úkoly', 'Tasks')})</h4>"
            f"<h2>{total_pick:,} TO</h2></div>",
            unsafe_allow_html=True
        )
        if not pick_daily.empty:
            a_pick = pick_daily[pick_daily['Shift'] == 'A'].shape[0]
            b_pick = pick_daily[pick_daily['Shift'] == 'B'].shape[0]
            st.write(f"**{tr('Směna A', 'Shift A')}:** {a_pick} TO "
                     f"*({tr('Produktivita:', 'Productivity:')} "
                     f"{a_pick/hc_a_pick if hc_a_pick > 0 else 0:.1f} / {tr('hlava', 'head')})*")
            st.write(f"**{tr('Směna B', 'Shift B')}:** {b_pick} TO "
                     f"*({tr('Produktivita:', 'Productivity:')} "
                     f"{b_pick/hc_b_pick if hc_b_pick > 0 else 0:.1f} / {tr('hlava', 'head')})*")
            st.markdown("---")
            st.markdown(f"**{tr('Rozpad podle front:', 'Breakdown by Queue:')}**")
            q_df = (pick_daily.groupby('Category').size().reset_index(name='TO')
                    .sort_values('TO', ascending=False))
            q_df.columns = [tr('Fronta', 'Queue'), tr('Počet TO', 'Number of TOs')]
            st.dataframe(q_df, hide_index=True, use_container_width=True)

    with kpi_c3:
        total_pack = pack_daily.shape[0]
        st.markdown(
            f"<div style='background-color:var(--secondary-background-color);padding:15px;"
            f"border-radius:8px;border-left:5px solid #8b5cf6;'>"
            f"<h4>📦 {tr('Balení', 'Packing')} (HU)</h4>"
            f"<h2>{total_pack:,} HU</h2></div>",
            unsafe_allow_html=True
        )
        if not pack_daily.empty:
            a_pack = pack_daily[pack_daily['Shift'] == 'A'].shape[0]
            b_pack = pack_daily[pack_daily['Shift'] == 'B'].shape[0]
            st.write(f"**{tr('Směna A', 'Shift A')}:** {a_pack} HU "
                     f"*({tr('Produktivita:', 'Productivity:')} "
                     f"{a_pack/hc_a_pack if hc_a_pack > 0 else 0:.1f} / {tr('hlava', 'head')})*")
            st.write(f"**{tr('Směna B', 'Shift B')}:** {b_pack} HU "
                     f"*({tr('Produktivita:', 'Productivity:')} "
                     f"{b_pack/hc_b_pack if hc_b_pack > 0 else 0:.1f} / {tr('hlava', 'head')})*")
            st.markdown("---")
            st.markdown(f"**{tr('Rozpad podle kategorií:', 'Breakdown by Category:')}**")
            c_df = (pack_daily.groupby('Category').size().reset_index(name='HU')
                    .sort_values('HU', ascending=False))
            c_df.columns = [tr('Kategorie', 'Category'), tr('Počet HU', 'Number of HUs')]
            st.dataframe(c_df, hide_index=True, use_container_width=True)

    st.divider()

    # --- 6. Porovnání směn A vs B ---
    _shift_comparison_section(
        pick_daily, pack_daily,
        hc_a_pick, hc_a_pack,
        hc_b_pick, hc_b_pack
    )

    st.divider()

    # --- 7. Hodinový graf ---
    st.markdown(f"#### 🕒 {tr('Hodinový vývoj skladu (24h)', 'Hourly Warehouse Progress (24h)')}")
    hourly_data = []
    if not pick_daily.empty:
        ph = pick_daily[pick_daily['Hour'] >= 0].groupby('Hour').size().reset_index(name='Volume')
        ph['Process'] = tr('Pick (TO)', 'Pick (TO)')
        hourly_data.append(ph)
    if not pack_daily.empty:
        bh = pack_daily[pack_daily['Hour'] >= 0].groupby('Hour').size().reset_index(name='Volume')
        bh['Process'] = tr('Pack (HU)', 'Pack (HU)')
        hourly_data.append(bh)

    if hourly_data:
        df_hourly = pd.concat(hourly_data)
        fig = px.bar(
            df_hourly, x='Hour', y='Volume', color='Process', barmode='group',
            color_discrete_map={
                tr('Pick (TO)', 'Pick (TO)'): '#3b82f6',
                tr('Pack (HU)', 'Pack (HU)'): '#8b5cf6'
            },
            labels={
                'Hour':   tr('Hodina dne', 'Hour of Day'),
                'Volume': tr('Počet úkolů / HU', 'Volume (Tasks / HU)')
            },
            template='plotly_white'
        )
        # Hranice směn
        fig.add_vline(x=5.75,  line_dash='dash', line_color='#f59e0b',
                      annotation_text='A', annotation_position='top right')
        fig.add_vline(x=13.75, line_dash='dash', line_color='#10b981',
                      annotation_text='B', annotation_position='top right')
        fig.add_vline(x=21.75, line_dash='dash', line_color='#ef4444',
                      annotation_text=tr('Konec B', 'End B'), annotation_position='top right')
        fig.update_layout(
            xaxis=dict(tickmode='linear', tick0=0, dtick=1, range=[-0.5, 23.5]),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(size=12, family="Inter, sans-serif")
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(tr("Zatím žádná data pro hodinový graf.", "No data for hourly chart yet."))

    st.divider()

    # --- 8. Power BI export ---
    st.markdown(f"#### 🔌 {tr('Datový export pro Power BI', 'Data Export for Power BI')}")
    pbi_rows = []
    if not pick_daily.empty:
        for _, row in pick_daily.iterrows():
            pbi_rows.append({
                'Date': sel_date_str, 'Time': row.get(time_col, ''),
                'Hour': row.get('Hour', -1), 'Shift': row.get('Shift', ''),
                'Process': 'Pick', 'Category': row.get('Category', ''),
                'Value': 1, 'Unit': 'TO'
            })
    if not pack_daily.empty and time_col_v:
        for _, row in pack_daily.iterrows():
            pbi_rows.append({
                'Date': sel_date_str, 'Time': row.get(time_col_v, ''),
                'Hour': row.get('Hour', -1), 'Shift': row.get('Shift', ''),
                'Process': 'Pack', 'Category': row.get('Category', ''),
                'Value': 1, 'Unit': 'HU'
            })

    if pbi_rows:
        df_pbi = pd.DataFrame(pbi_rows)
        df_pbi = df_pbi[df_pbi['Hour'] >= 0]
        st.dataframe(df_pbi.head(3), use_container_width=True)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_pbi.to_excel(writer, index=False, sheet_name='PBI_Export')
        st.download_button(
            label=tr("⬇️ Stáhnout Flat Table pro Power BI (.xlsx)",
                     "⬇️ Download Flat Table for Power BI (.xlsx)"),
            data=buffer.getvalue(),
            file_name=f"PowerBI_Export_{sel_date_str_nodash}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary"
        )
    else:
        st.warning(tr("Data pro Power BI nejsou pro vybraný den k dispozici.",
                      "Data for Power BI is not available for the selected day."))
