"""
Scheduler dedicato per lo scenario "scuola secondaria di primo grado" con
le regole specifiche richieste (aule speciali, palestra condivisa, religione
fissa per alcune classi, ecc.).

IMPORTANTE - conflitto matematico individuato:
Con 5 giorni disponibili, le seguenti regole non possono essere TUTTE rispettate
sempre allo stesso tempo per Italiano (8 ore/settimana):
  - "un docente non vede la stessa classe più di una volta al giorno"
  - "Italiano, Storia, Geografia mai lo stesso giorno"
Motivo: 8 ore di Italiano richiedono almeno 4 giorni diversi (se max 2/giorno);
restano al più 1 giorno libero per ospitare SIA Storia (2h, serve un giorno
suo) SIA Geografia (2h, altro giorno suo) senza mai toccare un giorno di
Italiano: servirebbero almeno 4+1+1=6 giorni, ma ce ne sono 5.
Stessa cosa in scala minore per Matematica/Scienze.

Per questo motivo queste regole sono trattate come PREFERENZE FORTI (il
motore le rispetta il più possibile, e alla fine riporta quante ne ha
rispettate), mentre tutto il resto (aule, sovrapposizioni, palestra,
religione fissa, blocchi orari) sono VINCOLI RIGIDI, sempre rispettati.
"""
import random
import logging
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

GIORNI_DEFAULT = ["Lun", "Mar", "Mer", "Gio", "Ven"]
ORE_PER_GIORNO = 6

# --- Regole fisse della scuola -----------------------------------------

# Motoria vietata: Martedì 3a/4a ora e Giovedì 3a/4a ora (indici 0-based: 2,3)
MOTORIA_BLOCCATA = {("Mar", 2), ("Mar", 3), ("Gio", 2), ("Gio", 3)}

# Aule speciali condivise per materia+anno (sovrascrivono l'aula personale del docente)
def aula_speciale(materia, grado):
    if materia == "Scienze":
        return "Lab_Scienze_Aula37" if grado in (1, 2) else "Aula_38"
    if materia == "Tecnologia":
        return "Lab_Tecnologia_Aula27" if grado in (2, 3) else "Aula_28"
    if materia == "Motoria":
        return "Palestra"
    return None

# Classi che in palestra devono stare SEMPRE da sole (mai in coppia)
MOTORIA_SOLE = {"2B", "2F"}

# Religione a posizione fissa (0 = prima ora, ORE_PER_GIORNO-1 = ultima ora)
RELIGIONE_FISSA = {"2E": 0, "2F": ORE_PER_GIORNO - 1}
# Religione preferita (soft) alla prima o ultima ora
RELIGIONE_PREFERITA = {"1D", "1E", "1F"}

TRIO_UMANISTICO = {"Italiano", "Storia", "Geografia"}
COPPIA_SCIENTIFICA = {"Matematica", "Scienze"}


def grado_di(classe):
    return int(classe[0])


class RisultatoOrarioScuola:
    def __init__(self, ok, stato, orario=None, messaggio="", report=None):
        self.ok = ok
        self.stato = stato
        self.orario = orario or {}
        self.messaggio = messaggio
        self.report = report or {}


class _Costruttore:
    """Incapsula lo stato di un singolo tentativo di costruzione dell'orario."""

    def __init__(self, professori, classi, materie, giorni, ore_per_giorno):
        self.professori = professori
        self.classi = classi
        self.materie = materie
        self.giorni = giorni
        self.ore_per_giorno = ore_per_giorno

        self.orario = defaultdict(dict)                      # classe -> {(g,h): stringa}
        self.occ_classe = defaultdict(set)                    # classe -> {(g,h)}
        self.occ_prof = defaultdict(set)                       # prof -> {(g,h)}
        self.occ_aula = defaultdict(set)                       # aula -> {(g,h)}  (non palestra)
        self.occ_palestra = defaultdict(list)                  # (g,h) -> [classi]
        self.ore_usate_prof = defaultdict(int)
        self.conteggio_prof_classe_giorno = defaultdict(int)   # (prof,classe,giorno) -> n
        self.materie_giorno_classe = defaultdict(lambda: defaultdict(set))  # classe->giorno->set(materie)
        self.posizione = defaultdict(lambda: defaultdict(lambda: {"prima": 0, "ultima": 0}))
        self.titolare = {}                                      # (classe,materia) -> prof
        self.n_inglese_giorno = defaultdict(lambda: defaultdict(int))  # classe->giorno->n

        # punteggio preferenze (più alto = meglio)
        self.preferenze_rispettate = 0
        self.preferenze_totali = 0

    # ------------------------------------------------------------------
    def aula_per(self, materia, classe, prof):
        speciale = aula_speciale(materia, grado_di(classe))
        if speciale:
            return speciale
        return self.professori[prof].get("aula", f"Aula_{prof}")

    def prof_qualificati(self, materia):
        return [p for p, info in self.professori.items() if materia in info["materie"]]

    def limite_giornaliero(self, materia):
        # eccezione necessaria: Italiano (8h/settimana) non può stare in max 1/giorno
        # su soli 5 giorni disponibili (servirebbero 8 giorni)
        return 2 if materia == "Italiano" else 1

    def puo_piazzare(self, materia, classe, prof, giorno, ora):
        if materia == "Motoria" and (giorno, ora) in MOTORIA_BLOCCATA:
            return False
        if (giorno, ora) in self.occ_classe[classe]:
            return False
        if (giorno, ora) in self.occ_prof[prof]:
            return False
        if self.ore_usate_prof[prof] >= self.professori[prof]["max_ore"]:
            return False

        tit = self.titolare.get((classe, materia))
        if tit is not None and tit != prof:
            return False

        if self.conteggio_prof_classe_giorno[(prof, classe, giorno)] >= self.limite_giornaliero(materia):
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
            aula = self.aula_per(materia, classe, prof)
            if (giorno, ora) in self.occ_aula[aula]:
                return False

        return True

    def piazza(self, materia, classe, prof, giorno, ora):
        aula = self.aula_per(materia, classe, prof)
        self.orario[classe][(giorno, ora)] = f"{materia} ({prof}) [Aula: {aula}]"
        self.occ_classe[classe].add((giorno, ora))
        self.occ_prof[prof].add((giorno, ora))
        self.ore_usate_prof[prof] += 1
        self.conteggio_prof_classe_giorno[(prof, classe, giorno)] += 1
        if materia == "Motoria":
            self.occ_palestra[(giorno, ora)].append(classe)
        else:
            self.occ_aula[aula].add((giorno, ora))
        self.titolare[(classe, materia)] = prof
        self.materie_giorno_classe[classe][giorno].add(materia)
        if materia == "Inglese":
            self.n_inglese_giorno[classe][giorno] += 1
        if ora == 0:
            self.posizione[classe][materia]["prima"] += 1
        if ora == self.ore_per_giorno - 1:
            self.posizione[classe][materia]["ultima"] += 1
        return aula

    def rimuovi(self, classe, giorno, ora):
        """Disfa un piazzamento precedente. Ritorna (materia, prof, aula)."""
        valore = self.orario[classe].pop((giorno, ora))
        materia = valore.split(" (")[0]
        prof = valore.split("(")[1].split(")")[0]
        aula = valore.split("Aula: ")[1].rstrip("]")

        self.occ_classe[classe].discard((giorno, ora))
        self.occ_prof[prof].discard((giorno, ora))
        self.ore_usate_prof[prof] -= 1
        self.conteggio_prof_classe_giorno[(prof, classe, giorno)] -= 1
        if materia == "Motoria":
            if classe in self.occ_palestra[(giorno, ora)]:
                self.occ_palestra[(giorno, ora)].remove(classe)
        else:
            self.occ_aula[aula].discard((giorno, ora))

        # ricalcola materie presenti quel giorno per la classe
        rimanenti = {v.split(" (")[0] for (g, h), v in self.orario[classe].items() if g == giorno}
        self.materie_giorno_classe[classe][giorno] = rimanenti

        if materia == "Inglese":
            self.n_inglese_giorno[classe][giorno] -= 1
        if ora == 0:
            self.posizione[classe][materia]["prima"] -= 1
        if ora == self.ore_per_giorno - 1:
            self.posizione[classe][materia]["ultima"] -= 1

        return materia, prof, aula

    # ------------------------------------------------------------------
    def punteggio_slot(self, materia, classe, giorno, ora):
        """Più alto = slot peggiore (da evitare). Usato per ORDINARE i candidati."""
        p = 0
        materie_oggi = self.materie_giorno_classe[classe][giorno]

        if materia in TRIO_UMANISTICO and (TRIO_UMANISTICO - {materia}) & materie_oggi:
            p += 6
        if materia in COPPIA_SCIENTIFICA and (COPPIA_SCIENTIFICA - {materia}) & materie_oggi:
            p += 6
        if materia == "Inglese" and "Seconda Lingua" in materie_oggi and self.n_inglese_giorno[classe][giorno] >= 1:
            p += 4
        if materia == "Seconda Lingua" and self.n_inglese_giorno[classe][giorno] >= 2:
            p += 4
        if materia in ("Italiano", "Matematica", "Inglese"):
            pos = self.posizione[classe][materia]
            if ora == 0 and pos["prima"] >= 1:
                p += 3
            if ora == self.ore_per_giorno - 1 and pos["ultima"] >= 1:
                p += 3
        # leggero disincentivo generale a raddoppiare lo stesso giorno (oltre al limite rigido)
        if self.conteggio_prof_classe_giorno.get((None, classe, giorno), 0):
            pass
        return p


def _lista_slot(giorni, ore_per_giorno):
    return [(g, h) for g in giorni for h in range(ore_per_giorno)]


def _ripara_con_scambio(c, classe, materia, slot_tutti, tentativi_scambio=60):
    """Se non c'è uno slot libero diretto, prova a liberarne uno spostando
    altrove la lezione che lo occupa (scambio a 1 livello, tipo min-conflicts)."""
    prof_titolare = c.titolare.get((classe, materia))
    candidati_prof = [prof_titolare] if prof_titolare else c.prof_qualificati(materia)
    candidati_prof = [p for p in candidati_prof if p]
    if not candidati_prof:
        return False
    random.shuffle(candidati_prof)

    occupati = list(c.orario[classe].keys())
    random.shuffle(occupati)
    occupati = occupati[:tentativi_scambio]

    for prof in candidati_prof:
        for (g, h) in occupati:
            materia_via, prof_via, _ = c.rimuovi(classe, g, h)
            if materia_via == materia:
                c.piazza(materia_via, classe, prof_via, g, h)
                continue
            if not c.puo_piazzare(materia, classe, prof, g, h):
                c.piazza(materia_via, classe, prof_via, g, h)
                continue
            c.piazza(materia, classe, prof, g, h)
            # ora ricolloca altrove la lezione appena tolta
            piazzato_via = False
            slot_alt = [s for s in slot_tutti if s != (g, h)]
            random.shuffle(slot_alt)
            for (g2, h2) in slot_alt:
                if c.puo_piazzare(materia_via, classe, prof_via, g2, h2):
                    c.piazza(materia_via, classe, prof_via, g2, h2)
                    piazzato_via = True
                    break
            if piazzato_via:
                return True
            # rollback completo
            c.rimuovi(classe, g, h)
            c.piazza(materia_via, classe, prof_via, g, h)
    return False


def genera_orario_scuola(professori, classi, materie, giorni=None, ore_per_giorno=ORE_PER_GIORNO,
                          tentativi=40):
    giorni = giorni or GIORNI_DEFAULT
    slot_tutti = _lista_slot(giorni, ore_per_giorno)

    if not professori or not classi or not materie:
        return RisultatoOrarioScuola(False, "DATI_INCOMPLETI", messaggio="Dati mancanti.")
    if "Religione" not in materie or "Inglese" not in materie:
        return RisultatoOrarioScuola(
            False, "DATI_INCOMPLETI",
            messaggio="Le materie 'Religione' e 'Inglese' sono richieste da queste regole."
        )

    materie_normali = {m: o for m, o in materie.items() if m != "Religione"}

    miglior = None
    miglior_completezza = -1
    miglior_qualita = -1
    miglior_report = None

    for tentativo in range(tentativi):
        random.seed(tentativo * 101 + 13)
        c = _Costruttore(professori, classi, materie, giorni, ore_per_giorno)
        religione_non_accoppiata = []
        fallite = []

        # --- FASE 1: pre-riserva Inglese+Religione per 2E e 2F -----------
        ok_fase1 = True
        for classe, ora_religione in RELIGIONE_FISSA.items():
            if classe not in classi:
                continue
            ora_inglese = ora_religione + 1 if ora_religione == 0 else ora_religione - 1
            prof_ing = c.prof_qualificati("Inglese")
            prof_rel = c.prof_qualificati("Religione")
            random.shuffle(prof_ing)
            random.shuffle(prof_rel)
            piazzato = False
            giorni_shuffle = giorni[:]
            random.shuffle(giorni_shuffle)
            for g in giorni_shuffle:
                for p_ing in prof_ing:
                    if not c.puo_piazzare("Inglese", classe, p_ing, g, ora_inglese):
                        continue
                    for p_rel in prof_rel:
                        if not c.puo_piazzare("Religione", classe, p_rel, g, ora_religione):
                            continue
                        c.piazza("Inglese", classe, p_ing, g, ora_inglese)
                        c.piazza("Religione", classe, p_rel, g, ora_religione)
                        piazzato = True
                        break
                    if piazzato:
                        break
                if piazzato:
                    break
            if not piazzato:
                ok_fase1 = False
                fallite.append(f"Religione fissa {classe}")

        # --- FASE 2: tutte le altre lezioni (tranne Religione rimanente) -
        # Priorità: le materie più vincolate (più ore, aule condivise, limiti
        # orari) vengono piazzate per prime, quando c'è più libertà di scelta.
        priorita_materia = {
            "Scienze": 0, "Tecnologia": 0, "Italiano": 0, "Motoria": 0,   # più vincolate: per prime
            "Matematica": 1,
            "Inglese": 2, "Seconda Lingua": 2,
        }

        lezioni = []
        for classe in classi:
            for materia, ore in materie_normali.items():
                gia_piazzate = sum(
                    1 for v in c.orario[classe].values() if v.startswith(materia + " (")
                )
                for _ in range(ore - gia_piazzate):
                    lezioni.append((classe, materia))
        random.shuffle(lezioni)
        lezioni.sort(key=lambda cm: priorita_materia.get(cm[1], 3))

        max_iter = len(lezioni) * 60
        coda = lezioni[:]
        it = 0
        assegnate = 0
        while coda and it < max_iter:
            it += 1
            classe, materia = coda.pop(0)
            prof_gia_titolare = c.titolare.get((classe, materia))
            candidati_prof = [prof_gia_titolare] if prof_gia_titolare else c.prof_qualificati(materia)
            if not candidati_prof:
                continue
            random.shuffle(candidati_prof)

            piazzato = False
            for prof in candidati_prof:
                candidati_slot = slot_tutti[:]
                random.shuffle(candidati_slot)
                candidati_slot.sort(key=lambda s: c.punteggio_slot(materia, classe, s[0], s[1]))
                for (g, h) in candidati_slot:
                    if not c.puo_piazzare(materia, classe, prof, g, h):
                        continue
                    c.piazza(materia, classe, prof, g, h)
                    assegnate += 1
                    piazzato = True
                    break
                if piazzato:
                    break
            if not piazzato:
                coda.append((classe, materia))

        # --- FASE 2b: riparazione via scambio (multi-round) ---------------
        for round_riparazione in range(12):
            mancanti_ora = []
            for classe in classi:
                for materia, ore in materie_normali.items():
                    gia = sum(1 for v in c.orario[classe].values() if v.startswith(materia + " ("))
                    for _ in range(ore - gia):
                        mancanti_ora.append((classe, materia))
            if not mancanti_ora:
                break
            random.shuffle(mancanti_ora)
            progressi = 0
            for classe, materia in mancanti_ora:
                gia = sum(1 for v in c.orario[classe].values() if v.startswith(materia + " ("))
                if gia >= materie_normali.get(materia, 0):
                    continue
                if _ripara_con_scambio(c, classe, materia, slot_tutti):
                    progressi += 1
            if progressi == 0:
                break

        # --- FASE 3: Religione per le classi rimanenti (accoppiata a Inglese)
        for classe in classi:
            if classe in RELIGIONE_FISSA:
                continue
            slot_inglese = [
                (g, h) for (g, h), v in c.orario[classe].items() if v.startswith("Inglese (")
            ]
            random.shuffle(slot_inglese)
            if classe in RELIGIONE_PREFERITA:
                slot_inglese.sort(key=lambda s: 0 if s[1] in (0, ore_per_giorno - 1 - 1, ore_per_giorno - 1) else 1)

            prof_rel = c.prof_qualificati("Religione")
            piazzato = False
            for (g, h) in slot_inglese:
                for h_adiacente in (h - 1, h + 1):
                    if h_adiacente < 0 or h_adiacente >= ore_per_giorno:
                        continue
                    random.shuffle(prof_rel)
                    for p in prof_rel:
                        if c.puo_piazzare("Religione", classe, p, g, h_adiacente):
                            c.piazza("Religione", classe, p, g, h_adiacente)
                            piazzato = True
                            break
                    if piazzato:
                        break
                if piazzato:
                    break

            if not piazzato:
                # fallback: religione da sola, non accoppiata (viene segnalato nel report)
                candidati_slot = slot_tutti[:]
                random.shuffle(candidati_slot)
                random.shuffle(prof_rel)
                for (g, h) in candidati_slot:
                    for p in prof_rel:
                        if c.puo_piazzare("Religione", classe, p, g, h):
                            c.piazza("Religione", classe, p, g, h)
                            piazzato = True
                            religione_non_accoppiata.append(classe)
                            break
                    if piazzato:
                        break

            if not piazzato:
                fallite.append(f"Religione {classe}")

        totale_lezioni_attese = sum(materie.values()) * len(classi)
        totale_piazzate = sum(len(c.orario[cl]) for cl in classi)
        completezza = totale_piazzate

        # --- calcolo qualità (preferenze soft rispettate) ---------------
        conflitti_trio = 0
        conflitti_coppia = 0
        for classe in classi:
            for g in giorni:
                materie_oggi = c.materie_giorno_classe[classe][g]
                if len(TRIO_UMANISTICO & materie_oggi) > 1:
                    conflitti_trio += 1
                if len(COPPIA_SCIENTIFICA & materie_oggi) > 1:
                    conflitti_coppia += 1
        qualita = -(conflitti_trio + conflitti_coppia + len(religione_non_accoppiata) * 3)

        if completezza > miglior_completezza or (completezza == miglior_completezza and qualita > miglior_qualita):
            miglior_completezza = completezza
            miglior_qualita = qualita
            miglior = c
            miglior_report = {
                "conflitti_trio_umanistico": conflitti_trio,
                "conflitti_coppia_scientifica": conflitti_coppia,
                "religione_non_accoppiata": religione_non_accoppiata,
                "lezioni_totali_attese": totale_lezioni_attese,
                "lezioni_piazzate": totale_piazzate,
                "fallite": fallite,
            }

        if completezza == totale_lezioni_attese and qualita == 0:
            break

    if miglior is None:
        return RisultatoOrarioScuola(False, "ERRORE", messaggio="Impossibile generare alcun tentativo.")

    totale_atteso = miglior_report["lezioni_totali_attese"]
    if miglior_completezza < totale_atteso:
        return RisultatoOrarioScuola(
            False, "PARZIALE",
            orario=dict(miglior.orario),
            messaggio=f"Assegnate {miglior_completezza}/{totale_atteso} lezioni. "
                      f"Mancanti: {miglior_report['fallite']}",
            report=miglior_report,
        )

    msg = (
        f"Orario completo. Conflitti Italiano/Storia/Geografia stesso giorno: "
        f"{miglior_report['conflitti_trio_umanistico']}. "
        f"Conflitti Matematica/Scienze stesso giorno: {miglior_report['conflitti_coppia_scientifica']}. "
        f"Religione non accoppiata a Inglese: {len(miglior_report['religione_non_accoppiata'])} "
        f"({', '.join(miglior_report['religione_non_accoppiata']) or 'nessuna'})."
    )
    return RisultatoOrarioScuola(True, "SOLUZIONE_TROVATA", orario=dict(miglior.orario),
                                  messaggio=msg, report=miglior_report)
