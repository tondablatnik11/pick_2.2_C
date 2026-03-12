import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import tr, safe_hu, safe_del, detect_vekp_columns, detect_vepo_columns

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f


# ==========================================
# CACHEOVANÁ BILLING LOGIKA
# ==========================================

@st.cache_data(show_spinner=False)
def cached_billing_logic(df_pick, df_vekp, df_vepo, df_cats,
                         queue_count_col: str,
                         voll_cache_key: tuple,   # OPRAVA: tuple místo set → deterministické hashování
                         raw: dict):              # OPRAVA: raw dict místo opakovaných load_from_db volání
    """
    Kompletní fakturační logika. Výsledek je cachován dokud se nezmění vstupy.

    OPRAVY oproti cached_billing_logic_v28:
    - voll_cache_key je tuple (sorted) → cache funguje deterministicky
    - Pomocná data (LIKP, KEP, VBPA) přijímají přes 'raw' slovník → žádné
      duplicitní load_from_db volání uvnitř cacheované funkce
    - HU strom se předpočítá jednou (build_leaves_cache) → O(n) místo O(n²)
    - Funkce vrací (billing_df, df_hu_details) – stejné API jako v28
    """
    # Rekonstrukce voll_set z cache key
    voll_set: set = set(voll_cache_key)

    billing_df    = pd.DataFrame()
    df_hu_details = pd.DataFrame()

    if df_vekp is None or df_vekp.empty:
        return billing_df, df_hu_details

    # ---------------------------------------------------------
    # 1. PŘÍPRAVA VEKP (centralizovaná detekce sloupců)
    # ---------------------------------------------------------
    vekp_cols = detect_vekp_columns(df_vekp)
    col_hu_int = vekp_cols['hu_int']  or df_vekp.columns[0]
    col_hu_ext = vekp_cols['hu_ext']  or df_vekp.columns[1]
    col_del    = vekp_cols['delivery']
    col_parent = vekp_cols['parent']
    col_date   = vekp_cols['date']

    vekp_clean = df_vekp.copy()
    vekp_clean['Uni_HU_Int'] = vekp_clean[col_hu_int]
    vekp_clean['Uni_Del']    = vekp_clean[col_del] if col_del else np.nan
    vekp_clean = vekp_clean.dropna(subset=['Uni_HU_Int', 'Uni_Del'])
    vekp_clean['Clean_Del']  = vekp_clean['Uni_Del'].apply(safe_del)
    vekp_filtered = vekp_clean[vekp_clean['Clean_Del'] != ''].copy()

    if vekp_filtered.empty:
        return billing_df, df_hu_details

    vekp_filtered['Clean_HU_Int'] = vekp_filtered['Uni_HU_Int'].apply(safe_hu)
    vekp_filtered['Clean_HU_Ext'] = vekp_filtered[col_hu_ext].apply(safe_hu) if col_hu_ext else ''
    vekp_filtered['Clean_Parent'] = vekp_filtered[col_parent].apply(safe_hu) if col_parent else ''

    if col_date:
        vekp_filtered['VEKP_Date']  = pd.to_datetime(vekp_filtered[col_date], errors='coerce')
        vekp_filtered['VEKP_Month'] = (vekp_filtered['VEKP_Date'].dt.to_period('M')
                                       .astype(str).replace('NaT', 'Neznámé'))
    else:
        vekp_filtered['VEKP_Month'] = 'Neznámé'

    del_vekp_month = vekp_filtered.groupby('Clean_Del')['VEKP_Month'].first().to_dict()
    int_to_ext     = dict(zip(vekp_filtered['Clean_HU_Int'], vekp_filtered['Clean_HU_Ext']))

    # ---------------------------------------------------------
    # 2. PŘÍPRAVA PICK DAT
    # ---------------------------------------------------------
    df_pick_billing   = pd.DataFrame()
    picked_mats_by_del = {}
    if df_pick is not None and not df_pick.empty:
        df_pick_billing = df_pick.copy()
        df_pick_billing['Clean_Del'] = df_pick_billing['Delivery'].apply(safe_del)
        picked_mats_by_del = (df_pick_billing.groupby('Clean_Del')['Material']
                               .apply(lambda x: set(x.astype(str).str.strip()))
                               .to_dict())
        if 'Pohyby_Rukou' not in df_pick_billing.columns:
            df_pick_billing['Pohyby_Rukou'] = 0

        # Vollpalette flag per řádek
        def _is_row_voll(row):
            d  = row['Clean_Del']
            hu = safe_hu(row.get('Handling Unit', ''))
            if not hu:
                hu = safe_hu(row.get('Source storage unit', ''))
            return (d, hu) in voll_set

        df_pick_billing['Is_Vollpalette'] = df_pick_billing.apply(_is_row_voll, axis=1)

    # ---------------------------------------------------------
    # 3. KATEGORIE ZAKÁZEK (df_cats → LIKP → KEP/VBPA)
    # ---------------------------------------------------------
    del_base_map: dict = {}

    if df_cats is not None and not df_cats.empty:
        c_del_cats = next(
            (c for c in df_cats.columns
             if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka', 'dodávka', 'zakazka', 'dodavka']),
            df_cats.columns[0]
        )
        c_kat = next(
            (c for c in df_cats.columns
             if 'kategorie' in str(c).lower() or 'category' in str(c).lower()),
            None
        )
        if c_del_cats and c_kat:
            for _, r in df_cats.iterrows():
                d = safe_del(r[c_del_cats])
                val = str(r[c_kat]).strip().upper()
                if val in ('N', 'E', 'O', 'OE'):
                    del_base_map[d] = val

    # LIKP → Versandstelle
    del_vs_map: dict = {}
    df_likp = raw.get('raw_likp')
    if df_likp is not None and not df_likp.empty:
        c_lief = next(
            (c for c in df_likp.columns
             if any(kw in str(c).lower() for kw in ['delivery', 'lieferung', 'dodávka', 'zakázka'])),
            df_likp.columns[0]
        )
        c_vs = next(
            (c for c in df_likp.columns
             if any(kw in str(c).lower()
                    for kw in ['shipping point', 'versandstelle', 'receiving pt', 'místo'])),
            None
        )
        if c_vs:
            del_vs_map = {safe_del(r[c_lief]): str(r[c_vs]).strip().upper()
                          for _, r in df_likp.iterrows()}

    # KEP dopravci
    kep_carriers: set = set()
    df_kep = raw.get('aus_sdshp_am2')
    if df_kep is not None and not df_kep.empty:
        c_sped = next((c for c in df_kep.columns if "Spediteur" in str(c)), df_kep.columns[0])
        c_kep  = next((c for c in df_kep.columns if "KEP" in str(c)), None)
        if c_kep:
            kep_carriers = {
                str(r[c_sped]).strip().lstrip('0')
                for _, r in df_kep.iterrows()
                if str(r[c_kep]).strip().upper() == 'X'
            }

    del_is_kep: dict = {}
    df_vbpa = raw.get('aus_vbpa')
    if df_vbpa is not None and not df_vbpa.empty:
        c_beleg = next(
            (c for c in df_vbpa.columns
             if 'Vertriebsbeleg' in str(c) or 'Delivery' in str(c)),
            df_vbpa.columns[0]
        )
        c_role = next((c for c in df_vbpa.columns if 'Partnerrolle' in str(c) or 'Partner Function' in str(c)), None)
        c_kred = next((c for c in df_vbpa.columns if 'Kreditor' in str(c) or 'Vendor' in str(c)), None)
        c_deb  = next((c for c in df_vbpa.columns if 'Debitor' in str(c) or 'Customer' in str(c)), None)
        if c_role and (c_kred or c_deb):
            for _, r in df_vbpa.iterrows():
                if str(r[c_role]).strip().upper() in ('SP', 'CR'):
                    sped = str(r.get(c_kred, r.get(c_deb, ''))).strip().lstrip('0')
                    if sped in kep_carriers:
                        del_is_kep[safe_del(r[c_beleg])] = True

    # Doplnění chybějících kategorií
    all_active_dels = vekp_filtered['Clean_Del'].unique()
    for d in all_active_dels:
        if d in del_base_map:
            continue
        vs     = del_vs_map.get(d, '')
        is_kep = del_is_kep.get(d, False)

        if vs == 'FM20':   base = 'N'
        elif vs == 'FM21': base = 'E'
        elif vs == 'FM22': base = 'E'
        elif vs == 'FM23': base = 'N'
        elif vs == 'FM24': base = 'O'
        else:              base = 'N'

        if is_kep:
            if base == 'N': base = 'E'
            if base == 'O': base = 'OE'
        elif not df_pick_billing.empty:
            grp = df_pick_billing[df_pick_billing['Clean_Del'] == d]
            if not grp.empty:
                all_queues  = set(grp['Queue'].dropna().astype(str).str.upper().unique())
                has_pallet  = any(q in {'PI_PL', 'PI_PL_OE', 'FU', 'FU_O', 'FUOE', 'PI_PL_FU'} for q in all_queues)
                has_parcel  = 'PI_PA' in all_queues or 'PI_PA_OE' in all_queues
                if has_parcel and not has_pallet:
                    if base == 'N': base = 'E'
                    if base == 'O': base = 'OE'

        del_base_map[d] = base

    # ---------------------------------------------------------
    # 4. VEPO – MATERIÁLY PER HU
    # ---------------------------------------------------------
    vepo_mats: dict = {}
    if df_vepo is not None and not df_vepo.empty:
        vepo_cols = detect_vepo_columns(df_vepo)
        v_hu_col  = vepo_cols['hu_int']
        v_mat_col = vepo_cols['material']
        if v_hu_col and v_mat_col:
            for _, r in df_vepo.dropna(subset=[v_hu_col, v_mat_col]).iterrows():
                h = safe_hu(r[v_hu_col])
                m = str(r[v_mat_col]).strip()
                if h:
                    vepo_mats.setdefault(h, set()).add(m)

    # ---------------------------------------------------------
    # 5. HU STROM – PŘEDPOČÍTANÝ (O(n) místo O(n²))
    # ---------------------------------------------------------
    parent_map   = dict(zip(vekp_filtered['Clean_HU_Int'], vekp_filtered['Clean_Parent']))
    children_map: dict = {}
    for child, parent in parent_map.items():
        if parent:
            children_map.setdefault(parent, []).append(child)

    def _build_leaves_cache(children_map: dict) -> dict:
        """
        Předpočítá listy (leaf nodes) pro každý uzel stromu HU hierarchie.

        OPRAVA výkonu: Původní get_leaves() byla rekurzivní funkce volaná
        pro každou HU zvlášť → O(n²) v nejhorším případě + riziko RecursionError
        na hluboké hierarchii.

        Tato funkce projde celý strom iterativně jednou → O(n).
        Výsledek je dict {node: [leaf1, leaf2, ...]} pro všechny uzly.
        """
        all_nodes = set(children_map.keys()) | {c for kids in children_map.values() for c in kids}
        leaf_cache: dict = {}

        def get_leaves_iter(start_node: str) -> list:
            if start_node in leaf_cache:
                return leaf_cache[start_node]
            stack   = [start_node]
            path    = []
            visited = set()
            leaves  = []
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                kids = children_map.get(node, [])
                if not kids:
                    leaves.append(node)
                else:
                    stack.extend(kids)
                    path.append(node)
            # Uložíme výsledek pro tento uzel i všechny na cestě
            for p in path:
                if p not in leaf_cache:
                    leaf_cache[p] = leaves
            leaf_cache[start_node] = leaves
            return leaves

        for node in all_nodes:
            if node not in leaf_cache:
                get_leaves_iter(node)

        return leaf_cache

    leaves_cache = _build_leaves_cache(children_map)

    # ---------------------------------------------------------
    # 6. VYÚČTOVÁNÍ – GOLDEN LOGIC (Root HU only)
    # ---------------------------------------------------------
    del_hu_counts  = []
    del_mat_cats: dict  = {}
    hu_details_list = []

    root_df = vekp_filtered[vekp_filtered['Clean_Parent'] == '']

    for d, grp in root_df.groupby('Clean_Del'):
        base = del_base_map.get(d, 'N')
        valid_picked_mats = picked_mats_by_del.get(d, set())

        for _, r in grp.iterrows():
            ext_hu  = r['Clean_HU_Ext']
            root_hu = r['Clean_HU_Int']
            leaves  = leaves_cache.get(root_hu, [root_hu])

            # Vollpalette check
            is_voll = (
                (d, ext_hu)  in voll_set or
                (d, root_hu) in voll_set or
                any((d, lf) in voll_set or (d, int_to_ext.get(lf, '')) in voll_set
                    for lf in leaves)
            )

            # Materiály přes VEPO
            mats = set()
            for lf in leaves:
                mats.update(vepo_mats.get(lf, set()))
            real_mats = {m for m in mats if m in valid_picked_mats} or mats

            if is_voll:
                cat = f"{base} Vollpalette"
                if base == 'OE': cat = 'O Vollpalette'
                if base == 'E':  cat = 'N Vollpalette'
            else:
                if not real_mats:
                    continue
                cat = (f"{base} Sortenrein" if len(real_mats) == 1
                       else f"{base} Misch")

            del_hu_counts.append({'Clean_Del': d, 'Category_Full': cat, 'pocet_hu': 1})
            hu_details_list.append({
                'Clean_Del': d, 'HU_Ext': ext_hu, 'HU_Int': root_hu,
                'Is_Vollpalette': 'ANO' if is_voll else 'NE',
                'Category_Full': cat,
                'Materials': ', '.join(real_mats)
            })
            for m in real_mats:
                del_mat_cats.setdefault((d, m), set()).add(cat)

    # Agregace HU počtů
    df_hu_counts = pd.DataFrame(del_hu_counts)
    if not df_hu_counts.empty:
        df_hu_counts = (df_hu_counts.groupby(['Clean_Del', 'Category_Full'])
                        .size().reset_index(name='pocet_hu'))
    else:
        df_hu_counts = pd.DataFrame(columns=['Clean_Del', 'Category_Full', 'pocet_hu'])

    df_hu_details = pd.DataFrame(hu_details_list)

    # ---------------------------------------------------------
    # 7. PICK AGREGACE
    # ---------------------------------------------------------
    if not df_pick_billing.empty:
        non_voll_mats = (df_pick_billing[~df_pick_billing['Is_Vollpalette']]
                         .groupby('Clean_Del')['Material'].nunique().to_dict())

        def _get_full_category(row):
            d    = row['Clean_Del']
            base = del_base_map.get(d, 'N')
            if row['Is_Vollpalette']:
                if base == 'OE': return 'O Vollpalette'
                if base == 'E':  return 'N Vollpalette'
                return f"{base} Vollpalette"
            mat  = str(row.get('Material', '')).strip()
            cats = {c for c in del_mat_cats.get((d, mat), set()) if 'Vollpalette' not in c}
            if len(cats) == 1: return list(cats)[0]
            if len(cats) > 1:  return f"{base} Misch"
            return (f"{base} Misch" if non_voll_mats.get(d, 1) > 1
                    else f"{base} Sortenrein")

        df_pick_billing['Category_Full'] = df_pick_billing.apply(_get_full_category, axis=1)
        pick_agg = df_pick_billing.groupby(['Clean_Del', 'Category_Full']).agg(
            pocet_to=(queue_count_col, 'nunique'),
            pohyby_celkem=('Pohyby_Rukou', 'sum'),
            pocet_lokaci=('Source Storage Bin', 'nunique'),
            pocet_mat=('Material', 'nunique')
        ).reset_index()
    else:
        pick_agg = pd.DataFrame(
            columns=['Clean_Del', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_lokaci', 'pocet_mat'])

    # ---------------------------------------------------------
    # 8. FINÁLNÍ MERGE
    # ---------------------------------------------------------
    billing_df = pd.merge(df_hu_counts, pick_agg, on=['Clean_Del', 'Category_Full'], how='outer')
    billing_df['Delivery']       = billing_df['Clean_Del']
    billing_df['Clean_Del_Merge'] = billing_df['Clean_Del']

    if not df_pick_billing.empty:
        del_meta = df_pick_billing.groupby('Clean_Del').agg(
            Month=('Month', 'first'),
            hlavni_fronta=('Queue', lambda x: x.mode()[0] if not x.empty else '')
        ).to_dict('index')
        billing_df['Month'] = billing_df['Clean_Del'].apply(
            lambda d: (del_vekp_month.get(d, 'Neznámé')
                       if del_vekp_month.get(d, 'Neznámé') != 'Neznámé'
                       else del_meta.get(d, {}).get('Month', 'Neznámé'))
        )
        billing_df['hlavni_fronta'] = billing_df['Clean_Del'].apply(
            lambda d: del_meta.get(d, {}).get('hlavni_fronta', '')
        )
    else:
        billing_df['Month']         = billing_df['Clean_Del'].map(del_vekp_month).fillna('Neznámé')
        billing_df['hlavni_fronta'] = ''

    for col in ['pocet_to', 'pohyby_celkem', 'pocet_lokaci', 'pocet_hu', 'pocet_mat']:
        billing_df[col] = billing_df[col].fillna(0).astype(int)

    billing_df['Bilance']   = (billing_df['pocet_to'] - billing_df['pocet_hu']).astype(int)
    billing_df['TO_navic']  = billing_df['Bilance'].clip(lower=0)

    return billing_df, df_hu_details


# ==========================================
# SPOLEHLIVOST DAT
# ==========================================

@fast_render
def render_reliability_report(df_pick, df_vekp, df_vepo, raw: dict):
    if df_vekp is None or df_vekp.empty:
        return

    st.markdown(
        "<div class='section-header'><h3>🛡️ Spolehlivost dat a chybějící záznamy</h3></div>",
        unsafe_allow_html=True
    )

    vekp_cols  = detect_vekp_columns(df_vekp)
    col_hu_int = vekp_cols['hu_int'] or df_vekp.columns[0]
    col_del    = vekp_cols['delivery']

    df_vk = df_vekp.copy()
    df_vk['Clean_Del'] = df_vk[col_del].apply(safe_del) if col_del else ''
    df_vk['Clean_HU']  = df_vk[col_hu_int].apply(safe_hu)

    all_dels  = df_vk[df_vk['Clean_Del'] != '']['Clean_Del'].unique()
    pick_dels = set(df_pick['Delivery'].apply(safe_del)) if df_pick is not None else set()

    likp_dels: set = set()
    df_likp = raw.get('raw_likp')
    if df_likp is not None and not df_likp.empty:
        c_likp_del = next(
            (c for c in df_likp.columns
             if any(kw in str(c).lower() for kw in ['delivery', 'lieferung', 'dodávka', 'zakázka'])),
            df_likp.columns[0]
        )
        likp_dels = set(df_likp[c_likp_del].apply(safe_del))

    vepo_hus: set = set()
    if df_vepo is not None and not df_vepo.empty:
        vepo_cols = detect_vepo_columns(df_vepo)
        col_vh    = vepo_cols['hu_int']
        if col_vh:
            vepo_hus = set(df_vepo[col_vh].apply(safe_hu))

    del_hu_map = df_vk.groupby('Clean_Del')['Clean_HU'].apply(set).to_dict()
    missing_data = []
    for d in all_dels:
        has_pick = d in pick_dels
        has_likp = d in likp_dels
        has_vepo = bool(del_hu_map.get(d, set()).intersection(vepo_hus))
        if not (has_pick and has_likp and has_vepo):
            missing_data.append({
                'Zakázka (Delivery)': d,
                'Pick Report (TO)': '✅ OK' if has_pick else '❌ Chybí',
                'LIKP (Brány)': '✅ OK' if has_likp else '❌ Chybí',
                'VEPO (Materiály)': '✅ OK' if has_vepo else '❌ Chybí (Prázdné)',
            })

    total_dels    = len(all_dels)
    perfect_dels  = total_dels - len(missing_data)
    reliability   = (perfect_dels / total_dels * 100) if total_dels > 0 else 0

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Spolehlivost datových podkladů", f"{reliability:.1f} %")
    with col2:
        if missing_data:
            with st.expander(f"⚠️ Zakázky s chybějícími daty ({len(missing_data)})", expanded=False):
                st.dataframe(pd.DataFrame(missing_data), hide_index=True, use_container_width=True)
        else:
            st.success("Perfektní! Všechny fakturované zakázky mají kompletní data.")
    st.divider()


# ==========================================
# RENDER BILLING TAB
# OPRAVA: Přijímá předpočítaná data z app.py (singleton billing výpočet)
# ==========================================

def render_billing(billing_df: pd.DataFrame, df_hu_details: pd.DataFrame,
                   df_vekp=None, df_vepo=None):
    """
    Vykreslí fakturační záložku.

    OPRAVA: Billing logika se NEPOČÍTÁ zde znovu. Data jsou předána jako parametry
    z centrálního výpočtu v app.py. render_billing je nyní čistě vizualizační funkce.
    """

    st.markdown(
        f"<div class='section-header'><h3>💰 {tr('Korelace mezi Pickováním a Účtováním', 'Correlation Between Picking and Billing')}</h3>"
        f"<p>{tr('Zákazník platí podle počtu výsledných balících jednotek (HU).', 'The customer pays based on the number of billed HUs.')}</p></div>",
        unsafe_allow_html=True
    )

    if billing_df is None or billing_df.empty:
        st.info(tr("Data fakturace nejsou k dispozici. Zkontrolujte nahrané soubory VEKP a VEPO.",
                   "Billing data not available. Check uploaded VEKP and VEPO files."))
        return billing_df

    # Diagnostika VEKP/VEPO
    if df_vekp is not None and not df_vekp.empty:
        vekp_cols = detect_vekp_columns(df_vekp)
        if not vekp_cols.get('delivery'):
            st.error(
                f"🚨 **Kritická chyba:** Aplikace nedokáže ve VEKP najít sloupec se zakázkou.\n\n"
                f"**Sloupce ve VEKP:** `{list(df_vekp.columns)}`"
            )
            return pd.DataFrame()

    if df_vepo is not None and not df_vepo.empty:
        vepo_cols = detect_vepo_columns(df_vepo)
        if not vepo_cols.get('material'):
            st.error(
                f"🚨 **Kritická chyba:** Aplikace nedokáže ve VEPO najít sloupec pro Materiál.\n\n"
                f"**Sloupce ve VEPO:** `{list(df_vepo.columns)}`"
            )
            return pd.DataFrame()

    # --- KPI METRIKY ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True):
            st.metric(tr("Zakázek celkem", "Total Orders"), f"{billing_df['Delivery'].nunique():,}")
    with c2:
        with st.container(border=True):
            st.metric(tr("Fakturované HU", "Billed HUs"), f"{int(billing_df['pocet_hu'].sum()):,}")
    with c3:
        with st.container(border=True):
            st.metric(tr("Fyzických Pick TO", "Physical Pick TOs"), f"{int(billing_df['pocet_to'].sum()):,}")
    with c4:
        net_diff   = int(billing_df['Bilance'].sum())
        loss_total = int(billing_df['TO_navic'].sum())
        profit_total = loss_total - net_diff
        with st.container(border=True):
            st.metric(
                tr("Čistá bilance (TO - HU)", "Net Balance (TO - HU)"),
                f"{net_diff:,}",
                help=tr(
                    f"Kladné = Prodělek. Ztráta: {loss_total:,} picků, Úspora: {profit_total:,} picků.",
                    f"Positive = Loss. Loss: {loss_total:,} picks, Savings: {profit_total:,} picks."
                )
            )

    st.divider()
    col_t1, col_t2 = st.columns([1.2, 1])

    with col_t1:
        st.markdown(f"**{tr('Souhrn podle kategorií (Zisky a Ztráty)', 'Summary by Categories (Profit & Loss)')}**")

        cat_sum = billing_df.groupby('Category_Full').agg(
            pocet_casti=('Delivery', 'count'),
            pocet_to=('pocet_to', 'sum'),
            pocet_hu=('pocet_hu', 'sum'),
            pocet_lok=('pocet_lokaci', 'sum'),
            poh=('pohyby_celkem', 'sum'),
            bilance=('Bilance', 'sum'),
            to_navic=('TO_navic', 'sum')
        ).reset_index()
        cat_sum['prum_poh'] = np.where(
            cat_sum['pocet_lok'] > 0,
            cat_sum['poh'] / cat_sum['pocet_lok'], 0
        )

        disp = cat_sum[['Category_Full', 'pocet_casti', 'pocet_to', 'pocet_hu', 'prum_poh', 'bilance', 'to_navic']].copy()
        disp.columns = [
            tr("Kategorie HU", "HU Category"),
            tr("Části zakázek", "Order Parts"),
            tr("Počet TO", "Total TO"),
            tr("Zúčtované HU", "Billed HU"),
            tr("Prům. pohybů na lokaci", "Avg Moves/Location"),
            tr("Čistá bilance", "Net Balance"),
            tr("Hrubá ztráta", "Gross Loss"),
        ]
        st.dataframe(
            disp.style.format({tr("Prům. pohybů na lokaci", "Avg Moves/Location"): "{:.1f}"}),
            use_container_width=True, hide_index=True
        )

        st.markdown(f"<br>**🔍 {tr('Detail podle kategorie:', 'Category Detail:')}**", unsafe_allow_html=True)
        cat_opts = [tr("— Vyberte kategorii —", "— Select Category —")] + sorted(
            billing_df['Category_Full'].dropna().unique().tolist())
        sel_cat = st.selectbox("Vyberte", options=cat_opts, label_visibility="collapsed")

        if sel_cat != tr("— Vyberte kategorii —", "— Select Category —"):
            det_df = billing_df[billing_df['Category_Full'] == sel_cat].copy()
            det_df['prum_poh_lok'] = np.where(
                det_df['pocet_lokaci'] > 0,
                det_df['pohyby_celkem'] / det_df['pocet_lokaci'], 0
            )
            det_df = det_df.sort_values('Bilance', ascending=False)
            disp_det = det_df[['Delivery', 'pocet_to', 'pocet_hu', 'prum_poh_lok', 'Bilance']].copy()
            disp_det.columns = [
                tr("Zakázka", "Order"), tr("Počet TO", "Total TO"),
                tr("Zabalené HU", "Packed HU"), tr("Pohybů/lok.", "Moves/Loc"),
                tr("Bilance", "Balance"),
            ]

            def _color_bilance(val):
                try:
                    if val > 0: return 'color: #ef4444; font-weight: bold'
                    if val < 0: return 'color: #10b981; font-weight: bold'
                except Exception:
                    pass
                return ''

            try:
                styled = disp_det.style.format({tr("Pohybů/lok.", "Moves/Loc"): "{:.1f}"}).map(
                    _color_bilance, subset=[tr("Bilance", "Balance")])
            except AttributeError:
                styled = disp_det.style.format({tr("Pohybů/lok.", "Moves/Loc"): "{:.1f}"}).applymap(
                    _color_bilance, subset=[tr("Bilance", "Balance")])
            st.dataframe(styled, use_container_width=True, hide_index=True)

    with col_t2:
        st.markdown(f"**{tr('Trend v čase (Měsíce)', 'Trend over Time (Months)')}**")

        @fast_render
        def _interactive_chart():
            cat_options = [tr("Všechny kategorie", "All Categories")] + sorted(
                billing_df['Category_Full'].dropna().unique().tolist())
            selected_cat = st.selectbox(
                tr("Kategorie:", "Category:"),
                options=cat_options,
                label_visibility="collapsed",
                key="billing_chart_cat"
            )
            plot_df = billing_df if selected_cat == tr("Všechny kategorie", "All Categories") \
                else billing_df[billing_df['Category_Full'] == selected_cat]

            tr_df = plot_df.groupby('Month').agg(
                to_sum=('pocet_to', 'sum'),
                hu_sum=('pocet_hu', 'sum'),
                poh=('pohyby_celkem', 'sum'),
                lok=('pocet_lokaci', 'sum')
            ).reset_index()
            tr_df['prum_poh'] = np.where(tr_df['lok'] > 0, tr_df['poh'] / tr_df['lok'], 0)

            fig = go.Figure()
            fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['to_sum'],
                                 name=tr('Počet TO', 'Total TOs'), marker_color='#38bdf8',
                                 text=tr_df['to_sum'], textposition='auto'))
            fig.add_trace(go.Bar(x=tr_df['Month'], y=tr_df['hu_sum'],
                                 name=tr('Počet HU', 'Total HUs'), marker_color='#818cf8',
                                 text=tr_df['hu_sum'], textposition='auto'))
            fig.add_trace(go.Scatter(x=tr_df['Month'], y=tr_df['prum_poh'],
                                     name=tr('Pohyby na lokaci', 'Moves per Loc'),
                                     yaxis='y2', mode='lines+markers+text',
                                     text=tr_df['prum_poh'].round(1), textposition='top center',
                                     textfont=dict(color='#f43f5e'),
                                     line=dict(color='#f43f5e', width=3)))
            fig.update_layout(
                yaxis2=dict(title=tr("Pohyby", "Moves"), side="right", overlaying="y", showgrid=False),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
            )
            st.plotly_chart(fig, use_container_width=True)

        _interactive_chart()

    # --- MASTER DATA TABULKA ---
    st.divider()
    st.markdown(f"### 💎 {tr('Analýza efektivity (Master Data)', 'Efficiency Analysis (Master Data)')}")

    with st.expander(f"📖 {tr('Vysvětlení sloupců', 'Column Explanations')}"):
        st.markdown(tr(
            "* **Index konsolidace (TO/HU):** Kolik TO na 1 vyfakturovanou HU. Ideál = 1.0.\n"
            "* **Fyzické pohyby na 1 HU:** Reálné pohyby rukou na 1 fakturovanou jednotku.\n"
            "* **1:1 (Ideál):** Zakázky kde 1 TO = 1 HU.\n"
            "* **Více TO (Proděly):** Více picků slitých do méně palet.\n"
            "* **Více HU (Zisky):** 1 pick rozpadlý do více fakturovaných jednotek.",
            "* **Consolidation Index (TO/HU):** TOs per billed HU. Ideal = 1.0.\n"
            "* **Physical Moves per HU:** Real hand moves per billed unit.\n"
            "* **1:1 (Ideal):** Orders where 1 TO = 1 HU.\n"
            "* **More TO (Loss):** Multiple picks merged into fewer pallets.\n"
            "* **More HU (Profit):** 1 pick split into multiple billed units."
        ))

    billing_df['is_1_to_1']  = (billing_df['pocet_to'] == billing_df['pocet_hu']).astype(int)
    billing_df['is_more_to'] = (billing_df['pocet_to'] > billing_df['pocet_hu']).astype(int)
    billing_df['is_more_hu'] = (billing_df['pocet_to'] < billing_df['pocet_hu']).astype(int)
    billing_df['ztrata_to']  = np.where(billing_df['is_more_to'], billing_df['pocet_to'] - billing_df['pocet_hu'], 0)
    billing_df['zisk_hu']    = np.where(billing_df['is_more_hu'], billing_df['pocet_hu'] - billing_df['pocet_to'], 0)

    ratio_table = billing_df.groupby('Category_Full').agg(
        celkem=('Delivery', 'count'),
        to_celkem=('pocet_to', 'sum'),
        hu_celkem=('pocet_hu', 'sum'),
        pohyby_celkem=('pohyby_celkem', 'sum'),
        count_1_1=('is_1_to_1', 'sum'),
        count_more_to=('is_more_to', 'sum'),
        ztrata_to=('ztrata_to', 'sum'),
        count_more_hu=('is_more_hu', 'sum'),
        zisk_hu=('zisk_hu', 'sum')
    ).reset_index()

    def _fmt_pct(count, total):
        return "0 (0.0%)" if total == 0 else f"{int(count)} ({count/total*100:.1f}%)"

    ratio_table['1:1 (Ideál)']     = ratio_table.apply(lambda r: _fmt_pct(r['count_1_1'],     r['celkem']), axis=1)
    ratio_table['Více TO (Počet)'] = ratio_table.apply(lambda r: _fmt_pct(r['count_more_to'], r['celkem']), axis=1)
    ratio_table['Více HU (Počet)'] = ratio_table.apply(lambda r: _fmt_pct(r['count_more_hu'], r['celkem']), axis=1)
    ratio_table['Index (TO/HU)']   = np.where(ratio_table['hu_celkem'] > 0,
                                               ratio_table['to_celkem'] / ratio_table['hu_celkem'], 0)
    ratio_table['Pohyby/HU']       = np.where(ratio_table['hu_celkem'] > 0,
                                               ratio_table['pohyby_celkem'] / ratio_table['hu_celkem'], 0)
    ratio_table['Čistá bilance']   = ratio_table['hu_celkem'] - ratio_table['to_celkem']

    disp_ratio = ratio_table[[
        'Category_Full', 'celkem', 'to_celkem', 'hu_celkem',
        'Index (TO/HU)', 'Pohyby/HU',
        '1:1 (Ideál)', 'Více TO (Počet)', 'ztrata_to',
        'Více HU (Počet)', 'zisk_hu', 'Čistá bilance'
    ]].copy()
    disp_ratio.columns = [
        tr("Kategorie HU", "HU Category"),
        tr("Částí zakázek", "Order Parts"),
        tr("TO Celkem", "Total TO"),
        tr("HU Celkem", "Total HU"),
        tr("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"),
        tr("Fyzické pohyby / HU", "Physical Moves / HU"),
        tr("1:1 (Ideál)", "1:1 (Ideal)"),
        tr("Více TO (Prodělaly)", "More TO (Loss)"),
        tr("Ztráta (ks TO)", "Loss (pcs TO)"),
        tr("Více HU (Vydělaly)", "More HU (Profit)"),
        tr("Zisk (ks HU)", "Profit (pcs HU)"),
        tr("Čistá bilance (HU - TO)", "Net Balance (HU - TO)"),
    ]

    def _style_master(val):
        try:
            if isinstance(val, (int, float)):
                if val > 0: return 'color: #10b981; font-weight: bold'
                if val < 0: return 'color: #ef4444; font-weight: bold'
        except Exception:
            pass
        return ''

    try:
        styled_m = disp_ratio.style.format({
            tr("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO",
            tr("Fyzické pohyby / HU", "Physical Moves / HU"): "{:.1f}",
            tr("Ztráta (ks TO)", "Loss (pcs TO)"): "- {}",
            tr("Zisk (ks HU)", "Profit (pcs HU)"): "+ {}",
        }).map(_style_master, subset=[tr("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])
    except AttributeError:
        styled_m = disp_ratio.style.format({
            tr("Index konsolidace (TO/HU)", "Consolidation Index (TO/HU)"): "{:.2f} TO",
            tr("Fyzické pohyby / HU", "Physical Moves / HU"): "{:.1f}",
        }).applymap(_style_master, subset=[tr("Čistá bilance (HU - TO)", "Net Balance (HU - TO)")])

    st.dataframe(styled_m, use_container_width=True, hide_index=True)

    # --- Trend ratio graf ---
    st.markdown(f"<br>**{tr('Trend typů zakázek (Měsíce)', 'Trend of Order Types (Months)')}**",
                unsafe_allow_html=True)
    all_trend_cats = sorted(billing_df['Category_Full'].dropna().unique().tolist())
    sel_trend_cats = st.multiselect(
        tr("Vyberte kategorie:", "Select categories:"),
        options=all_trend_cats, default=all_trend_cats, key="trend_ratio_cats"
    )

    if sel_trend_cats:
        trend_filt = billing_df[billing_df['Category_Full'].isin(sel_trend_cats)].copy()
        trend_r = trend_filt.groupby('Month').agg(
            count_1_1=('is_1_to_1', 'sum'),
            count_more_to=('is_more_to', 'sum'),
            count_more_hu=('is_more_hu', 'sum')
        ).reset_index()
        trend_r['total'] = trend_r[['count_1_1', 'count_more_to', 'count_more_hu']].sum(axis=1)
        for col in ['count_1_1', 'count_more_to', 'count_more_hu']:
            trend_r[f'pct_{col}'] = np.where(trend_r['total'] > 0,
                                               trend_r[col] / trend_r['total'] * 100, 0)

        fig_r = go.Figure()
        fig_r.add_trace(go.Bar(x=trend_r['Month'], y=trend_r['count_1_1'],
                                name=tr('1:1 (Kusy)', '1:1 (Pcs)'), marker_color='rgba(16,185,129,0.5)',
                                text=trend_r['count_1_1'], textposition='inside'))
        fig_r.add_trace(go.Bar(x=trend_r['Month'], y=trend_r['count_more_hu'],
                                name=tr('Více HU', 'More HU'), marker_color='rgba(59,130,246,0.5)',
                                text=trend_r['count_more_hu'], textposition='inside'))
        fig_r.add_trace(go.Bar(x=trend_r['Month'], y=trend_r['count_more_to'],
                                name=tr('Více TO', 'More TO'), marker_color='rgba(239,68,68,0.5)',
                                text=trend_r['count_more_to'], textposition='inside'))
        fig_r.add_trace(go.Scatter(x=trend_r['Month'], y=trend_r['pct_count_1_1'],
                                    name=tr('1:1 (%)', '1:1 (%)'), mode='lines+markers+text',
                                    text=trend_r['pct_count_1_1'].round(1).astype(str) + '%',
                                    textposition='top center', marker_color='#10b981',
                                    line=dict(width=3), yaxis='y2'))
        fig_r.add_trace(go.Scatter(x=trend_r['Month'], y=trend_r['pct_count_more_to'],
                                    name=tr('Více TO (%)', 'More TO (%)'), mode='lines+markers+text',
                                    text=trend_r['pct_count_more_to'].round(1).astype(str) + '%',
                                    textposition='bottom center', marker_color='#ef4444',
                                    line=dict(width=3), yaxis='y2'))
        fig_r.update_layout(
            barmode='stack',
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
            yaxis=dict(title=tr("Celkem částí zakázek", "Total Order Parts")),
            yaxis2=dict(title=tr("Podíl (%)", "Share (%)"), side="right", overlaying="y",
                        showgrid=False, range=[0, 110])
        )
        st.plotly_chart(fig_r, use_container_width=True)

    # --- Žebříček neefektivity ---
    st.divider()
    st.markdown(f"### ⚠️ {tr('Žebříček neefektivity (Práce zdarma)', 'Inefficiency Ranking (Free Labor)')}")
    imb_df = billing_df[billing_df['TO_navic'] > 0].sort_values('TO_navic', ascending=False).head(50)
    if not imb_df.empty:
        imb_disp = imb_df[['Delivery', 'Category_Full', 'pocet_to', 'pohyby_celkem', 'pocet_hu', 'TO_navic']].copy()
        imb_disp.columns = [
            tr("Delivery", "Delivery"), tr("Kategorie", "Category"),
            tr("Pick TO celkem", "Total Pick TOs"), tr("Pohyby rukou", "Hand Moves"),
            tr("Účtované HU", "Billed HU"), tr("Prodělek", "Loss"),
        ]
        st.dataframe(imb_disp, use_container_width=True, hide_index=True)
    else:
        st.success(tr("Žádné zakázky s prodělkem!", "No loss-making orders found!"))

    return billing_df