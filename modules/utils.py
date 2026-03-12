import streamlit as st
import pandas as pd
import numpy as np
import re

# ==========================================
# GLOBÁLNÍ DESIGN KONSTANTY
# ==========================================
CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#f8fafc', size=12, family="Inter, sans-serif"),
    colorway=CHART_COLORS,
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified"
)

QUEUE_DESC = {
    'PI_PL (Single)': 'Single SKU Pal',
    'PI_PL (Total)': 'Single SKU Pal + Mix Pal',
    'PI_PL_OE (Single)': 'OE Single SKU Pal',
    'PI_PL_OE (Total)': 'OE Single SKU Pal + Mix Pal',
    'PI_PA_OE': 'OE Parcel',
    'PI_PL (Mix)': 'Mix Pal',
    'PI_PA': 'Parcel',
    'PI_PL_OE (Mix)': 'OE Mix Pal',
    'PI_PA_RU': 'Parcel Express',
    'PI_PL_FU': 'Full Pall',
    'PI_PL_FUOE': 'OE Full Pal'
}

BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

# ==========================================
# PŘEKLADY – CENTRALIZOVANÝ PŘÍSTUP
# ==========================================
TEXTS = {
    'cs': {
        'switch_lang': "🇬🇧 Switch to English", 'title': "🏢 Warehouse Control Tower",
        'desc': "Kompletní End-to-End analýza: od fyzického pickování až po čas balení.",
        'sec_ratio': "🎯 Spolehlivost dat a zdroj výpočtů",
        'ratio_desc': "Z jakých podkladů aplikace vycházela (Ukazatel kvality dat ze SAPu):",
        'logic_explain_title': "ℹ️ Podrobná metodika: Jak aplikace vypočítává výsledná data?",
        'logic_explain_text': (
            "Tento analytický model detailně simuluje fyzickou zátěž skladníka a balení:\n\n"
            "**1. Dekompozice na celá balení (Krabice)**\nSystém matematicky rozdělí množství na plné krabice od největší. "
            "Co krabice, to **1 fyzický pohyb**.\n\n"
            "**2. Analýza volných kusů (Limity)**\nZbylé rozbalené kusy podléhají kontrole ergonomických limitů. "
            "Každý těžký/velký kus = **1 pohyb**, lehké kusy se berou do hrsti.\n\n"
            "**3. Obalová hierarchie (Tree-Climbing)**\nPomocí VEKP a VEPO se aplikace prokouše složitou strukturou "
            "balení až na hlavní kořen (Top-Level HU).\n\n"
            "**4. Časová náročnost (End-to-End)**\nPropojuje zjištěné fyzické pohyby a výsledné palety se záznamy z OE-Times."
        ),
        'ratio_moves': "Podíl z celkového počtu POHYBŮ:",
        'ratio_exact': "Přesně (Krabice / Palety / Volné)", 'ratio_miss': "Odhady (Chybí balení)",
        'sec_queue_title': "📊 Průměrná náročnost dle typu pickování (Queue)",
        'q_col_queue': "Queue", 'q_col_desc': "Popis", 'q_col_to': "Počet TO", 'q_col_orders': "Zakázky",
        'q_col_loc': "Prům. lokací", 'q_col_mov_loc': "Prům. pohybů na lokaci",
        'q_col_exact_loc': "Prům. přesně na lokaci",
        'q_pct_exact': "% Přesně", 'q_col_miss_loc': "Prům. odhad na lokaci", 'q_pct_miss': "% Odhad",
        'tab_dashboard': "📊 Dashboard & Queue", 'tab_pallets': "📦 Palety",
        'tab_fu': "🏭 Celé palety (FU)",
        'tab_top': "🏆 TOP Materiály", 'tab_billing': "💰 Fakturace (VEKP)",
        'tab_packing': "⏱️ Časy Balení (OE)", 'tab_audit': "🔍 Nástroje & Audit",
        'col_mat': "Materiál", 'col_qty': "Kusů celkem", 'col_mov': "Celkem pohybů",
        'col_mov_exact': "Pohyby (Přesně)",
        'col_mov_miss': "Pohyby (Odhady)", 'col_wgt': "Hmotnost (kg)", 'col_max_dim': "Rozměr (cm)",
        'btn_download': "📥 Stáhnout kompletní report (Excel)",
        'unknown': "Neznámá",
    },
    'en': {
        'switch_lang': "🇨🇿 Přepnout do češtiny", 'title': "🏢 Warehouse Control Tower",
        'desc': "End-to-End analysis: from physical picking to packing times.",
        'sec_ratio': "🎯 Data Reliability & Source",
        'ratio_desc': "Data foundation (SAP Data Quality indicator):",
        'logic_explain_title': "ℹ️ Detailed Methodology: How does the app calculate results?",
        'logic_explain_text': (
            "This analytical model meticulously simulates the picker's physical workload and packing:\n\n"
            "**1. Decomposition into Full Boxes**\nQuantities are split into full boxes from largest first. "
            "Each box = **1 physical move**.\n\n"
            "**2. Loose Pieces Analysis**\nRemaining pieces are checked against ergonomic limits. "
            "Heavy/large = **1 move each**, light pieces are grabbed together.\n\n"
            "**3. Packing Hierarchy (Tree-Climbing)**\nUsing VEKP and VEPO, the app climbs through complex nested "
            "packing structures up to the Top-Level HU.\n\n"
            "**4. End-to-End Time**\nCorrelates physical moves and final pallets with OE-Times to analyze packing speed."
        ),
        'ratio_moves': "Share of total MOVEMENTS:",
        'ratio_exact': "Exact (Boxes / Pallets / Loose)", 'ratio_miss': "Estimates (Missing packaging)",
        'sec_queue_title': "📊 Average Workload by Queue",
        'q_col_queue': "Queue", 'q_col_desc': "Description", 'q_col_to': "TO Count",
        'q_col_orders': "Orders",
        'q_col_loc': "Avg Locs", 'q_col_mov_loc': "Avg Moves per Loc",
        'q_col_exact_loc': "Avg Exact per Loc",
        'q_pct_exact': "% Exact", 'q_col_miss_loc': "Avg Estimate per Loc", 'q_pct_miss': "% Estimate",
        'tab_dashboard': "📊 Dashboard & Queue", 'tab_pallets': "📦 Pallet Orders",
        'tab_fu': "🏭 Full Pallets (FU)",
        'tab_top': "🏆 TOP Materials", 'tab_billing': "💰 Billing & Packing (VEKP)",
        'tab_packing': "⏱️ Packing Times (OE)", 'tab_audit': "🔍 Tools & Audit",
        'col_mat': "Material", 'col_qty': "Total Pieces", 'col_mov': "Total Moves",
        'col_mov_exact': "Moves (Exact)",
        'col_mov_miss': "Moves (Estimates)", 'col_wgt': "Weight (kg)", 'col_max_dim': "Max Dim (cm)",
        'btn_download': "📥 Download Comprehensive Report (Excel)",
        'unknown': "Unknown",
    }
}


def t(key):
    """Globální překlad podle aktuálního jazyka v session_state."""
    lang = st.session_state.get('lang', 'cs')
    return TEXTS.get(lang, TEXTS['cs']).get(key, key)


def tr(cs_text: str, en_text: str) -> str:
    """
    Inline překlad – náhrada za lokální _t(cs, en) lambdy v každém tabu.
    Použití: tr("Česky", "English")
    """
    return en_text if st.session_state.get('lang', 'cs') == 'en' else cs_text


# ==========================================
# DETEKCE SLOUPCŮ – CENTRALIZOVANÁ
# ==========================================

def detect_vekp_columns(df: pd.DataFrame) -> dict:
    """
    Detekuje sloupce v VEKP DataFrame a vrátí slovník s unifikovanými názvy.
    Místo ~15 inline list comprehensions v billing/audit/daily_kpi.
    
    Vrací: {
        'hu_int': str | None,
        'hu_ext': str | None,
        'delivery': str | None,
        'parent': str | None,
        'date': str | None,
        'time': str | None,
        'pack_material': str | None,
    }
    """
    cols = list(df.columns)
    cols_lower = [str(c).lower().strip() for c in cols]

    def find_col(patterns: list[str], exact: bool = False) -> str | None:
        for pat in patterns:
            for orig, low in zip(cols, cols_lower):
                if exact:
                    if low == pat:
                        return orig
                else:
                    if pat in low:
                        return orig
        return None

    return {
        'hu_int': find_col(["internal hu", "hu-nummer intern", "internal handling", "manipulační"]) or find_col(["intern"]),
        'hu_ext': find_col(["external hu", "external identification", "extern"]),
        'delivery': find_col(["generated delivery", "generierte lieferung", "vytvořená dodávka", "delivery", "lieferung", "dodávka", "zakázka"]),
        'parent': find_col(["higher-level", "übergeordn", "superordinate", "nadřazen"]),
        'date': find_col(["created on", "erfasst am", "erstelldatum"]),
        'time': find_col(["created at", "uhrzeit", "erfasszeit"]),
        'pack_material': find_col(["packmittel", "packaging material", "pack. mat"]),
    }


def detect_vepo_columns(df: pd.DataFrame) -> dict:
    """Detekuje sloupce v VEPO DataFrame."""
    cols = list(df.columns)
    cols_lower = [str(c).lower().strip() for c in cols]

    def find_col(patterns):
        for pat in patterns:
            for orig, low in zip(cols, cols_lower):
                if pat in low:
                    return orig
        return None

    return {
        'hu_int': find_col(["internal hu", "hu-nummer intern", "intern"]) or cols[0],
        'material': find_col(["material", "materiál"]),
        'qty': find_col(["packed quantity", "vemng", "balené množství", "menge"]),
    }


# ==========================================
# BEZPEČNÉ PARSOVÁNÍ HODNOT
# ==========================================

def safe_hu(val) -> str:
    """Vyčistí HU číslo – odstraní .0, prázdné hodnoty, mezery."""
    v = str(val).strip()
    if v.lower() in ('nan', 'none', ''):
        return ''
    if v.endswith('.0'):
        v = v[:-2]
    return v


def safe_del(val) -> str:
    """
    Vyčistí číslo dodávky – ošetřuje vědeckou notaci (5e+12),
    .0 suffix a leading zeros.
    """
    v = str(val).strip()
    if v.lower() in ('nan', 'none', ''):
        return ''
    # Ošetření vědecké notace (Excel float overflow)
    try:
        f = float(v)
        if f == int(f):
            return str(int(f)).lstrip('0') or ''
    except (ValueError, OverflowError):
        pass
    if v.endswith('.0'):
        v = v[:-2]
    return v.lstrip('0') or ''


# ==========================================
# MATERIÁLOVÉ KLÍČE
# ==========================================

def get_match_key_vectorized(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.upper()
    mask_decimal = s.str.match(r'^\d+\.\d+$')
    s = s.copy()
    s[mask_decimal] = s[mask_decimal].str.rstrip('0').str.rstrip('.')
    mask_numeric = s.str.match(r'^0+\d+$')
    s[mask_numeric] = s[mask_numeric].str.lstrip('0')
    return s


def get_match_key(val) -> str:
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit():
        v = v.rstrip('0').rstrip('.')
    if v.isdigit():
        v = v.lstrip('0') or '0'
    return v


# ==========================================
# OBAL HELPERS
# ==========================================

def is_box(v) -> bool:
    """Vrátí True pokud jde o krabici/KLT (ne paletu)."""
    v = str(v).upper().strip()
    if v == 'CARTON-16':
        return False  # CARTON-16 je velkorozměrná paleta, ne krabice
    if v in ('K1', 'K2', 'K3', 'K4', 'KLT', 'KLT1', 'KLT2'):
        return True
    if v.startswith('K') and len(v) <= 2:
        return True
    if 'CARTON' in v or 'BOX' in v or v in ('CT', 'CD3', 'CD', 'CR'):
        return True
    return False


# ==========================================
# VÝPOČET BALÍCÍCH ČASŮ
# ==========================================

def parse_packing_time(val) -> float:
    """Parsuje čas balení z různých formátů (HH:MM:SS, float, decimal days)."""
    v = str(val).strip()
    if v in ('', 'nan', 'None', 'NaN'):
        return 0.0
    try:
        num = float(v)
        if num < 1.0:
            return num * 24 * 60  # Excel decimal day
        return num
    except (ValueError, TypeError):
        pass
    parts = v.split(':')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + float(parts[2]) / 60.0
        elif len(parts) == 2:
            return int(parts[0]) + float(parts[1]) / 60.0
    except (ValueError, IndexError):
        pass
    return 0.0


# ==========================================
# VÝPOČET FYZICKÝCH POHYBŮ
# ==========================================

def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list,
                       v_lim, d_lim, h_lim):
    """
    Vektorový výpočet fyzických pohybů rukou pro každý řádek pick reportu.
    
    Vrací tuple (total_moves, exact_moves, miss_moves) – každý jako list intů.
    
    Logika:
    - FU fronta + značka X = 1 pohyb (celá paleta ze skladu)
    - Rozložení na krabice od největší, každá krabice = 1 pohyb
    - Zbylé kusy: těžké/velké = 1 pohyb/ks, jinak ceil(zbytek / hrst)
    - Pokud chybí obalová data → pohyby jdou do "miss" (odhad)
    """
    res_total, res_exact, res_miss = [], [], []

    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list, box_list, w_list, d_list):
        if qty <= 0:
            res_total.append(0)
            res_exact.append(0)
            res_miss.append(0)
            continue

        # Celá paleta přímo ze skladu
        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1)
            res_exact.append(1)
            res_miss.append(0)
            continue

        if not isinstance(boxes, list):
            boxes = []
        real_boxes = [b for b in boxes if b > 1]

        pb = pok = pmiss = 0
        zbytek = qty

        # Rozložení na krabice
        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b)
                pb += m
                zbytek = zbytek % b

        # Zbylé volné kusy
        if zbytek > 0:
            if w >= v_lim or d >= d_lim:
                p = int(zbytek)
            else:
                p = int(np.ceil(zbytek / max(h_lim, 1)))

            # Pokud víme o balení (byť jen po 1 ks) → přesné, jinak odhad
            if len(boxes) > 0:
                pok += p
            else:
                pmiss += p

        res_total.append(pb + pok + pmiss)
        res_exact.append(pb + pok)
        res_miss.append(pmiss)

    return res_total, res_exact, res_miss


# ==========================================
# CENTRÁLNÍ MOZEK – DETEKCE VOLLPALET (VEKTORIZOVÁNO)
# ==========================================

def detect_vollpalettes(df_pick: pd.DataFrame,
                        df_vekp: pd.DataFrame,
                        df_vepo: pd.DataFrame) -> set:
    """
    Detekuje Vollpalety (celé palety expedované bez přebalení) křížovým
    porovnáním Pick reportu, VEKP a VEPO.

    OPTIMALIZACE oproti původní verzi:
    - Nahrazuje double iterrows() (O(n*m) v Pythonu) za pandas merge (O(n log n))
    - Předpočítá sety platných HU z VEPO jednou
    - Vectorizované filtrování pick řádků před join operací

    Vrací set tuplů (delivery, hu_number) pro všechny detekované Vollpalety.
    Každá HU je přidána v obou variantách (ext i int) pro robustní párování.
    """
    voll_set = set()

    if any(df is None or (hasattr(df, 'empty') and df.empty)
           for df in [df_pick, df_vekp, df_vepo]):
        return voll_set

    # --- 1. PŘÍPRAVA VEPO: sada platných interních HU čísel ---
    vepo_cols = detect_vepo_columns(df_vepo)
    hu_col_vepo = vepo_cols['hu_int']
    valid_vepo_hus: set = set(df_vepo[hu_col_vepo].dropna().apply(safe_hu))
    valid_vepo_hus.discard('')

    # --- 2. PŘÍPRAVA VEKP: kořenové HU (bez rodiče, ne krabice) ---
    vekp_cols = detect_vekp_columns(df_vekp)

    col_hu_int  = vekp_cols['hu_int']  or df_vekp.columns[0]
    col_hu_ext  = vekp_cols['hu_ext']  or df_vekp.columns[1]
    col_del     = vekp_cols['delivery']
    col_parent  = vekp_cols['parent']
    col_pm      = vekp_cols['pack_material']

    vekp = df_vekp.copy()
    vekp['_hu_int']  = vekp[col_hu_int].apply(safe_hu)
    vekp['_hu_ext']  = vekp[col_hu_ext].apply(safe_hu)
    vekp['_del']     = vekp[col_del].apply(safe_del) if col_del else ''
    vekp['_parent']  = vekp[col_parent].apply(safe_hu) if col_parent else ''
    vekp['_pm']      = vekp[col_pm].astype(str).str.upper().str.strip() if col_pm else ''

    # Pouze root HU (žádný rodič) a ne krabice
    roots = vekp[
        (vekp['_parent'] == '') &
        (~vekp['_pm'].apply(is_box)) &
        (vekp['_hu_int'].isin(valid_vepo_hus)) &
        (vekp['_del'] != '')
    ][['_del', '_hu_int', '_hu_ext']].copy()

    if roots.empty:
        return voll_set

    # --- 3. PŘÍPRAVA PICK: předfiltrování na kandidáty ---
    c_su = next((c for c in df_pick.columns
                 if c in ('Storage Unit Type', 'Type')), None)

    pick = df_pick.copy()
    pick['_del'] = pick['Delivery'].apply(safe_del)
    pick['_ssu'] = pick.get('Source storage unit', pd.Series('', index=pick.index)).apply(safe_hu)
    pick['_hu']  = pick.get('Handling Unit', pd.Series('', index=pick.index)).apply(safe_hu)
    pick['_su_type'] = pick[c_su].astype(str) if c_su else ''
    pick['_queue']   = pick.get('Queue', '').astype(str).str.upper()
    pick['_removal'] = pick.get('Removal of total SU', '').astype(str).str.strip().str.upper()

    # Filtr: jen řádky se značkou X, ne krabice, ne parcel fronty
    pick_candidates = pick[
        (pick['_removal'] == 'X') &
        (~pick['_su_type'].apply(is_box)) &
        (~pick['_queue'].str.startswith('PI_PA'))
    ].copy()

    # Pouze řádky kde SSU == HU (nezměněná paleta) nebo jen jedno z nich vyplněno
    has_both  = (pick_candidates['_ssu'] != '') & (pick_candidates['_hu'] != '')
    has_ssu   = (pick_candidates['_ssu'] != '') & (pick_candidates['_hu'] == '')
    has_hu    = (pick_candidates['_ssu'] == '') & (pick_candidates['_hu'] != '')

    same_hu   = pick_candidates[has_both & (pick_candidates['_ssu'] == pick_candidates['_hu'])].copy()
    only_ssu  = pick_candidates[has_ssu].copy()
    only_hu   = pick_candidates[has_hu].copy()

    same_hu['_pick_hu']  = same_hu['_ssu']
    only_ssu['_pick_hu'] = only_ssu['_ssu']
    only_hu['_pick_hu']  = only_hu['_hu']

    pick_final = pd.concat([same_hu, only_ssu, only_hu], ignore_index=True)
    pick_final = pick_final[['_del', '_pick_hu']].drop_duplicates()
    pick_final = pick_final[pick_final['_pick_hu'] != '']

    if pick_final.empty:
        return voll_set

    # --- 4. JOIN: pick kandidáti × VEKP kořeny ---
    # Párujeme přes ext HU
    merged_ext = pick_final.merge(
        roots.rename(columns={'_hu_ext': '_pick_hu'})[['_del', '_pick_hu', '_hu_int']],
        on=['_del', '_pick_hu'],
        how='inner'
    )
    # Párujeme přes int HU
    merged_int = pick_final.merge(
        roots.rename(columns={'_hu_int': '_pick_hu'})[['_del', '_pick_hu', '_hu_ext']].rename(columns={'_hu_ext': '_hu_int'}),
        on=['_del', '_pick_hu'],
        how='inner'
    )

    # Přidáme obě varianty (ext i int) do výsledného setu
    for _, row in merged_ext.iterrows():
        voll_set.add((row['_del'], row['_pick_hu']))
        voll_set.add((row['_del'], row['_hu_int']))

    for _, row in merged_int.iterrows():
        voll_set.add((row['_del'], row['_pick_hu']))

    return voll_set


# ==========================================
# HASHABLE WRAPPER PRO VOLL_SET (pro st.cache_data)
# ==========================================

def voll_set_to_cache_key(voll_set: set) -> tuple:
    """
    Konvertuje voll_set na deterministický, hashable tuple pro použití
    jako parametr @st.cache_data funkcí.
    
    PROBLÉM který řeší: Python set nemá garantované pořadí iterace,
    takže str(set) není deterministický → falešné cache missy nebo hity.
    """
    return tuple(sorted(voll_set))