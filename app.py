"""
App Streamlit per la generazione dell'orario scolastico.

Avvio:
    streamlit run app.py
"""
import io
import pandas as pd
import streamlit as st

from io_data import leggi_input, scrivi_output
from scheduler import genera_orario, GIORNI_DEFAULT, ORTOOLS_DISPONIBILE

ORE_PER_GIORNO = 5

st.set_page_config(
    page_title="Generatore Orario — Scuola Pier Cironi di Prato",
    page_icon="🏫",
    layout="wide",
)

# ---------------------------------------------------------------------
# Stile istituzionale (colori ministeriali: blu istituzionale + bianco)
# ---------------------------------------------------------------------
st.markdown(
    """
    <style>
    .intestazione-scuola {
        background: linear-gradient(90deg, #0b3d66 0%, #1a5a8a 100%);
        color: white;
        padding: 1.4rem 1.8rem;
        border-radius: 8px;
        margin-bottom: 1.2rem;
    }
    .intestazione-scuola h1 {
        color: white !important;
        margin-bottom: 0.1rem;
        font-size: 1.6rem;
    }
    .intestazione-scuola p {
        color: #e6eef5;
        margin: 0;
        font-size: 0.92rem;
    }
    .stButton>button[kind="primary"] {
        background-color: #0b3d66;
        border-color: #0b3d66;
    }
    .stButton>button[kind="primary"]:hover {
        background-color: #1a5a8a;
        border-color: #1a5a8a;
    }
    footer.crediti {
        text-align: center;
        color: #888;
        font-size: 0.85rem;
        margin-top: 2.5rem;
        padding-top: 0.8rem;
        border-top: 1px solid #ddd;
    }
    </style>

    <div class="intestazione-scuola">
        <h1>🏫 Scuola Pier Cironi di Prato</h1>
        <p>Istituto Comprensivo "Pier Cironi" — Viale della Repubblica, 17 - 59100 Prato (PO)</p>
        <p>Generatore automatico dell'orario settimanale scolastico</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Stato di sessione
# ---------------------------------------------------------------------
for chiave, default in [
    ("professori", {}), ("classi", []), ("materie", {}), ("aule_preferenze", {}),
    ("orario", {}), ("risultato_messaggio", ""),
]:
    if chiave not in st.session_state:
        st.session_state[chiave] = default

st.caption("Greedy (con vincolo aule DADA) oppure OR-Tools CP-SAT — con preferenze soft di giorno")

# ---------------------------------------------------------------------
# 1. Caricamento file
# ---------------------------------------------------------------------
st.header("1. Carica l'Excel di input")
file_caricato = st.file_uploader(
    "Fogli richiesti: Professori, Classi, Materie. Foglio opzionale: Aule.",
    type=["xlsx"],
)

if file_caricato is not None:
    try:
        professori, classi, materie, aule_preferenze = leggi_input(file_caricato)
        st.session_state.professori = professori
        st.session_state.classi = classi
        st.session_state.materie = materie
        st.session_state.aule_preferenze = aule_preferenze
        st.success(
            f"✅ Caricati {len(professori)} professori, {len(classi)} classi, "
            f"{len(materie)} materie, {len(aule_preferenze)} preferenze aule."
        )
    except Exception as e:
        st.error(f"Impossibile leggere il file: {e}")

# ---------------------------------------------------------------------
# 2. Riepilogo dati
# ---------------------------------------------------------------------
if st.session_state.professori:
    st.header("2. Dati caricati")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        st.subheader("👨‍🏫 Professori")
        righe = [
            {
                "Nome": nome,
                "Materie": ", ".join(info["materie"]),
                "Max ore/sett.": info["max_ore"],
                "Giorno preferito": info.get("giorno_preferito", "—"),
                "Aula": info.get("aula", f"Aula_{nome}"),
            }
            for nome, info in st.session_state.professori.items()
        ]
        st.dataframe(pd.DataFrame(righe), use_container_width=True, hide_index=True)

    with col2:
        st.subheader("🏫 Classi")
        st.dataframe(pd.DataFrame({"Classe": st.session_state.classi}),
                     use_container_width=True, hide_index=True)

        st.subheader("📚 Materie")
        st.dataframe(
            pd.DataFrame(
                [{"Materia": m, "Ore/sett.": o} for m, o in st.session_state.materie.items()]
            ),
            use_container_width=True, hide_index=True,
        )

    with col3:
        st.subheader("🚪 Preferenze aule")
        if st.session_state.aule_preferenze:
            st.dataframe(
                pd.DataFrame(
                    [{"Aula": a, "Giorno preferito": g}
                     for a, g in st.session_state.aule_preferenze.items()]
                ),
                use_container_width=True, hide_index=True,
            )
        else:
            st.caption("Nessuna preferenza specificata.")

    ore_richieste = sum(st.session_state.materie.values()) * len(st.session_state.classi)
    ore_disponibili = sum(info["max_ore"] for info in st.session_state.professori.values())
    st.info(f"Ore settimanali richieste: **{ore_richieste}** — disponibili: **{ore_disponibili}**")
    if ore_richieste > ore_disponibili:
        st.warning("⚠️ Le ore richieste superano quelle disponibili: la generazione potrebbe fallire "
                    "o produrre un orario incompleto.")

    # -------------------------------------------------------------
    # 3. Parametri e generazione
    # -------------------------------------------------------------
    st.header("3. Genera l'orario")

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        opzioni_modalita = ["greedy"] + (["ortools"] if ORTOOLS_DISPONIBILE else [])
        modalita = st.selectbox(
            "Modalità",
            opzioni_modalita,
            format_func=lambda m: "🟢 Greedy (stabile)" if m == "greedy" else "🔵 OR-Tools (ottimale)",
        )
        if not ORTOOLS_DISPONIBILE:
            st.caption("⚠️ OR-Tools non installato (`pip install ortools`): solo Greedy disponibile.")
    with col_b:
        tempo = st.number_input(
            "Tempo max (sec, OR-Tools) / Tentativi (Greedy)",
            min_value=1, max_value=120, value=15,
        )

    if st.button("⚡ Genera orario", type="primary"):
        with st.spinner(f"Generazione in corso ({modalita})…"):
            risultato = genera_orario(
                st.session_state.professori,
                st.session_state.classi,
                st.session_state.materie,
                ore_per_giorno=ORE_PER_GIORNO,
                tempo_max_sec=tempo,
                modalita=modalita,
                aule_preferenze=st.session_state.aule_preferenze,
            )

        if not risultato.ok:
            st.error(f"❌ {risultato.messaggio}")
            st.info("💡 Suggerimenti: aumenta tempo/tentativi, riduci il monte ore richiesto, "
                     "aggiungi più professori, oppure prova l'altra modalità.")
            st.session_state.orario = {}
        else:
            st.session_state.orario = risultato.orario
            st.session_state.risultato_messaggio = risultato.messaggio
            st.success(f"✅ Orario generato con successo! {risultato.messaggio}")

# ---------------------------------------------------------------------
# 4. Visualizzazione ed esportazione
# ---------------------------------------------------------------------
if st.session_state.orario:
    st.header("4. Orario generato")

    tabs = st.tabs(st.session_state.classi)
    for classe, tab in zip(st.session_state.classi, tabs):
        with tab:
            dati_classe = st.session_state.orario.get(classe, {})
            righe = []
            for h in range(ORE_PER_GIORNO):
                riga = {"Ora": h + 1}
                for g in GIORNI_DEFAULT:
                    riga[g] = dati_classe.get((g, h), "")
                righe.append(riga)
            df = pd.DataFrame(righe).set_index("Ora")
            st.dataframe(df, use_container_width=True)

    st.header("5. Esporta")
    buffer = io.BytesIO()
    scrivi_output(buffer, st.session_state.orario, st.session_state.classi,
                  GIORNI_DEFAULT, ORE_PER_GIORNO)
    buffer.seek(0)
    st.download_button(
        "💾 Scarica orario in Excel",
        data=buffer,
        file_name="orario_generato.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------
st.markdown(
    """
    <footer class="crediti">
        Sviluppato da <strong>Annunziata Antenore</strong> per la
        <a href="https://www.istitutocironi.edu.it/" target="_blank">Scuola Pier Cironi di Prato</a>
    </footer>
    """,
    unsafe_allow_html=True,
)
