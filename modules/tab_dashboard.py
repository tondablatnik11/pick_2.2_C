import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from modules.utils import t, QUEUE_DESC

def render_dashboard(df_pick, queue_count_col):
    # Chytrý lokální překladač pro tuto záložku
    def _t(cs, en): 
        return en if st.session_state.get('lang', 'cs') == 'en' else cs

    # --- 1. Spolehlivost dat (Data Quality) ---
    st.markdown(f"<div class='section-header'><h3>{t('sec_ratio')}</h3><p>{t('ratio_desc')}</p></div>", unsafe_allow_html=True)
    
    total_moves = df_pick['Pohyby_Rukou'].sum()
    exact_moves = df_pick['Pohyby_Exact'].sum()
    miss_moves = df_pick['Pohyby_Loose_Miss'].sum()
    pct_exact = (exact_moves / total_moves * 100) if total_moves > 0 else 0
    pct_miss = (miss_moves / total_moves * 100) if total_moves > 0 else 0

    c1, c2, c3 = st.columns(3)
    c1.metric(t('ratio_moves'), f"{int(total_moves):,}")
    c2.metric(t('ratio_exact'), f"{int(exact_moves):,} ({pct_exact:.1f} %)")
    c3.metric(t('ratio_miss'), f"{int(miss_moves):,} ({pct_miss:.1f} %)")

    with st.expander(t('exp_missing_data')):
        miss_df = df_pick[df_pick['Pohyby_Loose_Miss'] > 0].groupby('Material').agg(
            Odhad_Pohybu=('Pohyby_Loose_Miss', 'sum'),
            Kusu=('Qty', 'sum')
        ).reset_index().sort_values('Odhad_Pohybu', ascending=False)
        
        miss_df.columns = [_t("Materiál", "Material"), _t("Odhadované pohyby (Miss)", "Estimated Moves (Miss)"), _t("Kusů", "Quantity")]
        st.dataframe(miss_df, hide_index=True, use_container_width=True)

    # --- 2. Tabulka průměrné náročnosti (Queue Table) ---
    st.markdown(f"<div class='section-header'><h3>{t('sec_queue_title')}</h3></div>", unsafe_allow_html=True)
    
    to_group = df_pick.groupby(queue_count_col).agg(
        Queue=('Queue', 'first'),
        lokace_v_to=('Source Storage Bin', 'nunique'),
        kusy_v_to=('Qty', 'sum'),
        pohyby_v_to=('Pohyby_Rukou', 'sum'),
        exact_poh=('Pohyby_Exact', 'sum'),
        miss_poh=('Pohyby_Loose_Miss', 'sum'),
        pocet_mat=('Material', 'nunique'),
        Delivery=('Delivery', 'first')
    ).reset_index()

    def split_queue(row):
        q = str(row['Queue']).strip()
        if q in ['PI_PL', 'PI_PL_OE']:
            if row['pocet_mat'] <= 1:
                return f"{q} (Single)"
            else:
                return f"{q} (Mix)"
        return q

    to_group['Queue_Split'] = to_group.apply(split_queue, axis=1)

    q_agg = to_group.groupby('Queue_Split').agg(
        pocet_to=(queue_count_col, 'nunique'),
        zakazky=('Delivery', 'nunique'),
        lokace_celkem=('lokace_v_to', 'sum'),
        kusy_celkem=('kusy_v_to', 'sum'),
        pohyby_celkem=('pohyby_v_to', 'sum'),
        exact_celkem=('exact_poh', 'sum'),
        miss_celkem=('miss_poh', 'sum')
    ).reset_index()

    q_agg['prum_lok_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['lokace_celkem'] / q_agg['pocet_to'], 0)
    q_agg['prum_ks_to'] = np.where(q_agg['pocet_to'] > 0, q_agg['kusy_celkem'] / q_agg['pocet_to'], 0)
    q_agg['prum_poh_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['pohyby_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['prum_exact_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['exact_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['prum_miss_lok'] = np.where(q_agg['lokace_celkem'] > 0, q_agg['miss_celkem'] / q_agg['lokace_celkem'], 0)
    q_agg['pct_exact'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['exact_celkem'] / q_agg['pohyby_celkem'] * 100, 0)
    q_agg['pct_miss'] = np.where(q_agg['pohyby_celkem'] > 0, q_agg['miss_celkem'] / q_agg['pohyby_celkem'] * 100, 0)

    q_agg['Queue_Desc'] = q_agg['Queue_Split'].map(QUEUE_DESC).fillna(t('unknown'))
    
    disp_q = q_agg[['Queue_Split', 'Queue_Desc', 'pocet_to', 'zakazky', 'prum_lok_to', 'prum_ks_to', 'prum_poh_lok', 'prum_exact_lok', 'pct_exact', 'prum_miss_lok', 'pct_miss']].copy()
    
    # Překlad názvů sloupců
    c_loc_to = _t("Průměr lokací (zastávek) / TO", "Avg Locations (Stops) / TO")
    c_ks_to = _t("Průměr kusů / TO", "Avg Qty / TO")
    c_poh_lok = _t("Průměr pohybů na 1 lokaci", "Avg Moves per 1 Location")
    c_ex_lok = _t("Pohyby přesně / lok.", "Exact Moves / Loc")
    c_mi_lok = _t("Pohyby odhad / lok.", "Estimated Moves / Loc")
    c_pct_ex = _t("% Přesně", "% Exact")
    c_pct_mi = _t("% Odhad", "% Estimated")

    disp_q.columns = [
        "Queue", 
        _t("Popis fronty", "Queue Description"), 
        _t("Počet TO", "Total TOs"), 
        _t("Zasažených zakázek", "Affected Orders"), 
        c_loc_to, 
        c_ks_to, 
        c_poh_lok, 
        c_ex_lok, 
        c_pct_ex, 
        c_mi_lok, 
        c_pct_mi
    ]
    
    st.dataframe(disp_q.style.format({
        c_loc_to: "{:.1f}", 
        c_ks_to: "{:.1f}", 
        c_poh_lok: "{:.2f}",
        c_ex_lok: "{:.2f}", 
        c_mi_lok: "{:.2f}",
        c_pct_ex: "{:.1f}%", 
        c_pct_mi: "{:.1f}%"
    }), hide_index=True, use_container_width=True)

    # --- 3. GRAF: Měsíční trend podle Queue ---
    st.markdown(f"<div class='section-header'><h3>📈 {_t('Trend náročnosti v čase podle Queue', 'Effort Trend over Time by Queue')}</h3></div>", unsafe_allow_html=True)
    
    if 'Month' in df_pick.columns:
        q_split_map = to_group.set_index(queue_count_col)['Queue_Split'].to_dict()
        df_pick['Queue_Split_Graf'] = df_pick[queue_count_col].map(q_split_map).fillna(df_pick['Queue'])

        valid_queues = sorted([q for q in df_pick['Queue_Split_Graf'].dropna().unique() if q != 'N/A'])
        
        selected_queues = st.multiselect(
            _t("Zvolte Queue pro zobrazení v grafu (můžete vybrat libovolný počet):", "Select Queue(s) to display in the chart:"),
            options=valid_queues,
            default=valid_queues[:3] if len(valid_queues) >= 3 else valid_queues
        )
        
        if selected_queues:
            trend_df = df_pick[df_pick['Queue_Split_Graf'].isin(selected_queues)]
            
            trend_to_group = trend_df.groupby(['Month', queue_count_col]).agg(
                Queue_Split=('Queue_Split_Graf', 'first'),
                lokace=('Source Storage Bin', 'nunique'),
                pohyby=('Pohyby_Rukou', 'sum')
            ).reset_index()

            trend_agg = trend_to_group.groupby(['Month', 'Queue_Split']).agg(
                to_count=(queue_count_col, 'nunique'),
                loc_count=('lokace', 'sum'),
                moves_count=('pohyby', 'sum')
            ).reset_index()
            
            trend_agg['prum_poh_lok'] = np.where(trend_agg['loc_count'] > 0, trend_agg['moves_count'] / trend_agg['loc_count'], 0)
            
            fig = go.Figure()
            colors = px.colors.qualitative.Plotly 
            
            for i, q in enumerate(selected_queues):
                q_data = trend_agg[trend_agg['Queue_Split'] == q].sort_values('Month')
                color = colors[i % len(colors)]
                
                if not q_data.empty:
                    lbl_to = _t("(Počet TO)", "(TO Count)")
                    lbl_mov = _t("(Pohybů/lokaci)", "(Moves/Loc)")
                    
                    fig.add_trace(go.Bar(
                        x=q_data['Month'], 
                        y=q_data['to_count'], 
                        name=f"{q} {lbl_to}", 
                        marker_color=color,
                        opacity=0.7,
                        offsetgroup=i
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=q_data['Month'], 
                        y=q_data['prum_poh_lok'], 
                        name=f"{q} {lbl_mov}", 
                        mode='lines+markers+text', 
                        text=q_data['prum_poh_lok'].round(1),
                        textposition='top center',
                        yaxis='y2',
                        line=dict(color=color, width=3),
                        marker=dict(symbol='diamond', size=8)
                    ))
            
            fig.update_layout(
                barmode='group',
                yaxis=dict(title=_t("Celkový počet TO", "Total TOs")),
                yaxis2=dict(title=_t("Průměr pohybů na lokaci", "Avg Moves per Location"), side="right", overlaying="y", showgrid=False),
                plot_bgcolor="rgba(0,0,0,0)", 
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0), 
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(_t("Prosím vyberte alespoň jednu Queue pro zobrazení grafu.", "Please select at least one Queue to display the chart."))
    else:
        st.info(_t("Data neobsahují informace o měsíci.", "Data does not contain month information."))

    return disp_q
