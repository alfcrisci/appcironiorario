"""Lettura e validazione dell'Excel 'Assegnazioni docenti reali'."""
from collections import defaultdict
import pandas as pd


def leggi_assegnazioni(path):
    """Legge il file Excel e restituisce (assegnazioni, vincoli_docenti, classi, materie_target).

    assegnazioni: dict {docente: {classe: {materia: ore}}}
    vincoli_docenti: dict {docente: {"totale_dichiarato": int|None, "giorni": str,
                                       "max_ore_giorno": ..., "max_buco": ..., "entrata_1e6": bool,
                                       "vincoli_speciali": str}}
    classi: list di stringhe
    materie_target: dict {materia: ore_settimanali}
    """
    xls = pd.read_excel(path, sheet_name=None)

    for foglio in ("Assegnazioni", "VincoliDocenti", "Classi", "MaterieTarget"):
        if foglio not in xls:
            raise ValueError(f"Foglio '{foglio}' non trovato nel file Excel.")

    assegnazioni = defaultdict(lambda: defaultdict(dict))
    for _, row in xls["Assegnazioni"].iterrows():
        docente = str(row["Docente"]).strip()
        classe = str(row["Classe"]).strip()
        materia = str(row["Materia"]).strip()
        ore = int(row["Ore"])
        assegnazioni[docente][classe][materia] = ore

    vincoli_docenti = {}
    for _, row in xls["VincoliDocenti"].iterrows():
        docente = str(row["Docente"]).strip()
        totale = row.get("TotaleDichiarato")
        totale = int(totale) if pd.notna(totale) else None
        vincoli_docenti[docente] = {
            "totale_dichiarato": totale,
            "giorni": str(row.get("Giorni", "")) if pd.notna(row.get("Giorni")) else "",
            "max_ore_giorno": row.get("MaxOreGiorno") if pd.notna(row.get("MaxOreGiorno")) else "",
            "max_buco": row.get("MaxBuco") if pd.notna(row.get("MaxBuco")) else "",
            "entrata_1e6": str(row.get("Entrata1e6", "")).strip() == "Sì",
            "vincoli_speciali": str(row.get("VincoliSpeciali", "")) if pd.notna(row.get("VincoliSpeciali")) else "",
        }

    classi = [str(c).strip() for c in xls["Classi"].iloc[:, 0].tolist()]

    materie_target = {}
    for _, row in xls["MaterieTarget"].iterrows():
        materie_target[str(row.iloc[0]).strip()] = int(row.iloc[1])

    return dict(assegnazioni), vincoli_docenti, classi, materie_target


def valida_assegnazioni(assegnazioni, vincoli_docenti, classi, materie_target):
    """Esegue gli stessi controlli fatti manualmente:
    1) il totale delle ore assegnate a ciascun docente corrisponde al totale dichiarato
    2) ogni classe riceve, per ciascuna materia, esattamente le ore attese (somma = 30)

    Ritorna un dict con i dettagli, pronto da mostrare in UI.
    """
    # --- 1. Verifica totali docente ---
    errori_docenti = []
    for docente, info in vincoli_docenti.items():
        totale_calcolato = sum(
            ore for classi_map in assegnazioni.get(docente, {}).values() for ore in classi_map.values()
        )
        atteso = info["totale_dichiarato"]
        if atteso is not None and totale_calcolato != atteso:
            errori_docenti.append({
                "docente": docente, "calcolato": totale_calcolato, "dichiarato": atteso,
            })

    # --- 2. Verifica ore per classe/materia ---
    ore_classe_materia = defaultdict(lambda: defaultdict(int))
    fonte_classe_materia = defaultdict(lambda: defaultdict(list))
    for docente, classi_map in assegnazioni.items():
        for classe, materie in classi_map.items():
            for materia, ore in materie.items():
                ore_classe_materia[classe][materia] += ore
                fonte_classe_materia[classe][materia].append(f"{docente}:{ore}h")

    errori_classi = []
    totale_atteso_classe = sum(materie_target.values())
    for classe in classi:
        totale_classe = sum(ore_classe_materia[classe].values())
        problemi = []
        for materia, ore_target in materie_target.items():
            ore_reali = ore_classe_materia[classe].get(materia, 0)
            if ore_reali != ore_target:
                problemi.append({
                    "materia": materia, "reali": ore_reali, "target": ore_target,
                    "fonti": fonte_classe_materia[classe].get(materia, []),
                })
        if problemi or totale_classe != totale_atteso_classe:
            errori_classi.append({"classe": classe, "totale": totale_classe,
                                   "totale_atteso": totale_atteso_classe, "problemi": problemi})

    return {
        "errori_docenti": errori_docenti,
        "errori_classi": errori_classi,
        "n_docenti": len(vincoli_docenti),
        "n_classi": len(classi),
        "n_assegnazioni": sum(
            1 for classi_map in assegnazioni.values() for materie in classi_map.values() for _ in materie
        ),
        "ok": not errori_docenti and not errori_classi,
    }
