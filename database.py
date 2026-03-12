import os
import streamlit as st
from supabase import create_client, Client
import pandas as pd
import io

# Inicializace klienta Supabase
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Chyba připojení k databázi. Zkontrolujte st.secrets.")
    supabase = None

# Název bucketu, který jsi vytvořil v Supabase Storage
BUCKET_NAME = "warehouse_data"

def save_to_db(df, name, append=False):
    """
    Extrémně efektivní ukládání: Zkomprimuje DataFrame do formátu Parquet 
    a uloží jako jediný malý soubor do Supabase Storage.
    Pokud je append=True, nejdřív stáhne stará data, připojí k nim nová a vyčistí duplicity.
    """
    if supabase is None or df is None or df.empty:
        return False
        
    try:
        # POKUD CHCEME DATA PŘIPOJIT, NEJPRVE JE STÁHNEME A SLOUČÍME
        if append:
            old_df = load_from_db(name)
            if old_df is not None and not old_df.empty:
                df = pd.concat([old_df, df], ignore_index=True)
                
                # Inteligentní odstranění duplicit (ponecháme vždy nejnovější záznam)
                if name == 'raw_pick' and 'Transfer Order Number' in df.columns:
                    df = df.drop_duplicates(subset=['Transfer Order Number', 'Material', 'Confirmation date', 'Confirmation time'], keep='last')
                elif name == 'raw_vekp' and 'Handling Unit' in df.columns:
                    df = df.drop_duplicates(subset=['Handling Unit'], keep='last')
                elif name == 'raw_cats':
                    c_del_cats = next((c for c in df.columns if str(c).strip().lower() in ['lieferung', 'delivery', 'zakázka']), None)
                    if c_del_cats:
                        df = df.drop_duplicates(subset=[c_del_cats], keep='last')
                    else:
                        df = df.drop_duplicates(keep='last')
                elif name == 'raw_queue' and 'Transfer Order Number' in df.columns:
                    df = df.drop_duplicates(subset=['Transfer Order Number'], keep='last')
                elif name in ['raw_marm', 'raw_manual'] and 'Material' in df.columns:
                    df = df.drop_duplicates(subset=['Material'], keep='last')
                else:
                    df = df.drop_duplicates(keep='last')
                    
        # 1. Převedeme data na zkomprimovaný binární Parquet
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine='pyarrow', index=False)
        buffer.seek(0)
        file_bytes = buffer.read()
        
        file_path = f"{name}.parquet"
        
        # 2. Smažeme starý soubor, pokud existuje
        try:
            supabase.storage.from_(BUCKET_NAME).remove([file_path])
        except:
            pass # Pokud soubor neexistoval, nic se neděje
            
        # 3. Nahrajeme nový komprimovaný soubor
        supabase.storage.from_(BUCKET_NAME).upload(file_path, file_bytes)
        return True
        
    except Exception as e:
        st.error(f"Chyba při ukládání {name} do Storage: {e}")
        return False

# TENTO JEDEN ŘÁDEK VŠE ZRYCHLÍ NA MAXIMUM:
@st.cache_data(show_spinner=False)
def load_from_db(name):
    """
    Extrémně rychlé čtení: Stáhne komprimovaný soubor a rozbalí ho 
    přímo do Pandas DataFrame. Pamatuje si ho v RAM!
    """
    if supabase is None:
        return None
        
    try:
        file_path = f"{name}.parquet"
        
        # 1. Stáhneme binární soubor ze Storage
        response = supabase.storage.from_(BUCKET_NAME).download(file_path)
        
        # 2. Převedeme binární data zpět na DataFrame
        buffer = io.BytesIO(response)
        df = pd.read_parquet(buffer, engine='pyarrow')
        return df
        
    except Exception as e:
        # Soubor na Supabase zatím neexistuje
        return None
