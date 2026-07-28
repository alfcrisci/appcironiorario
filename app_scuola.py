"""
App Streamlit — Generatore Orario "Scuola Pier Cironi di Prato"
Motore dedicato (scheduler_scuola.py, solo Greedy con riparazione via scambio
— nessun OR-Tools) che implementa le regole specifiche della scuola:
aule speciali (labs/palestra), religione fissa, ecc.

Avvio:
    streamlit run app_scuola.py
"""
import io
import pandas as pd
import streamlit as st

from io_data import leggi_input, scrivi_output, scrivi_output_per_docente
from scheduler_scuola import genera_orario_scuola, GIORNI_DEFAULT, ORE_PER_GIORNO

st.set_page_config(page_title="Orario — Scuola Pier Cironi di Prato", page_icon="🏫", layout="wide")

st.markdown(
    """
    <style>
    .intestazione-scuola {
        background: linear-gradient(90deg, #0b3d66 0%, #1a5a8a 100%);
        color: white; padding: 1.4rem 1.8rem; border-radius: 8px; margin-bottom: 1.2rem;
    }
    .intestazione-scuola h1 { color: white !important; margin-bottom: 0.1rem; font-size: 1.6rem; }
    .intestazione-scuola p { color: #e6eef5; margin: 0; font-size: 0.92rem; }
    .stButton>button[kind="primary"] { background-color: #0b3d66; border-color: #0b3d66; }
    .stButton>button[kind="primary"]:hover { background-color: #1a5a8a; border-color: #1a5a8a; }
    footer.crediti { text-align:center; color:#888; font-size:0.85rem; margin-top:2.5rem;
                      padding-top:0.8rem; border-top:1px solid #ddd; }
    </style>
    <div class="intestazione-scuola">
        <h1>🏫 Scuola Pier Cironi di Prato</h1>
        <p>Istituto Comprensivo "Pier Cironi" — Viale della Repubblica, 17 - 59100 Prato (PO)</p>
        <p>Generatore orario — motore dedicato con regole specifiche d'istituto</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("📋 Regole applicate da questo motore"):
    st.markdown("""
**Vincoli rigidi (sempre rispettati):**
- Nessuna sovrapposizione classe/docente/aula
- Un solo laboratorio di Scienze (aula 37, classi prime e seconde) — le terze in aula 38
- Un solo laboratorio di Tecnologia (aula 27, classi seconde e terze) — le prime in aula 28
- Un'unica palestra: max 2 classi contemporaneamente, solo stesso anno, tranne 2B e 2F che stanno sempre da sole
- Motoria mai martedì/giovedì alla 3ª e 4ª ora
- 2E: Religione fissa alla 1ª ora — 2F: Religione fissa all'ultima ora
- Un docente non insegna alla stessa classe più di una volta al giorno (eccezione necessaria: Italiano, fino a 2 volte — 8 ore/settimana non stanno altrimenti in 5 giorni)

**Preferenze forti (rispettate il più possibile, misurate a fine generazione):**
- Religione abbinata a un'ora di Inglese lo stesso giorno
- Italiano, Storia e Geografia mai lo stesso giorno
- Matematica e Scienze mai lo stesso giorno
- Al massimo un'ora di Inglese nei giorni con Seconda Lingua
- Italiano/Matematica/Inglese non sempre alla prima o all'ultima ora
- 1D, 1E, 1F: Religione preferibilmente alla prima o ultima ora

⚠️ **Nota**: alcune di queste preferenze sono matematicamente incompatibili tra loro
in una settimana di 5 giorni (es. 8 ore di Italiano da sole richiedono già 4 giorni,
lasciando troppo poco spazio per tenere Storia/Geografia sempre su giorni diversi).
Per questo sono preferenze forti, non vincoli assoluti — il motore le soddisfa il
più possibile e riporta a fine generazione quante ne ha rispettate.
    """)

for chiave, default in [("professori", {}), ("classi", []), ("materie", {}), ("orario", {}), ("report", {})]:
    if chiave not in st.session_state:
        st.session_state[chiave] = default

# ---------------------------------------------------------------------
st.header("1. Carica l'Excel di input")
file_caricato = st.file_uploader("Fogli richiesti: Professori, Classi, Materie.", type=["xlsx"])

if file_caricato is not None:
    try:
        professori, classi, materie, _ = leggi_input(file_caricato)
        st.session_state.professori = professori
        st.session_state.classi = classi
        st.session_state.materie = materie
        st.success(f"✅ Caricati {len(professori)} professori, {len(classi)} classi, {len(materie)} materie.")
    except Exception as e:
        st.error(f"Impossibile leggere il file: {e}")

# ---------------------------------------------------------------------
if st.session_state.professori:
    st.header("2. Genera l'orario")
    tentativi = st.slider(
        "Tentativi (più tentativi = più probabilità di completare al 100%, ma più lento)",
        min_value=5, max_value=60, value=20, step=5,
    )
    st.caption("⏱️ Stima: ~1 secondo per tentativo con 21 classi. Nessun OR-Tools: solo Greedy con riparazione via scambio.")

    if st.button("⚡ Genera orario", type="primary"):
        with st.spinner(f"Generazione in corso ({tentativi} tentativi)…"):
            risultato = genera_orario_scuola(
                st.session_state.professori, st.session_state.classi, st.session_state.materie,
                ore_per_giorno=ORE_PER_GIORNO, tentativi=tentativi,
            )
        st.session_state.orario = risultato.orario
        st.session_state.report = risultato.report

        atteso = risultato.report.get("lezioni_totali_attese", 0)
        piazzate = risultato.report.get("lezioni_piazzate", 0)
        pct = 100 * piazzate / atteso if atteso else 0

        if risultato.ok:
            st.success(f"✅ Orario completo ({piazzate}/{atteso} ore, 100%).")
        else:
            st.warning(f"⚠️ Orario quasi completo: {piazzate}/{atteso} ore ({pct:.1f}%). "
                       f"Alcune ore non hanno trovato posto — vedi il dettaglio sotto. "
                       f"Puoi aumentare i tentativi e rigenerare.")

        with st.expander("📊 Report sulle preferenze e su eventuali ore mancanti", expanded=not risultato.ok):
            st.write(f"Conflitti Italiano/Storia/Geografia stesso giorno: "
                     f"**{risultato.report.get('conflitti_trio_umanistico', '—')}**")
            st.write(f"Conflitti Matematica/Scienze stesso giorno: "
                     f"**{risultato.report.get('conflitti_coppia_scientifica', '—')}**")
            non_acc = risultato.report.get("religione_non_accoppiata", [])
            st.write(f"Religione non abbinata a Inglese: **{len(non_acc)}** "
                     f"({', '.join(non_acc) if non_acc else 'nessuna'})")

            if not risultato.ok:
                mancanti = {}
                for classe in st.session_state.classi:
                    conteggio = {}
                    for v in risultato.orario.get(classe, {}).values():
                        m = v.split(" (")[0]
                        conteggio[m] = conteggio.get(m, 0) + 1
                    for materia, ore_richieste in st.session_state.materie.items():
                        diff = ore_richieste - conteggio.get(materia, 0)
                        if diff > 0:
                            mancanti.setdefault(materia, []).append(f"{classe} (-{diff}h)")
                if mancanti:
                    st.write("**Ore non piazzate:**")
                    for m, lst in mancanti.items():
                        st.write(f"- {m}: {', '.join(lst)}")

# ---------------------------------------------------------------------
if st.session_state.orario:
    st.header("3. Orario per classe")
    tabs = st.tabs(st.session_state.classi)
    for classe, tab in zip(st.session_state.classi, tabs):
        with tab:
            dati_classe = st.session_state.orario.get(classe, {})
            righe = []
            for h in range(ORE_PER_GIORNO):
                riga = {"Ora": h + 1}
                for g in GIORNI_DEFAULT:
                    riga[g] = dati_classe.get((g, h), "—")
                righe.append(riga)
            df = pd.DataFrame(righe).set_index("Ora")
            st.dataframe(df, use_container_width=True)

    st.header("4. Esporta")
    col_a, col_b = st.columns(2)

    with col_a:
        buffer = io.BytesIO()
        scrivi_output(buffer, st.session_state.orario, st.session_state.classi, GIORNI_DEFAULT, ORE_PER_GIORNO)
        buffer.seek(0)
        st.download_button(
            "💾 Scarica orario per classe", data=buffer, file_name="orario_per_classe.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_b:
        buffer_doc = io.BytesIO()
        scrivi_output_per_docente(buffer_doc, st.session_state.orario, GIORNI_DEFAULT, ORE_PER_GIORNO)
        buffer_doc.seek(0)
        st.download_button(
            "👨‍🏫 Scarica orario per docente", data=buffer_doc, file_name="orario_per_docente.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

st.markdown(
    """
    <footer class="crediti">
        Sviluppato da <strong>Annunziata Antenore</strong> per la
        <a href="https://www.istitutocironi.edu.it/" target="_blank">Scuola Pier Cironi di Prato</a>
    </footer>
    """,
    unsafe_allow_html=True,
)
