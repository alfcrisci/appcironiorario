"""
App Streamlit — Verifica assegnazione docenti-classi-materie-ore.

Carica l'Excel (fogli: Assegnazioni, VincoliDocenti, Classi, MaterieTarget) e
verifica:
  1) che il totale ore di ciascun docente corrisponda a quanto dichiarato
  2) che ogni classe riceva, per ciascuna materia, esattamente le ore attese

Avvio:
    streamlit run app_check_docenti.py
"""
import pandas as pd
import streamlit as st

from io_docenti import leggi_assegnazioni, valida_assegnazioni

st.set_page_config(page_title="Verifica assegnazione docenti", page_icon="✅", layout="wide")

st.markdown(
    """
    <style>
    .intestazione-scuola {
        background: linear-gradient(90deg, #0b3d66 0%, #1a5a8a 100%);
        color: white; padding: 1.4rem 1.8rem; border-radius: 8px; margin-bottom: 1.2rem;
    }
    .intestazione-scuola h1 { color: white !important; margin-bottom: 0.1rem; font-size: 1.6rem; }
    .intestazione-scuola p { color: #e6eef5; margin: 0; font-size: 0.92rem; }
    footer.crediti { text-align:center; color:#888; font-size:0.85rem; margin-top:2.5rem;
                      padding-top:0.8rem; border-top:1px solid #ddd; }
    </style>
    <div class="intestazione-scuola">
        <h1>✅ Verifica assegnazione docenti</h1>
        <p>Scuola Pier Cironi di Prato — controllo di coerenza dei dati prima della generazione orario</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.header("1. Carica l'Excel delle assegnazioni")
file_caricato = st.file_uploader(
    "Fogli richiesti: Assegnazioni, VincoliDocenti, Classi, MaterieTarget", type=["xlsx"]
)

if file_caricato is not None:
    try:
        assegnazioni, vincoli, classi, materie_target = leggi_assegnazioni(file_caricato)
    except Exception as e:
        st.error(f"Impossibile leggere il file: {e}")
        st.stop()

    report = valida_assegnazioni(assegnazioni, vincoli, classi, materie_target)

    st.header("2. Risultato del controllo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Docenti", report["n_docenti"])
    c2.metric("Classi", report["n_classi"])
    c3.metric("Righe di assegnazione", report["n_assegnazioni"])

    if report["ok"]:
        st.success("✅ Tutto corretto: i totali dei docenti tornano e ogni classe riceve esattamente "
                   "le ore previste per materia.")
    else:
        st.error(f"⚠️ Trovate incoerenze: {len(report['errori_docenti'])} docenti con totale errato, "
                 f"{len(report['errori_classi'])} classi con ore non corrispondenti al target.")

    # --- Dettaglio errori docenti ---
    if report["errori_docenti"]:
        st.subheader("❌ Docenti: totale calcolato ≠ totale dichiarato")
        df_err_doc = pd.DataFrame(report["errori_docenti"])
        df_err_doc.columns = ["Docente", "Ore calcolate", "Ore dichiarate"]
        st.dataframe(df_err_doc, use_container_width=True, hide_index=True)

    # --- Dettaglio errori classi ---
    if report["errori_classi"]:
        st.subheader("❌ Classi: ore non corrispondenti al target")
        for e in report["errori_classi"]:
            with st.expander(f"{e['classe']} — totale {e['totale']}h (atteso {e['totale_atteso']}h)"):
                for p in e["problemi"]:
                    diff = p["reali"] - p["target"]
                    segno = "🔺 in eccesso" if diff > 0 else "🔻 mancante"
                    st.write(f"**{p['materia']}**: {p['reali']}h invece di {p['target']}h "
                             f"({segno}) — fonti: {', '.join(p['fonti']) if p['fonti'] else 'nessuna'}")

    # --- Vista tabellare completa (sempre disponibile) ---
    st.header("3. Dati caricati")
    tab1, tab2, tab3 = st.tabs(["Assegnazioni per docente", "Vincoli docenti", "Ore per classe/materia"])

    with tab1:
        docente_sel = st.selectbox("Docente", sorted(assegnazioni.keys()))
        righe = []
        for classe, materie in assegnazioni[docente_sel].items():
            for materia, ore in materie.items():
                righe.append({"Classe": classe, "Materia": materia, "Ore": ore})
        df = pd.DataFrame(righe).sort_values(["Classe", "Materia"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"Totale: {df['Ore'].sum()}h — dichiarato: "
                   f"{vincoli[docente_sel]['totale_dichiarato'] or '—'}h")

    with tab2:
        righe_vincoli = []
        for docente, v in vincoli.items():
            righe_vincoli.append({
                "Docente": docente, "Totale dichiarato": v["totale_dichiarato"] or "—",
                "Giorni": v["giorni"], "Max ore/giorno": v["max_ore_giorno"],
                "Max buco": v["max_buco"], "Entrata 1ª e 6ª": "Sì" if v["entrata_1e6"] else "",
                "Vincoli speciali": v["vincoli_speciali"],
            })
        st.dataframe(pd.DataFrame(righe_vincoli), use_container_width=True, hide_index=True)

    with tab3:
        righe_cm = []
        for classe in classi:
            riga = {"Classe": classe}
            for materia in materie_target:
                ore = sum(
                    m.get(materia, 0) for classi_map in assegnazioni.values()
                    for cl, m in classi_map.items() if cl == classe
                )
                riga[materia] = ore
            righe_cm.append(riga)
        st.dataframe(pd.DataFrame(righe_cm), use_container_width=True, hide_index=True)

st.markdown(
    """
    <footer class="crediti">
        Sviluppato da <strong>Annunziata Antenore</strong> per la
        <a href="https://www.istitutocironi.edu.it/" target="_blank">Scuola Pier Cironi di Prato</a>
    </footer>
    """,
    unsafe_allow_html=True,
)
