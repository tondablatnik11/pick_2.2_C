import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t

try:
    fast_render = st.fragment
except AttributeError:
    fast_render = lambda f: f

@fast_render
def render_board(df_pick, billing_df):
    st.markdown("<div class='section-header'><h3>🖨️ Nástěnka (Grafy připravené k tisku)</h3><p>Tyto grafy mají speciálně upravený kontrast a bílé pozadí, aby po vytištění na papír a vyvěšení na nástěnku vypadaly co nejlépe.</p></div>", unsafe_allow_html=True)

    if df_pick is None or df_pick.empty:
        st.warning("Žádná data k zobrazení.")
        return

    st.divider()
    
    # ---------------------------------------------------------
    # 1. ŘADA: OBJEM VYCHYSTÁVÁNÍ (PICKY A KUSY)
    # ---------------------------------------------------------
    st.markdown("###  Celkový objem vychystávání")
    c1, c2 = st.columns(2)
    
    with c1:
        st.markdown("#### Počet picků v měsících")
        # Pokud je k dispozici Transfer Order Number, spočítáme unikátní úkoly, jinak řádky
        if 'Transfer Order Number' in df_pick.columns:
            pick_trend = df_pick.groupby('Month')['Transfer Order Number'].nunique().reset_index(name='Počet Picků')
        else:
            pick_trend = df_pick.groupby('Month').size().reset_index(name='Počet Picků')
            
        fig_pick = px.bar(pick_trend, x='Month', y='Počet Picků', text='Počet Picků', 
                          color_discrete_sequence=['#3b82f6'], template='plotly_white')
        fig_pick.update_traces(textposition='outside')
        fig_pick.update_layout(margin=dict(l=0, r=0, t=30, b=0), yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig_pick, use_container_width=True)

    with c2:
        st.markdown("#### Počet vypickovaných Kusů v měsících")
        qty_trend = df_pick.groupby('Month')['Qty'].sum().reset_index(name='Počet Kusů')
        
        # Formátování čísel pro lepší čitelnost (např. 100 000 místo 100000)
        qty_trend['Text_Kusu'] = qty_trend['Počet Kusů'].apply(lambda x: f"{int(x):,}").str.replace(",", " ")
        
        fig_qty = px.bar(qty_trend, x='Month', y='Počet Kusů', text='Text_Kusu', 
                          color_discrete_sequence=['#10b981'], template='plotly_white')
        fig_qty.update_traces(textposition='outside')
        fig_qty.update_layout(margin=dict(l=0, r=0, t=30, b=0), yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig_qty, use_container_width=True)

    st.divider()

    # ---------------------------------------------------------
    # 2. ŘADA: VÝKON BALÍRNY (ZAKÁZKY A HU)
    # ---------------------------------------------------------
    st.markdown("###  Balení")
    
    if billing_df is not None and not billing_df.empty:
        # Agregace dat za měsíc (ignorujeme kategorie)
        bill_trend = billing_df.groupby('Month').agg(
            Zabalené_Zakázky=('Delivery', 'nunique'),
            Zabalené_HU=('pocet_hu', 'sum')
        ).reset_index()
        
        fig_bill = go.Figure()
        
        # Sloupec pro zabalené zakázky
        fig_bill.add_trace(go.Bar(
            x=bill_trend['Month'], 
            y=bill_trend['Zabalené_Zakázky'], 
            name='Počet zabalených zakázek', 
            marker_color='#f59e0b', 
            text=bill_trend['Zabalené_Zakázky'], 
            textposition='auto'
        ))
        
        # Sloupec pro zabalené HU
        fig_bill.add_trace(go.Bar(
            x=bill_trend['Month'], 
            y=bill_trend['Zabalené_HU'], 
            name='Počet zabalených HU', 
            marker_color='#8b5cf6', 
            text=bill_trend['Zabalené_HU'], 
            textposition='auto'
        ))
        
        fig_bill.update_layout(
            barmode='group', # Sloupce budou vedle sebe
            template='plotly_white',
            margin=dict(l=0, r=0, t=30, b=0), 
            yaxis_title=None, 
            xaxis_title=None,
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.05, 
                xanchor="center", 
                x=0.5,
                title=None
            )
        )
        st.plotly_chart(fig_bill, use_container_width=True)
    else:
        st.info("Pro zobrazení výkonu balírny navštivte nejprve záložku Fakturace.")
