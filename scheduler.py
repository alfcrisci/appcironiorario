"""Generazione dell'orario scolastico - Versione ibrida con vincoli DADA."""
from collections import defaultdict
import random
import logging
import copy
import time

# Prova a importare OR-Tools, ma se fallisce, usa solo Greedy
try:
    from ortools.sat.python import cp_model
    ORTOOLS_DISPONIBILE = True
except ImportError:
    ORTOOLS_DISPONIBILE = False
    cp_model = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

GIORNI_DEFAULT = ["Lun", "Mar", "Mer", "Gio", "Ven"]


class RisultatoOrario:
    def __init__(self, ok, stato, orario=None, messaggio=""):
        self.ok = ok
        self.stato = stato
        self.orario = orario or {}
        self.messaggio = messaggio


def genera_orario_greedy(professori, classi, materie, giorni=None, ore_per_giorno=5, tentativi=10,
                          aule_preferenze=None):
    """
    Genera l'orario usando un algoritmo greedy con vincoli DADA.
    I professori hanno aule fisse, le classi si spostano.

    Preferenze soft (non vincoli rigidi):
      - professori[nome]["giorno_preferito"]: giorno in cui il prof preferisce
        avere lezione, se possibile.
      - aule_preferenze[aula]: giorno in cui si preferisce usare quell'aula.
    """
    logger.info("=== GENERAZIONE ORARIO (GREEDY + DADA) ===")
    
    giorni = giorni or GIORNI_DEFAULT
    ore_per_giorno = min(ore_per_giorno, 8)
    aule_preferenze = aule_preferenze or {}
    
    # Verifica dati
    if not professori or not classi or not materie:
        return RisultatoOrario(False, "DATI_INCOMPLETI", messaggio="Dati mancanti.")

    # Assegna un'aula a ogni professore (se non specificata, usa il nome del prof)
    for prof, info in professori.items():
        if "aula" not in info:
            info["aula"] = f"Aula_{prof}"  # Aula predefinita

    # Calcolo ore totali
    ore_totali_richieste = sum(materie.values()) * len(classi)
    ore_totali_disponibili = sum(info["max_ore"] for info in professori.values())
    
    logger.info(f"Ore richieste: {ore_totali_richieste}, Ore disponibili: {ore_totali_disponibili}")
    
    if ore_totali_richieste > ore_totali_disponibili:
        return RisultatoOrario(
            False, "ORE_INSUFFICIENTI",
            messaggio=f"Ore richieste ({ore_totali_richieste}) > Ore disponibili ({ore_totali_disponibili})"
        )

    # Prepara struttura dati
    prof_per_materia = {}
    for materia in materie:
        prof_per_materia[materia] = []
        for prof, info in professori.items():
            if materia in info["materie"]:
                prof_per_materia[materia].append(prof)

    # Verifica che ogni materia abbia almeno un professore
    for materia in materie:
        if not prof_per_materia[materia]:
            return RisultatoOrario(
                False, "MATERIA_SENZA_PROFESSORE",
                messaggio=f"Nessun professore per la materia: {materia}"
            )

    slot_disponibili = [(g, h) for g in giorni for h in range(ore_per_giorno)]
    
    # Prova più tentativi
    miglior_orario = None
    miglior_assegnate = -1
    miglior_punteggio_pref = -1
    # limite teorico (ottimistico) usato solo per uscire prima se già ottimo
    numero_lezioni_totali = sum(materie.values()) * len(classi)
    miglior_punteggio_pref_teorico = numero_lezioni_totali * 2
    
    for tentativo in range(tentativi):
        logger.info(f"Tentativo {tentativo+1}/{tentativi}")
        random.seed(tentativo * 42 + 7)
        
        # Inizializza strutture
        orario = defaultdict(dict)
        ore_usate_prof = defaultdict(int)
        slot_occupati_classe = defaultdict(set)  # {classe: set((giorno, ora))}
        slot_occupati_prof = defaultdict(set)    # {professore: set((giorno, ora))}
        aula_occupata = defaultdict(set)         # {aula: set((giorno, ora))} - VINCOLO DADA
        punteggio_preferenze = 0                 # quante lezioni sono cadute nel giorno preferito
        
        # Crea lista lezioni
        lezioni = []
        for c in classi:
            for materia, ore in materie.items():
                for _ in range(ore):
                    lezioni.append((c, materia))
        
        random.shuffle(lezioni)
        
        lezioni_assegnate = 0
        lezioni_da_assegnare = lezioni[:]
        max_tentativi = len(lezioni) * 10
        contatore = 0
        
        while lezioni_da_assegnare and contatore < max_tentativi:
            contatore += 1
            classe, materia = lezioni_da_assegnare.pop(0)
            
            prof_disponibili = prof_per_materia[materia][:]
            random.shuffle(prof_disponibili)
            
            assegnato = False
            
            for prof in prof_disponibili:
                # Controlla se il professore ha ore disponibili
                if ore_usate_prof[prof] >= professori[prof]["max_ore"]:
                    continue
                
                aula_prof = professori[prof]["aula"]
                
                # Cerca uno slot libero: prova prima i giorni preferiti
                # (preferenza soft — se non sono disponibili si passa agli altri)
                slot_random = slot_disponibili[:]
                random.shuffle(slot_random)

                giorno_pref_prof = professori[prof].get("giorno_preferito")
                giorno_pref_aula = aule_preferenze.get(aula_prof)

                def _punteggio_slot(s, gp_prof=giorno_pref_prof, gp_aula=giorno_pref_aula):
                    g_slot, _ = s
                    p = 0
                    if gp_prof and g_slot == gp_prof:
                        p += 1
                    if gp_aula and g_slot == gp_aula:
                        p += 1
                    return -p  # più preferenze soddisfatte -> viene provato prima

                if giorno_pref_prof or giorno_pref_aula:
                    slot_random.sort(key=_punteggio_slot)
                
                for giorno, ora in slot_random:
                    # Vincolo 1: La classe non deve avere già una lezione in questo slot
                    if (giorno, ora) in slot_occupati_classe[classe]:
                        continue
                    
                    # Vincolo 2: Il professore non deve avere già una lezione in questo slot
                    if (giorno, ora) in slot_occupati_prof[prof]:
                        continue
                    
                    # Vincolo 3: L'aula del professore non deve essere occupata da un'altra classe (DADA)
                    if (giorno, ora) in aula_occupata[aula_prof]:
                        continue
                    
                    # Vincolo 4: una classe non può avere più di 2 ore CONSECUTIVE
                    # della STESSA materia (non blocca giornate piene con materie diverse)
                    ore_consecutive_stessa_materia = 0
                    for h_prec in range(ora - 1, -1, -1):
                        valore_prec = orario[classe].get((giorno, h_prec))
                        if valore_prec is None:
                            break
                        materia_prec = valore_prec.split(" (")[0]
                        if materia_prec == materia:
                            ore_consecutive_stessa_materia += 1
                        else:
                            break

                    if ore_consecutive_stessa_materia >= 2:
                        continue
                    
                    # Assegna la lezione
                    orario[classe][(giorno, ora)] = f"{materia} ({prof}) [Aula: {aula_prof}]"
                    slot_occupati_classe[classe].add((giorno, ora))
                    slot_occupati_prof[prof].add((giorno, ora))
                    aula_occupata[aula_prof].add((giorno, ora))  # VINCOLO DADA
                    ore_usate_prof[prof] += 1
                    lezioni_assegnate += 1
                    if giorno_pref_prof and giorno == giorno_pref_prof:
                        punteggio_preferenze += 1
                    if giorno_pref_aula and giorno == giorno_pref_aula:
                        punteggio_preferenze += 1
                    assegnato = True
                    break
                
                if assegnato:
                    break
            
            if not assegnato:
                lezioni_da_assegnare.append((classe, materia))
        
        logger.info(f"  Lezioni assegnate: {lezioni_assegnate}/{len(lezioni)} - "
                    f"Preferenze soddisfatte: {punteggio_preferenze}")

        migliora = (
            lezioni_assegnate > miglior_assegnate or
            (lezioni_assegnate == miglior_assegnate and punteggio_preferenze > miglior_punteggio_pref)
        )
        if migliora:
            miglior_assegnate = lezioni_assegnate
            miglior_punteggio_pref = punteggio_preferenze
            miglior_orario = orario
        
        if lezioni_assegnate == len(lezioni) and punteggio_preferenze == miglior_punteggio_pref_teorico:
            logger.info("✅ Soluzione completa e con preferenze massime trovata!")
            break
    
    if miglior_orario is None or miglior_assegnate < len(lezioni):
        return RisultatoOrario(
            False,
            "PARZIALE",
            messaggio=f"Assegnate {miglior_assegnate} su {len(lezioni)} lezioni.\n"
                      f"Riduci il monte ore o aggiungi più professori/aule."
        )
    
    logger.info(f"Orario generato con successo! Preferenze soddisfatte: {miglior_punteggio_pref}")
    return RisultatoOrario(
        True, "SOLUZIONE_TROVATA", orario=dict(miglior_orario),
        messaggio=f"Preferenze soddisfatte: {miglior_punteggio_pref}"
    )


def genera_orario_ortools(professori, classi, materie, giorni=None, ore_per_giorno=5, tempo_max_sec=30,
                           aule_preferenze=None):
    """
    Genera l'orario usando OR-Tools CP-SAT con vincoli DADA.

    Preferenze soft (non vincoli rigidi, ottimizzate se possibile):
      - professori[nome]["giorno_preferito"]
      - aule_preferenze[aula]
    """
    if not ORTOOLS_DISPONIBILE:
        return RisultatoOrario(
            False, "ORTOOLS_NON_DISPONIBILE",
            messaggio="OR-Tools non è installato. Usa la modalità Greedy."
        )
    
    logger.info("=== GENERAZIONE ORARIO (OR-TOOLS + DADA) ===")
    logger.info(f"Tempo massimo: {tempo_max_sec}s")
    aule_preferenze = aule_preferenze or {}
    
    try:
        giorni = giorni or GIORNI_DEFAULT
        slot = [(g, h) for g in giorni for h in range(ore_per_giorno)]

        # Verifica dati
        if not professori or not classi or not materie:
            return RisultatoOrario(False, "DATI_INCOMPLETI", messaggio="Dati mancanti.")

        # Assegna un'aula a ogni professore
        for prof, info in professori.items():
            if "aula" not in info:
                info["aula"] = f"Aula_{prof}"

        # Calcolo ore totali
        ore_totali_richieste = sum(materie.values()) * len(classi)
        ore_totali_disponibili = sum(info["max_ore"] for info in professori.values())
        
        if ore_totali_richieste > ore_totali_disponibili:
            return RisultatoOrario(
                False, "ORE_INSUFFICIENTI",
                messaggio=f"Ore richieste ({ore_totali_richieste}) > Ore disponibili ({ore_totali_disponibili})"
            )

        model = cp_model.CpModel()

        # Creazione variabili
        teach = {}
        for p, info in professori.items():
            for s in info["materie"]:
                if s not in materie:
                    continue
                for c in classi:
                    for (g, h) in slot:
                        teach[(p, c, s, g, h)] = model.NewBoolVar(f"t_{p}_{c}_{s}_{g}_{h}")

        logger.info(f"Variabili teach create: {len(teach)}")

        # Variabili assigned
        assigned = {}
        for p, info in professori.items():
            for s in info["materie"]:
                if s not in materie:
                    continue
                for c in classi:
                    assigned[(p, c, s)] = model.NewBoolVar(f"a_{p}_{c}_{s}")

        # VINCOLI
        # 1. Una classe: max 1 materia per slot
        for c in classi:
            for (g, h) in slot:
                vars_slot = [teach[k] for k in teach if k[1] == c and k[3] == g and k[4] == h]
                if vars_slot:
                    model.Add(sum(vars_slot) <= 1)

        # 2. Un professore: max 1 classe per slot
        for p in professori:
            for (g, h) in slot:
                vars_slot = [teach[k] for k in teach if k[0] == p and k[3] == g and k[4] == h]
                if vars_slot:
                    model.Add(sum(vars_slot) <= 1)

        # 3. VINCOLO DADA: Un'aula può ospitare solo una classe per slot
        # Raggruppa professori per aula
        aule = {}
        for p, info in professori.items():
            aula = info.get("aula", f"Aula_{p}")
            if aula not in aule:
                aule[aula] = []
            aule[aula].append(p)

        # Per ogni aula, per ogni slot, massimo una lezione
        for aula, profs in aule.items():
            for (g, h) in slot:
                vars_aula = [teach[k] for k in teach 
                           if k[0] in profs and k[3] == g and k[4] == h]
                if vars_aula:
                    model.Add(sum(vars_aula) <= 1)

        # 4. Ore richieste per materia/classe
        for c in classi:
            for s, ore_richieste in materie.items():
                vars_ms = [teach[k] for k in teach if k[1] == c and k[2] == s]
                if not vars_ms:
                    return RisultatoOrario(
                        False, "MATERIA_SENZA_PROFESSORE",
                        messaggio=f"Nessun professore per {s} in {c}"
                    )
                model.Add(sum(vars_ms) == ore_richieste)

        # 5. Un solo titolare per materia/classe
        for c in classi:
            for s in materie:
                prof_qualificati = [p for p, info in professori.items() if s in info["materie"]]
                if not prof_qualificati:
                    continue
                
                prof_vars = []
                for p in prof_qualificati:
                    if (p, c, s) in assigned:
                        prof_vars.append(assigned[(p, c, s)])
                
                if prof_vars:
                    model.Add(sum(prof_vars) == 1)
                    
                    for p in prof_qualificati:
                        if (p, c, s) in assigned:
                            ore_p = [teach[(p, c, s, g, h)] for (g, h) in slot if (p, c, s, g, h) in teach]
                            for var_ora in ore_p:
                                model.Add(var_ora <= assigned[(p, c, s)])

        # 6. Ore massime per professore
        for p, info in professori.items():
            vars_p = [teach[k] for k in teach if k[0] == p]
            if vars_p:
                model.Add(sum(vars_p) <= info["max_ore"])

        # 7. Limite di ore consecutive DELLA STESSA MATERIA per classe (max 2)
        for c in classi:
            for s in materie:
                for g in giorni:
                    for h in range(ore_per_giorno - 2):
                        vars_consecutive = [teach[k] for k in teach
                                          if k[1] == c and k[2] == s and k[3] == g and k[4] in [h, h+1, h+2]]
                        if vars_consecutive:
                            model.Add(sum(vars_consecutive) <= 2)

        # 8. Preferenze soft: massimizza le lezioni che cadono nel giorno
        #    preferito del professore e/o dell'aula (non sono vincoli rigidi,
        #    quindi se non sono soddisfacibili l'orario si genera comunque).
        termini_obiettivo = []
        for (p, c, s, g, h), var in teach.items():
            peso = 0
            giorno_pref_prof = professori[p].get("giorno_preferito")
            if giorno_pref_prof and g == giorno_pref_prof:
                peso += 1
            aula_p = professori[p].get("aula", f"Aula_{p}")
            giorno_pref_aula = aule_preferenze.get(aula_p)
            if giorno_pref_aula and g == giorno_pref_aula:
                peso += 1
            if peso > 0:
                termini_obiettivo.append(peso * var)

        if termini_obiettivo:
            model.Maximize(sum(termini_obiettivo))
            logger.info(f"Preferenze soft attive su {len(termini_obiettivo)} variabili")

        # Configura solver
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = tempo_max_sec
        solver.parameters.num_search_workers = 1
        solver.parameters.log_search_progress = False
        solver.parameters.enumerate_all_solutions = False
        solver.parameters.linearization_level = 2
        solver.parameters.cp_model_presolve = True

        logger.info("Avvio solver...")
        status = solver.Solve(model)

        logger.info(f"Solver completato. Status: {solver.StatusName(status)}")
        logger.info(f"Tempo impiegato: {solver.WallTime():.2f}s")

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return RisultatoOrario(
                False,
                solver.StatusName(status),
                messaggio=f"Nessuna soluzione trovata in {tempo_max_sec}s.\n"
                          f"Status: {solver.StatusName(status)}\n"
                          f"💡 Aumenta il tempo o aggiungi più professori/aule."
            )

        # Costruisci orario
        orario = defaultdict(dict)
        for (p, c, s, g, h), var in teach.items():
            if solver.Value(var):
                aula = professori[p].get("aula", f"Aula_{p}")
                orario[c][(g, h)] = f"{s} ({p}) [Aula: {aula}]"

        logger.info(f"Orario generato per {len(orario)} classi")
        messaggio_ok = ""
        if termini_obiettivo:
            messaggio_ok = f"Preferenze soddisfatte: {int(solver.ObjectiveValue())} (punteggio)"
            logger.info(messaggio_ok)
        return RisultatoOrario(True, solver.StatusName(status), orario=dict(orario), messaggio=messaggio_ok)

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        logger.error(f"Errore OR-Tools: {error_msg}")
        return RisultatoOrario(
            False, "ERRORE_ORTOOLS",
            messaggio=f"Errore con OR-Tools: {str(e)}\nUsa la modalità Greedy."
        )


def genera_orario(professori, classi, materie, giorni=None, ore_per_giorno=5,
                   tempo_max_sec=30, num_worker=1, modalita="greedy", aule_preferenze=None):
    """
    Genera l'orario usando la modalità selezionata.
    
    modalita: "greedy" o "ortools"
    aule_preferenze: dict {aula: giorno_preferito}, opzionale
    """
    if modalita == "ortools":
        return genera_orario_ortools(professori, classi, materie, giorni, ore_per_giorno,
                                      tempo_max_sec, aule_preferenze=aule_preferenze)
    else:
        return genera_orario_greedy(professori, classi, materie, giorni, ore_per_giorno,
                                     tentativi=tempo_max_sec, aule_preferenze=aule_preferenze)