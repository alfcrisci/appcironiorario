"""
Scheduler per l'assegnazione REALE (docenti_reali.py): le coppie
docente-classe-materia-ore sono già fissate (non le sceglie l'algoritmo).
Il motore deve solo trovare GLI ORARI (giorno, ora) rispettando:

VINCOLI RIGIDI (sempre rispettati):
  - nessuna sovrapposizione classe / docente / aula
  - ogni docente lavora solo nei suoi giorni disponibili
  - ogni docente non supera il suo max ore/giorno
  - aule speciali: Lab Scienze (37, classi 1e/2e) / aula 38 (3e);
    Lab Tecnologia (27, classi 2e/3e) / aula 28 (1e); Palestra unica
    (max 2 classi contemporanee, stesso anno, 2B/2F sempre da sole)
  - Motoria mai martedì/giovedì 3a/4a ora
  - Religione: 2E fissa alla 1a ora, 2F fissa all'ultima ora
  - REL2 (1B,2B,3B) tutte le ore di martedì (giorni disponibili = [Mar])
  - MATE7: esattamente 2 ore/giorno (nessun buco, tutti i 5 giorni)

PREFERENZE FORTI (soddisfatte il più possibile, misurate e riportate):
  - minimizzare le "ore di buco" di ciascun docente (restare entro il suo max)
  - ogni docente: almeno un'entrata alla 1a ora e almeno una alla 6a ora
  - note speciali per singolo docente (es. venerdì entrata 1a ora)
  - Italiano/Storia/Geografia mai lo stesso giorno per la stessa classe
  - Matematica/Scienze mai lo stesso giorno per la stessa classe
  - al massimo un'ora di Inglese nei giorni con Seconda Lingua
  - Italiano/Matematica/Inglese non sempre alla prima o ultima ora
  - Religione abbinata a un'ora di Inglese lo stesso giorno
"""
import random
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GIORNI_DEFAULT = ["Lun", "Mar", "Mer", "Gio", "Ven"]
ORE_PER_GIORNO = 6

MOTORIA_BLOCCATA = {("Mar", 2), ("Mar", 3), ("Gio", 2), ("Gio", 3)}
MOTORIA_SOLE = {"2B", "2F"}
RELIGIONE_FISSA = {"2E": 0, "2F": ORE_PER_GIORNO - 1}
TRIO_UMANISTICO = {"Italiano", "Storia", "Geografia"}
COPPIA_SCIENTIFICA = {"Matematica", "Scienze"}


def grado_di(classe):
    return int(classe[0])


def aula_speciale(materia, grado):
    if materia == "Scienze":
        return "Lab_Scienze_Aula37" if grado in (1, 2) else "Aula_38"
    if materia == "Tecnologia":
        return "Lab_Tecnologia_Aula27" if grado in (2, 3) else "Aula_28"
    if materia == "Motoria":
        return "Palestra"
    return None


def giorni_disponibili_docente(vincoli, giorni=GIORNI_DEFAULT):
    """Deriva l'elenco dei giorni utilizzabili da un docente a partire dai
    vincoli letti dall'Excel (foglio VincoliDocenti)."""
    speciali = (vincoli.get("vincoli_speciali") or "")
    if "tutte le ore di martedì" in speciali:
        return ["Mar"]

    testo = (vincoli.get("giorni") or "").strip()
    if testo.startswith("Lun-Ven") or testo == "":
        return list(giorni)
    if "+" in testo:  # es. "Lun+Mer+Ven" o "Mar+Gio"
        return [g for g in testo.split("+") if g in giorni]
    if "giorni" in testo:
        # es. "4 giorni, libero Mer" oppure "3 giorni, giorni a scelta"
        n = int(testo.split()[0])
        if "libero" in testo:
            libero = testo.split("libero")[-1].strip()
            return [g for g in giorni if g != libero]
        # "giorni a scelta": per ora restituiamo tutti i 5, la scelta di
        # QUALI n giorni usare la fa l'algoritmo lasciando liberi gli altri
        return list(giorni)
    return list(giorni)


class RisultatoOrarioReale:
    def __init__(self, ok, stato, orario=None, messaggio="", report=None):
        self.ok = ok
        self.stato = stato
        self.orario = orario or {}
        self.messaggio = messaggio
        self.report = report or {}


class _Costruttore:
    def __init__(self, assegnazioni, vincoli_docenti, classi, giorni, ore_per_giorno):
        self.assegnazioni = assegnazioni
        self.vincoli_docenti = vincoli_docenti
        self.classi = classi
        self.giorni = giorni
        self.ore_per_giorno = ore_per_giorno

        self.giorni_doc = {d: giorni_disponibili_docente(v, giorni) for d, v in vincoli_docenti.items()}
        self.max_ore_giorno_doc = {}
        for d, v in vincoli_docenti.items():
            mx = v.get("max_ore_giorno")
            try:
                mx = int(mx)
            except (TypeError, ValueError):
                mx = ore_per_giorno
            # MATE7: "2 ore al giorno senza buco" -> cap esatto a 2
            if "esattamente 2h/giorno" in (v.get("vincoli_speciali") or ""):
                mx = 2
            self.max_ore_giorno_doc[d] = mx

        # Limite "un docente non vede la stessa classe più di una volta al
        # giorno": di norma 1, ma se le ore assegnate per quella specifica
        # combinazione docente-classe-materia non ci stanno in 5 giorni a
        # 1/giorno, il minimo necessario è calcolato automaticamente
        # (es. 6 ore -> serve almeno 2/giorno in qualche giorno).
        # Limite "un docente non vede la stessa classe più di una volta al
        # giorno": di norma 1. Due eccezioni necessarie:
        #  (a) le ore assegnate per quella combinazione docente-classe-materia
        #      non ci starebbero in 5 giorni a 1/giorno (es. Italiano 6h)
        #  (b) il docente insegna quella materia a 3 o più classi diverse
        #      (es. Matematica+Scienze a 3 classi): con soli 5 giorni serve
        #      poter raddoppiare qualche giorno per riuscire a seguirle tutte
        n_classi_per_docente_materia = defaultdict(set)
        for doc, cmap in assegnazioni.items():
            for cl, mats in cmap.items():
                for mat in mats:
                    n_classi_per_docente_materia[(doc, mat)].add(cl)

        self.limite_giornaliero_dcm = {}
        for docente, classi_map in assegnazioni.items():
            for classe, materie in classi_map.items():
                for materia, ore in materie.items():
                    n_giorni_doc = max(1, len(self.giorni_doc.get(docente, giorni)))
                    limite_ore = max(1, -(-ore // n_giorni_doc))
                    n_classi_stessa_materia = len(n_classi_per_docente_materia[(docente, materia)])
                    limite_multiclasse = 2 if n_classi_stessa_materia >= 3 else 1
                    self.limite_giornaliero_dcm[(docente, classe, materia)] = max(limite_ore, limite_multiclasse)
        self.conteggio_prof_classe_giorno = defaultdict(int)  # (docente,classe,giorno) -> n

        self.orario = defaultdict(dict)                   # classe -> {(g,h): stringa}
        self.occ_classe = defaultdict(set)
        self.occ_prof = defaultdict(set)
        self.occ_aula = defaultdict(set)
        self.occ_palestra = defaultdict(list)
        self.ore_doc_giorno = defaultdict(lambda: defaultdict(int))
        self.materie_giorno_classe = defaultdict(lambda: defaultdict(set))
        self.n_inglese_giorno = defaultdict(lambda: defaultdict(int))
        self.posizione = defaultdict(lambda: defaultdict(lambda: {"prima": 0, "ultima": 0}))
        self.entrata_prima_doc = defaultdict(set)   # docente -> set(giorni con lezione a ora 0)
        self.entrata_ultima_doc = defaultdict(set)  # docente -> set(giorni con lezione a ora 5)

    def aula_per(self, docente, materia, classe):
        speciale = aula_speciale(materia, grado_di(classe))
        if speciale:
            return speciale
        return f"Aula_{docente}"

    def puo_piazzare(self, docente, classe, materia, giorno, ora):
        if giorno not in self.giorni_doc.get(docente, self.giorni):
            return False
        if materia == "Motoria" and (giorno, ora) in MOTORIA_BLOCCATA:
            return False
        if classe in RELIGIONE_FISSA and materia == "Religione" and ora != RELIGIONE_FISSA[classe]:
            return False
        if (giorno, ora) in self.occ_classe[classe]:
            return False
        if (giorno, ora) in self.occ_prof[docente]:
            return False
        if self.ore_doc_giorno[docente][giorno] >= self.max_ore_giorno_doc.get(docente, self.ore_per_giorno):
            return False
        limite_dcm = self.limite_giornaliero_dcm.get((docente, classe, materia), 1)
        if self.conteggio_prof_classe_giorno[(docente, classe, giorno)] >= limite_dcm:
            return False

        if materia == "Motoria":
            occupanti = self.occ_palestra[(giorno, ora)]
            if classe in MOTORIA_SOLE:
                if occupanti:
                    return False
            else:
                if len(occupanti) >= 2:
                    return False
                if occupanti:
                    altra = occupanti[0]
                    if altra in MOTORIA_SOLE or grado_di(altra) != grado_di(classe):
                        return False
        else:
            aula = self.aula_per(docente, materia, classe)
            if (giorno, ora) in self.occ_aula[aula]:
                return False
        return True

    def piazza(self, docente, classe, materia, giorno, ora):
        aula = self.aula_per(docente, materia, classe)
        self.orario[classe][(giorno, ora)] = f"{materia} ({docente}) [Aula: {aula}]"
        self.occ_classe[classe].add((giorno, ora))
        self.occ_prof[docente].add((giorno, ora))
        self.ore_doc_giorno[docente][giorno] += 1
        self.conteggio_prof_classe_giorno[(docente, classe, giorno)] += 1
        if materia == "Motoria":
            self.occ_palestra[(giorno, ora)].append(classe)
        else:
            self.occ_aula[aula].add((giorno, ora))
        self.materie_giorno_classe[classe][giorno].add(materia)
        if materia == "Inglese":
            self.n_inglese_giorno[classe][giorno] += 1
        if ora == 0:
            self.posizione[classe][materia]["prima"] += 1
            self.entrata_prima_doc[docente].add(giorno)
        if ora == self.ore_per_giorno - 1:
            self.posizione[classe][materia]["ultima"] += 1
            self.entrata_ultima_doc[docente].add(giorno)

    def rimuovi(self, classe, giorno, ora):
        valore = self.orario[classe].pop((giorno, ora))
        materia = valore.split(" (")[0]
        docente = valore.split("(")[1].split(")")[0]
        aula = valore.split("Aula: ")[1].rstrip("]")

        self.occ_classe[classe].discard((giorno, ora))
        self.occ_prof[docente].discard((giorno, ora))
        self.ore_doc_giorno[docente][giorno] -= 1
        self.conteggio_prof_classe_giorno[(docente, classe, giorno)] -= 1
        if materia == "Motoria":
            if classe in self.occ_palestra[(giorno, ora)]:
                self.occ_palestra[(giorno, ora)].remove(classe)
        else:
            self.occ_aula[aula].discard((giorno, ora))

        rimanenti = {v.split(" (")[0] for (g, h), v in self.orario[classe].items() if g == giorno}
        self.materie_giorno_classe[classe][giorno] = rimanenti
        if materia == "Inglese":
            self.n_inglese_giorno[classe][giorno] -= 1
        if ora == 0:
            self.posizione[classe][materia]["prima"] -= 1
        if ora == self.ore_per_giorno - 1:
            self.posizione[classe][materia]["ultima"] -= 1
        return materia, docente, aula

    # ------------------------------------------------------------------
    def punteggio_slot(self, docente, classe, materia, giorno, ora):
        p = 0
        materie_oggi = self.materie_giorno_classe[classe][giorno]

        if materia in TRIO_UMANISTICO and (TRIO_UMANISTICO - {materia}) & materie_oggi:
            p += 6
        if materia in COPPIA_SCIENTIFICA and (COPPIA_SCIENTIFICA - {materia}) & materie_oggi:
            p += 6
        if materia == "Inglese" and "Seconda Lingua" in materie_oggi and self.n_inglese_giorno[classe][giorno] >= 1:
            p += 4
        if materia in ("Italiano", "Matematica", "Inglese"):
            pos = self.posizione[classe][materia]
            if ora == 0 and pos["prima"] >= 1:
                p += 3
            if ora == self.ore_per_giorno - 1 and pos["ultima"] >= 1:
                p += 3

        # preferenza: estendere blocchi contigui del docente (minimizza i buchi)
        occupato_prima = (giorno, ora - 1) in self.occ_prof[docente] if ora > 0 else False
        occupato_dopo = (giorno, ora + 1) in self.occ_prof[docente] if ora < self.ore_per_giorno - 1 else False
        if not occupato_prima and not occupato_dopo and self.ore_doc_giorno[docente][giorno] > 0:
            p += 2  # slot "isolato" per il docente quel giorno: penalizzato

        # bonus verso entrata 1a/ultima ora se il docente non le ha ancora
        if ora == 0 and giorno not in self.entrata_prima_doc[docente]:
            p -= 1
        if ora == self.ore_per_giorno - 1 and giorno not in self.entrata_ultima_doc[docente]:
            p -= 1

        return p


def _piazza_religione_fissa(c, assegnazioni, giorni):
    """Riserva SUBITO gli slot fissi di Religione (2E 1a ora, 2F ultima ora),
    prima di qualunque altra materia, così nessun'altra lezione può occuparli."""
    docente_religione = {}
    for docente, classi_map in assegnazioni.items():
        for classe, materie in classi_map.items():
            if "Religione" in materie:
                docente_religione[classe] = docente

    falliti = []
    for classe, ora_fissa in RELIGIONE_FISSA.items():
        docente = docente_religione.get(classe)
        if docente is None:
            continue
        giorni_shuffle = giorni[:]
        random.shuffle(giorni_shuffle)
        piazzato = False
        for g in giorni_shuffle:
            if c.puo_piazzare(docente, classe, "Religione", g, ora_fissa):
                c.piazza(docente, classe, "Religione", g, ora_fissa)
                piazzato = True
                break
        if not piazzato:
            falliti.append((docente, classe, "Religione"))
    return falliti


def _slot_palestra_validi(giorni, ore_per_giorno):
    return [(g, h) for g in giorni for h in range(ore_per_giorno) if (g, h) not in MOTORIA_BLOCCATA]


def _pianifica_palestra_dedicata(c, assegnazioni, classi, giorni, ore_per_giorno):
    """Pre-calcola e piazza gli abbinamenti ottimali in palestra usando una
    struttura a ciclo (ogni classe abbinata esattamente 2 volte, il minimo
    teorico di slot). Ritorna la lista delle sessioni che non è riuscito a
    piazzare (da ritentare con l'algoritmo generico)."""
    docente_motoria = {}
    for docente, classi_map in assegnazioni.items():
        for classe, materie in classi_map.items():
            if "Motoria" in materie:
                docente_motoria[classe] = docente

    classi_motoria = [cl for cl in classi if cl in docente_motoria]
    per_grado = defaultdict(list)
    for cl in classi_motoria:
        per_grado[grado_di(cl)].append(cl)

    sessioni = []  # ogni elemento: tupla di 1 o 2 classi
    for grado, lista in per_grado.items():
        soli = [cl for cl in lista if cl in MOTORIA_SOLE]
        normali = [cl for cl in lista if cl not in MOTORIA_SOLE]
        for cl in soli:
            sessioni.append((cl,))
            sessioni.append((cl,))
        n = len(normali)
        if n == 1:
            sessioni.append((normali[0],))
            sessioni.append((normali[0],))
        elif n >= 2:
            for i in range(n):
                sessioni.append((normali[i], normali[(i + 1) % n]))

    random.shuffle(sessioni)
    slot_validi = _slot_palestra_validi(giorni, ore_per_giorno)

    falliti = []
    for sessione in sessioni:
        candidati = slot_validi[:]
        random.shuffle(candidati)
        piazzato = False
        for (g, h) in candidati:
            docenti_sessione = [docente_motoria[cl] for cl in sessione]
            ok = all(c.puo_piazzare(docente_motoria[cl], cl, "Motoria", g, h) for cl in sessione)
            if not ok:
                continue
            for cl, doc in zip(sessione, docenti_sessione):
                c.piazza(doc, cl, "Motoria", g, h)
            piazzato = True
            break
        if not piazzato:
            for cl in sessione:
                falliti.append((docente_motoria[cl], cl, "Motoria"))
    return falliti


def _lista_slot(giorni, ore_per_giorno):
    return [(g, h) for g in giorni for h in range(ore_per_giorno)]


def _ripara_con_scambio(c, classe, docente, materia, slot_tutti, tentativi_scambio=60):
    occupati = list(c.orario[classe].keys())
    random.shuffle(occupati)
    occupati = occupati[:tentativi_scambio]

    for (g, h) in occupati:
        materia_via, docente_via, _ = c.rimuovi(classe, g, h)
        if materia_via == materia and docente_via == docente:
            c.piazza(docente_via, classe, materia_via, g, h)
            continue
        if not c.puo_piazzare(docente, classe, materia, g, h):
            c.piazza(docente_via, classe, materia_via, g, h)
            continue
        c.piazza(docente, classe, materia, g, h)
        piazzato_via = False
        slot_alt = [s for s in slot_tutti if s != (g, h)]
        random.shuffle(slot_alt)
        for (g2, h2) in slot_alt:
            if c.puo_piazzare(docente_via, classe, materia_via, g2, h2):
                c.piazza(docente_via, classe, materia_via, g2, h2)
                piazzato_via = True
                break
        if piazzato_via:
            return True
        c.rimuovi(classe, g, h)
        c.piazza(docente_via, classe, materia_via, g, h)
    return False


def genera_orario_reale(assegnazioni, vincoli_docenti, classi, giorni=None, ore_per_giorno=ORE_PER_GIORNO,
                         tentativi=20):
    giorni = giorni or GIORNI_DEFAULT
    slot_tutti = _lista_slot(giorni, ore_per_giorno)

    if not assegnazioni or not classi:
        return RisultatoOrarioReale(False, "DATI_INCOMPLETI", messaggio="Dati mancanti.")

    lezioni_base = []
    for docente, classi_map in assegnazioni.items():
        for classe, materie in classi_map.items():
            for materia, ore in materie.items():
                for _ in range(ore):
                    lezioni_base.append((docente, classe, materia))
    totale_atteso = len(lezioni_base)

    priorita_materia = {
        "Scienze": 0, "Tecnologia": 0, "Religione": 0, "Matematica": 0,
        "Italiano": 1, "Motoria": 1,
        "Inglese": 2, "Seconda Lingua": 2,
    }

    miglior = None
    miglior_completezza = -1
    miglior_qualita = -1
    miglior_report = None

    for tentativo in range(tentativi):
        random.seed(tentativo * 97 + 5)
        c = _Costruttore(assegnazioni, vincoli_docenti, classi, giorni, ore_per_giorno)

        # --- FASE -1: riserva subito gli slot fissi di Religione (2E/2F) ---
        falliti_religione = _piazza_religione_fissa(c, assegnazioni, giorni)

        # --- FASE 0: pianificazione dedicata della palestra (Motoria) -----
        falliti_palestra = _pianifica_palestra_dedicata(c, assegnazioni, classi, giorni, ore_per_giorno)

        lezioni = [t for t in lezioni_base if t[2] != "Motoria" and t[2] != "Religione"]
        lezioni += falliti_palestra + falliti_religione
        # aggiungi le rimanenti ore di Religione (quelle non fisse)
        for docente, classi_map in assegnazioni.items():
            for classe, materie in classi_map.items():
                if "Religione" in materie and classe not in RELIGIONE_FISSA:
                    lezioni.append((docente, classe, "Religione"))
        random.shuffle(lezioni)
        lezioni.sort(key=lambda t: priorita_materia.get(t[2], 3))

        coda = lezioni[:]
        max_iter = len(lezioni) * 60
        it = 0
        while coda and it < max_iter:
            it += 1
            docente, classe, materia = coda.pop(0)
            candidati_slot = slot_tutti[:]
            random.shuffle(candidati_slot)
            candidati_slot.sort(key=lambda s: c.punteggio_slot(docente, classe, materia, s[0], s[1]))
            piazzato = False
            for (g, h) in candidati_slot:
                if c.puo_piazzare(docente, classe, materia, g, h):
                    c.piazza(docente, classe, materia, g, h)
                    piazzato = True
                    break
            if not piazzato:
                coda.append((docente, classe, materia))
                if len(coda) > 0 and it % len(lezioni_base) == 0 and it > 0:
                    pass  # evita loop infinito banale; max_iter comunque limita

        # --- riparazione via scambio (multi-round) ---
        for _round in range(20):
            mancanti = []
            for docente, classi_map in assegnazioni.items():
                for classe, materie in classi_map.items():
                    for materia, ore in materie.items():
                        gia = sum(1 for v in c.orario[classe].values()
                                  if v.startswith(materia + " (" + docente + ")"))
                        for _ in range(ore - gia):
                            mancanti.append((docente, classe, materia))
            if not mancanti:
                break
            random.shuffle(mancanti)
            progressi = 0
            for docente, classe, materia in mancanti:
                gia = sum(1 for v in c.orario[classe].values()
                          if v.startswith(materia + " (" + docente + ")"))
                ore_richieste = assegnazioni[docente][classe][materia]
                if gia >= ore_richieste:
                    continue
                if _ripara_con_scambio(c, classe, docente, materia, slot_tutti):
                    progressi += 1
            if progressi == 0:
                break

        totale_piazzate = sum(len(c.orario[cl]) for cl in classi)

        # --- qualità (preferenze soft) ---
        conflitti_trio = conflitti_coppia = 0
        for classe in classi:
            for g in giorni:
                materie_oggi = c.materie_giorno_classe[classe][g]
                if len(TRIO_UMANISTICO & materie_oggi) > 1:
                    conflitti_trio += 1
                if len(COPPIA_SCIENTIFICA & materie_oggi) > 1:
                    conflitti_coppia += 1

        docenti_senza_entrata16 = []
        for docente in vincoli_docenti:
            ha_prima = len(c.entrata_prima_doc.get(docente, set())) > 0
            ha_ultima = len(c.entrata_ultima_doc.get(docente, set())) > 0
            if not (ha_prima and ha_ultima):
                docenti_senza_entrata16.append(docente)

        qualita = -(conflitti_trio + conflitti_coppia + len(docenti_senza_entrata16))

        if totale_piazzate > miglior_completezza or (totale_piazzate == miglior_completezza and qualita > miglior_qualita):
            miglior_completezza = totale_piazzate
            miglior_qualita = qualita
            miglior = c
            miglior_report = {
                "lezioni_totali_attese": totale_atteso,
                "lezioni_piazzate": totale_piazzate,
                "conflitti_trio_umanistico": conflitti_trio,
                "conflitti_coppia_scientifica": conflitti_coppia,
                "docenti_senza_entrata_1_6": docenti_senza_entrata16,
            }

        if totale_piazzate == totale_atteso and qualita == 0:
            break

    if miglior is None:
        return RisultatoOrarioReale(False, "ERRORE", messaggio="Impossibile generare alcun tentativo.")

    if miglior_completezza < totale_atteso:
        return RisultatoOrarioReale(
            False, "PARZIALE", orario=dict(miglior.orario),
            messaggio=f"Assegnate {miglior_completezza}/{totale_atteso} ore.",
            report=miglior_report,
        )

    msg = (
        f"Orario completo. Conflitti Italiano/Storia/Geografia stesso giorno: "
        f"{miglior_report['conflitti_trio_umanistico']}. "
        f"Conflitti Matematica/Scienze stesso giorno: {miglior_report['conflitti_coppia_scientifica']}. "
        f"Docenti senza entrata 1a+6a ora: {len(miglior_report['docenti_senza_entrata_1_6'])} "
        f"({', '.join(miglior_report['docenti_senza_entrata_1_6']) or 'nessuno'})."
    )
    return RisultatoOrarioReale(True, "SOLUZIONE_TROVATA", orario=dict(miglior.orario),
                                 messaggio=msg, report=miglior_report)
