import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from modules.utils import t

def render_pallets(df_pick):
    # Chytrý lokální překladač pro tuto záložku
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    st.markdown(f"<div class='section-header'><h3>🎯 {_t('Analýza čistých palet (Single SKU)', 'Pure Pallets Analysis (Single SKU)')}</h3><p>{_t('Přehled paletových zakázek z front PI_PL a PI_PL_OE, které obsahují pouze jeden druh materiálu.', 'Overview of pallet orders from PI_PL and PI_PL_OE queues containing exactly one type of material.')}</p></div>", unsafe_allow_html=True)
    
    # 1. Vyfiltrujeme pouze paletové fronty
    pal_df = df_pick[df_pick['Queue'].astype(str).str.upper().isin(['PI_PL', 'PI_PL_OE'])].copy()
    
    if pal_df.empty:
        st.info(_t("V aktuálních datech nejsou žádné zakázky z front PI_PL nebo PI_PL_OE.", "No orders from PI_PL or PI_PL_OE queues found in current data."))
        return

    # 2. Agregace dat na úroveň celé zakázky (Delivery)
    pal_agg = pal_df.groupby('Delivery').agg(
        num_materials=('Material', 'nunique'),
        total_qty=('Qty', 'sum'),
        celkem_pohybu=('Pohyby_Rukou', 'sum'),
        lokace=('Source Storage Bin', 'nunique'),
        vaha_zakazky=('Celkova_Vaha_KG', 'sum'),
        Month=('Month', 'first')
    ).reset_index()

    # 3. PŘÍSNÝ FILTR - POUZE ZAKÁZKY S 1 MATERIÁLEM (Zahození Mixu)
    single_df = pal_agg[pal_agg['num_materials'] == 1].copy()

    if single_df.empty:
        st.warning(_t("V datech nejsou žádné čisté paletové zakázky obsahující pouze 1 materiál.", "No pure pallet orders containing only 1 material found in data."))
        return

    # 4. METRIKY (Čisté palety)
    total_single = len(single_df)
    avg_qty = single_df['total_qty'].mean()
    avg_moves = single_df['celkem_pohybu'].mean()
    
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True): 
            st.metric(_t("Počet zakázek (Čisté palety 1:1)", "Total Orders (Pure Pallets 1:1)"), f"{total_single:,}")
    with c2:
        with st.container(border=True): 
            st.metric(_t("Průměrně kusů na zakázku", "Avg Qty per Order"), f"{avg_qty:.0f}")
    with c3:
        with st.container(border=True): 
            st.metric(_t("Průměr fyz. pohybů na zakázku", "Avg Physical Moves per Order"), f"{avg_moves:.1f}")

    st.divider()

    col_t, col_g = st.columns([1, 1.5])

    # 5. TABULKA (Nejnáročnější čisté zakázky)
    with col_t:
        st.markdown(f"**{_t('Detailní přehled (Nejnáročnější čisté palety)', 'Detailed Overview (Most demanding pure pallets)')}**")
        single_df['prum_poh_lok'] = np.where(single_df['lokace'] > 0, single_df['celkem_pohybu'] / single_df['lokace'], 0)
        
        # Seřadíme od největšího počtu pohybů
        disp_single = single_df[['Delivery', 'total_qty', 'celkem_pohybu', 'prum_poh_lok', 'vaha_zakazky']].sort_values('celkem_pohybu', ascending=False).head(50)
        disp_single.columns = [
            _t("Zakázka", "Order"), 
            _t("Kusů", "Qty"), 
            _t("Pohyby celkem", "Total Moves"), 
            _t("Pohybů / lokaci", "Moves / Loc"), 
            _t("Celk. váha (kg)", "Total Weight (kg)")
        ]
        
        st.dataframe(disp_single.style.format({
            _t("Pohybů / lokaci", "Moves / Loc"): "{:.1f}", 
            _t("Celk. váha (kg)", "Total Weight (kg)"): "{:.1f}"
        }), use_container_width=True, hide_index=True)

    # 6. GRAF (Trend vývoje čistých palet v čase)
    with col_g:
        st.markdown(f"**📈 {_t('Měsíční trend u čistých palet', 'Monthly Trend for Pure Pallets')}**")
        if 'Month' in single_df.columns:
            trend_agg = single_df.groupby('Month').agg(
                pocet_zakazek=('Delivery', 'count'),
                prum_pohybu=('celkem_pohybu', 'mean')
            ).reset_index()
            
            fig = go.Figure()
            
            # Sloupce (Počet zakázek v daném měsíci)
            fig.add_trace(go.Bar(
                x=trend_agg['Month'], 
                y=trend_agg['pocet_zakazek'], 
                name=_t('Počet zakázek', 'Orders Count'), 
                marker_color='#10b981', 
                text=trend_agg['pocet_zakazek'], 
                textposition='auto',
                yaxis='y'
            ))
            
            # Čára (Vývoj průměrného počtu fyzických pohybů)
            fig.add_trace(go.Scatter(
                x=trend_agg['Month'], 
                y=trend_agg['prum_pohybu'], 
                name=_t('Prům. pohybů na zakázku', 'Avg Moves per Order'), 
                mode='lines+markers+text', 
                text=trend_agg['prum_pohybu'].round(1).astype(str), 
                textposition='top center', 
                marker_color='#f59e0b', 
                line=dict(width=3), 
                yaxis='y2'
            ))
            
            fig.update_layout(
                yaxis=dict(title=_t("Počet zakázek (1 mat.)", "Orders Count (1 mat.)")),
                yaxis2=dict(title=_t("Průměr pohybů", "Avg Moves"), side="right", overlaying="y", showgrid=False),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(_t("Chybí data o měsících pro vykreslení trendu.", "Missing month data to plot trend."))
