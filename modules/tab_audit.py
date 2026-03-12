import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import io
from modules.utils import (
    tr, safe_hu, safe_del, get_match_key,
    detect_vekp_columns, detect_vepo_columns,
    fast_compute_moves
)

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

_AUDIT_CAT_ORDER = [
    'N Sortenrein', 'N Misch', 'N Vollpalette',
    'E Sortenrein', 'E Misch',
    'O Sortenrein', 'O Misch', 'O Vollpalette',
    'OE Sortenrein', 'OE Misch', 'O Vollpalette (OE)',
]


def render_audit(df_pick, df_vekp, df_vepo, df_oe,
                 queue_count_col: str,
                 billing_df: pd.DataFrame,
                 manual_boxes: dict,
                 weight_dict: dict,
                 dim_dict: dict,
                 box_dict: dict,
                 limit_vahy: float,
                 limit_rozmeru: float,
                 kusy_na_hmat: int):
    """
    Audit záložka – rentgen dat, kontrola přesnosti billing logiky.

    OPRAVA:
    - Billing_df přijímá jako parametr (předpočítaný singleton z app.py).
    - Žádné duplicitní volání cached_billing_logic.
    - Odstraněn duplicitní load_from_db na začátku funkce.
    - Ošetřen KeyError 'Month' (přidána kontrola existence sloupce).
    """
    st.markdown(
        f"<div class='section-header'>"
        f"<h3>🔍 {tr('Audit & Rentgen dat', 'Audit & X-Ray')}</h3>"
        f"<p>{tr('Diagnostika přesnosti výpočtů a kvality dat.', 'Diagnostics of calculation accuracy and data quality.')}</p>"
        f"</div>",
        unsafe_allow_html=True
    )

    tabs = st.tabs([
        tr("📊 Billing přesnost", "📊 Billing Accuracy"),
        tr("🔬 Material Debug", "🔬 Material Debug"),
        tr("🏭 VEKP Rentgen", "🏭 VEKP X-Ray"),
        tr("📦 HU Detail", "📦 HU Detail"),
        tr("⏱️ Časy vs pohyby", "⏱️ Times vs Moves"),
    ])

    # ==================================================================
    # TAB 1: BILLING PŘESNOST
    # ==================================================================
    with tabs[0]:
        _render_billing_accuracy(billing_df, queue_count_col)

    # ==================================================================
    # TAB 2: MATERIAL DEBUG
    # ==================================================================
    with tabs[1]:
        _render_material_debug(
            df_pick, manual_boxes, weight_dict, dim_dict, box_dict,
            limit_vahy, limit_rozmeru, kusy_na_hmat
        )

    # ==================================================================
    # TAB 3: VEKP RENTGEN
    # ==================================================================
    with tabs[2]:
        _render_vekp_xray(df_vekp, df_vepo)

    # ==================================================================
    # TAB 4: HU DETAIL
    # ==================================================================
    with tabs[3]:
        _render_hu_detail(billing_df, st.session_state.get('debug_hu_details', pd.DataFrame()))

    # ==================================================================
    # TAB 5: ČASY VS POHYBY
    # ==================================================================
    with tabs[4]:
        _render_times_vs_moves(billing_df, df_oe)


@fast_render
def _render_billing_accuracy(billing_df: pd.DataFrame, queue_count_col: str):
    """Kontrola přesnosti billing logiky – upload kontrolního souboru a porovnání."""
    st.markdown(f"#### {tr('Porovnání s kontrolním souborem (kontrola.xlsx)', 'Comparison with kontrola.xlsx')}")

    uploaded = st.file_uploader(
        tr("Nahrát kontrolní soubor (Excel, sloupce: Delivery, Category_Full, pocet_hu)",
           "Upload control file (Excel, columns: Delivery, Category_Full, pocet_hu)"),
        type=['xlsx', 'xls', 'csv'],
        key="audit_kontrola_upload"
    )

    if uploaded is None:
        if billing_df is not None and not billing_df.empty:
            st.info(tr(
                "Nahrajte kontrolní soubor pro srovnání. Mezitím zobrazuji aktuální billing data.",
                "Upload a control file to compare. Showing current billing data in the meantime."
            ))
            _show_billing_summary(billing_df)
        return

    try:
        if uploaded.name.endswith('.csv'):
            df_kontrola = pd.read_csv(uploaded, dtype=str)
        else:
            df_kontrola = pd.read_excel(uploaded, dtype=str)
        df_kontrola.columns = df_kontrola.columns.str.strip()
    except Exception as e:
        st.error(f"Chyba při načítání souboru: {e}")
        return

    # Detekce sloupců kontrolního souboru
    cols_up = [str(c).upper().strip() for c in df_kontrola.columns]
    c_del = next((c for c, u in zip(df_kontrola.columns, cols_up)
                  if 'DELIVERY' in u or 'ZAKÁZKA' in u or 'LIEFERUNG' in u),
                 df_kontrola.columns[0])
    c_cat = next((c for c, u in zip(df_kontrola.columns, cols_up)
                  if 'CATEGORY' in u or 'KATEGORIE' in u), None)
    c_hu  = next((c for c, u in zip(df_kontrola.columns, cols_up)
                  if 'HU' in u or 'POCET' in u or 'COUNT' in u), None)

    if c_cat is None:
        st.error(tr("Soubor neobsahuje sloupec kategorie.", "File missing category column."))
        return

    df_kontrola['_del'] = df_kontrola[c_del].astype(str).str.strip().apply(safe_del)
    df_kontrola['_cat'] = df_kontrola[c_cat].astype(str).str.strip()
    if c_hu:
        df_kontrola['_hu'] = pd.to_numeric(df_kontrola[c_hu], errors='coerce').fillna(0).astype(int)
    else:
        df_kontrola['_hu'] = 1

    if billing_df is None or billing_df.empty:
        st.warning(tr("Billing data nejsou k dispozici.", "Billing data not available."))
        return

    app_agg = billing_df.copy()
    app_agg['_del'] = app_agg['Delivery'].apply(safe_del)
    app_agg_grp = app_agg.groupby(['_del', 'Category_Full'])['pocet_hu'].sum().reset_index()
    app_agg_grp.columns = ['_del', '_cat', '_hu_app']

    # Merge
    merged = pd.merge(
        df_kontrola[['_del', '_cat', '_hu']].rename(columns={'_hu': '_hu_ctrl'}),
        app_agg_grp,
        on=['_del', '_cat'],
        how='outer',
        indicator=True
    )
    merged['_hu_ctrl'] = merged['_hu_ctrl'].fillna(0).astype(int)
    merged['_hu_app']  = merged['_hu_app'].fillna(0).astype(int)
    merged['_diff']    = merged['_hu_app'] - merged['_hu_ctrl']
    merged['_match']   = merged['_diff'] == 0

    total     = len(merged)
    correct   = int(merged['_match'].sum())
    accuracy  = correct / total * 100 if total > 0 else 0.0

    # Výsledek
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(tr("Přesnost", "Accuracy"), f"{accuracy:.1f}%",
                  delta=f"{correct}/{total} {tr('řádků OK', 'rows OK')}")
    with col2:
        only_ctrl = merged[merged['_merge'] == 'left_only']
        st.metric(tr("Pouze v kontrole", "Only in control"), len(only_ctrl))
    with col3:
        only_app = merged[merged['_merge'] == 'right_only']
        st.metric(tr("Pouze v aplikaci", "Only in app"), len(only_app))

    if accuracy >= 100.0:
        st.success("🎉 100% shoda!")
    else:
        errors_df = merged[~merged['_match']].sort_values('_diff', key=abs, ascending=False)
        disp = errors_df[['_del', '_cat', '_hu_ctrl', '_hu_app', '_diff', '_merge']].copy()
        disp.columns = [
            tr('Zakázka', 'Delivery'), tr('Kategorie', 'Category'),
            tr('Kontrola', 'Control'), tr('Aplikace', 'App'),
            tr('Rozdíl', 'Diff'), tr('Zdroj', 'Source')
        ]
        st.dataframe(disp, use_container_width=True, hide_index=True)

    # Export
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        merged.to_excel(w, index=False, sheet_name='Audit_Compare')
    st.download_button(
        tr("⬇️ Export srovnání", "⬇️ Export Comparison"),
        data=buf.getvalue(),
        file_name="audit_comparison.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def _show_billing_summary(billing_df: pd.DataFrame):
    """Rychlý přehled billing dat bez kontrolního souboru."""
    cat_agg = billing_df.groupby('Category_Full').agg(
        Orders=('Delivery', 'nunique'),
        HU=('pocet_hu', 'sum'),
        TO=('pocet_to', 'sum')
    ).reset_index().sort_values('HU', ascending=False)
    st.dataframe(cat_agg, use_container_width=True, hide_index=True)


@fast_render
def _render_material_debug(df_pick, manual_boxes, weight_dict, dim_dict, box_dict,
                            limit_vahy, limit_rozmeru, kusy_na_hmat):
    """Debug pro konkrétní materiál – ukazuje balení, váhu, výpočet pohybů."""
    st.markdown(f"#### {tr('Debug materiálu', 'Material Debug')}")

    if df_pick is None or df_pick.empty:
        st.info(tr("Chybí pick data.", "Pick data missing."))
        return

    all_mats = sorted(df_pick['Material'].dropna().unique().tolist())
    sel_mat  = st.selectbox(tr("Vyberte materiál:", "Select material:"), options=all_mats)

    if not sel_mat:
        return

    mk = get_match_key(sel_mat)
    st.markdown(f"**Match Key:** `{mk}`")

    # Balení
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        st.markdown(tr("**📦 MARM balení:**", "**📦 MARM Packing:**"))
        marm_boxes = box_dict.get(mk, [])
        st.write(marm_boxes if marm_boxes else tr("Není v MARM", "Not in MARM"))
    with col_b2:
        st.markdown(tr("**✋ Ruční Master Data:**", "**✋ Manual Master Data:**"))
        man_boxes = manual_boxes.get(mk, [])
        st.write(man_boxes if man_boxes else tr("Není ručně definováno", "Not manually defined"))

    effective_boxes = man_boxes or marm_boxes
    st.markdown(f"**{tr('Efektivní balení', 'Effective Packing')}:** `{effective_boxes}`")

    w  = weight_dict.get(mk, 0.0)
    d  = dim_dict.get(mk, 0.0)
    st.markdown(f"**{tr('Váha', 'Weight')}:** `{w:.3f} kg`  |  **{tr('Max. rozměr', 'Max Dim')}:** `{d:.1f} cm`")

    # Testovací výpočet
    st.divider()
    st.markdown(f"**{tr('Testovací výpočet pohybů:', 'Test Move Calculation:')}**")
    test_qty = st.number_input(tr("Zadejte množství pro test:", "Enter test quantity:"),
                                min_value=1, value=100)
    test_queue = st.selectbox(tr("Fronta:", "Queue:"),
                               ['PI_PL', 'PI_PA', 'PI_PL_FU', 'PI_PL_OE', 'PI_PA_OE'], index=0)
    test_su    = st.selectbox(tr("Removal of total SU:", "Removal of total SU:"),
                               ['', 'X'], index=0)

    tot, exact, miss = fast_compute_moves(
        [test_qty], [test_queue], [test_su],
        [effective_boxes], [w], [d],
        limit_vahy, limit_rozmeru, kusy_na_hmat
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric(tr("Celkové pohyby", "Total Moves"), tot[0])
    with c2:
        with st.container(border=True):
            st.metric(tr("Přesné pohyby", "Exact Moves"), exact[0])
    with c3:
        with st.container(border=True):
            st.metric(tr("Odhadnuté pohyby", "Estimated Moves"), miss[0])

    # Pickup rows z pick reportu
    st.divider()
    st.markdown(f"**{tr('Pick řádky tohoto materiálu (prvních 20):', 'Pick rows for this material (first 20):')}**")
    pick_mat = df_pick[df_pick['Material'].astype(str) == str(sel_mat)].head(20)
    if not pick_mat.empty:
        disp_cols = [c for c in ['Delivery', 'Qty', 'Queue', 'Month',
                                  'Pohyby_Rukou', 'Pohyby_Exact', 'Box_Sizes_List'] if c in pick_mat.columns]
        st.dataframe(pick_mat[disp_cols], use_container_width=True, hide_index=True)
    else:
        st.info(tr("Materiál nenalezen v pick datech.", "Material not found in pick data."))


@fast_render
def _render_vekp_xray(df_vekp, df_vepo):
    """Rentgen VEKP/VEPO struktury – detekce sloupců, statistiky."""
    st.markdown(f"#### {tr('VEKP/VEPO Rentgen', 'VEKP/VEPO X-Ray')}")

    if df_vekp is None or df_vekp.empty:
        st.info(tr("VEKP data nejsou k dispozici.", "VEKP data not available."))
        return

    # Detekce sloupců
    vekp_cols = detect_vekp_columns(df_vekp)
    st.markdown(f"**{tr('Detekované sloupce VEKP:', 'Detected VEKP Columns:')}**")
    col_info = pd.DataFrame([
        {'Funkce': k, 'Sloupec (detekovaný)': v or tr('❌ Nenalezeno', '❌ Not Found')}
        for k, v in vekp_cols.items()
    ])
    st.dataframe(col_info, use_container_width=True, hide_index=True)

    col_p = vekp_cols.get('parent')
    col_d = vekp_cols.get('delivery')

    # Statistiky
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric(tr("Celkem HU záznamů", "Total HU Records"), f"{len(df_vekp):,}")
    with c2:
        roots = df_vekp[df_vekp[col_p].apply(safe_hu) == ''] if col_p else pd.DataFrame()
        with st.container(border=True):
            st.metric(tr("Root HU (bez rodiče)", "Root HU (no parent)"), f"{len(roots):,}")
    with c3:
        if col_d:
            dels = df_vekp[col_d].apply(safe_del).nunique()
        else:
            dels = 0
        with st.container(border=True):
            st.metric(tr("Unikátní zakázky ve VEKP", "Unique Deliveries in VEKP"), f"{dels:,}")

    # Hloubka hierarchie
    if col_p:
        st.divider()
        st.markdown(f"**{tr('Hierarchie HU (hloubka stromu):', 'HU Hierarchy (tree depth):')}**")
        col_hu_int = vekp_cols.get('hu_int') or df_vekp.columns[0]
        parent_map = {
            safe_hu(r[col_hu_int]): safe_hu(r[col_p])
            for _, r in df_vekp.iterrows()
            if safe_hu(r[col_hu_int])
        }
        depths = {}
        def _depth(hu, memo={}):
            if hu in memo: return memo[hu]
            p = parent_map.get(hu, '')
            d = 0 if not p else 1 + _depth(p, memo)
            memo[hu] = d
            return d

        for hu in list(parent_map.keys()):
            depths[hu] = _depth(hu)

        if depths:
            depth_counts = pd.Series(depths.values()).value_counts().sort_index()
            depth_df = depth_counts.reset_index()
            depth_df.columns = [tr('Hloubka', 'Depth'), tr('Počet HU', 'HU Count')]
            st.dataframe(depth_df, use_container_width=True, hide_index=True)

    # VEPO
    if df_vepo is not None and not df_vepo.empty:
        st.divider()
        st.markdown(f"**{tr('VEPO statistiky:', 'VEPO Statistics:')}**")
        vepo_cols = detect_vepo_columns(df_vepo)
        st.write({k: v for k, v in vepo_cols.items()})
        c1v, c2v = st.columns(2)
        with c1v:
            with st.container(border=True):
                st.metric(tr("Celkem VEPO řádků", "Total VEPO Rows"), f"{len(df_vepo):,}")
        with c2v:
            v_hu_col = vepo_cols.get('hu_int')
            if v_hu_col:
                uniq_hu = df_vepo[v_hu_col].apply(safe_hu).nunique()
                with st.container(border=True):
                    st.metric(tr("Unikátní HU ve VEPO", "Unique HU in VEPO"), f"{uniq_hu:,}")


@fast_render
def _render_hu_detail(billing_df: pd.DataFrame, df_hu_details: pd.DataFrame):
    """Detail HU klasifikace per zakázka."""
    st.markdown(f"#### {tr('HU Detail per zakázka', 'HU Detail per Delivery')}")

    if billing_df is None or billing_df.empty:
        st.info(tr("Billing data nejsou k dispozici.", "Billing data not available."))
        return

    all_dels = sorted(billing_df['Delivery'].dropna().unique().tolist())
    sel_del = st.selectbox(tr("Vyberte zakázku:", "Select delivery:"),
                            options=[tr("— vyberte —", "— select —")] + all_dels)

    if sel_del == tr("— vyberte —", "— select —"):
        return

    # Billing souhrn
    billing_del = billing_df[billing_df['Delivery'] == sel_del]
    st.markdown(f"**{tr('Billing souhrn:', 'Billing Summary:')}**")
    disp = billing_del[['Category_Full', 'pocet_hu', 'pocet_to', 'Bilance']].copy()
    disp.columns = [tr('Kategorie', 'Category'), tr('HU', 'HU'), tr('TO', 'TO'), tr('Bilance', 'Balance')]
    st.dataframe(disp, use_container_width=True, hide_index=True)

    # HU details
    if df_hu_details is not None and not df_hu_details.empty:
        st.markdown(f"**{tr('HU záznamy:', 'HU Records:')}**")
        hu_del = df_hu_details[df_hu_details['Clean_Del'] == sel_del]
        if not hu_del.empty:
            st.dataframe(hu_del, use_container_width=True, hide_index=True)
        else:
            st.info(tr("Žádné HU detaily pro tuto zakázku.", "No HU details for this delivery."))


@fast_render
def _render_times_vs_moves(billing_df: pd.DataFrame, df_oe):
    """Korelace fyzických pohybů s časy balení z OE-Times."""
    st.markdown(f"#### {tr('Časy balení vs pohyby', 'Packing Times vs Moves')}")

    if df_oe is None or df_oe.empty:
        st.info(tr("OE-Times data nejsou k dispozici.", "OE-Times data not available."))
        return

    if billing_df is None or billing_df.empty:
        st.info(tr("Billing data nejsou k dispozici.", "Billing data not available."))
        return

    # Merge billing s OE
    b = billing_df.groupby('Delivery').agg(
        pohyby=('pohyby_celkem', 'sum'),
        hu=('pocet_hu', 'sum'),
        to=('pocet_to', 'sum'),
        month=('Month', 'first')
    ).reset_index()

    df_oe_m = df_oe.copy()
    df_oe_m['Delivery'] = df_oe_m['Delivery'].astype(str).str.strip()

    merged = pd.merge(b, df_oe_m[['Delivery', 'Process_Time_Min']], on='Delivery', how='inner')

    if merged.empty:
        st.warning(tr("Nelze propojit billing s OE-Times (žádné shody).",
                      "Cannot merge billing with OE-Times (no matches)."))
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.metric(tr("Zakázek s časem", "Orders with Time"), f"{len(merged):,}")
    with c2:
        avg_min_per_hu = merged['Process_Time_Min'].sum() / merged['hu'].sum() if merged['hu'].sum() > 0 else 0
        with st.container(border=True):
            st.metric(tr("Prům. min/HU", "Avg min/HU"), f"{avg_min_per_hu:.2f}")
    with c3:
        avg_min_per_move = merged['Process_Time_Min'].sum() / merged['pohyby'].sum() if merged['pohyby'].sum() > 0 else 0
        with st.container(border=True):
            st.metric(tr("Prům. min/pohyb", "Avg min/move"), f"{avg_min_per_move:.2f}")

    # Scatter pohyby vs čas
    st.divider()
    fig_sc = px.scatter(
        merged, x='pohyby', y='Process_Time_Min',
        color='month' if 'month' in merged.columns else None,
        labels={
            'pohyby':          tr('Fyzické pohyby', 'Physical Moves'),
            'Process_Time_Min': tr('Čas balení (min)', 'Packing Time (min)'),
            'month':            tr('Měsíc', 'Month')
        },
        trendline='ols',
        opacity=0.7
    )
    fig_sc.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                          margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_sc, use_container_width=True)

    # Distribuce časů
    fig_hist = px.histogram(
        merged, x='Process_Time_Min', nbins=40,
        labels={'Process_Time_Min': tr('Čas balení (min)', 'Packing Time (min)')},
        color_discrete_sequence=['#3b82f6']
    )
    fig_hist.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                            margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_hist, use_container_width=True)

    # Export
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        merged.to_excel(w, index=False, sheet_name='Times_vs_Moves')
    st.download_button(
        tr("⬇️ Export časy vs pohyby", "⬇️ Export Times vs Moves"),
        data=buf.getvalue(),
        file_name="times_vs_moves.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.spec"
    )