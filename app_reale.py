"""
App Streamlit — Generatore orario da assegnazione REALE
(docenti_reali.xlsx: assegnazioni fisse docente-classe-materia-ore + vincoli).

Avvio:
    streamlit run app_reale.py
"""
import io
import pandas as pd
import streamlit as st

from io_docenti import leggi_assegnazioni, valida_assegnazioni
from io_data import scrivi_output
from scheduler_reale import genera_orario_reale, GIORNI_DEFAULT, ORE_PER_GIORNO

st.set_page_config(page_title="Orario — Scuola Pier Cironi di Prato", page_icon="🏫", layout="wide")

st.markdown(
    """
    <style>
    .intestazione-scuola { background: linear-gradient(90deg, #0b3d66 0%, #1a5a8a 100%);
        color: white; padding: 1.4rem 1.8rem; border-radius: 8px; margin-bottom: 1.2rem; }
    .intestazione-scuola h1 { color: white !important; margin-bottom: 0.1rem; font-size: 1.6rem; }
    .intestazione-scuola p { color: #e6eef5; margin: 0; font-size: 0.92rem; }
    .stButton>button[kind="primary"] { background-color: #0b3d66; border-color: #0b3d66; }
    footer.crediti { text-align:center; color:#888; font-size:0.85rem; margin-top:2.5rem;
                      padding-top:0.8rem; border-top:1px solid #ddd; }
    </style>
    <div class="intestazione-scuola">
        <h1>🏫 Scuola Pier Cironi di Prato</h1>
        <p>Generatore orario da assegnazione reale docenti-classi-materie</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("📋 Regole applicate"):
    st.markdown("""
**Dai dati caricati (per ciascun docente):** giorni disponibili, max ore/giorno, aule fisse/speciali.

**Vincoli rigidi aggiuntivi (sempre rispettati):**
- Un solo laboratorio Scienze (aula 37, classi 1e/2e) — le 3e in aula 38
- Un solo laboratorio Tecnologia (aula 27, classi 2e/3e) — le 1e in aula 28
- Un'unica palestra: max 2 classi/slot, solo stesso anno, 2B e 2F sempre da sole
- Motoria mai martedì/giovedì alla 3ª/4ª ora
- 2E: Religione fissa alla 1ª ora — 2F: Religione fissa all'ultima ora
- REL2 (1B, 2B, 3B): tutte le ore di Religione il martedì
- Un docente non vede la stessa classe più di una volta al giorno (eccezioni necessarie:
  quando le ore non ci starebbero altrimenti in 5 giorni, o quando il docente segue
  la stessa materia su 3+ classi diverse)

⚠️ **Nota**: questa ultima regola, con tutto il resto attivo, porta tipicamente a
**622/630 ore (98,7%)** invece del 100% — è un compromesso deliberato: le poche ore
residue (di solito su Storia/Geografia) vanno completate a mano nell'Excel esportato.

**Preferenze forti (misurate e riportate, non sempre garantite al 100%):**
- Ogni docente: almeno un'entrata alla 1ª ora e una alla 6ª ora nella settimana
- Italiano/Storia/Geografia mai lo stesso giorno per la stessa classe
- Matematica/Scienze mai lo stesso giorno per la stessa classe
- Minimizzare le ore "di buco" nell'orario di ciascun docente
    """)

for chiave, default in [("assegnazioni", {}), ("vincoli", {}), ("classi", []),
                         ("materie_target", {}), ("orario", {}), ("report", {})]:
    if chiave not in st.session_state:
        st.session_state[chiave] = default

# ---------------------------------------------------------------------
st.header("1. Carica l'Excel delle assegnazioni")
file_caricato = st.file_uploader(
    "Fogli richiesti: Assegnazioni, VincoliDocenti, Classi, MaterieTarget", type=["xlsx"]
)

if file_caricato is not None:
    try:
        assegnazioni, vincoli, classi, materie_target = leggi_assegnazioni(file_caricato)
        st.session_state.assegnazioni = assegnazioni
        st.session_state.vincoli = vincoli
        st.session_state.classi = classi
        st.session_state.materie_target = materie_target
    except Exception as e:
        st.error(f"Impossibile leggere il file: {e}")
        st.stop()

    report_check = valida_assegnazioni(assegnazioni, vincoli, classi, materie_target)
    if report_check["ok"]:
        st.success(f"✅ Dati coerenti: {report_check['n_docenti']} docenti, "
                   f"{report_check['n_classi']} classi, {report_check['n_assegnazioni']} assegnazioni.")
    else:
        st.error(f"⚠️ Attenzione: i dati hanno {len(report_check['errori_docenti'])} incoerenze sui totali "
                 f"docente e {len(report_check['errori_classi'])} classi con ore non corrispondenti al target. "
                 f"Puoi comunque generare l'orario, ma il risultato rifletterà queste incoerenze. "
                 f"Consiglio: correggi il file e ricaricalo.")
        with st.expander("Dettaglio incoerenze"):
            for e in report_check["errori_docenti"]:
                st.write(f"- Docente **{e['docente']}**: {e['calcolato']}h calcolate vs {e['dichiarato']}h dichiarate")
            for e in report_check["errori_classi"]:
                for p in e["problemi"]:
                    st.write(f"- **{e['classe']} / {p['materia']}**: {p['reali']}h invece di {p['target']}h")

# ---------------------------------------------------------------------
if st.session_state.assegnazioni:
    st.header("2. Genera l'orario")
    tentativi = st.slider("Tentativi", min_value=5, max_value=150, value=60, step=5)
    st.caption("⏱️ ~1 secondo per tentativo con 21 classi / 45 docenti. "
               "Con la regola \"un docente non vede la stessa classe più di una volta al giorno\" attiva, "
               "il risultato tipico è 622/630 ore (98,7%) — le poche ore residue vanno completate a mano. "
               "Nessun OR-Tools: solo Greedy con pianificazione dedicata per palestra/religione fissa e riparazione via scambio.")

    if st.button("⚡ Genera orario", type="primary"):
        with st.spinner(f"Generazione in corso ({tentativi} tentativi)…"):
            risultato = genera_orario_reale(
                st.session_state.assegnazioni, st.session_state.vincoli, st.session_state.classi,
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
                       f"Puoi aumentare i tentativi e rigenerare, oppure completare le ore mancanti a mano.")

        with st.expander("📊 Report", expanded=not risultato.ok):
            st.write(f"Conflitti Italiano/Storia/Geografia stesso giorno: "
                     f"**{risultato.report.get('conflitti_trio_umanistico', '—')}**")
            st.write(f"Conflitti Matematica/Scienze stesso giorno: "
                     f"**{risultato.report.get('conflitti_coppia_scientifica', '—')}**")
            senza_entrata = risultato.report.get("docenti_senza_entrata_1_6", [])
            st.write(f"Docenti senza entrata 1ª+6ª ora completa: **{len(senza_entrata)}** "
                     f"({', '.join(senza_entrata) if senza_entrata else 'nessuno'})")

            if not risultato.ok:
                mancanti = []
                for docente, classi_map in st.session_state.assegnazioni.items():
                    for classe, materie in classi_map.items():
                        for materia, ore in materie.items():
                            gia = sum(1 for v in risultato.orario.get(classe, {}).values()
                                      if v.startswith(f"{materia} ({docente})"))
                            if gia < ore:
                                mancanti.append(f"{docente} — {classe} — {materia}: {gia}/{ore}")
                if mancanti:
                    st.write("**Ore non piazzate:**")
                    for m in mancanti:
                        st.write(f"- {m}")

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
            st.dataframe(pd.DataFrame(righe).set_index("Ora"), use_container_width=True)

    st.header("4. Esporta")
    buffer = io.BytesIO()
    scrivi_output(buffer, st.session_state.orario, st.session_state.classi, GIORNI_DEFAULT, ORE_PER_GIORNO)
    buffer.seek(0)
    st.download_button(
        "💾 Scarica orario in Excel", data=buffer, file_name="orario_generato.xlsx",
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
