import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import re
from database import load_from_db
from modules.utils import t

# Globální nastavení grafů pro jednotný vzhled
CHART_LAYOUT = dict(
    paper_bgcolor='rgba(0,0,0,0)', 
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color='#f8fafc', size=12, family="Inter, sans-serif"),
    margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='left', x=0, bgcolor='rgba(0,0,0,0)'),
    hovermode="x unified"
)

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

# Pomocná funkce pro vyčištění a sjednocení názvů obalů
def clean_pkg_name(name):
    name = str(name).strip().upper()
    if name in ['NAN', 'NONE', '']: return ''
    # Odstraní počty kusů v závorce, např. " (1X)", "(2x)"
    name = re.sub(r'\s*\(\d+X\)', '', name)
    # Odstraní slovo KARTON a pomlčky kolem něj
    name = re.sub(r'-?\s*KARTON\s*', '', name)
    return name.strip()

# =====================================================================
# 🚀 CACHEOVANÝ VÝPOČET - Provede se jen jednou a uloží se do RAM!
# =====================================================================
@st.cache_data(show_spinner=False)
def prep_packing_data(billing_df, df_oe):
    if df_oe is None or df_oe.empty or billing_df is None or billing_df.empty:
        return pd.DataFrame(), pd.DataFrame(), None, None

    # Příprava dat pro čisté párování
    df_oe_clean = df_oe.copy()
    df_oe_clean['Clean_Del'] = df_oe_clean['Delivery'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
    
    bill_clean = billing_df.copy()
    bill_clean['Clean_Del'] = bill_clean['Clean_Del_Merge'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')

    # Spojení fakturačních dat a časů balení (Inner Join)
    pack_df = pd.merge(bill_clean, df_oe_clean, on='Clean_Del', how='inner')

    # Očištění dat od nesmyslných časů (např. 0 minut)
    valid_time_df = pack_df[pack_df['Process_Time_Min'] > 0].copy()

    if valid_time_df.empty:
        return valid_time_df, pd.DataFrame(), None, None

    # --- CHYTRÉ NAPOJENÍ NA PŘESNÁ SKLADOVÁ DATA ---
    df_pick = load_from_db('raw_pick')
    if df_pick is not None and not df_pick.empty:
        df_pick['Clean_Del'] = df_pick.get('Delivery', pd.Series()).astype(str).str.replace(r'\.0$', '', regex=True).str.strip().str.lstrip('0')
        df_pick['Qty'] = pd.to_numeric(df_pick.get('Act.qty (dest)', 0), errors='coerce').fillna(0)
        df_pick['Material'] = df_pick.get('Material', pd.Series()).astype(str).str.strip()
        
        # Pro každou zakázku sečteme reálné kusy a najdeme nejčastější materiál
        pick_info = df_pick.groupby('Clean_Del').agg(
            Skladovy_Material=('Material', lambda x: x.value_counts().index[0] if len(x.value_counts()) > 0 else ""),
            Celkove_Kusy=('Qty', 'sum')
        ).reset_index()
        
        valid_time_df = pd.merge(valid_time_df, pick_info, on='Clean_Del', how='left')
        pcs_col = 'Celkove_Kusy'
        mat_col = 'Skladovy_Material'
    else:
        # Fallback (kdyby pick report chyběl)
        pcs_col = 'pocet_to'
        mat_col = 'Material_y' if 'Material_y' in valid_time_df.columns else 'Material'

    # Výpočet efektivity
    valid_time_df['Min_per_HU'] = np.where(valid_time_df['pocet_hu'] > 0, valid_time_df['Process_Time_Min'] / valid_time_df['pocet_hu'], valid_time_df['Process_Time_Min'])

    # --- PŘEDVÝPOČET KOMPLEXNÍCH VAZEB (Tohle extrémně zdržovalo) ---
    mat_complex = pd.DataFrame()
    if mat_col in valid_time_df.columns:
        def get_top_pkg(series):
            all_pkgs = []
            for item in series.dropna():
                for p in str(item).split(';'):
                    cleaned = clean_pkg_name(p)
                    if cleaned: all_pkgs.append(cleaned)
            if not all_pkgs: return "-"
            return pd.Series(all_pkgs).mode()[0]
            
        mat_complex = valid_time_df.groupby(mat_col).agg(
            Orders=('Clean_Del', 'nunique'),
            Total_Time=('Process_Time_Min', 'sum'),
            Total_HU=('pocet_hu', 'sum'),
            Total_Pcs=(pcs_col, lambda x: pd.to_numeric(x, errors='coerce').sum()),
            Top_Carton=('Cartons', get_top_pkg) if 'Cartons' in valid_time_df.columns else ('Clean_Del', lambda x: "-"),
            Top_KLT=('KLT', get_top_pkg) if 'KLT' in valid_time_df.columns else ('Clean_Del', lambda x: "-"),
            Top_Pallet=('Palety', get_top_pkg) if 'Palety' in valid_time_df.columns else ('Clean_Del', lambda x: "-")
        ).reset_index()
        
        mat_complex = mat_complex[mat_complex['Orders'] > 0]
        mat_complex['Avg_Time_Order'] = np.where(mat_complex['Orders'] > 0, mat_complex['Total_Time'] / mat_complex['Orders'], 0)
        mat_complex['Avg_Time_HU'] = np.where(mat_complex['Total_HU'] > 0, mat_complex['Total_Time'] / mat_complex['Total_HU'], 0)
        mat_complex['Avg_Time_Pc'] = np.where(mat_complex['Total_Pcs'] > 0, mat_complex['Total_Time'] / mat_complex['Total_Pcs'], 0)
        mat_complex['Avg_Pcs_Order'] = np.where(mat_complex['Orders'] > 0, mat_complex['Total_Pcs'] / mat_complex['Orders'], 0)
        mat_complex = mat_complex.sort_values('Orders', ascending=False)

    return valid_time_df, mat_complex, pcs_col, mat_col


def render_packing(billing_df, df_oe):
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>📦 {_t('Analýza balícího procesu (OE-Times)', 'Packing Process Analysis (OE-Times)')}</h3><p>{_t('Komplexní propojení času u balícího stolu s konkrétními zákazníky, materiály a použitými obaly.', 'Comprehensive connection of packing station time with specific customers, materials, and used packaging.')}</p></div>", unsafe_allow_html=True)

    if df_oe is None or df_oe.empty:
        st.info(_t("Pro tuto záložku je nutné nahrát soubor OE-Times v Admin zóně.", "Upload the OE-Times file in Admin Zone to use this tab."))
        return

    if billing_df is None or billing_df.empty:
        st.warning(_t("Pro propojení chybí data z Fakturace (VEKP). Aplikace nejprve potřebuje načíst data z předchozích záložek.", "Billing data (VEKP) missing for correlation. App needs data from previous tabs first."))
        return

    with st.spinner(_t("🧠 Počítám efektivitu balení a analyzuji obaly...", "🧠 Calculating packing efficiency and packaging...")):
        valid_time_df, mat_complex, pcs_col, mat_col = prep_packing_data(billing_df, df_oe)

    if valid_time_df.empty:
        st.warning(_t("Nepodařilo se spárovat platné zakázky (> 0 min) z OE-Times se skladem.", "No valid orders (> 0 min) matched with warehouse data."))
        return

    # --- HLAVNÍ METRIKY ---
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        with st.container(border=True): st.metric(_t("Spárovaných zakázek", "Matched Orders"), f"{len(valid_time_df):,}")
    with c2:
        with st.container(border=True): st.metric(_t("Celkový čas balení", "Total Packing Time"), f"{valid_time_df['Process_Time_Min'].sum() / 60:.1f} h")
    with c3:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 zakázku", "Avg Time per Order"), f"{valid_time_df['Process_Time_Min'].mean():.1f} min")
    with c4:
        with st.container(border=True): st.metric(_t("Prům. čas na 1 Billed HU", "Avg Time per Billed HU"), f"{valid_time_df['Min_per_HU'].mean():.1f} min")

    st.divider()

    # --- PŘEPÍNAČE POHLEDŮ (TABS) ---
    tab_cust, tab_mat, tab_pkg, tab_detail, tab_complex = st.tabs([
        f"🏢 {_t('Podle zákazníka & Kategorie', 'By Customer & Category')}",
        f"⚙️ {_t('Podle materiálu & složitosti', 'By Material & Complexity')}",
        f"📦 {_t('Spotřeba a analýza obalů', 'Packaging Analysis')}",
        f"🔍 {_t('Detailní E2E Report', 'Detailed E2E Report')}",
        f"🧠 {_t('Komplexní vazby', 'Complex Relations')}"
    ])

    # ==========================================
    # ZÁLOŽKA 1: ZÁKAZNÍCI A KATEGORIE
    # ==========================================
    with tab_cust:
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.markdown(f"**🏢 {_t('Náročnost balení podle Zákazníků', 'Packing Effort by Customer')}**")
            if 'CUSTOMER' in valid_time_df.columns:
                cust_df = valid_time_df.groupby('CUSTOMER').agg(
                    Orders=('Clean_Del', 'nunique'),
                    Total_Time=('Process_Time_Min', 'sum'),
                    Total_HU=('pocet_hu', 'sum')
                ).reset_index()
                
                cust_df['Avg_Min_Order'] = np.where(cust_df['Orders'] > 0, cust_df['Total_Time'] / cust_df['Orders'], 0)
                cust_df['Avg_Min_HU'] = np.where(cust_df['Total_HU'] > 0, cust_df['Total_Time'] / cust_df['Total_HU'], 0)
                
                cust_df = cust_df.sort_values('Orders', ascending=False)
                
                disp_cust = cust_df[['CUSTOMER', 'Orders', 'Avg_Min_Order', 'Avg_Min_HU', 'Total_Time']].copy()
                disp_cust.columns = [_t("Zákazník", "Customer"), _t("Počet zakázek", "Orders"), _t("Prům. čas na zakázku", "Avg Time/Order"), _t("Prům. čas na 1 HU", "Avg Time/HU"), _t("Celkový čas (Min)", "Total Time (Min)")]
                st.dataframe(disp_cust.style.format({_t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}", _t("Prům. čas na zakázku", "Avg Time/Order"): "{:.1f}", _t("Prům. čas na 1 HU", "Avg Time/HU"): "{:.1f}"}), hide_index=True, use_container_width=True)
                
                fig_cust = go.Figure(go.Bar(
                    x=cust_df['Orders'].head(15), 
                    y=cust_df['CUSTOMER'].head(15), 
                    orientation='h', marker_color='#8b5cf6', 
                    text=cust_df['Orders'].head(15), textposition='auto'
                ))
                fig_cust.update_layout(**CHART_LAYOUT)
                fig_cust.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), title=_t("TOP 15 Zákazníků (dle počtu zakázek)", "TOP 15 Customers (by orders)"))
                st.plotly_chart(fig_cust, use_container_width=True)
            else:
                st.info(_t("Sloupec 'CUSTOMER' není v datech k dispozici.", "Column 'CUSTOMER' not available in data."))

        with col_c2:
            st.markdown(f"**🏷️ {_t('Náročnost balení podle Kategorií (E/OE/N)', 'Packing Effort by Categories (E/OE/N)')}**")
            cat_df = valid_time_df.groupby('Category_Full').agg(
                Orders=('Clean_Del', 'nunique'),
                Total_Time=('Process_Time_Min', 'sum'),
                Total_HU=('pocet_hu', 'sum')
            ).reset_index()
            
            cat_df['Avg_Min_Order'] = np.where(cat_df['Orders'] > 0, cat_df['Total_Time'] / cat_df['Orders'], 0)
            cat_df['Avg_Min_HU'] = np.where(cat_df['Total_HU'] > 0, cat_df['Total_Time'] / cat_df['Total_HU'], 0)
            cat_df = cat_df.sort_values('Orders', ascending=False)
            
            disp_cat = cat_df[['Category_Full', 'Orders', 'Avg_Min_Order', 'Avg_Min_HU', 'Total_Time']].copy()
            disp_cat.columns = [_t("Kategorie", "Category"), _t("Počet zakázek", "Orders"), _t("Prům. čas na zakázku", "Avg Time/Order"), _t("Prům. čas na 1 HU", "Avg Time/HU"), _t("Celkový čas (Min)", "Total Time (Min)")]
            st.dataframe(disp_cat.style.format({_t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}", _t("Prům. čas na zakázku", "Avg Time/Order"): "{:.1f}", _t("Prům. čas na 1 HU", "Avg Time/HU"): "{:.1f}"}), hide_index=True, use_container_width=True)

            fig_cat = go.Figure(go.Bar(
                x=cat_df['Orders'], 
                y=cat_df['Category_Full'], 
                orientation='h', marker_color='#3b82f6', 
                text=cat_df['Orders'], textposition='auto'
            ))
            fig_cat.update_layout(**CHART_LAYOUT)
            fig_cat.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), title=_t("Kategorie (dle počtu zakázek)", "Categories (by orders)"))
            st.plotly_chart(fig_cat, use_container_width=True)

    # ==========================================
    # ZÁLOŽKA 2: MATERIÁLY A SLOŽITOST
    # ==========================================
    with tab_mat:
        st.markdown(f"**⚙️ {_t('Nejnáročnější materiály na balení (Dle průměrného času)', 'Most demanding materials for packing (By Avg Time)')}**")
        
        if mat_col in valid_time_df.columns:
            mat_df = valid_time_df.groupby(mat_col).agg(
                Orders=('Clean_Del', 'nunique'),
                Avg_Time=('Process_Time_Min', 'mean'),
                Total_Time=('Process_Time_Min', 'sum')
            ).reset_index()
            # Filtrujeme jen materiály, co se dělaly aspoň 2x
            mat_df = mat_df[mat_df['Orders'] > 1].sort_values('Avg_Time', ascending=False).head(20)
            
            col_m1, col_m2 = st.columns([1, 1.2])
            with col_m1:
                disp_mat = mat_df.copy()
                disp_mat.columns = [_t("Materiál", "Material"), _t("Frekvence (Zakázek)", "Frequency (Orders)"), _t("Prům. čas (Min)", "Avg Time (Min)"), _t("Celkový čas (Min)", "Total Time (Min)")]
                st.dataframe(disp_mat.style.format({_t("Prům. čas (Min)", "Avg Time (Min)"): "{:.1f}", _t("Celkový čas (Min)", "Total Time (Min)"): "{:.0f}"}), hide_index=True, use_container_width=True)
            
            with col_m2:
                fig_mat = go.Figure(go.Bar(
                    x=mat_df['Avg_Time'], y=mat_df[mat_col].astype(str), 
                    orientation='h', marker_color='#f43f5e', 
                    text=mat_df['Avg_Time'].round(1).astype(str) + ' min', textposition='auto'
                ))
                fig_mat.update_layout(**CHART_LAYOUT)
                fig_mat.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Průměrný čas balení materiálu", "Avg packing time of material"))
                st.plotly_chart(fig_mat, use_container_width=True)

        st.divider()
        st.markdown(f"**🔴 {_t('Faktory zvyšující složitost balení (Skenování / KLT)', 'Factors increasing packing complexity (Scanning / KLT)')}**")
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            if 'Scanning serial numbers' in valid_time_df.columns:
                valid_time_df['Has_Scan'] = valid_time_df['Scanning serial numbers'].astype(str).str.upper().isin(['X', 'YES', 'ANO', '1'])
                scan_df = valid_time_df.groupby('Has_Scan')['Process_Time_Min'].mean().reset_index()
                
                scan_yes = scan_df[scan_df['Has_Scan'] == True]['Process_Time_Min'].mean()
                scan_no = scan_df[scan_df['Has_Scan'] == False]['Process_Time_Min'].mean()
                if pd.isna(scan_yes): scan_yes = 0
                if pd.isna(scan_no): scan_no = 0
                
                st.metric(_t("Vliv skenování sériových čísel", "Impact of serial number scanning"), f"{scan_yes:.1f} min", f"{scan_yes - scan_no:.1f} min {_t('navíc oproti normálu', 'extra vs normal')}", delta_color="inverse")
                
        with col_f2:
            if 'Difficult KLTs' in valid_time_df.columns:
                valid_time_df['Has_Diff'] = valid_time_df['Difficult KLTs'].astype(str).str.upper().isin(['X', 'YES', 'ANO', '1'])
                diff_df = valid_time_df.groupby('Has_Diff')['Process_Time_Min'].mean().reset_index()
                
                diff_yes = diff_df[diff_df['Has_Diff'] == True]['Process_Time_Min'].mean()
                diff_no = diff_df[diff_df['Has_Diff'] == False]['Process_Time_Min'].mean()
                if pd.isna(diff_yes): diff_yes = 0
                if pd.isna(diff_no): diff_no = 0
                
                st.metric(_t("Vliv 'Složitých KLT'", "Impact of 'Difficult KLTs'"), f"{diff_yes:.1f} min", f"{diff_yes - diff_no:.1f} min {_t('navíc oproti normálu', 'extra vs normal')}", delta_color="inverse")

    # ==========================================
    # ZÁLOŽKA 3: OBALY (PACKAGING)
    # ==========================================
    with tab_pkg:
        st.markdown(f"**📦 {_t('Sjednocená analytika spotřeby obalů a časové náročnosti', 'Unified analytics of packaging usage and time effort')}**")
        st.caption(_t("Data jsou automaticky očištěna (sloučeny názvy jako 'CARTON-05' a 'CARTON-05-KARTON (1x)').", "Data is automatically cleaned (merging names like 'CARTON-05' and 'CARTON-05-KARTON (1x)')."))
        
        def get_pkg_stats(df, col_name, pcs_col_name):
            if col_name not in df.columns: return pd.DataFrame()
            
            temp_df = df[['Clean_Del', 'Process_Time_Min', 'pocet_hu', pcs_col_name, col_name]].copy()
            temp_df[col_name] = temp_df[col_name].astype(str).str.split(';')
            exploded = temp_df.explode(col_name)
            
            exploded[col_name] = exploded[col_name].apply(clean_pkg_name)
            exploded = exploded[exploded[col_name] != '']
            
            if exploded.empty: return pd.DataFrame()
            
            stats = exploded.groupby(col_name).agg(
                Pouzito_Zakazek=('Clean_Del', 'nunique'),
                Total_Time=('Process_Time_Min', 'sum'),
                Total_HU=('pocet_hu', 'sum'),
                Total_Pcs=(pcs_col_name, 'sum') 
            ).reset_index()
            
            stats['Avg_Time_Order'] = np.where(stats['Pouzito_Zakazek'] > 0, stats['Total_Time'] / stats['Pouzito_Zakazek'], 0)
            stats['Avg_Time_HU'] = np.where(stats['Total_HU'] > 0, stats['Total_Time'] / stats['Total_HU'], 0)
            stats['Avg_Pcs'] = np.where(stats['Pouzito_Zakazek'] > 0, stats['Total_Pcs'] / stats['Pouzito_Zakazek'], 0)
            
            return stats.sort_values('Pouzito_Zakazek', ascending=False)

        def render_pkg_section(title, col_name, color):
            st.markdown(f"##### {title}")
            pkg_df = get_pkg_stats(valid_time_df, col_name, pcs_col)
            
            if not pkg_df.empty:
                col_pt, col_pg = st.columns([1.5, 1])
                with col_pt:
                    disp = pkg_df[[col_name, 'Pouzito_Zakazek', 'Avg_Time_Order', 'Avg_Time_HU', 'Avg_Pcs']].copy()
                    disp.columns = [_t("Vyčištěný název obalu", "Clean Packaging Name"), _t("Použito (Zakázek)", "Used (Orders)"), _t("Prům. čas na zakázku (Min)", "Avg Time/Order (Min)"), _t("Prům. čas na HU (Min)", "Avg Time/HU (Min)"), _t("Prům. ks materiálu", "Avg Mat Pcs")]
                    st.dataframe(disp.style.format({
                        _t("Prům. čas na zakázku (Min)", "Avg Time/Order (Min)"): "{:.1f}",
                        _t("Prům. čas na HU (Min)", "Avg Time/HU (Min)"): "{:.1f}",
                        _t("Prům. ks materiálu", "Avg Mat Pcs"): "{:.1f}"
                    }), hide_index=True, use_container_width=True)
                with col_pg:
                    fig = go.Figure(go.Bar(
                        x=pkg_df['Pouzito_Zakazek'].head(10), 
                        y=pkg_df[col_name].head(10), 
                        orientation='h', marker_color=color, 
                        text=pkg_df['Pouzito_Zakazek'].head(10), textposition='auto'
                    ))
                    fig.update_layout(**CHART_LAYOUT)
                    fig.update_layout(yaxis={'categoryorder':'total ascending'}, xaxis_title=_t("Počet zakázek", "Number of Orders"), margin=dict(t=0, b=0, l=0, r=0), height=300)
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info(_t("Žádná data pro tento typ obalu.", "No data for this packaging type."))

        render_pkg_section(f"🗃️ {_t('Krabice (Cartons)', 'Cartons')}", 'Cartons', '#f59e0b')
        st.divider()
        render_pkg_section(f"🟦 {_t('KLT boxy', 'KLT Boxes')}", 'KLT', '#3b82f6')
        st.divider()
        render_pkg_section(f"🏭 {_t('Palety', 'Pallets')}", 'Palety', '#10b981')

    # ==========================================
    # ZÁLOŽKA 4: DETAILNÍ E2E REPORT
    # ==========================================
    with tab_detail:
        st.markdown(f"**🔍 {_t('Surová E2E data (Od regálu až k balícímu stolu)', 'Raw E2E data (From shelf to packing desk)')}**")
        
        disp_cols = ['Clean_Del', 'Category_Full', 'Month', 'hlavni_fronta', 'pocet_lokaci']
        if 'CUSTOMER' in valid_time_df.columns: disp_cols.append('CUSTOMER')
        if mat_col in valid_time_df.columns: disp_cols.append(mat_col)
        
        disp_cols.extend(['pocet_to', pcs_col, 'pohyby_celkem', 'pocet_hu', 'Process_Time_Min', 'Min_per_HU'])
        if 'Shift' in valid_time_df.columns: disp_cols.append('Shift')
        
        disp_pack = valid_time_df[disp_cols].copy()
        disp_pack = disp_pack.sort_values('Process_Time_Min', ascending=False)
        
        rename_dict = {
            'Clean_Del': _t("Zakázka", "Order"),
            'Category_Full': _t("Kategorie", "Category"),
            'Month': _t("Měsíc", "Month"),
            'hlavni_fronta': _t("Hlavní fronta", "Main Queue"),
            'pocet_lokaci': _t("Navštívené lokace", "Visited Locations"),
            'CUSTOMER': _t("Zákazník", "Customer"),
            mat_col: _t("Hlavní materiál", "Main Material"),
            'pocet_to': _t("Pickováno TO", "Picked TOs"),
            pcs_col: _t("Kusů (Qty)", "Pieces (Qty)"),
            'pohyby_celkem': _t("Fyzické pohyby", "Physical Moves"),
            'pocet_hu': _t("Vyfakturováno HU", "Billed HUs"),
            'Process_Time_Min': _t("Čas balení (Min)", "Packing Time (Min)"),
            'Min_per_HU': _t("Minut na 1 HU", "Minutes per 1 HU"),
            'Shift': _t("Směna", "Shift")
        }
        
        disp_pack.rename(columns=rename_dict, inplace=True)
        
        st.dataframe(disp_pack.style.format({
            _t("Čas balení (Min)", "Packing Time (Min)"): "{:.1f}", 
            _t("Minut na 1 HU", "Minutes per 1 HU"): "{:.1f}",
            _t("Kusů (Qty)", "Pieces (Qty)"): "{:.0f}"
        }), hide_index=True, use_container_width=True)

    # ==========================================
    # ZÁLOŽKA 5: KOMPLEXNÍ VAZBY (Materiál -> Kusy -> Obaly)
    # ==========================================
    with tab_complex:
        st.markdown(f"**🧠 {_t('Chování materiálů: Do čeho a v jakém množství se balí?', 'Material Behavior: What packaging and quantities are used?')}**")
        st.caption(_t("Algoritmus zkoumá každý materiál, detekuje průměrný počet odeslaných kusů a vyhledá z historie nejčastěji používanou krabici, KLT nebo paletu, do které pracovník tento materiál vložil.", "The algorithm examines each material, average pieces shipped, and finds the most frequently used packaging from history."))
        
        if not mat_complex.empty:
            # --- BUBBLE GRAF ---
            st.markdown(f"**📊 {_t('Rozložení náročnosti TOP 100 materiálů', 'Effort Distribution of TOP 100 Materials')}**")
            top100_mat = mat_complex.head(100).copy()
            
            fig_bub = px.scatter(
                top100_mat, 
                x="Avg_Pcs_Order", 
                y="Avg_Time_Order", 
                size="Orders", 
                color="Top_Carton",
                hover_name=mat_col,
                log_x=True, # Logaritmická osa X pro lepší čitelnost (1 ks vs 1000 ks)
                size_max=40,
                labels={
                    "Avg_Pcs_Order": _t("Průměrně kusů na zakázku (Logaritmicky)", "Avg Pcs per Order (Log)"),
                    "Avg_Time_Order": _t("Průměrně minut na zakázku", "Avg Minutes per Order"),
                    "Top_Carton": _t("Typický karton", "Typical Carton"),
                    "Orders": _t("Počet zakázek", "Number of Orders")
                }
            )
            fig_bub.update_layout(**CHART_LAYOUT)
            fig_bub.update_layout(height=450)
            st.plotly_chart(fig_bub, use_container_width=True)

            # --- TABULKA ---
            disp_mat_complex = mat_complex[[
                mat_col, 'Orders', 'Avg_Pcs_Order', 'Top_Carton', 'Top_KLT', 'Top_Pallet',
                'Avg_Time_Order', 'Avg_Time_HU', 'Avg_Time_Pc'
            ]].copy()

            disp_mat_complex.columns = [
                _t("Materiál", "Material"),
                _t("Zakázek", "Orders"),
                _t("Prům. ks na zakázku", "Avg Pcs/Order"),
                _t("Nejčastější Krabice", "Top Carton"),
                _t("Nejčastější KLT", "Top KLT"),
                _t("Nejčastější Paleta", "Top Pallet"),
                _t("Prům. čas (Min / Zak.)", "Avg Time (Min / Ord)"),
                _t("Prům. čas (Min / HU)", "Avg Time (Min / HU)"),
                _t("Prům. čas (Min / Ks)", "Avg Time (Min / Pc)")
            ]

            st.dataframe(disp_mat_complex.style.format({
                _t("Prům. ks na zakázku", "Avg Pcs/Order"): "{:.1f}",
                _t("Prům. čas (Min / Zak.)", "Avg Time (Min / Ord)"): "{:.1f}",
                _t("Prům. čas (Min / HU)", "Avg Time (Min / HU)"): "{:.1f}",
                _t("Prům. čas (Min / Ks)", "Avg Time (Min / Pc)"): "{:.2f}"
            }), hide_index=True, use_container_width=True)

        else:
            st.info(_t("Pro vykreslení této matice chybí v datech sloupec 'Material'.", "Column 'Material' missing to render this matrix."))
